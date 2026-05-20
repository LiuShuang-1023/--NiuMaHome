"""SQLite 会话数据库 (v0.3.0)

存储一次搜索会话的全部数据：
- sessions:  会话元信息 + 目的地 geocode 缓存
- listings:  抓取到的房源（含 geo / 距离 / 是否被粗筛过滤）
- commutes:  通勤数据（offline 估算 / amap-baidu 精算）
- costs:     成本测算

关键设计：
1. 所有表都带 session_id，FK ON DELETE CASCADE，删 session 自动连带删
2. 用 sqlite3 stdlib，不引 SQLAlchemy（依赖 + 学习成本低）
3. 写操作单连接 + 锁，读操作每次新建短连接（asyncio 友好）
4. WAL 模式，读写不互斥
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from app.models import (
    CommuteSummary,
    CostBreakdown,
    Listing,
    ParsedRequirement,
)

# 数据库路径
DB_DIR = Path(__file__).parent.parent.parent.parent / "data"
DB_PATH = DB_DIR / "sessions.db"

# 会话 TTL（秒）—— 超过则被定时任务清理
SESSION_TTL_SECONDS = 30 * 60  # 30 分钟


# ============================================================
# DDL
# ============================================================
SCHEMA_DDL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    created_at   INTEGER NOT NULL,
    last_active  INTEGER NOT NULL,
    requirement  TEXT NOT NULL,
    dest_lng     REAL,
    dest_lat     REAL,
    dest_label   TEXT,
    geo_radius_km REAL              -- 粗筛半径（按 max_minutes × 0.4 算）
);

CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(last_active);

CREATE TABLE IF NOT EXISTS listings (
    session_id      TEXT NOT NULL,
    listing_id      TEXT NOT NULL,
    platform        TEXT NOT NULL,
    title           TEXT,
    community       TEXT,
    address         TEXT,
    url             TEXT,
    price_base      INTEGER,
    area            REAL,
    layout          TEXT,
    floor           TEXT,
    orientation     TEXT,
    rental_type_tag TEXT,
    image_url       TEXT,
    raw_json        TEXT NOT NULL,    -- 完整 Listing JSON
    geo_lng         REAL,
    geo_lat         REAL,
    geo_source      TEXT,
    geo_hit_addr    TEXT,             -- 命中的 fallback 候选地址
    distance_km     REAL,
    is_filtered_out INTEGER DEFAULT 0,-- 1=被粗筛过滤
    filter_reason   TEXT,
    PRIMARY KEY (session_id, listing_id),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_listings_session ON listings(session_id, distance_km);

CREATE TABLE IF NOT EXISTS commutes (
    session_id           TEXT NOT NULL,
    listing_id           TEXT NOT NULL,
    source               TEXT NOT NULL,    -- 'offline' / 'amap' / 'baidu'
    best_duration_min    INTEGER,
    transit_min          INTEGER,
    riding_min           INTEGER,
    walking_min          INTEGER,
    driving_min          INTEGER,
    raw_json             TEXT NOT NULL,    -- CommuteSummary JSON
    computed_at          INTEGER NOT NULL,
    PRIMARY KEY (session_id, listing_id),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS costs (
    session_id  TEXT NOT NULL,
    listing_id  TEXT NOT NULL,
    total       INTEGER NOT NULL,
    raw_json    TEXT NOT NULL,
    PRIMARY KEY (session_id, listing_id),
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
"""


# ============================================================
# 工具
# ============================================================
def _now() -> int:
    return int(time.time())


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


# ============================================================
# 数据库主类
# ============================================================
class SessionDB:
    """单实例，封装所有 DB 操作"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._write_lock = threading.Lock()
        self._initialized = False

    def init(self):
        """初始化 DB（创建表 / 启用 WAL）"""
        if self._initialized:
            return
        DB_DIR.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA_DDL)
            conn.commit()
        self._initialized = True
        logger.info(f"✅ SQLite 已初始化: {self.db_path}")

    @contextmanager
    def _connect(self):
        """短连接上下文管理器（asyncio 安全：每次新建）"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=10.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
        finally:
            conn.close()

    # ============================================================
    # session
    # ============================================================
    def upsert_session(
        self,
        session_id: str,
        requirement: ParsedRequirement,
        dest_lng: Optional[float] = None,
        dest_lat: Optional[float] = None,
        dest_label: str = "",
        geo_radius_km: Optional[float] = None,
    ):
        """创建或更新 session（last_active 自动刷新）"""
        now = _now()
        req_json = requirement.model_dump_json()
        with self._write_lock, self._connect() as conn:
            conn.execute("""
                INSERT INTO sessions (session_id, created_at, last_active, requirement,
                                     dest_lng, dest_lat, dest_label, geo_radius_km)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_active = excluded.last_active,
                    requirement = excluded.requirement,
                    dest_lng = excluded.dest_lng,
                    dest_lat = excluded.dest_lat,
                    dest_label = excluded.dest_label,
                    geo_radius_km = excluded.geo_radius_km
            """, (session_id, now, now, req_json, dest_lng, dest_lat, dest_label, geo_radius_km))
            conn.commit()

    def touch_session(self, session_id: str):
        """更新 session 的 last_active 时间（每次请求调用）"""
        now = _now()
        with self._write_lock, self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET last_active = ? WHERE session_id = ?",
                (now, session_id),
            )
            conn.commit()

    def get_session(self, session_id: str) -> Optional[dict]:
        """读取 session 元信息"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            return _row_to_dict(row) if row else None

    def session_exists(self, session_id: str) -> bool:
        return self.get_session(session_id) is not None

    def delete_session(self, session_id: str) -> int:
        """删除整个会话（连带 listings/commutes/costs）"""
        with self._write_lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM sessions WHERE session_id = ?", (session_id,)
            )
            conn.commit()
            return cur.rowcount

    def cleanup_expired(self, ttl_seconds: int = SESSION_TTL_SECONDS) -> int:
        """清理超过 TTL 的会话"""
        threshold = _now() - ttl_seconds
        with self._write_lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM sessions WHERE last_active < ?", (threshold,)
            )
            conn.commit()
            return cur.rowcount

    # ============================================================
    # listings
    # ============================================================
    def upsert_listings(self, session_id: str, listings: list[Listing]):
        """批量写入 listings（覆盖更新）"""
        if not listings:
            return
        rows = []
        for l in listings:
            image_url = l.images[0] if l.images else None
            rows.append((
                session_id, l.id, l.platform.value if hasattr(l.platform, "value") else str(l.platform),
                l.title, l.community, l.address, l.url,
                l.price_base, l.area, l.layout, l.floor, l.orientation,
                l.rental_type_tag, image_url,
                l.model_dump_json(),
                l.geo_lng, l.geo_lat,
                None, None,                   # geo_source / geo_hit_addr 后续 update
                None,                          # distance_km
                0, None,                       # is_filtered_out / filter_reason
            ))
        with self._write_lock, self._connect() as conn:
            conn.executemany("""
                INSERT INTO listings (
                    session_id, listing_id, platform, title, community, address, url,
                    price_base, area, layout, floor, orientation, rental_type_tag, image_url,
                    raw_json, geo_lng, geo_lat, geo_source, geo_hit_addr,
                    distance_km, is_filtered_out, filter_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, listing_id) DO UPDATE SET
                    title = excluded.title,
                    community = excluded.community,
                    address = excluded.address,
                    price_base = excluded.price_base,
                    area = excluded.area,
                    layout = excluded.layout,
                    floor = excluded.floor,
                    orientation = excluded.orientation,
                    rental_type_tag = excluded.rental_type_tag,
                    image_url = excluded.image_url,
                    raw_json = excluded.raw_json
            """, rows)
            conn.commit()

    def update_listing_geo(
        self,
        session_id: str,
        listing_id: str,
        lng: Optional[float],
        lat: Optional[float],
        source: Optional[str],
        hit_addr: Optional[str],
        distance_km: Optional[float],
    ):
        """更新单条房源的 geocode 结果"""
        with self._write_lock, self._connect() as conn:
            conn.execute("""
                UPDATE listings
                SET geo_lng = ?, geo_lat = ?, geo_source = ?,
                    geo_hit_addr = ?, distance_km = ?
                WHERE session_id = ? AND listing_id = ?
            """, (lng, lat, source, hit_addr, distance_km, session_id, listing_id))
            conn.commit()

    def update_listing_filter(
        self,
        session_id: str,
        listing_id: str,
        is_filtered_out: bool,
        reason: str = "",
    ):
        """标记房源是否被粗筛过滤"""
        with self._write_lock, self._connect() as conn:
            conn.execute("""
                UPDATE listings
                SET is_filtered_out = ?, filter_reason = ?
                WHERE session_id = ? AND listing_id = ?
            """, (1 if is_filtered_out else 0, reason, session_id, listing_id))
            conn.commit()

    def list_listings(
        self,
        session_id: str,
        include_filtered: bool = False,
    ) -> list[dict]:
        """读取 session 下所有房源（带 geo / 距离 / 过滤标记）"""
        sql = "SELECT * FROM listings WHERE session_id = ?"
        if not include_filtered:
            sql += " AND is_filtered_out = 0"
        with self._connect() as conn:
            rows = conn.execute(sql, (session_id,)).fetchall()
            return [_row_to_dict(r) for r in rows]

    def get_listing(self, session_id: str, listing_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM listings WHERE session_id = ? AND listing_id = ?",
                (session_id, listing_id),
            ).fetchone()
            return _row_to_dict(row) if row else None

    def count_filter_stats(self, session_id: str) -> dict:
        """粗筛统计：总数 / 已 geocode / 在范围内 / 超出范围"""
        with self._connect() as conn:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN geo_lng IS NOT NULL THEN 1 ELSE 0 END) as geocoded,
                    SUM(CASE WHEN is_filtered_out = 0 THEN 1 ELSE 0 END) as within_radius,
                    SUM(CASE WHEN is_filtered_out = 1 THEN 1 ELSE 0 END) as out_of_radius
                FROM listings
                WHERE session_id = ?
            """, (session_id,)).fetchone()
            d = _row_to_dict(row) if row else {}
            return {
                "total": d.get("total", 0) or 0,
                "geocoded": d.get("geocoded", 0) or 0,
                "geocode_failed": (d.get("total", 0) or 0) - (d.get("geocoded", 0) or 0),
                "within_radius": d.get("within_radius", 0) or 0,
                "out_of_radius": d.get("out_of_radius", 0) or 0,
            }

    # ============================================================
    # commutes
    # ============================================================
    def upsert_commute(
        self,
        session_id: str,
        listing_id: str,
        summary: CommuteSummary,
        source: str,  # 'offline' / 'amap' / 'baidu'
    ):
        """写入或覆盖通勤数据"""
        # 提取各模式分钟数（取最快）
        per_mode: dict[str, int] = {}
        for r in summary.results:
            mode = r.mode.value if hasattr(r.mode, "value") else str(r.mode)
            if mode not in per_mode or r.duration_min < per_mode[mode]:
                per_mode[mode] = r.duration_min

        with self._write_lock, self._connect() as conn:
            conn.execute("""
                INSERT INTO commutes (
                    session_id, listing_id, source, best_duration_min,
                    transit_min, riding_min, walking_min, driving_min,
                    raw_json, computed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, listing_id) DO UPDATE SET
                    source = excluded.source,
                    best_duration_min = excluded.best_duration_min,
                    transit_min = excluded.transit_min,
                    riding_min = excluded.riding_min,
                    walking_min = excluded.walking_min,
                    driving_min = excluded.driving_min,
                    raw_json = excluded.raw_json,
                    computed_at = excluded.computed_at
            """, (
                session_id, listing_id, source, summary.best_duration_min,
                per_mode.get("transit"), per_mode.get("riding"),
                per_mode.get("walking"), per_mode.get("driving"),
                summary.model_dump_json(), _now(),
            ))
            conn.commit()

    def get_commute(self, session_id: str, listing_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM commutes WHERE session_id = ? AND listing_id = ?",
                (session_id, listing_id),
            ).fetchone()
            return _row_to_dict(row) if row else None

    def list_commutes(self, session_id: str) -> dict[str, dict]:
        """返回 {listing_id: commute_row_dict}"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM commutes WHERE session_id = ?", (session_id,)
            ).fetchall()
            return {r["listing_id"]: _row_to_dict(r) for r in rows}

    def count_commute_sources(self, session_id: str) -> dict:
        """统计 source 分布"""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT source, COUNT(*) as n FROM commutes
                WHERE session_id = ? GROUP BY source
            """, (session_id,)).fetchall()
            d = {"offline": 0, "amap": 0, "baidu": 0}
            for r in rows:
                d[r["source"]] = r["n"]
            d["total"] = sum(d.values())
            d["precise"] = d["amap"] + d["baidu"]  # 精算总数
            return d

    # ============================================================
    # costs
    # ============================================================
    def upsert_costs(self, session_id: str, costs: dict[str, CostBreakdown]):
        """批量写入成本"""
        if not costs:
            return
        rows = [
            (session_id, lid, c.total, c.model_dump_json())
            for lid, c in costs.items()
        ]
        with self._write_lock, self._connect() as conn:
            conn.executemany("""
                INSERT INTO costs (session_id, listing_id, total, raw_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id, listing_id) DO UPDATE SET
                    total = excluded.total, raw_json = excluded.raw_json
            """, rows)
            conn.commit()

    def list_costs(self, session_id: str) -> dict[str, dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM costs WHERE session_id = ?", (session_id,)
            ).fetchall()
            return {r["listing_id"]: _row_to_dict(r) for r in rows}

    # ============================================================
    # 调试 / 统计
    # ============================================================
    def get_stats(self) -> dict:
        """全局统计：会话数 / 房源总数等"""
        with self._connect() as conn:
            sessions = conn.execute("SELECT COUNT(*) as n FROM sessions").fetchone()["n"]
            listings = conn.execute("SELECT COUNT(*) as n FROM listings").fetchone()["n"]
            commutes = conn.execute("SELECT COUNT(*) as n FROM commutes").fetchone()["n"]
            return {
                "sessions": sessions,
                "listings": listings,
                "commutes": commutes,
                "db_path": str(self.db_path),
            }


# 全局单例
session_db = SessionDB()


def init_db():
    """供 FastAPI lifespan 调用"""
    session_db.init()

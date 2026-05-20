"""
每日缓存数据库（daily_cache.py）

职责：
  缓存当日爬取的房源列表 和 地址Geocode坐标结果，避免同一天内重复调用。
  通勤数据不在此处缓存——通勤统一由 commute_store.py 管理（永久库）。

表：
  cache_listings  —— (city+district+价格档+platform) → 已抓取房源JSON列表
  cache_geocode   —— (city+address+provider)         → 坐标(lng,lat,level)

TTL：按 cache_date 字段（YYYY-MM-DD），每次启动时自动清掉前日数据。
"""

import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from loguru import logger

_CACHE_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "daily_cache.db"
_CACHE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_SCHEMA_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS cache_listings (
    cache_key     TEXT NOT NULL,
    platform      TEXT NOT NULL,
    listing_id    TEXT NOT NULL,
    raw_json      TEXT NOT NULL,
    cache_date    TEXT NOT NULL,
    cached_at     INTEGER NOT NULL,
    PRIMARY KEY (cache_key, listing_id)
);
CREATE INDEX IF NOT EXISTS idx_cl_date ON cache_listings(cache_date);
CREATE INDEX IF NOT EXISTS idx_cl_key  ON cache_listings(cache_key);

CREATE TABLE IF NOT EXISTS cache_geocode (
    city          TEXT NOT NULL,
    address       TEXT NOT NULL,
    provider      TEXT NOT NULL DEFAULT 'amap',
    lng           REAL NOT NULL,
    lat           REAL NOT NULL,
    level         TEXT,
    hit_addr      TEXT,
    cache_date    TEXT NOT NULL,
    cached_at     INTEGER NOT NULL,
    PRIMARY KEY (city, address, provider)
);
CREATE INDEX IF NOT EXISTS idx_cg_date ON cache_geocode(cache_date);
"""


def _today() -> str:
    return date.today().isoformat()


def _now_ts() -> int:
    return int(datetime.now().timestamp())


class DailyCache:
    """每日缓存（房源 + Geocode，线程安全，WAL 模式）"""

    def __init__(self, db_path: Path = _CACHE_DB_PATH):
        self._db_path = db_path
        self._write_lock = threading.Lock()
        self._init_db()
        self._cleanup_old_dates()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._write_lock:
            with self._connect() as conn:
                conn.executescript(_SCHEMA_DDL)
        logger.info(f"[daily_cache] 初始化完成: {self._db_path}")

    def _cleanup_old_dates(self):
        today = _today()
        with self._write_lock:
            with self._connect() as conn:
                for table in ("cache_listings", "cache_geocode"):
                    result = conn.execute(
                        f"DELETE FROM {table} WHERE cache_date < ?", (today,)
                    )
                    if result.rowcount > 0:
                        logger.info(f"[daily_cache] 清理旧日缓存 {table}: {result.rowcount} 条")

    def cleanup_today(self):
        """手动强制清理今日缓存（测试用）"""
        today = _today()
        with self._write_lock:
            with self._connect() as conn:
                for table in ("cache_listings", "cache_geocode"):
                    conn.execute(f"DELETE FROM {table} WHERE cache_date = ?", (today,))
        logger.info("[daily_cache] 已清理今日全部缓存")

    # ── 房源缓存 ──────────────────────────────────────────
    def get_listings(self, cache_key: str) -> Optional[list[str]]:
        today = _today()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT raw_json FROM cache_listings WHERE cache_key=? AND cache_date=? ORDER BY listing_id",
                (cache_key, today),
            ).fetchall()
        if rows:
            logger.info(f"[daily_cache] 房源缓存命中 {cache_key}: {len(rows)} 条")
            return [r["raw_json"] for r in rows]
        return None

    def save_listings(self, cache_key: str, platform: str, raw_jsons: list[tuple[str, str]]):
        if not raw_jsons:
            return
        today = _today()
        ts = _now_ts()
        with self._write_lock:
            with self._connect() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO cache_listings (cache_key,platform,listing_id,raw_json,cache_date,cached_at) VALUES (?,?,?,?,?,?)",
                    [(cache_key, platform, lid, rj, today, ts) for lid, rj in raw_jsons],
                )
        logger.info(f"[daily_cache] 房源缓存写入 {cache_key}: {len(raw_jsons)} 条")

    def listing_cache_key(self, city: str, district: str, price_tag: str, platform: str) -> str:
        return f"{city}|{district or '全市'}|{price_tag}|{platform}"

    # ── Geocode 缓存 ─────────────────────────────────────
    def get_geocode(
        self, city: str, address: str, provider: str = "amap"
    ) -> Optional[tuple[float, float, Optional[str], Optional[str]]]:
        today = _today()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT lng,lat,level,hit_addr FROM cache_geocode WHERE city=? AND address=? AND provider=? AND cache_date=?",
                (city, address, provider, today),
            ).fetchone()
        if row:
            logger.debug(f"[daily_cache] geocode 缓存命中: {city} {address}")
            return row["lng"], row["lat"], row["level"], row["hit_addr"]
        return None

    def save_geocode(self, city: str, address: str, lng: float, lat: float,
                     level: Optional[str] = None, hit_addr: Optional[str] = None,
                     provider: str = "amap"):
        today = _today()
        ts = _now_ts()
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO cache_geocode (city,address,provider,lng,lat,level,hit_addr,cache_date,cached_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (city, address, provider, lng, lat, level, hit_addr, today, ts),
                )
        logger.debug(f"[daily_cache] geocode 缓存写入: {city} {address}")

    # ── 统计 ─────────────────────────────────────────────
    def stats(self) -> dict:
        today = _today()
        with self._connect() as conn:
            l = conn.execute("SELECT COUNT(*) FROM cache_listings WHERE cache_date=?", (today,)).fetchone()[0]
            g = conn.execute("SELECT COUNT(*) FROM cache_geocode WHERE cache_date=?", (today,)).fetchone()[0]
        return {"date": today, "listings": l, "geocode": g}


daily_cache = DailyCache()

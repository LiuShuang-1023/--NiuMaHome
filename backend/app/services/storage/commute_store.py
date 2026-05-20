"""
永久通勤知识库（commute_store.py）v0.3.2

职责：
  永久保存用户精算过的通勤数据，越用越准。
  提供三档数据质量：
    - 稳定基准（is_stable=1）：样本≥3次且近7天内波动系数CV<规定阈值 → 固化，精算时直接跳过API
    - 普通基准（is_stable=0）：有历史数据但尚未稳定 → 估算时优先使用，比离线公式准
    - 无数据：降级到离线公式估算

固化阈值（按交通模式区分）：
  - 步行 / 骑行：样本≥3 且 CV < 10%（速度稳定，变化少）
  - 公交 / 地铁：样本≥5 且 CV < 20%（峰值差异大，需更多样本）

7日滚动均值逻辑：
  每天00:00触发 daily_update()，对最近7天的精算记录分组计算均值 → 更新 commute_baseline。
  同时检查是否满足固化条件 → 更新 is_stable 字段。
  超过7天的原始精算记录删除（均值已吸收原始值）。

地址归一化（_normalize_key）：
  取地址最后2-4个核心汉字，去掉城市/区级前缀 + 租房前缀。
  目的：让"广州番禺区南村万博商务区"和"南村万博"命中同一条 baseline。

表结构：
  commute_precise  —— 每次精算一条原始记录（保留最近7天）
  commute_baseline —— 7日均值 + 稳定标记（永久保留）
"""

import re
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger

_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "commute_store.db"
_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_SCHEMA_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS commute_precise (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    origin_key    TEXT NOT NULL,
    dest_key      TEXT NOT NULL,
    mode          TEXT NOT NULL,
    duration_min  INTEGER NOT NULL,
    provider      TEXT NOT NULL,
    measured_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cp_keys ON commute_precise(origin_key, dest_key, mode);
CREATE INDEX IF NOT EXISTS idx_cp_time ON commute_precise(measured_at);

CREATE TABLE IF NOT EXISTS commute_baseline (
    origin_key    TEXT NOT NULL,
    dest_key      TEXT NOT NULL,
    mode          TEXT NOT NULL,
    baseline_min  REAL NOT NULL,
    sample_count  INTEGER NOT NULL DEFAULT 0,
    cv            REAL NOT NULL DEFAULT 1.0,   -- 变异系数（标准差/均值），越小越稳定
    is_stable     INTEGER NOT NULL DEFAULT 0,  -- 1=已固化，精算时跳过API
    week_start    TEXT NOT NULL,
    updated_at    INTEGER NOT NULL,
    PRIMARY KEY (origin_key, dest_key, mode)
);
CREATE INDEX IF NOT EXISTS idx_cb_keys ON commute_baseline(origin_key, dest_key);

CREATE TABLE IF NOT EXISTS commute_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# 固化阈值：(最小样本数, 最大CV)
_STABLE_THRESHOLD: dict[str, tuple[int, float]] = {
    "walking": (3, 0.10),
    "riding":  (3, 0.10),
    "transit": (5, 0.20),
    "driving": (5, 0.20),
}


def _normalize_key(raw: str) -> str:
    """提取地址中最后2-4个核心汉字作为标准化key。

    原则：去掉所有行政区划前缀（城市/区县）和租房业务前缀（整租/合租），
    只保留小区/地标核心词。

    示例：
      "广州番禺区南村万博商务区" → "南村万博商务区"（取最后核心词）
      "整租·珠江新城天汇广场" → "珠江新城天汇广场"
      "合租 碧桂园凤凰城三期" → "碧桂园凤凰城三期"
    """
    s = raw.strip().lower()
    # 去掉租房前缀（整租/合租/独栋等 + 分隔符）
    s = re.sub(r'^(整租|合租|独栋|独租|单间)[·・\-\s]+', '', s)
    # 去掉 省/直辖市 前缀
    s = re.sub(r'^(广东|北京|上海|浙江|四川|湖北|江苏|天津|重庆)(省|市)?', '', s)
    # 去掉 城市 前缀
    s = re.sub(r'^(广州|深圳|北京|上海|杭州|成都|武汉|南京|天津|重庆)(市)?', '', s)
    # 去掉 区/县 前缀（2-4字的区名）
    s = re.sub(r'^[\u4e00-\u9fff]{2,4}(区|县|新区|开发区)', '', s)
    # 压缩空白
    s = re.sub(r'\s+', '', s)
    return s or raw.strip().lower()


def _cv(values: list[float]) -> float:
    """计算变异系数 CV = 标准差 / 均值（越小表示数据越稳定）"""
    if len(values) < 2:
        return 0.0
    n = len(values)
    mean = sum(values) / n
    if mean == 0:
        return 0.0
    variance = sum((x - mean) ** 2 for x in values) / n
    return (variance ** 0.5) / mean


class CommuteStore:
    """永久通勤知识库（线程安全，WAL 模式）"""

    def __init__(self, db_path: Path = _DB_PATH):
        self._db_path = db_path
        self._write_lock = threading.Lock()
        self._init_db()
        logger.info(
            f"[commute_store] 就绪: {db_path.name} | "
            f"精算={self._count('commute_precise')} | "
            f"基准={self._count('commute_baseline')} | "
            f"已固化={self._count_stable()}"
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._write_lock:
            with self._connect() as conn:
                conn.executescript(_SCHEMA_DDL)
                # 兼容旧版本：补充新字段（已有表时 ALTER TABLE）
                for col, default in [("cv", "1.0"), ("is_stable", "0")]:
                    try:
                        conn.execute(f"ALTER TABLE commute_baseline ADD COLUMN {col} REAL NOT NULL DEFAULT {default}")
                    except Exception:
                        pass  # 字段已存在，忽略

    def _count(self, table: str) -> int:
        with self._connect() as conn:
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def _count_stable(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM commute_baseline WHERE is_stable=1").fetchone()[0]

    # ── 元数据：记录上次 daily_update 日期，防止重复跑 ──
    def _get_meta(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute("SELECT value FROM commute_meta WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None

    def _set_meta(self, key: str, value: str):
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO commute_meta (key,value) VALUES (?,?)", (key, value)
            )

    # ── 写入精算原始记录 ──────────────────────────────────
    def record_precise(
        self,
        origin: str,
        dest: str,
        mode: str,
        duration_min: int,
        provider: str,
    ):
        """精算成功后调用，写入原始记录。由 map/engine.py 调用。"""
        ok = _normalize_key(origin)
        dk = _normalize_key(dest)
        ts = int(datetime.now().timestamp())
        with self._write_lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO commute_precise (origin_key,dest_key,mode,duration_min,provider,measured_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (ok, dk, mode, duration_min, provider, ts),
                )
        logger.debug(f"[commute_store] 精算: {ok}→{dk} ({mode}) = {duration_min}min")

    # ── 查询基准线（估算时调用）──────────────────────────
    def get_baseline(self, origin: str, dest: str, mode: str) -> Optional[tuple[float, int]]:
        """返回 (baseline_min, sample_count)；未命中返回 None。
        用于 offline_estimator：有历史精算均值时替代离线公式。
        """
        ok = _normalize_key(origin)
        dk = _normalize_key(dest)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT baseline_min, sample_count FROM commute_baseline WHERE origin_key=? AND dest_key=? AND mode=?",
                (ok, dk, mode),
            ).fetchone()
        if row:
            logger.debug(f"[commute_store] baseline命中: {ok}→{dk} ({mode}) = {row['baseline_min']:.1f}min n={row['sample_count']}")
            return row["baseline_min"], row["sample_count"]
        return None

    def get_stable_baseline(self, origin: str, dest: str) -> Optional[dict[str, tuple[float, int]]]:
        """返回已固化路线的所有交通模式 {mode: (baseline_min, sample_count)}。
        仅返回 is_stable=1 的记录。用于 engine.py：固化路线跳过 API 调用。
        """
        ok = _normalize_key(origin)
        dk = _normalize_key(dest)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT mode, baseline_min, sample_count FROM commute_baseline "
                "WHERE origin_key=? AND dest_key=? AND is_stable=1",
                (ok, dk),
            ).fetchall()
        if rows:
            return {r["mode"]: (r["baseline_min"], r["sample_count"]) for r in rows}
        return None

    def get_all_baselines(self, origin: str, dest: str) -> dict[str, tuple[float, int]]:
        """返回所有交通模式的基准线（含未固化）{mode: (baseline_min, sample_count)}"""
        ok = _normalize_key(origin)
        dk = _normalize_key(dest)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT mode, baseline_min, sample_count FROM commute_baseline WHERE origin_key=? AND dest_key=?",
                (ok, dk),
            ).fetchall()
        return {r["mode"]: (r["baseline_min"], r["sample_count"]) for r in rows}

    # ── 每日任务 ─────────────────────────────────────────
    def needs_daily_update(self) -> bool:
        """检查今天是否已执行过 daily_update（用 last_run_date 标记，防重复）"""
        last = self._get_meta("last_run_date")
        return last != date.today().isoformat()

    def daily_update(self) -> dict:
        """每天00:00执行一次（由 main.py 后台任务调用）。
        1. 对最近7天精算记录分组求均值 → 更新 commute_baseline
        2. 计算CV，满足固化条件的路线标记 is_stable=1
        3. 删掉7天前的原始精算记录
        4. 记录 last_run_date 防重复执行
        """
        today = date.today().isoformat()
        if not self.needs_daily_update():
            logger.info(f"[commute_store] daily_update 今日已执行，跳过")
            return {"skipped": True}

        cutoff_ts = int((datetime.now() - timedelta(days=7)).timestamp())
        week_start = (date.today() - timedelta(days=6)).isoformat()
        today_ts = int(datetime.now().timestamp())
        stats = {"baselines_updated": 0, "newly_stable": 0, "old_precise_deleted": 0}

        with self._write_lock:
            with self._connect() as conn:
                # Step1: 计算最近7天均值
                rows = conn.execute("""
                    SELECT origin_key, dest_key, mode,
                           AVG(duration_min) AS avg_min,
                           COUNT(*)          AS cnt,
                           GROUP_CONCAT(duration_min) AS raw_values
                    FROM commute_precise
                    WHERE measured_at >= ?
                    GROUP BY origin_key, dest_key, mode
                """, (cutoff_ts,)).fetchall()

                for r in rows:
                    values = [float(v) for v in r["raw_values"].split(",")]
                    cv_val = _cv(values)
                    cnt = r["cnt"]
                    mode = r["mode"]

                    # 判断是否满足固化条件
                    min_samples, max_cv = _STABLE_THRESHOLD.get(mode, (5, 0.15))
                    is_stable = 1 if (cnt >= min_samples and cv_val <= max_cv) else 0

                    conn.execute("""
                        INSERT INTO commute_baseline
                            (origin_key, dest_key, mode, baseline_min, sample_count, cv, is_stable, week_start, updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(origin_key, dest_key, mode) DO UPDATE SET
                            baseline_min  = excluded.baseline_min,
                            sample_count  = excluded.sample_count,
                            cv            = excluded.cv,
                            is_stable     = excluded.is_stable,
                            week_start    = excluded.week_start,
                            updated_at    = excluded.updated_at
                    """, (r["origin_key"], r["dest_key"], mode,
                          r["avg_min"], cnt, cv_val, is_stable,
                          week_start, today_ts))

                    if is_stable:
                        stats["newly_stable"] += 1

                stats["baselines_updated"] = len(rows)

                # Step2: 删掉7天前原始记录
                result = conn.execute(
                    "DELETE FROM commute_precise WHERE measured_at < ?", (cutoff_ts,)
                )
                stats["old_precise_deleted"] = result.rowcount

                # Step3: 标记今日已执行
                conn.execute(
                    "INSERT OR REPLACE INTO commute_meta (key,value) VALUES ('last_run_date',?)",
                    (today,)
                )

        logger.info(f"[commute_store] daily_update 完成: {stats}")
        return stats

    # ── 统计 ─────────────────────────────────────────────
    def stats(self) -> dict:
        with self._connect() as conn:
            precise_count = conn.execute("SELECT COUNT(*) FROM commute_precise").fetchone()[0]
            baseline_count = conn.execute("SELECT COUNT(*) FROM commute_baseline").fetchone()[0]
            stable_count = conn.execute("SELECT COUNT(*) FROM commute_baseline WHERE is_stable=1").fetchone()[0]
            top = conn.execute("""
                SELECT origin_key, dest_key, mode, baseline_min, sample_count, cv, is_stable
                FROM commute_baseline ORDER BY sample_count DESC LIMIT 5
            """).fetchall()
        return {
            "precise_records": precise_count,
            "baseline_routes": baseline_count,
            "stable_routes": stable_count,
            "top_by_samples": [dict(r) for r in top],
        }


commute_store = CommuteStore()

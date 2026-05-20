"""
保障房政策本地缓存  (v0.9.0)

- SQLite 表 housing_policy_cache
- 静态 DB 城市（广州/北京等）：写入时 source='db'，不过期
- AI 生成城市：写入时 source='ai'，超过 120 天（4个月）视为过期，自动重查
- 每次查询时检查是否过期并标注 is_stale=True
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent.parent.parent / "data" / "housing_policy.db"
_STALE_DAYS = 120  # 4 个月


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS housing_policy_cache (
            city        TEXT PRIMARY KEY,
            source      TEXT NOT NULL,          -- 'db' | 'ai'
            payload_json TEXT NOT NULL,          -- PolicyInfoResponse JSON（不含 city/disclaimer）
            fetched_at  TEXT NOT NULL,           -- ISO8601
            updated_at  TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def get_cached(city: str) -> dict | None:
    """
    返回缓存记录，格式：
    { source, payload, fetched_at, updated_at, is_stale }
    找不到返回 None
    """
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM housing_policy_cache WHERE city=?", (city,)
        ).fetchone()
    if not row:
        return None

    fetched_at_str: str = row["fetched_at"]
    fetched_at = datetime.fromisoformat(fetched_at_str)
    is_stale = (
        row["source"] == "ai"
        and (datetime.utcnow() - fetched_at).days >= _STALE_DAYS
    )
    return {
        "source": row["source"],
        "payload": json.loads(row["payload_json"]),
        "fetched_at": fetched_at_str,
        "updated_at": row["updated_at"],
        "is_stale": is_stale,
    }


def save_cache(city: str, source: str, payload: dict) -> str:
    """
    写入/更新缓存，返回写入时间 ISO8601 字符串
    """
    now = datetime.utcnow().isoformat()
    with _conn() as conn:
        existing = conn.execute(
            "SELECT fetched_at FROM housing_policy_cache WHERE city=?", (city,)
        ).fetchone()
        fetched_at = existing["fetched_at"] if existing else now
        conn.execute("""
            INSERT INTO housing_policy_cache (city, source, payload_json, fetched_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(city) DO UPDATE SET
                source=excluded.source,
                payload_json=excluded.payload_json,
                updated_at=excluded.updated_at
        """, (city, source, json.dumps(payload, ensure_ascii=False), fetched_at, now))
        conn.commit()
    return fetched_at


def list_stale_cities() -> list[str]:
    """返回所有 source='ai' 且超过 120 天未更新的城市列表（用于定时自查）"""
    cutoff = (datetime.utcnow() - timedelta(days=_STALE_DAYS)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT city FROM housing_policy_cache WHERE source='ai' AND fetched_at < ?",
            (cutoff,),
        ).fetchall()
    return [r["city"] for r in rows]

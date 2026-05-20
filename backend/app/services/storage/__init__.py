"""SQLite 临时数据库存储 (v0.3.0)

设计目标：
- 替代进程内 _cache 字典，避免跨版本残留 + 调试不可见
- 按 session_id 隔离用户会话，自动 TTL 清理（30 分钟）
- 支持增量更新通勤数据（离线估算 → 用户精算 → 覆盖）

不引入 SQLAlchemy ORM，直接 sqlite3 + 原生 SQL（包小、依赖少、易调试）。
所有表的写操作都通过本模块的函数，外部不直接操作 SQL。
"""
from app.services.storage.session_db import (
    SessionDB,
    session_db,
    init_db,
)

__all__ = ["SessionDB", "session_db", "init_db"]

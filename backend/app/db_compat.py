"""数据库方言的少量差异集中在这里。

目前只有两处：

1. `insert`：共鸣/屏蔽/举报用的是 `INSERT ... ON CONFLICT`，SQLite 与
   PostgreSQL 的 SQLAlchemy 构造器不同，但 `on_conflict_do_*` 的调用形式一致。
2. 旧库补列：`PRAGMA table_info` 只有 SQLite 有。PostgreSQL 没有这条历史包袱
   （schema 由 `create_all` 从当前模型建立），因此迁移只在 SQLite 上执行。

**这不是 ORM 抽象。** 如果将来出现更多方言差异，正确的做法是引入 Alembic，
而不是继续往这里堆 if。
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .database import DATABASE_URL

IS_SQLITE = DATABASE_URL.startswith("sqlite")
IS_POSTGRES = DATABASE_URL.startswith("postgresql")

insert = postgresql_insert if IS_POSTGRES else sqlite_insert

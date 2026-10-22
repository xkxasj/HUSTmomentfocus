from pathlib import Path
import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


DB_PATH = Path(os.getenv("MOUKE_DB_PATH", Path(__file__).with_name("mouke.db")))
DATABASE_URL = os.getenv("MOUKE_DATABASE_URL") or f"sqlite:///{DB_PATH.as_posix()}"


def _engine_options(url: str) -> dict:
    if url.startswith("sqlite"):
        # timeout 与下面的 busy_timeout 配合：并发写入时等待锁，而不是立刻报
        # "database is locked"。
        return {"connect_args": {"check_same_thread": False, "timeout": 15}}
    return {
        "pool_pre_ping": True,
        "pool_size": int(os.getenv("MOUKE_DB_POOL_SIZE", "5")),
        "max_overflow": int(os.getenv("MOUKE_DB_MAX_OVERFLOW", "10")),
    }


engine = create_engine(DATABASE_URL, **_engine_options(DATABASE_URL))


if DATABASE_URL.startswith("sqlite"):
    # SQLite 默认不启用外键、也不开 WAL。前者让模型里的 ForeignKey 变成摆设，
    # 后者让“读不阻塞写”失效。放在 connect 事件里，确保每个新连接都生效。
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _connection_record):  # pragma: no cover - 连接级副作用
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

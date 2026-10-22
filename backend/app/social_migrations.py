"""Idempotent additions for databases created before social workflows existed."""
from datetime import datetime, timedelta
from sqlalchemy import text


def migrate_social(connection):
    additions = {
        "resonances": {"user_id": "INTEGER REFERENCES users(id)"},
        "echoes": {"user_id": "INTEGER REFERENCES users(id)", "is_hidden": "BOOLEAN DEFAULT 0"},
        "conversations": {"status": "VARCHAR(20) DEFAULT 'pending'", "expires_at": "DATETIME",
                          "initiator_read_id": "INTEGER DEFAULT 0", "recipient_read_id": "INTEGER DEFAULT 0"},
        "users": {"failed_login_count": "INTEGER DEFAULT 0", "locked_until": "DATETIME"},
        "verification_codes": {"attempts": "INTEGER DEFAULT 0"},
    }
    for table, fields in additions.items():
        columns = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
        # 空集合说明这张表根本不存在（极旧库/局部测试库）。create_all 已经负责建表，
        # 这里跳过而不是让 ALTER 抛「no such table」。
        if not columns:
            continue
        legacy_conversations = table == "conversations" and "status" not in columns
        for field, sql_type in fields.items():
            if field not in columns:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {field} {sql_type}"))
        if legacy_conversations:
            # Do not invent consent for old conversations. Keep history, ask the recipient again.
            connection.execute(text("UPDATE conversations SET expires_at = :expiry"),
                               {"expiry": datetime.now() + timedelta(hours=24)})
    connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_resonance_user ON resonances(moment_id, user_id)"))

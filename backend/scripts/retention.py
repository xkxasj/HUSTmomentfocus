"""数据保留期清理。

为什么必须有这个脚本：验证码、登录会话、埋点、AI 用量都会无限增长。SQLite 的
体积增长不是最麻烦的，麻烦的是「已经不用的个人数据还留着」——这既是存储成本，
也是隐私面。删除策略写死在代码里，不提供环境变量开关，改保留期走代码评审。

建议每天凌晨跑一次（cron 示例见 docs/OPERATIONS.md）：

    cd backend && .venv/bin/python scripts/retention.py
    cd backend && .venv/bin/python scripts/retention.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 允许 `python scripts/retention.py` 直接运行（sys.path[0] 是 scripts/）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import and_, delete, func, inspect, or_, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AiUsage,
    AnalyticsEvent,
    AuthSession,
    SuggestionFeedback,
    VerificationCode,
)


def tasks(now: datetime):
    return [
        ("过期登录会话", AuthSession, AuthSession.expires_at < now),
        (
            "过期或已用验证码",
            VerificationCode,
            or_(
                VerificationCode.expires_at < now,
                and_(
                    VerificationCode.consumed.is_(True),
                    VerificationCode.created_at < now - timedelta(hours=24),
                ),
            ),
        ),
        ("30 天前 AI 用量", AiUsage, AiUsage.created_at < now - timedelta(days=30)),
        ("90 天前埋点", AnalyticsEvent, AnalyticsEvent.created_at < now - timedelta(days=90)),
        # 表达语料用于个性化，保留太久没有收益；保留半年足够观察模型效果。
        ("180 天前表达反馈", SuggestionFeedback, SuggestionFeedback.created_at < now - timedelta(days=180)),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="清理超过保留期的数据")
    parser.add_argument("--dry-run", action="store_true", help="只统计，不删除")
    args = parser.parse_args()

    now = datetime.now()
    with SessionLocal() as db:
        existing = set(inspect(db.get_bind()).get_table_names())
        for label, model, condition in tasks(now):
            # 旧库可能还没跑过新版本的 lifespan（例如只升级了代码就执行脚本）。
            # 缺表时跳过，而不是让整次清理中断。
            if model.__tablename__ not in existing:
                print(f"{label}: 跳过（表 {model.__tablename__} 不存在）")
                continue
            if args.dry_run:
                count = db.scalar(select(func.count()).select_from(model).where(condition)) or 0
            else:
                count = db.execute(delete(model).where(condition)).rowcount or 0
            print(f"{label}: {count}")
        if not args.dry_run:
            db.commit()
    print("完成" if not args.dry_run else "完成（dry-run，未写入）")


if __name__ == "__main__":
    main()

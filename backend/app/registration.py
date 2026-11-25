"""Optional invite roster for new campus registrations."""
import os
import re

from fastapi import HTTPException


def allowed_student_ids() -> frozenset[str]:
    raw = os.getenv("MOUKE_ALLOWED_STUDENT_IDS", "").strip()
    if not raw:
        return frozenset()
    ids = frozenset(value.strip().upper() for value in raw.split(","))
    if any(re.fullmatch(r"[A-Z0-9]{6,20}", value) is None for value in ids):
        raise RuntimeError("MOUKE_ALLOWED_STUDENT_IDS 必须是以英文逗号分隔的有效学号")
    return ids


def require_registration_invite(student_id: str) -> None:
    allowed = allowed_student_ids()
    if allowed and student_id not in allowed:
        raise HTTPException(403, "当前为受邀内测，该学号暂未开放注册")

from datetime import datetime, timedelta
import hmac
import os
import secrets
import smtplib

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from . import auth_security
from .auth import hash_code, hash_password, send_verification_email
from .database import get_db
from .models import AuthSession, PasswordReset, User
from .schemas import LoginRequest

router = APIRouter(prefix="/api")

class ResetCodeRequest(BaseModel):
    student_id: str = Field(pattern=r"^[A-Za-z0-9]{6,20}$")


class ResetPasswordRequest(LoginRequest):
    code: str = Field(pattern=r"^\d{6}$")

@router.post("/auth/reset-code")
def reset_code(payload: ResetCodeRequest, request: Request, db: Session = Depends(get_db)):
    student_id = payload.student_id.upper()
    auth_security.enforce("reset_code_ip", auth_security.client_ip(request), *auth_security.REQUEST_CODE_IP, message="请稍后再试")
    auth_security.enforce("reset_code_subject", student_id, *auth_security.REQUEST_CODE_SUBJECT, message="请稍后再试")
    result = {"message": "若账号存在且可用，验证码将发送至绑定邮箱", "dev_code": None}
    user = db.scalar(select(User).where(User.student_id == student_id, User.is_active.is_(True)))
    if not user:
        return result
    latest = db.scalar(select(PasswordReset).where(PasswordReset.user_id == user.id).order_by(PasswordReset.id.desc()))
    if latest and latest.created_at > datetime.now() - timedelta(seconds=60):
        return result
    code = f"{secrets.randbelow(1_000_000):06d}"
    db.execute(update(PasswordReset).where(PasswordReset.user_id == user.id).values(consumed=True))
    row = PasswordReset(user_id=user.id, code_hash=hash_code(f"reset:{code}"), expires_at=datetime.now() + timedelta(minutes=10))
    db.add(row)
    db.commit()
    try:
        sent = send_verification_email(user.email, code)
    except (OSError, smtplib.SMTPException):
        sent = False
    if os.getenv("MOUKE_DEV_EMAIL_CODES", "0") == "1":
        result["dev_code"] = code
    elif not sent:
        # Do not reveal account existence through a different response.
        row.consumed = True
        db.commit()
    return result


@router.post("/auth/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    auth_security.enforce("reset_password_ip", auth_security.client_ip(request), *auth_security.LOGIN_IP, message="请稍后再试")
    user = db.scalar(select(User).where(User.student_id == payload.student_id.upper(), User.is_active.is_(True)))
    row = db.scalar(select(PasswordReset).where(PasswordReset.user_id == user.id).order_by(PasswordReset.id.desc())) if user else None
    if not row or row.consumed or row.attempts >= 5 or row.expires_at <= datetime.now():
        raise HTTPException(400, "验证码无效或已过期，请重新获取")
    # Atomic attempt counter and one-time consumption also protect concurrent requests.
    valid = hmac.compare_digest(row.code_hash, hash_code(f"reset:{payload.code}"))
    claimed = db.execute(update(PasswordReset).where(PasswordReset.id == row.id,
        PasswordReset.consumed.is_(False), PasswordReset.attempts < 5,
        PasswordReset.expires_at > datetime.now()).values(
            attempts=PasswordReset.attempts + 1, consumed=valid))
    if not claimed.rowcount or not valid:
        db.commit()
        raise HTTPException(400, "验证码无效或已过期，请重新获取")
    user.password_hash = hash_password(payload.password)
    user.failed_login_count = 0
    user.locked_until = None
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.commit()
    return {"reset": True}

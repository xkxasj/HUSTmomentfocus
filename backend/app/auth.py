import hashlib
import hmac
import os
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import AuthSession, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
DEFAULT_CODE_SECRET = "mouke-local-development-change-me"
CODE_SECRET = os.getenv("MOUKE_CODE_SECRET", DEFAULT_CODE_SECRET)
ALIAS_SECRET = os.getenv("MOUKE_ALIAS_SECRET") or CODE_SECRET
PBKDF2_ITERATIONS = 600_000
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15


def validate_production_config() -> None:
    """生产环境的“失败即拒绝启动”检查。

    这些默认值在本地开发时很方便，一旦原样上公网就是事故：验证码会直接回显、
    验证码哈希可被离线伪造、昵称可被学号反推。与其在运行中悄悄降级，不如让
    进程起不来。
    """
    if os.getenv("MOUKE_ENV", "development").lower() != "production":
        return
    problems: list[str] = []
    if os.getenv("MOUKE_DEV_EMAIL_CODES", "0") == "1":
        problems.append("MOUKE_DEV_EMAIL_CODES 必须为 0")
    if CODE_SECRET == DEFAULT_CODE_SECRET or len(CODE_SECRET) < 32:
        problems.append("MOUKE_CODE_SECRET 必须设置为至少 32 位的随机值")
    if ALIAS_SECRET == DEFAULT_CODE_SECRET or len(ALIAS_SECRET) < 32:
        problems.append("MOUKE_ALIAS_SECRET 必须设置为至少 32 位的随机值")
    if ALIAS_SECRET == CODE_SECRET:
        # 两条密钥各管一件事：一条泄露不应同时让验证码可伪造、昵称可反推。
        problems.append("MOUKE_ALIAS_SECRET 必须与 MOUKE_CODE_SECRET 不同")
    if not os.getenv("MOUKE_SMTP_HOST"):
        problems.append("MOUKE_SMTP_HOST 未配置，生产环境无法发送验证码")
    if problems:
        raise RuntimeError("生产配置不安全：" + "；".join(problems))


def hash_code(code: str) -> str:
    return hashlib.sha256(f"{code}:{CODE_SECRET}".encode()).hexdigest()

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"

def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256": return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (TypeError, ValueError):
        return False

def create_access_token(user: User, db: Session) -> str:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(user_id=user.id, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=datetime.now() + timedelta(days=14)))
    db.commit()
    return token

def get_current_user(token: Annotated[str | None, Depends(oauth2_scheme)], db: Annotated[Session, Depends(get_db)]) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录", headers={"WWW-Authenticate": "Bearer"})
    if not token: raise unauthorized
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_hash, AuthSession.expires_at > datetime.now()))
    if session is None: raise unauthorized
    user = db.get(User, session.user_id)
    if user is None or not user.is_active: raise unauthorized
    return user

def send_verification_email(email: str, code: str) -> bool:
    host = os.getenv("MOUKE_SMTP_HOST")
    if not host: return False
    port = int(os.getenv("MOUKE_SMTP_PORT", "587"))
    username = os.getenv("MOUKE_SMTP_USERNAME")
    password = os.getenv("MOUKE_SMTP_PASSWORD")
    sender = os.getenv("MOUKE_SMTP_FROM", username or "noreply@hust.edu.cn")
    message = EmailMessage()
    message["Subject"] = "某刻校园注册验证码"
    message["From"] = sender
    message["To"] = email
    message.set_content(f"你的某刻校园验证码是：{code}\n\n验证码 10 分钟内有效。请勿转发给他人。")
    client_type = smtplib.SMTP_SSL if os.getenv("MOUKE_SMTP_SSL", "0") == "1" else smtplib.SMTP
    with client_type(host, port, timeout=15) as client:
        if client_type is smtplib.SMTP and os.getenv("MOUKE_SMTP_TLS", "1") == "1": client.starttls()
        if username and password: client.login(username, password)
        client.send_message(message)
    return True

def make_alias(student_id: str) -> str:
    """由学号派生匿名昵称。

    必须带服务端密钥：学号是可枚举的，裸 SHA-256 会让任何人离线算出
    “学号 → 昵称”，匿名就失效了。HMAC 让没有密钥的人无法建立映射。
    """
    adjectives = ["银杏", "晚风", "星光", "湖畔", "青苔", "橘灯", "书页", "云朵"]
    nouns = ["纸船", "松果", "猫", "铅笔", "月亮", "蒲公英", "海盐", "钟摆"]
    digest = hmac.new(ALIAS_SECRET.encode(), student_id.encode(), hashlib.sha256).digest()
    return f"匿名{adjectives[digest[0] % len(adjectives)]}{nouns[digest[1] % len(nouns)]}"


def login_locked(user: User) -> bool:
    return bool(user.locked_until and user.locked_until > datetime.now())


def register_login_failure(user: User, db: Session) -> None:
    user.failed_login_count = (user.failed_login_count or 0) + 1
    if user.failed_login_count >= MAX_FAILED_LOGINS:
        user.locked_until = datetime.now() + timedelta(minutes=LOCK_MINUTES)
        user.failed_login_count = 0
    db.commit()


def register_login_success(user: User, db: Session) -> None:
    if user.failed_login_count or user.locked_until:
        user.failed_login_count = 0
        user.locked_until = None
        db.commit()

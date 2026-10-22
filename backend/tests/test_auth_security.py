"""上线前的认证安全边界。

覆盖四类「默认值一上公网就出事」的行为：生产配置自检、发码/登录限流、
验证码爆破计数、登录锁定，以及注销账号后的身份解除。骨架与 test_ratelimit.py
一致：自建临时库 + dependency_overrides，不跑生产 lifespan。

这里额外调用 auth_security.reset_all()：限流桶是进程内全局状态，不清会让
用例之间互相污染（尤其是按学号计数的那几档）。
"""

import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import auth, auth_security, ratelimit
from app.auth import create_access_token, hash_code, hash_password
from app.database import Base, get_db
from app.main import app
from app.models import (
    AiUsage,
    AuthSession,
    Conversation,
    Location,
    Moment,
    User,
    VerificationCode,
)
from app.seed import seed_database
from app.social_migrations import migrate_social


class AuthSecurityTest(unittest.TestCase):
    def setUp(self):
        auth_security.reset_all()
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{(Path(self.temp.name) / 'security.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.engine.begin() as connection:
            migrate_social(connection)
            migrate_social(connection)
        with self.sessions() as db:
            seed_database(db)
            self.location_id = db.scalar(select(Location.id))

        def db_override():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = db_override
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        auth_security.reset_all()
        self.engine.dispose()
        self.temp.cleanup()

    # --- 工具 ---------------------------------------------------------------

    def make_user(self, student_id: str, password: str = "Correct123!"):
        with self.sessions() as db:
            user = User(
                student_id=student_id,
                email=f"{student_id.lower()}@hust.edu.cn",
                password_hash=hash_password(password),
                alias=f"匿名{student_id[-3:]}",
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            headers = {"Authorization": f"Bearer {create_access_token(user, db)}"}
            return user.id, headers

    def login(self, student_id: str, password: str):
        return self.client.post(
            "/api/auth/login",
            json={"student_id": student_id, "password": password},
        )

    # --- 生产配置自检 -------------------------------------------------------

    def test_production_config_rejects_development_defaults(self):
        with mock.patch.dict(os.environ, {
            "MOUKE_ENV": "production",
            "MOUKE_DEV_EMAIL_CODES": "1",
            "MOUKE_SMTP_HOST": "",
        }), mock.patch.object(auth, "CODE_SECRET", auth.DEFAULT_CODE_SECRET), \
                mock.patch.object(auth, "ALIAS_SECRET", auth.DEFAULT_CODE_SECRET):
            with self.assertRaises(RuntimeError) as ctx:
                auth.validate_production_config()
        message = str(ctx.exception)
        self.assertIn("MOUKE_CODE_SECRET", message)
        self.assertIn("MOUKE_SMTP_HOST", message)
        self.assertIn("MOUKE_DEV_EMAIL_CODES", message)

    def test_production_config_accepts_secure_values(self):
        with mock.patch.dict(os.environ, {
            "MOUKE_ENV": "production",
            "MOUKE_DEV_EMAIL_CODES": "0",
            "MOUKE_SMTP_HOST": "smtp.example.com",
        }), mock.patch.object(auth, "CODE_SECRET", "k" * 40), \
                mock.patch.object(auth, "ALIAS_SECRET", "a" * 40):
            auth.validate_production_config()  # 不抛即通过

    def test_production_config_rejects_reused_secret(self):
        shared = "s" * 40
        with mock.patch.dict(os.environ, {
            "MOUKE_ENV": "production",
            "MOUKE_DEV_EMAIL_CODES": "0",
            "MOUKE_SMTP_HOST": "smtp.example.com",
        }), mock.patch.object(auth, "CODE_SECRET", shared), \
                mock.patch.object(auth, "ALIAS_SECRET", shared):
            with self.assertRaises(RuntimeError) as ctx:
                auth.validate_production_config()
        self.assertIn("必须与", str(ctx.exception))

    def test_development_is_not_blocked(self):
        with mock.patch.dict(os.environ, {"MOUKE_ENV": "development"}):
            auth.validate_production_config()

    # --- 限流 ---------------------------------------------------------------

    def test_request_code_is_limited_per_student(self):
        browser = {"MOUKE_DEV_EMAIL_CODES": "1"}
        payload = {"student_id": "T2026001", "email": "t2026001@hust.edu.cn"}
        with mock.patch.dict(os.environ, browser), \
                mock.patch.object(auth_security, "REQUEST_CODE_SUBJECT", (1, 3600)):
            first = self.client.post("/api/auth/request-code", json=payload)
            second = self.client.post("/api/auth/request-code", json=payload)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("学号", second.json()["detail"])

    def test_login_is_limited_per_student(self):
        self.make_user("LIMIT1")
        with mock.patch.object(auth_security, "LOGIN_SUBJECT", (2, 600)):
            first = self.login("LIMIT1", "wrong-password")
            second = self.login("LIMIT1", "wrong-password")
            third = self.login("LIMIT1", "wrong-password")
        self.assertEqual(first.status_code, 401)
        self.assertEqual(second.status_code, 401)
        self.assertEqual(third.status_code, 429)
        self.assertIn("Retry-After", third.headers)

    # --- 验证码 -------------------------------------------------------------

    def test_verification_code_is_invalidated_after_five_failures(self):
        student_id, email = "T2026002", "t2026002@hust.edu.cn"
        with self.sessions() as db:
            db.add(VerificationCode(
                student_id=student_id, email=email, code_hash=hash_code("123456"),
                expires_at=datetime.now() + timedelta(minutes=10),
            ))
            db.commit()

        def register(code: str):
            return self.client.post("/api/auth/register", json={
                "student_id": student_id, "email": email,
                "code": code, "password": "Password123!",
            })

        for _ in range(5):
            self.assertEqual(register("000000").status_code, 400)
        # 5 次失败后验证码作废，即使猜中也必须重新获取
        self.assertEqual(register("123456").status_code, 400)
        with self.sessions() as db:
            row = db.scalar(select(VerificationCode).where(VerificationCode.student_id == student_id))
            self.assertEqual(row.attempts, 5)
            self.assertTrue(row.consumed)
            self.assertIsNone(db.scalar(select(User).where(User.student_id == student_id)))

    def test_correct_verification_code_registers_once(self):
        student_id, email = "T2026003", "t2026003@hust.edu.cn"
        with self.sessions() as db:
            db.add(VerificationCode(
                student_id=student_id, email=email, code_hash=hash_code("654321"),
                expires_at=datetime.now() + timedelta(minutes=10),
            ))
            db.commit()
        payload = {
            "student_id": student_id, "email": email,
            "code": "654321", "password": "Password123!",
        }
        first = self.client.post("/api/auth/register", json=payload)
        second = self.client.post("/api/auth/register", json=payload)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)  # 学号已注册，不能重放

    def test_consumed_code_cannot_be_replayed_without_existing_user(self):
        """同一验证码第二次使用时用户已经存在，所以 409 先于 400 —— 这里直接
        验证「已消费」这一状态本身，避免把 409 误当成验证码仍然有效。"""
        student_id, email = "T2026004", "t2026004@hust.edu.cn"
        with self.sessions() as db:
            db.add(VerificationCode(
                student_id=student_id, email=email, code_hash=hash_code("111111"),
                expires_at=datetime.now() + timedelta(minutes=10),
            ))
            db.commit()
        payload = {
            "student_id": student_id, "email": email,
            "code": "111111", "password": "Password123!",
        }
        self.assertEqual(self.client.post("/api/auth/register", json=payload).status_code, 201)
        with self.sessions() as db:
            row = db.scalar(select(VerificationCode).where(VerificationCode.student_id == student_id))
            self.assertTrue(row.consumed)

    # --- 登录锁定 -----------------------------------------------------------

    def test_five_failures_lock_the_account(self):
        user_id, _ = self.make_user("LOCK01")
        for _ in range(5):
            self.assertEqual(self.login("LOCK01", "wrong-password").status_code, 401)
        locked = self.login("LOCK01", "Correct123!")
        self.assertEqual(locked.status_code, 423)
        with self.sessions() as db:
            user = db.get(User, user_id)
            self.assertIsNotNone(user.locked_until)
            self.assertGreater(user.locked_until, datetime.now())

    def test_successful_login_clears_failure_state(self):
        user_id, _ = self.make_user("LOCK02")
        for _ in range(3):
            self.login("LOCK02", "wrong-password")
        with self.sessions() as db:
            user = db.get(User, user_id)
            user.locked_until = datetime.now() - timedelta(seconds=1)
            db.commit()
        self.assertEqual(self.login("LOCK02", "Correct123!").status_code, 200)
        with self.sessions() as db:
            user = db.get(User, user_id)
            self.assertEqual(user.failed_login_count, 0)
            self.assertIsNone(user.locked_until)

    # --- 注销 ---------------------------------------------------------------

    def test_delete_account_anonymizes_and_revokes_sessions(self):
        user_id, headers = self.make_user("DEL001")
        with self.sessions() as db:
            moment = Moment(
                location_id=self.location_id, user_id=user_id,
                author_alias="匿名001", content="这是一条会被匿名化的动态",
            )
            db.add(moment)
            db.commit()
            moment_id = moment.id

        wrong_password = self.client.post("/api/me/delete", headers=headers, json={
            "password": "not-the-password", "confirm": "注销账号",
        })
        self.assertEqual(wrong_password.status_code, 400)
        wrong_confirm = self.client.post("/api/me/delete", headers=headers, json={
            "password": "Correct123!", "confirm": "删除",
        })
        self.assertEqual(wrong_confirm.status_code, 422)

        deleted = self.client.post("/api/me/delete", headers=headers, json={
            "password": "Correct123!", "confirm": "注销账号",
        })
        self.assertEqual(deleted.status_code, 200)
        # 旧 token 立即失效
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)

        with self.sessions() as db:
            user = db.get(User, user_id)
            self.assertFalse(user.is_active)
            self.assertEqual(user.student_id, f"deleted-{user_id}")
            self.assertEqual(user.email, f"deleted-{user_id}@deleted.invalid")
            self.assertEqual(user.alias, "已注销用户")
            self.assertFalse(user.share_location)
            self.assertIsNone(user.last_latitude)
            self.assertEqual(
                db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user_id)),
                0,
            )
            moment = db.get(Moment, moment_id)
            self.assertTrue(moment.is_hidden)
            self.assertIsNone(moment.user_id)
            self.assertEqual(moment.author_alias, "已注销用户")

    # --- 健康检查与安全响应头 -----------------------------------------------

    def test_healthz_and_security_headers(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertIn("Content-Security-Policy", response.headers)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        # 明文 HTTP 下不能发 HSTS，否则本地开发会被浏览器强制升级
        self.assertNotIn("Strict-Transport-Security", response.headers)

        forwarded = self.client.get("/healthz", headers={"X-Forwarded-Proto": "https"})
        self.assertIn("Strict-Transport-Security", forwarded.headers)

    # --- AI 配额 ------------------------------------------------------------

    def test_ai_quota_is_enforced_per_user(self):
        user_id, headers = self.make_user("AI001")
        peer_id, _ = self.make_user("AI002")
        with self.sessions() as db:
            conversation = Conversation(
                initiator_id=user_id, recipient_id=peer_id, peer_alias="匿名002",
                status="active", expires_at=datetime.now() + timedelta(hours=1),
            )
            db.add(conversation)
            db.commit()
            conversation_id = conversation.id

        tight = replace(ratelimit.REPLY_SUGGESTION, limit=1)
        with mock.patch.object(ratelimit, "REPLY_SUGGESTION", tight):
            first = self.client.post(
                "/api/ai/reply-suggestions", headers=headers,
                json={"conversation_id": conversation_id},
            )
            second = self.client.post(
                "/api/ai/reply-suggestions", headers=headers,
                json={"conversation_id": conversation_id},
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        with self.sessions() as db:
            usage = db.scalar(select(func.count()).select_from(AiUsage).where(AiUsage.user_id == user_id))
            self.assertEqual(usage, 1)


if __name__ == "__main__":
    unittest.main()

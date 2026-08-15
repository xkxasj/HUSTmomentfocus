import asyncio
import os
from pathlib import Path
import tempfile
import unittest


_temp_dir = tempfile.TemporaryDirectory()
os.environ["MOUKE_DB_PATH"] = str(Path(_temp_dir.name) / "admin-test.db")
os.environ["MOUKE_ADMIN_STUDENT_ID"] = "MOUKEADMIN"
os.environ["MOUKE_ADMIN_EMAIL"] = "admin-test@example.com"
os.environ["MOUKE_ADMIN_PASSWORD"] = "Admin-Test-Only-123!"

from fastapi import HTTPException

from app.admin import admin_moment_visibility, admin_overview, get_admin_user, record_event
from app.auth import hash_password
from app.database import SessionLocal
from app.main import app, lifespan, login
from app.models import Location, Moment, User
from app.schemas import AdminMomentVisibilityUpdate, AnalyticsEventCreate, LoginRequest


class AdminSmokeTest(unittest.TestCase):
    def test_admin_bootstrap_permissions_analytics_and_moderation(self):
        async def scenario():
            async with lifespan(app):
                with SessionLocal() as db:
                    login_result = login(LoginRequest(
                        student_id="MOUKEADMIN",
                        password="Admin-Test-Only-123!",
                    ), db)
                    self.assertTrue(login_result["user"]["is_admin"])
                    admin = db.get(User, login_result["user"]["id"])

                    regular = User(
                        student_id="U123456",
                        email="u123456@hust.edu.cn",
                        password_hash=hash_password("Regular-Test-123!"),
                        alias="测试用户",
                    )
                    db.add(regular)
                    db.commit()
                    db.refresh(regular)

                    with self.assertRaises(HTTPException) as denied:
                        get_admin_user(regular)
                    self.assertEqual(denied.exception.status_code, 403)

                    record_event(AnalyticsEventCreate(
                        event_name="app_open",
                        session_id="session-test-123",
                        page="/map",
                    ), regular, db)
                    overview = admin_overview(admin, db)
                    self.assertEqual(overview["users"]["total"], 1)
                    self.assertEqual(overview["users"]["dau"], 1)

                    location = db.query(Location).first()
                    moment = Moment(
                        location_id=location.id,
                        user_id=regular.id,
                        author_alias=regular.alias,
                        content="后台隐藏测试",
                    )
                    db.add(moment)
                    db.commit()
                    db.refresh(moment)
                    result = admin_moment_visibility(
                        moment.id,
                        AdminMomentVisibilityUpdate(is_hidden=True),
                        admin,
                        db,
                    )
                    self.assertTrue(result["is_hidden"])

        asyncio.run(scenario())


def tearDownModule():
    from app.database import engine
    engine.dispose()
    _temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()

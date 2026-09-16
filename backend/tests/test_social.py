from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.auth import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models import AdminAuditLog, Conversation, Location, Moment, User
from app.seed import seed_database
from app.social_migrations import migrate_social


class SocialApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{(Path(self.temp.name) / 'social.db').as_posix()}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.engine.begin() as connection:
            migrate_social(connection)
            migrate_social(connection)
        with self.sessions() as db:
            seed_database(db)
            self.users = []
            self.headers = []
            for i in range(4):
                user = User(student_id=f"TEST00{i}", email=f"test00{i}@hust.edu.cn", password_hash="unused", alias=f"匿名{i}", is_admin=i == 3)
                db.add(user)
                db.commit()
                self.users.append(user.id)
                self.headers.append({"Authorization": f"Bearer {create_access_token(user, db)}"})
            self.location_id = db.scalar(select(Location.id))

        def db_override():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = db_override
        # Schema / fixtures are local to this test, so do not run production lifespan.
        self.client = TestClient(app)
        result = self.client.post('/api/moments', headers=self.headers[0], json={"location_id": self.location_id, "content": "今天的晚风很舒服"})
        self.assertEqual(result.status_code, 201, result.text)
        self.moment_id = result.json()["id"]

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()
        self.temp.cleanup()

    def invite(self):
        result = self.client.post('/api/conversations', headers=self.headers[1], json={"moment_id": self.moment_id})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()["id"]

    def accept(self, conversation_id):
        result = self.client.post(f'/api/conversations/{conversation_id}/decision', headers=self.headers[0], json={"action": "accept"})
        self.assertEqual(result.status_code, 200, result.text)

    def test_resonance_idempotency_echo_and_activity(self):
        path = f'/api/moments/{self.moment_id}/resonances'
        for kind in ("抱抱你", "抱抱你", "我也这样"):
            result = self.client.post(path, headers=self.headers[1], json={"kind": kind})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["resonance_count"], 1)
        echo = self.client.post(f'/api/moments/{self.moment_id}/echoes', headers=self.headers[1], json={"content": "我也喜欢晚风"})
        self.assertEqual(echo.status_code, 200, echo.text)
        data = self.client.get(f'/api/moments/{self.moment_id}/interactions', headers=self.headers[1]).json()
        self.assertEqual(data["my_resonance"], "我也这样")
        self.assertEqual(data["echoes"][0]["author_alias"], "匿名1")
        own = self.client.get('/api/me/activity', headers=self.headers[1]).json()
        self.assertEqual((own["resonance_given"], own["echoes_sent"]), (1, 1))
        author = self.client.get('/api/me/activity', headers=self.headers[0]).json()
        self.assertEqual(author["received_resonance"], 1)
        self.assertEqual(self.client.delete(path, headers=self.headers[1]).json()["resonance_count"], 0)
        self.assertEqual(self.client.post(f'/api/moments/{self.moment_id}/echoes', headers=self.headers[1], json={"content": "   "}).status_code, 400)

    def test_consent_unread_and_read_cursor_permissions(self):
        cid = self.invite()
        path = f'/api/conversations/{cid}'
        self.assertEqual(self.client.get('/api/conversations', headers=self.headers[0]).json()[0]["unread_count"], 1)
        self.assertEqual(self.client.post(path + '/messages', headers=self.headers[1], json={"content": "你好"}).status_code, 409)
        self.assertEqual(self.client.post(path + '/decision', headers=self.headers[1], json={"action": "accept"}).status_code, 403)
        self.assertEqual(self.client.get(path + '/messages', headers=self.headers[2]).status_code, 404)
        self.assertEqual(self.client.post(path + '/read', headers=self.headers[2], json={"message_id": 0}).status_code, 404)
        self.accept(cid)
        self.assertEqual(self.client.post(path + '/decision', headers=self.headers[0], json={"action": "accept"}).status_code, 409)
        first = self.client.post(path + '/messages', headers=self.headers[1], json={"content": "你好"}).json()
        self.assertEqual(self.client.post(path + '/messages', headers=self.headers[1], json={"content": "   "}).status_code, 400)
        self.assertEqual(self.client.post(path + '/read', headers=self.headers[0], json={"message_id": 99999}).status_code, 400)
        self.assertEqual(self.client.post(path + '/read', headers=self.headers[0], json={"message_id": first["id"]}).status_code, 200)
        self.assertEqual(self.client.get('/api/conversations', headers=self.headers[0]).json()[0]["unread_count"], 0)
        self.client.post(path + '/messages', headers=self.headers[1], json={"content": "第二条"})
        self.client.post(path + '/read', headers=self.headers[0], json={"message_id": first["id"]})
        self.assertEqual(self.client.get('/api/conversations', headers=self.headers[0]).json()[0]["unread_count"], 1)

    def test_expiry_rejection_close_and_location_consent(self):
        cid = self.invite()
        with self.sessions() as db:
            user = db.get(User, self.users[0])
            user.share_location = True
            user.last_latitude, user.last_longitude = 30.5134, 114.4162
            user.last_position_at = datetime.now()
            db.commit()
        self.assertIsNone(self.client.get('/api/conversations', headers=self.headers[1]).json()[0]["peer_presence"])
        self.accept(cid)
        self.assertIsNotNone(self.client.get('/api/conversations', headers=self.headers[1]).json()[0]["peer_presence"])
        with self.sessions() as db:
            db.get(Conversation, cid).expires_at = datetime.now() - timedelta(seconds=1)
            db.commit()
        row = self.client.get('/api/conversations', headers=self.headers[1]).json()[0]
        self.assertEqual(row["status"], "expired")
        self.assertIsNone(row["peer_presence"])
        self.assertEqual(self.client.post(f'/api/conversations/{cid}/messages', headers=self.headers[1], json={"content": "过期"}).status_code, 409)
        self.assertEqual(self.client.post('/api/ai/reply-suggestions', headers=self.headers[1], json={"conversation_id": cid}).status_code, 409)
        self.assertEqual(self.client.get(f'/api/conversations/{cid}/messages', headers=self.headers[1]).status_code, 200)

    def test_reject_and_close(self):
        cid = self.invite()
        self.assertEqual(self.client.post(f'/api/conversations/{cid}/decision', headers=self.headers[0], json={"action": "reject"}).status_code, 200)
        self.assertEqual(self.client.post(f'/api/conversations/{cid}/messages', headers=self.headers[1], json={"content": "你好"}).status_code, 409)
        self.assertEqual(self.client.post('/api/conversations', headers=self.headers[1], json={"moment_id": self.moment_id}).status_code, 409)
        other = self.client.post('/api/moments', headers=self.headers[0], json={"location_id": self.location_id, "content": "另一个片段"}).json()["id"]
        cid2 = self.client.post('/api/conversations', headers=self.headers[1], json={"moment_id": other}).json()["id"]
        self.accept(cid2)
        self.assertEqual(self.client.post(f'/api/conversations/{cid2}/decision', headers=self.headers[1], json={"action": "close"}).status_code, 200)
        self.assertEqual(self.client.post(f'/api/conversations/{cid2}/messages', headers=self.headers[0], json={"content": "结束"}).status_code, 409)

    def test_block_across_moments_unblock_does_not_reopen(self):
        cid = self.invite()
        self.accept(cid)
        self.assertEqual(self.client.post(f'/api/conversations/{cid}/block', headers=self.headers[0]).status_code, 200)
        self.assertEqual(self.client.get('/api/conversations', headers=self.headers[1]).json(), [])
        self.assertEqual(self.client.post(f'/api/conversations/{cid}/messages', headers=self.headers[1], json={"content": "你好"}).status_code, 403)
        other = self.client.post('/api/moments', headers=self.headers[0], json={"location_id": self.location_id, "content": "新的片段"}).json()["id"]
        self.assertEqual(self.client.post('/api/conversations', headers=self.headers[1], json={"moment_id": other}).status_code, 403)
        self.assertEqual(self.client.post(f'/api/moments/{other}/echoes', headers=self.headers[1], json={"content": "打扰"}).status_code, 403)
        block_id = self.client.get('/api/me/blocks', headers=self.headers[0]).json()[0]["id"]
        self.assertEqual(self.client.delete(f'/api/me/blocks/{block_id}', headers=self.headers[1]).status_code, 404)
        self.assertEqual(self.client.delete(f'/api/me/blocks/{block_id}', headers=self.headers[0]).status_code, 200)
        self.assertEqual(self.client.get('/api/conversations', headers=self.headers[1]).json()[0]["status"], "closed")
        self.assertEqual(self.client.post('/api/conversations', headers=self.headers[1], json={"moment_id": other}).status_code, 201)

    def test_report_admin_permissions_evidence_and_hide(self):
        payload = {"target_type": "moment", "target_id": self.moment_id, "reason": "泄露隐私"}
        for _ in range(2):
            self.assertEqual(self.client.post('/api/reports', headers=self.headers[1], json=payload).status_code, 201)
        self.assertEqual(self.client.get('/api/admin/reports', headers=self.headers[1]).status_code, 403)
        rows = self.client.get('/api/admin/reports', headers=self.headers[3]).json()
        self.assertEqual(len(rows), 1)
        self.assertIn("晚风", rows[0]["evidence"])
        report_id = rows[0]["id"]
        result = self.client.patch(f'/api/admin/reports/{report_id}', headers=self.headers[3], json={"action": "hide", "note": "核实后隐藏"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.get('/api/feed').json()["moments"], [])
        self.assertEqual(self.client.get(f'/api/moments/{self.moment_id}/interactions', headers=self.headers[1]).status_code, 404)
        self.assertEqual(self.client.post('/api/conversations', headers=self.headers[1], json={"moment_id": self.moment_id}).status_code, 404)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(AdminAuditLog.action)), "report_hide")

    def test_chat_report_only_participants_and_after_block(self):
        cid = self.invite()
        payload = {"target_type": "conversation", "target_id": cid, "reason": "持续骚扰"}
        self.assertEqual(self.client.post('/api/reports', headers=self.headers[2], json=payload).status_code, 404)
        self.client.post(f'/api/conversations/{cid}/block', headers=self.headers[0])
        self.assertEqual(self.client.post('/api/reports', headers=self.headers[0], json=payload).status_code, 201)
        row = self.client.get('/api/admin/reports', headers=self.headers[3]).json()[0]
        self.assertIn("content", row["evidence"])

    def test_public_privacy_validation_logout_and_pagination(self):
        self.assertEqual(self.client.post('/api/moments', headers=self.headers[0], json={"location_id": self.location_id, "content": "请联系13812345678"}).status_code, 400)
        first = self.client.get('/api/feed?limit=1').json()
        self.assertEqual(len(first["moments"]), 1)
        self.assertFalse(first["has_more"])
        self.assertEqual(self.client.get('/api/feed?offset=1').json()["moments"], [])
        self.assertEqual(self.client.post('/api/auth/logout', headers=self.headers[1]).status_code, 200)
        self.assertEqual(self.client.get('/api/auth/me', headers=self.headers[1]).status_code, 401)

    def test_echo_report_hides_echo_from_counts_and_activity(self):
        self.client.post(f'/api/moments/{self.moment_id}/echoes', headers=self.headers[1], json={"content": "待审核回声"})
        eid = self.client.get(f'/api/moments/{self.moment_id}/interactions', headers=self.headers[0]).json()["echoes"][0]["id"]
        self.client.post('/api/reports', headers=self.headers[0], json={"target_type": "echo", "target_id": eid, "reason": "不当内容"})
        rid = self.client.get('/api/admin/reports', headers=self.headers[3]).json()[0]["id"]
        self.assertEqual(self.client.patch(f'/api/admin/reports/{rid}', headers=self.headers[3], json={"action": "hide", "note": "核实后隐藏"}).status_code, 200)
        self.assertEqual(self.client.get('/api/feed').json()["moments"][0]["echo_count"], 0)
        self.assertEqual(self.client.get(f'/api/moments/{self.moment_id}/interactions', headers=self.headers[0]).json()["echoes"], [])
        self.assertEqual(self.client.get('/api/me/activity', headers=self.headers[1]).json()["echoes_sent"], 0)

    def test_expired_invitation_and_admin_closure(self):
        cid = self.invite()
        with self.sessions() as db:
            db.get(Conversation, cid).expires_at = datetime.now() - timedelta(seconds=1)
            db.commit()
        self.assertEqual(self.client.post(f'/api/conversations/{cid}/decision', headers=self.headers[0], json={"action": "accept"}).status_code, 409)
        self.client.post('/api/reports', headers=self.headers[0], json={"target_type": "conversation", "target_id": cid, "reason": "骚扰邀请"})
        rid = self.client.get('/api/admin/reports', headers=self.headers[3]).json()[0]["id"]
        self.assertEqual(self.client.patch(f'/api/admin/reports/{rid}', headers=self.headers[3], json={"action": "close", "note": "结束被举报会话"}).status_code, 200)
        self.assertEqual(self.client.get('/api/conversations', headers=self.headers[1]).json()[0]["status"], 'closed')


class LegacyMigrationTest(unittest.TestCase):
    def test_additive_migration_preserves_history_and_does_not_invent_consent(self):
        engine = create_engine('sqlite://')
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE resonances (id INTEGER PRIMARY KEY, moment_id INTEGER, kind TEXT)'))
            connection.execute(text('CREATE TABLE echoes (id INTEGER PRIMARY KEY, moment_id INTEGER, content TEXT)'))
            connection.execute(text('CREATE TABLE conversations (id INTEGER PRIMARY KEY, is_blocked BOOLEAN)'))
            connection.execute(text("INSERT INTO resonances VALUES (1, 10, '抱抱你')"))
            connection.execute(text('INSERT INTO conversations VALUES (1, 0)'))
            migrate_social(connection)
            migrate_social(connection)
            self.assertEqual(connection.execute(text('SELECT status FROM conversations')).scalar(), 'pending')
            self.assertIsNotNone(connection.execute(text('SELECT expires_at FROM conversations')).scalar())
            self.assertEqual(connection.execute(text('SELECT kind FROM resonances')).scalar(), '抱抱你')
        engine.dispose()

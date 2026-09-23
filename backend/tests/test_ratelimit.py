"""发布侧频控。

分两层测：

- `QuotaConstantTest` 钉住**真实限额的意图**。这些数字是产品参数不是实现细节 ——
  定紧了会误伤正常使用，所以用断言把它们锁在「对正常用户不可见」的量级上，将来
  有人手滑改成 `limit=1` 会红。它不 import app.main，毫秒级。
- 其余用 `dataclasses.replace` 把某一档的限额临时改小，测**机制**。这样不用为了
  触发 429 真发 10 条动态 —— 既快，也不与具体数字耦合（改限额不会改测试）。

骨架抄自 test_social.py:18-53（自建 engine + app.dependency_overrides[get_db]），
**不是** test_admin_smoke.py 的「先设环境变量再 import」写法，理由见
test_moderation_api.py 顶部。
"""

import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import ratelimit
from app.auth import create_access_token
from app.database import Base, get_db
from app.main import app
from app.models import Echo, Location, Moment, SuggestionFeedback, User
from app.seed import seed_database
from app.social_migrations import migrate_social

ALL_QUOTAS = (ratelimit.MOMENT, ratelimit.ECHO, ratelimit.SUGGESTION_FEEDBACK)


class QuotaConstantTest(unittest.TestCase):
    """限额的意图，不是限额的实现。"""

    def test_shipped_quotas_are_generous(self):
        for quota in ALL_QUOTAS:
            with self.subTest(quota=quota.name):
                self.assertGreaterEqual(
                    quota.limit, 10,
                    "限额太紧会误伤正常使用；现在还不知道真实规模，宁可宽",
                )
                self.assertGreaterEqual(quota.window_seconds, 60)
                self.assertTrue(quota.message.strip())

    def test_messages_are_display_ready(self):
        """文案会被前端直接展示（api.ts 把 detail 当消息渲染），要能当句子读。"""
        for quota in ALL_QUOTAS:
            with self.subTest(quota=quota.name):
                self.assertIsInstance(quota.message, str)
                self.assertTrue(quota.message.endswith("。"), quota.message)
                self.assertNotIn("{", quota.message, "没有格式化占位符，别写得像模板")

    def test_feedback_quota_is_the_loosest(self):
        """前端 fire-and-forget 调它（void api.xxx()），触发 429 是**静默丢语料**，
        用户看不到任何提示。所以这一档必须比别的宽 —— 这个不对称是刻意的。"""
        self.assertGreater(
            ratelimit.SUGGESTION_FEEDBACK.limit, ratelimit.MOMENT.limit
        )
        self.assertGreaterEqual(
            ratelimit.SUGGESTION_FEEDBACK.limit, ratelimit.ECHO.limit
        )

    def test_names_are_unique(self):
        """name 用于日志排查，重名会让「谁触发的」这个信息失效。"""
        names = [quota.name for quota in ALL_QUOTAS]
        self.assertEqual(len(names), len(set(names)))


class RatelimitApiTest(unittest.TestCase):
    """共用的库与账号。本身没有用例，只被子类继承。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{(Path(self.temp.name) / 'ratelimit.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.engine.begin() as connection:
            migrate_social(connection)
            migrate_social(connection)
        with self.sessions() as db:
            seed_database(db)
            self.headers = []
            self.user_ids = []
            for index in range(2):
                user = User(
                    student_id=f"RL00{index}",
                    email=f"rl00{index}@hust.edu.cn",
                    password_hash="unused",
                    alias=f"匿名{index}",
                )
                db.add(user)
                db.commit()
                self.user_ids.append(user.id)
                self.headers.append(
                    {"Authorization": f"Bearer {create_access_token(user, db)}"}
                )
            self.location_id = db.scalar(select(Location.id))

        def db_override():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = db_override
        # Schema/fixtures 是本测试私有的，不要跑生产的 lifespan（R6）。
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()
        self.temp.cleanup()

    # --- 工具 ---------------------------------------------------------------

    def tight(self, name: str, limit: int):
        """把 ratelimit.<name> 换成一档 limit 很小的配额。

        只改 limit，name / window_seconds / message 保持原样，所以测的仍然是真实
        配额对象的行为。返回 context manager。
        """
        quota = getattr(ratelimit, name)
        return mock.patch.object(ratelimit, name, replace(quota, limit=limit))

    def publish(self, content: str = "今天的晚风很舒服", header: int = 0):
        return self.client.post('/api/moments', headers=self.headers[header], json={
            "location_id": self.location_id, "content": content, "mood": "平静",
        })

    def echo(self, moment_id: int, header: int = 0):
        return self.client.post(
            f'/api/moments/{moment_id}/echoes',
            headers=self.headers[header],
            json={"content": "我也喜欢晚风"},
        )

    def feedback(self, header: int = 0):
        return self.client.post('/api/ai/suggestion-feedback', headers=self.headers[header], json={
            "context_type": "reply",
            "suggestion": "",
            "final_text": "测试语料",
            "selected_rank": 1,
        })

    def count(self, model) -> int:
        with self.sessions() as db:
            return db.scalar(select(func.count()).select_from(model))

    def backdate(self, model, user_id: int):
        """把该用户的已有行挪到窗口之外。

        用来验证窗口真的在滑动 —— 比 sleep(window) 快，而且不会在慢机器上抖动。
        """
        with self.sessions() as db:
            for row in db.scalars(select(model).where(model.user_id == user_id)):
                row.created_at = datetime.now() - timedelta(days=1)
            db.commit()


class MomentQuotaTest(RatelimitApiTest):
    def test_limit_blocks_the_next_request(self):
        with self.tight("MOMENT", 2):
            self.assertEqual(self.publish().status_code, 201)
            self.assertEqual(self.publish().status_code, 201)
            self.assertEqual(self.publish().status_code, 429)

    def test_429_detail_is_a_plain_string(self):
        """frontend/src/api.ts 把 detail 直接当消息渲染，返回对象会显示 [object Object]。"""
        with self.tight("MOMENT", 1):
            self.publish()
            result = self.publish()
        self.assertEqual(result.status_code, 429)
        self.assertIsInstance(result.json()["detail"], str)
        self.assertEqual(result.json()["detail"], ratelimit.MOMENT.message)

    def test_nothing_is_written_when_blocked(self):
        """429 的语义是「什么都没发生」。只看状态码不够（R5 的同类错误）。"""
        with self.tight("MOMENT", 2):
            self.publish()
            self.publish()
            before = self.count(Moment)
            self.assertEqual(self.publish().status_code, 429)
            self.assertEqual(self.count(Moment), before)
        self.assertEqual(before, 2)

    def test_quota_is_per_user(self):
        """频控按账号算。

        窗口查询里那句 `model.user_id == user_id` 要是漏了，整张表都变成「这个人
        发的」，一个人发满全员被封 —— 两条断言把两个方向都钉住。
        """
        with self.tight("MOMENT", 1):
            self.assertEqual(self.publish(header=0).status_code, 201)
            self.assertEqual(self.publish(header=0).status_code, 429)
            self.assertEqual(self.publish(header=1).status_code, 201)

    def test_rejected_content_does_not_consume_quota(self):
        """只统计**已经写进去**的行。

        校验顺序是「先频控、再内容把关」，所以被内容拒掉的请求根本不会增加计数 ——
        不该算在这个人的发布频率里。测试用一个足够小的限额把这条语义钉死：连发
        5 条违规内容全部 400 之后，正常内容仍然发得出去。
        """
        with self.tight("MOMENT", 2):
            for _ in range(5):
                result = self.publish(content="你这个傻逼")
                self.assertEqual(result.status_code, 400)
            self.assertEqual(self.count(Moment), 0)
            self.assertEqual(self.publish().status_code, 201)
            self.assertEqual(self.publish().status_code, 201)
            self.assertEqual(self.publish().status_code, 429)

    def test_requests_older_than_the_window_do_not_count(self):
        with self.tight("MOMENT", 1):
            self.assertEqual(self.publish().status_code, 201)
            self.assertEqual(self.publish().status_code, 429)
            self.backdate(Moment, self.user_ids[0])
            self.assertEqual(self.publish().status_code, 201)


class OtherResourceQuotaTest(RatelimitApiTest):
    def test_echo_quota_applies(self):
        moment_id = self.publish().json()["id"]
        with self.tight("ECHO", 1):
            self.assertEqual(self.echo(moment_id).status_code, 200)
            result = self.echo(moment_id)
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result.json()["detail"], ratelimit.ECHO.message)
        self.assertEqual(self.count(Echo), 1)

    def test_echo_quota_is_separate_from_moment_quota(self):
        """两档是独立计数器。发满动态不该让回声也发不出去。"""
        with self.tight("MOMENT", 1):
            moment_id = self.publish().json()["id"]
            self.assertEqual(self.publish().status_code, 429)
            self.assertEqual(self.echo(moment_id).status_code, 200)

    def test_suggestion_feedback_quota_applies(self):
        with self.tight("SUGGESTION_FEEDBACK", 2):
            self.assertEqual(self.feedback().status_code, 201)
            self.assertEqual(self.feedback().status_code, 201)
            result = self.feedback()
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result.json()["detail"], ratelimit.SUGGESTION_FEEDBACK.message)
        self.assertEqual(self.count(SuggestionFeedback), 2)


if __name__ == "__main__":
    unittest.main()

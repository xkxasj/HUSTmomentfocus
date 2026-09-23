"""把关层在真实 API 上的行为。

骨架抄自 test_social.py:18-53（自建 engine + app.dependency_overrides[get_db]），
**不是** test_admin_smoke.py 的「先设环境变量再 import」写法 —— unittest discover
按字母序 import，test_admin_smoke 最先跑、并且已经把 app.database.engine 指向它
自己的临时库；后设的 MOUKE_DB_PATH 会被静默忽略，测试跑在别人的库上，绿但什么
都没验到。

这个文件覆盖三件事：

1. 硬拦截真的拦住，而且**什么都没写进库**。只看状态码是不够的 —— 校验点要是写在
   db.add/db.commit 之后，接口照样返回 400，但脏内容已经入库了（R5）。
2. 历史行为没被改坏：隐私文案逐字一致、合法内容原样往返（R2b）、同时命中时仍给
   隐私文案。
3. AI 输出过滤后整批降级为模板，且 ai_used / vision_used 诚实。

AI 部分全部 mock 掉 provider：**不触网、不需要任何 API key**。
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app import moderation
from app.auth import create_access_token
from app.database import Base, get_db
from app.main import (
    CAPTION_TEMPLATES,
    REPLY_AGREED,
    REPLY_FOLLOW_UP,
    REPLY_THANKS,
    UPLOAD_DIR,
    app,
)
from app.models import Echo, Location, Moment, User
from app.moderation import CATEGORY_MESSAGES
from app.seed import LOCATIONS, seed_database
from app.social_migrations import migrate_social

PRIVACY_DETAIL = "内容可能包含手机号、邮箱或其他身份信息，请移除后再发布。"

# 只要求魔数正确，upload_image 不做图片解码，所以一段签名 + 填充就够。
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

# 四类各一条，全部来自 moderation.TERMS 的种子词。
BANNED = {
    "abuse": "你这个傻逼",
    "ad": "私聊我领取福利名额",
    "adult": "一起约炮吗",
    "illegal": "可以代考",
}


class ModerationApiTest(unittest.TestCase):
    def setUp(self):
        # R8：本机若配了 MOUKE_VISION_API_URL/KEY，image_caption 在候选为空时会真的
        # 发一次外网请求；MOUKE_AI_STRICT 会让失败路径随本机配置漂移。全部钉死。
        self.env = mock.patch.dict(os.environ, {
            "MOUKE_VISION_API_URL": "",
            "MOUKE_VISION_API_KEY": "",
            "MOUKE_AI_STRICT": "0",
        })
        self.env.start()
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{(Path(self.temp.name) / 'moderation.db').as_posix()}",
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
            for index in range(2):
                user = User(student_id=f"MOD00{index}", email=f"mod00{index}@hust.edu.cn", password_hash="unused", alias=f"匿名{index}")
                db.add(user)
                db.commit()
                self.headers.append({"Authorization": f"Bearer {create_access_token(user, db)}"})
            self.location_id = db.scalar(select(Location.id))

        def db_override():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = db_override
        # Schema / fixtures are local to this test, so do not run production lifespan.
        self.client = TestClient(app)
        self.uploaded: list[Path] = []

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()
        self.temp.cleanup()
        for path in self.uploaded:
            path.unlink(missing_ok=True)
        self.env.stop()

    # --- 工具 ---------------------------------------------------------------

    def count(self, model) -> int:
        with self.sessions() as db:
            return db.scalar(select(func.count()).select_from(model))

    def publish(self, content: str = "今天的晚风很舒服", mood: str = "平静"):
        return self.client.post('/api/moments', headers=self.headers[0], json={
            "location_id": self.location_id, "content": content, "mood": mood,
        })

    def upload_png(self) -> str:
        result = self.client.post('/api/uploads/images', content=PNG_BYTES, headers={
            **self.headers[0], "Content-Type": "image/png",
        })
        self.assertEqual(result.status_code, 201, result.text)
        image_url = result.json()["image_url"]
        self.uploaded.append(UPLOAD_DIR / Path(image_url).name)
        return image_url

    def active_conversation(self) -> int:
        moment_id = self.publish().json()["id"]
        created = self.client.post('/api/conversations', headers=self.headers[1], json={"moment_id": moment_id})
        self.assertEqual(created.status_code, 201, created.text)
        conversation_id = created.json()["id"]
        accepted = self.client.post(f'/api/conversations/{conversation_id}/decision', headers=self.headers[0], json={"action": "accept"})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        return conversation_id

    def short_name(self) -> str:
        with self.sessions() as db:
            return db.get(Location, self.location_id).short_name


class PublicTextGateTest(ModerationApiTest):
    """动态 / 回声 / mood 三条公开入口。"""

    def test_moment_rejects_each_category_and_writes_nothing(self):
        before = self.count(Moment)
        for category, content in BANNED.items():
            with self.subTest(category=category):
                result = self.publish(content=content)
                self.assertEqual(result.status_code, 400, result.text)
                detail = result.json()["detail"]
                self.assertIsInstance(detail, str, "api.ts:57 把 detail 直接当消息渲染，返回对象会显示成 [object Object]")
                self.assertEqual(detail, CATEGORY_MESSAGES[category])
        self.assertEqual(self.count(Moment), before, "硬拦截的语义是什么都不写，只看状态码看不出写入是否发生在校验之前")

    def test_echo_rejects_and_writes_nothing(self):
        moment_id = self.publish().json()["id"]
        before = self.count(Echo)
        result = self.client.post(f'/api/moments/{moment_id}/echoes', headers=self.headers[1], json={"content": "你就是个脑残"})
        self.assertEqual(result.status_code, 400, result.text)
        self.assertEqual(self.count(Echo), before)

    def test_mood_rejects_and_writes_nothing(self):
        """mood 是自由文本、无枚举校验、且直接进 feed。"""
        before = self.count(Moment)
        result = self.publish(mood="加我约炮")
        self.assertEqual(result.status_code, 400, result.text)
        self.assertEqual(self.count(Moment), before)

    def test_legit_content_is_stored_verbatim(self):
        """R2b：归一化只用于匹配，绝不能写回或返回。

        NFKC 是有损的（①→1、Ⅴ→V、㎡→m2）。现有测试一条都没有断言 content 相等，
        改坏了不会红，所以这条必须显式钉住。
        """
        content = "第①餐厅的饭真的绝了，㎡ 和 Ⅴ 级都好吃"
        result = self.publish(content=content)
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()["content"], content)
        with self.sessions() as db:
            self.assertEqual(db.get(Moment, result.json()["id"]).content, content)

    def test_privacy_detail_is_byte_identical_to_history(self):
        result = self.publish(content="请联系13812345678")
        self.assertEqual(result.status_code, 400, result.text)
        self.assertEqual(result.json()["detail"], PRIVACY_DETAIL)

    def test_hitting_both_privacy_and_banned_still_reports_privacy(self):
        """顺序有意如此：隐私在前，历史文案不变。"""
        result = self.publish(content="我就是个傻逼，请联系13812345678")
        self.assertEqual(result.status_code, 400, result.text)
        self.assertEqual(result.json()["detail"], PRIVACY_DETAIL)


class AiCaptionGateTest(ModerationApiTest):
    """image_caption 的输出闸门。"""

    CLEAN = ("在图书馆，镜头替我记住了这一刻", "今天路过图书馆，刚好遇见这一幕", "普通的一天，也有值得存下来的画面")
    BAD = "照片里那个人的手机号是 13812345678"

    def caption(self, payload: str):
        with mock.patch("app.main.call_siliconflow_vision", return_value=payload):
            result = self.client.post('/api/ai/image-caption', headers=self.headers[0], json={
                "image_url": self.upload_png(), "location_id": self.location_id, "tone": "像本人",
            })
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_clean_batch_is_kept_and_flagged_vision_used(self):
        body = self.caption(json.dumps({"suggestions": list(self.CLEAN)}))
        self.assertEqual(body["mode"], "vision")
        self.assertTrue(body["vision_used"])
        self.assertEqual(body["captions"], list(self.CLEAN))

    def test_one_bad_caption_drops_the_whole_batch(self):
        """整批降级：一条坏候选就丢掉整批走模板。

        部分过滤会造出「3 条里 1 条是模板」的混合批次，而 vision_used 仍是 True，
        前端会据此谎称三条都由 AI 生成。
        """
        payload = json.dumps({"suggestions": [self.CLEAN[0], self.BAD, self.CLEAN[2]]})
        body = self.caption(payload)
        self.assertEqual(body["mode"], "template")
        self.assertFalse(body["vision_used"])
        self.assertNotIn(self.BAD, body["captions"])
        self.assertEqual(body["captions"][0], CAPTION_TEMPLATES[0].format(place=self.short_name()))
        for text in body["captions"]:
            with self.subTest(text=text):
                self.assertIsNotNone(moderation.sanitize_ai_output(text), "降级路径本身不能返回被拦内容")

    def test_vision_failure_falls_back_to_template(self):
        """不配 key / provider 抛错时的兜底路径必须可达。"""
        with mock.patch("app.main.call_siliconflow_vision", side_effect=RuntimeError("no key")):
            result = self.client.post('/api/ai/image-caption', headers=self.headers[0], json={
                "image_url": self.upload_png(), "location_id": self.location_id, "tone": "像本人",
            })
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["mode"], "template")


class AiReplyGateTest(ModerationApiTest):
    """reply_suggestions 的输出闸门。"""

    CLEAN = ("我也是这样想的", "你当时是什么感觉", "谢谢你告诉我这些")
    BAD = "一起约炮吗"

    def reply(self, payload: str):
        conversation_id = self.active_conversation()
        with mock.patch("app.main.call_deepseek", return_value=payload):
            result = self.client.post('/api/ai/reply-suggestions', headers=self.headers[0], json={"conversation_id": conversation_id})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_clean_batch_keeps_ai_used_true(self):
        body = self.reply(json.dumps({"suggestions": list(self.CLEAN)}))
        self.assertTrue(body["ai_used"])
        self.assertEqual([row["text"] for row in body["suggestions"]], list(self.CLEAN))

    def test_one_bad_reply_drops_the_whole_batch_and_clears_ai_used(self):
        """免费得来的整批降级：过滤掉任何一条，剩余必然 < 3，现有的
        `if len(choices) < 3:` 分支就会整批换模板；过滤在 ai_used 之前，
        所以标志位永远是诚实的。
        """
        payload = json.dumps({"suggestions": [self.CLEAN[0], self.BAD, self.CLEAN[2]]})
        body = self.reply(payload)
        self.assertFalse(body["ai_used"], "整批降级后 ai_used 必须是 False")
        self.assertEqual(
            [row["text"] for row in body["suggestions"]],
            [REPLY_AGREED, REPLY_FOLLOW_UP, REPLY_THANKS],
        )

    def test_model_failure_falls_back_to_template(self):
        body = self.reply("这不是 JSON，也不是三行")
        self.assertFalse(body["ai_used"])
        self.assertEqual(len(body["suggestions"]), 3)
        for row in body["suggestions"]:
            with self.subTest(text=row["text"]):
                self.assertIsNotNone(moderation.sanitize_ai_output(row["text"]))


class TemplateConstantTest(ModerationApiTest):
    """main.py 里的模板常量必须能过自己的闸门。

    模板被自己的规则拦掉，降级路径就会返回空 —— 而这条路径平时没人走。
    真正会被拦的是「有人把模板里出现过的字加进了词表」，所以这里直接断言
    **app.main 里的真常量**，不依赖任何抄写副本。
    """

    def test_caption_templates_are_clean_for_every_seed_place(self):
        for row in LOCATIONS:
            for template in CAPTION_TEMPLATES:
                text = template.format(place=row[1])
                with self.subTest(text=text):
                    self.assertIsNotNone(moderation.sanitize_ai_output(text), f"模板被自己的规则拦掉：{text!r}")

    def test_reply_templates_are_clean(self):
        for text in (REPLY_AGREED, REPLY_FOLLOW_UP, REPLY_THANKS):
            with self.subTest(text=text):
                self.assertIsNotNone(moderation.sanitize_ai_output(text), f"模板被自己的规则拦掉：{text!r}")


if __name__ == "__main__":
    unittest.main()

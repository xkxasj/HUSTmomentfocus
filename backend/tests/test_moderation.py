"""把关层的纯函数测试。

这个文件只依赖标准库 + app.moderation + app.seed 的常量，不需要 DB、
不需要 TestClient、不需要 httpx、不受 import 顺序影响，毫秒级。
改词表之后先跑这个文件。

这里同时是「加词纪律」的执行者：
- RuleIntegrityTest 在有人加单字词或忘配文案时当场报错；
- FalsePositiveCorpusTest 拦住往词表里误加「晚风」「匿名」这类现有文案子串；
- KnownOverBlockTest 把硬拦截词表的代价**显式记录**下来，而不是假装没有。
"""

import unittest

from app import moderation
from app.moderation import (
    CATEGORY_MESSAGES,
    TERMS,
    privacy_hit,
    sanitize_ai_output,
    screen,
)
from app.seed import LOCATIONS


class NormalizationTest(unittest.TestCase):
    """归一化必须拦住变形绕过，同时不能制造跨句误报。"""

    def test_plain_hit(self):
        self.assertIsNotNone(screen("你这个傻逼"))

    def test_separator_variants_all_hit(self):
        for text in ("傻·逼", "傻-逼", "傻.逼", "傻_逼", "傻 逼", "傻*逼", "傻~逼"):
            with self.subTest(text=text):
                self.assertIsNotNone(screen(text), f"{text!r} 应被拦截")

    def test_zero_width_variants_all_hit(self):
        """零宽字符是最常见的绕过手段，逐个码位验一遍。

        码位用 \\u 转义写出来，不写字面量 —— 不可见字符放进源码里既看不出来
        也改不动，这个文件之前就在这上面栽过一次。
        """
        for label, cp in (("U+200B", "\u200b"), ("U+200C", "\u200c"),
                          ("U+200D", "\u200d"), ("U+FEFF", "\ufeff")):
            with self.subTest(label=label):
                self.assertIsNotNone(screen("你这个傻" + cp + "逼"), f"插入 {label} 应仍被拦截")

    def test_fold_normalizes_full_width_and_case(self):
        """NFKC + casefold 的契约。

        当前词表全是中文，NFKC/casefold 对它们是恒等的 —— 这两步是为将来
        可能加入的 ASCII 词（如 VX、QQ）预留的。直接测 _fold 的契约，
        免得这段逻辑在没人用的情况下悄悄坏掉。
        """
        self.assertEqual(moderation._fold("ＶＸａｂｃ"), "vxabc")
        self.assertEqual(moderation._fold("ABC"), "abc")
        self.assertEqual(moderation._fold("Ａ１"), "a1")

    def test_fold_strips_format_characters(self):
        self.assertEqual(moderation._fold("傻\u200b逼"), "傻逼")
        self.assertEqual(moderation._fold("\ufeff你好"), "你好")

    def test_cross_sentence_concatenation_is_not_a_hit(self):
        """设计里最关键的一条反例。

        「太傻了。逼着…」如果对整段做压缩会拼出「傻逼」，把正常中文误判成
        辱骂。按句末标点切段之后不应该命中。这条测试就是那个设计决策的守卫。
        """
        self.assertIsNone(screen("我当时太傻了。逼着自己学了一晚上"))
        self.assertIsNone(screen("他有点傻。逼得大家都重做了一遍"))
        self.assertIsNone(screen("这题真难。逼着我熬夜"))
        self.assertIsNone(screen("我真的傻了！逼我加班到十点"))

    def test_intervening_character_prevents_false_concatenation(self):
        """两个字之间还夹着别的字时，不能拼出违禁词。

        这和上一条是同一枚硬币：只有「傻」「逼」两字**紧邻**才算。夹了「了」
        就是正常句子，夹了逗号更不是 —— 逗号既不在切段符里也不在间隔符里，
        天然充当边界。
        """
        self.assertIsNone(screen("太傻了 逼着我学了一晚上"))
        self.assertIsNone(screen("我真是傻了 逼自己熬夜"))
        self.assertIsNone(screen("他真傻，逼得大家都重做了一遍"))

    def test_known_tradeoff_bare_space_concatenation_still_hits(self):
        """已知取舍，显式记录。

        没有句末标点、且两字紧邻只隔一个空格时，段内去空格会把它拼成违禁词
        （「他真傻 逼得我」→「他真傻逼得我」）。空格既是绕过手段也是天然词
        边界，无法两全；这里选择保住「傻 逼」这类更常见的绕过。代价是不收
        短词和拼接词（由 RuleIntegrityTest 约束）。
        """
        self.assertIsNotNone(
            screen("他真傻 逼得我"),
            "若将来改进了分段策略让这里变干净，请更新这条断言而不是删掉它。",
        )


class ScreenTest(unittest.TestCase):
    def test_each_category_reports_its_own_category(self):
        cases = {
            "abuse": "你就是个脑残",
            "adult": "加我约炮",
            "illegal": "可以代考",
        }
        for category, text in cases.items():
            with self.subTest(category=category):
                flag = screen(text)
                self.assertIsNotNone(flag, f"{text!r} 应命中 {category}")
                self.assertEqual(flag.category, category)
                self.assertTrue(flag.rule_id)

    def test_ad_cooccurrence_needs_both_groups(self):
        """「私聊」本身是正常社交动作（核心功能），单独出现不能拦。"""
        self.assertIsNone(screen("那我们私聊吧"))
        self.assertIsNone(screen("想领取资料的同学看这里"))
        flag = screen("私聊我领取福利名额")
        self.assertIsNotNone(flag, "两个组合同时出现应命中")
        self.assertEqual(flag.category, "ad")
        self.assertEqual(flag.rule_id, "ad.solicit")

    def test_cooccurrence_is_scoped_to_one_segment(self):
        """共现必须在同一段内，否则两句无关的话会被拼成广告。"""
        self.assertIsNone(screen("我们先私聊吧。资料我已经领取了"))

    def test_message_never_echoes_the_matched_term(self):
        """文案只给类别级原因。回显命中词等于把词表教给对抗者。"""
        for text in ("你就是个脑残", "加我约炮", "可以代考", "私聊我领取福利名额"):
            with self.subTest(text=text):
                flag = screen(text)
                self.assertIsNotNone(flag)
                self.assertIn(flag.message, tuple(CATEGORY_MESSAGES.values()))
                for term in ("脑残", "约炮", "代考", "福利", "私聊"):
                    self.assertNotIn(term, flag.message)

    def test_empty_and_whitespace_are_clean(self):
        for value in (None, "", "   ", "\n\n", "。。。"):
            with self.subTest(value=value):
                self.assertIsNone(screen(value))


class RuleIntegrityTest(unittest.TestCase):
    """词表纪律的机器执行者。"""

    def test_categories_are_exactly_the_agreed_four(self):
        self.assertEqual(set(TERMS), {"abuse", "ad", "adult", "illegal"})
        self.assertEqual(set(CATEGORY_MESSAGES), set(TERMS))

    def test_every_message_is_well_formed(self):
        for category, message in CATEGORY_MESSAGES.items():
            with self.subTest(category=category):
                self.assertTrue(message.strip())
                self.assertTrue(message.endswith("。"), "文案会被前端直接展示，要以句号收尾")

    def test_no_single_character_terms(self):
        """单字词在中文里误报率极高，必须禁止。"""
        for category, terms in TERMS.items():
            for term in terms:
                with self.subTest(category=category, term=term):
                    self.assertGreaterEqual(len(term), 2, f"{term!r} 太短，会大面积误伤")

    def test_terms_are_unique_across_categories(self):
        seen: dict[str, str] = {}
        for category, terms in TERMS.items():
            for term in terms:
                self.assertNotIn(term, seen, f"{term!r} 同时出现在 {seen.get(term)} 和 {category}")
                seen[term] = category

    def test_no_duplicate_terms_within_a_category(self):
        for category, terms in TERMS.items():
            with self.subTest(category=category):
                self.assertEqual(len(terms), len(set(terms)))

    def test_every_term_is_actually_reachable(self):
        """每个词都要能被 screen() 命中 —— 防止加了个永远不会触发的死词。"""
        for category, terms in TERMS.items():
            for term in terms:
                with self.subTest(category=category, term=term):
                    flag = screen(f"我说{term}啊")
                    self.assertIsNotNone(flag, f"{term!r} 加进词表却匹配不到")
                    self.assertEqual(flag.category, category)


class FalsePositiveCorpusTest(unittest.TestCase):
    """「没有破坏现有内容」的机器证明。

    语料来自产品自身的文案：28 个地点的描述/提问/心情，加上现有测试里
    发布过的每一句正常内容。任何一条被拦都是回归。
    """

    # 字段序见 seed.py 顶部注释：name, short_name, description, prompt, mood, ...
    SEED_FIELDS = (0, 1, 2, 3, 4)

    def test_seed_corpus_is_never_flagged(self):
        for row in LOCATIONS:
            for index in self.SEED_FIELDS:
                text = row[index]
                with self.subTest(text=text):
                    self.assertIsNone(screen(text), f"种子文案被误拦：{text!r}")

    def test_existing_test_literals_are_never_flagged(self):
        """这些是 test_social.py 里真实发布过的内容。

        其中「今天的晚风很舒服」在 setUp 里发布 —— 一旦被误拦，
        整个 SocialApiTest 的 10 条用例会一起崩。
        """
        literals = (
            "今天的晚风很舒服", "我也喜欢晚风", "待审核回声", "另一个片段",
            "新的片段", "你好", "第二条", "过期", "结束", "打扰",
            "持续骚扰", "骚扰邀请", "泄露隐私", "不当内容", "核实后隐藏",
            "结束被举报会话",
        )
        for text in literals:
            with self.subTest(text=text):
                self.assertIsNone(screen(text), f"现有测试文案被误拦：{text!r}")

    def test_ai_template_copy_is_never_flagged(self):
        """AI 兜底模板必须能通过自己的闸门，否则降级路径会返回空。

        这里是手抄的副本 —— 本文件刻意不 import app.main（那会拖进 fastapi 与
        httpx，毁掉「毫秒级、零依赖」这个性质）。真正会拦下漂移的是
        test_moderation_api.py::TemplateConstantTest，它直接断言 app.main 里的
        **真常量**。改了那边的模板，记得同步这里。
        """
        templates = (
            "普通的一天，也有值得存下来的画面",
            "可以呀，我也有点这种感觉",
            "嗯嗯，我懂你说的",
            "那你当时是怎么想的呀",
            "谢谢你愿意和我说这些",
        )
        for text in templates:
            with self.subTest(text=text):
                self.assertIsNone(screen(text), f"AI 模板被误拦：{text!r}")

    def test_ordinary_campus_venting_is_never_flagged(self):
        """校园吐槽里的正常表达。泛化粗口刻意没有进词表。"""
        literals = (
            "卧槽这个实验报告也太多了",
            "我靠今天食堂排队排到怀疑人生",
            "服了，又断网了",
            "今天累成狗",
            "老师太狠了吧这作业量",
            "好想吐槽这个实验",
            "晚风很舒服，想在这里多坐一会儿",
            "图书馆的插座救了我一命",
            "这个食堂的饭真的绝了",
            "谁懂啊，早八人已经麻了",
        )
        for text in literals:
            with self.subTest(text=text):
                self.assertIsNone(screen(text), f"正常吐槽被误拦：{text!r}")

    def test_near_miss_terms_are_not_flagged(self):
        """近似但不同的表达不能被误伤。"""
        near_misses = (
            "这个算法的时间复杂度是代数的考点",  # 含「代」但不是「代考」
            "我在准备考试",                      # 「考」单独不构成
            "他赌气不理我了",                    # 「赌气」不是「赌博」
            "这个食堂的饭太咸了",                # 对照：完全无害
            "我想报名参加这个讲座",              # 「报名」不是「名额」共现
        )
        for text in near_misses:
            with self.subTest(text=text):
                self.assertIsNone(screen(text), f"近似表达被误拦：{text!r}")


class KnownOverBlockTest(unittest.TestCase):
    """硬拦截词表的代价，显式记录而不是假装没有。

    用户选了「一律硬拦截」，所以词表命中就是拒绝发布，没有人工复核这一层。
    下面这些是**正常的校园表达**，但当前词表会拦。它们是这个策略的真实成本。

    如果将来决定放开某一条，正确做法是把它从 TERMS 里删掉、把这里的断言
    移到最后一条「应该干净」的列表里 —— 而不是删掉这条测试。
    """

    OVER_BLOCKS = (
        "农学院的课程介绍了大麻的植物学特征",   # 命中 illegal 的「大麻」
        "学校说校园贷要警惕，别乱借",           # 命中 illegal 的「校园贷」
        "这篇报道讲的是洗钱犯罪的司法认定",     # 命中 illegal 的「洗钱」
        "他这个月靠返利省了不少钱",             # 命中 ad 的「返利」
        "我今天心情好，想日结一下作业",         # 命中 ad 的「日结」
    )

    def test_documented_over_blocks(self):
        for text in self.OVER_BLOCKS:
            with self.subTest(text=text):
                flag = screen(text)
                self.assertIsNotNone(
                    flag,
                    f"{text!r} 现在不再被拦了。如果这是有意放开的，"
                    f"请把它移到 test_near_miss_terms_are_not_flagged 里。",
                )
                self.assertIn(flag.category, TERMS)


class PrivacyTest(unittest.TestCase):
    def test_detects_phone_id_email_and_keywords(self):
        self.assertTrue(privacy_hit("联系我 13812345678"))
        self.assertTrue(privacy_hit("邮箱是 someone@hust.edu.cn"))
        self.assertTrue(privacy_hit("身份证 11010119900307123X"))
        self.assertTrue(privacy_hit("我住在宿舍号 305"))

    def test_ignores_ordinary_numbers(self):
        self.assertFalse(privacy_hit("今天是 2026 年，我大二"))
        self.assertFalse(privacy_hit("这个算法复杂度是 O(n^2)"))
        self.assertFalse(privacy_hit("我在 305 教室上课"))  # 没有「宿舍号」这类关键词

    def test_empty_is_clean(self):
        self.assertFalse(privacy_hit(""))
        self.assertFalse(privacy_hit(None))


class SanitizeAiOutputTest(unittest.TestCase):
    def test_clean_text_passes_through_unchanged(self):
        text = "在图书馆，镜头替我记住了这一刻"
        self.assertEqual(sanitize_ai_output(text), text)

    def test_flagged_text_is_dropped(self):
        self.assertIsNone(sanitize_ai_output("加我约炮"))
        self.assertIsNone(sanitize_ai_output("你就是个脑残"))

    def test_privacy_in_ai_output_is_dropped(self):
        """视觉模型可能从照片里读出手机号或宿舍号。"""
        self.assertIsNone(sanitize_ai_output("照片里的人手机号是 13812345678"))
        self.assertIsNone(sanitize_ai_output("这是宿舍号 305 的照片"))

    def test_none_stays_none(self):
        self.assertIsNone(sanitize_ai_output(None))

    def test_empty_string_passes(self):
        self.assertEqual(sanitize_ai_output(""), "")

    def test_output_is_not_normalized(self):
        """闸门不能顺手改写通过的内容 —— NFKC 是有损的。"""
        text = "第①餐厅 ㎡ Ⅴ 级"
        self.assertEqual(sanitize_ai_output(text), text, "通过的内容必须原样返回")


if __name__ == "__main__":
    unittest.main()

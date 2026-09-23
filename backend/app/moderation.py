"""本地内容把关层。

确定性、零外部依赖、结果可复现。LLM 负责「生成候选」，这一层负责「把关」。

改这个文件前先读这四条纪律
------------------------------------------------------------------
1. **纯标准库**（re + unicodedata），不 import fastapi / sqlalchemy / models。
   这样才能用毫秒级单测直接调用，且不依赖 httpx、DB 或 import 顺序。

2. **归一化结果只用于匹配，绝不写回数据库或返回给用户。**
   NFKC 是有损的（①→1、Ⅴ→V、㎡→m2、连字），把折叠后的文本存库或返回
   等于静默篡改用户内容。调用方（public_text）必须 return 原始字符串。

3. **面向用户的文案不回显命中的具体词**，只给类别级原因。
   回显等于把词表教给对抗者。命中细节只进日志。

4. **只有 public_text() 抛异常，privacy_note() 永远只返回字符串。**
   privacy_note 的另一个调用方是 /api/ai/expression-prompt —— 前端拿它给
   「正在输入的草稿」做发布前软提示。让它抛异常会直接废掉发布按钮。

关于词表
------------------------------------------------------------------
这里只放**少量无争议的种子词**，用来验证机制可跑通。正式词表涉及具体
法域与社区标准，必须由维护者从合规渠道获取并人工审校后再上线。

加词的纪律：
- 每条不少于 2 个汉字，不收单字和常用词；
- 不收「由两个常用词拼接而成」的词（去间隔符后会变成跨 token 误伤）；
- 每条新词必须同时配一条「近似但不该命中」的反例测试；
- 「低俗」只收明确露骨内容，**不收泛化粗口** ——「卧槽 / 我靠 / 服了」
  这类语气词在校园吐槽里是正常表达，收进去会大面积误伤；
- 「辱骂」只收**指向人**的攻击词，不收泛化脏话；
- 「私聊我」在本产品语义里是正常社交动作（私聊就是核心功能），不能单收。
  广告类靠 COOCCURRENCE 共现规则，不靠单词。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["Flag", "screen", "sanitize_ai_output", "privacy_hit", "CATEGORY_MESSAGES"]


# --- 面向用户的文案（只给类别级原因，不含命中词） ---------------------------

CATEGORY_MESSAGES: dict[str, str] = {
    "abuse": "内容包含人身攻击，请修改后再发布。",
    "ad": "内容疑似广告或引流信息，请修改后再发布。",
    "adult": "内容包含不适宜公开的信息，请修改后再发布。",
    "illegal": "内容涉嫌违法或危险行为，请修改后再发布。",
}


@dataclass(frozen=True)
class Flag:
    """一次命中。message 给用户看，rule_id 只进日志。"""

    category: str
    rule_id: str
    message: str


def _flag(category: str, rule_id: str) -> Flag:
    return Flag(category=category, rule_id=rule_id, message=CATEGORY_MESSAGES[category])


# --- 词表 -------------------------------------------------------------------

TERMS: dict[str, tuple[str, ...]] = {
    # 只收指向人的攻击词。不收泛化粗口（见文件头「加词的纪律」）。
    "abuse": ("傻逼", "脑残", "贱人", "杂种"),
    # 只收明确露骨内容。
    "adult": ("约炮", "裸聊", "招嫖", "卖淫", "一夜情"),
    "illegal": (
        "代考", "替考", "赌博", "博彩", "赌球", "六合彩",
        "毒品", "冰毒", "大麻", "枪支", "洗钱", "刷单", "校园贷",
    ),
    "ad": ("返利", "日结", "扫码领", "免费领", "内部渠道", "限时秒杀"),
}

# 共现规则：(rule_id, category, A 组, B 组)。
# 同一段内 A 组和 B 组各命中至少一个才算，用来抓组合式的广告话术，
# 避免把「私聊」这种正常社交动作单收成违禁词。
COOCCURRENCE: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "ad.solicit",
        "ad",
        ("私聊", "加我", "加微信", "扫码", "联系我", "扣我"),
        ("领取", "名额", "福利", "优惠", "兼职", "返现", "免费送", "代理"),
    ),
)


# --- 归一化 -----------------------------------------------------------------


# 强句末标点：切段用。
_SENTENCE_SPLIT = re.compile(r"[。！？!?；;…\n\r]+")

# 段内要去掉的间隔符（空格、星号、点、横线、引号括号等）。
_SEPARATORS = re.compile(r"[\s*·.\-_~|/+\\'\"“”‘’()（）\[\]【】<>《》]+")


def _strip_format(text: str) -> str:
    """去掉零宽与格式字符（U+200B、U+FEFF 等）。

    用 Unicode 的 Cf 类别判定，而不是把不可见字符写成字面量——后者在源码里
    既看不出来也改不动，而且容易漏。
    """
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _fold(text: str) -> str:
    """匹配用的折叠视图：NFKC → 去零宽 → casefold。

    只用于匹配。**不要**用它替换要返回或入库的原文（见文件头纪律 2）。
    """
    value = unicodedata.normalize("NFKC", text)
    value = _strip_format(value)
    return value.casefold()


def _segments(text: str) -> list[str]:
    """按句末标点切段，**段内**再去掉空白与间隔符。

    必须先切段再去间隔符。如果对整段做压缩，「我当时太傻了。逼着自己学了
    一晚上」会拼出「傻逼」，正常内容被硬拦。按句切段后，「傻 逼」「傻*逼」
    这类真绕过仍然命中，跨句拼接不会。

    已知取舍：没有句末标点时，段内去空格会把紧邻的两字拼起来 ——「他真傻
    逼得我」会命中「傻逼」。空格既是绕过手段也是天然词边界，无法两全；这里
    选择保住「傻 逼」这类更常见的绕过。所以词表不收短词和拼接词。

    注意「太傻了 逼着我学」**不会**命中：中间夹着一个「了」，只有「傻」「逼」
    两字紧邻才算。逗号同理 —— 它既不在切段符里也不在间隔符里，天然是边界。
    """
    folded = _fold(text)
    return [_SEPARATORS.sub("", part) for part in _SENTENCE_SPLIT.split(folded)]


# import 时预折叠一次，请求期零重复计算。
_TERM_INDEX: tuple[tuple[str, str, str], ...] = tuple(
    (category, term, _fold(term)) for category, terms in TERMS.items() for term in terms
)
_COOCCURRENCE_INDEX: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = tuple(
    (rule_id, category, tuple(_fold(a) for a in group_a), tuple(_fold(b) for b in group_b))
    for rule_id, category, group_a, group_b in COOCCURRENCE
)


# --- 隐私信息（正则） -------------------------------------------------------

# 与 social.privacy_note 历史上用的规则保持一致，单点维护。
_PRIVACY_PATTERN = re.compile(
    r"(?<!\d)1[3-9]\d{9}(?!\d)|(?<!\d)\d{17}[\dXx](?!\w)|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}"
)
_PRIVACY_WORDS = ("宿舍号", "手机号", "身份证", "老师姓名", "班级群")


def privacy_hit(text: str) -> bool:
    """是否含手机号 / 身份证号 / 邮箱 / 身份类关键词。

    与违禁词分开：隐私是「建议移除」，违禁是「拒绝发布」，文案与处置都不同。
    """
    if not text:
        return False
    return bool(_PRIVACY_PATTERN.search(text)) or any(word in text for word in _PRIVACY_WORDS)


# --- 对外入口 ---------------------------------------------------------------


def screen(text: str | None) -> Flag | None:
    """检查一段用户可见的文本。命中返回 Flag，干净返回 None。

    只查违禁词。隐私信息走 privacy_hit()，因为两者文案与处置不同。
    """
    if not text:
        return None
    segments = _segments(text)
    for category, _term, needle in _TERM_INDEX:
        if any(needle in segment for segment in segments):
            return _flag(category, f"term.{category}")
    for rule_id, category, group_a, group_b in _COOCCURRENCE_INDEX:
        for segment in segments:
            if any(a in segment for a in group_a) and any(b in segment for b in group_b):
                return _flag(category, rule_id)
    return None


def sanitize_ai_output(text: str | None) -> str | None:
    """AI 输出的闸门。命中（违禁词或隐私信息）返回 None，调用方丢弃该条。

    AI 输出要额外查隐私：视觉模型可能从照片里读出手机号、宿舍号。
    """
    if text is None:
        return None
    if privacy_hit(text) or screen(text):
        return None
    return text

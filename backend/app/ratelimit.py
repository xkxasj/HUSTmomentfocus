"""发布侧频控：把「一个人刷屏」挡在写库之前。

这是工业界那套审核流水线里**「风控策略引擎」的最小形态** —— 只做频控计数，
不做设备指纹、账号画像、分级阈值、Redis 计数器。之所以只做这一层，是因为
审核系统的复杂度是被**对抗强度**推出来的，不是被内容量推出来的：小红书要
pHash 查重、向量库、CNN 抽帧，因为对面是职业黑产；校园场景的对手是同学发
牢骚。对抗强度低的时候，确定性词表 + 频控就是正确答案，不是降级方案。

**零新表、零迁移。** 直接数现有表里该用户最近 N 秒的行数 —— 四个目标表
（moments / echoes / suggestion_feedback）都有 `user_id` 索引和 `created_at`，
所以现在就能跑，不需要 Redis，也不需要服务器。

规模上来之后怎么换
------------------------------------------------------------------
**只改这个文件。** 把 `_recent_count()` 换成 Redis 的 INCR+EXPIRE 或滑动
窗口，调用方一行都不用动。同理，将来要加「分级处置」（低风险仅自己可见、
高风险拒绝），也在这一层加 —— 调用方现在拿到的是 HTTPException，将来换成
返回一个 decision 对象即可。

**没有环境变量开关。** 和 moderation.py 一样：一个能被静默关掉的限流本身
就是风险。改限流数走代码评审。

已知代价
------------------------------------------------------------------
`/api/ai/suggestion-feedback` 是前端 fire-and-forget 调的（`void api.xxx()`，
见 useCampusApp.ts:121、:303）。所以那一档一旦触发 429，用户看不到任何提示，
只是**静默丢掉一次训练语料**。这是有意的取舍：宁可丢语料，也不让这个接口
变成无限写入的存储滥用面。所以它的限额定得比前两档宽松得多。

不在这里做的事
------------------------------------------------------------------
- **不审内容。** 内容把关在 moderation.py，两件事分开：把关决定「这条能不能
  发」，频控决定「这个人现在还能不能发」。
- **不做举报频控。** `reports` 上已有 UniqueConstraint(reporter_id, target_type,
  target_id)，同一个人无法重复举报同一目标；要加也只是多一个调用点。
- **不做全局限流**（如所有用户合计 QPS）。那要按服务器容量定，现在没服务器。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Quota:
    """一档配额。name 只用于日志与排错，message 给用户看。"""

    name: str
    limit: int
    window_seconds: int
    message: str


# 限额取得**明显偏宽**：现在不知道真实规模，定紧了会误伤正常使用，而定松了
# 只是少挡一点滥用。下面这些数字对正常用户几乎不可能触发 —— 实测一个很活跃
# 的用户 10 分钟也就发 1-2 条动态。
#
# 要调就调这三个数，别的都不用动。
MOMENT = Quota(
    name="moment",
    limit=10,
    window_seconds=600,
    message="发布太频繁了，歇一会儿再发吧。",
)
ECHO = Quota(
    name="echo",
    limit=20,
    window_seconds=600,
    message="回声发得太频繁了，歇一会儿再试。",
)
# 前端每发一条动态 / 一条消息就调一次，所以这档必须比前两档宽得多，
# 否则长会话里会静默丢语料（见文件头「已知代价」）。
SUGGESTION_FEEDBACK = Quota(
    name="suggestion_feedback",
    limit=120,
    window_seconds=600,
    message="操作太频繁了，歇一会儿再试。",
)


def _recent_count(db: Session, model, user_id: int, since: datetime) -> int:
    """该用户在这张表里 since 之后的行数。

    换成 Redis 时就替换这一个函数。
    """
    return db.scalar(
        select(func.count()).select_from(model).where(
            model.user_id == user_id,
            model.created_at > since,
        )
    ) or 0


def enforce(db: Session, user_id: int, model, quota: Quota) -> None:
    """超配额抛 429。

    只统计**已经写进去**的行，所以「先校验再入库」的路径天然成立：被内容把关
    拒绝的请求根本不会增加计数，不该算在这个人的发布频率里。
    """
    since = datetime.now() - timedelta(seconds=quota.window_seconds)
    if _recent_count(db, model, user_id, since) >= quota.limit:
        raise HTTPException(429, quota.message)

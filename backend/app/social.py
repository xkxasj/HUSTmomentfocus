"""Shared social permissions and the report / consent workflow."""
from datetime import datetime, timedelta
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session, selectinload

from . import moderation
from .admin import audit, get_admin_user
from .auth import get_current_user
from .database import get_db
from .models import ChatMessage, Conversation, Echo, Moment, Report, User, UserBlock
from .schemas import ConversationDecision, ConversationRead, ReportCreate, ReportResolution

router = APIRouter(prefix="/api")


def blocked_pair(db: Session, first: int, second: int | None) -> bool:
    return db.scalar(select(UserBlock.id).where(or_(
        and_(UserBlock.blocker_id == first, UserBlock.blocked_id == second),
        and_(UserBlock.blocker_id == second, UserBlock.blocked_id == first),
    ))) is not None


def conversation_state(row: Conversation) -> str:
    if row.is_blocked:
        return "blocked"
    if row.status in ("pending", "active") and row.expires_at and row.expires_at <= datetime.now():
        return "expired"
    return row.status


def get_conversation(db: Session, conversation_id: int, user: User, writable: bool = False) -> Conversation:
    row = db.scalar(select(Conversation).options(selectinload(Conversation.messages)).where(
        Conversation.id == conversation_id,
        or_(Conversation.initiator_id == user.id, Conversation.recipient_id == user.id),
    ))
    if row is None:
        raise HTTPException(404, "会话不存在")
    peer_id = row.recipient_id if row.initiator_id == user.id else row.initiator_id
    if row.is_blocked or blocked_pair(db, user.id, peer_id):
        raise HTTPException(403, "此会话已被屏蔽")
    peer = db.get(User, peer_id) if peer_id else None
    if writable and (conversation_state(row) != "active" or not peer or not peer.is_active):
        raise HTTPException(409, "会话尚未接受、已结束或已到期，无法发送消息")
    return row


def visible_moment(db: Session, moment_id: int) -> Moment:
    row = db.get(Moment, moment_id)
    if row is None or row.is_hidden:
        raise HTTPException(404, "片段不存在")
    return row


def privacy_note(content: str) -> str | None:
    """A deterministic warning, not a claim of comprehensive content moderation.

    规则本体住在 moderation.privacy_hit()，与 AI 输出的隐私闸门共用同一份实现，
    避免两处正则漂移。

    **这个函数永远只返回字符串，绝不抛异常。** /api/ai/expression-prompt 拿它给
    用户「正在输入的草稿」做发布前提示，抛异常会让发布按钮直接失效。
    """
    if moderation.privacy_hit(content):
        return "内容可能包含手机号、邮箱或其他身份信息，请移除后再发布。"
    return None


def public_text(content: str, allow_empty: bool = False) -> str:
    """公开文本的唯一入口：空 → 隐私 → 违禁，都是硬拦截。

    顺序有意如此：先隐私后违禁，于是同时命中两者的内容拿到的仍是历史上那条隐私
    文案，老行为不变。

    返回的始终是原始 `value`。moderation 内部的 NFKC 折叠只用于匹配，绝不能写回
    或返回给用户 —— NFKC 是有损的（①→1、Ⅴ→V），那是静默的数据篡改。
    """
    value = content.strip()
    if not value and not allow_empty:
        raise HTTPException(400, "内容不能为空")
    note = privacy_note(value)
    if note:
        raise HTTPException(400, note)
    flag = moderation.screen(value)
    if flag:
        raise HTTPException(400, flag.message)
    return value


@router.post("/conversations/{conversation_id}/decision")
def decide(conversation_id: int, payload: ConversationDecision, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_conversation(db, conversation_id, user)
    state = conversation_state(row)
    if payload.action in ("accept", "reject"):
        if user.id != row.recipient_id:
            raise HTTPException(403, "只有接收方可以处理邀请")
        if state != "pending":
            raise HTTPException(409, "邀请已被处理或已过期")
        target = "active" if payload.action == "accept" else "rejected"
    else:
        if state not in ("pending", "active"):
            raise HTTPException(409, "会话已经结束")
        target = "closed"
    now = datetime.now()
    values = {"status": target, "updated_at": now}
    if target == "active":
        values["expires_at"] = now + timedelta(hours=24)
    result = db.execute(update(Conversation).where(
        Conversation.id == row.id, Conversation.status == row.status,
        Conversation.is_blocked.is_(False), Conversation.expires_at > now,
    ).values(**values))
    if not result.rowcount:
        raise HTTPException(409, "会话状态已变化，请刷新后重试")
    db.commit()
    return {"status": target}


@router.post("/conversations/{conversation_id}/read")
def mark_read(conversation_id: int, payload: ConversationRead, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_conversation(db, conversation_id, user)
    if payload.message_id and not any(m.id == payload.message_id for m in row.messages):
        raise HTTPException(400, "消息不属于此会话")
    field = Conversation.initiator_read_id if row.initiator_id == user.id else Conversation.recipient_read_id
    db.execute(update(Conversation).where(Conversation.id == row.id, field < payload.message_id).values({field: payload.message_id}))
    db.commit()
    return {"read": True}


@router.get("/me/blocks")
def list_blocks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(UserBlock, User.alias).join(User, User.id == UserBlock.blocked_id).where(UserBlock.blocker_id == user.id)).all()
    return [{"id": row.id, "alias": alias, "created_at": row.created_at} for row, alias in rows]


@router.delete("/me/blocks/{block_id}")
def unblock(block_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(UserBlock).where(UserBlock.id == block_id, UserBlock.blocker_id == user.id))
    if row is None:
        raise HTTPException(404, "屏蔽记录不存在")
    db.delete(row)
    db.commit()
    return {"unblocked": True}


@router.post("/reports", status_code=201)
def report(payload: ReportCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reason = payload.reason.strip()
    if len(reason) < 2:
        raise HTTPException(400, "请填写举报原因")
    if payload.target_type == "moment":
        row = visible_moment(db, payload.target_id)
        evidence = json.dumps({"content": row.content, "image_url": row.image_url}, ensure_ascii=False)
    elif payload.target_type == "echo":
        row = db.get(Echo, payload.target_id)
        if row is None or row.is_hidden:
            raise HTTPException(404, "回声不存在")
        visible_moment(db, row.moment_id)
        evidence = row.content
    else:
        # Participants can report even after blocking; no general chat-reading admin API.
        row = db.scalar(select(Conversation).options(selectinload(Conversation.messages)).where(
            Conversation.id == payload.target_id,
            or_(Conversation.initiator_id == user.id, Conversation.recipient_id == user.id),
        ))
        if row is None:
            raise HTTPException(404, "会话不存在")
        evidence = json.dumps([{"role": "举报人" if m.sender_user_id == user.id else "对方", "content": m.content}
                               for m in row.messages[-20:]], ensure_ascii=False)
    db.execute(insert(Report).values(reporter_id=user.id, target_type=payload.target_type,
        target_id=payload.target_id, reason=reason, evidence=evidence).on_conflict_do_nothing(
            index_elements=["reporter_id", "target_type", "target_id"]))
    db.commit()
    return {"reported": True}


@router.get("/admin/reports")
def reports(admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Report).order_by((Report.status == "pending").desc(), Report.created_at.desc()).limit(200))
    return [{"id": r.id, "target_type": r.target_type, "target_id": r.target_id, "reason": r.reason,
             "evidence": r.evidence, "status": r.status, "resolution": r.resolution,
             "created_at": r.created_at} for r in rows]


@router.patch("/admin/reports/{report_id}")
def resolve_report(report_id: int, payload: ReportResolution, admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    row = db.get(Report, report_id)
    if row is None:
        raise HTTPException(404, "举报不存在")
    if row.status != "pending":
        raise HTTPException(409, "举报已处理")
    if len(payload.note.strip()) < 2:
        raise HTTPException(400, "请填写处理说明")
    if payload.action == "hide":
        if row.target_type not in ("moment", "echo"):
            raise HTTPException(400, "会话只能结束，不能隐藏")
        target = db.get(Moment if row.target_type == "moment" else Echo, row.target_id)
        if target:
            target.is_hidden = True
    elif payload.action == "close":
        if row.target_type != "conversation":
            raise HTTPException(400, "只有会话可以结束")
        target = db.get(Conversation, row.target_id)
        if target:
            target.status = "closed"
    row.status = "dismissed" if payload.action == "dismiss" else "resolved"
    row.resolution = payload.note.strip()
    row.resolved_at = datetime.now()
    audit(db, admin, f"report_{payload.action}", "report", row.id)
    db.commit()
    return {"status": row.status}

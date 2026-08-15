from datetime import datetime, time, timedelta
from statistics import median
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .auth import get_current_user, hash_password
from .database import SessionLocal, get_db
from .models import AdminAuditLog, AnalyticsEvent, ChatMessage, Conversation, Moment, User
from .schemas import AdminMomentVisibilityUpdate, AdminUserStatusUpdate, AnalyticsEventCreate


router = APIRouter(prefix="/api")


def user_profile(user: User) -> dict:
    return {
        "id": user.id,
        "student_id": user.student_id,
        "email": user.email,
        "alias": user.alias,
        "share_location": user.share_location,
        "is_admin": user.is_admin,
    }


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return user


def bootstrap_admin() -> None:
    student_id = os.getenv("MOUKE_ADMIN_STUDENT_ID", "").strip().upper()
    email = os.getenv("MOUKE_ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("MOUKE_ADMIN_PASSWORD", "")
    if not student_id and not email and not password:
        return
    if not student_id or not email or len(password) < 12:
        raise RuntimeError("管理员初始化需要完整账号信息和至少 12 位密码")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(or_(User.student_id == student_id, User.email == email)))
        if user is None:
            user = User(
                student_id=student_id,
                email=email,
                password_hash=hash_password(password),
                alias="某刻管理员",
                is_active=True,
                is_admin=True,
            )
            db.add(user)
        else:
            user.is_admin = True
            user.is_active = True
            user.password_hash = hash_password(password)
        db.commit()


def audit(db: Session, admin: User, action: str, target_type: str, target_id: int) -> None:
    db.add(AdminAuditLog(
        admin_user_id=admin.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
    ))


@router.post("/analytics/events", status_code=201)
def record_event(
    payload: AnalyticsEventCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db.add(AnalyticsEvent(
        user_id=user.id,
        event_name=payload.event_name,
        session_id=payload.session_id,
        page=payload.page,
        duration_seconds=payload.duration_seconds,
    ))
    db.commit()
    return {"recorded": True}


def retention_metric(db: Session, days: int, now: datetime) -> dict:
    users = list(db.scalars(select(User).where(
        User.created_at <= now - timedelta(days=days),
        User.is_admin.is_(False),
    )))
    if not users:
        return {"days": days, "eligible": 0, "retained": 0, "rate": None}
    retained = 0
    for user in users:
        target = user.created_at.date() + timedelta(days=days)
        start = datetime.combine(target, time.min)
        active = db.scalar(select(func.count()).select_from(AnalyticsEvent).where(
            AnalyticsEvent.user_id == user.id,
            AnalyticsEvent.created_at >= start,
            AnalyticsEvent.created_at < start + timedelta(days=1),
        ))
        if active:
            retained += 1
    return {
        "days": days,
        "eligible": len(users),
        "retained": retained,
        "rate": round(retained / len(users) * 100, 1),
    }


@router.get("/admin/overview")
def admin_overview(admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    now = datetime.now()
    today = datetime.combine(now.date(), time.min)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    total_users = db.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(False))) or 0
    new_today = db.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(False), User.created_at >= today)) or 0
    active_users = select(func.count(func.distinct(AnalyticsEvent.user_id))).join(User, User.id == AnalyticsEvent.user_id).where(User.is_admin.is_(False))
    dau = db.scalar(active_users.where(AnalyticsEvent.created_at >= today)) or 0
    wau = db.scalar(active_users.where(AnalyticsEvent.created_at >= week_ago)) or 0
    mau = db.scalar(active_users.where(AnalyticsEvent.created_at >= month_ago)) or 0
    moments_today = db.scalar(select(func.count()).select_from(Moment).where(Moment.created_at >= today, Moment.is_hidden.is_(False))) or 0
    messages_today = db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.created_at >= today)) or 0
    conversations_today = db.scalar(select(func.count()).select_from(Conversation).where(Conversation.updated_at >= today)) or 0

    session_rows = db.execute(select(
        AnalyticsEvent.session_id,
        func.max(AnalyticsEvent.duration_seconds),
    ).where(
        AnalyticsEvent.event_name == "session_ping",
        AnalyticsEvent.created_at >= month_ago,
    ).group_by(AnalyticsEvent.session_id)).all()
    durations = [row[1] for row in session_rows if row[1] is not None]

    daily = []
    for offset in range(13, -1, -1):
        day = now.date() - timedelta(days=offset)
        start = datetime.combine(day, time.min)
        end = start + timedelta(days=1)
        daily.append({
            "date": day.isoformat(),
            "new_users": db.scalar(select(func.count()).select_from(User).where(User.is_admin.is_(False), User.created_at >= start, User.created_at < end)) or 0,
            "active_users": db.scalar(select(func.count(func.distinct(AnalyticsEvent.user_id))).join(User, User.id == AnalyticsEvent.user_id).where(User.is_admin.is_(False), AnalyticsEvent.created_at >= start, AnalyticsEvent.created_at < end)) or 0,
            "messages": db.scalar(select(func.count()).select_from(ChatMessage).where(ChatMessage.created_at >= start, ChatMessage.created_at < end)) or 0,
        })

    conversations = list(db.scalars(select(Conversation).options(selectinload(Conversation.messages)).where(Conversation.updated_at >= month_ago)))
    replied = 0
    reply_minutes: list[float] = []
    for conversation in conversations:
        senders = {message.sender_user_id for message in conversation.messages if message.sender_user_id is not None}
        if len(senders) >= 2:
            replied += 1
        for previous, current in zip(conversation.messages, conversation.messages[1:]):
            if previous.sender_user_id != current.sender_user_id:
                reply_minutes.append(max(0, (current.created_at - previous.created_at).total_seconds() / 60))
                break

    return {
        "generated_at": now,
        "users": {"total": total_users, "new_today": new_today, "dau": dau, "wau": wau, "mau": mau},
        "content": {"moments_today": moments_today, "messages_today": messages_today, "conversations_today": conversations_today},
        "sessions": {
            "count_30d": len(durations),
            "average_minutes": round(sum(durations) / len(durations) / 60, 1) if durations else None,
            "median_minutes": round(median(durations) / 60, 1) if durations else None,
        },
        "retention": [retention_metric(db, days, now) for days in (1, 7, 30)],
        "chat": {
            "conversations_30d": len(conversations),
            "replied_conversations_30d": replied,
            "reply_rate": round(replied / len(conversations) * 100, 1) if conversations else None,
            "median_first_reply_minutes": round(median(reply_minutes), 1) if reply_minutes else None,
        },
        "daily": daily,
    }


@router.get("/admin/users")
def admin_users(admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = list(db.scalars(select(User).order_by(User.created_at.desc()).limit(500)))
    last_seen = dict(db.execute(select(AnalyticsEvent.user_id, func.max(AnalyticsEvent.created_at)).group_by(AnalyticsEvent.user_id)).all())
    moment_counts = dict(db.execute(select(Moment.user_id, func.count()).where(Moment.user_id.is_not(None)).group_by(Moment.user_id)).all())
    message_counts = dict(db.execute(select(ChatMessage.sender_user_id, func.count()).where(ChatMessage.sender_user_id.is_not(None)).group_by(ChatMessage.sender_user_id)).all())
    return [{
        **user_profile(user),
        "is_active": user.is_active,
        "created_at": user.created_at,
        "last_seen_at": last_seen.get(user.id),
        "moment_count": moment_counts.get(user.id, 0),
        "message_count": message_counts.get(user.id, 0),
    } for user in users]


@router.patch("/admin/users/{user_id}/status")
def admin_user_status(
    user_id: int,
    payload: AdminUserStatusUpdate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    if target.id == admin.id and not payload.is_active:
        raise HTTPException(400, "不能停用自己的管理员账号")
    target.is_active = payload.is_active
    audit(db, admin, "activate_user" if payload.is_active else "deactivate_user", "user", target.id)
    db.commit()
    return {"updated": True, "is_active": target.is_active}


@router.get("/admin/moments")
def admin_moments(admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(Moment).options(selectinload(Moment.location)).order_by(Moment.created_at.desc()).limit(500)))
    return [{
        "id": row.id,
        "author_alias": row.author_alias,
        "content": row.content,
        "image_url": row.image_url,
        "location_name": row.location.name,
        "created_at": row.created_at,
        "is_hidden": row.is_hidden,
    } for row in rows]


@router.patch("/admin/moments/{moment_id}/visibility")
def admin_moment_visibility(
    moment_id: int,
    payload: AdminMomentVisibilityUpdate,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
):
    moment = db.get(Moment, moment_id)
    if moment is None:
        raise HTTPException(404, "内容不存在")
    moment.is_hidden = payload.is_hidden
    audit(db, admin, "hide_moment" if payload.is_hidden else "restore_moment", "moment", moment.id)
    db.commit()
    return {"updated": True, "is_hidden": moment.is_hidden}


@router.get("/admin/audit-logs")
def admin_audit_logs(admin: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    rows = list(db.scalars(select(AdminAuditLog).order_by(AdminAuditLog.created_at.desc()).limit(200)))
    return [{
        "id": row.id,
        "admin_user_id": row.admin_user_id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "detail": row.detail,
        "created_at": row.created_at,
    } for row in rows]

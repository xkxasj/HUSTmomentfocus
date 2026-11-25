from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.orm import Session

from .auth import get_current_user
from .database import get_db
from .models import Conversation, Echo, Moment, User
from .schemas import EchoCreate
from .social import public_text

router = APIRouter(prefix="/api")


class MomentEdit(BaseModel):
    content: str = Field(max_length=280)


def owned(db, model, target_id, user):
    row = db.get(model, target_id)
    if not row or row.user_id != user.id or row.is_deleted:
        raise HTTPException(404, "内容不存在或不属于你")
    return row


@router.patch("/moments/{moment_id}")
def edit_moment(moment_id: int, payload: MomentEdit, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = owned(db, Moment, moment_id, user)
    if row.is_hidden:
        raise HTTPException(409, "已被隐藏的内容无法编辑")
    content = public_text(payload.content, allow_empty=bool(row.image_url))
    row.content = content
    db.commit()
    return {"updated": True}


@router.delete("/moments/{moment_id}")
def delete_moment(moment_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = owned(db, Moment, moment_id, user)
    db.execute(update(Conversation).where(Conversation.origin_moment_id == row.id).values(origin_moment_id=None, origin_excerpt="原片段已删除"))
    # Keep IDs reserved: SQLite may reuse hard-deleted IDs and misdirect old reports.
    row.is_deleted = True
    row.is_hidden = True
    row.content = ""
    row.image_url = None
    for echo in row.echoes:
        echo.is_deleted = True
        echo.is_hidden = True
        echo.content = ""
    row.resonances.clear()
    db.commit()
    return {"deleted": True}


@router.patch("/echoes/{echo_id}")
def edit_echo(echo_id: int, payload: EchoCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = owned(db, Echo, echo_id, user)
    if row.is_hidden or db.get(Moment, row.moment_id).is_hidden:
        raise HTTPException(409, "已被隐藏的内容无法编辑")
    row.content = public_text(payload.content)
    db.commit()
    return {"updated": True}


@router.delete("/echoes/{echo_id}")
def delete_echo(echo_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = owned(db, Echo, echo_id, user)
    row.is_deleted = True
    row.is_hidden = True
    row.content = ""
    db.commit()
    return {"deleted": True}

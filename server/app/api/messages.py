"""
站内消息用户侧（Spec §6.5）：
收件箱分页（box=all/unread/read 已读态筛选）、未读计数、详情打开即已读、全部已读 read-all
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import Message, MessageRecipient, User
from .deps import get_current_user

router = APIRouter(prefix="/api/messages", tags=["站内消息"])


def _read_cond(box: str):
    """box → read_at 条件（all 不加条件）"""
    if box == "unread":
        return MessageRecipient.read_at.is_(None)
    if box == "read":
        return MessageRecipient.read_at.is_not(None)
    return None


@router.get("")
def list_messages(
    box: str = Query("all", pattern="^(all|unread|read)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conds = [MessageRecipient.user_id == user.id]
    box_cond = _read_cond(box)
    if box_cond is not None:
        conds.append(box_cond)
    total = db.scalar(
        select(func.count())
        .select_from(MessageRecipient)
        .join(Message, Message.id == MessageRecipient.message_id)
        .where(*conds)
    )
    rows = db.execute(
        select(Message, MessageRecipient.read_at)
        .join(MessageRecipient, MessageRecipient.message_id == Message.id)
        .where(*conds)
        .order_by(Message.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        {
            "id": m.id,
            "title": m.title,
            "content": m.content,
            "read": read_at is not None,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m, read_at in rows
    ]
    return {"code": 0, "msg": "", "data": {"items": items, "total": total, "page": page, "page_size": page_size}}


@router.get("/unread-count")
def unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    cnt = db.scalar(
        select(func.count()).select_from(MessageRecipient).where(
            MessageRecipient.user_id == user.id,
            MessageRecipient.read_at.is_(None),
        )
    )
    return {"code": 0, "msg": "", "data": {"count": cnt}}


@router.post("/read-all")
def read_all(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """全部标记已读（FE-2 我的消息页「全部已读」依赖）"""
    res = db.execute(
        update(MessageRecipient)
        .where(MessageRecipient.user_id == user.id, MessageRecipient.read_at.is_(None))
        .values(read_at=datetime.now())
    )
    db.commit()
    return {"code": 0, "msg": "", "data": {"updated": res.rowcount}}


@router.get("/{message_id}")
def message_detail(message_id: int, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """详情并置 read_at=now()；非本人收件 403、不存在 404"""
    row = db.execute(
        select(Message, MessageRecipient)
        .join(MessageRecipient, MessageRecipient.message_id == Message.id)
        .where(Message.id == message_id, MessageRecipient.user_id == user.id)
    ).first()
    if row is None:
        if db.get(Message, message_id) is None:
            raise HTTPException(404, "消息不存在")
        raise HTTPException(403, "非本人收件，无权查看")
    msg, rec = row
    if rec.read_at is None:
        rec.read_at = datetime.now()  # 打开即已读
        db.commit()
    return {
        "code": 0,
        "msg": "",
        "data": {
            "id": msg.id,
            "title": msg.title,
            "content": msg.content,
            "sender_id": msg.sender_id,
            "read": True,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        },
    }

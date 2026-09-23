"""T22 管理端消息发送（Spec §6.5）：单人/按区域/按单位三口径（一律 ∩ scope）+ 已发列表已读统计
- target_type: user=user_id；region=区域码（市码展开整市=全市群发）；station=派出所名
- station 双口径：传 stations=[{name, region_code}]（单位多选，名+区县收紧重名）或
  legacy target_value=单名字符串（全局名匹配，老前端兼容）
- 收件人一律 ∩ scope，越界部分忽略并回 sent/skipped 计数
- 已发列表：本人 sender_id 的消息，含收件数（recipient 数）与已读数（read_at IS NOT NULL 计数）
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import Message, MessageRecipient, Region, User
from ...schemas import ok
from ...services import audit
from ...services.messaging import send_message
from ..deps import require_admin, resolve_scope

router = APIRouter(prefix="/messages", tags=["管理端-消息发送"])


class StationRef(BaseModel):
    name: str          # 单位名（与 User.police_station 同口径）
    region_code: str   # 所属区县码（同名单位跨区县重名时收紧匹配）


class MessageSendBody(BaseModel):
    target_type: str              # user / region / station
    target_value: Any = None      # user=user_id(int)；region=区域码；station=派出所名（legacy 单值）
    title: str
    content: str
    stations: list[StationRef] | None = None   # station 多选：[{name, region_code}]


def _expand_region(db: Session, code: str) -> list[str]:
    """区域码及其全部下级（市码=全市群发）"""
    result, queue = [code], [code]
    while queue:
        children = db.scalars(select(Region.code).where(Region.parent_code.in_(queue))).all()
        queue = [c for c in children if c not in result]
        result.extend(queue)
    return result


@router.post("")
def send_admin_message(
    payload: MessageSendBody,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if payload.target_type == "user":
        try:
            candidates = [int(str(payload.target_value).strip())]
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="按人员发送时 target_value 必须是用户 id（数字）")
    elif payload.target_type == "region":
        codes = _expand_region(db, str(payload.target_value))
        candidates = [u.id for u in db.query(User).filter(User.region_code.in_(codes)).all()]
    elif payload.target_type == "station":
        if payload.stations is not None:
            # 多选：{名+区县} 收紧匹配（同名单位跨区县重名不误伤）
            refs = [r for r in payload.stations if r.name.strip()]
            if not refs:
                raise HTTPException(status_code=400, detail="按单位发送时 stations 不能为空")
            for r in refs:
                if db.get(Region, r.region_code) is None:
                    raise HTTPException(status_code=400, detail=f"区县码不存在：{r.region_code}")
            conds = [
                and_(User.police_station == r.name,
                     User.region_code.in_(_expand_region(db, r.region_code)))
                for r in refs
            ]
            candidates = [u.id for u in db.query(User).filter(or_(*conds)).all()]
        else:
            # legacy：单名字符串全局匹配（老前端兼容）
            candidates = [u.id for u in db.query(User).filter(User.police_station == str(payload.target_value)).all()]
    else:
        raise HTTPException(status_code=400, detail="target_type 仅支持 user/region/station")

    scope = resolve_scope(db, admin)
    in_scope_ids: list[int] = []
    for uid in candidates:
        u = db.get(User, uid)
        if u is not None and (scope is None or u.region_code in scope):
            in_scope_ids.append(uid)

    send_message(db, in_scope_ids, payload.title, payload.content, sender_id=admin.id)
    target_desc = (payload.target_value if payload.stations is None else
                   "、".join(f"{r.name}@{r.region_code}" for r in payload.stations))
    audit.queue_audit(operate_type=audit.OP_CREATE, operate_name="消息发送", user=admin, request=request,
                      operate_condition=(f"执行了[站内消息发送]功能，操作参数为[对象类型：{payload.target_type}"
                                         f"||对象：{target_desc}||实际送达：{len(in_scope_ids)} 人]。"),
                      display=f"标题：{payload.title}"[:200], data_level=1)
    return ok({"sent": len(in_scope_ids), "skipped": len(candidates) - len(in_scope_ids)})


@router.get("")
def list_sent_messages(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total = db.scalar(
        select(func.count()).select_from(Message).where(Message.sender_id == admin.id))
    rows = db.execute(
        select(Message, func.count(MessageRecipient.id), func.count(MessageRecipient.read_at))
        .outerjoin(MessageRecipient, MessageRecipient.message_id == Message.id)
        .where(Message.sender_id == admin.id)
        .group_by(Message.id)
        .order_by(Message.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [
        {
            "id": m.id,
            "title": m.title,
            "content": m.content,
            "created_at": m.created_at.isoformat() if m.created_at else None,
            "recipient_count": rc,
            "read_count": rdc,
        }
        for m, rc, rdc in rows
    ]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})

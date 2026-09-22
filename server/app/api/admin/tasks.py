"""T21 任务管理（Spec §5.2/§6.4）：辖区任务列表 + 单人/批量下达 + 调整/取消 + 下达自动站内信
下达规则：
- 目标用户必须在 scope 内（否则 403）
- 已有 active 同类型 → 更新 target_count/note（base_count 不变）
- 已有 cancelled / 无 → 新建（base_count = 当前存量快照）
- 每次成功下达（含批量逐人）send_message(uid, "新任务", ...)
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import Task, User
from ...schemas import ok
from ...services.messaging import send_message
from ...services.task_progress import progress_map
from ..deps import require_admin, resolve_scope, scope_filter

router = APIRouter(prefix="/tasks", tags=["管理端-任务管理"])

_TYPE_LABEL = {"recording": "录音", "annotation": "标注"}
_TYPE_PAGE = {"recording": "录音采集", "annotation": "录音标注"}
_DONE_KEY = {"recording": "recording_done", "annotation": "annotation_done"}


class TaskAssignBody(BaseModel):
    user_id: int
    type: str
    target_count: int
    note: str = ""


class TaskBatchBody(BaseModel):
    user_ids: List[int]
    type: str
    target_count: int
    note: str = ""


class TaskUpdateBody(BaseModel):
    target_count: Optional[int] = None
    note: Optional[str] = None
    status: Optional[str] = None


def _stock(db: Session, user_id: int, ttype: str) -> int:
    return progress_map(db, [user_id])[user_id][_DONE_KEY[ttype]]


def _notify(db: Session, user_id: int, ttype: str, target_count: int, sender_id: int) -> None:
    send_message(
        db, [user_id], "新任务",
        f"管理员给你下达了{_TYPE_LABEL[ttype]}任务：{target_count} 条，请前往「{_TYPE_PAGE[ttype]}」完成。",
        sender_id=sender_id,
    )


def _assign_one(db: Session, admin: User, user_id: int, ttype: str,
                target_count: int, note: str) -> None:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    scope = resolve_scope(db, admin)
    if scope is not None and user.region_code not in scope:
        raise HTTPException(status_code=403, detail="无权给辖区外用户下达任务")

    active = db.scalars(
        select(Task).where(Task.user_id == user_id, Task.type == ttype, Task.status == "active")
    ).first()
    if active is not None:
        active.target_count = target_count
        if note:
            active.note = note
        db.commit()
    else:
        task = Task(user_id=user_id, type=ttype, target_count=target_count,
                    base_count=_stock(db, user_id, ttype), status="active",
                    note=note, created_by=admin.id)
        db.add(task)
        db.commit()
    _notify(db, user_id, ttype, target_count, admin.id)


@router.get("")
def list_tasks(
    real_name: str | None = Query(None),
    type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    scope = resolve_scope(db, admin)
    query = (
        db.query(Task, User)
        .join(User, Task.user_id == User.id)
        .filter(scope_filter(User.region_code, scope))
    )
    if real_name:
        query = query.filter(User.real_name.like(f"%{real_name}%"))
    if type:
        query = query.filter(Task.type == type)
    if status:
        query = query.filter(Task.status == status)

    total = query.count()
    rows = (query.order_by(Task.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())

    prog = progress_map(db, [t.user_id for t, _ in rows])
    items = [
        {
            "id": t.id,
            "user_id": t.user_id,
            "real_name": u.real_name,
            "police_station": u.police_station,
            "type": t.type,
            "target_count": t.target_count,
            "base_count": t.base_count,
            "done": max(0, prog[t.user_id][_DONE_KEY[t.type]] - t.base_count),
            "status": t.status,
            "note": t.note,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t, u in rows
    ]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.post("")
def assign_task(
    payload: TaskAssignBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _assign_one(db, admin, payload.user_id, payload.type, payload.target_count, payload.note)
    return ok(msg="下达成功")


@router.post("/batch")
def assign_batch(
    payload: TaskBatchBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    for uid in payload.user_ids:
        _assign_one(db, admin, uid, payload.type, payload.target_count, payload.note)
    return ok(msg=f"已下达 {len(payload.user_ids)} 人")


@router.put("/{task_id}")
def update_task(
    task_id: int,
    payload: TaskUpdateBody,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    task = db.get(Task, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    user = db.get(User, task.user_id)
    scope = resolve_scope(db, admin)
    if scope is not None and (user is None or user.region_code not in scope):
        raise HTTPException(status_code=403, detail="无权操作辖区外任务")

    if payload.target_count is not None:
        task.target_count = payload.target_count
    if payload.note is not None:
        task.note = payload.note
    if payload.status is not None:
        if payload.status == "cancelled":
            task.status = "cancelled"
        elif payload.status == "active":
            task.status = "active"
            task.base_count = _stock(db, task.user_id, task.type)  # 恢复激活重拍快照
        else:
            raise HTTPException(status_code=400, detail="status 仅支持 active/cancelled")
    db.commit()
    return ok(msg="操作成功")

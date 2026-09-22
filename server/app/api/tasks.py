"""
我的任务进度（用户侧，Spec §6.4 用户端）
GET /api/tasks/my → recording/annotation 两类 active 任务及进度，无 active 任务为 null
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import Task, User
from .deps import get_current_user
from ..services.task_progress import progress_map

router = APIRouter(prefix="/api/tasks", tags=["我的任务"])

_DONE_KEY = {"recording": "recording_done", "annotation": "annotation_done"}


def _my_task(db: Session, user_id: int, ttype: str) -> dict | None:
    """本人某类型 active 任务的进度载荷；done 下限 0、超额如实（Spec §5.2）"""
    task = db.scalars(
        select(Task)
        .where(Task.user_id == user_id, Task.type == ttype, Task.status == "active")
        .order_by(Task.id.desc())
    ).first()
    if task is None:
        return None
    valid = progress_map(db, [user_id])[user_id][_DONE_KEY[ttype]]
    return {
        "target_count": task.target_count,
        "base_count": task.base_count,
        "done": max(0, valid - task.base_count),
        "status": task.status,
        "note": task.note,
    }


@router.get("/my")
def my_tasks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        "code": 0,
        "msg": "",
        "data": {
            "recording": _my_task(db, user.id, "recording"),
            "annotation": _my_task(db, user.id, "annotation"),
        },
    }

"""T18 管理端录音管理：scope 列表（行含 用户姓名/文本/类别/方言/时长/大小/质检状态/时间 + file_url）
试听直接复用用户侧 /api/recordings/{id}/file（P-media 已放行管理员 scope 命中，本包不改该端点）
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import Recording, Text, User
from ...schemas import ok
from ..deps import require_admin, resolve_scope, scope_filter

router = APIRouter(prefix="/recordings", tags=["管理端-录音管理"])


@router.get("")
def list_recordings(
    region: str | None = Query(None),
    category: str | None = Query(None),
    q: str | None = Query(None),
    qc_status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    scope = resolve_scope(db, admin)
    query = (
        db.query(Recording, Text, User)
        .outerjoin(Text, Recording.text_id == Text.id)
        .outerjoin(User, Recording.user_id == User.id)
        .filter(scope_filter(Recording.region_code, scope))
    )
    if region:
        query = query.filter(Recording.region_code == region)
    if category:
        query = query.filter(Text.category == category)
    if qc_status:
        query = query.filter(Recording.qc_status == qc_status)
    if q:
        query = query.filter(Text.content.like(f"%{q}%"))

    total = query.count()
    rows = (query.order_by(Recording.created_at.desc(), Recording.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())

    items = [
        {
            "id": rec.id,
            "user_id": rec.user_id,
            "user_name": user.real_name if user else "",
            "text_content": text.content if text else "（文本已删除）",
            "category": text.category if text else "",
            "dialect": text.dialect if text else "",
            "region_code": rec.region_code,
            "duration": rec.duration,
            "file_size": rec.file_size,
            "qc_status": rec.qc_status,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
            "file_url": f"/api/recordings/{rec.id}/file",
        }
        for rec, text, user in rows
    ]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})

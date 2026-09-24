"""管理端转译记录：scope 辖区列表（行含 录制人/状态/文件/时长/识别结果/时间 + file_url）
试听直接复用用户侧 /api/transcriptions/{id}/file（权限已放行管理员 scope 命中，本包不改该端点）。
仅列表 + 播放，不做管理端删改（转译记录归上传民警本人所有）。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import Transcription, User
from ...schemas import ok
from ..deps import require_admin, resolve_scope, scope_filter

router = APIRouter(prefix="/transcriptions", tags=["管理端-转译记录"])


@router.get("")
def list_transcriptions(
    region: str | None = Query(None),
    status: str | None = Query(None),
    corrected: bool | None = Query(None),
    file_ext: str | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    scope = resolve_scope(db, admin)
    query = (db.query(Transcription, User)
             .outerjoin(User, Transcription.user_id == User.id)
             .filter(scope_filter(Transcription.region_code, scope)))
    if region:
        query = query.filter(Transcription.region_code == region)
    if status:
        query = query.filter(Transcription.status == status)
    if corrected is True:
        query = query.filter(Transcription.text_fixed != "")
    elif corrected is False:
        query = query.filter(Transcription.text_fixed == "")
    if file_ext:
        query = query.filter(Transcription.file_ext == file_ext)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Transcription.file_name.like(like),
                                 Transcription.text_raw.like(like),
                                 Transcription.text_fixed.like(like)))

    total = query.count()
    rows = (query.order_by(Transcription.created_at.desc(), Transcription.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())

    items = [
        {
            "id": row.id,
            "user_id": row.user_id,
            "user_name": user.real_name if user else "",
            "region_code": row.region_code,
            "file_name": row.file_name,
            "file_ext": row.file_ext,
            "file_size": row.file_size,
            "duration": row.duration,
            "status": row.status,
            "text_raw": row.text_raw,
            "text_fixed": row.text_fixed,
            "error_message": row.error_message,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "file_url": f"/api/transcriptions/{row.id}/file",
        }
        for row, user in rows
    ]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})

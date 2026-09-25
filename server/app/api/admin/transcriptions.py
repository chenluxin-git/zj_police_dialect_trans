"""管理端转译记录：层级辖区列表（本级+下级全部，行含 录制人/区域/状态/文件/时长/识别结果/时间 + file_url）
- region 筛选支持整域：省/市码 BFS 展开下级后 ∩ 本人 scope（越界码返回空页，不放大视野）
- q 关键词命中 文件名 / 识别原文 / 修正文本 / 录制人姓名
试听直接复用用户侧 /api/transcriptions/{id}/file（权限已放行管理员 scope 命中，本包不改该端点）。
仅列表 + 播放，不做管理端删改（转译记录归上传民警本人所有）。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import Region, Transcription, User
from ...schemas import ok
from ..deps import require_admin, resolve_scope, scope_filter

router = APIRouter(prefix="/transcriptions", tags=["管理端-转译记录"])


def _expand_region(db: Session, code: str) -> list[str]:
    """code 及其全部下级（BFS；省/市码可整域筛选，与 admin/users 同口径）"""
    result, queue = [code], [code]
    while queue:
        children = list(db.scalars(select(Region.code).where(Region.parent_code.in_(queue))).all())
        queue = [c for c in children if c not in result]
        result.extend(queue)
    return result


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
        expanded = _expand_region(db, region)
        codes = expanded if scope is None else [c for c in expanded if c in scope]
        if not codes:
            return ok({"items": [], "total": 0, "page": page, "page_size": page_size})
        query = query.filter(Transcription.region_code.in_(codes))
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
                                 Transcription.text_fixed.like(like),
                                 User.real_name.like(like)))

    total = query.count()
    rows = (query.order_by(Transcription.created_at.desc(), Transcription.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    names = {r.code: r.name for r in db.scalars(select(Region)).all()}

    items = [
        {
            "id": row.id,
            "user_id": row.user_id,
            "user_name": user.real_name if user else "",
            "region_code": row.region_code,
            "region_name": names.get(row.region_code, row.region_code or ""),
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

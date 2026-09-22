"""T18 管理端标注管理：scope 列表（行含 译者与音频 id）+ 删标注回池
删标注即删行：进度回退由 progress_map 实时口径自然实现，音频因 file_id 唯一约束自动回到可标注池
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import Annotation, AudioFile, User
from ...schemas import ok
from ..deps import require_admin, resolve_scope, scope_filter

router = APIRouter(prefix="/annotations", tags=["管理端-标注管理"])


@router.get("")
def list_annotations(
    region: str | None = Query(None),
    is_dialect: bool | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    scope = resolve_scope(db, admin)
    query = (
        db.query(Annotation, AudioFile, User)
        .outerjoin(AudioFile, Annotation.file_id == AudioFile.id)
        .outerjoin(User, Annotation.annotator_id == User.id)
        .filter(scope_filter(Annotation.region_code, scope))
    )
    if region:
        query = query.filter(Annotation.region_code == region)
    if is_dialect is not None:
        query = query.filter(Annotation.is_dialect == is_dialect)
    if q:
        query = query.filter(Annotation.translation.like(f"%{q}%"))

    total = query.count()
    rows = (query.order_by(Annotation.created_at.desc(), Annotation.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())

    items = [
        {
            "id": ann.id,
            "file_id": ann.file_id,
            "annotator_id": ann.annotator_id,
            "annotator_name": user.real_name if user else "",
            "is_dialect": ann.is_dialect,
            "translation": ann.translation,
            "region_code": ann.region_code,
            "file_name": af.file_name if af else "",
            "created_at": ann.created_at.isoformat() if ann.created_at else None,
        }
        for ann, af, user in rows
    ]
    return ok({"items": items, "total": total, "page": page, "page_size": page_size})


@router.delete("/{annotation_id}")
def delete_annotation(
    annotation_id: int,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    ann = db.get(Annotation, annotation_id)
    if ann is None:
        raise HTTPException(status_code=404, detail="标注不存在")
    scope = resolve_scope(db, admin)
    if scope is not None and ann.region_code not in scope:
        raise HTTPException(status_code=403, detail="无权删除辖区外标注")
    db.delete(ann)
    db.commit()
    return ok(msg="删除成功")

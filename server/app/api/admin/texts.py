"""T16 管理端文本管理：scope 列表（category/q/日期/区域）+ 批量删除（跳过被录音引用/越界项并回显 {deleted, skipped}）
移植自旧项目 app/api/admin/texts.py（机制见规格 §6.9），差异：
- 权限由 resolve_scope / scope_filter 统一推导（替代旧 if-else 分支）
- 批量删除语义：旧实现任一被引用即整体 400；本版按 L2 裁定改为跳过被引用/越界/不存在项并在响应回显 skipped 明细
- 信封统一 from app.schemas import ok
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...models import Recording, Region, Text, User
from ...schemas import ok
from ...services import audit
from ..deps import require_admin, resolve_scope, scope_filter

router = APIRouter(prefix="/texts", tags=["管理端-文本管理"])


class BatchDeleteBody(BaseModel):
    ids: list[int]


def _text_dict(t: Text) -> dict:
    return {"id": t.id, "content": t.content, "dialect": t.dialect, "category": t.category,
            "region_code": t.region_code, "dialect_code": t.dialect_code,
            "created_at": t.created_at.isoformat()}


@router.get("")
def list_texts(
    category: str | None = None,
    region_code: str | None = None,
    q: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    scope = resolve_scope(db, admin)
    query = db.query(Text).filter(scope_filter(Text.region_code, scope))
    # 仅超管（scope=None）可传 region_code 下钻：市码展开全市，区县码精确匹配
    if region_code and scope is None:
        region = db.get(Region, region_code)
        if region is not None:
            codes = [region_code]
            if region.level == "city":
                codes += [r.code for r in db.query(Region).filter(Region.parent_code == region_code)]
            query = query.filter(Text.region_code.in_(codes))
    if category:
        query = query.filter(Text.category == category)
    if q:
        query = query.filter(Text.content.contains(q))
    if date_start:
        query = query.filter(Text.created_at >= datetime.strptime(date_start, "%Y-%m-%d"))
    if date_end:
        query = query.filter(Text.created_at <= datetime.strptime(date_end, "%Y-%m-%d")
                             .replace(hour=23, minute=59, second=59))

    total = query.count()
    rows = (query.order_by(Text.created_at.desc(), Text.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return ok({"total": total, "page": page, "page_size": page_size,
               "items": [_text_dict(t) for t in rows]})


@router.delete("/batch")
def delete_texts_batch(body: BatchDeleteBody, request: Request, admin: User = Depends(require_admin),
                       db: Session = Depends(get_db)):
    scope = resolve_scope(db, admin)
    deleted: list[int] = []
    skipped: list[int] = []
    for tid in body.ids:
        t = db.get(Text, tid)
        if t is None:                       # 不存在
            skipped.append(tid)
            continue
        if scope is not None and t.region_code not in scope:  # 越界
            skipped.append(tid)
            continue
        if db.query(Recording.id).filter(Recording.text_id == tid).first():  # 被录音引用
            skipped.append(tid)
            continue
        db.delete(t)
        deleted.append(tid)
    db.commit()
    audit.queue_audit(operate_type=audit.OP_DELETE, operate_name="文本批量删除", user=admin, request=request,
                      operate_condition=(f"执行了[文本批量删除]功能，操作参数为[请求删除：{len(body.ids)} 条"
                                         f"||实际删除：{len(deleted)} 条||跳过：{len(skipped)} 条]。"),
                      display=f"删除ID={deleted[:50]}", data_level=1)
    return ok({"deleted": deleted, "skipped": skipped})
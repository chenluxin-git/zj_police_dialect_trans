"""T7 文本分配（2 分钟惰性锁）+ 自定义文本
移植自旧项目 app/api/texts.py（机制见规格 §6.1/§9）：
- assign：先全局惰性删除过期锁 → 本人已有有效锁则直接返回该文本（顺带续期）→
  否则候选池随机一条（未被锁占、本人未录过、本区或空区匹配）
- 无可用文本：HTTP 404 + code=1（信封）
- custom：入库 category=custom、region_code=用户区域、方言取该区域方言名，并自动分配给本人
"""
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..api.deps import get_current_user
from ..core.database import get_db
from ..models import Dialect, Recording, Text, TextAssignment, User
from ..schemas.text import ApiResponse, AssignTextData, CustomTextIn

router = APIRouter(prefix="/texts", tags=["文本分配"])

LOCK_SECONDS = 120  # 文本分配锁 120 秒（Global Constraints）


def _payload(text: Text, remaining: int) -> AssignTextData:
    return AssignTextData(
        text_id=text.id,
        content=text.content,
        category=text.category,
        dialect=text.dialect,
        region_code=text.region_code or "",
        dialect_code=text.dialect_code or "",
        remaining_seconds=remaining,
    )


# -------------------- 静态路径优先（须先于 /assign/{id} 声明） --------------------

@router.delete("/assign/expired", response_model=ApiResponse)
def delete_expired_assignments(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """回收本人全部过期分配（页面刷新时清理用）"""
    expired = datetime.now() - timedelta(seconds=LOCK_SECONDS)
    deleted = db.query(TextAssignment).filter(
        TextAssignment.user_id == current_user.id,
        TextAssignment.assigned_at <= expired,
    ).delete()
    db.commit()
    return ApiResponse(msg=f"已清理 {deleted} 条过期分配")


# -------------------- 带参数路径 --------------------

@router.post("/assign/{text_id}/refresh", response_model=ApiResponse)
def refresh_assignment(
    text_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """续期：重置 assigned_at（换一条录音过程中防超时）"""
    if db.query(Recording).filter(Recording.text_id == text_id).first() is not None:
        raise HTTPException(status_code=400, detail="该文本已被录制")
    assignment = db.query(TextAssignment).filter(
        TextAssignment.text_id == text_id,
        TextAssignment.user_id == current_user.id,
    ).first()
    if not assignment:
        raise HTTPException(status_code=403, detail="您没有分配此文本，请重新获取")
    assignment.assigned_at = datetime.now()
    db.commit()
    return ApiResponse(msg="分配已续期")


@router.delete("/assign/{text_id}", response_model=ApiResponse)
def release_assignment(
    text_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """放弃分配：物理删除本人的分配记录（「换一条」）"""
    assignment = db.query(TextAssignment).filter(
        TextAssignment.text_id == text_id,
        TextAssignment.user_id == current_user.id,
    ).first()
    if assignment:
        db.delete(assignment)
        db.commit()
    return ApiResponse(msg="分配已释放")


# -------------------- 领取 / 自定义 --------------------

@router.post("/assign", response_model=ApiResponse[AssignTextData])
def assign_text(
    category: str | None = Query(None, description="文本类别：police/life/dirty/place/custom"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    now = datetime.now()
    expired = now - timedelta(seconds=LOCK_SECONDS)

    # 1) 惰性回收：全局删除过期锁（谁碰到谁清理，与旧项目一致）
    db.query(TextAssignment).filter(TextAssignment.assigned_at <= expired).delete()
    db.commit()

    # 2) 本人已有有效锁：直接返回同一文本并顺带续期
    existing = db.query(TextAssignment).filter(
        TextAssignment.user_id == current_user.id,
    ).first()
    if existing:
        text = db.get(Text, existing.text_id)
        if text and (category is None or text.category == category):
            existing.assigned_at = now
            db.commit()
            return ApiResponse[AssignTextData](data=_payload(text, LOCK_SECONDS))
        db.delete(existing)  # 类别不匹配：释放后重新领
        db.commit()

    # 3) 候选池：未被任何锁占用 + 本人未录过 + 本区或空区匹配（保留旧写法一条 SQL）
    sub_assigned = db.query(TextAssignment.text_id)
    sub_recorded = db.query(Recording.text_id).filter(Recording.user_id == current_user.id)
    query = db.query(Text).filter(
        ~Text.id.in_(sub_assigned),
        ~Text.id.in_(sub_recorded),
    )
    if current_user.region_code:
        query = query.filter(
            (Text.region_code == current_user.region_code)
            | (Text.region_code == None)  # noqa: E711  SQLAlchemy 需要 is-null 比较
            | (Text.region_code == "")
        )
    if category:
        query = query.filter(Text.category == category)

    candidates = query.all()
    if not candidates:
        return JSONResponse(status_code=404, content={"code": 1, "msg": "暂无可用文本", "data": None})

    selected = random.choice(candidates)
    db.add(TextAssignment(text_id=selected.id, user_id=current_user.id, assigned_at=now))
    db.commit()
    return ApiResponse[AssignTextData](data=_payload(selected, LOCK_SECONDS))


@router.post("/custom", response_model=ApiResponse[AssignTextData])
def create_custom_text(
    payload: CustomTextIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """自定义文本：入库即自动分配给本人（category=custom、区域随用户、方言随区域）"""
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="文本内容不能为空")

    dialect_name, dialect_code = "", ""
    if current_user.region_code:
        d = db.query(Dialect).filter(Dialect.region_code == current_user.region_code).first()
        if d:
            dialect_name, dialect_code = d.name, d.code

    text = Text(
        content=content,
        dialect=dialect_name,
        category="custom",
        region_code=current_user.region_code or "",
        dialect_code=dialect_code,
    )
    db.add(text)
    db.flush()
    db.add(TextAssignment(text_id=text.id, user_id=current_user.id, assigned_at=datetime.now()))
    db.commit()
    return ApiResponse[AssignTextData](data=_payload(text, LOCK_SECONDS))

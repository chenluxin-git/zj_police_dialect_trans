r"""T10 标注作业（移植自旧 app/api/annotations.py）：
- 3 分钟（180s）惰性锁：next 先全局物理删除过期分配，再随机领一条未被标注且未被分配的音频
- 区域口径沿用旧项目：音频 region_code 等于用户 region_code 或为空（None/"")才可领
- 一条音频一条标注（annotations.file_id 唯一约束兜底）；translation 必填 400（已取消是否方言判定）
- next 契约 {file_id, file_name, file_url, region_code, dialect_code}；无货 HTTP 404 + code=1
- Annotation.region_code 取自音频文件（模型新增列，非空）；时间基准统一本地 datetime.now()
  （与模型列 default 一致，不得混用 utcnow，否则 8 小时偏移导致锁立即过期）
- 信封 {code,msg,data}：统一 from ..schemas import ok（集成收敛，原包内联实现已删）
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import Annotation, AudioFile, FileAssignment, User
from ..schemas import ok
from ..schemas.annotation import AnnotationCreate
from .deps import get_current_user

router = APIRouter(prefix="/annotations", tags=["标注"])

LOCK = timedelta(seconds=180)  # 音频分配锁 3 分钟（全局约束）


def _purge_expired(db: Session) -> int:
    """全局物理删除过期分配（惰性回收，不限当前用户，解决遗留冲突）"""
    deleted = db.query(FileAssignment).filter(
        FileAssignment.assigned_at <= datetime.now() - LOCK).delete()
    if deleted:
        db.commit()
    return deleted


def _ann_dict(ann: Annotation, f: AudioFile | None) -> dict:
    return {"id": ann.id, "file_id": ann.file_id,
            "file_name": f.file_name if f else "（文件已删除）",
            "translation": ann.translation,
            "region_code": ann.region_code,
            "created_at": ann.created_at.isoformat() if ann.created_at else None}


@router.get("/next")
def next_audio(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _purge_expired(db)
    annotated = select(Annotation.file_id)
    assigned = select(FileAssignment.file_id)
    f = (db.query(AudioFile)
         .filter(~AudioFile.id.in_(annotated), ~AudioFile.id.in_(assigned),
                 (AudioFile.region_code == current_user.region_code)
                 | (AudioFile.region_code.is_(None)) | (AudioFile.region_code == ""))
         .order_by(func.random())
         .first())
    if f is None:
        return JSONResponse(status_code=404, content={"code": 1, "msg": "暂无待标注音频", "data": None})
    db.add(FileAssignment(file_id=f.id, user_id=current_user.id, assigned_at=datetime.now()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "分配冲突，请重试")
    return ok({"file_id": f.id, "file_name": f.file_name,
               "file_url": f"/api/audio/files/{f.id}/file",
               "region_code": f.region_code, "dialect_code": f.dialect_code})


@router.post("")
def submit_annotation(body: AnnotationCreate,
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.get(AudioFile, body.file_id)
    if f is None:
        raise HTTPException(404, "音频文件不存在")
    if db.scalar(select(Annotation).where(Annotation.file_id == body.file_id)) is not None:
        raise HTTPException(400, "该音频已被标注")
    if not body.translation.strip():
        raise HTTPException(400, "请填写普通话翻译文本")
    a = db.query(FileAssignment).filter_by(file_id=body.file_id, user_id=current_user.id).first()
    if a is None:
        raise HTTPException(403, "您没有分配此文件，无法提交标注")
    if a.assigned_at <= datetime.now() - LOCK:
        db.delete(a)
        db.commit()
        raise HTTPException(403, "分配已过期，请重新获取")
    ann = Annotation(file_id=f.id, annotator_id=current_user.id, is_dialect=True,
                     translation=body.translation.strip(),
                     region_code=f.region_code)
    db.add(ann)
    db.delete(a)
    db.commit()
    db.refresh(ann)
    return ok(_ann_dict(ann, f))


@router.get("/my")
def my_annotations(page: int = 1, page_size: int = 20,
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = (db.query(Annotation).filter(Annotation.annotator_id == current_user.id)
         .order_by(Annotation.created_at.desc(), Annotation.id.desc()))
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    items = [_ann_dict(a, db.get(AudioFile, a.file_id)) for a in rows]
    return ok({"total": total, "page": page, "page_size": page_size, "items": items})


@router.get("/my/dialect-count")
def my_dialect_count(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """已取消是否方言判定：口径改为我的标注总数（路径保留兼容旧前端）"""
    n = db.query(Annotation).filter_by(annotator_id=current_user.id).count()
    return ok(n)


@router.put("/{annotation_id}")
def update_annotation(annotation_id: int, body: AnnotationCreate,
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ann = db.query(Annotation).filter_by(id=annotation_id, annotator_id=current_user.id).first()
    if ann is None:
        raise HTTPException(404, "标注不存在或无权限修改")
    if ann.file_id != body.file_id:
        raise HTTPException(400, "标注与文件不匹配")
    if not body.translation.strip():
        raise HTTPException(400, "请填写普通话翻译文本")
    ann.translation = body.translation.strip()
    db.commit()
    return ok(msg="更新成功")


@router.delete("/{annotation_id}")
def delete_annotation(annotation_id: int,
                      current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ann = db.query(Annotation).filter_by(id=annotation_id, annotator_id=current_user.id).first()
    if ann is None:
        raise HTTPException(404, "标注不存在或无权限删除")
    db.delete(ann)
    db.commit()
    return ok(msg="删除成功")


@router.post("/assign/{file_id}/refresh")
def refresh_assignment(file_id: int,
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.scalar(select(Annotation).where(Annotation.file_id == file_id)) is not None:
        raise HTTPException(400, "该音频已被标注")
    a = db.query(FileAssignment).filter_by(file_id=file_id, user_id=current_user.id).first()
    if a is None:
        raise HTTPException(403, "您没有分配此文件，请重新获取")
    a.assigned_at = datetime.now()
    db.commit()
    return ok(msg="分配已刷新")


@router.delete("/assign/expired")
def clear_my_expired(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    deleted = db.query(FileAssignment).filter(
        FileAssignment.user_id == current_user.id,
        FileAssignment.assigned_at <= datetime.now() - LOCK).delete()
    db.commit()
    return ok(msg=f"已清理 {deleted} 条过期标注分配")

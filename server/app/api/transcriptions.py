r"""语音转译（工作台）：音视频上传 → 后台泵串行识别 → 前端轮询
- 复用 recordings 的转码契约：convert_to_wav（容器 ffmpeg 全量，mp4/mov 直接解音轨，
  视频无需前端抽轨）+ _ffmpeg_sem 并发限流 + _user_folder 落盘布局
- 落盘 {audio_storage_path}/{user_folder}/trans/{id}.wav（trans/ 子目录，与录音
  {id}.wav 撞号隔离）；识别由 services/transcription.py::trans_loop 后台泵驱动，
  上传即回 pending 行，工作台 3s 轮询 ?ids= 批量取状态
- 修正语义（dome 定稿）：text == text_raw → text_fixed=""（改回原文=撤销修正）
- GET /{id}/file 权限与录音一致：本人 或 管理员且 region_code ∈ resolve_scope
  （管理端「转译记录」页直接复用本端点，不再扩展）
"""
import asyncio
import logging
import os

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..api.deps import get_current_user, resolve_scope
from ..api.recordings import _ffmpeg_sem, _user_folder, convert_to_wav
from ..core.config import settings
from ..core.database import get_db
from ..models import Transcription, User
from ..schemas.transcription import (
    ApiResponse,
    PageData,
    TranscriptionFixIn,
    TranscriptionItem,
)
from ..services import audit

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/transcriptions", tags=["语音转译"])

TRANS_MAX_BYTES = 50 * 1024 * 1024    # 单文件 50MB（nginx client_max_body_size 100m 内）
TRANS_MAX_DURATION = 900.0            # 15 分钟
TRANS_ALLOWED_EXTS = {"wav", "mp3", "m4a", "webm", "mp4", "mov"}
TRANS_MAX_POLL_IDS = 50               # 工作台 ids 批量轮询上限


def _item(row: Transcription) -> TranscriptionItem:
    return TranscriptionItem(
        id=row.id, file_name=row.file_name, file_ext=row.file_ext,
        file_size=row.file_size, duration=row.duration, status=row.status,
        text_raw=row.text_raw, text_fixed=row.text_fixed,
        corrected=row.text_fixed != "",
        error_message=row.error_message,
        created_at=row.created_at,
        file_url=f"/api/transcriptions/{row.id}/file",
    )


def _remove_file(path: str) -> None:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            logger.warning("删除转译文件失败 %s", path)


@router.post("", response_model=ApiResponse[TranscriptionItem])
async def create_transcription(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    name = file.filename or ""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in TRANS_ALLOWED_EXTS:
        raise HTTPException(status_code=400,
                            detail=f"不支持的文件格式，仅限 {' / '.join(sorted(TRANS_ALLOWED_EXTS))}")
    src = await file.read()
    if not src:
        raise HTTPException(status_code=400, detail="文件为空")
    if len(src) > TRANS_MAX_BYTES:
        raise HTTPException(status_code=400, detail="文件超过 50MB 上限")

    row = Transcription(user_id=current_user.id,
                        region_code=current_user.region_code or "",
                        file_name=name, file_ext=ext, file_path="",
                        file_size=len(src), duration=0.0, status="pending")
    db.add(row)
    db.commit()  # 先入库拿 id，再以 trans/{id}.wav 定名落盘（与录音上传同构）

    trans_dir = os.path.join(settings.audio_storage_path, _user_folder(current_user), "trans")
    os.makedirs(trans_dir, exist_ok=True)
    final_path = os.path.join(trans_dir, f"{row.id}.wav")
    try:
        async with _ffmpeg_sem:  # 与录音上传共用并发限流，转换本体走线程池
            duration = await asyncio.to_thread(convert_to_wav, src, final_path)
    except Exception as e:
        db.delete(row)
        db.commit()
        logger.error("用户 %s 转译音频转换失败 %s: %s", current_user.id, name, e)
        raise HTTPException(status_code=500, detail="音频转换失败，请检查文件后重试")
    if duration > TRANS_MAX_DURATION:
        _remove_file(final_path)
        db.delete(row)
        db.commit()
        raise HTTPException(status_code=400, detail="音频超过 15 分钟上限")

    row.file_path = final_path
    row.duration = duration
    db.commit()
    logger.info("用户 %s 转译上传成功 transcription=%s (%s, %.1fs)",
                current_user.id, row.id, name, duration)
    audit.queue_audit(operate_type=audit.OP_CREATE, operate_name="语音转译", user=current_user, request=request,
                      operate_condition=f"执行了[语音转译]功能，操作参数为[文件：{name}||时长：{duration:.2f}s]。",
                      display=f"转译记录ID={row.id}，字节数={row.file_size}", data_level=2)
    return ApiResponse[TranscriptionItem](data=_item(row))


@router.get("", response_model=ApiResponse[PageData[TranscriptionItem]])
def list_my_transcriptions(
    status: str | None = None,
    corrected: bool | None = None,
    file_ext: str | None = None,
    q: str | None = None,
    ids: str | None = Query(None, description="逗号分隔 id 批量轮询（≤50，超出截断）"),
    active: int = 0,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(Transcription).filter(Transcription.user_id == current_user.id)
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
    if active:
        query = query.filter(Transcription.status.in_(["pending", "processing"]))
    if ids is not None:
        id_list = [int(p) for p in ids.split(",") if p.strip().isdigit()][:TRANS_MAX_POLL_IDS]
        if not id_list:
            return ApiResponse[PageData[TranscriptionItem]](data=PageData[TranscriptionItem](
                total=0, page=page, page_size=page_size, items=[]))
        query = query.filter(Transcription.id.in_(id_list))

    total = query.count()
    rows = (query.order_by(Transcription.created_at.desc(), Transcription.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())
    return ApiResponse[PageData[TranscriptionItem]](data=PageData[TranscriptionItem](
        total=total, page=page, page_size=page_size, items=[_item(r) for r in rows]))


def _get_owned(db: Session, transcription_id: int, user: User) -> Transcription:
    row = db.get(Transcription, transcription_id)
    if row is None:
        raise HTTPException(status_code=404, detail="转译记录不存在")
    if row.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")
    return row


@router.get("/{transcription_id}", response_model=ApiResponse[TranscriptionItem])
def get_transcription(
    transcription_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """本人单条（工作台轮询兜底）"""
    return ApiResponse[TranscriptionItem](data=_item(_get_owned(db, transcription_id, current_user)))


@router.get("/{transcription_id}/file")
def download_transcription(
    transcription_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """转译音频流：本人 或 管理员且 region_code ∈ scope（管理端复用本端点）"""
    row = db.get(Transcription, transcription_id)
    if row is None:
        raise HTTPException(status_code=404, detail="转译记录不存在")
    if row.user_id != current_user.id:
        if current_user.role not in ("admin", "super_admin"):
            raise HTTPException(status_code=403, detail="无权访问")
        scope = resolve_scope(db, current_user)
        if scope is not None and row.region_code not in scope:
            raise HTTPException(status_code=403, detail="无权访问辖区外录音")
    if not row.file_path or not os.path.exists(row.file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(row.file_path, media_type="audio/wav",
                        filename=os.path.basename(row.file_path))


@router.post("/{transcription_id}/fix", response_model=ApiResponse[TranscriptionItem])
def fix_transcription(
    transcription_id: int,
    payload: TranscriptionFixIn,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修正识别结果：改回原文 = 撤销修正（text_fixed 回 ""）；仅 done 可修正"""
    row = _get_owned(db, transcription_id, current_user)
    if row.status != "done":
        raise HTTPException(status_code=400, detail="仅完成的记录可修正")
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="修正文本不能为空")
    row.text_fixed = "" if text == row.text_raw else text
    db.commit()
    audit.queue_audit(operate_type=audit.OP_UPDATE, operate_name="转译修正", user=current_user, request=request,
                      operate_condition=f"执行了[转译修正]功能，操作参数为[转译ID：{transcription_id}]。",
                      display=f"转译记录ID={row.id}，{'撤销' if row.text_fixed == '' else '保存'}修正", data_level=2)
    return ApiResponse[TranscriptionItem](data=_item(row))


@router.post("/{transcription_id}/retry", response_model=ApiResponse[TranscriptionItem])
def retry_transcription(
    transcription_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重试失败识别：回置 pending、清结果字段（泵下一轮接管）"""
    row = _get_owned(db, transcription_id, current_user)
    if row.status != "failed":
        raise HTTPException(status_code=400, detail="仅失败的记录可重试")
    row.status = "pending"
    row.text_raw = ""
    row.text_fixed = ""
    row.error_message = ""
    db.commit()
    audit.queue_audit(operate_type=audit.OP_UPDATE, operate_name="转译重试", user=current_user, request=request,
                      operate_condition=f"执行了[转译重试]功能，操作参数为[转译ID：{transcription_id}]。",
                      display=f"转译记录ID={row.id}，已重新排队", data_level=2)
    return ApiResponse[TranscriptionItem](data=_item(row))


@router.delete("/{transcription_id}", response_model=ApiResponse)
def delete_transcription(
    transcription_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除本人转译记录：行与盘上文件联动删除（任意状态可删，泵容忍处理中删除竞态）"""
    row = _get_owned(db, transcription_id, current_user)
    fname = row.file_name  # commit 后对象过期，先取审计字段
    _remove_file(row.file_path)
    db.delete(row)
    db.commit()
    audit.queue_audit(operate_type=audit.OP_DELETE, operate_name="删除转译", user=current_user, request=request,
                      operate_condition=f"执行了[删除转译]功能，操作参数为[转译ID：{transcription_id}||文件：{fname}]。",
                      display="删除成功", data_level=2)
    return ApiResponse(msg="删除成功")

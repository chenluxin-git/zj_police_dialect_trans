"""T8 录音上传：webm/opus 经 ffmpeg 转 16k 单声道 WAV、入库即 pending、删除联动删盘上文件
移植自旧项目 app/api/records.py 同名机制（规格 §6.1/§6.2/§9）：
- convert_to_wav(src_bytes, dst_path) -> float 与模块级 _ffmpeg_sem = asyncio.Semaphore(2)
  为产出契约（T19 音频上传线复用；签名不得偏离）
- GET /{id}/file 权限：本人 或 管理员且录音 region_code ∈ resolve_scope（P-media 契约修订，
  T18 管理端直接复用本端点，不再扩展）
"""
import asyncio
import logging
import os
import re
import subprocess

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..api.deps import get_current_user, resolve_scope
from ..core.config import settings
from ..core.database import get_db
from ..models import Dialect, Recording, Text, TextAssignment, User
from ..schemas.recording import ApiResponse, PageData, RecordingItem, UploadResultData

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/recordings", tags=["录音"])

_ffmpeg_sem = asyncio.Semaphore(2)  # ffmpeg 并发限流 2（Global Constraints；T19 复用）


def _ffprobe_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 取时长失败: {r.stderr.strip()[:200]}")
    return float(r.stdout.strip())


def convert_to_wav(src_bytes: bytes, dst_path: str) -> float:
    """原始音频字节 → 16k 单声道 pcm_s16le WAV（stdin 直灌 ffmpeg，不落原始临时文件），返回时长秒"""
    cmd = ["ffmpeg", "-y", "-i", "-", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", dst_path]
    r = subprocess.run(cmd, input=src_bytes, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(f"ffmpeg 转换失败: {err[:200]}")
    return _ffprobe_duration(dst_path)


def _user_folder(user: User) -> str:
    safe = re.sub(r"[^\w\u4e00-\u9fff]", "", user.real_name)  # 重名安全：去非法字符
    tail4 = user.phone[-4:] if len(user.phone) >= 4 else user.phone
    return f"{safe or 'user'}_{tail4}"


@router.post("", response_model=ApiResponse[UploadResultData])
async def upload_recording(
    file: UploadFile = File(...),
    text_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    text = db.get(Text, text_id)
    if text is None:
        raise HTTPException(status_code=404, detail="文本不存在")
    if db.query(Recording).filter_by(user_id=current_user.id, text_id=text_id).first():
        raise HTTPException(status_code=400, detail="该文本已录制过")  # unique(user_id, text_id)

    is_custom = text.category == "custom"
    assignment = db.query(TextAssignment).filter_by(
        text_id=text_id, user_id=current_user.id).first()
    if not is_custom and assignment is None:
        raise HTTPException(status_code=403, detail="您没有分配此文本，请先获取分配")

    dialect_code = ""
    if current_user.region_code:
        d = db.query(Dialect).filter(Dialect.region_code == current_user.region_code).first()
        if d:
            dialect_code = d.code

    user_dir = os.path.join(settings.audio_storage_path, _user_folder(current_user))
    os.makedirs(user_dir, exist_ok=True)
    src = await file.read()

    rec = Recording(user_id=current_user.id, text_id=text_id, file_path="", file_size=0,
                    duration=0.0, region_code=current_user.region_code or "",
                    dialect_code=dialect_code, qc_status="pending")
    db.add(rec)
    db.commit()  # 先入库拿 id，再以 {recording_id}.wav 定名落盘

    final_path = os.path.join(user_dir, f"{rec.id}.wav")
    try:
        async with _ffmpeg_sem:  # 信号量在异步层限流，转换本体走线程池不阻塞事件循环
            duration = await asyncio.to_thread(convert_to_wav, src, final_path)
    except Exception as e:
        db.delete(rec)
        db.commit()
        logger.error("用户 %s 音频转换失败 text=%s: %s", current_user.id, text_id, e)
        raise HTTPException(status_code=500, detail="音频转换失败，请重试")

    rec.file_path = final_path
    rec.duration = duration
    rec.file_size = os.path.getsize(final_path)
    if assignment is not None:  # 上传成功即释放分配
        db.delete(assignment)
    db.commit()
    logger.info("用户 %s 录音上传成功 recording=%s text=%s", current_user.id, rec.id, text_id)
    return ApiResponse[UploadResultData](data=UploadResultData(
        id=rec.id, duration=duration, file_size=rec.file_size, qc_status="pending"))


@router.get("", response_model=ApiResponse[PageData[RecordingItem]])
def list_my_recordings(
    category: str | None = None,
    q: str | None = None,
    qc_status: str | None = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Recording, Text)
        .outerjoin(Text, Recording.text_id == Text.id)
        .filter(Recording.user_id == current_user.id)
    )
    if qc_status:
        query = query.filter(Recording.qc_status == qc_status)
    if category:
        query = query.filter(Text.category == category)
    if q:
        query = query.filter(Text.content.like(f"%{q}%"))

    total = query.count()
    rows = (query.order_by(Recording.created_at.desc(), Recording.id.desc())
            .offset((page - 1) * page_size).limit(page_size).all())

    items = [
        RecordingItem(
            id=rec.id,
            text_id=rec.text_id,
            text_content=text.content if text else "（文本已删除）",
            category=text.category if text else "",
            dialect=text.dialect if text else "",
            duration=rec.duration,
            file_size=rec.file_size,
            qc_status=rec.qc_status,
            created_at=rec.created_at,
            file_url=f"/api/recordings/{rec.id}/file",
        )
        for rec, text in rows
    ]
    return ApiResponse[PageData[RecordingItem]](data=PageData(
        total=total, page=page, page_size=page_size, items=items))


@router.get("/{recording_id}/file")
def download_recording(
    recording_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """录音文件流：本人 或 管理员且录音 region_code ∈ scope（契约修订：T18 管理端直接复用）"""
    rec = db.get(Recording, recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="录音不存在")
    if rec.user_id != current_user.id:
        if current_user.role not in ("admin", "super_admin"):
            raise HTTPException(status_code=403, detail="无权访问")
        scope = resolve_scope(db, current_user)
        if scope is not None and rec.region_code not in scope:
            raise HTTPException(status_code=403, detail="无权访问辖区外录音")
    if not os.path.exists(rec.file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(rec.file_path, media_type="audio/wav",
                        filename=os.path.basename(rec.file_path))


@router.delete("/{recording_id}", response_model=ApiResponse)
def delete_recording(
    recording_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除本人录音：记录与盘上文件联动删除（进度回退由 T12 实时统计口径自然实现）"""
    rec = db.get(Recording, recording_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="录音不存在")
    if rec.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除")
    if rec.file_path and os.path.exists(rec.file_path):
        os.remove(rec.file_path)
    db.delete(rec)
    db.commit()
    return ApiResponse(msg="删除成功")

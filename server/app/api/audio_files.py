"""T11 标注音频流：FileResponse 直出，登录即可听（供标注页播放；移植自旧 app/api/audio_files.py）
media_type 由文件扩展名推断（扫盘导入不止 wav，旧版硬编码 audio/wav 不再适用）
"""
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import AudioFile, User
from .deps import get_current_user

router = APIRouter(prefix="/audio/files", tags=["音频文件"])


@router.get("/{file_id}/file")
def get_audio_file(file_id: int,
                   current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.get(AudioFile, file_id)
    if f is None:
        raise HTTPException(404, "文件不存在")
    if not os.path.exists(f.file_path):
        raise HTTPException(404, "文件在服务器上不存在")
    return FileResponse(f.file_path, filename=f.file_name)

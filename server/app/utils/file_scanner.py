"""T19 服务器扫盘工具：按 7 扩展名递归/非递归收集音频文件绝对路径
移植自旧项目 app/utils/file_scanner.py，扩展名集按计划 T19 调整为
wav/mp3/m4a/wma/amr/aac/ogg（旧集 flac/webm 弃用）。调用方应传绝对路径，保证去重按绝对路径比对。
"""
from pathlib import Path

AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".wma", ".amr", ".aac", ".ogg"}


def scan_audio_files(folder_path: str, recursive: bool = False) -> list[str]:
    """返回目录下音频文件路径列表（folder 非目录时返回空表）"""
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        return []
    it = folder.rglob("*") if recursive else folder.iterdir()
    return [str(p) for p in it if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]

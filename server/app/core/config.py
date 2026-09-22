"""
配置管理模块
pydantic-settings 从环境变量与 .env 文件读取配置，提供全局访问的 settings 对象
（移植自 audio-server-test/app/core/config.py：MySQL 分项配置改为单一 DATABASE_URL，
 JWT 配置改为 SECRET_KEY/ACCESS_TOKEN_EXPIRE_HOURS，新增 ASR 质检与 CORS 配置项）
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类，所有配置项定义在此（字段名小写，环境变量大小写不敏感匹配）"""

    # ---------- 数据库配置 ----------
    database_url: str = "sqlite:///./data/app.db"

    # ---------- 文件存储配置 ----------
    audio_storage_path: str = "./audio_storage"
    export_path: str = "./data/exports"

    # ---------- JWT 配置 ----------
    secret_key: str = "change-me-in-prod"
    access_token_expire_hours: int = 12

    # ---------- CORS 配置（逗号分隔白名单） ----------
    cors_origins: str = "http://localhost:5173"

    # ---------- ASR 方言转译配置（asr_api_url 为空 = 质检停用） ----------
    asr_api_url: str = ""
    asr_timeout: int = 30

    # ---------- 质检配置 ----------
    qc_similarity_threshold: float = 0.5
    qc_max_retry: int = 3
    qc_scan_interval: int = 60

    # ---------- 导入/扫盘运行目录（容器内指向 /data 卷，防侧车台账落容器临时层） ----------
    text_import_dir: str = "data/text_imports"
    audio_import_dir: str = "data/audio_imports"
    scan_root: str = ""   # 扫盘白名单根目录；空=不限制（仅限本机开发），生产/容器必设

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


# 创建全局配置实例，供其他模块导入使用
settings = Settings()

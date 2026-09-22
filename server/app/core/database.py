"""
数据库连接管理模块
创建SQLAlchemy引擎和会话工厂，提供获取数据库会话的依赖项与建表入口
（移植自 audio-server-test/app/core/database.py，保持同步 engine；默认 SQLite，
 去掉 MySQL 专有的 SET time_zone 连接事件——本项目 ORM 层不得使用 MySQL 专有语法）
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings

# SQLite 时需允许跨线程复用连接（FastAPI 同步端点跑在线程池，连接池会跨线程复用）
_is_sqlite = settings.database_url.startswith("sqlite")

# 创建数据库引擎
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,   # 连接前检查，避免使用已断开的连接
    echo=False,           # 生产环境设为False，避免打印SQL语句
    connect_args={"check_same_thread": False} if _is_sqlite else {},
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 所有模型的基类
Base = declarative_base()

def get_db():
    """
    依赖项函数：获取数据库会话
    在请求处理中使用，请求结束后自动关闭会话
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db() -> None:
    """按当前 Base 元数据建表（已存在的表跳过，供 startup 调用）"""
    Base.metadata.create_all(bind=engine)

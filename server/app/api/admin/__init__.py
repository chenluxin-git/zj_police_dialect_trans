"""管理端路由包（/api/admin）
本文件由 P-export（T23）创建；P-admin-users / P-admin-content / P-admin-data 各包合并时在此追加各自路由 import。
"""
from .users import router as users_router                     # P-admin-users(T14)
from .user_import import router as user_import_router         # P-admin-users(T15)
from . import texts, text_import, audio_upload, audio_import  # noqa: F401  # P-admin-content(T16/T17/T19)
from .recordings import router as admin_recordings_router  # P-admin-data(T18)
from .annotations import router as admin_annotations_router  # P-admin-data(T18)
from .stats import router as admin_stats_router  # P-admin-data(T20)
from .tasks import router as admin_tasks_router  # P-admin-data(T21)
from .messages import router as admin_messages_router  # P-admin-data(T22)
from .org_sync import router as admin_org_sync_router  # 浙警智治：统一用户/部门首次初始化与状态

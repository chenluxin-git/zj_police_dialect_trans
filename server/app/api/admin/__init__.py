"""管理端路由包（/api/admin）
本文件由 P-export（T23）创建；P-admin-users / P-admin-content / P-admin-data 各包合并时在此追加各自路由 import。
"""
from .recordings import router as admin_recordings_router  # P-admin-data(T18)
from .annotations import router as admin_annotations_router  # P-admin-data(T18)


"""
任务进度口径服务（Spec §5.2）：实时统计不记流水
- recording：COUNT(recordings WHERE user_id=X AND qc_status='passed')——待质检不计入，
  质检剔除/删除录音自动回退，无需额外处理
- annotation：COUNT(annotations WHERE annotator_id=X)
- 本函数返回**原始有效数**（不扣 base_count）；done = max(0, 有效数 - base_count)
  由调用方（/api/tasks/my 与管理端 T14/T20/T21）按各自任务的 base_count 快照计算
"""
from sqlalchemy import select, func

from ..models import Recording, Annotation


def progress_map(db, user_ids: list[int]) -> dict[int, dict[str, int]]:
    """批量统计一组用户的录音/标注有效数，每类一条 GROUP BY 查询

    Returns: {uid: {"recording_done": 36, "annotation_done": 24}}，未命中用户为零值
    """
    result: dict[int, dict[str, int]] = {
        uid: {"recording_done": 0, "annotation_done": 0} for uid in user_ids
    }
    if not user_ids:
        return result
    for uid, cnt in db.execute(
        select(Recording.user_id, func.count())
        .where(Recording.user_id.in_(user_ids), Recording.qc_status == "passed")
        .group_by(Recording.user_id)
    ):
        result[uid]["recording_done"] = cnt
    for uid, cnt in db.execute(
        select(Annotation.annotator_id, func.count())
        .where(Annotation.annotator_id.in_(user_ids))
        .group_by(Annotation.annotator_id)
    ):
        result[uid]["annotation_done"] = cnt
    return result

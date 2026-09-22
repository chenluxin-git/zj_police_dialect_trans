"""
站内消息发送服务：任务下达自动通知（T21）、质检未通过重录通知（T9）、
管理端消息群发（T22）的统一入口——后端最核心契约，多包消费，签名不得偏离
"""
from ..models import Message, MessageRecipient


def send_message(db, user_ids: list[int], title: str, content: str,
                 sender_id: int | None = None) -> None:
    """建一条 Message + 批量 MessageRecipient 收件记录

    - user_ids 去重（保序），空列表不建消息
    - sender_id=None 表示系统自动消息
    - 事务在本函数内提交（调用方后续再 commit 幂等无害）
    """
    unique_ids = list(dict.fromkeys(user_ids))
    if not unique_ids:
        return
    msg = Message(title=title, content=content, sender_id=sender_id)
    db.add(msg)
    db.flush()  # 先拿到自增 message.id
    db.add_all(MessageRecipient(message_id=msg.id, user_id=uid) for uid in unique_ids)
    db.commit()

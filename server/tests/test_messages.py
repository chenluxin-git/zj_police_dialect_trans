"""T13 站内消息测试（Spec §6.5）：
send_message 批量收件去重、收件分页（box 已读态筛选）、未读计数、详情打开即已读、
非本人收件 403、全部已读 read-all（FE-2 依赖）
注意：conftest 的 auth_header 硬编码用户 id=1，多用户用例显式 create_token(str(user.id))
"""
from datetime import datetime

from app.core.security import create_token
from app.models import Message, MessageRecipient
from tests.conftest import make_user


def _auth(uid: int) -> dict:
    return {"Authorization": f"Bearer {create_token(str(uid))}"}


def _mark_read(db, message_ids: list[int]) -> None:
    db.query(MessageRecipient).filter(
        MessageRecipient.message_id.in_(message_ids)
    ).update({MessageRecipient.read_at: datetime.now()}, synchronize_session=False)
    db.commit()


def test_send_message_dedupes(db):
    """建 1 条 Message + 批量 MessageRecipient；user_ids 去重；sender_id 可空可指定"""
    from app.services.messaging import send_message
    make_user(db)  # id=1
    u2 = make_user(db, phone="33100400003", name="测试民警2")  # id=2
    send_message(db, [1, 1, 2], "标题", "内容", sender_id=None)
    assert db.query(Message).count() == 1
    assert db.query(MessageRecipient).count() == 2  # 去重后 2 条收件
    m = db.query(Message).first()
    assert m.title == "标题" and m.content == "内容" and m.sender_id is None
    send_message(db, [2], "通知", "内容二", sender_id=1)
    m2 = db.query(Message).filter_by(title="通知").one()
    assert m2.sender_id == 1


def test_unread_count_and_detail_marks_read(client, db, auth_header):
    """3 条消息 1 未读 2 已读 → count==1；打开详情后归零；重复打开幂等"""
    from app.services.messaging import send_message
    send_message(db, [1], "消息一", "内容一")
    send_message(db, [1], "消息二", "内容二")
    send_message(db, [1], "消息三", "内容三")
    mids = [m.id for m in db.query(Message).order_by(Message.id).all()]
    _mark_read(db, mids[:2])  # 前两条已读
    r = client.get("/api/messages/unread-count", headers=_auth(1))
    assert r.status_code == 200 and r.json()["code"] == 0
    assert r.json()["data"]["count"] == 1
    r = client.get(f"/api/messages/{mids[2]}", headers=_auth(1))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["title"] == "消息三"
    assert body["data"]["content"] == "内容三"
    assert body["data"]["read"] is True  # 打开即已读
    assert client.get("/api/messages/unread-count", headers=_auth(1)).json()["data"]["count"] == 0
    # 已读后重复打开仍 200
    assert client.get(f"/api/messages/{mids[2]}", headers=_auth(1)).status_code == 200


def test_detail_forbidden_for_non_recipient(client, db, auth_header):
    """非本人收件 403；不存在的消息 404"""
    from app.services.messaging import send_message
    u2 = make_user(db, phone="33100400003", name="测试民警2")
    send_message(db, [1], "仅给用户1", "内容")
    mid = db.query(Message).first().id
    assert client.get(f"/api/messages/{mid}", headers=_auth(u2.id)).status_code == 403
    assert client.get("/api/messages/9999", headers=_auth(1)).status_code == 404


def test_list_pagination_and_box_filter(client, db, auth_header):
    """分页字段（total/page/page_size）与最新在前；box=unread/read 筛选"""
    from app.services.messaging import send_message
    for i in range(1, 6):
        send_message(db, [1], f"标题{i}", f"内容{i}")
    mids = [m.id for m in db.query(Message).order_by(Message.id).all()]
    _mark_read(db, [mids[1], mids[3]])  # 标题2、标题4 已读
    r = client.get("/api/messages?page=1&page_size=2", headers=_auth(1))
    assert r.status_code == 200 and r.json()["code"] == 0
    data = r.json()["data"]
    assert data["total"] == 5 and data["page"] == 1 and data["page_size"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["title"] == "标题5"  # 最新在前
    assert data["items"][0]["read"] is False
    assert data["items"][1]["title"] == "标题4"
    assert data["items"][1]["read"] is True
    # 末页数量正确
    data3 = client.get("/api/messages?page=3&page_size=2", headers=_auth(1)).json()["data"]
    assert len(data3["items"]) == 1
    # box 筛选
    assert client.get("/api/messages?box=unread", headers=_auth(1)).json()["data"]["total"] == 3
    assert client.get("/api/messages?box=read", headers=_auth(1)).json()["data"]["total"] == 2
    # 非法 box 值 422
    assert client.get("/api/messages?box=other", headers=_auth(1)).status_code == 422


def test_read_all(client, db, auth_header):
    """全部已读：本人未读清零、返回更新数、幂等、不影响他人"""
    from app.services.messaging import send_message
    u2 = make_user(db, phone="33100400003", name="测试民警2")
    for i in range(3):
        send_message(db, [1, 2], f"群发{i}", "内容")
    assert client.get("/api/messages/unread-count", headers=_auth(1)).json()["data"]["count"] == 3
    r = client.post("/api/messages/read-all", headers=_auth(1))
    assert r.status_code == 200 and r.json()["code"] == 0
    assert r.json()["data"]["updated"] == 3
    assert client.get("/api/messages/unread-count", headers=_auth(1)).json()["data"]["count"] == 0
    # 幂等
    assert client.post("/api/messages/read-all", headers=_auth(1)).json()["data"]["updated"] == 0
    # 不影响他人未读
    assert client.get("/api/messages/unread-count", headers=_auth(u2.id)).json()["data"]["count"] == 3


def test_messages_require_login(client, db):
    """未登录 401"""
    assert client.get("/api/messages").status_code == 401
    assert client.get("/api/messages/unread-count").status_code == 401
    assert client.get("/api/messages/1").status_code == 401
    assert client.post("/api/messages/read-all").status_code == 401

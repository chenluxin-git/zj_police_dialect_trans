"""T7 文本分配测试：2 分钟惰性锁 / 续期 / 放弃 / 过期回收 / 本区或空区匹配 / 自定义文本
口径：计划 T7 Step 1 四条核心用例 + refresh/release/expired 三个端点行为。
conftest 默认用户 id=1（phone 33100400002，region 331004），auth_header 即其令牌。
"""
from datetime import datetime, timedelta

from app.core.security import create_token
from app.models import Dialect, Recording, Text, TextAssignment  # 模块级导入：conftest 建表前须已注册模型
from tests.conftest import make_user


def seed_texts(db, contents=("大家不要吵了", "我们是警察"), region="331004", category="police"):
    texts = [Text(content=c, dialect="临海方言", category=category,
                  region_code=region, dialect_code="dh_lh") for c in contents]
    db.add_all(texts)
    db.commit()
    return texts


def auth_of(user):
    return {"Authorization": f"Bearer {create_token(str(user.id))}"}


# ---------- 核心用例（计划 T7 Step 1） ----------

def test_assign_creates_lock(client, db, auth_header):
    seed_texts(db)
    r = client.post("/api/texts/assign", headers=auth_header)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["content"] in ("大家不要吵了", "我们是警察")
    assert data["category"] == "police"
    assert data["remaining_seconds"] > 0
    a = db.query(TextAssignment).filter_by(user_id=1).one()
    assert a.text_id == data["text_id"]


def test_assign_skips_own_recorded_text(client, db, auth_header):
    texts = seed_texts(db, contents=("已录文本", "新文本"))
    db.add(Recording(user_id=1, text_id=texts[0].id, file_path="a.wav", file_size=1,
                     duration=1.0, region_code="331004", dialect_code="dh_lh",
                     qc_status="pending"))
    db.commit()
    r = client.post("/api/texts/assign", headers=auth_header)
    assert r.status_code == 200
    assert r.json()["data"]["text_id"] == texts[1].id


def test_assign_returns_own_failed_text(client, db, auth_header):
    """failed 文本释放回池：质检未通过的文本可重新领到重录"""
    texts = seed_texts(db, contents=("质检没过的文本",))
    db.add(Recording(user_id=1, text_id=texts[0].id, file_path="a.wav", file_size=1,
                     duration=1.0, region_code="331004", dialect_code="dh_lh",
                     qc_status="failed"))
    db.commit()
    r = client.post("/api/texts/assign", headers=auth_header)
    assert r.status_code == 200
    assert r.json()["data"]["text_id"] == texts[0].id


def test_assign_lazy_recovers_expired_lock(client, db, auth_header):
    texts = seed_texts(db, contents=("唯一文本",))
    r = client.post("/api/texts/assign", headers=auth_header)
    assert r.status_code == 200
    a = db.query(TextAssignment).one()
    a.assigned_at = datetime.now() - timedelta(minutes=3)
    db.commit()

    r2 = client.post("/api/texts/assign", headers=auth_header)
    assert r2.status_code == 200
    assert r2.json()["data"]["text_id"] == texts[0].id  # 过期锁回收后可重新分到同一条
    locks = db.query(TextAssignment).all()
    assert len(locks) == 1  # 旧过期行物理删除，只剩新锁
    assert (datetime.now() - locks[0].assigned_at).total_seconds() < 10


def test_custom_text_created_and_assigned(client, db, auth_header):
    db.add(Dialect(code="dh_lh", name="临海方言", region_code="331004"))
    db.commit()
    r = client.post("/api/texts/custom", headers=auth_header, json={"content": "请出示身份证件"})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["category"] == "custom"
    assert data["content"] == "请出示身份证件"
    assert data["dialect"] == "临海方言"

    t = db.query(Text).one()
    assert t.category == "custom"
    assert t.region_code == "331004"
    assert t.dialect_code == "dh_lh"
    assert db.query(TextAssignment).filter_by(user_id=1, text_id=t.id).count() == 1  # 自动分配给本人


# ---------- 端点补充用例 ----------

def test_assign_no_available_returns_404_code1(client, db, auth_header):
    texts = seed_texts(db, contents=("仅有文本",))
    db.add(Recording(user_id=1, text_id=texts[0].id, file_path="a.wav", file_size=1,
                     duration=1.0, region_code="331004", dialect_code="dh_lh",
                     qc_status="pending"))
    db.commit()
    r = client.post("/api/texts/assign", headers=auth_header)
    assert r.status_code == 404
    assert r.json()["code"] == 1


def test_assign_matches_own_or_empty_region(client, db, auth_header):
    db.add(Text(content="外区文本", dialect="", category="police",
                region_code="330100", dialect_code=""))
    db.commit()
    r = client.post("/api/texts/assign", headers=auth_header)
    assert r.status_code == 404 and r.json()["code"] == 1  # 外区文本不参与分配
    db.add(Text(content="全省通用文本", dialect="", category="police",
                region_code="", dialect_code=""))
    db.commit()
    r2 = client.post("/api/texts/assign", headers=auth_header)
    assert r2.status_code == 200
    assert r2.json()["data"]["content"] == "全省通用文本"


def test_refresh_resets_lock(client, db, auth_header):
    seed_texts(db, contents=("唯一文本",))
    r = client.post("/api/texts/assign", headers=auth_header)
    tid = r.json()["data"]["text_id"]
    a = db.query(TextAssignment).one()
    a.assigned_at = datetime.now() - timedelta(seconds=100)
    db.commit()

    r2 = client.post(f"/api/texts/assign/{tid}/refresh", headers=auth_header)
    assert r2.status_code == 200 and r2.json()["code"] == 0
    db.expire_all()
    a2 = db.query(TextAssignment).one()
    assert (datetime.now() - a2.assigned_at).total_seconds() < 10  # assigned_at 已重置


def test_refresh_allows_failed_but_blocks_pending(client, db, auth_header):
    """续期的"已被录制"检查：failed 行不算（文本已释放），pending/passed 仍拦截"""
    texts = seed_texts(db, contents=("失败可续期文本", "在质检不可续期文本"))

    db.add(TextAssignment(text_id=texts[0].id, user_id=1))
    db.add(Recording(user_id=1, text_id=texts[0].id, file_path="a.wav", file_size=1,
                     duration=1.0, region_code="331004", dialect_code="dh_lh",
                     qc_status="failed"))
    r1 = client.post(f"/api/texts/assign/{texts[0].id}/refresh", headers=auth_header)
    assert r1.status_code == 200                                   # failed 不拦

    db.add(TextAssignment(text_id=texts[1].id, user_id=1))
    db.add(Recording(user_id=1, text_id=texts[1].id, file_path="b.wav", file_size=1,
                     duration=1.0, region_code="331004", dialect_code="dh_lh",
                     qc_status="pending"))
    r2 = client.post(f"/api/texts/assign/{texts[1].id}/refresh", headers=auth_header)
    assert r2.status_code == 400 and "已被录制" in r2.json()["detail"]  # pending 拦截

    # 无分配的文本不可续期
    r3 = client.post("/api/texts/assign/999/refresh", headers=auth_header)
    assert r3.status_code == 403


def test_release_deletes_lock(client, db, auth_header):
    seed_texts(db, contents=("唯一文本",))
    r = client.post("/api/texts/assign", headers=auth_header)
    tid = r.json()["data"]["text_id"]
    r2 = client.delete(f"/api/texts/assign/{tid}", headers=auth_header)
    assert r2.status_code == 200 and r2.json()["code"] == 0
    assert db.query(TextAssignment).count() == 0


def test_delete_expired_cleans_own_only(client, db, auth_header):
    t1, t2 = seed_texts(db, contents=("文本A", "文本B"))
    u2 = make_user(db, phone="33100400003", name="民警二号")
    expired = datetime.now() - timedelta(minutes=3)
    db.add_all([TextAssignment(text_id=t1.id, user_id=1, assigned_at=expired),
                TextAssignment(text_id=t2.id, user_id=u2.id, assigned_at=expired)])
    db.commit()

    r = client.delete("/api/texts/assign/expired", headers=auth_header)
    assert r.status_code == 200 and r.json()["code"] == 0
    remain = db.query(TextAssignment).all()
    assert len(remain) == 1 and remain[0].user_id == u2.id  # 只清本人过期分配

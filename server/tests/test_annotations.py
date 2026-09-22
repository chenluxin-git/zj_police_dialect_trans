# tests/test_annotations.py —— T10 标注作业：3分钟锁/区域过滤/译文必填/一条音频一条标注/我的标注可改可删（已取消是否方言判定）
from datetime import datetime, timedelta

from app.models import Annotation, AudioFile, FileAssignment
from app.core.security import create_token
from tests.conftest import make_user


def auth(u):
    return {"Authorization": f"Bearer {create_token(str(u.id))}"}


def make_audio(db, path="a1.wav", region="331004", dialect="dh331004"):
    f = AudioFile(file_path=f"./test_audio/{path}", file_name=path,
                  duration=1.5, region_code=region, dialect_code=dialect)
    db.add(f)
    db.commit()
    return f


def take(client, u):
    r = client.get("/api/annotations/next", headers=auth(u))
    assert r.status_code == 200 and r.json()["code"] == 0
    return r.json()["data"]


def test_next_locks_and_excludes_second_user(client, db):
    u1 = make_user(db, phone="33100400002")
    u2 = make_user(db, phone="33100400003")
    f1 = make_audio(db, "a1.wav")
    f2 = make_audio(db, "a2.wav")
    d1 = take(client, u1)
    assert d1["file_id"] in (f1.id, f2.id)
    assert d1["region_code"] == "331004" and d1["dialect_code"] == "dh331004"
    assert db.query(FileAssignment).filter_by(file_id=d1["file_id"], user_id=u1.id).count() == 1
    # 第二人拿不到已被锁定的那条
    d2 = take(client, u2)
    assert d2["file_id"] != d1["file_id"]
    # 全部被锁后无货：HTTP 404 + code=1
    r3 = client.get("/api/annotations/next", headers=auth(u1))
    assert r3.status_code == 404 and r3.json()["code"] == 1


def test_next_region_filter(client, db):
    u = make_user(db)
    mine = make_audio(db, "mine.wav", region="331004")
    make_audio(db, "empty.wav", region="")
    foreign = make_audio(db, "foreign.wav", region="330100")
    d = take(client, u)
    assert d["file_id"] in (mine.id, mine.id + 1)  # 本区或空区，绝不为外区
    assert d["file_id"] != foreign.id


def test_expired_assignment_recycled(client, db):
    u1 = make_user(db, phone="33100400002")
    u2 = make_user(db, phone="33100400003")
    f = make_audio(db)
    take(client, u1)
    # 置 4 分钟前 → 惰性回收后他人可再领
    a = db.query(FileAssignment).filter_by(file_id=f.id).first()
    a.assigned_at = datetime.now() - timedelta(minutes=4)
    db.commit()
    d = take(client, u2)
    assert d["file_id"] == f.id
    assert db.query(FileAssignment).filter_by(file_id=f.id, user_id=u2.id).count() == 1


def test_submit_ok_and_assignment_removed(client, db):
    u = make_user(db)
    f = make_audio(db)
    take(client, u)
    r = client.post("/api/annotations", headers=auth(u),
                    json={"file_id": f.id, "translation": "你好"})
    assert r.status_code == 200 and r.json()["code"] == 0
    ann = db.query(Annotation).filter_by(file_id=f.id).first()
    assert ann.annotator_id == u.id and ann.translation == "你好"
    assert ann.region_code == "331004"
    assert db.query(FileAssignment).filter_by(file_id=f.id).count() == 0
    # 一条音频一条标注：再次提交 400
    r2 = client.post("/api/annotations", headers=auth(u),
                     json={"file_id": f.id, "translation": "再来"})
    assert r2.status_code == 400


def test_submit_requires_translation(client, db):
    u = make_user(db)
    f = make_audio(db)
    take(client, u)
    r = client.post("/api/annotations", headers=auth(u),
                    json={"file_id": f.id, "translation": "  "})
    assert r.status_code == 400


def test_submit_without_assignment_forbidden(client, db):
    u = make_user(db)
    f = make_audio(db)  # 未领取直接提交
    r = client.post("/api/annotations", headers=auth(u),
                    json={"file_id": f.id, "translation": "你好"})
    assert r.status_code == 403


def test_update_and_delete_own(client, db):
    u = make_user(db)
    f = make_audio(db)
    take(client, u)
    client.post("/api/annotations", headers=auth(u),
                json={"file_id": f.id, "translation": "旧译文"})
    ann = db.query(Annotation).filter_by(file_id=f.id).first()
    r = client.put(f"/api/annotations/{ann.id}", headers=auth(u),
                   json={"file_id": f.id, "translation": "新译文"})
    assert r.status_code == 200 and r.json()["code"] == 0
    assert ann.translation == "新译文"
    r2 = client.delete(f"/api/annotations/{ann.id}", headers=auth(u))
    assert r2.status_code == 200
    assert db.query(Annotation).count() == 0


def test_update_others_annotation_404(client, db):
    u1 = make_user(db, phone="33100400002")
    u2 = make_user(db, phone="33100400003")
    f = make_audio(db)
    take(client, u1)
    client.post("/api/annotations", headers=auth(u1),
                json={"file_id": f.id, "translation": "你好"})
    ann = db.query(Annotation).filter_by(file_id=f.id).first()
    r = client.put(f"/api/annotations/{ann.id}", headers=auth(u2),
                   json={"file_id": f.id, "translation": "x"})
    assert r.status_code == 404


def test_my_list(client, db):
    u = make_user(db)
    make_audio(db, "a1.wav")
    make_audio(db, "a2.wav")
    d1 = take(client, u)  # next 随机领号，须提交实际领到的文件
    r1 = client.post("/api/annotations", headers=auth(u),
                     json={"file_id": d1["file_id"], "translation": "你好"})
    assert r1.status_code == 200
    d2 = take(client, u)
    r2p = client.post("/api/annotations", headers=auth(u),
                      json={"file_id": d2["file_id"], "translation": "再见"})
    assert r2p.status_code == 200
    r = client.get("/api/annotations/my", headers=auth(u))
    data = r.json()["data"]
    assert r.status_code == 200 and data["total"] == 2
    assert data["items"][0]["file_name"] in ("a1.wav", "a2.wav")
    assert "is_dialect" not in data["items"][0]
    r2 = client.get("/api/annotations/my/dialect-count", headers=auth(u))
    assert r2.json()["data"] == 2  # 已取消判定，口径=我的标注总数


def test_refresh_and_clear_expired(client, db):
    u = make_user(db)
    f = make_audio(db)
    take(client, u)
    r = client.post(f"/api/annotations/assign/{f.id}/refresh", headers=auth(u))
    assert r.status_code == 200 and r.json()["code"] == 0
    # 未分配的文件刷新 → 403
    f2 = make_audio(db, "a2.wav")
    r2 = client.post(f"/api/annotations/assign/{f2.id}/refresh", headers=auth(u))
    assert r2.status_code == 403
    # 过期后清理自己的分配
    a = db.query(FileAssignment).filter_by(file_id=f.id).first()
    a.assigned_at = datetime.now() - timedelta(minutes=4)
    db.commit()
    r3 = client.delete("/api/annotations/assign/expired", headers=auth(u))
    assert r3.status_code == 200 and r3.json()["code"] == 0
    assert db.query(FileAssignment).filter_by(user_id=u.id).count() == 0


def test_next_requires_login(client, db):
    r = client.get("/api/annotations/next")
    assert r.status_code == 401

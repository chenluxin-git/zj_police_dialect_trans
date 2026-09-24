"""T18 管理端录音/标注管理测试：
- 录音列表：scope 过滤（行含 用户姓名/文本/类别/方言/时长/大小/质检状态/时间/file_url）、qc_status 与 category/region/q 筛选
- 标注列表：scope 过滤（行含译者与音频 id；已取消是否方言判定）
- 删标注：scope 内成功回池（行删除）、越界 403、二次删 404
"""
import pytest

from app.core.security import create_token
from app.models import Annotation, AudioFile, QCLog, Recording, Region, Text, User
from tests.conftest import make_user


def seed_regions(db):
    db.add_all([
        Region(code="330000", name="浙江省", level="province", parent_code=None),
        Region(code="331000", name="台州市", level="city", parent_code="330000"),
        Region(code="331004", name="临海市", level="district", parent_code="331000"),
        Region(code="331082", name="三门县", level="district", parent_code="331000"),
        Region(code="330100", name="杭州市", level="city", parent_code="330000"),
        Region(code="330105", name="拱墅区", level="district", parent_code="330100"),
    ])
    db.commit()


def auth_of(user):
    return {"Authorization": f"Bearer {create_token(str(user.id))}"}


def make_admins(db):
    tz_admin = make_user(db, phone="33100000001", name="台州管理员", role="admin", region="331000")
    hz_admin = make_user(db, phone="33010000001", name="杭州管理员", role="admin", region="330100")
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    return tz_admin, hz_admin, super_admin


def seed_manage_data(db, tmp_path):
    """临海：passed/pending 录音各 1 + 标注 1；杭州：passed 录音 1 + 标注 1"""
    # 33100400003 避开 auth_header 默认民警 33100400002 的 phone 唯一约束
    u_lh = make_user(db, phone="33100400003", name="临海民警", region="331004")
    u_hz = make_user(db, phone="33010500002", name="杭州民警", region="330105")

    t1 = Text(content="请出示身份证", dialect="临海方言", category="police", region_code="331004")
    t2 = Text(content="今天天气不错", dialect="临海方言", category="life", region_code="331004")
    t3 = Text(content="请配合检查", dialect="杭州方言", category="police", region_code="330105")
    db.add_all([t1, t2, t3])
    db.commit()

    f1 = tmp_path / "lh_passed.wav"; f1.write_bytes(b"RIFF1")
    f2 = tmp_path / "lh_pending.wav"; f2.write_bytes(b"RIFF2")
    f3 = tmp_path / "hz_passed.wav"; f3.write_bytes(b"RIFF3")
    rec1 = Recording(user_id=u_lh.id, text_id=t1.id, file_path=str(f1), file_size=100, duration=2.0,
                     region_code="331004", dialect_code="dh_lh", qc_status="passed")
    rec2 = Recording(user_id=u_lh.id, text_id=t2.id, file_path=str(f2), file_size=200, duration=3.0,
                     region_code="331004", dialect_code="dh_lh", qc_status="pending")
    rec3 = Recording(user_id=u_hz.id, text_id=t3.id, file_path=str(f3), file_size=300, duration=4.0,
                     region_code="330105", dialect_code="dh_hz", qc_status="passed")
    db.add_all([rec1, rec2, rec3])
    db.commit()

    fa = tmp_path / "a_lh.mp3"; fa.write_bytes(b"MP3LH")
    fb = tmp_path / "a_hz.mp3"; fb.write_bytes(b"MP3HZ")
    af_lh = AudioFile(file_path=str(fa), file_name="a_lh.mp3", duration=5.0,
                      region_code="331004", dialect_code="dh_lh")
    af_hz = AudioFile(file_path=str(fb), file_name="a_hz.mp3", duration=6.0,
                      region_code="330105", dialect_code="dh_hz")
    db.add_all([af_lh, af_hz])
    db.commit()
    ann_lh = Annotation(file_id=af_lh.id, annotator_id=u_lh.id, is_dialect=True,
                        translation="下雨了，收衣服", region_code="331004")
    ann_hz = Annotation(file_id=af_hz.id, annotator_id=u_hz.id, is_dialect=True,
                        translation="外区域译文", region_code="330105")
    db.add_all([ann_lh, ann_hz])
    db.commit()
    return {"u_lh": u_lh, "u_hz": u_hz, "rec1": rec1, "rec2": rec2, "rec3": rec3,
            "af_lh": af_lh, "af_hz": af_hz, "ann_lh": ann_lh, "ann_hz": ann_hz}


# ---------- 录音列表 ----------

def test_recordings_scope_and_columns(client, db, auth_header, tmp_path):
    seed_regions(db)
    d = seed_manage_data(db, tmp_path)
    tz_admin, hz_admin, super_admin = make_admins(db)

    # 民警访问管理端 → 403
    assert client.get("/api/admin/recordings", headers=auth_header).status_code == 403

    # 超管：scope=None 见全部 3 条，行含姓名/质检/文本/文件链接
    r = client.get("/api/admin/recordings", headers=auth_of(super_admin))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 3
    item = data["items"][0]
    assert item["user_name"] == "杭州民警" or item["user_name"] == "临海民警"
    assert item["qc_status"] in ("passed", "pending")
    assert item["text_content"] in ("请出示身份证", "今天天气不错", "请配合检查")
    assert item["file_url"] == f"/api/recordings/{item['id']}/file"
    assert "created_at" in item and "duration" in item and "file_size" in item

    # 台州市管（scope=331000/331004/331082）：只见临海 2 条，不见杭州
    r2 = client.get("/api/admin/recordings", headers=auth_of(tz_admin))
    assert r2.json()["data"]["total"] == 2
    assert all(i["region_code"] == "331004" for i in r2.json()["data"]["items"])

    # 杭州市管：只见杭州 1 条
    r3 = client.get("/api/admin/recordings", headers=auth_of(hz_admin))
    assert r3.json()["data"]["total"] == 1
    assert r3.json()["data"]["items"][0]["region_code"] == "330105"


def test_recordings_filters(client, db, tmp_path):
    seed_regions(db)
    seed_manage_data(db, tmp_path)
    _, _, super_admin = make_admins(db)
    h = auth_of(super_admin)

    assert client.get("/api/admin/recordings", headers=h,
                      params={"qc_status": "passed"}).json()["data"]["total"] == 2
    assert client.get("/api/admin/recordings", headers=h,
                      params={"qc_status": "pending"}).json()["data"]["total"] == 1
    assert client.get("/api/admin/recordings", headers=h,
                      params={"category": "police"}).json()["data"]["total"] == 2
    assert client.get("/api/admin/recordings", headers=h,
                      params={"category": "life"}).json()["data"]["total"] == 1
    assert client.get("/api/admin/recordings", headers=h,
                      params={"region": "331004"}).json()["data"]["total"] == 2
    assert client.get("/api/admin/recordings", headers=h,
                      params={"q": "身份证"}).json()["data"]["total"] == 1


def test_recording_qc_detail_scope(client, db, auth_header, tmp_path):
    """质检文本对比详情：require_admin + scope 校验，按 (user, text) 聚合 qc_logs"""
    seed_regions(db)
    d = seed_manage_data(db, tmp_path)
    rec1 = d["rec1"]  # 临海 passed（331004 ∈ 台州 scope）
    db.add(QCLog(recording_id=rec1.id, user_id=rec1.user_id, text_id=rec1.text_id,
                 text_content="请出示身份证", asr_text="请出示证件", similarity=0.8,
                 result="passed"))
    db.commit()
    url = f"/api/admin/recordings/{rec1.id}/qc"
    tz_admin, hz_admin, super_admin = make_admins(db)

    assert client.get(url, headers=auth_header).status_code == 403        # 民警非管理端
    r = client.get(url, headers=auth_of(tz_admin))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["text_content"] == "请出示身份证" and len(data["items"]) == 1
    assert data["items"][0]["asr_text"] == "请出示证件" and data["items"][0]["similarity"] == 0.8
    assert client.get(url, headers=auth_of(hz_admin)).status_code == 403  # 越界市管
    assert client.get(url, headers=auth_of(super_admin)).status_code == 200
    assert client.get("/api/admin/recordings/999/qc",
                      headers=auth_of(super_admin)).status_code == 404


# ---------- 标注列表 ----------

def test_annotations_scope_and_columns(client, db, auth_header, tmp_path):
    seed_regions(db)
    d = seed_manage_data(db, tmp_path)
    tz_admin, hz_admin, super_admin = make_admins(db)

    assert client.get("/api/admin/annotations", headers=auth_header).status_code == 403

    # 超管见 2 条
    r = client.get("/api/admin/annotations", headers=auth_of(super_admin))
    assert r.json()["data"]["total"] == 2

    # 台州市管：仅临海 1 条，含译者与音频 id
    r2 = client.get("/api/admin/annotations", headers=auth_of(tz_admin))
    assert r2.json()["data"]["total"] == 1
    item = r2.json()["data"]["items"][0]
    assert item["annotator_name"] == "临海民警"
    assert item["file_id"] == d["af_lh"].id
    assert "is_dialect" not in item

    # 译文关键词筛选
    r3 = client.get("/api/admin/annotations", headers=auth_of(super_admin),
                    params={"q": "外区域"})
    assert r3.json()["data"]["total"] == 1
    assert r3.json()["data"]["items"][0]["region_code"] == "330105"


# ---------- 删标注 ----------

def test_delete_annotation(client, db, tmp_path):
    seed_regions(db)
    d = seed_manage_data(db, tmp_path)
    tz_admin, _, super_admin = make_admins(db)

    # 越界删除（杭州标注不属于台州 scope）→ 403
    r = client.delete(f"/api/admin/annotations/{d['ann_hz'].id}", headers=auth_of(tz_admin))
    assert r.status_code == 403

    # scope 内删除成功（回池：行删除）
    r2 = client.delete(f"/api/admin/annotations/{d['ann_lh'].id}", headers=auth_of(tz_admin))
    assert r2.status_code == 200
    assert db.get(Annotation, d["ann_lh"].id) is None

    # 二次删除 404
    r3 = client.delete(f"/api/admin/annotations/{d['ann_lh'].id}", headers=auth_of(tz_admin))
    assert r3.status_code == 404

    # 超管可删任意
    r4 = client.delete(f"/api/admin/annotations/{d['ann_hz'].id}", headers=auth_of(super_admin))
    assert r4.status_code == 200
    assert db.get(Annotation, d["ann_hz"].id) is None
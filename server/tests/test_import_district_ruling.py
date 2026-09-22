"""规格裁定回归（2026-09-22）：导入强制落区县级。
背景：市管导入 region=331000 的文本/音频，用户侧领取为"本区/空区"精确匹配 → 3310xx 用户领不到（死数据）。
裁定口径（三入库口一致：文本导入 / 音频上传 / 音频扫盘）：
- 县级管理员不传 → 默认本区（原行为不变）
- 市/省/超管不传 → 400；传入市/省级码或未知码 → 400
- 传入值须 ∈ 本人 scope → 否则 403（县管传他县、市管传他市区县均拒）
"""
import subprocess

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import create_token
from app.models import AudioFile, Region, Text, User  # 模块级导入：conftest 建表前须已注册模型
from tests.conftest import make_user


def auth_of(user):
    return {"Authorization": f"Bearer {create_token(str(user.id))}"}


def seed(db):
    db.add_all([
        Region(code="330000", name="浙江省", level="province", parent_code=None),
        Region(code="331000", name="台州市", level="city", parent_code="330000"),
        Region(code="331004", name="路桥区", level="district", parent_code="331000"),
        Region(code="331082", name="三门县", level="district", parent_code="331000"),
        Region(code="330100", name="杭州市", level="city", parent_code="330000"),
        Region(code="330105", name="拱墅区", level="district", parent_code="330100"),
    ])
    db.commit()


@pytest.fixture()
def ti_env(db, tmp_path, monkeypatch):
    from app.api.admin import text_import as ti
    monkeypatch.setattr(ti, "_session_factory",
                        sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(ti, "_manifest_dir", lambda: str(tmp_path))
    return ti


@pytest.fixture()
def ai_env(db, tmp_path, monkeypatch):
    from app.api.admin import audio_import as ai
    monkeypatch.setattr(ai, "_session_factory",
                        sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(ai, "_manifest_dir", lambda: str(tmp_path))
    return ai


def _import_texts(client, h, region=None):
    data = {"category": "police"}
    if region:
        data["region_code"] = region
    return client.post("/api/admin/texts/import", headers=h, data=data,
                       files={"file": ("t.txt", "句子一。句子二。".encode("utf-8"), "text/plain")})


def make_wav(path):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
                    "-ar", "16000", "-ac", "1", str(path)], check=True, capture_output=True)


# ---------- 文本导入 ----------

def test_city_admin_import_must_pick_district(client, db, ti_env):
    seed(db)
    city = make_user(db, phone="33100000001", name="台州管理员", role="admin", region="331000")
    # 不传 → 400（市码归属=县级用户领不到的死数据）
    assert _import_texts(client, auth_of(city)).status_code == 400
    # 市级码本身 → 400
    assert _import_texts(client, auth_of(city), region="331000").status_code == 400
    # 他市区县 → 403
    assert _import_texts(client, auth_of(city), region="330105").status_code == 403
    # 本市区县 → 200，文本落区县级
    r = _import_texts(client, auth_of(city), region="331004")
    assert r.status_code == 200
    texts = db.query(Text).all()
    assert texts and all(t.region_code == "331004" for t in texts)


def test_county_admin_import_defaults_own_district(client, db, ti_env):
    seed(db)
    county = make_user(db, phone="33100400001", name="路桥管理员", role="admin", region="331004")
    assert _import_texts(client, auth_of(county)).status_code == 200
    assert db.query(Text).first().region_code == "331004"


def test_province_and_super_admin_import(client, db, ti_env):
    seed(db)
    prov = make_user(db, phone="33000000002", name="省管理员", role="admin", region="330000")
    sup = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    # 省/超管不传 → 400；省级码 → 400；跨市区县可（scope=None）→ 200
    assert _import_texts(client, auth_of(prov)).status_code == 400
    assert _import_texts(client, auth_of(sup), region="330000").status_code == 400
    assert _import_texts(client, auth_of(prov), region="330105").status_code == 200
    assert _import_texts(client, auth_of(sup), region="331082").status_code == 200
    assert {t.region_code for t in db.query(Text).all()} == {"330105", "331082"}


# ---------- 音频上传 ----------

def test_upload_district_ruling(client, db, tmp_path, monkeypatch):
    seed(db)
    monkeypatch.setattr(settings, "audio_storage_path", str(tmp_path))
    city = make_user(db, phone="33100000001", name="台州管理员", role="admin", region="331000")
    src = tmp_path / "s.wav"
    make_wav(src)
    # 不传 → 400
    r1 = client.post("/api/admin/audio/upload", headers=auth_of(city),
                     files=[("files", ("s.wav", src.read_bytes(), "audio/wav"))])
    assert r1.status_code == 400
    # 本市区县 → 200
    r2 = client.post("/api/admin/audio/upload", headers=auth_of(city),
                     data={"region_code": "331004"},
                     files=[("files", ("s.wav", src.read_bytes(), "audio/wav"))])
    assert r2.status_code == 200
    assert db.query(AudioFile).one().region_code == "331004"


# ---------- 音频扫盘 ----------

def test_scan_district_ruling(client, db, tmp_path, ai_env):
    seed(db)
    city = make_user(db, phone="33100000001", name="台州管理员", role="admin", region="331000")
    folder = tmp_path / "lib"
    folder.mkdir()
    # 不传 → 400
    r1 = client.post("/api/admin/audio/import", headers=auth_of(city),
                     json={"server_path": str(folder), "recursive": False})
    assert r1.status_code == 400
    # 本市区县 → 200
    r2 = client.post("/api/admin/audio/import", headers=auth_of(city),
                     json={"server_path": str(folder), "recursive": False, "region_code": "331004"})
    assert r2.status_code == 200 and r2.json()["code"] == 0

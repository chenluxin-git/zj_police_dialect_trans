"""T19 音频双通道测试：多文件上传（UUID 重命名 + convert_to_wav + ffprobe 时长）与服务器扫盘（7 扩展名/绝对路径去重/递归）
ffmpeg/ffprobe 宿主机可用（勿 skip）。
"""
import os
import subprocess

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import create_token
from app.models import AudioFile, Dialect, Region, User  # 模块级导入：先注册模型
from tests.conftest import make_user


def seed_regions_and_dialects(db):
    db.add_all([
        Region(code="330000", name="浙江省", level="province", parent_code=None),
        Region(code="331000", name="台州市", level="city", parent_code="330000"),
        Region(code="331004", name="路桥区", level="district", parent_code="331000"),
    ])
    db.add(Dialect(code="dh_lq", name="路桥方言", region_code="331004"))
    db.commit()


def auth_of(user):
    return {"Authorization": f"Bearer {create_token(str(user.id))}"}


def make_audio(path, seconds=0.3, fmt="wav"):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-ar", "16000", "-ac", "1", str(path)], check=True, capture_output=True)


# ---------- 上传 ----------

def test_upload_wav(client, db, tmp_path, monkeypatch):
    seed_regions_and_dialects(db)
    monkeypatch.setattr(settings, "audio_storage_path", str(tmp_path))
    admin = make_user(db, phone="33100400001", name="路桥管理员", role="admin", region="331004")

    src = tmp_path / "s.wav"
    make_audio(src)
    r = client.post("/api/admin/audio/upload", headers=auth_of(admin),
                    files=[("files", ("s.wav", src.read_bytes(), "audio/wav"))])
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["imported"] == 1 and data["results"][0]["file_name"] == "s.wav"

    af = db.query(AudioFile).one()
    assert af.region_code == "331004" and af.dialect_code == "dh_lq"
    assert os.path.exists(af.file_path)
    assert os.path.basename(af.file_path).endswith(".wav")  # UUID 重命名
    assert af.file_name == "s.wav"
    assert 0.15 < af.duration < 0.6


def test_upload_region_override(client, db, tmp_path, monkeypatch):
    seed_regions_and_dialects(db)
    monkeypatch.setattr(settings, "audio_storage_path", str(tmp_path))
    db.add_all([
        Region(code="331082", name="三门县", level="district", parent_code="331000"),
        Dialect(code="dh_sm", name="三门方言", region_code="331082"),
    ])
    db.commit()
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    admin = make_user(db, phone="33100400001", name="路桥管理员", role="admin", region="331004")

    src = tmp_path / "s.wav"
    make_audio(src)
    # 超管指定 region_code=331082 → 归属三门
    r = client.post("/api/admin/audio/upload", headers=auth_of(super_admin),
                    data={"region_code": "331082"},
                    files=[("files", ("s.wav", src.read_bytes(), "audio/wav"))])
    assert r.status_code == 200
    assert db.query(AudioFile).one().region_code == "331082"

    # admin 传 scope 外区县 → 403（规格裁定 2026-09-22：指定值须为辖区内区县级，不再静默忽略）
    r2 = client.post("/api/admin/audio/upload", headers=auth_of(admin),
                     data={"region_code": "331082"},
                     files=[("files", ("s.wav", src.read_bytes(), "audio/wav"))])
    assert r2.status_code == 403
    assert db.query(AudioFile).count() == 1  # 仍仅超管那条，未落库


# ---------- 扫盘 ----------

@pytest.fixture()
def scan_env(db, tmp_path, monkeypatch):
    from app.api.admin import audio_import as ai
    monkeypatch.setattr(ai, "_session_factory",
                        sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(ai, "_manifest_dir", lambda: str(tmp_path))
    return ai


def test_scan_dedup_and_recursive(client, db, tmp_path, scan_env):
    seed_regions_and_dialects(db)
    admin = make_user(db, phone="33100400001", name="路桥管理员", role="admin", region="331004")
    h = auth_of(admin)

    folder = tmp_path / "lib"
    sub = folder / "sub"
    sub.mkdir(parents=True)
    w1 = folder / "a.wav"
    w2 = sub / "b.mp3"
    make_audio(w1)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3",
                    str(w2)], check=True, capture_output=True)

    # 预置一条同绝对路径 → 扫盘时跳过
    db.add(AudioFile(file_path=str(w1), file_name="a.wav", duration=0.3,
                     region_code="331004", dialect_code="dh_lq"))
    db.commit()

    r = client.post("/api/admin/audio/import", headers=h,
                    json={"server_path": str(folder), "recursive": True})
    assert r.status_code == 200 and r.json()["code"] == 0
    task_id = r.json()["data"]["task_id"]

    t = client.get(f"/api/admin/audio/import/{task_id}", headers=h)
    d = t.json()["data"]
    assert d["status"] == "completed"
    assert d["found"] == 2 and d["imported"] == 1 and d["skipped"] == 1
    assert db.query(AudioFile).count() == 2


def test_scan_invalid_path(client, db, tmp_path, scan_env):
    seed_regions_and_dialects(db)
    admin = make_user(db, phone="33100400001", name="路桥管理员", role="admin", region="331004")
    r = client.post("/api/admin/audio/import", headers=auth_of(admin),
                    json={"server_path": str(tmp_path / "nope"), "recursive": False})
    assert r.status_code == 400


# ---------- file_scanner 单元 ----------

def test_file_scanner_extensions(tmp_path):
    from app.utils.file_scanner import AUDIO_EXTENSIONS, scan_audio_files
    assert AUDIO_EXTENSIONS == {".wav", ".mp3", ".m4a", ".wma", ".amr", ".aac", ".ogg"}
    for ext in [".wav", ".mp3", ".m4a", ".wma", ".amr", ".aac", ".ogg", ".txt", ".flac"]:
        (tmp_path / f"f{ext}").write_bytes(b"x")
    got = scan_audio_files(str(tmp_path), recursive=False)
    assert len(got) == 7  # txt/flac 不计
    assert all(os.path.isabs(p) for p in got)
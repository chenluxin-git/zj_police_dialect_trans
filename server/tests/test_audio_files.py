# tests/test_audio_files.py —— T11 标注音频流：登录可听、404、未登录 401
from app.models import AudioFile
from app.core.security import create_token
from tests.conftest import make_user


def auth(u):
    return {"Authorization": f"Bearer {create_token(str(u.id))}"}


def test_audio_file_stream(client, db, tmp_path):
    u = make_user(db)
    p = tmp_path / "a.wav"
    p.write_bytes(b"RIFF-fake-wav-bytes")
    f = AudioFile(file_path=str(p), file_name="a.wav", duration=1.0,
                  region_code="331004", dialect_code="")
    db.add(f)
    db.commit()
    r = client.get(f"/api/audio/files/{f.id}/file", headers=auth(u))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio")
    assert r.content == b"RIFF-fake-wav-bytes"


def test_audio_file_missing_on_disk(client, db):
    u = make_user(db)
    f = AudioFile(file_path="./test_audio/none.wav", file_name="none.wav",
                  duration=1.0, region_code="331004", dialect_code="")
    db.add(f)
    db.commit()
    r = client.get(f"/api/audio/files/{f.id}/file", headers=auth(u))
    assert r.status_code == 404


def test_audio_file_not_found(client, db):
    u = make_user(db)
    r = client.get("/api/audio/files/999/file", headers=auth(u))
    assert r.status_code == 404


def test_audio_file_requires_login(client, db):
    r = client.get("/api/audio/files/1/file")
    assert r.status_code == 401

"""T8 录音上传测试：ffmpeg 转 WAV / pending 入库 / 落盘路径 / 删分配 / 重复 400 / 删除联动 / 列表筛选 / 文件下载权限
+ failed 重录替换 / failed 列表可见 / 质检详情端点
口径：计划 T8 Step 1 四条核心用例 + convert_to_wav 模块契约 + 列表与下载权限补充。
测试音频由本机 ffmpeg 生成 1 秒静音 webm/opus；宿主机无 ffmpeg/ffprobe 时涉转码用例按计划 skip。
conftest 默认用户 id=1（测试民警，phone 33100400002 → 尾4=0002，region 331004）。
"""
import asyncio
import os
import shutil
import subprocess
from datetime import datetime, timedelta

import pytest

from app.core.config import settings
from app.core.security import create_token
from app.models import QCLog, Recording, Region, Text, TextAssignment  # 模块级导入：conftest 建表前须已注册模型
from tests.conftest import make_user

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
HAS_FF = bool(FFMPEG and FFPROBE)
needs_ffmpeg = pytest.mark.skipif(not HAS_FF, reason="宿主机无 ffmpeg/ffprobe，涉转码用例按计划跳过")


@pytest.fixture(scope="module")
def webm_bytes(tmp_path_factory):
    """1 秒静音 webm/opus 测试音频（ffmpeg anullsrc 生成）"""
    if not HAS_FF:
        pytest.skip("宿主机无 ffmpeg")
    out = tmp_path_factory.mktemp("av") / "test.webm"
    subprocess.run(
        [FFMPEG, "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
         "-t", "1", "-c:a", "libopus", str(out)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return out.read_bytes()


@pytest.fixture()
def clean_audio_dir():
    """每个上传用例前清掉 conftest 指定的测试音频目录，避免跨用例残留"""
    base = settings.audio_storage_path  # conftest 设为 ./test_audio
    if os.path.isdir(base):
        shutil.rmtree(base)
    yield
    if os.path.isdir(base):
        shutil.rmtree(base)


def make_text_with_lock(db, user_id=1, content="请配合检查"):
    t = Text(content=content, dialect="临海方言", category="police",
             region_code="331004", dialect_code="dh_lh")
    db.add(t)
    db.commit()
    db.add(TextAssignment(text_id=t.id, user_id=user_id))
    db.commit()
    return t


def auth_of(user):
    return {"Authorization": f"Bearer {create_token(str(user.id))}"}


def upload(client, headers, text_id, audio):
    return client.post("/api/recordings", headers=headers,
                       data={"text_id": str(text_id)},
                       files={"file": ("test.webm", audio, "audio/webm")})


# ---------- 模块契约（P-admin-content T19 复用） ----------

@needs_ffmpeg
def test_convert_to_wav_contract(tmp_path, webm_bytes):
    from app.api.recordings import _ffmpeg_sem, convert_to_wav
    dst = tmp_path / "out.wav"
    dur = convert_to_wav(webm_bytes, str(dst))
    assert isinstance(dur, float)
    assert dur == pytest.approx(1.0, abs=0.3)
    assert dst.read_bytes()[:4] == b"RIFF"
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=channels,sample_rate,codec_name",
         "-of", "default=noprint_wrappers=1", str(dst)],
        capture_output=True, text=True, check=True,
    )
    assert "codec_name=pcm_s16le" in probe.stdout
    assert "sample_rate=16000" in probe.stdout
    assert "channels=1" in probe.stdout
    assert isinstance(_ffmpeg_sem, asyncio.Semaphore)  # 并发限流信号量存在（限 2 由实现保证）


# ---------- 核心用例（计划 T8 Step 1） ----------

@needs_ffmpeg
def test_upload_creates_pending_and_deletes_assignment(client, db, auth_header, webm_bytes, clean_audio_dir):
    t = make_text_with_lock(db)
    r = upload(client, auth_header, t.id, webm_bytes)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["qc_status"] == "pending"          # 入库即 pending
    assert data["duration"] == pytest.approx(1.0, abs=0.3)
    assert data["file_size"] > 0
    rec = db.query(Recording).one()
    assert rec.text_id == t.id
    assert rec.qc_status == "pending"
    assert db.query(TextAssignment).count() == 0   # 对应分配记录被删


@needs_ffmpeg
def test_upload_file_layout(client, db, auth_header, webm_bytes, clean_audio_dir):
    t = make_text_with_lock(db)
    r = upload(client, auth_header, t.id, webm_bytes)
    rid = r.json()["data"]["id"]
    rec = db.query(Recording).one()
    expected = os.path.join(settings.audio_storage_path, "测试民警_0002", f"{rid}.wav")
    assert rec.file_path == expected               # {姓名}_{手机尾4}/{recording_id}.wav
    assert os.path.isfile(expected)
    with open(expected, "rb") as f:
        assert f.read(4) == b"RIFF"


@needs_ffmpeg
def test_upload_duplicate_same_text_400(client, db, auth_header, webm_bytes, clean_audio_dir):
    t = make_text_with_lock(db)
    assert upload(client, auth_header, t.id, webm_bytes).status_code == 200
    r2 = upload(client, auth_header, t.id, webm_bytes)
    assert r2.status_code == 400                   # unique(user_id, text_id) 冲突（pending 不可重录）
    assert db.query(Recording).count() == 1


@needs_ffmpeg
def test_upload_replaces_failed_recording(client, db, auth_header, webm_bytes,
                                          clean_audio_dir, tmp_path):
    """failed 行保留后重录：上传端删旧 failed 行（含文件）再插新行，qc_logs 流水保留"""
    t = make_text_with_lock(db)
    old_wav = tmp_path / "old.wav"
    old_wav.write_bytes(b"RIFFold")
    old = Recording(user_id=1, text_id=t.id, file_path=str(old_wav), file_size=8,
                    duration=1.0, region_code="331004", dialect_code="dh_lh",
                    qc_status="failed")
    db.add(old)
    db.flush()
    db.add(QCLog(recording_id=old.id, user_id=1, text_id=t.id, text_content=t.content,
                 asr_text="无关内容", similarity=0.1, result="failed"))
    db.commit()
    old_id = old.id

    r = upload(client, auth_header, t.id, webm_bytes)
    assert r.status_code == 200
    rows = db.query(Recording).filter_by(user_id=1, text_id=t.id).all()
    assert len(rows) == 1                          # 删旧插新：仍只有一行
    assert rows[0].qc_status == "pending"          # 新行从 pending 重新走质检
    # SQLite 可能复用被删行的 id，用"新文件已按上传布局落盘"证明是全新行而非旧行改状态
    expected = os.path.join(settings.audio_storage_path, "测试民警_0002", f"{rows[0].id}.wav")
    assert rows[0].file_path == expected and os.path.isfile(expected)
    assert not old_wav.exists()                    # 旧 failed 音频文件已删
    assert db.query(QCLog).filter_by(recording_id=old_id).count() == 1  # 旧流水留存可追溯


@needs_ffmpeg
def test_delete_removes_record_and_file(client, db, auth_header, webm_bytes, clean_audio_dir):
    t = make_text_with_lock(db)
    rid = upload(client, auth_header, t.id, webm_bytes).json()["data"]["id"]
    path = db.query(Recording).one().file_path
    r = client.delete(f"/api/recordings/{rid}", headers=auth_header)
    assert r.status_code == 200 and r.json()["code"] == 0
    assert db.query(Recording).count() == 0        # 记录消失
    assert not os.path.exists(path)                # 盘上文件联动删除


# ---------- 端点补充用例 ----------

def test_upload_without_assignment_403(client, db, auth_header, webm_bytes, clean_audio_dir):
    t = Text(content="未分配文本", dialect="临海方言", category="police",
             region_code="331004", dialect_code="dh_lh")
    db.add(t)
    db.commit()
    r = upload(client, auth_header, t.id, webm_bytes)
    assert r.status_code == 403                    # 非自定义文本无分配不可上传


def test_my_recordings_list_and_filters(client, db, auth_header):
    t_police = Text(content="把车停到路边接受检查", dialect="临海方言", category="police",
                    region_code="331004", dialect_code="dh_lh")
    t_life = Text(content="今天天气蛮好", dialect="临海方言", category="life",
                  region_code="331004", dialect_code="dh_lh")
    db.add_all([t_police, t_life])
    db.commit()
    db.add_all([
        Recording(user_id=1, text_id=t_police.id, file_path="a.wav", file_size=1, duration=1.0,
                  region_code="331004", dialect_code="dh_lh", qc_status="passed"),
        Recording(user_id=1, text_id=t_life.id, file_path="b.wav", file_size=1, duration=2.0,
                  region_code="331004", dialect_code="dh_lh", qc_status="pending"),
    ])
    u2 = make_user(db, phone="33100400003", name="民警二号")
    db.add(Recording(user_id=u2.id, text_id=t_police.id, file_path="c.wav", file_size=1, duration=1.0,
                     region_code="331004", dialect_code="dh_lh", qc_status="passed"))
    db.commit()

    r = client.get("/api/recordings", headers=auth_header)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 2                       # 仅本人列表
    item = data["items"][0]
    assert {"text_content", "qc_status", "file_url", "duration", "created_at"} <= set(item)

    r = client.get("/api/recordings", headers=auth_header, params={"qc_status": "passed"})
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["items"][0]["text_content"] == "把车停到路边接受检查"

    r = client.get("/api/recordings", headers=auth_header, params={"q": "天气"})
    assert r.json()["data"]["total"] == 1

    r = client.get("/api/recordings", headers=auth_header, params={"category": "life"})
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["items"][0]["text_content"] == "今天天气蛮好"


def test_my_recordings_failed_visible(client, db, auth_header):
    """failed 行保留：列表可见 + qc_status 筛选互通"""
    t = Text(content="上盘镇在哪边", dialect="临海方言", category="place",
             region_code="331004", dialect_code="dh_lh")
    db.add(t)
    db.commit()
    db.add(Recording(user_id=1, text_id=t.id, file_path="f.wav", file_size=1, duration=1.0,
                     region_code="331004", dialect_code="dh_lh", qc_status="failed"))
    db.commit()

    r = client.get("/api/recordings", headers=auth_header)
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["items"][0]["qc_status"] == "failed"
    r = client.get("/api/recordings", headers=auth_header, params={"qc_status": "failed"})
    assert r.json()["data"]["total"] == 1
    r = client.get("/api/recordings", headers=auth_header, params={"qc_status": "passed"})
    assert r.json()["data"]["total"] == 0


def test_recording_qc_detail_owner_only(client, db, auth_header):
    """质检详情：按 (user, text) 聚合全历史倒序；仅本人；404/403；无日志 items 空"""
    t = Text(content="上盘镇", dialect="临海方言", category="place",
             region_code="331004", dialect_code="dh_lh")
    db.add(t)
    db.commit()
    rec = Recording(user_id=1, text_id=t.id, file_path="f.wav", file_size=1, duration=1.0,
                    region_code="331004", dialect_code="dh_lh", qc_status="failed")
    db.add(rec)
    db.flush()
    base = datetime(2026, 9, 24, 10, 0, 0)
    db.add_all([
        QCLog(recording_id=999, user_id=1, text_id=t.id, text_content="上盘镇",
              asr_text="最早一次失败", similarity=0.2, result="failed",
              created_at=base),
        QCLog(recording_id=rec.id, user_id=1, text_id=t.id, text_content="上盘镇",
              asr_text="", similarity=None, result="error", error_message="asr down",
              created_at=base + timedelta(minutes=1)),
        QCLog(recording_id=rec.id, user_id=1, text_id=t.id, text_content="上盘镇",
              asr_text="最近一次转译", similarity=0.25, result="failed",
              created_at=base + timedelta(minutes=2)),
    ])
    db.commit()

    r = client.get(f"/api/recordings/{rec.id}/qc", headers=auth_header)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["recording_id"] == rec.id and data["text_content"] == "上盘镇"
    assert len(data["items"]) == 3                 # 含挂旧 recording_id 的历史流水
    assert [i["asr_text"] for i in data["items"]] == ["最近一次转译", "", "最早一次失败"]  # 倒序
    assert data["items"][1]["similarity"] is None and data["items"][1]["error_message"] == "asr down"

    other = make_user(db, phone="33100400003", name="民警二号")
    assert client.get(f"/api/recordings/{rec.id}/qc", headers=auth_of(other)).status_code == 403
    assert client.get("/api/recordings/999/qc", headers=auth_header).status_code == 404

    # pending 且无质检日志 → items 为空
    t2 = Text(content="第二条文本", dialect="临海方言", category="police",
              region_code="331004", dialect_code="dh_lh")
    db.add(t2)
    db.commit()
    rec2 = Recording(user_id=1, text_id=t2.id, file_path="g.wav", file_size=1, duration=1.0,
                     region_code="331004", dialect_code="dh_lh", qc_status="pending")
    db.add(rec2)
    db.commit()
    assert client.get(f"/api/recordings/{rec2.id}/qc", headers=auth_header).json()["data"]["items"] == []


def test_file_download_permissions(client, db, auth_header, tmp_path):
    """契约修订：本人 或 require_admin 且录音 region_code ∈ scope"""
    db.add_all([
        Region(code="330000", name="浙江省", level="province", parent_code=None),
        Region(code="330100", name="杭州市", level="city", parent_code="330000"),
        Region(code="331000", name="台州市", level="city", parent_code="330000"),
        Region(code="331004", name="临海市", level="district", parent_code="331000"),
        Region(code="331082", name="三门县", level="district", parent_code="331000"),
    ])
    f = tmp_path / "r.wav"
    f.write_bytes(b"RIFFdummy")
    rec = Recording(user_id=1, text_id=999, file_path=str(f), file_size=9, duration=1.0,
                    region_code="331004", dialect_code="dh_lh", qc_status="passed")
    db.add(rec)
    db.commit()
    url = f"/api/recordings/{rec.id}/file"

    assert client.get(url, headers=auth_header).status_code == 200          # 本人
    other = make_user(db, phone="33100400003", name="民警二号")
    assert client.get(url, headers=auth_of(other)).status_code == 403       # 他人民警
    city_admin = make_user(db, phone="33100000001", name="台州管理员",
                           role="admin", region="331000")
    assert client.get(url, headers=auth_of(city_admin)).status_code == 200  # 辖区市管（331004 ∈ scope）
    other_admin = make_user(db, phone="33010000001", name="杭州管理员",
                            role="admin", region="330100")
    assert client.get(url, headers=auth_of(other_admin)).status_code == 403  # 越界市管
    sa = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    resp = client.get(url, headers=auth_of(sa))
    assert resp.status_code == 200                                           # 超管（scope None）
    assert resp.headers["content-type"].startswith("audio/")

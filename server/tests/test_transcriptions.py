"""语音转译测试（仿 test_recordings.py 口径）
- 上传：ext 白名单 / 50MB 上限 / 转码失败行删 / 15 分钟上限行删 / trans/ 子目录布局（needs_ffmpeg）
- 泵（直接同步调 pump_pending，monkeypatch services.transcription.SessionLocal → TestingSession）：
  mock 出 done / ASR 异常 failed / 上游未配置 failed / 用户间轮转串行 / 卡死自愈 / 处理中删除竞态
- 端点：fix 语义（设定/撤销/空 400/非 done 400/他人 403）、retry、delete 行+文件、
  列表 filters（status/corrected/file_ext/q/ids/active/分页）、file 下载权限、admin 列表 scope
conftest 默认用户 id=1（测试民警，region 331004）；ASR_UPSTREAM_BASE="" 默认停用。
"""
import os
import shutil
import subprocess
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import create_token
from app.models import Region, Transcription
from app.services import transcription as trans_svc
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
    out = tmp_path_factory.mktemp("trans") / "test.webm"
    subprocess.run(
        [FFMPEG, "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
         "-t", "1", "-c:a", "libopus", str(out)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return out.read_bytes()


@pytest.fixture()
def clean_audio_dir():
    base = settings.audio_storage_path  # conftest 设为 ./test_audio
    if os.path.isdir(base):
        shutil.rmtree(base)
    yield
    if os.path.isdir(base):
        shutil.rmtree(base)


@pytest.fixture()
def pump_db(db, monkeypatch):
    """把泵的模块级 SessionLocal 指到测试内存库（同引擎数据互通），并默认开 mock。
    注意：不能 from tests.conftest import TestingSession —— tests 非包，pytest 以顶层
    `conftest` 名导入、这里再按 `tests.conftest` 导会得到第二份模块（自带一个空
    引擎），泵就查不到表；故由 db.get_bind() 现场派生会话工厂（计划口径）。"""
    session_factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(trans_svc, "SessionLocal", session_factory)
    monkeypatch.setattr(settings, "trans_asr_mock", True)
    yield session_factory


def auth_of(user):
    return {"Authorization": f"Bearer {create_token(str(user.id))}"}


def make_trans(db, user_id=1, status="pending", name="调解录音_0923.wav", ext="wav",
               text_raw="", text_fixed="", error="", region="331004",
               file_path="t.wav", duration=5.0, created=None, updated=None):
    row = Transcription(user_id=user_id, region_code=region, file_name=name, file_ext=ext,
                        file_path=file_path, file_size=12345, duration=duration, status=status,
                        text_raw=text_raw, text_fixed=text_fixed, error_message=error,
                        created_at=created or datetime(2026, 9, 24, 10, 0, 0),
                        updated_at=updated or datetime(2026, 9, 24, 10, 0, 0))
    db.add(row)
    db.commit()
    return row


def upload(client, headers, filename, audio):
    return client.post("/api/transcriptions", headers=headers,
                       files={"file": (filename, audio, "application/octet-stream")})


# ---------- 上传 ----------

@needs_ffmpeg
def test_upload_creates_pending_and_trans_layout(client, db, auth_header, webm_bytes, clean_audio_dir):
    r = upload(client, auth_header, "调解录音_0923.webm", webm_bytes)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] == "pending"                    # 入库即 pending（后台泵接管）
    assert data["file_name"] == "调解录音_0923.webm"
    assert data["file_ext"] == "webm"
    assert data["file_size"] == len(webm_bytes)           # 原始字节数
    assert data["duration"] == pytest.approx(1.0, abs=0.3)
    assert data["corrected"] is False
    assert data["file_url"] == f"/api/transcriptions/{data['id']}/file"

    row = db.query(Transcription).one()
    expected = os.path.join(settings.audio_storage_path, "测试民警_0002",
                            "trans", f"{row.id}.wav")
    assert row.file_path == expected                      # trans/ 子目录，与录音 {id}.wav 撞号隔离
    assert os.path.isfile(expected)
    with open(expected, "rb") as f:
        assert f.read(4) == b"RIFF"


def test_upload_rejects_ext_and_empty(client, db, auth_header):
    r = upload(client, auth_header, "文档.txt", b"hello")
    assert r.status_code == 400                           # ext 白名单
    r = upload(client, auth_header, "空文件.webm", b"")
    assert r.status_code == 400                           # 空文件
    assert db.query(Transcription).count() == 0


def test_upload_rejects_oversize(client, db, auth_header, monkeypatch):
    from app.api import transcriptions as api_trans
    monkeypatch.setattr(api_trans, "TRANS_MAX_BYTES", 8)
    r = upload(client, auth_header, "大文件.wav", b"0123456789")
    assert r.status_code == 400
    assert "50MB" in r.json()["detail"]
    assert db.query(Transcription).count() == 0


def test_upload_rejects_overlong_duration(client, db, auth_header, monkeypatch, clean_audio_dir):
    """时长 > 15 分钟：文件与行都删，400 返回"""
    from app.api import transcriptions as api_trans

    def fake_convert(src, dst):
        return 901.0
    monkeypatch.setattr(api_trans, "convert_to_wav", fake_convert)
    r = upload(client, auth_header, "超长.wav", b"0123456789")
    assert r.status_code == 400
    assert "15 分钟" in r.json()["detail"]
    assert db.query(Transcription).count() == 0           # 行已删


def test_upload_convert_failure_cleans_row(client, db, auth_header, monkeypatch):
    from app.api import transcriptions as api_trans

    def fake_convert(src, dst):
        raise RuntimeError("ffmpeg 转换失败: boom")
    monkeypatch.setattr(api_trans, "convert_to_wav", fake_convert)
    r = upload(client, auth_header, "坏文件.mp3", b"0123456789")
    assert r.status_code == 500
    assert db.query(Transcription).count() == 0           # 转码失败行删，不留 pending 僵尸


# ---------- 泵（services/transcription.py） ----------

def test_pump_mock_done(db, pump_db):
    row = make_trans(db, text_raw="")
    trans_svc.pump_pending()
    db.refresh(row)
    assert row.status == "done"
    assert row.text_raw == trans_svc.MOCK_TEXTS[row.id % len(trans_svc.MOCK_TEXTS)]
    assert row.text_fixed == ""


def test_pump_skips_pending_row_before_upload_finishes(db, pump_db):
    """上传先入库 pending+空 file_path 再转码：泵在转码窗口内扫到也不得抓走
    （否则真实上游收到空路径必失败，误标 failed 需用户手动重试）"""
    empty = make_trans(db, name="大文件.mp4", file_path="")            # 转码中（file_path 未回填）
    ready = make_trans(db, name="小文件.wav", file_path="t.wav",
                       created=datetime(2026, 9, 24, 9, 0, 0))         # 更早的已就绪行
    trans_svc.pump_pending()
    db.refresh(empty)
    db.refresh(ready)
    assert empty.status == "pending"        # 空路径跳过，等上传端点补 file_path 后下轮接管
    assert ready.status == "done"           # 就绪行正常处理（跳过不阻塞队列）


def test_pump_asr_exception_failed(db, pump_db, monkeypatch):
    monkeypatch.setattr(settings, "trans_asr_mock", False)
    monkeypatch.setattr(settings, "asr_upstream_base", "http://fake-upstream")
    monkeypatch.setattr(trans_svc, "call_asr", lambda p: (_ for _ in ()).throw(ValueError("上游 500")))
    row = make_trans(db)
    trans_svc.pump_pending()
    db.refresh(row)
    assert row.status == "failed"
    assert "上游 500" in row.error_message
    assert row.text_raw == ""


def test_pump_upstream_unconfigured_failed(db, pump_db, monkeypatch):
    """asr_upstream_base 空 + 未开 mock → failed「转译服务未配置」（与 QC 直通不同）"""
    monkeypatch.setattr(settings, "trans_asr_mock", False)
    monkeypatch.setattr(settings, "asr_upstream_base", "")
    row = make_trans(db)
    trans_svc.pump_pending()
    db.refresh(row)
    assert row.status == "failed"
    assert "转译服务未配置" in row.error_message


def test_pump_round_robin_and_per_user_serial(db, pump_db, monkeypatch):
    """用户间轮转（A1→B1→A2→B2）且任一时刻每用户至多 1 条 processing"""
    session_factory = pump_db
    monkeypatch.setattr(settings, "trans_asr_mock", False)
    monkeypatch.setattr(settings, "asr_upstream_base", "http://fake-upstream")
    make_user(db)                                       # 先占住 id=1（无 auth_header 时首个用户即 1 号）
    u2 = make_user(db, phone="33100400003", name="民警二号")
    base = datetime(2026, 9, 24, 10, 0, 0)
    rows = [
        make_trans(db, user_id=1, file_path="1_a1.wav", created=base, updated=base),
        make_trans(db, user_id=u2.id, file_path="2_b1.wav",
                   created=base + timedelta(minutes=1), updated=base),
        make_trans(db, user_id=1, file_path="1_a2.wav",
                   created=base + timedelta(minutes=2), updated=base),
        make_trans(db, user_id=u2.id, file_path="2_b2.wav",
                   created=base + timedelta(minutes=3), updated=base),
    ]

    order = []

    def fake_asr(path):
        uid = int(os.path.basename(path).split("_")[0])
        with session_factory() as s:   # 每用户串行：识别中该用户只有当前这一条
            n = (s.query(Transcription)
                 .filter_by(user_id=uid, status="processing").count())
            assert n == 1, f"用户 {uid} 同时有 {n} 条 processing"
        order.append(os.path.basename(path))
        return "转写结果"

    monkeypatch.setattr(trans_svc, "call_asr", fake_asr)
    trans_svc.pump_pending()

    assert order == ["1_a1.wav", "2_b1.wav", "1_a2.wav", "2_b2.wav"]  # 用户间轮转
    db.expire_all()                                      # 泵在别的会话改的状态，弃本地缓存
    for r in db.query(Transcription).all():
        assert r.status == "done"


def test_pump_recovers_stuck_processing(db, pump_db):
    """processing 超 trans_stuck_minutes 按 updated_at 回置 pending 后正常处理；
    未超时的 processing 不动（另一用户，避免「每用户至多 1 条在途」挡住自愈行）"""
    make_user(db)                                       # old 归 1 号；先建避免 u2 抢到 id=1
    old = make_trans(db, status="processing", file_path="stuck.wav",
                     updated=datetime.now() - timedelta(minutes=settings.trans_stuck_minutes + 1))
    u2 = make_user(db, phone="33100400003", name="民警二号")
    fresh = make_trans(db, user_id=u2.id, status="processing", file_path="fresh.wav",
                       updated=datetime.now())
    trans_svc.pump_pending()
    db.refresh(old)
    db.refresh(fresh)
    assert old.status == "done"                          # 卡死行自愈后走完识别
    assert fresh.status == "processing"                  # 未超时不动（泵单线程不会撞它）


def test_pump_tolerates_delete_race(db, pump_db, monkeypatch):
    """识别过程中行被删除：泵不发疯不复活行"""
    session_factory = pump_db
    monkeypatch.setattr(settings, "trans_asr_mock", False)
    monkeypatch.setattr(settings, "asr_upstream_base", "http://fake-upstream")
    row = make_trans(db)
    row.file_path = f"{row.id}.wav"
    db.commit()

    def delete_then_return(path):
        rid = int(os.path.basename(path).split(".")[0])
        with session_factory() as s:
            s.query(Transcription).filter_by(id=rid).delete()
            s.commit()
        return "迟到的识别结果"

    monkeypatch.setattr(trans_svc, "call_asr", delete_then_return)
    trans_svc.pump_pending()                             # 不抛异常即通过
    assert db.query(Transcription).count() == 0          # 行保持删除，未被复活


# ---------- 端点：单条 / fix / retry / delete ----------

def test_get_single_owner_only(client, db, auth_header):
    row = make_trans(db, status="done", text_raw="原文内容")
    r = client.get(f"/api/transcriptions/{row.id}", headers=auth_header)
    assert r.status_code == 200
    assert r.json()["data"]["text_raw"] == "原文内容"
    other = make_user(db, phone="33100400003", name="民警二号")
    assert client.get(f"/api/transcriptions/{row.id}", headers=auth_of(other)).status_code == 403
    assert client.get("/api/transcriptions/999", headers=auth_header).status_code == 404


def test_fix_semantics(client, db, auth_header):
    """设定修正 / 改回原文=撤销（text_fixed 回 ""）/ 空文本 400 / 非 done 400 / 他人 403"""
    row = make_trans(db, status="done", text_raw="落雨了，衣裳好收收了。")
    url = f"/api/transcriptions/{row.id}/fix"

    r = client.post(url, headers=auth_header, json={"text": "落雨了，衣裳好收了。"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["text_fixed"] == "落雨了，衣裳好收了。" and d["corrected"] is True

    r = client.post(url, headers=auth_header, json={"text": "落雨了，衣裳好收收了。"})
    d = r.json()["data"]                                 # 改回原文 → 撤销修正
    assert d["text_fixed"] == "" and d["corrected"] is False

    assert client.post(url, headers=auth_header, json={"text": "  "}).status_code == 400

    pend = make_trans(db, status="pending")
    assert client.post(f"/api/transcriptions/{pend.id}/fix", headers=auth_header,
                       json={"text": "x"}).status_code == 400  # 仅 done 可修正

    other = make_user(db, phone="33100400003", name="民警二号")
    assert client.post(url, headers=auth_of(other), json={"text": "x"}).status_code == 403


def test_retry_semantics(client, db, auth_header):
    row = make_trans(db, status="failed", error="转写接口超时")
    r = client.post(f"/api/transcriptions/{row.id}/retry", headers=auth_header)
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "pending" and d["error_message"] == ""

    done = make_trans(db, status="done", text_raw="原文")
    assert client.post(f"/api/transcriptions/{done.id}/retry",
                       headers=auth_header).status_code == 400   # 仅 failed 可重试

    other = make_user(db, phone="33100400003", name="民警二号")
    assert client.post(f"/api/transcriptions/{row.id}/retry",
                       headers=auth_of(other)).status_code == 403


def test_delete_removes_row_and_file(client, db, auth_header, tmp_path):
    f = tmp_path / "t1.wav"
    f.write_bytes(b"RIFFdummy")
    row = make_trans(db, status="done", file_path=str(f))
    r = client.delete(f"/api/transcriptions/{row.id}", headers=auth_header)
    assert r.status_code == 200 and r.json()["code"] == 0
    assert db.query(Transcription).count() == 0
    assert not f.exists()                                # 盘上文件联动删除

    f2 = tmp_path / "t2.wav"
    f2.write_bytes(b"RIFFdummy")
    row2 = make_trans(db, file_path=str(f2))
    other = make_user(db, phone="33100400003", name="民警二号")
    assert client.delete(f"/api/transcriptions/{row2.id}",
                         headers=auth_of(other)).status_code == 403


# ---------- 端点：列表 filters ----------

def test_list_filters(client, db, auth_header):
    base = datetime(2026, 9, 24, 10, 0, 0)
    make_trans(db, status="done", name="调解录音_0923.wav", ext="wav",
               text_raw="侬好，我是社区民警", text_fixed="侬好，我是社区民警。",
               created=base)
    make_trans(db, status="done", name="走访记录.m4a", ext="m4a",
               text_raw="今朝天气蛮好", created=base + timedelta(minutes=1))
    make_trans(db, status="failed", name="接处警_20260921.mp3", ext="mp3",
               error="转写接口超时", created=base + timedelta(minutes=2))
    make_trans(db, status="pending", name="rec_0047.webm", ext="webm",
               created=base + timedelta(minutes=3))
    make_trans(db, status="processing", name="排队中.mp4", ext="mp4",
               created=base + timedelta(minutes=4))
    u2 = make_user(db, phone="33100400003", name="民警二号")
    make_trans(db, user_id=u2.id, status="done", name="别人的.wav", created=base)

    def get(**params):
        return client.get("/api/transcriptions", headers=auth_header, params=params).json()["data"]

    assert get()["total"] == 5                           # 仅本人
    assert get(status="done")["total"] == 2
    assert get(corrected=True)["total"] == 1
    assert get(corrected=False)["total"] == 4
    assert get(file_ext="webm")["total"] == 1
    assert get(q="调解")["total"] == 1                    # 文件名命中
    assert get(q="今朝")["total"] == 1                    # 识别原文命中
    assert get(active=1)["total"] == 2                    # pending + processing
    d = get(active=1)
    assert {i["status"] for i in d["items"]} == {"pending", "processing"}

    first = get()["items"][0]
    assert first["file_name"] == "排队中.mp4"            # created_at 倒序

    d = get(page=1, page_size=2)
    assert d["total"] == 5 and len(d["items"]) == 2      # 分页

    # ids 批量轮询：只回交集且含他人行被 user 过滤
    ids = [1, 2, 3, 99]
    d = get(ids=",".join(str(i) for i in ids))
    assert d["total"] == 3
    assert get(ids="abc")["total"] == 0                  # 非法 ids → 空页


# ---------- 端点：文件下载权限 ----------

def test_file_download_permissions(client, db, auth_header, tmp_path):
    db.add_all([
        Region(code="330000", name="浙江省", level="province", parent_code=None),
        Region(code="330100", name="杭州市", level="city", parent_code="330000"),
        Region(code="331000", name="台州市", level="city", parent_code="330000"),
        Region(code="331004", name="临海市", level="district", parent_code="331000"),
    ])
    f = tmp_path / "t.wav"
    f.write_bytes(b"RIFFdummy")
    row = make_trans(db, file_path=str(f), region="331004")
    url = f"/api/transcriptions/{row.id}/file"

    assert client.get(url, headers=auth_header).status_code == 200          # 本人
    other = make_user(db, phone="33100400003", name="民警二号")
    assert client.get(url, headers=auth_of(other)).status_code == 403       # 他人民警
    city_admin = make_user(db, phone="33100000001", name="台州管理员",
                           role="admin", region="331000")
    assert client.get(url, headers=auth_of(city_admin)).status_code == 200  # 辖区市管
    other_admin = make_user(db, phone="33010000001", name="杭州管理员",
                            role="admin", region="330100")
    assert client.get(url, headers=auth_of(other_admin)).status_code == 403  # 越界市管
    sa = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    resp = client.get(url, headers=auth_of(sa))
    assert resp.status_code == 200                                           # 超管（scope None）
    assert resp.headers["content-type"].startswith("audio/")


# ---------- 管理端列表 ----------

def test_admin_list_scope_and_filters(client, db, auth_header):
    db.add_all([
        Region(code="330000", name="浙江省", level="province", parent_code=None),
        Region(code="330100", name="杭州市", level="city", parent_code="330000"),
        Region(code="331000", name="台州市", level="city", parent_code="330000"),
        Region(code="331004", name="临海市", level="district", parent_code="331000"),
        Region(code="331023", name="仙居县", level="district", parent_code="331000"),
        Region(code="330105", name="拱墅区", level="district", parent_code="330100"),
    ])
    make_trans(db, user_id=1, status="done", text_raw="临海内容", region="331004")
    make_trans(db, user_id=1, status="failed", region="331023", name="仙居.wav")
    u2 = make_user(db, phone="33010500001", name="杭州民警", region="330105")
    make_trans(db, user_id=u2.id, status="done", region="330105", name="杭州.wav")

    city_admin = make_user(db, phone="33100000001", name="台州管理员",
                           role="admin", region="331000")

    r = client.get("/api/admin/transcriptions", headers=auth_of(city_admin))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["total"] == 2                                # 台州辖区（331004 + 331023），杭州行不可见
    assert {i["region_code"] for i in d["items"]} == {"331004", "331023"}
    assert d["items"][0]["user_name"] == "测试民警"       # ⋈ User 带姓名

    d = client.get("/api/admin/transcriptions", headers=auth_of(city_admin),
                   params={"status": "failed"}).json()["data"]
    assert d["total"] == 1 and d["items"][0]["file_name"] == "仙居.wav"

    sa = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    assert client.get("/api/admin/transcriptions",
                      headers=auth_of(sa)).json()["data"]["total"] == 3   # 超管全量

    assert client.get("/api/admin/transcriptions",
                      headers=auth_header).status_code == 403             # 非管理 403

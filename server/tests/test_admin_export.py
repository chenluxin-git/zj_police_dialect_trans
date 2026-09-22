"""T23 数据集导出测试：两源清单 / 筛选与 scope / 勾选与全量导出 / ZIP_STORED + dataset.txt / 下载即焚 / 逐条 scope 校验
口径：计划 T23 Step 1（passed 录音 + 已判方言 audio_file 全量导出 → task completed、ZIP 内 2 音频 + dataset.txt 两行、
下载即焚二次 404、pending 不入包）+ 清单筛选与逐条 scope 补充。
后台任务说明：实现用 BackgroundTasks（沿用旧项目机制），TestClient 下 POST 返回即任务已完成；
后台任务自带会话工厂（模块级 _session_factory），测试重定向到 db fixture 同一引擎（db.get_bind()，
因 tests/ 无 __init__.py，import tests.conftest 会得到与 pytest 所加载 conftest 不同的模块实例）。
"""
import io
import zipfile

import pytest

from app.core.config import settings
from app.core.security import create_token
from app.models import (Annotation, AudioFile, ExportTask, Recording, Region,  # 模块级导入：conftest 建表前须已注册模型
                        Text, User)
from tests.conftest import make_user


# ---------- 造数 ----------

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


def seed_export_data(db, tmp_path):
    """临海（331004，台州辖区）：passed/pending 录音各 1 + 已判/未判音频各 1；杭州（330105）passed 录音 1"""
    u_lh = db.query(User).filter_by(phone="33100400002").first()  # auth_header fixture 可能已建默认民警
    if u_lh is None:
        u_lh = make_user(db)
    u_hz = make_user(db, phone="33010500002", name="杭州民警", region="330105")

    t_lh = Text(content="你们不要吵了，都先坐下来", dialect="临海方言", category="police",
                region_code="331004", dialect_code="dh_lh")
    t_lh2 = Text(content="我是社区民警，麻烦开下门", dialect="临海方言", category="life",
                 region_code="331004", dialect_code="dh_lh")
    t_hz = Text(content="请出示健康码", dialect="杭州方言", category="police",
                region_code="330105", dialect_code="dh_hz")
    db.add_all([t_lh, t_lh2, t_hz])
    db.commit()

    f_passed = tmp_path / "r_passed.wav"
    f_passed.write_bytes(b"RIFF_passed")
    f_pending = tmp_path / "r_pending.wav"
    f_pending.write_bytes(b"RIFF_pending")
    f_hz = tmp_path / "r_hz.wav"
    f_hz.write_bytes(b"RIFF_hz")

    rec_passed = Recording(user_id=u_lh.id, text_id=t_lh.id, file_path=str(f_passed), file_size=10,
                           duration=3.0, region_code="331004", dialect_code="dh_lh", qc_status="passed")
    rec_pending = Recording(user_id=u_lh.id, text_id=t_lh2.id, file_path=str(f_pending), file_size=10,
                            duration=4.0, region_code="331004", dialect_code="dh_lh", qc_status="pending")
    rec_hz = Recording(user_id=u_hz.id, text_id=t_hz.id, file_path=str(f_hz), file_size=10,
                       duration=5.0, region_code="330105", dialect_code="dh_hz", qc_status="passed")

    f_ann = tmp_path / "a_ann.mp3"
    f_ann.write_bytes(b"MP3_annotated")
    f_unann = tmp_path / "a_unann.mp3"
    f_unann.write_bytes(b"MP3_unannotated")
    af_ann = AudioFile(file_path=str(f_ann), file_name="a_ann.mp3", duration=6.0,
                       region_code="331004", dialect_code="dh_lh")
    af_unann = AudioFile(file_path=str(f_unann), file_name="a_unann.mp3", duration=7.0,
                         region_code="331004", dialect_code="dh_lh")
    db.add_all([rec_passed, rec_pending, rec_hz, af_ann, af_unann])
    db.commit()
    ann = Annotation(file_id=af_ann.id, annotator_id=u_lh.id, is_dialect=True,
                     translation="下雨了，衣服要收起来了", region_code="331004")
    db.add(ann)
    db.commit()
    return {"u_lh": u_lh, "rec_passed": rec_passed, "rec_pending": rec_pending, "rec_hz": rec_hz,
            "af_ann": af_ann, "af_unann": af_unann}


def make_admins(db):
    tz_admin = make_user(db, phone="33100000001", name="台州管理员", role="admin", region="331000")
    hz_admin = make_user(db, phone="33010000001", name="杭州管理员", role="admin", region="330100")
    super_admin = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    return tz_admin, hz_admin, super_admin


def auth_of(user):
    return {"Authorization": f"Bearer {create_token(str(user.id))}"}


@pytest.fixture()
def export_env(db, tmp_path, monkeypatch):
    """后台任务会话 → 与 db fixture 同一引擎（db.get_bind()）；导出目录 → tmp_path（不污染 server/data/exports）"""
    from sqlalchemy.orm import sessionmaker

    from app.api.admin import export as export_module
    monkeypatch.setattr(export_module, "_session_factory",
                        sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(settings, "export_path", str(tmp_path / "exports"))
    return export_module


def read_zip(resp) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(resp.content))


# ---------- 两源清单（计划：recordings 仅 passed + audio_files 已判方言） ----------

def test_audio_list_two_sources_and_scope(client, db, auth_header, tmp_path):
    seed_regions(db)
    seed_export_data(db, tmp_path)
    tz_admin, hz_admin, super_admin = make_admins(db)

    # 民警访问管理端 → 403
    assert client.get("/api/admin/export/audio-list", headers=auth_header).status_code == 403

    # 超管：passed 3 条（331004 两条其一为 pending 不入列）+ 已判方言音频 1 条 = 3
    r = client.get("/api/admin/export/audio-list", headers=auth_of(super_admin))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 3
    sources = {i["source"] for i in data["items"]}
    assert sources == {"recording", "audio_file"}
    contents = {i["text_or_name"] for i in data["items"]}
    assert "你们不要吵了，都先坐下来" in contents          # passed 录音的文本
    assert "我是社区民警，麻烦开下门" not in contents      # pending 录音不入清单
    af_item = next(i for i in data["items"] if i["source"] == "audio_file")
    assert af_item["text_or_name"] == "a_ann.mp3"          # 音频库行含文件名
    assert af_item["translation"] == "下雨了，衣服要收起来了"  # 与译文
    assert af_item["region_code"] == "331004" and af_item["dialect_code"] == "dh_lh"
    rec_item = next(i for i in data["items"] if i["source"] == "recording" and i["region_code"] == "331004")
    assert rec_item["user_real_name"] == "测试民警"         # 录音行含用户

    # 台州市管（scope=331000/331004/331082）：杭州那条被 scope 过滤 → 2
    r2 = client.get("/api/admin/export/audio-list", headers=auth_of(tz_admin))
    assert r2.json()["data"]["total"] == 2

    # 杭州市管：只见杭州 1 条
    r3 = client.get("/api/admin/export/audio-list", headers=auth_of(hz_admin))
    assert r3.json()["data"]["total"] == 1
    assert r3.json()["data"]["items"][0]["region_code"] == "330105"


def test_audio_list_filters(client, db, tmp_path):
    seed_regions(db)
    seed_export_data(db, tmp_path)
    _, _, super_admin = make_admins(db)
    h = auth_of(super_admin)

    # category=police：仅警情类 passed 录音（临海+杭州各 1），音频库无类别不入列
    r = client.get("/api/admin/export/audio-list", headers=h, params={"category": "police"})
    data = r.json()["data"]
    assert data["total"] == 2
    assert all(i["source"] == "recording" and i["category"] == "police" for i in data["items"])

    # dialect 过滤
    r = client.get("/api/admin/export/audio-list", headers=h, params={"dialect": "dh_hz"})
    assert r.json()["data"]["total"] == 1
    r = client.get("/api/admin/export/audio-list", headers=h, params={"dialect": "dh_none"})
    assert r.json()["data"]["total"] == 0

    # region=331000（市码展开整市）：临海 2 条；region=331004 同
    assert client.get("/api/admin/export/audio-list", headers=h,
                      params={"region": "331000"}).json()["data"]["total"] == 2
    assert client.get("/api/admin/export/audio-list", headers=h,
                      params={"region": "331004"}).json()["data"]["total"] == 2

    # annotated=false：音频库源切换为未判方言音频 → passed 录音 2 + 未判音频 1 = 3，且无译文
    r = client.get("/api/admin/export/audio-list", headers=h, params={"annotated": "false"})
    data = r.json()["data"]
    assert data["total"] == 3
    af_items = [i for i in data["items"] if i["source"] == "audio_file"]
    assert len(af_items) == 1
    assert af_items[0]["text_or_name"] == "a_unann.mp3"
    assert af_items[0]["translation"] is None


# ---------- 勾选导出（核心链路：后台 ZIP + dataset.txt + 下载即焚） ----------

def test_export_selected_flow(client, db, tmp_path, export_env):
    seed_regions(db)
    d = seed_export_data(db, tmp_path)
    _, _, super_admin = make_admins(db)
    h = auth_of(super_admin)

    r = client.post("/api/admin/export/audio", headers=h, json={
        "items": [{"source": "recording", "id": d["rec_passed"].id},
                  {"source": "audio_file", "id": d["af_ann"].id}]})
    assert r.status_code == 200 and r.json()["code"] == 0
    task_id = r.json()["data"]["task_id"]

    # 任务台账：completed + 进度满格
    t = client.get(f"/api/admin/export/task/{task_id}", headers=h)
    assert t.status_code == 200
    tdata = t.json()["data"]
    assert tdata["status"] == "completed"
    assert tdata["total_count"] == 2 and tdata["processed_count"] == 2
    assert tdata["file_url"] == f"/api/admin/export/download/{task_id}"

    # 下载 ZIP：2 音频 + dataset.txt 两行（文件名\t区域\t方言\t文本或译文）
    dl = client.get(f"/api/admin/export/download/{task_id}", headers=h)
    assert dl.status_code == 200
    assert dl.headers["content-type"] == "application/zip"
    zf = read_zip(dl)
    names = zf.namelist()
    assert len([n for n in names if n != "dataset.txt"]) == 2
    assert "dataset.txt" in names
    lines = zf.read("dataset.txt").decode("utf-8").strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        cols = line.split("\t")
        assert len(cols) == 4
    joined = "\n".join(lines)
    assert "331004" in joined and "dh_lh" in joined
    assert "你们不要吵了，都先坐下来" in joined          # 录音 → 文本
    assert "下雨了，衣服要收起来了" in joined            # 音频库 → 译文
    # ZIP_STORED 打包
    assert all(zf.getinfo(n).compress_type == zipfile.ZIP_STORED for n in names)

    # 下载即焚：二次下载 404
    dl2 = client.get(f"/api/admin/export/download/{task_id}", headers=h)
    assert dl2.status_code == 404


def test_export_all_excludes_pending_and_unannotated(client, db, tmp_path, export_env):
    seed_regions(db)
    d = seed_export_data(db, tmp_path)
    _, _, super_admin = make_admins(db)
    h = auth_of(super_admin)

    r = client.post("/api/admin/export/audio-all", headers=h, json={})
    assert r.status_code == 200
    task_id = r.json()["data"]["task_id"]
    tdata = client.get(f"/api/admin/export/task/{task_id}", headers=h).json()["data"]
    assert tdata["status"] == "completed"
    assert tdata["total_count"] == 3  # passed 3（含杭州）+ 已判音频 1；pending 与未判音频不入包

    dl = client.get(f"/api/admin/export/download/{task_id}", headers=h)
    zf = read_zip(dl)
    names = zf.namelist()
    audios = [n for n in names if n != "dataset.txt"]
    assert len(audios) == 3
    assert not any("pending" in n for n in audios)
    assert not any("unann" in n for n in audios)
    lines = zf.read("dataset.txt").decode("utf-8").strip().splitlines()
    assert len(lines) == 3

    # 同筛全量：带 region=331000 → 仅台州 2 条
    r2 = client.post("/api/admin/export/audio-all", headers=h, json={"region": "331000"})
    task_id2 = r2.json()["data"]["task_id"]
    tdata2 = client.get(f"/api/admin/export/task/{task_id2}", headers=h).json()["data"]
    assert tdata2["total_count"] == 2


def test_export_selected_scope_skips_out_of_scope(client, db, tmp_path, export_env):
    """逐条 scope 校验：越界项不进包（任务仍完成）"""
    seed_regions(db)
    d = seed_export_data(db, tmp_path)
    tz_admin, _, _ = make_admins(db)
    h = auth_of(tz_admin)

    r = client.post("/api/admin/export/audio", headers=h, json={
        "items": [{"source": "recording", "id": d["rec_passed"].id},   # 331004 ∈ scope
                  {"source": "recording", "id": d["rec_hz"].id}]})     # 330105 ∉ scope
    task_id = r.json()["data"]["task_id"]
    tdata = client.get(f"/api/admin/export/task/{task_id}", headers=h).json()["data"]
    assert tdata["status"] == "completed"

    dl = client.get(f"/api/admin/export/download/{task_id}", headers=h)
    zf = read_zip(dl)
    audios = [n for n in zf.namelist() if n != "dataset.txt"]
    assert len(audios) == 1                     # 仅辖区那条进包
    assert not any("hz" in n for n in audios)   # 越界杭州录音被剔除
    lines = zf.read("dataset.txt").decode("utf-8").strip().splitlines()
    assert len(lines) == 1


def test_export_task_not_found_and_empty_selection(client, db, tmp_path, export_env):
    seed_regions(db)
    seed_export_data(db, tmp_path)
    _, _, super_admin = make_admins(db)
    h = auth_of(super_admin)

    assert client.get("/api/admin/export/task/999", headers=h).status_code == 404
    r = client.post("/api/admin/export/audio", headers=h, json={"items": []})
    assert r.status_code == 400                 # 未选择导出项

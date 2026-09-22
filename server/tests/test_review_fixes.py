"""终审修复回归（requesting-code-review，5 项 Important + minor#4）：
#1 文本导入台账辖区隔离（轮询/详情/撤销 403、列表过滤、属主可撤）
#2 导出任务属主隔离（状态/下载 403、属主与超管 200、即焚后二次 404）
#3 tasks type/target_count 422 + messages target_value 非数字 400
#4 扫盘白名单 SCAN_ROOT（越根/同前缀根外目录 400、根内 200）
#5 侧车台账目录走 settings（text/audio 各自键，容器内指 /data 卷）
minor#4 resolve_scope region 行缺失回退分支（终审判定补测）
"""
import pytest
from sqlalchemy.orm import sessionmaker

from app.core.security import create_token
from app.models import ExportTask, Region, User  # 模块级导入：conftest 建表前须已注册模型
from tests.conftest import make_user


def auth_of(user):
    return {"Authorization": f"Bearer {create_token(str(user.id))}"}


def seed(db):
    db.add_all([
        Region(code="330000", name="浙江省", level="province", parent_code=None),
        Region(code="331000", name="台州市", level="city", parent_code="330000"),
        Region(code="331004", name="路桥区", level="district", parent_code="331000"),
        Region(code="330100", name="杭州市", level="city", parent_code="330000"),
        Region(code="330105", name="拱墅区", level="district", parent_code="330100"),
    ])
    db.commit()


def two_county_admins(db):
    tz = make_user(db, phone="33100400001", name="路桥管理员", role="admin", region="331004")
    hz = make_user(db, phone="33010500001", name="拱墅管理员", role="admin", region="330105")
    return tz, hz


# ---------- #1 文本导入台账辖区隔离 ----------

@pytest.fixture()
def ti_env(db, tmp_path, monkeypatch):
    from app.api.admin import text_import as ti
    monkeypatch.setattr(ti, "_session_factory",
                        sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(ti, "_manifest_dir", lambda: str(tmp_path))
    return ti


def _import_texts(client, h, content):
    return client.post("/api/admin/texts/import", headers=h, data={"category": "police"},
                       files={"file": ("t.txt", content.encode("utf-8"), "text/plain")})


def test_text_import_manage_isolated_by_scope(client, db, ti_env):
    seed(db)
    tz, hz = two_county_admins(db)
    r = _import_texts(client, auth_of(hz), "拱墅批次句子一。句子二。")
    assert r.status_code == 200 and r.json()["code"] == 0
    tid = r.json()["data"]["task_id"]

    # 台州县管对杭州批次：轮询/详情/撤销一律 403（防跨县撤销删除）
    assert client.get(f"/api/admin/texts/import/{tid}", headers=auth_of(tz)).status_code == 403
    assert client.get(f"/api/admin/text-import-manage/{tid}", headers=auth_of(tz)).status_code == 403
    assert client.delete(f"/api/admin/text-import-manage/{tid}", headers=auth_of(tz)).status_code == 403
    # 属主管县可撤销
    assert client.delete(f"/api/admin/text-import-manage/{tid}", headers=auth_of(hz)).status_code == 200

    # 列表只含本辖区批次
    _import_texts(client, auth_of(hz), "拱墅又一批。")
    _import_texts(client, auth_of(tz), "路桥批次。")
    items = client.get("/api/admin/text-import-manage", headers=auth_of(hz)).json()["data"]["items"]
    assert items and all(it["region_code"] == "330105" for it in items)


# ---------- #2 导出任务属主隔离 ----------

def test_export_task_isolated_by_owner(client, db, tmp_path):
    seed(db)
    tz, hz = two_county_admins(db)
    sup = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    z = tmp_path / "pkg.zip"
    z.write_bytes(b"PK\x03\x04fake-zip")
    t = ExportTask(status="completed", total_count=1, processed_count=1,
                   file_path=str(z), created_by=tz.id)
    db.add(t)
    db.commit()

    # 他县管：状态/下载 403（导出包内容按创建者 scope 打包，防跨县取包）
    assert client.get(f"/api/admin/export/task/{t.id}", headers=auth_of(hz)).status_code == 403
    assert client.get(f"/api/admin/export/download/{t.id}", headers=auth_of(hz)).status_code == 403
    # 属主可查可下
    assert client.get(f"/api/admin/export/task/{t.id}", headers=auth_of(tz)).status_code == 200
    assert client.get(f"/api/admin/export/download/{t.id}", headers=auth_of(tz)).status_code == 200
    # 下载即焚后，超管二次下载 404（状态仍可查）
    assert client.get(f"/api/admin/export/task/{t.id}", headers=auth_of(sup)).status_code == 200
    assert client.get(f"/api/admin/export/download/{t.id}", headers=auth_of(sup)).status_code == 404


# ---------- #3 参数校验 ----------

def test_task_assign_type_and_count_validated(client, db):
    seed(db)
    u = make_user(db, phone="33100400002", name="路桥民警", region="331004")
    sup = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    h = auth_of(sup)
    # type 非法 / target_count 非正 → 422（此前裸 str 会 KeyError 500）
    assert client.post("/api/admin/tasks", headers=h,
                       json={"user_id": u.id, "type": "foo", "target_count": 10}).status_code == 422
    assert client.post("/api/admin/tasks", headers=h,
                       json={"user_id": u.id, "type": "recording", "target_count": 0}).status_code == 422
    assert client.post("/api/admin/tasks/batch", headers=h,
                       json={"user_ids": [u.id], "type": "xxx", "target_count": 5}).status_code == 422


def test_message_target_value_numeric_validated(client, db):
    seed(db)
    sup = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    r = client.post("/api/admin/messages", headers=auth_of(sup),
                    json={"target_type": "user", "target_value": "abc", "title": "t", "content": "c"})
    assert r.status_code == 400  # 此前 int("abc") 会 500


# ---------- #4 扫盘白名单 ----------

@pytest.fixture()
def ai_env(db, tmp_path, monkeypatch):
    from app.api.admin import audio_import as ai
    monkeypatch.setattr(ai, "_session_factory",
                        sessionmaker(bind=db.get_bind(), expire_on_commit=False))
    monkeypatch.setattr(ai, "_manifest_dir", lambda: str(tmp_path))
    return ai


def test_scan_root_whitelist(client, db, tmp_path, ai_env, monkeypatch):
    seed(db)
    sup = make_user(db, phone="33000000001", name="省超管", role="super_admin", region="330000")
    h = auth_of(sup)
    root = tmp_path / "scanroot"
    (root / "lib").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    sibling = tmp_path / "scanroot2"  # 同前缀根外目录，防 startswith 误放行
    sibling.mkdir()
    monkeypatch.setattr("app.core.config.settings.scan_root", str(root))

    assert client.post("/api/admin/audio/import", headers=h,
                       json={"server_path": str(outside), "recursive": False}).status_code == 400
    assert client.post("/api/admin/audio/import", headers=h,
                       json={"server_path": str(sibling), "recursive": False}).status_code == 400
    r = client.post("/api/admin/audio/import", headers=h,
                    json={"server_path": str(root / "lib"), "recursive": False,
                          "region_code": "331004"})  # 超管须显式区县级（规格裁定 2026-09-22）
    assert r.status_code == 200 and r.json()["code"] == 0


def test_scan_poll_isolated_by_scope(client, db, tmp_path, ai_env):
    seed(db)
    tz, hz = two_county_admins(db)
    folder = tmp_path / "lib"
    folder.mkdir()
    r = client.post("/api/admin/audio/import", headers=auth_of(tz),
                    json={"server_path": str(folder), "recursive": False})
    tid = r.json()["data"]["task_id"]
    # 扫盘任务结果（含目录明细）仅本辖区可见
    assert client.get(f"/api/admin/audio/import/{tid}", headers=auth_of(hz)).status_code == 403
    d = client.get(f"/api/admin/audio/import/{tid}", headers=auth_of(tz)).json()["data"]
    assert d["status"] == "completed" and d["found"] == 0


# ---------- #5 侧车台账目录走 settings ----------

def test_manifest_dir_from_settings(tmp_path, monkeypatch):
    from app.api.admin import audio_import as ai, text_import as ti
    monkeypatch.setattr("app.core.config.settings.text_import_dir", str(tmp_path / "t"))
    monkeypatch.setattr("app.core.config.settings.audio_import_dir", str(tmp_path / "a"))
    assert ti._manifest_dir() == str(tmp_path / "t")
    assert ai._manifest_dir() == str(tmp_path / "a")


# ---------- minor#4：resolve_scope region 行缺失回退分支 ----------

def test_resolve_scope_missing_region_row_fallback(db):
    seed(db)  # 注意 330999 未播种
    u = make_user(db, phone="33099900001", name="孤县管理员", role="admin", region="330999")
    from app.api.deps import resolve_scope
    assert resolve_scope(db, u) == ["330999"]

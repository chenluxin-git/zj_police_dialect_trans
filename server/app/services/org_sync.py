"""应用管理器「统一用户」组件对接：部门与警员初始化 + 增量同步

对接目标（应用管理器统一集成规范）：
- 初始化：`信息初始化` 接口，部门 `SJLX=1`、用户 `SJLX=3`，分页拉取
- 增量：`获取部门增量信息`（游标 `BEGINID`）、`获取警员增量信息`（游标 `ZID`/`BEGINID`），
  定时频率**不少于 1 分钟**，游标持久化在 `org_sync_cursor` 表
- 每次同步后把 12 位机构代码映射到行政区划代码写入 `org_units.region_code`（见 region_mapper）

⚠️ 参数大小写与字段名以**资源管理器下载的组件调用文档**为准（本文件把服务路径与入参名
放在 `OrgSyncConfig` 中集中可改，避免散落在业务代码里）。
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from sqlalchemy import select

from ..core.config import settings
from ..core.database import SessionLocal
from ..models.org import OrgUnit, OrgSyncCursor
from ..models.social import User
from .audit import service_log
from .region_mapper import map_region_code

logger = logging.getLogger(__name__)

# 单次运行最多拉多少页（防止平台侧游标不前进时死循环；1 页=一次接口调用）
MAX_PAGES_PER_RUN = 50


@dataclass
class OrgSyncConfig:
    """接口地址与入参名（以组件调用文档为准，集中在此便于联调期调整）"""

    base_url: str = ""            # 统一用户组件服务基地址（申请后在组件调用文档中获取）
    init_path: str = "/init"
    dept_increment_path: str = "/deptIncrement"
    user_increment_path: str = "/userIncrement"
    page_size_dept: int = 1000    # 规范建议 ≤1000
    page_size_user: int = 100     # 规范建议 ≤100
    request_id: str = ""          # 即系统标准码/requestId；空则取 zhijing_sys_id
    app_key: str = ""
    app_secret: str = ""
    headers: dict = field(default_factory=dict)


_cfg = OrgSyncConfig()


def configure(cfg: OrgSyncConfig) -> None:
    """显式注入配置（联调/测试用；生产走 settings 自动装载）"""
    global _cfg
    _cfg = cfg


def load_from_settings() -> OrgSyncConfig:
    """从环境配置装载（生产路径：全部参数走 .env，无需改代码）"""
    import json as _json

    headers: dict = {}
    if settings.zhijing_org_headers.strip():
        try:
            parsed = _json.loads(settings.zhijing_org_headers)
            if isinstance(parsed, dict):
                headers = {str(k): str(v) for k, v in parsed.items()}
        except ValueError:
            logger.warning("ZHIJING_ORG_HEADERS 不是合法 JSON，已忽略：%s", settings.zhijing_org_headers)

    return OrgSyncConfig(
        base_url=settings.zhijing_org_base_url,
        init_path=settings.zhijing_org_init_path,
        dept_increment_path=settings.zhijing_org_dept_increment_path,
        user_increment_path=settings.zhijing_org_user_increment_path,
        page_size_dept=settings.zhijing_org_page_size_dept,
        page_size_user=settings.zhijing_org_page_size_user,
        request_id=settings.zhijing_sys_id,
        app_key=settings.zhijing_app_key,
        app_secret=settings.zhijing_app_secret,
        headers=headers,
    )


def current_config() -> OrgSyncConfig:
    """当前生效配置（自检端点展示用，不含 key/secret 明文）"""
    return _cfg


def ensure_configured() -> bool:
    """未显式注入时自动从 settings 装载；返回是否具备可用 base_url"""
    global _cfg
    if not _cfg.base_url:
        _cfg = load_from_settings()
    return bool(_cfg.base_url)


def _post(path: str, payload: dict, *, interface_name: str = "") -> dict:
    ensure_configured()  # 生产路径：未显式注入时自动从环境配置装载
    base = (_cfg.base_url or "").rstrip("/")
    if not base:
        raise RuntimeError("未配置统一用户组件服务地址（ZHIJING_ORG_BASE_URL 或 OrgSyncConfig.base_url）")
    name = interface_name or path
    requester = _cfg.request_id or settings.zhijing_sys_id or "方言语料采集平台"
    headers = {"Content-Type": "application/json", **_cfg.headers}
    try:
        with httpx.Client(timeout=settings.zhijing_timeout, verify=settings.zhijing_verify_ssl) as client:
            resp = client.post(f"{base}{path}", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        # 服务日志：调用统一用户组件失败也要留痕（联调排查看服务日志最快）
        service_log(interface_name=name, requester=requester, interface_result="0", error_code="2000",
                    condition=f"POST {path}",
                    display=f"{type(exc).__name__}: {str(exc)[:200]}", data_level=1)
        raise
    code = str(data.get("status_code", data.get("code", "0000")))
    ok = code in ("0000", "0", "200")
    service_log(interface_name=name, requester=requester,
                interface_result="1" if ok else "0", error_code="" if ok else "2000",
                condition=f"POST {path} rows={len(_rows(data))}",
                display=f"status_code={code} message={str(data.get('message') or data.get('msg') or '')[:200]}",
                data_level=1)
    if not ok:
        raise RuntimeError(f"统一用户接口返回异常：{code} {data.get('message') or data.get('msg') or ''}")
    return data


def _rows(data: dict) -> list[dict]:
    for key in ("result", "data", "rows", "list"):
        value = data.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for inner in ("list", "rows", "data", "records"):
                if isinstance(value.get(inner), list):
                    return value[inner]
    return []


def _cursor(name: str) -> str:
    with SessionLocal() as db:
        row = db.get(OrgSyncCursor, name)
        return row.cursor if row else ""


def _save_cursor(name: str, cursor: str, result: str, delta: int) -> None:
    with SessionLocal() as db:
        row = db.get(OrgSyncCursor, name)
        if row is None:
            row = OrgSyncCursor(name=name)
            db.add(row)
        row.cursor = cursor or row.cursor
        row.last_sync_at = datetime.now()
        row.last_result = result[:500]
        # 新建行时 total_synced 在 flush 前为 None，不能直接 +=（会 TypeError）
        row.total_synced = (row.total_synced or 0) + delta
        db.commit()


# --------------------------------------------------------------------------- #
# 部门
# --------------------------------------------------------------------------- #
def _upsert_dept(db, item: dict) -> bool:
    code = str(item.get("BMCODE") or item.get("bmcode") or item.get("code") or "").strip()
    if not code:
        return False
    row = db.get(OrgUnit, code) or OrgUnit(code=code)
    row.name = str(item.get("BMMC") or item.get("bmmc") or item.get("name") or row.name or "")
    row.parent_code = str(item.get("SJBMCODE") or item.get("parentCode") or item.get("PBMCODE") or row.parent_code or "")
    row.platform_id = str(item.get("BMID") or item.get("bmid") or row.platform_id or "")
    row.begin_id = str(item.get("BEGINID") or item.get("beginid") or row.begin_id or "")
    row.region_code = map_region_code(db, code).region_code
    db.add(row)
    return True


def sync_departments_increment(db=None) -> dict:
    """按 BEGINID 拉部门增量（**分页拉完为止**：返回条数等于分页上限说明还有下一页）"""
    cursor = _cursor("dept")
    saved = 0
    last_cursor = cursor
    pages = 0
    while pages < MAX_PAGES_PER_RUN:
        payload = {
            "requestid": _cfg.request_id or settings.zhijing_sys_id,
            "beginid": last_cursor,
            "maxrows": _cfg.page_size_dept,
        }
        data = _post(_cfg.dept_increment_path, payload, interface_name="获取部门增量信息")
        rows = _rows(data)
        pages += 1
        if not rows:
            break
        with SessionLocal() as s:
            for item in rows:
                if _upsert_dept(s, item):
                    saved += 1
                last_cursor = str(item.get("BEGINID") or item.get("beginid") or last_cursor)
            s.commit()
        if len(rows) < _cfg.page_size_dept:
            break  # 不满一页 = 已拉完（规范推荐判据）
    _save_cursor("dept", last_cursor, f"增量 {saved} 条 / {pages} 页", saved)
    return {"saved": saved, "cursor": last_cursor, "pages": pages}


# --------------------------------------------------------------------------- #
# 警员
# --------------------------------------------------------------------------- #
def _upsert_user(db, item: dict) -> bool:
    cert_id = str(item.get("SFZH") or item.get("sfzh") or item.get("IDCARD") or item.get("idcard") or "").strip()
    police_no = str(item.get("JYCODE") or item.get("jycode") or item.get("POLICENUMBER") or item.get("jh") or "").strip()
    name = str(item.get("JYNAME") or item.get("jyname") or item.get("XM") or item.get("xm") or "").strip()
    org_code = str(item.get("BMCODE") or item.get("bmcode") or item.get("DM") or item.get("dm") or "").strip()
    dept_name = str(item.get("BMMC") or item.get("bmmc") or item.get("DEPTNAME") or "").strip()
    if not (cert_id or police_no):
        return False

    user = None
    if cert_id:
        user = db.scalar(select(User).where(User.cert_id == cert_id))
    if user is None and police_no:
        user = db.scalar(select(User).where(User.police_no == police_no))
    # 手机号也参与认人：`users.phone` 唯一，历史 seed/Excel 导入账号的 phone 就是警号，
    # 不认出来会在插入时撞唯一约束（与 services/zero_trust.py::upsert_user 保持同一策略）
    if user is None:
        for key in (police_no, cert_id):
            if not key:
                continue
            user = db.scalar(select(User).where(User.phone == key))
            if user is not None:
                break

    if user is None:
        user = User(phone=police_no or cert_id or None, password_hash="", real_name=name or "未知名",
                    region_code=map_region_code(db, org_code).region_code, role=settings.zhijing_user_default_role,
                    source="zhijing")
        db.add(user)
    user.cert_id = cert_id or user.cert_id
    user.police_no = police_no or user.police_no
    user.real_name = name or user.real_name
    if org_code:
        user.org_code = org_code
        user.region_code = map_region_code(db, org_code).region_code
    if dept_name:
        user.dept_name = dept_name
        user.police_station = dept_name
    user.source = "zhijing"
    db.add(user)
    return True


def sync_users_increment() -> dict:
    """按 BEGINID 拉警员增量（分页拉完为止）；同步进来的账号无本地口令，只能用平台登录"""
    cursor = _cursor("user")
    saved = 0
    last_cursor = cursor
    pages = 0
    while pages < MAX_PAGES_PER_RUN:
        payload = {
            "REQUESTID": _cfg.request_id or settings.zhijing_sys_id,
            "BEGINID": last_cursor,
            "MAXROWS": _cfg.page_size_user,
            "ISYH": "1",
        }
        data = _post(_cfg.user_increment_path, payload, interface_name="获取警员增量信息")
        rows = _rows(data)
        pages += 1
        if not rows:
            break
        with SessionLocal() as s:
            for item in rows:
                if _upsert_user(s, item):
                    saved += 1
                last_cursor = str(item.get("ZID") or item.get("BEGINID") or item.get("zid") or last_cursor)
            s.commit()
        if len(rows) < _cfg.page_size_user:
            break
    _save_cursor("user", last_cursor, f"增量 {saved} 条 / {pages} 页", saved)
    return {"saved": saved, "cursor": last_cursor, "pages": pages}


# --------------------------------------------------------------------------- #
# 初始化（首次同步；规范：SJLX=1 部门 / 3 用户，分页拉取，记录最后一条作为增量起点）
# --------------------------------------------------------------------------- #
def sync_init(kind: str, *, max_pages: int = MAX_PAGES_PER_RUN) -> dict:
    """全量初始化：`kind` 取 `dept`（SJLX=1）或 `user`（SJLX=3）

    仅用于**首次接入**：把平台现有部门/警员全量拉下来，并把最后一条的游标写入增量游标表，
    之后由定时增量接续。重复执行是幂等的（upsert），但全量拉取较重，不要放进定时任务。
    """
    if kind == "dept":
        sjlx, path, name = "1", _cfg.init_path, "信息初始化（部门）"
    elif kind == "user":
        sjlx, path, name = "3", _cfg.init_path, "信息初始化（警员）"
    else:
        raise ValueError("kind 只支持 dept / user")

    page_size = _cfg.page_size_dept if kind == "dept" else _cfg.page_size_user
    saved = 0
    last_cursor = ""
    page_no = 1
    rows: list[dict] = []
    while page_no <= max_pages:
        payload = {
            "REQUESTID": _cfg.request_id or settings.zhijing_sys_id,
            "PAGENO": page_no,
            "PAGESIZE": page_size,
            "SJLX": sjlx,
        }
        data = _post(path, payload, interface_name=name)
        rows = _rows(data)
        if not rows:
            break
        with SessionLocal() as s:
            for item in rows:
                if kind == "dept":
                    if _upsert_dept(s, item):
                        saved += 1
                    last_cursor = str(item.get("BEGINID") or item.get("beginid") or last_cursor)
                else:
                    if _upsert_user(s, item):
                        saved += 1
                    last_cursor = str(item.get("ZID") or item.get("BEGINID") or item.get("zid") or last_cursor)
            s.commit()
        if len(rows) < page_size:
            break
        page_no += 1

    _save_cursor(kind, last_cursor, f"初始化 {saved} 条 / {page_no} 页", saved)
    return {"saved": saved, "cursor": last_cursor, "pages": page_no}


def sync_all_increment(include_init: bool = False) -> dict:
    result: dict = {}
    try:
        result["dept"] = sync_departments_increment()
    except Exception as exc:  # noqa: BLE001
        logger.warning("部门同步失败：%s", exc)
        result["dept_error"] = str(exc)
    try:
        result["user"] = sync_users_increment()
    except Exception as exc:  # noqa: BLE001
        logger.warning("警员同步失败：%s", exc)
        result["user_error"] = str(exc)
    return result


def current_status() -> dict:
    """当前配置与进度（自检端点用；**只读、不写库**，避免污染内存库测试）"""
    cfg = _cfg if _cfg.base_url else load_from_settings()
    return {
        "enabled": settings.zhijing_org_sync_enabled,
        "base_url_configured": bool(cfg.base_url),
        "interval_seconds": max(60, settings.zhijing_org_sync_seconds),
        "paths": {
            "init": cfg.init_path,
            "dept_increment": cfg.dept_increment_path,
            "user_increment": cfg.user_increment_path,
        },
        "page_size": {"dept": cfg.page_size_dept, "user": cfg.page_size_user},
        "max_pages_per_run": MAX_PAGES_PER_RUN,
    }


def sync_status() -> dict:
    """同步状态（自检端点用）：开关、地址是否配好、两侧游标与上次结果"""
    status = current_status()
    with SessionLocal() as db:
        cursors = {}
        for name in ("dept", "user"):
            row = db.get(OrgSyncCursor, name)
            cursors[name] = {
                "cursor": row.cursor if row else "",
                "last_sync_at": row.last_sync_at.strftime("%Y-%m-%d %H:%M:%S") if row and row.last_sync_at else "",
                "last_result": row.last_result if row else "",
                "total_synced": (row.total_synced or 0) if row else 0,
            }
        unit_count = db.query(OrgUnit).count()
    status["org_units"] = unit_count
    status["cursors"] = cursors
    return status


def initialize(kind: str, *, trigger_token: str = "") -> dict:
    """首次接入用：全量初始化部门或警员（幂等）

    - 结果写服务日志（含耗时），便于联调时核对"到底拉了多少、有没有报错"
    - 初始化会把最后一条游标写入增量游标表，之后由定时增量接续
    """
    import time

    started = time.monotonic()
    try:
        result = sync_init(kind)
    except Exception as exc:  # noqa: BLE001
        service_log(interface_name=f"信息初始化（{'部门' if kind == 'dept' else '警员'}）",
                    requester=_cfg.request_id or settings.zhijing_sys_id or "方言语料采集平台",
                    interface_result="0", error_code="2000",
                    condition=f"trigger={trigger_token or '-'}",
                    display=f"{type(exc).__name__}: {str(exc)[:200]}", data_level=1)
        raise
    service_log(interface_name=f"信息初始化（{'部门' if kind == 'dept' else '警员'}）",
                requester=_cfg.request_id or settings.zhijing_sys_id or "方言语料采集平台",
                interface_result="1",
                condition=f"trigger={trigger_token or '-'}",
                display=f"入库 {result['saved']} 条 / {result['pages']} 页 / 耗时 {time.monotonic() - started:.1f}s",
                data_level=1)
    return {**result, "kind": kind, "elapsed_seconds": round(time.monotonic() - started, 2)}


async def org_sync_loop() -> None:
    """定时增量（规范：频率不少于 1 分钟）"""
    interval = max(60, settings.zhijing_org_sync_seconds)
    while True:
        # 开关打开但地址没配：首轮打一次告警，避免静默不同步
        if settings.zhijing_org_sync_enabled and not ensure_configured():
            logger.error("已开启组织同步但未配置 ZHIJING_ORG_BASE_URL，本轮跳过")
        elif settings.zhijing_org_sync_enabled:
            try:
                await asyncio.to_thread(sync_all_increment)
            except Exception:  # noqa: BLE001
                logger.exception("组织同步循环异常")
        await asyncio.sleep(interval)

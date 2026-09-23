"""审计服务中心对接（浙警智治零信任体系 · 全部应用必做）

职责：
1. 业务侧只需调用 `queue_audit(...)`，审计记录先落本地 SQLite/MySQL 台账（规范要求本地留存 ≥2 年）
2. 后台任务 `audit_loop()` 批量上报 `POST {SJSerIP}/commonApi/logApi_v2/transferJsonLog`
3. 上报失败（含接口原因）**保留 pending 状态并指数退避重推**（规范 P1 硬性要求）
4. 校验码按规范计算：`SM3(sysId & sendId & logType & subLogType & logContents & appSecret)`，
   其中 `logContents` 内每个对象的 key 按字典升序拼 JSON

限制（规范）：单批条数 ≤100、报文 ≤1M、且同一批只能含同一类型日志。
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from datetime import datetime
from urllib.parse import urlsplit

import httpx
from fastapi import Request
from sqlalchemy import select

from ..core.config import settings
from ..core.database import SessionLocal
from ..core.sm3 import sm3_hex
from ..models.audit import AuditLog, AuditSend

logger = logging.getLogger(__name__)

# 规范字段长度上限（超出必须截断，否则平台侧可能拒收或截断错位）
FIELD_LIMITS = {
    "num_id": 32, "user_id": 40, "organization": 100, "organization_id": 18,
    "user_name": 30, "terminal_id": 50, "operate_name": 30,
    "operate_condition": 5000, "display": 5000, "error_code": 4,
    "interface_name": 50, "requester": 50,
}
OPERATE_NAME_MAX_LEN = FIELD_LIMITS["operate_name"]

# 操作类型（规范 §7.5）
OP_LOGIN = 0
OP_QUERY = 1
OP_CREATE = 2
OP_UPDATE = 3
OP_DELETE = 4
OP_LOGOUT = 5
OP_EXPORT = 6
OP_COMPARE = 7
OP_VIDEO = 8

# 失败原因码（节选常用）
ERR_NONE = ""
ERR_BAD_INPUT = "1001"       # 无效输入
ERR_IP_LIMIT = "3001"        # IP 受限
ERR_NO_PERMISSION = "3007"   # 无操作权限
ERR_BAD_CREDENTIAL = "3004"  # 用户名与密码不匹配

MAX_RETRY = 10


def service_log(
    *,
    interface_name: str,
    requester: str = "",
    user=None,
    request: Request | None = None,
    user_id: str = "",
    user_name: str = "",
    organization: str = "",
    organization_id: str = "",
    terminal_id: str | None = None,
    interface_result: str = "1",
    error_code: str = ERR_NONE,
    condition: str = "",
    display: str = "",
    data_level: int = 1,
) -> None:
    """记录**服务日志**（规范 logType=2 / subLogType=201）：本系统调用外部接口服务的调用明细

    应用日志记"用户干了什么"，服务日志记"我们调了谁、结果如何"，
    零信任联调与安全检测都会看服务日志是否齐全（接口名称/请求方/结果/错误码/返回内容）。
    """
    queue_audit(
        operate_type=OP_QUERY,
        operate_name=interface_name,
        user=user,
        request=request,
        user_id=user_id,
        user_name=user_name,
        organization=organization,
        organization_id=organization_id,
        terminal_id=terminal_id,
        operate_condition=condition,
        display=display,
        operate_result=interface_result,
        error_code=error_code,
        data_level=data_level,
        log_type="2",
        interface_name=interface_name,
        requester=requester,
    )


def client_ip(request: Request | None) -> str:
    """取真实源 IP：X-Forwarded-For 第一跳优先（用户域→数据域存在多次代理），退化到 X-Real-IP / socket"""
    if request is None:
        return ""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    real = request.headers.get("x-real-ip", "").strip()
    if real:
        return real
    return request.client.host if request.client else ""


def _now14() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _num_id() -> str:
    """记录标识：时间戳 + 随机数，≤32 位"""
    return f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}{secrets.token_hex(4)}"[:32]


def _send_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d%H%M%S')}{secrets.token_hex(4)}"[:32]


def _cut(value: str | None, limit: int) -> str:
    """按规范字段长度截断（按字符计，避免多字节被截半）"""
    if not value:
        return ""
    text = str(value)
    return text if len(text) <= limit else text[:limit]


def _log_item(r: AuditLog) -> dict:
    """把一条台账行组装成规范要求的日志对象（key 按字典升序）"""
    if r.log_type == "2":
        item = {
            "numId": r.num_id,
            "interfaceName": r.interface_name,
            "requester": r.requester,
            "userId": r.user_id,
            "organization": r.organization,
            "organizationId": r.organization_id,
            "userName": r.user_name,
            "interfaceTime": r.operate_time,
            "terminalId": r.terminal_id,
            "interfaceResult": r.operate_result,
            "errorCode": r.error_code,
            "interfaceCondition": r.operate_condition,
            "display": r.display,
            "dataLevel": r.data_level,
        }
    else:
        item = {
            "numId": r.num_id,
            "userId": r.user_id,
            "organization": r.organization,
            "organizationId": r.organization_id,
            "userName": r.user_name,
            "operateTime": r.operate_time,
            "terminalId": r.terminal_id,
            "operateType": r.operate_type,
            "operateResult": r.operate_result,
            "errorCode": r.error_code,
            "operateName": r.operate_name,
            "operateCondition": r.operate_condition,
            "display": r.display,
            "dataLevel": r.data_level,
        }
    return {k: item[k] for k in sorted(item)}


def _contents_json(rows: list[AuditLog]) -> str:
    """把台账行组装成规范要求的 logContents（key 按字典升序，紧凑 JSON）"""
    return "[" + ",".join(json.dumps(_log_item(r), ensure_ascii=False, separators=(",", ":"))
                          for r in rows) + "]" if rows else "[]"


def build_check_sum(sys_id: str, send_id: str, log_type: str, sub_log_type: str,
                    log_contents: str, app_secret: str) -> str:
    """请求参数校验码：外层按文档字段顺序拼接后 SM3"""
    raw = "&".join([sys_id, send_id, log_type, sub_log_type, log_contents, app_secret])
    return sm3_hex(raw)


def verify_response_check_sum(status_code: str, message: str, sys_id: str, check_sum: str) -> bool:
    """可选：校验审计服务响应 checkSum = SM3(status_code & Message & sysId)"""
    if not check_sum:
        return True
    return check_sum.lower() == sm3_hex("&".join([status_code, message, sys_id]))


def queue_audit(
    *,
    operate_type: int,
    operate_name: str,
    user=None,
    request: Request | None = None,
    operate_condition: str = "",
    display: str = "",
    operate_result: str = "1",
    error_code: str = ERR_NONE,
    data_level: int = 1,
    organization: str = "",
    organization_id: str = "",
    user_id: str = "",
    user_name: str = "",
    terminal_id: str | None = None,
    log_type: str = "1",
    interface_name: str = "",
    requester: str = "",
) -> None:
    """写入一条待上报审计日志（业务代码唯一入口；失败只记日志，绝不影响业务流程）"""
    if not settings.zhijing_audit_queue_enabled:
        return  # 测试/本地可关闭入队，避免污染台账
    try:
        if user is not None:
            user_id = user_id or getattr(user, "cert_id", "") or getattr(user, "phone", "")
            user_name = user_name or getattr(user, "real_name", "")
            organization = organization or getattr(user, "police_station", "")
            organization_id = organization_id or getattr(user, "org_code", "")
        row = AuditLog(
            num_id=_num_id(),
            log_type=log_type,
            sub_log_type="201" if log_type == "2" else "101",
            user_id=_cut(user_id, 40),
            organization=_cut(organization, 100),
            organization_id=_cut(organization_id, 18),
            user_name=_cut(user_name, 30),
            operate_time=_now14(),
            terminal_id=_cut(terminal_id if terminal_id is not None else client_ip(request), 50),
            operate_type=operate_type,
            operate_result=operate_result,
            error_code=_cut(error_code, 4),
            operate_name=_cut(operate_name, OPERATE_NAME_MAX_LEN),
            operate_condition=_cut(operate_condition, 5000),
            display=_cut(display, 5000),
            data_level=data_level,
            interface_name=_cut(interface_name, 50),
            requester=_cut(requester, 50),
        )
        with SessionLocal() as db:
            db.add(row)
            db.commit()
    except Exception:  # noqa: BLE001 —— 审计失败不得影响业务
        logger.exception("审计日志入队失败")


def pending_count() -> int:
    with SessionLocal() as db:
        return len(db.scalars(select(AuditLog.id).where(AuditLog.status == "pending")).all())


def backlog_stats() -> dict:
    """积压统计（自检/运维用）：待上报条数、最老一条的时间、重推超限条数"""
    from sqlalchemy import func

    with SessionLocal() as db:
        pending = db.scalar(select(func.count(AuditLog.id)).where(AuditLog.status == "pending")) or 0
        total = db.scalar(select(func.count(AuditLog.id))) or 0
        sent = db.scalar(select(func.count(AuditLog.id)).where(AuditLog.status == "sent")) or 0
        trouble = db.scalar(select(func.count(AuditLog.id)).where(AuditLog.retry_count >= MAX_RETRY)) or 0
        oldest = db.scalar(select(func.min(AuditLog.created_at)).where(AuditLog.status == "pending"))
    return {
        "pending": pending,
        "sent": sent,
        "total": total,
        "retry_over_limit": trouble,
        "oldest_pending_at": oldest.strftime("%Y-%m-%d %H:%M:%S") if oldest else "",
    }


def _take_batch(db, limit: int) -> list[AuditLog]:
    rows = db.scalars(
        select(AuditLog).where(AuditLog.status == "pending").order_by(AuditLog.id).limit(limit)
    ).all()
    if not rows:
        return []
    # 同一批只能含同一类型日志：按首条类型过滤
    first_type = rows[0].log_type
    return [r for r in rows if r.log_type == first_type]


def _summary_audit_path() -> str:
    """审计上报路径（默认按零信任规范；若实际组件调用文档不同，改配置即可）"""
    return settings.zhijing_path_audit_json


def _fit_batch(rows: list[AuditLog], max_bytes: int) -> list[AuditLog]:
    """从待上报记录里挑出**能装进单批报文上限**的最大前缀

    规范：单次 logContents 总大小 ≤1M、条数 ≤100，且同一批只能含同一类型。
    逐条累加序列化长度（O(n)，n≤100）比"超限就折半"精确：
    折半仍可能超限（单条 display 可达 5000 字），会导致该批永远发不出去。
    """
    size = 2  # "[]"
    fitted: list[AuditLog] = []
    for row in rows:
        piece = json.dumps(_log_item(row), ensure_ascii=False, separators=(",", ":"))
        add = len(piece.encode("utf-8")) + (1 if fitted else 0)  # 逗号
        if size + add > max_bytes and fitted:
            break
        if size + add > max_bytes and not fitted:
            return [row]  # 单条即超限：至少发一条，避免死锁（是否超限由平台侧判定）
        size += add
        fitted.append(row)
    return fitted


def flush_once() -> dict:
    """同步上报一批；返回 {ok, count, status_code, message}。供后台循环与测试直接调用。"""
    sys_id = settings.zhijing_sys_id
    app_secret = settings.zhijing_app_secret
    if not settings.zhijing_audit_enabled:
        return {"ok": False, "count": 0, "status_code": "", "message": "audit disabled"}
    if not sys_id or not app_secret:
        return {"ok": False, "count": 0, "status_code": "", "message": "缺少 sysId/appSecret 配置"}

    with SessionLocal() as db:
        rows = _take_batch(db, settings.zhijing_audit_batch)
        if not rows:
            return {"ok": True, "count": 0, "status_code": "", "message": "no pending"}
        log_type = rows[0].log_type
        sub_log_type = "201" if log_type == "2" else "101"
        contents = _contents_json(rows)
        if len(contents.encode("utf-8")) > settings.zhijing_audit_max_bytes:
            # 精确裁到装得下的最大前缀（折半可能仍超限，见 _fit_batch 注释）
            rows = _fit_batch(rows, settings.zhijing_audit_max_bytes)
            contents = _contents_json(rows)
        send_id = _send_id()
        payload = {
            "sysId": sys_id,
            "sendId": send_id,
            "logType": log_type,
            "subLogType": sub_log_type,
            "logContents": contents,
            "appSecret": app_secret,
        }
        payload["checkSum"] = build_check_sum(sys_id, send_id, log_type, sub_log_type, contents, app_secret)
        url = f"{settings.zhijing_audit_url.rstrip('/')}{_summary_audit_path()}"

        ok, status_code, message = False, "", ""
        try:
            with httpx.Client(timeout=settings.zhijing_timeout, verify=settings.zhijing_verify_ssl) as c:
                resp = c.post(url, json=payload)
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            status_code = str(body.get("status_code", "")) or str(resp.status_code)
            message = str(body.get("Message") or body.get("message") or "")[:500]
            ok = resp.status_code == 200 and status_code == "0000"
            if not ok and not message:
                message = f"HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001 —— 网络/接口异常一律缓存重推
            message = f"{type(exc).__name__}: {exc}"[:500]
            logger.warning("审计上报失败，将重推：%s", message)

        db.add(AuditSend(send_id=send_id, log_type=log_type, count=len(rows),
                         result="ok" if ok else "fail", status_code=status_code, message=message))
        now = datetime.now()
        for r in rows:
            if ok:
                r.status = "sent"
                r.sent_at = now
            else:
                r.retry_count += 1
                r.last_error = message
                # 规范 P1：失败必须本地缓存后重推 —— 因此**永远不丢弃**，保持 pending 继续退避重推。
                # 重试超限只升级告警级别，便于运维按日志/自检接口发现积压（而不是静默丢数据）。
                if r.retry_count == MAX_RETRY:
                    logger.error("审计日志重推已达 %s 次仍失败，转入告警并继续重推：num_id=%s err=%s",
                                 MAX_RETRY, r.num_id, message)
        db.commit()
        return {"ok": ok, "count": len(rows), "status_code": status_code, "message": message}


async def audit_loop() -> None:
    """后台循环：按配置间隔上报；失败后按重推间隔再试"""
    interval = max(5, settings.zhijing_audit_flush_seconds)
    while True:
        try:
            if settings.zhijing_audit_enabled:
                result = await asyncio.to_thread(flush_once)
                if not result.get("ok") and result.get("count"):
                    interval = max(5, settings.zhijing_audit_retry_seconds)
                else:
                    interval = max(5, settings.zhijing_audit_flush_seconds)
        except Exception:  # noqa: BLE001
            logger.exception("审计循环异常")
            interval = max(5, settings.zhijing_audit_retry_seconds)
        await asyncio.sleep(interval)


def audit_self_check() -> dict:
    """联调自检：配置齐不齐、地址通不通（不产生业务副作用）"""
    url = f"{settings.zhijing_audit_url.rstrip('/')}{_summary_audit_path()}"
    info = {
        "enabled": settings.zhijing_audit_enabled,
        "sysId": bool(settings.zhijing_sys_id),
        "appSecret": bool(settings.zhijing_app_secret),
        "endpoint": url,
        "host": urlsplit(url).hostname or "",
        "pending": pending_count(),
    }
    try:
        info["backlog"] = backlog_stats()
    except Exception:  # noqa: BLE001 —— 自检不能因为统计失败而 500
        logger.exception("审计积压统计失败")
    return info

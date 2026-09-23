"""前端日志接收（内网排障用）

前端 JS 崩溃、白屏、接口失败在浏览器里发生，后端完全看不到。本模块接收前端上报，
落 `logs/client.log`，与 `request.log` / `nginx access.log` 用同一个 `trace_id` 对齐。

## 为什么不做鉴权

崩溃可能发生在登录之前（bootstrap 阶段、登录页、回调页），此时没有 token。
若强制鉴权，"最需要日志的那次崩溃"恰恰会被 401 挡掉。因此本接口**匿名可访问**，
代价是必须自己防滥用：

- 请求体上限 256 KB（`main.MAX_CLIENT_LOG_BYTES`）
- 单条 message/stack 截断，条数上限
- 按来源 IP 限流（每分钟 N 条请求）
- 只写文本日志，**不落库**，避免污染业务数据

## 隐私

只记错误文本、堆栈、路由 path、trace_id。前端已把 query 截断成 path，
本模块再做一次兜底清洗（身份证号/手机号打码），防止误报带出个人信息。
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict, deque
from logging.handlers import RotatingFileHandler

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/client-logs", tags=["前端日志"])

CLIENT_LOG = "logs/client.log"
MAX_BODY_BYTES = 256 * 1024
MAX_ITEMS = 100
MAX_FIELD = 4000
RATE_LIMIT_PER_MIN = 60

logger = logging.getLogger("app.client")

# 兜底清洗：前端理论上已处理，这里是"再保险"，防止误报把个人信息写进盘
_PII_PATTERNS = [
    (re.compile(r"\b\d{17}[\dXx]\b"), "<身份证号已打码>"),
    (re.compile(r"\b1[3-9]\d{9}\b"), "<手机号已打码>"),
    (re.compile(r"(?i)(rzzx-usertoken|rzzx-apptoken|authorization|token)([=:]\s*)([^\s&\"',}]+)"),
     r"\1\2<已打码>"),
]

# 简易限流：{ip: deque[时间戳]}。单进程够用（uvicorn 默认单 worker）
_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def _rate_ok(ip: str) -> bool:
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT_PER_MIN:
        return False
    q.append(now)
    return True


def _scrub(text: str) -> str:
    if not text:
        return ""
    out = str(text)[:MAX_FIELD]
    for pattern, repl in _PII_PATTERNS:
        out = pattern.sub(repl, out)
    # 控制字符会污染按行解析，换成可见转义
    return out.replace("\r", "\\r").replace("\n", "\\n")


def _ensure_handler() -> logging.Logger:
    """单独一个轮转 handler，只收前端日志（便于整份回传）。"""
    lg = logging.getLogger("app.client")
    if getattr(lg, "_zjpdt_ready", False):
        return lg
    os.makedirs("logs", exist_ok=True)
    # 前端日志量可能较大，用大小轮转（5MB × 5）防止写满磁盘
    h = RotatingFileHandler(CLIENT_LOG, maxBytes=5 * 1024 * 1024,
                            backupCount=5, encoding="utf-8", delay=False)
    h.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d %(message)s",
                                     "%Y-%m-%d %H:%M:%S"))
    lg.addHandler(h)
    lg.setLevel(logging.INFO)
    lg.propagate = False   # 不再进 app.log，避免重复
    lg._zjpdt_ready = True  # type: ignore[attr-defined]
    return lg


@router.post("")
async def receive_client_logs(request: Request):
    """接收前端批量日志。始终返回 200，避免前端因上报失败而反复重试刷屏。"""
    ip = _client_ip(request)

    if not _rate_ok(ip):
        return JSONResponse({"code": 0, "msg": "rate limited", "data": {"accepted": 0}})

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        logger.warning("前端日志超限被拒：%d 字节 ip=%s", len(raw), ip)
        return JSONResponse({"code": 0, "msg": "too large", "data": {"accepted": 0}})

    try:
        import json
        payload = json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        logger.warning("前端日志解析失败 ip=%s 原始前200字=%s", ip, _scrub(raw[:200].decode("utf-8", "replace")))
        return JSONResponse({"code": 0, "msg": "bad json", "data": {"accepted": 0}})

    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return JSONResponse({"code": 0, "msg": "no items", "data": {"accepted": 0}})

    lg = _ensure_handler()
    accepted = 0
    for it in items[:MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        # 单行输出：便于 grep / 整份回传
        lg.info(
            "CLIENT ip=%s level=%s source=%s route=%s trace=%s status=%s url=%s msg=%s%s",
            ip,
            _scrub(it.get("level", "info")),
            _scrub(it.get("source", "-")),
            _scrub(it.get("route", "-")),
            _scrub(it.get("traceId", "-")),
            _scrub(it.get("status", "-")),
            _scrub(it.get("url", "-")),
            _scrub(it.get("message", "")),
            (f" stack={_scrub(it.get('stack'))}" if it.get("stack") else ""),
        )
        accepted += 1

    return JSONResponse({"code": 0, "msg": "", "data": {"accepted": accepted}})

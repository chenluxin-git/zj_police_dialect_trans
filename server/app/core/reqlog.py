"""请求级日志与追踪（内网联调排障用）

为什么需要它：内网首次部署最怕"出错了但没日志"。本模块解决四件事：

1. **trace_id 贯穿**：每个请求生成/沿用 `X-Trace-Id`，响应头回写，前端错误上报也带同一个 id。
   这样"用户点了一下报错"能和后端某条日志、nginx 某行访问日志对上号。
2. **请求/响应成对入日志**：方法、路径、状态、耗时、真实 IP、用户。慢请求单独告警。
3. **敏感路径的入参留痕**：认证回调必须能看清"平台到底传了什么参数"，
   否则联调时只能靠猜。只对这些路径记，且**令牌只记长度与前后缀，不记全值**。
4. **异常全栈**：任何未捕获异常连同请求上下文写进 error.log，不用再去翻 stdout。

日志文件（都落 `logs/`，容器里挂卷）：
- `app.log`      业务日志（原有）
- `error.log`    ERROR 及以上 + 异常全栈
- `request.log`  一行一请求的结构化记录，**排障主要看这个**
- `startup.log`  启动自检报告（配置齐备性、外部服务可达性）

与审计的关系：本模块是**技术排障日志**，不是合规审计。审计另有 `services/audit.py`
按规范十六字段上报，两者互不替代。
"""
from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger("app.request")

# 请求体要留痕的路径（联调排障关键路径）。
# 只挑这些：认证回调/票据交换/联动服务——即"平台侧主动打进来"的接口。
# 业务接口（录音上传等）体量大或含隐私，不记 body。
BODY_CAPTURE_PREFIXES = (
    "/api/auth/zhijing/callback",
    "/api/auth/zhijing/exchange",
    "/api/auth/login",
    "/api/rzzx/linkage",
)

# 这些字段只记长度/掩码，绝不记全值。
# ⚠️ 必须覆盖「统一认证回调」可能用的全部人员标识字段名别名（见 zero_trust.dynamic_identity）：
# 平台到底传 sfzh 还是 certId 尚未确认，所以两种命名都要按敏感处理。
# 姓名（xm/name）**不**列入：排障时需要看"是谁登的"，且姓名不属于高敏标识。
SENSITIVE_KEYS = {
    # 凭据类
    "token", "password", "secret", "app_secret", "appsecret", "securekey",
    "rzzx-usertoken", "rzzx-apptoken", "authorization", "callersign", "sign",
    "ticket",
    # 人员标识类（身份证号 / 警号）——回调可能放在 query 里，必须脱敏
    "cert_id", "certid", "sfzh", "idcard", "zjh", "usernumber",
    "police_no", "policeno", "policenumber", "jh", "jycode",
}
MAX_BODY_LOG = 4000  # 单条 body 日志上限，防超大报文刷爆日志
SLOW_MS = 3000       # 超过这个耗时按 WARNING 记，便于发现"卡住"的请求

TRACE_HEADER = "X-Trace-Id"


def mask(value: str) -> str:
    """敏感值掩码：保留长度与首尾各 4 字符，便于比对是否被截断/换行污染。"""
    if not value:
        return ""  # 空值原样返回：日志里 `key=` 保持可读，不写成 `<len=0>` 添噪
    s = str(value)
    if len(s) <= 12:
        return f"<len={len(s)}>"
    return f"{s[:4]}…{s[-4:]}(len={len(s)})"


def redact(obj):
    """递归脱敏 dict/list，命中 SENSITIVE_KEYS 的字段走 mask。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in SENSITIVE_KEYS:
                out[k] = mask(v) if v else ""
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def _client_ip(request: Request) -> str:
    """真实源 IP：X-Forwarded-For 取第一跳（用户域访问数据域会多次代理）。"""
    xff = request.headers.get("x-forwarded-for") or ""
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else ""


class RequestLogMiddleware(BaseHTTPMiddleware):
    """一行一请求；异常另记全栈；敏感路径额外记入参。"""

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get(TRACE_HEADER) or uuid.uuid4().hex[:16]
        request.state.trace_id = trace_id
        start = time.perf_counter()

        path = request.url.path
        # query 必须脱敏：动态秘钥回调把身份证号/警号放在参数里
        query = redact_query(request.url.query)
        ip = _client_ip(request)
        ua = request.headers.get("user-agent", "")

        # 平台打进来的请求：先把"有没有带令牌"记下来（这是联调第一诊断点）
        auth_hint = ""
        if "/zhijing/" in path or "/rzzx/" in path:
            ut = request.headers.get("rzzx-usertoken") or ""
            at = request.headers.get("rzzx-apptoken") or ""
            auth_hint = (f" usertoken={'有' if ut else '无'} apptoken={'有' if at else '无'}"
                         f" ctype={request.headers.get('content-type', '-')}")

        body_note = ""
        if any(path.startswith(p) for p in BODY_CAPTURE_PREFIXES):
            body_note = await self._capture_body(request)

        try:
            response = await call_next(request)
        except Exception:
            cost = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "REQ-EXC trace=%s %s %s%s%s ip=%s %sms",
                trace_id, request.method, path, auth_hint, body_note, ip, cost,
            )
            raise

        cost = int((time.perf_counter() - start) * 1000)
        response.headers[TRACE_HEADER] = trace_id

        line = (f"REQ trace={trace_id} {request.method} {path}"
                f"{'?' + query if query else ''} -> {response.status_code} {cost}ms"
                f" ip={ip}{auth_hint}{body_note}")
        if cost >= SLOW_MS:
            logger.warning("SLOW %s", line)
        elif response.status_code >= 500:
            logger.error("%s", line)
        elif response.status_code >= 400:
            logger.warning("%s", line)
        else:
            logger.info("%s", line)

        # nginx/浏览器侧排障：把 trace_id 也给前端，便于前端错误上报对齐
        if response.status_code >= 400:
            logger.info("REQ-ERR-UA trace=%s ua=%s", trace_id, ua)
        return response

    @staticmethod
    async def _capture_body(request: Request) -> str:
        """读一份 body 用于日志，再塞回去供路由正常消费。

        只对这些关键路径做，且限制体积；解析失败也不影响主流程。
        """
        try:
            raw = await request.body()
        except Exception as exc:  # noqa: BLE001
            return f" body=<读取失败 {type(exc).__name__}>"

        async def receive():
            return {"type": "http.request", "body": raw, "more_body": False}

        request._receive = receive  # noqa: SLF001 —— Starlette 约定：替换接收流以回放 body

        if not raw:
            return " body=<空>"
        text = raw.decode("utf-8", errors="replace")
        if len(text) > MAX_BODY_LOG:
            text = text[:MAX_BODY_LOG] + f"…<截断 共{len(raw)}字节>"
        try:
            parsed = json.loads(text)
            text = json.dumps(redact(parsed), ensure_ascii=False)
        except Exception:  # noqa: BLE001 —— 表单/URL 编码，做正则级脱敏
            pass
        text = _scrub_text(text)
        return f" body={text}"


def _scrub_text(text: str) -> str:
    """对 `key=value` / `key: value` / `key":"value"` 三种形态做值掩码。

    用于 query string 与非 JSON 的 body（表单/URL 编码）。
    ⚠️ query string 也必须过这一步：平台动态秘钥回调会把身份证号放在参数里，
    直接落盘等于把公民个人信息写进日志文件。
    """
    import re
    for key in SENSITIVE_KEYS:
        pattern = re.compile(
            rf"({re.escape(key)}\s*[=:]\s*[\"']?)([^&\"'\s,}}]+)", re.IGNORECASE)
        text = pattern.sub(lambda m: m.group(1) + mask(m.group(2)), text)
    return text


def redact_query(query: str) -> str:
    """query string 脱敏后入日志；无 query 返回空串。"""
    if not query:
        return ""
    return _scrub_text(query)

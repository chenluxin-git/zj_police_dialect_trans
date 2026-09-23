"""日志与启动自检（内网联调排障用）

## 为什么单独抽出来

原实现把日志写在 `main.py` 的 `_setup_logging()` 里，有三个致命问题：

1. **`logging.basicConfig()` 被 uvicorn 抢先了不会报错但会失效**，而且
   **uvicorn 自己的启动日志只到 stdout**，容器一重启就没了。内网首次部署失败
   最常见的表现恰恰是启动阶段（连不上库 / 配置缺失 / 端口占用），
   这些日志现在是拿不到的。
2. **没有 trace_id**：前端报错、nginx 访问日志、后端日志三者对不上号。
3. **没有启动自检**：进了内网才发现配置没填全，只能靠人肉猜。

## 日志文件（都落 logs/，容器里挂卷保留）

| 文件 | 内容 | 排障用途 |
| --- | --- | --- |
| `startup.log` | 启动自检报告（配置齐备性 + 外部服务可达性） | **第一个该看的文件** |
| `startup-report.json` | 同上，机器可读，直接回传给开发 | 一键回传 |
| `request.log` | 一行一请求（含 trace_id、耗时、平台令牌有无） | 业务/联调问题 |
| `app.log` | 业务 INFO 及以上 | 上下文 |
| `error.log` | ERROR 及以上 + 异常全栈 | 崩溃类问题 |

保留策略：每日轮转，留 180 天（规范要求本地留存不少于两年；容器卷长期保留，
180 天是单文件轮转上限，实际保留取决于卷容量，见 deploy/README 备份说明）。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = "logs"
BACKUP_DAYS = 180

FMT = "%(asctime)s.%(msecs)03d %(levelname)-5s [%(name)s] %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

# uvicorn 的这几个 logger：接管它们的 handler，让启动日志也进文件
UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _rotating(filename: str, level: int) -> TimedRotatingFileHandler:
    handler = TimedRotatingFileHandler(
        os.path.join(LOG_DIR, filename),
        when="midnight", backupCount=BACKUP_DAYS, encoding="utf-8", delay=False,
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(FMT, DATEFMT))
    return handler


def setup_logging() -> None:
    """安装根 logger 的 handler，并接管 uvicorn 的 logger。

    幂等：重复调用不会叠加 handler（uvicorn --reload 会重入）。
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    root = logging.getLogger()
    if getattr(root, "_zjpdt_configured", False):
        return

    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)

    app_h = _rotating("app.log", logging.INFO)
    err_h = _rotating("error.log", logging.ERROR)
    # 控制台保留：docker logs 仍然能看到，方便容器里直接看
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(FMT, DATEFMT))
    root.addHandler(app_h)
    root.addHandler(err_h)
    root.addHandler(console)

    # 请求日志单独一份，便于整份回传（一行一请求，量大但最好读）
    req_logger = logging.getLogger("app.request")
    req_logger.setLevel(logging.INFO)
    req_logger.propagate = False
    for h in list(req_logger.handlers):
        req_logger.removeHandler(h)
    req_logger.addHandler(_rotating("request.log", logging.INFO))
    req_logger.addHandler(console)

    # 接管 uvicorn：清掉它自带的 handler，交给根 logger（否则启动日志不进文件）
    for name in UVICORN_LOGGERS:
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
    # uvicorn.access 每条请求都会打一行，与我们的 app.request 重复。
    # 抬到 WARNING 让它闭嘴（4xx/5xx 也由 app.request 记了，信息更全）。
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    root._zjpdt_configured = True  # type: ignore[attr-defined]
    logging.getLogger(__name__).info(
        "日志已就绪：logs/{app,error,request}.log（每日轮转，留 %d 天）", BACKUP_DAYS)


# --------------------------------------------------------------------------- #
# 启动自检
# --------------------------------------------------------------------------- #

def _mask_url(url: str) -> str:
    """数据库/服务地址里的口令打码后再进日志。"""
    import re
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:***@", url)


def _ipv4_of(host: str) -> str:
    """解析主机名到 IPv4。

    内网最常见的失败是 DNS 不通（拿到假 IP 或直接解析失败），
    这里把解析结果显式记下来，便于一眼看出是 DNS 问题还是网络问题。
    """
    try:
        import socket
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
        return ",".join(sorted({i[4][0] for i in infos})) or "<无 IPv4>"
    except Exception as exc:  # noqa: BLE001
        return f"<解析失败 {type(exc).__name__}: {exc}>"


def _probe(url: str, timeout: float = 5.0) -> dict:
    """探测外部服务可达性。只做 TCP/TLS 层面判断，不发业务报文。"""
    from urllib.parse import urlparse
    p = urlparse(url)
    host = p.hostname or ""
    port = p.port or (443 if p.scheme == "https" else 80)
    out: dict = {"url": url, "host": host, "port": port, "resolved": _ipv4_of(host)}
    if out["resolved"].startswith("<解析失败"):
        out["tcp"] = "skipped(dns)"
        return out
    try:
        import socket
        with socket.create_connection((host, port), timeout=timeout):
            out["tcp"] = "ok"
    except Exception as exc:  # noqa: BLE001
        out["tcp"] = f"fail({type(exc).__name__})"
    return out


def startup_report(*, probe_network: bool = True) -> dict:
    """生成启动自检报告：配置齐备性 + 外部服务可达性。不产生任何业务数据。

    写 `logs/startup.log`（人读）与 `logs/startup-report.json`（机器读，直接回传）。
    """
    from .config import settings as s

    secret = s.secret_key or ""
    db = s.database_url or ""
    report: dict = {
        "阶段": "启动自检",
        "基础配置": {
            "python": sys.version.split()[0],
            "数据库类型": db.split("://", 1)[0] if db else "<空>",
            "数据库地址": _mask_url(db),
            "SECRET_KEY长度": len(secret),
            "SECRET_KEY是默认值": secret in ("change-me-in-prod", "", "change-me"),
            "FRONTEND_BASE": s.frontend_base,
            "CORS_ORIGINS": s.cors_origins,
            "音频存储目录": s.audio_storage_path,
            "导出目录": s.export_path,
            "ASR质检": s.asr_api_url or "<未配置，质检直通>",
            "扫盘白名单SCAN_ROOT": s.scan_root or "<未限制（生产应设）>",
        },
        "浙警智治": {
            "模式ZHIJING_MODE": s.zhijing_mode,
            "身份来源LOGIN_SOURCE": s.zhijing_login_source,
            "过渡期本地登录LEGACY_LOGIN": s.zhijing_legacy_login,
            "认证回调路径": s.zhijing_callback_path,
            "SYS_ID(系统标准码)": bool(s.zhijing_sys_id),
            "APP_KEY": bool(s.zhijing_app_key),
            "APP_SECRET": bool(s.zhijing_app_secret),
            "DQXTBS": s.zhijing_dqxtbs or f"<回退 SYS_ID>",
            "AUTH_BUTTON(APPID)": s.zhijing_auth_button or "<未配，不做应用级鉴权>",
            "审计上报开关": s.zhijing_audit_enabled,
            "审计批量上限": f"{s.zhijing_audit_batch} 条 / {s.zhijing_audit_max_bytes} 字节",
            "组织同步开关": s.zhijing_org_sync_enabled,
            "组织同步基地址": s.zhijing_org_base_url or "<未配，不同步>",
            "校验SSL": s.zhijing_verify_ssl,
        },
        "外部服务地址": {
            "认证服务SerRzIP": s.zhijing_rz_url,
            "权限服务SerQxIP": s.zhijing_qx_url,
            "审计服务SJSerIP": s.zhijing_audit_url,
        },
    }

    # 配置齐备性直接给结论，省得人肉比对
    problems: list[str] = []
    if s.zhijing_mode == "off":
        problems.append("ZHIJING_MODE=off —— 当前是纯本地账号模式，平台免登录不会生效")
    if s.zhijing_mode == "live":
        for name, val in (("ZHIJING_SYS_ID", s.zhijing_sys_id),
                          ("ZHIJING_APP_KEY", s.zhijing_app_key)):
            if not val:
                problems.append(f"live 模式但 {name} 未配置 —— 认证/审计必填")
        if s.zhijing_audit_enabled and not s.zhijing_app_secret:
            problems.append("审计已开启但 ZHIJING_APP_SECRET 未配置 —— checkSum 无法计算")
        if not s.zhijing_audit_enabled:
            problems.append("ZHIJING_AUDIT_ENABLED=false —— 规范要求所有应用接入审计，上架前须置 true")
    if report["基础配置"]["SECRET_KEY是默认值"]:
        problems.append("SECRET_KEY 仍为默认值 —— 必须替换为不少于 32 位随机串")
    if db.startswith("sqlite"):
        problems.append("数据库仍是 SQLite —— 内网正式环境建议切 MySQL（见 .env.zhijing.docker.example）")
    if not s.scan_root:
        problems.append("SCAN_ROOT 未设置 —— 音频扫盘可读任意路径，生产应设白名单")
    if s.zhijing_legacy_login:
        problems.append("ZHIJING_LEGACY_LOGIN=true —— 保留手机号密码登录，上架检测前建议关闭")
    report["配置问题"] = problems or ["无"]

    if probe_network:
        report["可达性"] = {
            "认证服务": _probe(s.zhijing_rz_url),
            "权限服务": _probe(s.zhijing_qx_url),
            "审计服务": _probe(s.zhijing_audit_url),
        }
    return report


def write_startup_report(report: dict) -> None:
    """报告写日志 + 落一份 JSON 供一键回传。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    log = logging.getLogger("app.startup")
    log.info("=" * 72)
    log.info("启动自检报告（排障请优先提供本文件 logs/startup.log）")
    log.info("=" * 72)
    for section, body in report.items():
        log.info("【%s】", section)
        if isinstance(body, dict):
            for k, v in body.items():
                if isinstance(v, dict):
                    log.info("    %s: %s", k, json.dumps(v, ensure_ascii=False))
                else:
                    log.info("    %s: %s", k, v)
        elif isinstance(body, list):
            for item in body:
                log.info("    - %s", item)
        else:
            log.info("    %s", body)
    log.info("=" * 72)

    path = os.path.join(LOG_DIR, "startup-report.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        log.info("自检报告已写入 %s（可直接回传开发）", path)
    except OSError as exc:
        log.warning("自检报告 JSON 写入失败：%s", exc)

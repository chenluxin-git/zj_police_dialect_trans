#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""浙警智治 · 内网对接信息采集工具（单文件，仅依赖 Python 标准库）

为什么这样设计
--------------
联调前缺的信息分三类，获取方式完全不同：
  1. 平台侧信息（AK/SK、系统标准码、服务地址、认证参数类型、组件调用文档）——只能**要**，脚本问不出来；
  2. 协议侧信息（回调实际传什么参数名、`getLoginUser` 实际返回什么字段、前置代理有没有吞令牌头）
     ——只能**被动接收+抓真实报文**，主动探测猜不出来；
  3. 环境侧信息（连通性、服务端证书链、浏览器与证书介质）——适合本工具。

因此本工具的四条硬规矩：
  1. **被动优先**：`serve` 模式是"平台打我们"，不主动探测平台任何端口；
  2. **只碰文档地址**：`check`/`token` 只访问你显式给出的 URL，**不做端口扫描、不做目录爆破**；
  3. **只读证书**：客户端清单只读证书的 subject/issuer/有效期，**绝不读取或导出私钥**；
  4. **产物不出网**：回调报文含令牌（短期凭据），产物必须留在内网，按敏感材料处置。

子命令
------
  check       连通性 + 服务端 TLS 证书链 + 时钟偏差（回答"要不要装 CA、要不要开策略"）
  serve       被动回调观测器：抓平台真实回调的原始报文，并代调 getLoginUser 落原始 JSON
  token       用 AK/SK 验证凭据与 SM3 签名（联调前唯一能自证签名算法对不对的手段）
  auditstats  从本地审计台账统计**实际登录认证因子**分布（回答"谁在用、用哪种因子"）
  report      把 serve 抓到的回调 JSONL 汇总成 Markdown 报告
  all         串联 check + token + auditstats（不含 serve，serve 需常驻）

用法示例
--------
  # 1) 环境体检（只连下面这几个文档地址，不扫描）
  python zhijing_recon.py check --out ./recon-out

  # 2) AK/SK 与 SM3 签名自证
  python zhijing_recon.py token --ak xxx --sk yyy --sys-id zjfy-001 --out ./recon-out

  # 3) 联调期被动抓回调（把上架时填的"认证URL"临时指向本服务）
  python zhijing_recon.py serve --port 8600 --rz-url https://lxrdl.gat.zj:5010/jiRMS_RzSer --out ./recon-out

  # 4) 汇总成报告
  python zhijing_recon.py report --out ./recon-out
"""
from __future__ import annotations

import argparse
import glob
import http.client
import json
import os
import re
import socket
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

VERSION = "1.0"

# --------------------------------------------------------------------------- #
# 文档中给出的服务地址（Skill：常用服务地址速查）
# 只作为 `check` 的默认目标；不在这里的地址一律不会去连
# --------------------------------------------------------------------------- #
DOC_SERVICES = [
    ("认证服务 SerRzIP", "用户域", "https://lxrdl.gat.zj:5010/jiRMS_RzSer"),
    ("权限服务 SerQxIP", "用户域", "https://lxrdl.gat.zj:5020/jiRMS_QxSer"),
    ("审计服务 SJSerIP", "用户域", "https://41.188.255.179:9000"),
    ("认证服务 SerRzIP", "数据域", "https://rzfw.data.zj:5010/jiRMS_RzSer"),
    ("权限服务 SerQxIP", "数据域", "https://qxfw.data.zj:5020/jiRMS_QxSer"),
    ("审计服务 SJSerIP", "数据域", "https://139.3.6.101:9000"),
    ("GAPM-agent 上报", "用户域", "41.190.21.156:31640"),
    ("AIOS-agent 上报", "用户域", "41.190.21.156:32342"),
    ("Matomo 前端采集", "用户域", "41.190.22.9:9530"),
    ("GAPM-agent 上报", "数据域", "139.6.0.83:11800"),
    ("AIOS-agent 上报", "数据域", "139.6.0.83:1883"),
]

DOC_DNS = [("用户域 DNS", "10.118.1.10"), ("数据域 DNS", "139.8.0.40")]

# getLoginUser 文档声明的输出字段（5.4）——用于"字段存在矩阵"
DOC_LOGIN_USER_FIELDS = ["ID", "SFZH", "IP", "USERNAME", "SEX", "POLICENUMBER",
                         "POLICETYPE", "DM", "DEPTNAME", "RYLB", "APPID"]

# 认证因子候选参数名（审计规范：operateName 必须写**实际**认证因子）
FACTOR_KEYS = ["loginType", "login_type", "rzfs", "authType", "auth_type", "yzfs",
               "yzys", "factor", "authFactor", "loginWay", "login_way", "certType"]

TOKEN_HEADER_NAMES = ["rzzx-usertoken", "rzzx-apptoken"]

DEFAULT_PATHS = {
    "login_user": "/jyglb/apis/V2/getLoginUser",
    "create_app_token": "/jwt/nologin/V2/202307/createAppToken",
    "decode_token": "/jwt/nologin/V2/decodeToken",
    "verify_app_token": "/jwt/nologin/V2/verifyAppToken",
    "verify_user_token": "/jwt/nologin/V2/verifyUserToken",
    "renew_token": "/jwt/nologin/V2/renewOrOfflineToken",
    "app_permission": "/dzRole/V2/202307/jqfw/yyj",
}


def log(msg: str = "") -> None:
    print(msg, flush=True)


def stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# --------------------------------------------------------------------------- #
# 国密 SM3（GB/T 32905-2016）纯 Python 实现
# 与 server/app/core/sm3.py 同源，此处内联以便本工具单文件独立运行
# --------------------------------------------------------------------------- #
_IV = (0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
       0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E)
_MASK32 = 0xFFFFFFFF


def _rotl(x: int, n: int) -> int:
    n %= 32
    return ((x << n) | (x >> (32 - n))) & _MASK32


def _p0(x: int) -> int:
    return x ^ _rotl(x, 9) ^ _rotl(x, 17)


def _p1(x: int) -> int:
    return x ^ _rotl(x, 15) ^ _rotl(x, 23)


def _ff(j: int, x: int, y: int, z: int) -> int:
    return (x ^ y ^ z) if j < 16 else ((x & y) | (x & z) | (y & z))


def _gg(j: int, x: int, y: int, z: int) -> int:
    return (x ^ y ^ z) if j < 16 else ((x & y) | (~x & z) & _MASK32)


def _cf(v, block: bytes):
    w = [int.from_bytes(block[i * 4:i * 4 + 4], "big") for i in range(16)]
    for j in range(16, 68):
        w.append(_p1(w[j - 16] ^ w[j - 9] ^ _rotl(w[j - 3], 15)) ^ _rotl(w[j - 13], 7) ^ w[j - 6])
    w1 = [w[j] ^ w[j + 4] for j in range(64)]
    a, b, c, d, e, f, g, h = v
    for j in range(64):
        t = 0x79CC4519 if j < 16 else 0x7A879D8A
        ss1 = _rotl((_rotl(a, 12) + e + _rotl(t, j)) & _MASK32, 7)
        ss2 = ss1 ^ _rotl(a, 12)
        tt1 = (_ff(j, a, b, c) + d + ss2 + w1[j]) & _MASK32
        tt2 = (_gg(j, e, f, g) + h + ss1 + w[j]) & _MASK32
        d, c, b, a = c, _rotl(b, 9), a, tt1
        h, g, f, e = g, _rotl(f, 19), e, _p0(tt2)
    return tuple(x ^ y for x, y in zip(v, (a, b, c, d, e, f, g, h)))


def sm3_hex(data) -> str:
    """返回 64 位小写十六进制摘要；str 入参按 UTF-8 编码（与 Java digestHex 行为一致）"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    msg = bytes(data)
    bit_len = len(msg) * 8
    padded = msg + b"\x80"
    padded += b"\x00" * ((56 - len(padded) % 64) % 64)
    padded += bit_len.to_bytes(8, "big")
    v = _IV
    for i in range(0, len(padded), 64):
        v = _cf(v, padded[i:i + 64])
    return "".join(x.to_bytes(4, "big").hex() for x in v)


def build_renew_sign(params: dict) -> str:
    """令牌续期注销 callerSign = SM3(去除 callerSign/dqxtbs 后按 key 升序的 JSON)

    规范：入参**去除 callerSign、dqxtbs 后按 key 递增排序**，对 JSON 对象做 SM3。
    """
    payload = {k: v for k, v in params.items() if k not in ("callerSign", "dqxtbs")}
    raw = json.dumps({k: payload[k] for k in sorted(payload)},
                     ensure_ascii=False, separators=(",", ":"))
    return sm3_hex(raw)


# --------------------------------------------------------------------------- #
# HTTP / TLS 基础
# --------------------------------------------------------------------------- #
def build_ssl_ctx(verify: bool, cacert: str = ""):
    if not verify:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if cacert:
        ctx = ssl.create_default_context(cafile=cacert)
    else:
        ctx = ssl.create_default_context()
    return ctx


def http_request(url: str, *, method: str = "GET", payload: dict | None = None,
                 headers: dict | None = None, timeout: int = 15,
                 verify: bool = False, cacert: str = "") -> dict:
    """返回 {ok, http_status, body, error, resp_headers}；HTTPError 也读 body（平台错误码常在 body 里）"""
    out = {"ok": False, "http_status": 0, "body": "", "error": "", "resp_headers": {}}
    data = None
    hdrs = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json;charset=UTF-8")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    ctx = build_ssl_ctx(verify, cacert)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            out["http_status"] = resp.status
            out["body"] = resp.read().decode("utf-8", "replace")
            out["resp_headers"] = {k: v for k, v in resp.headers.items()}
            out["ok"] = True
    except urllib.error.HTTPError as exc:  # 4xx/5xx 但body有内容
        out["http_status"] = exc.code
        try:
            out["body"] = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        out["error"] = f"HTTP {exc.code}"
        out["resp_headers"] = {k: v for k, v in (exc.headers or {}).items()}
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def parse_json(text: str):
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def split_host_port(url: str, default_port: int = 443) -> tuple[str, str, int, str]:
    """把 'host:port' 或 'https://host:port/path' 统一拆成 (scheme, host, port, path)"""
    raw = url.strip()
    if "://" not in raw:
        raw = "https://" + raw
    p = urllib.parse.urlsplit(raw)
    scheme = p.scheme or "https"
    host = p.hostname or ""
    port = p.port or (443 if scheme == "https" else 80)
    path = p.path or ""
    return scheme, host, port, path


# --------------------------------------------------------------------------- #
# 模式一：check —— 连通性 + 服务端 TLS 证书链 + 时钟偏差
# --------------------------------------------------------------------------- #
def _decode_cert(der: bytes) -> dict:
    """解析服务端证书：优先 cryptography，回退 CPython 私有 ssl._test_decode_cert"""
    try:
        from cryptography import x509  # type: ignore
        from cryptography.hazmat.primitives import hashes  # type: ignore
        c = x509.load_der_x509_certificate(der)
        try:
            san = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            san_list = [str(x.value) for x in san]
        except Exception:  # noqa: BLE001
            san_list = []
        return {
            "subject": c.subject.rfc4514_string(),
            "issuer": c.issuer.rfc4514_string(),
            "not_before": c.not_valid_before_utc.isoformat(),
            "not_after": c.not_valid_after_utc.isoformat(),
            "serial": format(c.serial_number, "x"),
            "sha256": c.fingerprint(hashes.SHA256()).hex(),
            "san": san_list,
        }
    except Exception:  # noqa: BLE001
        pass
    try:
        with tempfile.NamedTemporaryFile("wb", suffix=".pem", delete=False) as fh:
            import base64
            b64 = base64.encodebytes(der).decode("ascii")
            fh.write(b"-----BEGIN CERTIFICATE-----\n" + b64.encode() + b"-----END CERTIFICATE-----\n")
            tmp = fh.name
        try:
            info = ssl._ssl._test_decode_cert(tmp)  # type: ignore[attr-defined]
        finally:
            os.unlink(tmp)
        return {
            "subject": "".join(f"{k}={v}" for rdn in info.get("subject", ()) for k, v in rdn),
            "issuer": "".join(f"{k}={v}" for rdn in info.get("issuer", ()) for k, v in rdn),
            "not_before": info.get("notBefore", ""),
            "not_after": info.get("notAfter", ""),
            "serial": info.get("serialNumber", ""),
            "sha256": "",
            "san": [v for k, v in info.get("subjectAltName", ()) if k.lower() == "dns"],
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": f"证书解析失败：{type(exc).__name__}: {exc}"}


def _is_self_signed(cert: dict) -> bool:
    s, i = cert.get("subject", ""), cert.get("issuer", "")
    return bool(s) and s == i


def check_one(name: str, zone: str, url: str, *, timeout: int, verify: bool,
              cacert: str) -> dict:
    scheme, host, port, path = split_host_port(url)
    r = {"名称": name, "区域": zone, "地址": url, "主机": host, "端口": port}

    # (1) DNS
    t0 = time.time()
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
        ips = sorted({i[4][0] for i in infos})
        r["dns"] = {"结果": "解析成功", "IP": ips, "耗时ms": int((time.time() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        r["dns"] = {"结果": f"解析失败：{type(exc).__name__}", "IP": [], "耗时ms": int((time.time() - t0) * 1000)}
        r["tcp"] = {"结果": "未测（DNS 失败）"}
        r["结论"] = "不通：域名解析失败（检查 DNS 或 hosts）"
        return r

    # (2) TCP
    t0 = time.time()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            r["tcp"] = {"结果": "连接成功", "耗时ms": int((time.time() - t0) * 1000)}
    except Exception as exc:  # noqa: BLE001
        r["tcp"] = {"结果": f"连接失败：{type(exc).__name__}", "耗时ms": int((time.time() - t0) * 1000)}
        r["结论"] = "不通：端口不可达（需申请网络策略开通）"
        return r

    # (3) TLS
    if scheme == "https":
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with socket.create_connection((host, port), timeout=timeout) as sock:
                with ctx.wrap_socket(sock, server_hostname=host) as ss:
                    der = ss.getpeercert(binary_form=True)
                    r["tls"] = {"协议": ss.version(), "套件": (ss.cipher() or ("", "", 0))[0]}
            cert = _decode_cert(der) if der else {}
            cert["是否自签"] = _is_self_signed(cert)
            # 用系统信任库真校验一次 —— 决定 ZHIJING_VERIFY_SSL 能不能开
            vctx = ssl.create_default_context(cafile=cacert) if cacert else ssl.create_default_context()
            try:
                with socket.create_connection((host, port), timeout=timeout) as sock:
                    with vctx.wrap_socket(sock, server_hostname=host):
                        pass
                cert["受信校验"] = "通过（公网/受信 CA 签发，verify_ssl 可置 True）"
            except ssl.SSLCertVerificationError as exc:
                cert["受信校验"] = f"失败：{exc.verify_message}（私有 CA/自签 → 需把 CA 证书装进镜像后开启校验）"
            except Exception as exc:  # noqa: BLE001
                cert["受信校验"] = f"失败：{type(exc).__name__}"
            r["证书"] = cert
        except Exception as exc:  # noqa: BLE001
            r["tls"] = {"错误": f"{type(exc).__name__}: {exc}"}

    # (4) 时钟偏差（令牌含毫秒时间戳，服务器时钟偏移会导致认证失败）
    try:
        h_ctx = build_ssl_ctx(verify, cacert)
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout, context=h_ctx) as resp:
            date_hdr = resp.headers.get("Date", "")
            r["http_status"] = resp.status
        if date_hdr:
            try:
                from email.utils import parsedate_to_datetime
                srv = parsedate_to_datetime(date_hdr)
                if srv.tzinfo is None:
                    srv = srv.replace(tzinfo=timezone.utc)
                skew = (datetime.now(timezone.utc) - srv).total_seconds()
                r["时钟偏差秒"] = round(skew, 1)
                r["时钟"] = ("正常" if abs(skew) <= 60
                            else f"偏差 {skew:.0f}s：会影响应用令牌/令牌续期的时间戳校验，请校准 NTP")
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        r.setdefault("http_status", f"未取到（{type(exc).__name__}）")

    if "结论" not in r:
        r["结论"] = "通"
    return r


def mode_check(args) -> int:
    outdir = ensure_outdir(args.out)
    targets = []
    for u in (args.url or []):
        targets.append((f"自定义 {u}", "自定义", u))
    if not args.url or args.also_doc:
        for name, zone, url in DOC_SERVICES:
            targets.append((name, zone, url))
    if not args.url:
        log("提示：本模式只连接下面列出的**文档地址**，不做端口扫描、不做目录探测。")
        log(f"      （若只想测自己的地址，加 --url，并去掉 --also-doc）\n")

    log(f"=== 连通性 / TLS 证书链 / 时钟 体检（{len(targets)} 个地址）===")
    results = []
    for name, zone, url in targets:
        r = check_one(name, zone, url, timeout=args.timeout, verify=args.verify_ssl, cacert=args.cacert)
        results.append(r)
        tag = "OK  " if r.get("结论") == "通" else "FAIL"
        extra = ""
        if "证书" in r:
            extra = f" | 证书签发者={r['证书'].get('issuer', '?')[:60]}"
            if r["证书"].get("是否自签"):
                extra += " [自签]"
        log(f"[{tag}] {name}({zone}) {url} —— {r.get('结论')}{extra}")

    # DNS 服务器可达性（只 ping 文档给出的 DNS 地址）
    dns_res = []
    if not args.url:
        log("\n--- DNS 服务器可达性（仅文档地址） ---")
        for name, ip in DOC_DNS:
            try:
                with socket.create_connection((ip, 53), timeout=args.timeout):
                    dns_res.append({"名称": name, "地址": ip, "结果": "53/tcp 可达"})
                    log(f"[OK  ] {name} {ip} —— 53/tcp 可达")
            except Exception as exc:  # noqa: BLE001
                dns_res.append({"名称": name, "地址": ip, "结果": f"不可达：{type(exc).__name__}"})
                log(f"[FAIL] {name} {ip} —— 不可达（{type(exc).__name__}）")

    payload = {
        "生成时间": datetime.now().isoformat(timespec="seconds"),
        "本机": local_env(),
        "目标": results,
        "DNS服务器": dns_res,
        "说明": "仅连接上述显式地址；未做端口扫描。",
    }
    jpath = os.path.join(outdir, f"check-{stamp()}.json")
    write_json(jpath, payload)
    mpath = jpath[:-5] + ".md"
    write_text(mpath, check_markdown(payload))
    log(f"\n已写出：{jpath}\n已写出：{mpath}")
    return 0


def local_env() -> dict:
    import platform
    info = {
        "python": sys.version.split()[0],
        "平台": platform.platform(),
        "主机名": socket.gethostname(),
        "本机时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "时区": time.strftime("%Z"),
        "UTC偏移分钟": -time.timezone // 60,
    }
    # 时钟/时区是令牌时间戳校验的隐形杀手，单独报出来
    if abs(-time.timezone // 60) != 480:
        info["时区告警"] = f"UTC 偏移 {-time.timezone // 60} 分钟，非中国时区(+480)，建议统一为 Asia/Shanghai"
    return info


def check_markdown(payload: dict) -> str:
    L = ["# 浙警智治 · 内网环境体检报告", "",
         f"> 生成时间：{payload['生成时间']}",
         f"> 本机：{payload['本机'].get('平台')} / Python {payload['本机'].get('python')}",
         f"> 本机时间：{payload['本机'].get('本机时间')}（时区 {payload['本机'].get('时区')}）", ""]
    if payload["本机"].get("时区告警"):
        L += [f"> ⚠️ {payload['本机']['时区告警']}", ""]
    L += ["## 连通性一览", "",
          "| 目标 | 区域 | 地址 | DNS | TCP | TLS | 结论 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in payload["目标"]:
        L.append("| {} | {} | {} | {} | {} | {} | {} |".format(
            r["名称"], r["区域"], r["地址"],
            r.get("dns", {}).get("结果", "-"), r.get("tcp", {}).get("结果", "-"),
            r.get("tls", {}).get("协议", r.get("tls", {}).get("错误", "-")), r.get("结论", "-")))
    L += ["", "## 服务端证书链（决定 ZHIJING_VERIFY_SSL 能否开启）", ""]
    for r in payload["目标"]:
        c = r.get("证书")
        if not c:
            continue
        L += [f"### {r['名称']}（{r['区域']}）`{r['地址']}`", "",
              f"- 主体：`{c.get('subject', '?')}`",
              f"- 签发者：`{c.get('issuer', '?')}`",
              f"- 有效期：`{c.get('not_before', '?')}` ~ `{c.get('not_after', '?')}`",
              f"- 是否自签：**{'是' if c.get('是否自签') else '否'}**",
              f"- 受信校验：{c.get('受信校验', '?')}",
              f"- SAN：{', '.join(c.get('san') or []) or '（无）'}",
              f"- SHA256：`{c.get('sha256', '') or '（未解析）'}`", ""]
    L += ["## 时钟偏差（令牌时间戳校验相关）", ""]
    for r in payload["目标"]:
        if "时钟偏差秒" in r:
            L.append(f"- {r['名称']}：{r['时钟偏差秒']}s —— {r.get('时钟', '')}")
    L += ["", "## DNS 服务器", ""]
    for d in payload.get("DNS服务器", []):
        L.append(f"- {d['名称']} `{d['地址']}`：{d['结果']}")
    L += ["", "---", "",
          "**本报告只包含显式列出的文档地址的连通性与证书信息；未做端口扫描、未做目录探测。**", ""]
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# 模式二：serve —— 被动回调观测器（最高价值）
# --------------------------------------------------------------------------- #
def call_get_login_user(rz_url: str, app_token: str, user_token: str, dqxtbs: str,
                        *, path: str, timeout: int, verify: bool, cacert: str) -> dict:
    url = rz_url.rstrip("/") + path
    body = {"appTokenId": app_token, "userTokenId": user_token, "dqxtbs": dqxtbs}
    resp = http_request(url, method="POST", payload=body, timeout=timeout,
                        verify=verify, cacert=cacert)
    data = parse_json(resp["body"])
    out = {"url": url, "请求": body, "http_status": resp["http_status"],
           "error": resp["error"], "原始响应": resp["body"][:20000]}
    if isinstance(data, dict):
        out["status_code"] = str(data.get("status_code", ""))
        out["message"] = str(data.get("message", ""))
        result = data.get("result") or {}
        if isinstance(result, dict):
            out["字段存在情况"] = {f: (f in result) for f in DOC_LOGIN_USER_FIELDS}
            out["字段多余项"] = sorted(set(result) - set(DOC_LOGIN_USER_FIELDS))
            out["SFZH形态"] = classify_id(str(result.get("SFZH", "") or ""))
            out["DM长度"] = len(str(result.get("DM", "") or ""))
            out["结果"] = result
    else:
        out["字段存在情况"] = {}
        out["解析"] = "响应不是 JSON"
    return out


def classify_id(v: str) -> str:
    if not v:
        return "空"
    if re.fullmatch(r"\d{17}[\dXx]", v):
        return "18位身份证号（与文档 SFZH 一致）"
    if re.fullmatch(r"[0-9A-Fa-f]{32}", v):
        return "32位十六进制（疑似**数字证书主体标识**，非身份证号）"
    if re.fullmatch(r"[0-9A-Fa-f]{40}", v):
        return "40位十六进制（疑似证书指纹/主体标识）"
    if re.fullmatch(r"\d{6,18}", v):
        return f"纯数字 {len(v)} 位（形态待确认）"
    return f"其他形态（长度 {len(v)}）"


def _mask(v: str, keep: int = 2) -> str:
    v = str(v or "")
    if not v:
        return ""
    if len(v) <= keep:
        return v[0] + "*" * (len(v) - 1)
    return v[:keep] + "*" * max(3, len(v) - keep)


def mode_serve(args) -> int:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    outdir = ensure_outdir(args.out)
    jsonl = os.path.join(outdir, f"callbacks-{stamp()}.jsonl")

    log("=== 被动回调观测器（不主动探测任何平台端口）===")
    log(f"监听：http://{args.bind}:{args.port}/   （任意方法、任意路径都会被记录）")
    log(f"落盘：{jsonl}")
    log("用法：把上架时的『认证URL』临时指向本地址，然后从浙警智治终端点开应用。")
    log("      抓够样本后 Ctrl+C 停止，再跑 report 子命令汇总。")
    if args.bind == "0.0.0.0":
        log("\n⚠️  当前监听 0.0.0.0：只允许在内网、且经报备后这样用。")
    log("\n" + "-" * 78)

    state = {"count": 0}

    class Handler(BaseHTTPRequestHandler):
        server_version = "zhijing-recon/" + VERSION
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *a):  # 静音默认访问日志，我们自己打
            pass

        def _collect(self):
            parsed = urllib.parse.urlsplit(self.path)
            query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
            query = {}
            for k, v in query_pairs:
                query[k] = v if k not in query else f"{query[k]},{v}"
            headers = {k: v for k, v in self.headers.items()}
            low = {k.lower(): v for k, v in headers.items()}
            length = int(self.headers.get("Content-Length") or 0)
            body = ""
            if length:
                body = self.rfile.read(min(length, 1024 * 512)).decode("utf-8", "replace")
            body_form = {}
            if body and "=" in body and "{" not in body[:1]:
                body_form = dict(urllib.parse.parse_qsl(body, keep_blank_values=True))

            user_token = low.get("rzzx-usertoken", "") or query.get("RZZX-USERTOKEN", "") or body_form.get("RZZX-USERTOKEN", "")
            app_token = low.get("rzzx-apptoken", "") or query.get("RZZX-APPTOKEN", "") or body_form.get("RZZX-APPTOKEN", "")
            if low.get("rzzx-usertoken"):
                transport = "header"          # 规范首选，且证明前置代理没吞头
            elif query.get("RZZX-USERTOKEN") or body_form.get("RZZX-USERTOKEN"):
                transport = "query/body（回退路径）"
            else:
                transport = "none（仅参数下发，无令牌）"

            xff = low.get("x-forwarded-for", "")
            rec = {
                "时间": datetime.now().isoformat(timespec="milliseconds"),
                "方法": self.command,
                "路径": parsed.path,
                "原始query": parsed.query,
                "query": query,
                "query参数名": sorted(query),
                "请求头名": sorted(headers),
                "请求头": headers,
                "body": body[:20000],
                "body参数名": sorted(body_form),
                "来源IP": self.client_address[0],
                "X-Forwarded-For": xff,
                "真实源IP首跳": (xff.split(",")[0].strip() if xff else self.client_address[0]),
                "令牌传输方式": transport,
                "收到用户令牌": bool(user_token),
                "收到应用令牌": bool(app_token),
            }

            # 认证因子候选：审计 operateName 必须写实际因子
            factors = {}
            for src_name, src in (("query", query), ("body", body_form)):
                for k in FACTOR_KEYS:
                    if src.get(k):
                        factors[f"{src_name}.{k}"] = src[k]
            rec["认证因子候选"] = factors

            if args.call_auth and user_token:
                try:
                    rec["getLoginUser"] = call_get_login_user(
                        args.rz_url, app_token, user_token, args.dqxtbs,
                        path=args.login_user_path, timeout=args.timeout,
                        verify=args.verify_ssl, cacert=args.cacert)
                except Exception as exc:  # noqa: BLE001
                    rec["getLoginUser"] = {"error": f"{type(exc).__name__}: {exc}"}

            with open(jsonl, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

            state["count"] += 1
            n = state["count"]
            extra = ""
            glu = rec.get("getLoginUser") or {}
            if glu.get("status_code"):
                extra = f" | getLoginUser status_code={glu['status_code']} SFZH={glu.get('SFZH形态', '')}"
            elif glu.get("error"):
                extra = f" | getLoginUser 调用失败：{glu['error']}"
            log(f"[{n:03d}] {rec['时间']} {rec['方法']} {rec['路径']}"
                f" 令牌={rec['令牌传输方式']} 参数={rec['query参数名'] or rec['body参数名']}{extra}")
            if factors:
                log(f"      认证因子候选：{factors}")
            return rec

        def _respond(self):
            try:
                self._collect()
            except Exception as exc:  # noqa: BLE001
                log(f"      !! 记录失败：{type(exc).__name__}: {exc}")
            page = ("<html><meta charset='utf-8'><body style='font-family:sans-serif'>"
                    "<h3>已收到回调，事件已落盘</h3>"
                    f"<p>累计 {state['count']} 条。可继续从浙警智治终端点开应用采集样本。</p>"
                    "<p>抓够后回到运行本服务的终端按 Ctrl+C，再执行 "
                    "<code>report</code> 子命令。</p></body></html>").encode("utf-8")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(page)
            except Exception:  # noqa: BLE001
                pass

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _respond

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            """客户端提前断开属正常（浏览器/代理惯常行为），不要刷 traceback 干扰观测"""
            exc = sys.exc_info()[1]
            if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
                return
            log(f"      !! 连接异常 {client_address}：{type(exc).__name__}: {exc}")

    httpd = Server((args.bind, args.port), Handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log(f"\n停止。共记录 {state['count']} 条回调 → {jsonl}")
        log(f"下一步：python {os.path.basename(__file__)} report --out {outdir}")
    finally:
        httpd.server_close()
    return 0


# --------------------------------------------------------------------------- #
# 模式三：token —— AK/SK 与 SM3 签名自证
# --------------------------------------------------------------------------- #
def mode_token(args) -> int:
    outdir = ensure_outdir(args.out)
    rz = args.rz_url.rstrip("/")
    log("=== AK/SK 与服务端签名自证（只调用文档接口，不扫描）===")
    log(f"认证服务：{rz}\n")

    result = {"生成时间": datetime.now().isoformat(timespec="seconds"),
              "认证服务": rz, "步骤": []}

    def post(path: str, payload: dict, title: str) -> tuple[dict, dict]:
        url = rz + path
        resp = http_request(url, method="POST", payload=payload, timeout=args.timeout,
                            verify=args.verify_ssl, cacert=args.cacert)
        data = parse_json(resp["body"]) or {}
        code = str(data.get("status_code", ""))
        step = {"步骤": title, "地址": url, "请求": redact(payload),
                "http_status": resp["http_status"], "error": resp["error"],
                "status_code": code, "message": str(data.get("message", "")),
                "原始响应": resp["body"][:4000]}
        result["步骤"].append(step)
        tag = "OK  " if code == "0000" else "FAIL"
        log(f"[{tag}] {title} —— status_code={code} message={step['message']}"
            + (f" ({resp['error']})" if resp["error"] else ""))
        return data, step

    if not args.ak or not args.sk:
        log("未提供 --ak/--sk，跳过应用令牌相关步骤（这两项只能向对接人要，脚本问不出来）。")
    else:
        data, step = post(args.create_app_token_path, {
            "appKey": args.ak, "secureKey": args.sk,
            "yhsj": int(time.time() * 1000),
        }, "① 应用令牌生成服务（校验 AK/SK 是否正确）")
        app_token = str((data.get("result") or {}).get("appToken", ""))
        step["appToken前12位"] = app_token[:12]
        if app_token:
            log(f"      取得应用令牌（{app_token[:12]}…，长度 {len(app_token)}）")

            data2, step2 = post(args.decode_token_path,
                                {"appTokenId": app_token, "dqxtbs": args.dqxtbs},
                                "② 应用令牌元素查询（核对系统唯一标识 dqxtbs）")
            res2 = data2.get("result") or {}
            step2["结果字段"] = sorted(res2) if isinstance(res2, dict) else res2
            if isinstance(res2, dict):
                ut = res2.get("userToken") or {}
                step2["系统唯一标识"] = {"appId": res2.get("appId"), "orgCode": ut.get("orgCode") if isinstance(ut, dict) else None}
                log(f"      appId={res2.get('appId')} 到期={res2.get('expireAt')}")

            post(args.verify_app_token_path, {"appTokenId": app_token, "dqxtbs": args.dqxtbs},
                 "③ 应用令牌校验服务")

            # ④ 关键：证明我方 SM3 callerSign 与平台一致
            payload = {
                "tokenId": app_token, "type": "app", "action": "renew",
                "callerId": args.dqxtbs or args.sys_id or "zjfy-recon",
                "callerTimestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "callerNounce": os.urandom(16).hex(),
            }
            sign = build_renew_sign(payload)
            payload["callerSign"] = sign
            payload["dqxtbs"] = args.dqxtbs
            data4, step4 = post(args.renew_token_path, payload,
                                "④ 令牌续期注销服务（SM3 callerSign 自证）")
            step4["callerSign"] = sign
            code4 = str(data4.get("status_code", ""))
            if code4 in ("0000", "1004", "1005"):
                step4["判定"] = "✅ SM3 签名被平台接受（签名算法与拼接顺序与规范一致）"
                log("      判定：SM3 签名被平台接受 —— 我方 callerSign 实现与规范一致")
            elif code4:
                step4["判定"] = ("⚠️ 签名可能不一致或令牌不可续期；若返回的是参数类错误码，"
                                 "优先核对 key 升序拼接与 dqxtbs 是否排除")
                log(f"      判定：返回 {code4}，需对照规范核对签名拼接（key 升序、去除 callerSign/dqxtbs）")
            else:
                step4["判定"] = "未取得 status_code，无法判定"

    result["小结"] = build_token_summary(result)
    jpath = os.path.join(outdir, f"token-{stamp()}.json")
    write_json(jpath, result)
    log(f"\n{result['小结']}\n已写出：{jpath}")
    return 0


def redact(payload: dict) -> dict:
    """落盘时把密钥类字段遮蔽，避免凭据被顺手带出"""
    out = {}
    for k, v in payload.items():
        if k.lower() in ("securekey", "sk", "appsecret", "password", "callersign"):
            out[k] = _mask(str(v), 4)
        else:
            out[k] = v
    return out


def build_token_summary(result: dict) -> str:
    ok = [s for s in result["步骤"] if s.get("status_code") == "0000"]
    bad = [s for s in result["步骤"] if s.get("status_code") and s["status_code"] != "0000"]
    lines = [f"小结：{len(ok)} 步成功，{len(bad)} 步非 0000。"]
    for s in bad:
        lines.append(f"  - {s['步骤']}：status_code={s['status_code']} {s['message']}")
    sign_step = next((s for s in result["步骤"] if "callerSign" in s), None)
    if sign_step:
        lines.append("  - " + sign_step.get("判定", ""))
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 模式四：auditstats —— 从本地审计台账统计实际认证因子
# --------------------------------------------------------------------------- #
def mode_auditstats(args) -> int:
    import sqlite3
    outdir = ensure_outdir(args.out)
    db = args.db
    if not os.path.exists(db):
        log(f"未找到审计库 {db}。用 --db 指定（默认 server/data/app.db）。")
        log("提示：这是**我们自己的台账**，只能证明流经本系统的登录；全域分布需平台侧数据。")
        return 2
    log(f"=== 本地审计台账统计（只读打开 {db}）===")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        out = {"生成时间": datetime.now().isoformat(timespec="seconds"), "库": db}

        cur.execute("SELECT operate_name, COUNT(*) FROM audit_logs WHERE operate_type=0 "
                    "GROUP BY operate_name ORDER BY COUNT(*) DESC")
        rows = cur.fetchall()
        out["登录认证因子分布"] = [{"认证因子": r[0] or "（空）", "次数": r[1]} for r in rows]
        log("\n-- 登录认证因子分布（operate_type=0）--")
        if not rows:
            log("  （无登录记录）")
        for r in rows:
            log(f"  {r[0] or '（空）':<24} {r[1]:>6}")

        cur.execute("SELECT COUNT(*), SUM(operate_result='0') FROM audit_logs WHERE operate_type=0")
        total, fail = cur.fetchone()
        out["登录总数"] = total or 0
        out["登录失败数"] = fail or 0
        log(f"\n  登录总数 {out['登录总数']}，其中失败 {out['登录失败数']}")

        cur.execute("SELECT status, COUNT(*) FROM audit_logs GROUP BY status")
        out["上报状态分布"] = {r[0]: r[1] for r in cur.fetchall()}
        log(f"\n-- 审计上报状态分布 --\n  {out['上报状态分布']}")

        cur.execute("SELECT result, status_code, COUNT(*) FROM audit_send GROUP BY result, status_code "
                    "ORDER BY COUNT(*) DESC LIMIT 20")
        out["上报批次结果"] = [{"result": r[0], "status_code": r[1], "批次数": r[2]} for r in cur.fetchall()]
        log(f"\n-- 上报批次结果 top20 --")
        for r in out["上报批次结果"]:
            log(f"  result={r['result']} status_code={r['status_code']} 批次数={r['批次数']}")

        cur.execute("SELECT DISTINCT organization_id FROM audit_logs WHERE organization_id<>'' LIMIT 20")
        out["机构代码样本"] = [r[0] for r in cur.fetchall()]
        if out["机构代码样本"]:
            log(f"\n-- 机构代码样本（核对 12 位口径）--\n  {out['机构代码样本']}")

        cur.execute("SELECT DISTINCT terminal_id FROM audit_logs WHERE terminal_id<>'' LIMIT 20")
        out["真实源IP样本"] = [r[0] for r in cur.fetchall()]
        if out["真实源IP样本"]:
            log(f"\n-- 真实源 IP（XFF 首跳）样本 --\n  {out['真实源IP样本']}")
    finally:
        con.close()

    jpath = os.path.join(outdir, f"auditstats-{stamp()}.json")
    write_json(jpath, out)
    log(f"\n已写出：{jpath}")
    log("注意：本项只反映**流经本系统的登录**；『谁在用电子证书』的全域分布需向平台侧（统一认证/警综）索取。")
    return 0


# --------------------------------------------------------------------------- #
# 模式五：report —— 回调 JSONL 汇总成 Markdown
# --------------------------------------------------------------------------- #
def mode_report(args) -> int:
    outdir = ensure_outdir(args.out)
    files = sorted(glob.glob(os.path.join(outdir, "callbacks-*.jsonl")))
    if not files:
        log(f"{outdir} 下没有 callbacks-*.jsonl，先跑 serve 抓回调。")
        return 2
    recs = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        recs.append(json.loads(line))
                    except Exception:  # noqa: BLE001
                        pass
    if not recs:
        log("回调文件为空。")
        return 2

    # 只有"带令牌"或"带参数"的请求才是平台回调；GET / 之类的健康检查/探测单独列出，避免污染统计口径
    def is_callback(r: dict) -> bool:
        return bool(r.get("收到用户令牌") or r.get("收到应用令牌")
                    or r.get("query参数名") or r.get("body参数名"))

    samples = [r for r in recs if is_callback(r)]
    others = [r for r in recs if not is_callback(r)]
    if not samples:
        log(f"共记录 {len(recs)} 条请求，但没有一条带令牌或参数——多半还没抓到真实回调。")
        log("请确认上架时的『认证URL』已指向本服务，并从浙警智治终端点开应用。")
        return 2

    mask = not args.no_mask
    methods, paths, param_names, header_names = {}, {}, {}, {}
    transports, factors, sfzh_shapes, dm_lengths, xff_samples, missing_fields = {}, {}, {}, {}, [], {}
    glu_ok = glu_fail = 0
    for r in samples:
        methods[r.get("方法", "")] = methods.get(r.get("方法", ""), 0) + 1
        paths[r.get("路径", "")] = paths.get(r.get("路径", ""), 0) + 1
        for k in r.get("query参数名", []) + r.get("body参数名", []):
            param_names[k] = param_names.get(k, 0) + 1
        for k in r.get("请求头名", []):
            header_names[k] = header_names.get(k, 0) + 1
        t = r.get("令牌传输方式", "")
        transports[t] = transports.get(t, 0) + 1
        for k, v in (r.get("认证因子候选") or {}).items():
            factors[f"{k}={v}"] = factors.get(f"{k}={v}", 0) + 1
        glu = r.get("getLoginUser") or {}
        if glu.get("status_code"):
            glu_ok += 1
            s = glu.get("SFZH形态", "")
            sfzh_shapes[s] = sfzh_shapes.get(s, 0) + 1
            dl = glu.get("DM长度", 0)
            dm_lengths[dl] = dm_lengths.get(dl, 0) + 1
            for f, present in (glu.get("字段存在情况") or {}).items():
                if not present:
                    missing_fields[f] = missing_fields.get(f, 0) + 1
            if len(xff_samples) < 10:
                xff_samples.append(str(glu.get("结果", {}).get("IP", "") or r.get("X-Forwarded-For", "")))
        elif glu:
            glu_fail += 1

    L = ["# 浙警智治 · 认证回调原始报文观测报告", "",
         f"> 生成时间：{datetime.now().isoformat(timespec='seconds')}",
         f"> 回调样本数：**{len(samples)}** 条（来自 {len(files)} 个 JSONL 文件；另有 {len(others)} 条无令牌无参数请求已排除）",
         f"> 时间范围：{samples[0].get('时间', '?')} ~ {samples[-1].get('时间', '?')}",
         f"> 脱敏：{'是（--no-mask 可关）' if mask else '否'}", ""]

    L += ["## 1. 令牌是怎么送过来的（对应规范：Header 优先，取不到回退参数）", "",
          "| 令牌传输方式 | 次数 |", "| --- | --- |"]
    for k, v in sorted(transports.items(), key=lambda x: -x[1]):
        L.append(f"| {k} | {v} |")
    hdr_ok = any("header" == k for k in transports)
    L += ["", ("**判定：收到过头传令牌 —— 前置代理没有吞 `RZZX-*` 头，规范首选路径可用。**"
               if hdr_ok else
               "**判定：未观察到 header 传令牌。若联调时报 1001/1003（令牌不存在），"
               "优先怀疑前置代理/网关吞了 `RZZX-USERTOKEN`/`RZZX-APPTOKEN` 头。**"), ""]

    L += ["## 2. 回调实际出现了哪些参数名（直接钉死动态秘钥字段口径）", "",
          "| 参数名 | 出现次数 |", "| --- | --- |"]
    for k, v in sorted(param_names.items(), key=lambda x: -x[1]):
        L.append(f"| `{k}` | {v} |")
    if not param_names:
        L.append("| （无 query/body 参数） | - |")

    L += ["", "## 3. 认证因子候选（审计 `operateName` 必须写实际因子）", ""]
    if factors:
        L += ["| 候选（来源.参数=值） | 次数 |", "| --- | --- |"]
        for k, v in sorted(factors.items(), key=lambda x: -x[1]):
            L.append(f"| `{k}` | {v} |")
        L += ["", "> 审计规范：登录类 `operateCondition` 形如 `通过[认证因子1||认证因子2]方式登录了系统。`，",
              "> 因子含且不限于数字证书、账号口令、短信验证、人脸认证。请按上表实际值填写。"]
    else:
        L += ["未在回调参数中识别到认证因子字段 —— 说明**平台未把认证方式下发给应用**，",
              "`operateName` 只能按平台约定/责任民警确认后填写（不要把「数字证书」当默认值硬编码）。"]

    L += ["", "## 4. getLoginUser 返回字段核对（文档 5.4 声明的 11 个字段）", ""]
    L += [f"- 调用成功（有 status_code）：{glu_ok} 次；调用异常/失败：{glu_fail} 次"]
    if glu_ok == 0:
        L += ["", "**本批没有一次成功的 `getLoginUser` 调用，因此无法核对字段口径。**",
              "先看 JSONL 里 `getLoginUser.error` / `http_status` 定位原因（地址、策略、证书校验、超时），重抓后再看本节。"]
    elif missing_fields:
        L += ["", f"**文档声明但实际缺失的字段（{glu_ok} 次成功调用中）：**", ""]
        for k, v in sorted(missing_fields.items(), key=lambda x: -x[1]):
            L.append(f"- `{k}`：{v} 次未出现")
    else:
        L += ["", f"{glu_ok} 次成功调用中，文档声明的 11 个字段均出现。"]
    if sfzh_shapes:
        L += ["", "### `SFZH` 实际形态（决定审计 `userId` 与本地认人键）", "",
              "| 形态 | 次数 |", "| --- | --- |"]
        for k, v in sorted(sfzh_shapes.items(), key=lambda x: -x[1]):
            L.append(f"| {k} | {v} |")
        if any("32位十六进制" in k or "40位" in k for k in sfzh_shapes):
            L += ["", "> ⚠️ 出现非 18 位身份证号形态：文档 `getDetailedUser` 示例中 `IDCARD` 即为 32 位证书主体标识，",
                  "> 且存在 `ISZSSFZ`（是否正式身份证）字段。此时审计 `userId` 写证书主体标识是**合规的**",
                  "> （规范允许「公民身份号码或数字证书主体标识符」），但本地 `users.phone` 唯一列的取值口径要相应确认。"]
    if dm_lengths:
        L += ["", f"### `DM`（机构代码）长度分布：{dm_lengths}",
              "", "> 对应最大风险点：12 位机构码 → 6 位行政区划码映射。用 `GET /api/auth/zhijing/mapping-health` 核对落点。"]
    if xff_samples:
        L += ["", "### 真实源 IP / XFF 样本（审计 `terminalId` 取首跳）", ""]
        for s in xff_samples[:10]:
            L.append(f"- `{_mask(s, 3) if mask else s}`")

    L += ["", "## 5. 请求方法 / 路径", "",
          f"- 方法：{methods}", f"- 路径：{paths}", ""]
    L += ["## 6. 出现过的请求头（前 30）", ""]
    for k, v in sorted(header_names.items(), key=lambda x: -x[1])[:30]:
        L.append(f"- `{k}`：{v} 次")

    if others:
        L += ["", "## 7. 已排除的非回调请求（无令牌、无参数）", "",
              "这些多半是健康检查/浏览器预取，不计入上面的统计口径：", ""]
        opaths = {}
        for r in others:
            opaths[f"{r.get('方法', '')} {r.get('路径', '')}"] = opaths.get(f"{r.get('方法', '')} {r.get('路径', '')}", 0) + 1
        for k, v in sorted(opaths.items(), key=lambda x: -x[1])[:20]:
            L.append(f"- `{k}`：{v} 次")

    L += ["", "---", "",
          "**本报告由真实回调报文汇总，未对平台做任何主动探测。**",
          "报告中的令牌值属凭据材料，请留在内网按敏感材料处置。", ""]

    p = os.path.join(outdir, f"callback-report-{stamp()}.md")
    write_text(p, "\n".join(L))
    log(f"已写出：{p}")
    log(f"回调样本 {len(samples)} 条（已排除 {len(others)} 条非回调请求）；令牌传输方式：{transports}")
    return 0


# --------------------------------------------------------------------------- #
# all
# --------------------------------------------------------------------------- #
def mode_all(args) -> int:
    log("=== all：环境体检 + AK/SK 签名自证 + 本地台账统计（不含 serve）===\n")
    rc = mode_check(args)
    log("\n" + "=" * 78 + "\n")
    rc2 = mode_token(args)
    log("\n" + "=" * 78 + "\n")
    rc3 = mode_auditstats(args)
    log("\n提示：最有价值的『回调原始报文抓取』需常驻，请另起一个终端跑：")
    log(f"  python {os.path.basename(__file__)} serve --port 8600 --out {args.out}")
    return max(rc, rc2, 0 if rc3 == 2 else rc3)


# --------------------------------------------------------------------------- #
# 工具函数与 CLI
# --------------------------------------------------------------------------- #
def ensure_outdir(path: str) -> str:
    path = path or "./recon-out"
    os.makedirs(path, exist_ok=True)
    return path


def write_json(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zhijing_recon.py",
        description="浙警智治内网对接信息采集工具（单文件、纯标准库、不扫描）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("用法示例")[-1] if "用法示例" in __doc__ else "")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--out", default="./recon-out", help="产物目录（默认 ./recon-out）")
        sp.add_argument("--timeout", type=int, default=10, help="单次超时秒（默认 10）")
        sp.add_argument("--verify-ssl", action="store_true",
                        help="校验服务端证书（默认关，与 ZHIJING_VERIFY_SSL 默认一致；"
                             "拿到私有 CA 后建议开启）")
        sp.add_argument("--cacert", default="", help="私有 CA 证书路径（配合 --verify-ssl）")
        sp.add_argument("--rz-url", default="https://lxrdl.gat.zj:5010/jiRMS_RzSer",
                        help="认证服务 SerRzIP 基地址")
        sp.add_argument("--dqxtbs", default="", help="当前系统标识（系统标准码/requestId）")
        sp.add_argument("--ak", default="", help="AppKey")
        sp.add_argument("--sk", default="", help="SecretKey")
        sp.add_argument("--sys-id", default="", help="系统标准码")
        sp.add_argument("--db", default="server/data/app.db", help="审计库路径（默认 server/data/app.db）")

    sp = sub.add_parser("check", help="连通性 + TLS 证书链 + 时钟偏差")
    common(sp)
    sp.add_argument("--url", action="append", default=[], help="自定义地址（可重复）；给了就不测文档地址")
    sp.add_argument("--also-doc", action="store_true", help="给了 --url 时也一并测文档地址")
    sp.set_defaults(func=mode_check)

    sp = sub.add_parser("serve", help="被动回调观测器（最高价值）")
    common(sp)
    sp.add_argument("--bind", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    sp.add_argument("--port", type=int, default=8600, help="监听端口（默认 8600）")
    sp.add_argument("--call-auth", action="store_true", default=True,
                    help="收到用户令牌时代调 getLoginUser 落原始 JSON（默认开）")
    sp.add_argument("--no-auth-call", dest="call_auth", action="store_false",
                    help="关闭代调 getLoginUser")
    sp.add_argument("--login-user-path", default=DEFAULT_PATHS["login_user"],
                    help="用户基本信息获取服务路径")
    sp.set_defaults(func=mode_serve)

    sp = sub.add_parser("token", help="AK/SK 与 SM3 签名自证")
    common(sp)
    sp.add_argument("--appid", default="", help="应用标识 APPID（应用级鉴权用）")
    sp.add_argument("--create-app-token-path", default=DEFAULT_PATHS["create_app_token"])
    sp.add_argument("--decode-token-path", default=DEFAULT_PATHS["decode_token"])
    sp.add_argument("--verify-app-token-path", default=DEFAULT_PATHS["verify_app_token"])
    sp.add_argument("--renew-token-path", default=DEFAULT_PATHS["renew_token"])
    sp.set_defaults(func=mode_token)

    sp = sub.add_parser("auditstats", help="本地审计台账：认证因子分布")
    common(sp)
    sp.set_defaults(func=mode_auditstats)

    sp = sub.add_parser("report", help="回调 JSONL 汇总成 Markdown")
    common(sp)
    sp.add_argument("--no-mask", action="store_true", help="报告不脱敏（默认脱敏）")
    sp.set_defaults(func=mode_report)

    sp = sub.add_parser("all", help="check + token + auditstats")
    common(sp)
    sp.add_argument("--url", action="append", default=[])
    sp.add_argument("--also-doc", action="store_true")
    sp.add_argument("--appid", default="")
    sp.add_argument("--create-app-token-path", default=DEFAULT_PATHS["create_app_token"])
    sp.add_argument("--decode-token-path", default=DEFAULT_PATHS["decode_token"])
    sp.add_argument("--verify-app-token-path", default=DEFAULT_PATHS["verify_app_token"])
    sp.add_argument("--renew-token-path", default=DEFAULT_PATHS["renew_token"])
    sp.set_defaults(func=mode_all, call_auth=False, bind="", port=0,
                    login_user_path=DEFAULT_PATHS["login_user"])
    return p


def main(argv=None) -> int:
    # Windows 控制台默认非 UTF-8，中文会乱码；尽量切到 UTF-8（失败不影响功能）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

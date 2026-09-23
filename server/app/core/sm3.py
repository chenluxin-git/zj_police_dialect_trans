"""国密 SM3 摘要（GB/T 32905-2016）纯 Python 实现

用途：
- 审计服务 checkSum（`sysId&sendId&logType&subLogType&logContents&appSecret` 的 SM3）
- 令牌续期注销 callerSign、零信任联动服务 sign 的 SM3
- 审批/规范要求"开发同步使用国产密码算法"，避免为单个摘要引入第三方依赖

实现要点：消息填充（0x80 + 补零 + 64 位比特长度）→ 512 位分组 → 64 步压缩，
P0/P1 置换与 Tj 常量按标准取值。自检向量见 tests/test_sm3.py。
"""
from __future__ import annotations

# 初始向量 IV
_IV = (
    0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
    0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E,
)

_MASK32 = 0xFFFFFFFF


def _rotl(x: int, n: int) -> int:
    """32 位循环左移"""
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


def _cf(v: tuple[int, ...], block: bytes) -> tuple[int, ...]:
    """压缩函数 CF：一组 64 字节消息 + 8 字状态 → 新状态"""
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


def sm3_digest(data: bytes) -> bytes:
    """返回 32 字节摘要"""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("sm3_digest 只接受 bytes")
    msg = bytes(data)
    bit_len = len(msg) * 8
    # 填充：0x80，补 0 至 56 (mod 64)，末尾 8 字节大端比特长度
    padded = msg + b"\x80"
    padded += b"\x00" * ((56 - len(padded) % 64) % 64)
    padded += bit_len.to_bytes(8, "big")

    v = _IV
    for i in range(0, len(padded), 64):
        v = _cf(v, padded[i:i + 64])
    return b"".join(x.to_bytes(4, "big") for x in v)


def sm3_hex(data: bytes | str) -> str:
    """返回 64 位小写十六进制摘要；str 入参按 UTF-8 编码（与 Java digestHex 行为一致）"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return sm3_digest(data).hex()

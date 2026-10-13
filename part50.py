# part50.py (v2.37.0) - nền cho Holder Graph: lọc ví hạ tầng, fingerprint, snapshot log
# Chỉ dùng thư viện chuẩn. Mọi tên có tiền tố hg_ để không đụng các part cũ.
# Nếu chưa gọi hg_bind() thì mọi hàm ghi đều im lặng không làm gì (không làm sập API).
import hashlib
import json
import math
import time

HG_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_HG_P = 2**255 - 19
_HG_D = (-121665 * pow(121666, _HG_P - 2, _HG_P)) % _HG_P

# Ví hệ thống chắc chắn không phải "cá voi"
HG_INFRA = {
    "11111111111111111111111111111111",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
    "1nc1nerator11111111111111111111111111111111",
}
# Thêm tay: ví sàn, ví treasury... (ví thường nằm TRÊN đường cong nên không tự lọc được)
HG_EXTRA_EXCLUDE = set()

HG_FP_DAYS = 30
HG_FEAT_LOG_MAX = 5000      # giữ 5000 snapshot gần nhất cho việc huấn luyện offline
HG_SNAP_GATE_S = 6 * 3600   # mỗi mint chỉ log 1 snapshot / 6h

_hg_cmd = None
_hg_pipe = None


def hg_bind(cmd, pipe=None):
    """cmd: async (*args) -> kết quả 1 lệnh Redis.
    pipe: async (list[list]) -> list kết quả (tuỳ chọn, nên có để tiết kiệm lệnh/độ trễ)."""
    global _hg_cmd, _hg_pipe
    _hg_cmd, _hg_pipe = cmd, pipe


async def hg_run(cmds):
    if not cmds or _hg_cmd is None:
        return []
    if _hg_pipe is not None:
        return await _hg_pipe(cmds)
    return [await _hg_cmd(*c) for c in cmds]


async def hg_gate(key, seconds):
    """True nếu đây là lần đầu trong cửa sổ thời gian (SET NX EX)."""
    if _hg_cmd is None:
        return False
    return (await _hg_cmd("SET", key, "1", "NX", "EX", int(seconds))) is not None


def _hg_b58d(s):
    n = 0
    for ch in s:
        i = HG_B58.find(ch)
        if i < 0:
            return None
        n = n * 58 + i
    pad = len(s) - len(s.lstrip("1"))
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\x00" * pad + body


def hg_on_curve(addr):
    """True = ví thường (ed25519), False = PDA (bonding curve, vault LP, authority...),
    None = địa chỉ không hợp lệ."""
    b = _hg_b58d(addr) if isinstance(addr, str) else None
    if b is None or len(b) != 32:
        return None
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= _HG_P:
        return False
    x2 = (y * y - 1) * pow(_HG_D * y * y + 1, _HG_P - 2, _HG_P) % _HG_P
    return x2 == 0 or pow(x2, (_HG_P - 1) // 2, _HG_P) == 1


def hg_is_infra(addr):
    """Ví hạ tầng: danh sách cố định, danh sách thêm tay, hoặc PDA (off-curve).
    Lưu ý: ví multisig kiểu PDA cũng bị loại, chấp nhận vì không theo dõi hành vi được."""
    if addr in HG_INFRA or addr in HG_EXTRA_EXCLUDE:
        return True
    return hg_on_curve(addr) is not True


def hg_owners(raw):
    """Chuẩn hoá top owners -> list[(addr, pct|None)] đã lọc hạ tầng, bỏ trùng, giữ thứ tự.
    raw: list str | list dict {owner|address|wallet, pct|percent|share} | list (addr, pct)."""
    out, seen = [], set()
    for it in raw or []:
        if isinstance(it, dict):
            a = it.get("owner") or it.get("address") or it.get("wallet")
            p = it.get("pct", it.get("percent", it.get("share")))
        elif isinstance(it, (list, tuple)) and it:
            a, p = it[0], (it[1] if len(it) > 1 else None)
        else:
            a, p = it, None
        if not isinstance(a, str) or a in seen or hg_is_infra(a):
            continue
        seen.add(a)
        try:
            p = float(p) if p is not None else None
        except (TypeError, ValueError):
            p = None
        if p is not None and not math.isfinite(p):
            p = None
        out.append((a, p))
    return out


def hg_fingerprint(raw, top=5, min_n=3):
    """Hash 12 ký tự của top-N holder thật (đã lọc hạ tầng, sắp xếp). None nếu quá ít holder."""
    own = [a for a, _ in hg_owners(raw)][:top]
    if len(own) < min_n:
        return None
    return hashlib.sha256("|".join(sorted(own)).encode()).hexdigest()[:12]


def hg_jaccard(a, b):
    a, b = set(a), set(b)
    u = len(a | b)
    return len(a & b) / u if u else 0.0


def hg_flatten(d, prefix="", out=None, depth=0):
    """Làm phẳng dict tín hiệu thành {tên: số}. Bool -> 0/1, bỏ chuỗi/None/NaN. Dùng làm feature."""
    out = {} if out is None else out
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, bool):
            out[key] = int(v)
        elif isinstance(v, (int, float)):
            if math.isfinite(v):
                out[key] = round(float(v), 6)
        elif isinstance(v, dict) and depth < 3:
            hg_flatten(v, key + ".", out, depth + 1)
    return out


async def hg_record_snapshot(mint, verdict, risk_score, flags, features, owners,
                             deployer=None, ts=None):
    """Ghi 1 snapshot (feature + fingerprint + deployer) cho huấn luyện và cluster.
    Gọi ngay sau khi có verdict. Trả về fingerprint (hoặc None)."""
    if _hg_cmd is None:
        return None
    if not await hg_gate(f"hg:snap:{mint}", HG_SNAP_GATE_S):
        return None
    ts = int(ts or time.time())
    own = [a for a, _ in hg_owners(owners)][:5]
    fp = hg_fingerprint(owners)
    row = {"m": mint, "t": ts, "v": verdict, "r": risk_score, "f": sorted(flags or []),
           "x": features or {}, "fp": fp, "o": own, "d": deployer}
    ttl = HG_FP_DAYS * 86400
    cmds = [["LPUSH", "hg:feat", json.dumps(row, separators=(",", ":"), default=str)],
            ["LTRIM", "hg:feat", 0, HG_FEAT_LOG_MAX - 1]]
    if fp:
        cmds += [["SADD", f"hg:fp:{fp}", mint], ["EXPIRE", f"hg:fp:{fp}", ttl]]
    if deployer:
        cmds += [["SADD", f"hg:dep:{deployer}", mint], ["EXPIRE", f"hg:dep:{deployer}", ttl]]
    await hg_run(cmds)
    return fp

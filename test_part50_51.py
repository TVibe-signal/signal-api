import asyncio
import hashlib
import json
import os
import random

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

HERE = os.path.dirname(os.path.abspath(__file__))
NS = {}
for part in ("part50.py", "part51.py"):          # nạp chung namespace như loader
    exec(compile(open(os.path.join(HERE, part), encoding="utf-8").read(), part, "exec"), NS)

B58 = NS["HG_B58"]


def b58e(b):
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\x00"))) + s


# --- oracle độc lập: recover_x theo RFC 8032 (căn bậc hai qua mũ (p+3)/8) ---
P = 2**255 - 19
D = (-121665 * pow(121666, P - 2, P)) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def oracle_on_curve(b):
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= P:
        return False
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P) % P
    if x2 == 0:
        return True
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    return (x * x - x2) % P == 0


def real_wallet():
    pub = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return b58e(pub)


def find_pda(seed, program_id):
    pid = NS["_hg_b58d"](program_id)
    for bump in range(255, -1, -1):
        h = hashlib.sha256(seed + bytes([bump]) + pid + b"ProgramDerivedAddress").digest()
        if not oracle_on_curve(h):
            return b58e(h)


def run(c):
    return asyncio.run(c)


class FakeRedis:
    def __init__(self):
        self.d, self.ttl, self.calls = {}, {}, 0

    @staticmethod
    def _rng(n, a, b):
        a = a + n if a < 0 else a
        b = b + n if b < 0 else b
        return max(a, 0), min(b, n - 1)

    async def cmd(self, op, key, *a):
        self.calls += 1
        d = self.d
        if op == "SET":
            if "NX" in a and key in d:
                return None
            d[key] = a[0]
            return "OK"
        if op in ("LPUSH", "RPUSH"):
            l = d.setdefault(key, [])
            l.insert(0, a[0]) if op == "LPUSH" else l.append(a[0])
            return len(l)
        if op == "LTRIM":
            l = d.get(key, [])
            s, e = self._rng(len(l), a[0], a[1])
            d[key] = l[s:e + 1]
            return "OK"
        if op == "LRANGE":
            l = d.get(key, [])
            s, e = self._rng(len(l), a[0], a[1])
            return l[s:e + 1]
        if op == "SADD":
            d.setdefault(key, set()).add(a[0])
            return 1
        if op == "SCARD":
            return len(d.get(key, ()))
        if op == "HSETNX":
            h = d.setdefault(key, {})
            if a[0] in h:
                return 0
            h[a[0]] = str(a[1])
            return 1
        if op == "HSET":
            d.setdefault(key, {})[a[0]] = str(a[1])
            return 1
        if op == "HINCRBY":
            h = d.setdefault(key, {})
            h[a[0]] = str(int(h.get(a[0], 0)) + a[1])
            return int(h[a[0]])
        if op == "HGETALL":
            return [x for kv in d.get(key, {}).items() for x in kv]
        if op == "INCR":
            d[key] = int(d.get(key, 0)) + 1
            return d[key]
        if op == "EXPIRE":
            self.ttl[key] = a[0]
            return 1
        raise NotImplementedError(op)

    async def pipe(self, cmds):
        return [await self.cmd(*c) for c in cmds]


def fresh(use_pipe=True):
    r = FakeRedis()
    NS["hg_bind"](r.cmd, r.pipe if use_pipe else None)
    return r


# ------------------------------------------------------------------ tests
def test_on_curve_matches_oracle():
    rnd = random.Random(7)
    for _ in range(400):
        b = bytes(rnd.getrandbits(8) for _ in range(32))
        assert NS["hg_on_curve"](b58e(b)) == oracle_on_curve(b)


def test_real_wallets_and_pda():
    for _ in range(40):
        assert NS["hg_on_curve"](real_wallet()) is True
        assert not NS["hg_is_infra"](real_wallet())
    pda = find_pda(b"bonding-curve", "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
    assert NS["hg_on_curve"](pda) is False and NS["hg_is_infra"](pda)


def test_fixed_and_invalid():
    assert NS["hg_is_infra"]("11111111111111111111111111111111")
    assert NS["hg_is_infra"]("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
    assert NS["hg_on_curve"]("not-base58-0OIl") is None
    assert NS["hg_is_infra"]("short")


def test_owners_normalize():
    w = [real_wallet() for _ in range(3)]
    pda = find_pda(b"x", "11111111111111111111111111111111")
    raw = [{"owner": w[0], "pct": "4.5"}, {"address": pda, "percent": 30}, (w[1], 2),
           w[2], {"owner": w[0], "pct": 1}, {"owner": None}, 5]
    out = NS["hg_owners"](raw)
    assert out == [(w[0], 4.5), (w[1], 2.0), (w[2], None)]


def test_fingerprint():
    w = [real_wallet() for _ in range(6)]
    a = NS["hg_fingerprint"](w[:5])
    assert a and a == NS["hg_fingerprint"](list(reversed(w[:5])))   # thứ tự đầu vào không ảnh hưởng
    assert NS["hg_fingerprint"](w[:2]) is None
    pda = find_pda(b"y", "11111111111111111111111111111111")
    assert NS["hg_fingerprint"]([pda] + w[:5]) == a   # PDA bị lọc, top-5 thật không đổi
    assert NS["hg_fingerprint"](w[1:6]) != a


def test_jaccard_flatten():
    assert NS["hg_jaccard"]("abc", "bcd") == 0.5 and NS["hg_jaccard"]([], []) == 0.0
    f = NS["hg_flatten"]({"a": 1, "b": True, "c": "x", "d": {"e": 2.5, "f": float("nan"), "g": None}})
    assert f == {"a": 1.0, "b": 1, "d.e": 2.5}


def test_classify():
    c = NS["hg_classify"]
    prev = {"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "G": 2.0}
    cur = {"A": 6.0, "B": 2.0, "C": 3.1, "E": 1.5, "G": 2.0}
    got = {(a, act) for a, act, _ in c(prev, cur)}
    assert got == {("A", "accumulates"), ("B", "dumps"), ("E", "entered_top"), ("D", "left_top")}
    got = {(a, act) for a, act, _ in c(prev, cur, price_chg=-25)}
    assert ("A", "absorbs_dip") in got and ("E", "absorbs_dip") in got and ("B", "dumps") in got


def test_record_graph_end_to_end():
    r = fresh()
    w = [real_wallet() for _ in range(5)]
    prev = [{"owner": w[0], "pct": 5}, {"owner": w[1], "pct": 4}, {"owner": w[2], "pct": 3}]
    cur = [{"owner": w[0], "pct": 6}, {"owner": w[1], "pct": 2}, {"owner": w[3], "pct": 1.2}]
    acts = run(NS["hg_record_graph"]("MINT1", cur, prev, price_chg=-20, ts=1000))
    kinds = {(a, k) for a, k, _ in acts}
    assert kinds == {(w[0], "absorbs_dip"), (w[1], "dumps"), (w[3], "absorbs_dip"), (w[2], "left_top")}
    assert run(NS["hg_record_graph"]("MINT1", cur, prev, ts=1001)) == []          # cổng 6h
    p = run(NS["hg_wallet_profile"](w[1]))
    assert p["counts"] == {"dumps": 1, "total": 1} and p["tokens"] == 1
    assert p["first"] == 1000 and p["actions"][0][:2] == ["MINT1", "dumps"]
    # co-hold tính đúng 1 lần cho mint, co-dump chỉ có khi >= 2 ví cùng dump
    assert r.d[f"hg:co:{min(w[0], w[1])}:{max(w[0], w[1])}"] == 1
    assert not any(k.startswith("hg:cd:") for k in r.d)
    assert any(k.startswith("hg:ca:") for k in r.d)     # w0 và w3 cùng mua
    r.d["hg:g:MINT1"] = None
    del r.d["hg:g:MINT1"]
    run(NS["hg_record_graph"]("MINT1", cur, prev, ts=5000))
    assert r.d[f"hg:co:{min(w[0], w[1])}:{max(w[0], w[1])}"] == 1   # không đếm lại cùng mint


def test_actions_capped_and_no_pipe():
    fresh(use_pipe=False)                      # chạy từng lệnh, không pipeline
    w = real_wallet()
    for i in range(210):                       # mỗi mint: 1% -> 5% = accumulates
        run(NS["hg_record_graph"](f"M{i}", [{"owner": w, "pct": 5}], [{"owner": w, "pct": 1}], ts=i))
    p = run(NS["hg_wallet_profile"](w))
    assert len(p["actions"]) == NS["HG_ACTIONS_MAX"]
    assert p["counts"]["accumulates"] == 210 and p["tokens"] == 210


def test_dump_rate():
    assert NS["hg_dump_rate"]({"dumps": 3, "accumulates": 1}) is None
    assert NS["hg_dump_rate"]({"dumps": 4, "accumulates": 1, "absorbs_dip": 1, "left_top": 9}) == 4 / 6


def test_snapshot():
    r = fresh()
    w = [real_wallet() for _ in range(5)]
    fp = run(NS["hg_record_snapshot"]("M1", "avoid", 70, ["brand_new_pair", "dump_risk"],
                                      {"a": 1}, w, deployer="DEP1", ts=42))
    assert fp and f"hg:fp:{fp}" in r.d and "hg:dep:DEP1" in r.d
    row = json.loads(r.d["hg:feat"][0])
    assert row["m"] == "M1" and row["f"] == ["brand_new_pair", "dump_risk"] and row["o"] == w
    assert run(NS["hg_record_snapshot"]("M1", "avoid", 70, [], {}, w)) is None    # cổng 6h
    for i in range(NS["HG_FEAT_LOG_MAX"] + 5):
        r.d["hg:feat"].insert(0, "x")
    run(NS["hg_record_snapshot"]("M2", "ok", 5, [], {}, w))
    assert len(r.d["hg:feat"]) == NS["HG_FEAT_LOG_MAX"]


def test_unbound_is_noop():
    NS["hg_bind"](None, None)
    w = [real_wallet() for _ in range(3)]
    assert run(NS["hg_record_snapshot"]("M", "ok", 1, [], {}, w)) is None
    assert run(NS["hg_record_graph"]("M", [{"owner": w[0], "pct": 1}])) == []
    assert run(NS["hg_wallet_profile"](w[0])) is None


if __name__ == "__main__":
    import sys
    fails = 0
    for name, fn in sorted((k, v) for k, v in globals().items() if k.startswith("test_")):
        try:
            fn()
            print("ok  ", name)
        except Exception as e:                      # noqa
            fails += 1
            print("FAIL", name, type(e).__name__, e)
    sys.exit(1 if fails else 0)

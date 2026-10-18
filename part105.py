# part105.py - Verifiable verdicts (v2.88.0)
# Every new /omni verdict gets an Ed25519 signature and is chained by hash to the previous one.
# Once a day the head of the chain is written to Solana as a memo from the same address,
# so anyone can check that a verdict existed before its outcome was known.
# Needs: `cryptography` in requirements.txt, Upstash Redis env vars (or ATTEST_SECRET).
# Loader line (after part104, before part7):  ("part105.py", 0, "SKIP"),
import asyncio
import base64
import datetime
import hashlib
import json
import os
import re
import time
import types

VERSION = "2.88.0"
app.version = VERSION
app.openapi_schema = None

_ATT_ON = os.environ.get("ATTEST", "1") != "0"
_ATT_DEDUP_S = int(os.environ.get("ATTEST_DEDUP_S", "600"))
_MEMO_PROGRAM = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_GENESIS = hashlib.sha256(b"tvibe-attest-v1").hexdigest()


def _b58e(b):
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = _B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + s


def _b58d(s):
    n = 0
    for c in s:
        n = n * 58 + _B58.index(c)
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return b"\0" * (len(s) - len(s.lstrip("1"))) + raw


def _canon(o):
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _day(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")


def _err(e):
    # never leak RPC / Redis URLs (they can contain API keys)
    return re.sub(r"https?://\S+", "<url>", str(e))[:200]


S = types.SimpleNamespace(
    loaded=False, ok=False, reason="not loaded yet", persistent=False, next_load=0.0,
    sign=None, pub=b"", pubs="", head=_GENESIS, n=0, day="", day_n=0,
    buf=[], flush_task=None, anchor_task=None, closing={}, anchors={},
    last_err="", last_try=0.0, anchoring=False, cache={},
)
_lock = asyncio.Lock()


# ---------------------------------------------------------------- storage (Upstash REST)
def _redis_cfg():
    for u, t in (("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"),
                 ("KV_REST_API_URL", "KV_REST_API_TOKEN"),
                 ("REDIS_REST_URL", "REDIS_REST_TOKEN")):
        if os.environ.get(u) and os.environ.get(t):
            return os.environ[u].rstrip("/"), os.environ[t]
    return None


async def _redis(cmds):
    cfg = _redis_cfg()
    if not cfg:
        return None
    import httpx
    async with httpx.AsyncClient(timeout=6) as c:
        r = await c.post(cfg[0] + "/pipeline", headers={"Authorization": "Bearer " + cfg[1]}, json=cmds)
        r.raise_for_status()
        return [x.get("result") for x in r.json()]


def _pairs(x):
    if isinstance(x, dict):
        return list(x.items())
    if isinstance(x, list):
        return list(zip(x[::2], x[1::2]))
    return []


# ---------------------------------------------------------------- signer
def _init_signer(seed):
    if len(seed) != 32:
        raise ValueError("signing seed must be 32 bytes")
    try:
        from cryptography.hazmat.primitives import serialization as ser
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        k = Ed25519PrivateKey.from_private_bytes(seed)
        S.sign = k.sign
        S.pub = k.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)
    except ImportError:
        try:
            from nacl.signing import SigningKey
            sk = SigningKey(seed)
            S.sign = lambda m: sk.sign(m).signature
            S.pub = bytes(sk.verify_key)
        except ImportError:
            raise RuntimeError("add 'cryptography' to requirements.txt")
    S.pubs = _b58e(S.pub)


class _Cfg(Exception):
    pass


async def _load():
    if S.loaded or time.time() < S.next_load:
        return
    async with _lock:
        if S.loaded or time.time() < S.next_load:
            return
        try:
            env_secret = os.environ.get("ATTEST_SECRET")
            if env_secret:
                seed = base64.b64decode(env_secret)
            elif _redis_cfg():
                r = await _redis([["GET", "tv:attest:seed"]])
                if not r[0]:
                    await _redis([["SET", "tv:attest:seed", base64.b64encode(os.urandom(32)).decode(), "NX"]])
                    r = await _redis([["GET", "tv:attest:seed"]])
                seed = base64.b64decode(r[0])
            else:
                raise _Cfg("needs Upstash Redis env vars or ATTEST_SECRET")
            _init_signer(seed)
            if _redis_cfg():
                res = await _redis([["GET", "tv:attest:state"], ["HGETALL", "tv:attest:closing"],
                                    ["HGETALL", "tv:attest:anchors"]])
                st = json.loads(res[0]) if res[0] else {}
                S.head = st.get("head", _GENESIS)
                S.n = st.get("n", 0)
                S.day = st.get("day", "")
                S.day_n = st.get("day_n", 0)
                S.closing = {k: json.loads(v) for k, v in _pairs(res[1])}
                S.anchors = {k: json.loads(v) for k, v in _pairs(res[2])}
                S.persistent = True
            S.ok, S.reason, S.loaded = True, "ok", True
        except (_Cfg, RuntimeError, ValueError) as e:
            S.ok, S.reason, S.loaded = False, _err(e), True
        except Exception as e:  # transient (network, Redis): retry soon
            S.ok, S.reason, S.next_load = False, _err(e), time.time() + 30


# ---------------------------------------------------------------- chain
async def _attest(d):
    dec = d.get("decision") or {}
    verdict, mint = dec.get("verdict"), d.get("mint")
    if not verdict or not mint:
        return None
    risk = dec.get("risk_score")
    now = int(time.time())
    hit = S.cache.get(mint)
    if hit and hit[0] == (verdict, risk) and now - hit[2] < _ATT_DEDUP_S:
        return hit[1]
    rec = {"v": 1, "mint": mint, "verdict": verdict, "risk": risk, "ts": now,
           "ver": d.get("version"), "dna": d.get("dna")}
    async with _lock:
        day = _day(now)
        if S.day and day != S.day:
            S.closing[S.day] = {"head": S.head, "n": S.day_n}
            S.buf.append(["HSET", "tv:attest:closing", S.day, _canon(S.closing[S.day])])
            S.day_n = 0
        S.day = day
        prev = S.head
        h = hashlib.sha256((prev + _canon(rec)).encode()).hexdigest()
        sig = S.sign(bytes.fromhex(h)).hex()
        S.head, S.n, S.day_n = h, S.n + 1, S.day_n + 1
        S.buf.append(["RPUSH", "tv:attest:day:" + day, _canon({"rec": rec, "prev": prev, "h": h, "sig": sig})])
        att = {"record": rec, "prev": prev, "hash": h, "sig": sig, "pubkey": S.pubs, "chain_n": S.n}
    if len(S.cache) > 5000:
        S.cache.clear()
    S.cache[mint] = ((verdict, risk), att, now)
    if S.flush_task is None or S.flush_task.done():
        S.flush_task = asyncio.create_task(_flush_later())
    return att


async def _flush():
    async with _lock:
        cmds, S.buf = S.buf, []
        state = _canon({"head": S.head, "n": S.n, "day": S.day, "day_n": S.day_n})
    if not cmds or not _redis_cfg():
        return
    try:
        await _redis(cmds + [["SET", "tv:attest:state", state]])
    except Exception as e:
        S.last_err = "redis: " + _err(e)
        async with _lock:
            S.buf = (cmds + S.buf)[-5000:]


async def _flush_later():
    await asyncio.sleep(2)
    await _flush()
    if S.anchor_task is None or S.anchor_task.done():
        S.anchor_task = asyncio.create_task(_maybe_anchor())


# ---------------------------------------------------------------- Solana memo anchor
def _rpc_url():
    for k in ("ATTEST_RPC_URL", "PRIVATE_RPC", "SOLANA_RPC_URL", "RPC_URL", "HELIUS_RPC_URL"):
        v = os.environ.get(k, "")
        if v.startswith("http"):
            return v
    return "https://api.mainnet-beta.solana.com"


async def _rpc(method, params):
    import httpx
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(_rpc_url(), json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        r.raise_for_status()
        j = r.json()
    if "error" in j:
        raise RuntimeError(str(j["error"])[:160])
    return j["result"]


def _cu16(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _memo_tx(blockhash_b58, memo):
    msg = (bytes([1, 0, 1]) + _cu16(2) + S.pub + _b58d(_MEMO_PROGRAM) + _b58d(blockhash_b58)
           + _cu16(1) + bytes([1]) + _cu16(1) + bytes([0]) + _cu16(len(memo)) + memo)
    return _cu16(1) + S.sign(msg) + msg


async def _maybe_anchor():
    due = sorted(d for d in S.closing if d not in S.anchors)
    if not due or S.anchoring or not S.ok or time.time() - S.last_try < 600:
        return
    S.anchoring, S.last_try = True, time.time()
    try:
        for day in due[:3]:
            info = S.closing[day]
            memo = "tvibe1|%s|%d|%s" % (day, info["n"], info["head"])
            bh = (await _rpc("getLatestBlockhash", [{"commitment": "confirmed"}]))["value"]["blockhash"]
            tx = base64.b64encode(_memo_tx(bh, memo.encode())).decode()
            sig = await _rpc("sendTransaction", [tx, {"encoding": "base64", "preflightCommitment": "confirmed"}])
            S.anchors[day] = {"tx": sig, "head": info["head"], "n": info["n"], "memo": memo, "ts": int(time.time())}
            await _redis([["HSET", "tv:attest:anchors", day, _canon(S.anchors[day])]])
            S.last_err = ""
    except Exception as e:
        S.last_err = "anchor: " + _err(e)
    finally:
        S.anchoring = False


# ---------------------------------------------------------------- middleware: sign /omni
async def _inject(start, body):
    if start.get("status") != 200:
        return body
    hs = {k.lower(): v for k, v in start["headers"]}
    if b"content-encoding" in hs or b"json" not in hs.get(b"content-type", b""):
        return body
    await _load()
    if not S.ok:
        return body
    d = json.loads(body)
    if not isinstance(d, dict) or "attestation" in d:
        return body
    att = await _attest(d)
    if att:
        d["attestation"] = att
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class _AttestMW:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not _ATT_ON or scope["type"] != "http" or scope.get("path") != "/omni" or scope.get("method") != "GET":
            return await self.app(scope, receive, send)
        held, chunks = {}, []

        async def cap(msg):
            if msg["type"] == "http.response.start":
                held["start"] = msg
                return
            if msg["type"] != "http.response.body" or "start" not in held:
                return await send(msg)
            chunks.append(msg.get("body", b""))
            if msg.get("more_body"):
                return
            body, start = b"".join(chunks), held["start"]
            try:
                body = await _inject(start, body)
            except Exception as e:
                S.last_err = "inject: " + _err(e)
            hdrs = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
            hdrs.append((b"content-length", str(len(body)).encode()))
            await send({**start, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, cap)


try:
    app.add_middleware(_AttestMW)
except Exception as _e:
    print("[part105] could not add middleware:", _err(_e))


# ---------------------------------------------------------------- public routes
_HOW = [
    "1. hash = sha256(prev + canonical_json(record)); canonical_json = json.dumps(record, sort_keys=True, separators=(',', ':')).",
    "2. Check the Ed25519 signature over bytes.fromhex(hash) with the pubkey (a Solana address, base58).",
    "3. The head hash at the end of each UTC day is written on Solana as a memo 'tvibe1|date|count|head' from the same address.",
    "Genesis prev = sha256(b'tvibe-attest-v1').hexdigest(). Records of one day: GET /attest/day?date=YYYY-MM-DD.",
]


@app.get("/attest", tags=["trust"])
async def attest_status():
    await _load()
    last = max(S.anchors) if S.anchors else None
    out = {
        "enabled": bool(_ATT_ON and S.ok), "reason": S.reason, "persistent": S.persistent,
        "pubkey": S.pubs or None, "chain_length": S.n, "head": S.head, "today": S.day, "today_count": S.day_n,
        "anchored_days": len(S.anchors),
        "last_anchor": ({"date": last, **S.anchors[last], "solscan": "https://solscan.io/tx/" + S.anchors[last]["tx"]}
                        if last else None),
        "pending_days": sorted(d for d in S.closing if d not in S.anchors),
        "last_error": S.last_err or None, "how_to_verify": _HOW, "version": VERSION,
    }
    if S.pubs and not S.anchors:
        out["note"] = "Daily anchoring needs a little SOL (about 0.01) on the pubkey address to pay network fees."
    return out


@app.get("/attest/day", tags=["trust"])
async def attest_day(date: str):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return {"error": "date must be YYYY-MM-DD"}
    if not _redis_cfg():
        return {"error": "storage not configured"}
    r = await _redis([["LRANGE", "tv:attest:day:" + date, 0, 1999], ["LLEN", "tv:attest:day:" + date],
                      ["HGET", "tv:attest:closing", date], ["HGET", "tv:attest:anchors", date]])
    recs = []
    for line in r[0] or []:
        try:
            recs.append(json.loads(line))
        except Exception:
            pass
    return {"date": date, "count": r[1], "truncated": (r[1] or 0) > len(recs), "records": recs,
            "closing": json.loads(r[2]) if r[2] else None, "anchor": json.loads(r[3]) if r[3] else None}


print("[part105] v%s verifiable verdicts: signed /omni + hash chain + daily Solana memo" % VERSION)

# part120.py - Phase 2: shadow clusters from OUR outcomes only (not live verdict) (v2.95.1, reviewed)
# Association only; it is not proof of coordinated or nested wallets and never changes the live verdict.
# Review fixes vs v2.95.0:
#   - it never recorded anything: at outcome time nobody knows the wallets. Now the top holder / creator is stored
#     once per mint when the verdict is made (1 Redis write per new mint per day) and read back at outcome time.
#   - it wrote the SAME hash as part110 (si:shadow:deployer), double counting deployers. The deployer now goes
#     through part110 (passed as meta["creator"]); this part only writes top-holder and pair stats.
#   - /stats/cluster-shadow was always empty (HGETALL comes back as a flat list, the old code only read dicts).
#   - outcome callback is called once with its real signature (no blind retry on TypeError).
#   - list floors: at least 5 outcomes (default 10), and each row shows lift vs the average, because most
#     tokens fail anyway; the old "100% bad" on a handful of samples says little.
#   - the block on every signal was noise; it is attached only when this wallet has >= 10 judged outcomes.
VERSION = "2.95.1"
app.version = VERSION
app.openapi_schema = None

import inspect
import time
from typing import Any, Dict, List, Optional

CL_KEY = "si:shadow:cluster:v1"      # top1:<wallet>:n/bad and pair:<creator>_<wallet>:n/bad
MAP_KEY = "si:shadow:mintmap:v1"     # mint -> "creator|top1"
CL_TTL = 120 * 86400
_CL_FLOOR = 5
_CL_ATTACH_MIN_N = 10
_MAP_SEEN: Dict[str, float] = {}
_MAP_WRITES = [0]
_CL_CACHE: Dict[str, Any] = {"ts": 0.0, "top1": {}, "pair": {}, "base": None}
_SYS = "11111111111111111111111111111111"


def _w(v) -> Optional[str]:
    return v if isinstance(v, str) and 32 <= len(v) <= 54 and v != _SYS else None


def _creator_of(body: dict) -> Optional[str]:
    for src in (body, body.get("rugcheck"), body.get("security")):
        if isinstance(src, dict):
            for k in ("creator", "deployer", "deployer_wallet", "creator_wallet"):
                if _w(src.get(k)):
                    return src[k]
    return None


def _top1_of(body: dict) -> Optional[str]:
    sec = body.get("security") if isinstance(body.get("security"), dict) else {}
    tops = sec.get("top_holders") or body.get("top_holders") or []
    if isinstance(tops, list) and tops and isinstance(tops[0], dict):
        return _w(tops[0].get("owner") or tops[0].get("address"))
    return None


def _call_prev(cb, client, mint, bad, meta, kwargs):
    try:
        plist = list(inspect.signature(cb).parameters.values())
    except (TypeError, ValueError):
        plist = []
    takes_meta = len(plist) >= 4 or any(p.kind == p.VAR_POSITIONAL for p in plist)
    return cb(client, mint, bad, meta, **kwargs) if takes_meta else cb(client, mint, bad)


async def _remember(client, mint: str, body: dict) -> None:
    """Store creator/top holder for this mint once per day, so the outcome hook can find them later."""
    if not globals().get("PRED_ENABLED") or not client or "redis_pipe" not in globals():
        return
    dep, top1 = _creator_of(body), _top1_of(body)
    now = time.time()
    if not (dep or top1) or now - _MAP_SEEN.get(mint, 0) < 86400:
        return
    if len(_MAP_SEEN) > 5000:
        _MAP_SEEN.clear()
    _MAP_SEEN[mint] = now
    cmds = [["HSET", MAP_KEY, mint, "%s|%s" % (dep or "", top1 or "")]]
    _MAP_WRITES[0] += 1
    if _MAP_WRITES[0] % 50 == 1:
        cmds.append(["EXPIRE", MAP_KEY, CL_TTL])
    await redis_pipe(client, cmds)


_prev_out_120 = globals().get("on_outcome_for_si")


async def on_outcome_for_si(client, mint: str, bad: bool, meta: Optional[dict] = None, **kwargs):
    dep = top1 = None
    try:
        if globals().get("PRED_ENABLED") and client and "redis_pipe" in globals():
            raw = await redis_pipe(client, [["HGET", MAP_KEY, mint]])
            v = (raw or [None])[0]
            if isinstance(v, str) and "|" in v:
                a, b = v.split("|", 1)
                dep, top1 = _w(a), _w(b)
    except Exception as e:
        print("[part120] map lookup:", str(e)[:100])
    meta2 = dict(meta or {})
    if dep and not meta2.get("creator"):
        meta2["creator"] = dep  # part110 records the deployer from this
    if callable(_prev_out_120):
        try:
            await _call_prev(_prev_out_120, client, mint, bad, meta2, kwargs)
        except Exception as e:
            print("[part120] previous outcome hook:", str(e)[:100])
    if top1 and globals().get("PRED_ENABLED") and client and "redis_pipe" in globals():
        try:
            b = 1 if bad else 0
            cmds = [["HINCRBY", CL_KEY, "top1:%s:n" % top1, 1], ["HINCRBY", CL_KEY, "top1:%s:bad" % top1, b]]
            if dep:
                pair = "pair:%s_%s" % (dep[:16], top1[:16])
                cmds += [["HINCRBY", CL_KEY, pair + ":n", 1], ["HINCRBY", CL_KEY, pair + ":bad", b]]
            cmds.append(["EXPIRE", CL_KEY, CL_TTL])
            await redis_pipe(client, cmds)
        except Exception as e:
            print("[part120] cluster outcome:", str(e)[:100])


async def _refresh(client, force: bool = False) -> None:
    now = time.time()
    if not force and now - _CL_CACHE["ts"] < 600:
        return
    _CL_CACHE["ts"] = now  # set first: only one refresh per 10 minutes, even if it fails
    if not globals().get("PRED_ENABLED") or not client or "redis_pipe" not in globals():
        return
    raw = await redis_pipe(client, [["HGETALL", CL_KEY]])
    h = to_dict((raw or [{}])[0] or {}) if "to_dict" in globals() else {}
    top1: Dict[str, Dict[str, int]] = {}
    pair: Dict[str, Dict[str, int]] = {}
    for k, v in (h or {}).items():
        if not isinstance(k, str) or ":" not in k:
            continue
        name, kind = k.rsplit(":", 1)
        if kind not in ("n", "bad"):
            continue
        target = top1 if name.startswith("top1:") else pair if name.startswith("pair:") else None
        if target is None:
            continue
        target.setdefault(name.split(":", 1)[1], {"n": 0, "bad": 0})[kind] = int(float(v or 0))
    tn = sum(c["n"] for c in top1.values())
    tb = sum(c["bad"] for c in top1.values())
    _CL_CACHE.update(top1=top1, pair=pair, base=(100.0 * tb / tn) if tn else None)


def _row(name: str, c: Dict[str, int], kind: str) -> dict:
    n, bad = c["n"], c["bad"]
    rate = 100.0 * bad / n if n else None
    base = _CL_CACHE.get("base")
    return {"id": name, "kind": kind, "n": n, "bad": bad,
            "bad_rate_pct": round(rate, 1) if rate is not None else None,
            "lift_vs_average": round(rate / base, 2) if (rate is not None and base) else None}


_build_prev_120 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_120(client, mint, security, *args, **kwargs)
    try:
        body = res[0] if isinstance(res, tuple) else res
        if isinstance(body, dict):
            await _remember(client, str(mint), body)
            await _refresh(client)
            top1 = _top1_of(body)
            c = _CL_CACHE["top1"].get(top1) if top1 else None
            if c and c["n"] >= _CL_ATTACH_MIN_N:
                body["shadow_cluster"] = {
                    "live_verdict_unchanged": True, **_row(top1, c, "top1_holder"),
                    "average_bad_rate_pct": round(_CL_CACHE["base"], 1) if _CL_CACHE["base"] else None,
                    "note": "Shadow association from our judged outcomes. Not proof of coordination. "
                            "Does not change the live verdict."}
    except Exception as e:
        print("[part120] wrap:", str(e)[:120])
    return res


@app.get("/stats/cluster-shadow", tags=["accuracy"])
async def stats_cluster_shadow(request: Request, min_n: int = 10, limit: int = 30):
    """Shadow only - top-holder and pair association from our judged outcomes."""
    client = request.app.state.client
    min_n = max(_CL_FLOOR, min_n)
    try:
        await _refresh(client)
        rows: List[dict] = []
        for name, c in _CL_CACHE["top1"].items():
            if c["n"] >= min_n:
                rows.append(_row(name, c, "top1_holder"))
        for name, c in _CL_CACHE["pair"].items():
            if c["n"] >= min_n:
                rows.append(_row(name, c, "creator_top1_pair"))
        rows.sort(key=lambda r: (-(r["lift_vs_average"] or 0), -r["n"]))
        rows = rows[: max(1, min(limit, 100))]
    except Exception as e:
        return {"version": VERSION, "shadow": True, "error": str(e)[:160], "rows": []}
    return {"version": VERSION, "shadow": True, "live_verdict_unchanged": True, "min_n": min_n,
            "average_bad_rate_pct": round(_CL_CACHE["base"], 1) if _CL_CACHE["base"] else None,
            "rows": rows,
            "note": "Built only from judged outcomes. Most tokens fail anyway, so compare with the average (lift). "
                    "An association, not proof of intent. Not financial advice."}


print(f"[part120] v{VERSION} cluster shadow -> GET /stats/cluster-shadow (top holder stored per mint)")

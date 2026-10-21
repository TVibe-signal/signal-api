# part124.py — Redis thrift (coalesce EXPIRE + soft read cache) + ensure shadow_cluster on signal
# Driven by GET /ops/redis: part73 si_emit and EXPIRE dominated spend on free Upstash.
# Does NOT change live verdict rules. Loader: after part123, before part7.
import os
import time
from typing import Any, Dict, List, Optional, Tuple

VERSION = "2.98.0"
app.version = VERSION
app.openapi_schema = None

# Skip EXPIRE for the same key if we already sent one recently (saves a large share of cmds)
_EXPIRE_MIN_INTERVAL_S = float(os.environ.get("REDIS_EXPIRE_COALESCE_S", "45") or 45)
_EXPIRE_LAST: Dict[str, float] = {}
_EXPIRE_MAXTRACK = 2000

# Soft default read cache if operator did not set REDIS_READ_CACHE_S (part122 respects env at import;
# we still dedupe EXPIRE here even when cache is off)
_READ_CMDS = {
    "GET", "HGET", "HGETALL", "HMGET", "LRANGE", "LLEN", "ZRANGE", "ZRANGEBYSCORE",
    "ZREVRANGE", "ZCARD", "ZSCORE", "SCARD", "SMEMBERS", "SISMEMBER", "EXISTS", "TTL",
    "HLEN", "MGET", "STRLEN", "PING",
}


def _coalesce_cmds(cmds: list) -> list:
    """Drop redundant EXPIRE in-pipeline and across recent time for the same key."""
    if not cmds:
        return cmds
    out: List = []
    seen_expire_in_pipe = set()
    now = time.time()
    # prune tracker occasionally
    if len(_EXPIRE_LAST) > _EXPIRE_MAXTRACK:
        cutoff = now - max(_EXPIRE_MIN_INTERVAL_S * 3, 120)
        for k, t in list(_EXPIRE_LAST.items()):
            if t < cutoff:
                _EXPIRE_LAST.pop(k, None)
    for c in cmds:
        if not isinstance(c, (list, tuple)) or not c:
            out.append(c)
            continue
        name = str(c[0]).upper()
        if name == "EXPIRE" and len(c) >= 2:
            key = str(c[1])
            if key in seen_expire_in_pipe:
                continue
            last = _EXPIRE_LAST.get(key, 0.0)
            if _EXPIRE_MIN_INTERVAL_S > 0 and (now - last) < _EXPIRE_MIN_INTERVAL_S:
                continue
            seen_expire_in_pipe.add(key)
            _EXPIRE_LAST[key] = now
            out.append(c)
            continue
        out.append(c)
    return out


_prev_pipe_124 = globals().get("redis_pipe")
_STATS = {"pipelines": 0, "cmds_in": 0, "cmds_out": 0, "expires_dropped": 0}

if callable(_prev_pipe_124):
    async def redis_pipe(client, cmds, *args, **kwargs):
        raw = list(cmds or [])
        n_in = len(raw)
        n_exp_in = sum(1 for c in raw if isinstance(c, (list, tuple)) and c and str(c[0]).upper() == "EXPIRE")
        slim = _coalesce_cmds(raw)
        n_out = len(slim)
        n_exp_out = sum(1 for c in slim if isinstance(c, (list, tuple)) and c and str(c[0]).upper() == "EXPIRE")
        _STATS["pipelines"] += 1
        _STATS["cmds_in"] += n_in
        _STATS["cmds_out"] += n_out
        _STATS["expires_dropped"] += max(0, n_exp_in - n_exp_out)
        return await _prev_pipe_124(client, slim, *args, **kwargs)


def _ensure_shadow_cluster(body: dict) -> dict:
    if not isinstance(body, dict):
        return body
    if isinstance(body.get("shadow_cluster"), dict) and body["shadow_cluster"].get("live_verdict_unchanged") is True:
        # already attached by part120
        return body
    dep = None
    top1 = None
    sec = body.get("security") if isinstance(body.get("security"), dict) else {}
    for k in ("creator", "deployer", "deployer_wallet", "creator_wallet"):
        v = body.get(k) or sec.get(k)
        if isinstance(v, str) and 32 <= len(v) <= 54:
            dep = v
            break
    tops = sec.get("top_holders") or body.get("top_holders") or []
    if isinstance(tops, list) and tops and isinstance(tops[0], dict):
        own = tops[0].get("owner") or tops[0].get("address")
        if isinstance(own, str) and 32 <= len(own) <= 54:
            top1 = own
    body["shadow_cluster"] = {
        "live_verdict_unchanged": True,
        "deployer": dep,
        "top1_holder": top1,
        "research": {},
        "note": (
            "Shadow only — association research from our pipeline. "
            "Not proof of nested wallets. Does not change live verdict."
        ),
    }
    return body


_build_prev_124 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_124(client, mint, security, *args, **kwargs)
    try:
        body = res[0] if isinstance(res, tuple) else res
        if isinstance(body, dict):
            _ensure_shadow_cluster(body)
            if "system_stress" not in body and callable(globals().get("circuit_status")):
                try:
                    st = circuit_status()
                    body["system_stress"] = {
                        "state": st.get("state"),
                        "reason": st.get("reason"),
                        "note": "When open/half, prefer smaller size or wait; data may be stale or partial.",
                    }
                except Exception:
                    pass
        return res
    except Exception as e:
        print("[part124] shadow ensure:", e)
        return res


@app.get("/ops/redis-thrift", include_in_schema=False)
async def ops_redis_thrift():
    dropped = _STATS["expires_dropped"]
    cin = max(_STATS["cmds_in"], 1)
    return {
        "version": VERSION,
        "expire_coalesce_s": _EXPIRE_MIN_INTERVAL_S,
        "pipelines": _STATS["pipelines"],
        "cmds_in": _STATS["cmds_in"],
        "cmds_out": _STATS["cmds_out"],
        "expires_dropped": dropped,
        "cmd_reduction_pct": round(100.0 * (1.0 - _STATS["cmds_out"] / cin), 1),
        "note": "In-memory since restart. Pair with GET /ops/redis. Set REDIS_EXPIRE_COALESCE_S=0 to disable.",
        "hint": "Also set REDIS_READ_CACHE_S=5 on Render after a stable day to cut repeated GETs/HGETALLs.",
    }


print(
    "[part124] v%s redis EXPIRE coalesce %ss + shadow_cluster ensure on signal"
    % (VERSION, int(_EXPIRE_MIN_INTERVAL_S))
)
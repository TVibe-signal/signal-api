# part124.py - Redis thrift (coalesce long-TTL EXPIRE) + shadow_cluster ensure on signal (v2.98.1, reviewed)
# Driven by GET /ops/redis: part73 si_emit and EXPIRE dominated spend on the free Upstash plan.
# Does NOT change live verdict rules. Loader: after part123, before part7.
# Review fixes vs v2.98.0:
#   - dropping an EXPIRE shifted the list of results, so a caller reading result[3] could get another command's
#     answer. Dropped commands now get a placeholder (0) so every result keeps its position.
#   - short-TTL keys (rate-limit windows of 60s or less) lost their TTL when an EXPIRE was skipped. Only EXPIRE with
#     a long TTL (>= 300s and >= 4x the coalesce interval) is coalesced; short ones are always sent.
#   - a repeated EXPIRE inside one pipeline is dropped only if it is identical (same key and same TTL).
import os
import time
from typing import Dict, List, Tuple

VERSION = "2.98.1"
app.version = VERSION
app.openapi_schema = None

_EXPIRE_MIN_INTERVAL_S = float(os.environ.get("REDIS_EXPIRE_COALESCE_S", "45") or 45)
_EXPIRE_LAST: Dict[str, Tuple[float, float]] = {}  # key -> (time sent, ttl sent)
_EXPIRE_MAXTRACK = 2000
_STATS = {"pipelines": 0, "cmds_in": 0, "cmds_out": 0, "expires_dropped": 0}


def _is_cmd(c) -> bool:
    return isinstance(c, (list, tuple)) and bool(c)


def _coalesce_cmds(cmds: list) -> Tuple[list, List[int]]:
    """Return (slim_commands, kept_indices)."""
    if not cmds:
        return cmds, []
    now = time.time()
    if len(_EXPIRE_LAST) > _EXPIRE_MAXTRACK:
        cutoff = now - max(_EXPIRE_MIN_INTERVAL_S * 3, 120)
        for k, t in list(_EXPIRE_LAST.items()):
            if t[0] < cutoff:
                _EXPIRE_LAST.pop(k, None)
    out: List = []
    kept: List[int] = []
    in_pipe = set()
    for i, c in enumerate(cmds):
        if _is_cmd(c) and str(c[0]).upper() == "EXPIRE" and len(c) >= 3 and _EXPIRE_MIN_INTERVAL_S > 0:
            key = str(c[1])
            try:
                ttl = float(c[2])
            except (TypeError, ValueError):
                ttl = 0.0
            if ttl >= max(300.0, 4 * _EXPIRE_MIN_INTERVAL_S):
                sig = (key, ttl)
                last_t, last_ttl = _EXPIRE_LAST.get(key, (0.0, -1.0))
                if sig in in_pipe or (last_ttl == ttl and (now - last_t) < _EXPIRE_MIN_INTERVAL_S):
                    continue  # redundant: the same TTL was set a moment ago
                in_pipe.add(sig)
                _EXPIRE_LAST[key] = (now, ttl)
        out.append(c)
        kept.append(i)
    return out, kept


def _restore_positions(res, kept: List[int], n_in: int):
    """Give back one result per ORIGINAL command (dropped ones get 0)."""
    if not isinstance(res, list) or len(res) != len(kept) or len(kept) == n_in:
        return res
    full = [0] * n_in
    for pos, val in zip(kept, res):
        full[pos] = val
    return full


_prev_pipe_124 = globals().get("redis_pipe")

if callable(_prev_pipe_124):
    async def redis_pipe(client, cmds, *args, **kwargs):
        raw = list(cmds or [])
        slim, kept = _coalesce_cmds(raw)
        _STATS["pipelines"] += 1
        _STATS["cmds_in"] += len(raw)
        _STATS["cmds_out"] += len(slim)
        _STATS["expires_dropped"] += len(raw) - len(slim)
        if not slim:
            return [0] * len(raw) if raw else []
        res = await _prev_pipe_124(client, slim, *args, **kwargs)
        return _restore_positions(res, kept, len(raw))


def _ensure_shadow_cluster(body: dict) -> dict:
    if not isinstance(body, dict):
        return body
    if isinstance(body.get("shadow_cluster"), dict) and body["shadow_cluster"].get("live_verdict_unchanged") is True:
        return body  # part120 already attached real stats
    dep = top1 = None
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
        "available": False,
        "live_verdict_unchanged": True,
        "deployer": dep,
        "top1_holder": top1,
        "note": "Shadow only. No judged history for this wallet yet (needs 10+ outcomes). Not proof of nested wallets. "
                "Does not change the live verdict.",
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
                    body["system_stress"] = {"state": st.get("state"), "reason": st.get("reason"),
                                             "note": "When open/half, prefer smaller size or wait; data may be stale or partial."}
                except Exception:
                    pass
        return res
    except Exception as e:
        print("[part124] shadow ensure:", e)
        return res


@app.get("/ops/redis-thrift", include_in_schema=False)
async def ops_redis_thrift():
    cin = max(_STATS["cmds_in"], 1)
    return {
        "version": VERSION,
        "expire_coalesce_s": _EXPIRE_MIN_INTERVAL_S,
        "only_ttl_at_least_s": max(300.0, 4 * _EXPIRE_MIN_INTERVAL_S),
        "pipelines": _STATS["pipelines"],
        "cmds_in": _STATS["cmds_in"],
        "cmds_out": _STATS["cmds_out"],
        "expires_dropped": _STATS["expires_dropped"],
        "cmd_reduction_pct": round(100.0 * (1.0 - _STATS["cmds_out"] / cin), 1),
        "note": "In-memory since restart. Pair with GET /ops/redis. Set REDIS_EXPIRE_COALESCE_S=0 to disable.",
        "hint": "Also set REDIS_READ_CACHE_S=5 on Render after a stable day to cut repeated GETs/HGETALLs.",
    }


print("[part124] v%s redis EXPIRE coalesce %ss (long TTL only, positions kept) + shadow_cluster ensure" % (VERSION, int(_EXPIRE_MIN_INTERVAL_S)))

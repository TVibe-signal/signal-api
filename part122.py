# part122.py - Redis usage meter + optional short read cache (v2.97.0)
# Why: Upstash bills per command and the free quota ran out (about 30K commands a day). Before cutting anything we
# need to know WHICH code spends them. This wraps redis_pipe (and the attestation helper) and counts every command
# by command name and by the part file / function that sent it. Look at GET /ops/redis after a day or two.
# It also has an optional, OFF-by-default read cache: set REDIS_READ_CACHE_S=5 to reuse identical read-only
# pipelines for that many seconds (writes are never cached).
# Counters live in memory only (reset on restart). Optional: set OPS_KEY and call /ops/redis?key=<value>.
# Loader line (after part121, before part7):  ("part122.py", 0, "SKIP"),
import collections
import copy
import json
import os
import sys
import time
import types

from fastapi.responses import JSONResponse

VERSION = "2.97.0"
app.version = VERSION
app.openapi_schema = None

_RM = types.SimpleNamespace(start=time.time(), pipelines=0, commands=0, by_cmd=collections.Counter(),
                            by_caller={}, hours=collections.deque(maxlen=48), cache_hits=0, cache_saved=0)
_RM_CACHE_S = float(os.environ.get("REDIS_READ_CACHE_S", "0") or 0)
_RM_READS = {"GET", "HGET", "HGETALL", "HMGET", "LRANGE", "LLEN", "ZRANGE", "ZRANGEBYSCORE", "ZREVRANGE",
             "ZCARD", "ZSCORE", "SCARD", "SMEMBERS", "SISMEMBER", "EXISTS", "TTL", "HLEN", "MGET", "STRLEN"}
_RM_RCACHE = {}
_RM_MAXCACHE = 400


def _rm_where(depth: int):
    try:
        f = sys._getframe(depth)
    except ValueError:
        return ["?"]
    out = []
    for _ in range(3):
        if f is None:
            break
        out.append("%s:%s" % (os.path.basename(f.f_code.co_filename), f.f_code.co_name))
        f = f.f_back
    return out


def _rm_note(cmds, where):
    try:
        n = len(cmds)
        _RM.pipelines += 1
        _RM.commands += n
        hour = int(time.time() // 3600)
        if _RM.hours and _RM.hours[-1][0] == hour:
            _RM.hours[-1][1] += n
        else:
            _RM.hours.append([hour, n])
        key = where[0]
        c = _RM.by_caller.get(key)
        if c is None:
            c = _RM.by_caller[key] = {"pipelines": 0, "commands": 0, "cmds": collections.Counter(), "via": where[1:3]}
        c["pipelines"] += 1
        c["commands"] += n
        for x in cmds:
            name = str(x[0]).upper() if isinstance(x, (list, tuple)) and x else "?"
            _RM.by_cmd[name] += 1
            c["cmds"][name] += 1
    except Exception:
        pass


def _rm_all_reads(cmds) -> bool:
    return bool(cmds) and all(isinstance(c, (list, tuple)) and c and str(c[0]).upper() in _RM_READS for c in cmds)


_prev_redis_pipe_122 = globals().get("redis_pipe")

if callable(_prev_redis_pipe_122):
    async def redis_pipe(client, cmds, *args, **kwargs):
        where = _rm_where(2)  # frame 2 = whoever called redis_pipe
        if _RM_CACHE_S > 0 and _rm_all_reads(cmds):
            try:
                key = json.dumps(cmds, default=str)
                hit = _RM_RCACHE.get(key)
                if hit and hit[0] > time.time():
                    _RM.cache_hits += 1
                    _RM.cache_saved += len(cmds)
                    return copy.deepcopy(hit[1])
            except Exception:
                key = None
        else:
            key = None
        _rm_note(cmds, where)
        res = await _prev_redis_pipe_122(client, cmds, *args, **kwargs)
        if key is not None:
            try:
                if len(repr(res)) < 200000:
                    if len(_RM_RCACHE) >= _RM_MAXCACHE:
                        now = time.time()
                        for k in [k for k, v in _RM_RCACHE.items() if v[0] <= now] or list(_RM_RCACHE)[:50]:
                            _RM_RCACHE.pop(k, None)
                    _RM_RCACHE[key] = (time.time() + _RM_CACHE_S, copy.deepcopy(res))
            except Exception:
                pass
        return res

_prev_attest_redis_122 = globals().get("_redis")
if callable(_prev_attest_redis_122) and _prev_attest_redis_122 is not globals().get("redis_pipe"):
    async def _redis(cmds):
        _rm_note(cmds or [], ["part105.py:attestation"])
        return await _prev_attest_redis_122(cmds)


@app.get("/ops/redis", include_in_schema=False)
async def ops_redis(key: str = ""):
    need = os.environ.get("OPS_KEY", "")
    if need and key != need:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    up_h = max((time.time() - _RM.start) / 3600.0, 0.01)
    total = _RM.commands
    top = sorted(_RM.by_caller.items(), key=lambda kv: -kv[1]["commands"])[:15]
    last24 = sum(c for h, c in _RM.hours if h >= int(time.time() // 3600) - 23)
    return {
        "version": VERSION,
        "up_hours": round(up_h, 2),
        "total_pipelines": _RM.pipelines,
        "total_commands": total,
        "commands_per_hour_avg": round(total / up_h, 1),
        "last_24h_commands": last24,
        "projected_per_month": int(total / up_h * 24 * 30),
        "note": "In-memory since the last restart. A sleeping free instance under-counts: the projection assumes it runs all the time.",
        "top_callers": [{"where": k, "pipelines": v["pipelines"], "commands": v["commands"],
                         "share_pct": round(100.0 * v["commands"] / total, 1) if total else None,
                         "top_cmds": dict(v["cmds"].most_common(4)), "via": v["via"]} for k, v in top],
        "top_commands": dict(_RM.by_cmd.most_common(10)),
        "read_cache": {"seconds": _RM_CACHE_S, "hits": _RM.cache_hits, "commands_saved": _RM.cache_saved},
    }


print("[part122] v%s redis usage meter -> GET /ops/redis (read cache %s)" % (VERSION, "%ss" % _RM_CACHE_S if _RM_CACHE_S else "off"))

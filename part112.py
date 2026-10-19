# part112.py - small in-memory response cache for hot, read-only endpoints (v2.89.2)
# Why: the home page calls /stats (twice) and /exit on every visit; each call reads Redis and
# can hit Jupiter. With this, the first request fills the cache and everyone else gets the
# saved copy for a short time. Concurrent requests for the same thing share ONE real call.
# Not cached: errors, compressed replies, and /exit when Jupiter says "unavailable"
# (so the Retry button still works).
# Turn off with env RESP_CACHE=0. Check it works at GET /cachez.
# Loader line (any place before part7):  ("part112.py", 0, "SKIP"),
import asyncio
import json
import os
import time
import types

_C_ON = os.environ.get("RESP_CACHE", "1") != "0"
_C_RULES = {"/stats": 120, "/accuracy": 120, "/exit": 60, "/benchmark/daily": 300, "/stats/deployer-shadow": 300}  # path -> seconds
_C_MAX = 400
_C_MAXBYTES = 1000000
_C = {}
_C_LOCKS = {}
_CS = types.SimpleNamespace(hit=0, miss=0, skip=0, coalesced=0, stored=0, started=int(time.time()))


def _now():
    return time.monotonic()


def _c_key(scope):
    accept = b""
    for k, v in scope.get("headers", []):
        if k == b"accept":
            accept = v
            break
    return (scope.get("path"), scope.get("query_string", b""), b"h" if b"text/html" in accept else b"o")


def _c_get(key):
    e = _C.get(key)
    if e and e[0] > _now():
        return e
    if e:
        _C.pop(key, None)
    return None


def _c_hdrs(base, extra):
    out = [(k, v) for k, v in base if k.lower() not in (b"content-length", b"x-cache", b"age")]
    return out + extra


async def _c_send(send, status, headers, body, extra):
    await send({"type": "http.response.start", "status": status,
                "headers": _c_hdrs(headers, [(b"content-length", str(len(body)).encode())] + extra)})
    await send({"type": "http.response.body", "body": body})


def _c_store(key, path, ttl, start, body):
    """Return True if stored."""
    if start.get("status") != 200 or len(body) > _C_MAXBYTES:
        return False
    hs = {k.lower(): v for k, v in start["headers"]}
    if b"content-encoding" in hs:
        _CS.skip += 1
        return False
    if b"set-cookie" in hs:
        return False
    ctype = hs.get(b"content-type", b"")
    if not (b"json" in ctype or b"html" in ctype or b"text" in ctype):
        return False
    if path == "/exit":
        try:
            d = json.loads(body)
            ex = d.get("exit") if isinstance(d, dict) else None
            if not isinstance(d, dict) or (isinstance(ex, dict) and ex.get("available") is False):
                return False
        except Exception:
            return False
    if len(_C) >= _C_MAX:
        now = _now()
        for k in [k for k, e in _C.items() if e[0] <= now]:
            _C.pop(k, None)
        while len(_C) >= _C_MAX:
            _C.pop(min(_C, key=lambda k: _C[k][0]), None)
    _C[key] = (_now() + ttl, start["status"], list(start["headers"]), body, ttl)
    _CS.stored += 1
    return True


class _CacheMW:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path") if scope["type"] == "http" else None
        ttl = _C_RULES.get(path)
        if not _C_ON or not ttl or scope.get("method") != "GET":
            return await self.app(scope, receive, send)
        key = _c_key(scope)

        async def serve_hit(e):
            _CS.hit += 1
            age = max(0, int(e[4] - (e[0] - _now())))
            extra = [(b"x-cache", b"HIT"), (b"age", str(age).encode())]
            if not any(k.lower() == b"cache-control" for k, _ in e[2]):
                extra.append((b"cache-control", ("public, max-age=%d" % min(60, ttl)).encode()))
            await _c_send(send, e[1], e[2], e[3], extra)

        e = _c_get(key)
        if e:
            return await serve_hit(e)
        lock = _C_LOCKS.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                e = _c_get(key)
                if e:
                    _CS.coalesced += 1
                    return await serve_hit(e)
                _CS.miss += 1
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
                    stored = _c_store(key, path, ttl, start, body)
                    extra = [(b"x-cache", b"MISS")]
                    has_cc = any(k.lower() == b"cache-control" for k, _ in start["headers"])
                    if stored and not has_cc:
                        extra.append((b"cache-control", ("public, max-age=%d" % min(60, ttl)).encode()))
                    elif not stored and path == "/exit" and not has_cc:
                        extra.append((b"cache-control", b"no-store"))
                    await _c_send(send, start["status"], start["headers"], body, extra)

                await self.app(scope, receive, cap)
        finally:
            _C_LOCKS.pop(key, None)


try:
    app.add_middleware(_CacheMW)
except Exception as _e:
    print("[part112] could not add middleware:", str(_e)[:120])


@app.get("/cachez", include_in_schema=False)
async def cache_status():
    total = _CS.hit + _CS.miss
    return {"enabled": _C_ON, "rules_seconds": _C_RULES, "entries": len(_C),
            "hits": _CS.hit, "misses": _CS.miss, "shared_waits": _CS.coalesced,
            "hit_rate_pct": round(_CS.hit * 100.0 / total, 1) if total else None,
            "skipped_compressed": _CS.skip, "up_since": _CS.started}


print("[part112] response cache for %s (RESP_CACHE=%s)" % (", ".join(sorted(_C_RULES)), "on" if _C_ON else "off"))

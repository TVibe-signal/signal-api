"""part98 - Fewer blocks, visible reasons (v2.76.0). Changes NO verdict.
One wrapper around httpx.AsyncClient.send for the upstream hosts below:
 1. counts status codes / latency per host -> GET /upstream/errors (429 vs 403 vs timeouts)
 2. single-flight: identical in-flight GETs share one upstream call
 3. soft token bucket per host: waits up to P98_MAX_WAIT_MS (default 1200), never blocks longer
Env (all optional): P98_ENABLED, P98_LIMIT, P98_COALESCE (default on; 0/off/false disables),
P98_DEX_RPM=240, P98_DEX_PROF_RPM=48, P98_GECKO_RPM=24, P98_PUMP_RPM=60, P98_MAX_WAIT_MS=1200
Limits sit at about 80% of the published ones (Dex 300/60, Gecko 30 per minute).
"""
VERSION = "2.76.0"
app.version = VERSION
app.openapi_schema = None

import asyncio
import os
import time

import httpx

_P98_T0 = time.time()
_P98_HOSTS = {"api.dexscreener.com", "api.geckoterminal.com", "frontend-api-v3.pump.fun",
              "lite-api.jup.ag", "api.jup.ag", "api.rugcheck.xyz"}
_P98_ST = {}
_P98_INFLIGHT = {}
_P98_BUCKETS = {}
_P98_TOTAL = {"coalesced": 0, "limiter_waits": 0, "waited_ms": 0}


def _p98_on(name):
    return os.environ.get(name, "1").lower() not in ("0", "false", "off")


def _p98_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except Exception:
        return default


class _Bucket:
    def __init__(self, rpm, burst):
        self.rate, self.cap = max(rpm, 1) / 60.0, float(burst)
        self.tokens, self.ts = float(burst), time.monotonic()

    def reserve(self):
        now = time.monotonic()
        self.tokens = min(self.cap, self.tokens + (now - self.ts) * self.rate)
        self.ts = now
        self.tokens = max(-self.cap, self.tokens - 1)
        return max(0.0, -self.tokens) / self.rate


def _p98_class(host, path):
    if host == "api.dexscreener.com":
        slow = path.startswith(("/token-profiles", "/token-boosts", "/orders"))
        return ("dex_profile", _p98_int("P98_DEX_PROF_RPM", 48), 5) if slow else \
               ("dex_pairs", _p98_int("P98_DEX_RPM", 240), 20)
    if host == "api.geckoterminal.com":
        return "gecko", _p98_int("P98_GECKO_RPM", 24), 5
    if host == "frontend-api-v3.pump.fun":
        return "pump", _p98_int("P98_PUMP_RPM", 60), 10
    return None


async def _p98_wait(host, path):
    spec = _p98_class(host, path)
    if not spec or not _p98_on("P98_LIMIT"):
        return
    name, rpm, burst = spec
    b = _P98_BUCKETS.get(name)
    if b is None:
        b = _P98_BUCKETS[name] = _Bucket(rpm, burst)
    w = min(b.reserve(), _p98_int("P98_MAX_WAIT_MS", 1200) / 1000.0)
    if w > 0.01:
        _P98_TOTAL["limiter_waits"] += 1
        _P98_TOTAL["waited_ms"] += int(w * 1000)
        await asyncio.sleep(w)


def _p98_rec(host, code, ms, retry_after=None):
    s = _P98_ST.setdefault(host, {"n": 0, "codes": {}, "ms": 0.0, "consec_block": 0,
                                   "last_429_ago_s": None, "retry_after": None, "coalesced": 0})
    s["n"] += 1
    s["ms"] += ms
    key = "exc" if code == 0 else ("5xx" if code >= 500 else str(code))
    s["codes"][key] = s["codes"].get(key, 0) + 1
    if code in (403, 429):
        s["consec_block"] += 1
        if code == 429:
            s["_t429"] = time.time()
    elif 200 <= code < 300:
        s["consec_block"] = 0
    if retry_after:
        s["retry_after"] = retry_after


def _p98_diag(s):
    n, c = max(s["n"], 1), s["codes"]
    if s["consec_block"] >= 3:
        return "blocked_or_waf", "3+ blocks in a row (403/429): hard limit or IP/WAF block. Slow down, cache longer, use another egress or an API key."
    if c.get("429", 0) / n > 0.05:
        return "rate_limited", "429 above 5%: batch more tokens per call, raise cache TTL, lower P98_*_RPM."
    if c.get("exc", 0) / n > 0.10:
        return "unreachable_or_slow", "Timeouts/errors above 10%: network or provider trouble, keep the fallback source on."
    if c.get("403", 0):
        return "some_403", "Occasional 403: watch it, may be a WAF challenge."
    return "ok", ""


if not getattr(httpx.AsyncClient.send, "_p98", False):
    _p98_orig_send = httpx.AsyncClient.send

    async def _p98_send(self, request, **kw):
        host = request.url.host
        if host not in _P98_HOSTS or not _p98_on("P98_ENABLED"):
            return await _p98_orig_send(self, request, **kw)
        coalesce = request.method == "GET" and not kw.get("stream") and _p98_on("P98_COALESCE")
        key = str(request.url)
        if coalesce and key in _P98_INFLIGHT:
            try:
                resp = await asyncio.shield(_P98_INFLIGHT[key])
                _P98_TOTAL["coalesced"] += 1
                _P98_ST.setdefault(host, {"n": 0, "codes": {}, "ms": 0.0, "consec_block": 0,
                                          "retry_after": None, "coalesced": 0})["coalesced"] += 1
                return resp
            except Exception:
                pass  # leader failed: make our own call
        leader = None
        if coalesce:
            leader = asyncio.get_running_loop().create_future()
            _P98_INFLIGHT[key] = leader
        t0 = time.time()
        try:
            await _p98_wait(host, request.url.path)
            resp = await _p98_orig_send(self, request, **kw)
        except BaseException:
            _p98_rec(host, 0, (time.time() - t0) * 1000)
            if leader is not None and not leader.done():
                leader.set_exception(RuntimeError("leader failed"))
                leader.exception()
            raise
        else:
            ra = resp.headers.get("retry-after") if resp.status_code in (429, 503) else None
            _p98_rec(host, resp.status_code, (time.time() - t0) * 1000, ra)
            if leader is not None and not leader.done():
                leader.set_result(resp)
            return resp
        finally:
            if leader is not None and _P98_INFLIGHT.get(key) is leader:
                _P98_INFLIGHT.pop(key, None)

    _p98_send._p98 = True
    httpx.AsyncClient.send = _p98_send


@app.get("/upstream/errors", tags=["product"])
async def upstream_errors():
    hosts = {}
    for host, s in _P98_ST.items():
        n = s["n"]
        d, hint = _p98_diag(s)
        t = s.get("_t429")
        hosts[host] = {
            "requests": n, "status_counts": s["codes"],
            "rate_429_pct": round(100.0 * s["codes"].get("429", 0) / n, 1) if n else None,
            "avg_ms": round(s["ms"] / n) if n else None,
            "coalesced": s.get("coalesced", 0), "last_retry_after": s["retry_after"],
            "last_429_ago_s": int(time.time() - t) if t else None,
            "diagnosis": d, "hint": hint,
        }
    return {"version": VERSION, "since_s": int(time.time() - _P98_T0), "hosts": hosts, "totals": _P98_TOTAL,
            "note": "In-memory counters, reset on restart or sleep. Needs ~20+ requests per host to mean much."}


print(f"[part98] v{VERSION} upstream counters + single-flight + soft limiter -> GET /upstream/errors")

"""part96 - Calibration fixes (v2.74.0). Changes NO verdict.
- part93 look-ahead fix: the FIRST snapshot per mint is kept (SET NX)
- /stats/shadow-avoid: recall, live baseline, per-rule counts, Wilson 95% CI
- /stats/bias, /stats/horizons, /upstream/status read the real /stats and /health
- POST /keys/request: per-IP limit (3/hour), honest storage errors
- decision_confidence: heuristic level from data completeness + source health
"""
VERSION = "2.74.0"
app.version = VERSION
app.openapi_schema = None

import asyncio
import hashlib
import json
import math
import os
import time

from fastapi.responses import JSONResponse

_P96_CACHE = {}
_P96_TASKS = set()
_P96_HEALTH = {"data": {}, "ts": 0.0}


def wilson(k, n, z=1.96):
    k, n = int(k or 0), int(n or 0)
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    lo, hi = max(0.0, (c - m) / d), min(1.0, (c + m) / d)
    return [round(100 * lo, 1), round(100 * hi, 1)]


def _pct(k, n):
    return round(100.0 * k / n, 1) if n else None


def _drop_routes(paths, method=None):
    keep = []
    for r in app.router.routes:
        ms = getattr(r, "methods", None) or set()
        if getattr(r, "path", None) in paths and (method is None or method in ms):
            continue
        keep.append(r)
    app.router.routes[:] = keep


async def _internal_get(path, ttl=15):
    """Call our own route through ASGI (real handler, no guessed names)."""
    hit = _P96_CACHE.get(path)
    if hit and hit[0] > time.time():
        return hit[1]
    data = {}
    try:
        import httpx
        tr = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=tr, base_url="http://internal", timeout=8) as c:
            r = await c.get(path)
            if r.status_code == 200:
                data = r.json()
    except Exception as e:
        print(f"[part96] internal {path}: {str(e)[:100]}")
    if isinstance(data, dict) and data:
        _P96_CACHE[path] = (time.time() + ttl, data)
        return data
    return {}


def _first(res):
    v = res[0] if res else None
    return v.get("result") if isinstance(v, dict) else v


# ---- 1) look-ahead fix: keep the first snapshot, count each mint once ----
async def _shadow_avoid_pending(client, mint, payload):
    if not PRED_ENABLED or not client:
        return
    try:
        key = SHADOW_AVOID_PENDING.format(mint)
        res = await redis_pipe(client, [["SET", key, json.dumps(payload), "EX", SHADOW_AVOID_TTL, "NX"]])
        if not _first(res):
            return  # an earlier snapshot is already waiting for its outcome
        cmds = [["HINCRBY", SHADOW_AVOID_KEY, "emitted", 1],
                ["EXPIRE", SHADOW_AVOID_KEY, 120 * 86400]]
        if payload.get("would_flag_avoid"):
            cmds.append(["HINCRBY", SHADOW_AVOID_KEY, "flagged_avoid", 1])
        if payload.get("live_verdict") == "avoid":
            cmds.append(["HINCRBY", SHADOW_AVOID_KEY, "live_flagged", 1])
        await redis_pipe(client, cmds)
    except Exception:
        pass


# ---- 2) outcome: tp/fp for shadow AND live, per rule, gain over live ----
async def shadow_avoid_on_outcome(client, mint, bad, meta=None):
    if not PRED_ENABLED or not client:
        return
    try:
        key = SHADOW_AVOID_PENDING.format(mint)
        raw = await redis_get(client, key)
        if not raw:
            return
        snap = json.loads(raw)
        flagged = bool(snap.get("would_flag_avoid"))
        live_avoid = (snap.get("live_verdict") or "").lower() == "avoid"
        K, tag = SHADOW_AVOID_KEY, ("tp" if bad else "fp")
        cmds = [["HINCRBY", K, "judged", 1], ["HINCRBY", K, "bad", 1 if bad else 0],
                ["DEL", key], ["EXPIRE", K, 120 * 86400]]
        if flagged:
            cmds.append(["HINCRBY", K, tag, 1])
        if live_avoid:
            cmds.append(["HINCRBY", K, "live_" + tag, 1])
        if flagged and not live_avoid:
            cmds.append(["HINCRBY", K, "gain_" + tag, 1])
        if bad and not flagged and not live_avoid:
            cmds.append(["HINCRBY", K, "fn_vs_live_miss", 1])
        for rule in snap.get("rules_hit") or []:
            cmds.append(["HINCRBY", K, f"r_{rule}_{tag}", 1])
        await redis_pipe(client, cmds)
    except Exception as e:
        print(f"[part96] outcome: {e}")


_drop_routes({"/stats/shadow-avoid"})


@app.get("/stats/shadow-avoid", tags=["accuracy"])
async def stats_shadow_avoid_v2(request: Request):
    client, h = request.app.state.client, {}
    try:
        if PRED_ENABLED and client:
            raw = await redis_pipe(client, [["HGETALL", SHADOW_AVOID_KEY]])
            h = to_dict((raw or [{}])[0] or {})
    except Exception:
        pass

    def g(k):
        try:
            return int(float(h.get(k, 0) or 0))
        except Exception:
            return 0

    judged, bad = g("judged"), g("bad")

    def block(t, f):
        n = t + f
        return {"flagged": n, "tp": t, "fp": f,
                "precision_pct": _pct(t, n), "precision_ci95": wilson(t, n),
                "recall_pct": _pct(t, bad), "recall_ci95": wilson(t, bad)}

    shadow, live = block(g("tp"), g("fp")), block(g("live_tp"), g("live_fp"))
    base = _pct(bad, judged)
    floor = max(base or 0, live["precision_pct"] or 0)
    names = {str(k)[2:-3] for k in h if str(k).startswith("r_") and str(k)[-3:] in ("_tp", "_fp")}
    rules, ready = {}, []
    for nm in sorted(names):
        b = block(g(f"r_{nm}_tp"), g(f"r_{nm}_fp"))
        rules[nm] = b
        ci = b["precision_ci95"]
        if b["flagged"] >= 30 and ci and ci[0] > floor:
            ready.append(nm)
    return {
        "version": VERSION, "emitted": g("emitted"), "judged": judged, "bad": bad,
        "base_rate_pct": base, "base_rate_ci95": wilson(bad, judged),
        "shadow": shadow, "live": live,
        "gain_vs_live": {"extra_bad_caught": g("gain_tp"), "extra_false_alarms": g("gain_fp")},
        "rules": rules, "promote_candidates": ready, "ready": judged >= 30,
        "note": ("Shadow only. A rule is a candidate when flagged>=30 and the lower 95% bound of "
                 "its precision beats both the base rate and live precision. Live verdict unchanged."),
    }


# ---- 3) real /stats and /health readers ----
_drop_routes({"/stats/bias", "/stats/horizons", "/upstream/status"})


def _keys(st):
    return sorted(st.keys())[:60] if isinstance(st, dict) else []


@app.get("/stats/bias", tags=["accuracy"])
async def stats_bias_v2():
    st = await _internal_get("/stats", 20)
    p = build_bias_panel(st)
    p["source"] = "stats" if st else "internal_call_failed"
    if not p.get("available"):
        p["seen_keys"] = _keys(st)  # send these so field names can be matched
    return p


@app.get("/stats/horizons", tags=["accuracy"])
async def stats_horizons_v2():
    st = await _internal_get("/stats", 20)
    p = build_horizons_panel(st)
    p["source"] = "stats" if st else "internal_call_failed"
    if not any(v.get("n") for k, v in p["horizons"].items() if k != "24h"):
        p["seen_keys"] = _keys(st)
    return p


@app.get("/upstream/status", tags=["product"])
async def upstream_status_v2():
    h = await _internal_get("/health", 10)
    return {
        "version": VERSION, "source": "health" if h else "internal_call_failed",
        "sources": h.get("sources") or {}, "stability": h.get("stability") or {},
        "upstream": h.get("upstream") or {}, "fallback": h.get("fallback") or {},
        "agent_hint": ("On HTTP 429/503 honor Retry-After. Prefer /omni over many small calls. "
                       "Batch max 10 via /signals. Cache client-side 15-30s for the same mint."),
    }


# ---- 4) /keys/request: limit per IP, no fake success ----
def _client_ip(request):
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else ""
    return ip or (request.client.host if request.client else "unknown")


_drop_routes({"/keys/request"}, "POST")


@app.post("/keys/request", tags=["product"])
async def keys_request_v2(request: Request, contact: str = "", use_case: str = "", expected_rpm: int = 60):
    client = request.app.state.client
    contact, use_case = (contact or "").strip()[:200], (use_case or "").strip()[:500]
    if len(contact) < 3:
        return {"ok": False, "error": "contact required (X handle or email)", "version": VERSION}
    if not (PRED_ENABLED and client):
        return {"ok": False, "error": "storage unavailable, DM https://x.com/realTVibe", "version": VERSION}
    salt = os.environ.get("KEY_SALT") or os.environ.get("RENDER_SERVICE_ID") or "tvibex402"
    iph = hashlib.sha256((salt + _client_ip(request)).encode()).hexdigest()[:16]
    try:
        rk = f"si:key:rl:{iph}"
        res = await redis_pipe(client, [["INCR", rk], ["EXPIRE", rk, 3600]])
        if int(_first(res) or 0) > 3:
            return JSONResponse({"ok": False, "error": "too many requests, try later", "version": VERSION},
                                status_code=429, headers={"Retry-After": "3600"})
        row = {"ts": int(time.time()), "contact": contact, "use_case": use_case,
               "expected_rpm": max(1, min(int(expected_rpm or 60), 5000)),
               "ip_hash": iph, "status": "pending"}
        await redis_pipe(client, [["LPUSH", KEY_REQ, json.dumps(row)], ["LTRIM", KEY_REQ, 0, 499],
                                  ["EXPIRE", KEY_REQ, KEY_REQ_TTL]])
    except Exception as e:
        return {"ok": False, "error": str(e)[:120], "version": VERSION}
    return {"ok": True, "status": "pending", "version": VERSION,
            "message": "Request stored. Keys are issued by hand during beta; you may also DM https://x.com/realTVibe"}


# ---- 5) decision_confidence (heuristic, NOT calibrated) ----
_CORE = ("dexscreener", "solana_rpc", "rugcheck")


def _health_cached():
    if time.time() - _P96_HEALTH["ts"] > 20:
        _P96_HEALTH["ts"] = time.time()

        async def _refresh():
            d = await _internal_get("/health", 15)
            if d:
                _P96_HEALTH["data"] = d

        t = asyncio.create_task(_refresh())
        _P96_TASKS.add(t)
        t.add_done_callback(_P96_TASKS.discard)
    return _P96_HEALTH["data"]


def _confidence(result):
    reasons, pts = [], 0
    unk = (result.get("decision") or {}).get("unknowns") or []
    if isinstance(unk, list) and unk:
        reasons.append(f"{len(unk)} unknowns")
        pts += min(len(unk), 3)
    for k, label in (("stale", "stale data"), ("partial", "partial data")):
        if result.get(k):
            reasons.append(label)
            pts += 1
    src = _health_cached().get("sources") or {}
    bad = [n for n in _CORE if (src.get(n) or {}).get("status") in ("degraded", "down")]
    if bad:
        reasons.append("sources degraded: " + ",".join(bad))
        pts += len(bad)
        if "dexscreener" in bad and (src.get("geckoterminal") or {}).get("status") == "down":
            reasons.append("no fallback for market data")
            pts += 1
    level = "high" if pts == 0 else "medium" if pts <= 2 else "low"
    return {"level": level, "reasons": reasons, "calibrated": False,
            "note": "Heuristic from data completeness and source health; not yet checked against outcomes."}


_build_prev_p96 = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_p96(client, mint, security, prefetched)
    try:
        if isinstance(result, dict):
            result["decision_confidence"] = _confidence(result)
            order = result.get("si_reading_order")
            if isinstance(order, dict) and "decision_confidence" not in order.get("primary", []):
                order.setdefault("primary", []).append("decision_confidence")
    except Exception:
        pass
    return result, status


print(f"[part96] v{VERSION} calibration fixes: shadow-avoid recall/CI, real stats+health readers, key limit, confidence")

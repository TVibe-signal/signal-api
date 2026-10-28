"""
TVibe Signal API — extensions.py
Extensions: UI, Telegram, benchmarks, stats, MCP server (must be last)
Loaded by main.py into shared namespace (same behavior as original multi-part).
Source: https://github.com/TVibe-signal/signal-api
"""

# --- part94 ---
# ---------- v2.72: Agent snippets + SI noise reduction ----------
VERSION = "2.72.0"
app.version = VERSION
app.openapi_schema = None

from fastapi.responses import PlainTextResponse, HTMLResponse

AGENT_SNIPPETS = r'''# TVibex402 — agent snippets (copy-paste)

Base: https://signal-api-24q4.onrender.com
Primary: GET /omni?mint=<MINT>
MCP: POST /mcp  tool omni(mint)
Not financial advice.

## curl
curl -s "https://signal-api-24q4.onrender.com/omni?mint=So11111111111111111111111111111111111111112"

## Python httpx
import httpx
r = httpx.get(
    "https://signal-api-24q4.onrender.com/omni",
    params={"mint": "So11111111111111111111111111111111111111112"},
    timeout=60,
)
data = r.json()
verdict = (data.get("decision") or {}).get("verdict")

## LangChain-style tool (pseudo)
# Use StructuredTool that GETs /omni and returns decision.verdict + summary only.

## CrewAI / AutoGen
# One tool: fetch_omni(mint) -> trust decision.*; treat debate/residual/pre_rug as optional context.

## Claude MCP / Cursor
# Add MCP server URL: https://signal-api-24q4.onrender.com/mcp
# Prefer tool: omni

## How to read the payload
1. decision.verdict  (primary)
2. decision.blockers / cautions / unknowns
3. Optional: debate, attention_residuals, pre_rug, shadow_avoid (experimental)
4. Prove: GET /stats  GET /stats/horizons  GET /stats/bias  GET /benchmark/prerug
'''


@app.get("/agents/snippets", response_class=PlainTextResponse, tags=["product"])
async def agents_snippets():
    return AGENT_SNIPPETS


@app.get("/agents/snippets.html", response_class=HTMLResponse, tags=["product"], include_in_schema=False)
async def agents_snippets_html():
    body = AGENT_SNIPPETS.replace("&", "&amp;").replace("<", "&lt;")
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>TVibex402 agent snippets</title>
<style>body{{font-family:ui-monospace,monospace;background:#0b1220;color:#e8eef6;padding:24px}}
pre{{white-space:pre-wrap;background:#121a2a;padding:16px;border-radius:12px}}</style></head>
<body><h1>Agent snippets</h1><pre>{body}</pre>
<p><a href="/agents" style="color:#14f195">/agents</a> · <a href="/llms.txt" style="color:#14f195">/llms.txt</a></p>
</body></html>"""


def _si_quiet(result: dict) -> dict:
    """Mark experimental blocks so agents know what is primary."""
    if not isinstance(result, dict):
        return result
    exp = []
    for k in ("debate", "attention_residuals", "shadow_avoid", "pre_rug", "dna", "time_to_death",
              "counterfactual", "hypotheses_matched", "genetic_risk", "attention_trap", "swarm"):
        if result.get(k) is not None:
            exp.append(k)
    result["si_reading_order"] = {
        "primary": ["decision.verdict", "decision.blockers", "decision.cautions", "decision.unknowns"],
        "experimental": exp,
        "note": "Trust decision.* first. Experimental fields are context, not overrides.",
        "version": VERSION,
    }
    return result


_build_prev_quiet = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_quiet(client, mint, security, prefetched)
    try:
        if isinstance(result, dict):
            result = _si_quiet(result)
    except Exception:
        pass
    return result, status


print(f"[part94] v{VERSION} agent snippets + si_reading_order → /agents/snippets")

# --- part95 ---
# ---------- v2.73: Self-serve key request (beta) + upstream RL status ----------
VERSION = "2.73.0"
app.version = VERSION
app.openapi_schema = None

import hashlib
import json
import os
import time
from typing import Optional

KEY_REQ = "si:key:requests"
KEY_REQ_TTL = 30 * 86400
UPSTREAM_RL = "si:upstream:rl"


@app.post("/keys/request", tags=["product"])
async def keys_request(
    request: Request,
    contact: str = "",
    use_case: str = "",
    expected_rpm: int = 60,
):
    """
    Self-serve *request* for a higher limit key (still manually issued in beta).
    Does not mint a live key automatically — stores the request for the operator.
    """
    client = request.app.state.client
    contact = (contact or "").strip()[:200]
    use_case = (use_case or "").strip()[:500]
    expected_rpm = max(1, min(int(expected_rpm or 60), 5000))
    if len(contact) < 3:
        return {"ok": False, "error": "contact required (X handle or email)", "version": VERSION}
    row = {
        "ts": int(time.time()),
        "contact": contact,
        "use_case": use_case,
        "expected_rpm": expected_rpm,
        "ip_hash": hashlib.sha256(
            (request.client.host if request.client else "unknown").encode()
        ).hexdigest()[:16],
        "status": "pending",
    }
    try:
        if PRED_ENABLED and client:
            await redis_pipe(client, [
                ["LPUSH", KEY_REQ, json.dumps(row)],
                ["LTRIM", KEY_REQ, 0, 499],
                ["EXPIRE", KEY_REQ, KEY_REQ_TTL],
            ])
    except Exception as e:
        return {"ok": False, "error": str(e)[:120], "version": VERSION}
    return {
        "ok": True,
        "status": "pending",
        "message": "Request stored. Keys are issued by hand during beta; you may also DM https://x.com/realTVibe",
        "version": VERSION,
    }


@app.get("/keys/request", tags=["product"])
async def keys_request_help():
    return {
        "how": "POST /keys/request?contact=@your_x&use_case=my_bot&expected_rpm=120",
        "beta": True,
        "auto_issue": False,
        "version": VERSION,
    }


@app.get("/upstream/status", tags=["product"])
async def upstream_status(request: Request):
    """Lightweight upstream health for agents (Dex cooling, sources)."""
    health = {}
    # Reuse in-process source stats if present
    src = globals().get("_source_stats") or globals().get("SOURCE_STATS") or {}
    stability = {}
    try:
        # Prefer last health snapshot if something cached it
        h = globals().get("_LAST_HEALTH") or {}
        if isinstance(h, dict):
            src = h.get("sources") or src
            stability = h.get("stability") or {}
    except Exception:
        pass
    return {
        "version": VERSION,
        "sources": src,
        "stability": stability,
        "agent_hint": (
            "On HTTP 429/503 honor Retry-After. Prefer /omni over many small calls. "
            "Batch max 10 via /signals. Cache client-side 15–30s for the same mint."
        ),
        "note": "Server already cools Dex and falls back to GeckoTerminal when needed.",
    }


print(f"[part95] v{VERSION} POST /keys/request · GET /upstream/status")

# --- part96 ---
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

# --- part97 ---
"""part97 - /stats output fixes + honest comparison (v2.75.0). Changes NO verdict.
A small middleware post-processes GET /stats (original body is returned if anything fails):
- ci95_pct values were x100 (9220 -> 92.2)
- by_risk_bucket avg_return_pct 0.0 (not measured) -> null
- outlier-distorted means (>1000%) hidden
- adds base_rate (+ lift_vs_base), rule_comparison_24h, selection_bias
Needs part96 (wilson, _pct) loaded first.
"""
VERSION = "2.75.0"
app.version = VERSION
app.openapi_schema = None

import json

from fastapi.responses import Response


def _ci_over_100(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k.endswith("ci95_pct") and isinstance(v, list) and any(
                    isinstance(x, (int, float)) and x > 100 for x in v):
                return True
            if _ci_over_100(v):
                return True
    elif isinstance(o, list):
        return any(_ci_over_100(x) for x in o)
    return False


def _scale_ci(o):
    if isinstance(o, dict):
        for k, v in list(o.items()):
            if k.endswith("ci95_pct") and isinstance(v, list):
                o[k] = [round(x / 100.0, 1) if isinstance(x, (int, float)) else x for x in v]
            else:
                _scale_ci(v)
    elif isinstance(o, list):
        for x in o:
            _scale_ci(x)


def _hide_outliers(o):
    for v in (o.get("by_verdict") or {}).values():
        for blk in (v or {}).values():
            if not isinstance(blk, dict):
                continue
            for f in ("avg_return_pct", "avg_excess_return_pct"):
                x = blk.get(f)
                if isinstance(x, (int, float)) and abs(x) > 1000:
                    blk[f] = None
                    blk["outlier_note"] = "mean hidden: distorted by extreme values (median not tracked yet)"
    for b in o.get("by_risk_bucket") or []:
        if b.get("avg_excess_return_pct") is None and b.get("avg_return_pct") == 0:
            b["avg_return_pct"] = None  # was never measured, 0.0 was misleading


def _base_rate(o):
    a = (o.get("performance") or {}).get("all_tracked") or {}
    j, b = int(a.get("judged") or 0), int(a.get("bad_outcomes") or 0)
    if not j:
        return None
    r = {"judged": j, "bad": b, "bad_outcome_rate_pct": _pct(b, j), "ci95_pct": wilson(b, j),
         "note": "A random token is already 'bad' this often: read precision as lift over this rate."}
    for v in (o.get("by_verdict") or {}).values():
        full = (v or {}).get("full") or {}
        rate = full.get("bad_outcome_rate_pct")
        if rate is not None and r["bad_outcome_rate_pct"]:
            full["lift_vs_base"] = round(rate / r["bad_outcome_rate_pct"], 2)
    return r


def _rule_table(o, base):
    sr = o.get("shadow_rules") or {}
    rules = sr.get("rules") or {}
    live = rules.get("live") or {}
    lp, lr = live.get("avoid_precision_pct"), live.get("avoid_recall_pct")
    out = {}
    for name, r in rules.items():
        av = r.get("avoid") or {}
        n, rate = int(av.get("n") or 0), av.get("bad_outcome_rate_pct")
        if not n or rate is None:
            continue
        ci = wilson(round(rate * n / 100.0), n)
        ok = r.get("ok") or {}
        row = {"avoid_n": n, "precision_pct": rate, "precision_ci95_pct": ci,
               "recall_pct": r.get("avoid_recall_pct"),
               "ok_n": ok.get("n"), "ok_bad_rate_pct": ok.get("bad_outcome_rate_pct")}
        rec = r.get("avoid_recall_pct")
        if name != "live" and None not in (lp, lr, rec):
            d_r, d_p = round(rec - lr, 1), round(rate - lp, 1)
            row["recall_vs_live_pts"], row["precision_vs_live_pts"] = d_r, d_p
            row["candidate"] = bool(n >= 100 and ci and base and ci[0] > base and d_r >= 10 and d_p >= -3)
        out[name] = row
    return {"horizon_hours": sr.get("horizon_hours"), "judged": live.get("judged"), "rules": out,
            "criterion": ("candidate = avoid_n>=100, lower 95% precision bound above the base rate, "
                          "recall at least 10 pts above live, precision at most 3 pts below live. "
                          "Check walk-forward before promoting; live verdict is unchanged.")}


def _cohort_rates(block):
    if not isinstance(block, dict):
        return {"n": 0}
    vs = block.get("verdicts") or {}
    return {"n": int(block.get("n") or 0),
            "bad_outcome_rate_pct": block.get("bad_outcome_rate_pct"),
            "ci95_pct": block.get("ci95_pct"),
            "verdicts": {k: {"n": (vs.get(k) or {}).get("n"),
                             "bad_outcome_rate_pct": (vs.get(k) or {}).get("bad_outcome_rate_pct")}
                         for k in ("ok", "caution", "avoid") if k in vs}}


def build_bias_panel(stats):
    by = (stats or {}).get("by_source") or {}
    user = _cohort_rates(by.get("user") or {})
    parts = {k: _cohort_rates(v) for k, v in by.items() if str(k).startswith("seed")}
    seed_n = sum(p["n"] for p in parts.values())
    t, u = (parts.get("seed_trending") or {}).get("bad_outcome_rate_pct"), user.get("bad_outcome_rate_pct")
    return {
        "available": bool(by), "user": user, "seed": {"n": seed_n, "parts": parts},
        "untagged": _cohort_rates(by.get("untagged") or {}),
        "user_minus_seed_trending_pts": round(u - t, 1) if None not in (u, t) else None,
        "note": ("user = tokens people/agents queried; seed_boost and seed_profile are paid DexScreener "
                 "promotions, seed_trending and seed_new come from GeckoTerminal. Cohorts differ a lot, so "
                 "rates are selection-biased. Rates are hidden under 20 samples."),
        "ready": (user.get("n") or 0) >= 20 or seed_n >= 20, "version": VERSION,
    }


def _fix_stats(d):
    if not isinstance(d, dict) or not d.get("available", True):
        return d
    if _ci_over_100(d):
        _scale_ci(d)
    _hide_outliers(d)
    br = _base_rate(d)
    if br:
        d["base_rate"] = br
    d["rule_comparison_24h"] = _rule_table(d, (br or {}).get("bad_outcome_rate_pct"))
    d["selection_bias"] = build_bias_panel(d)
    d["stats_fixes"] = VERSION
    return d


try:
    @app.middleware("http")
    async def _p97_stats_mw(request, call_next):
        resp = await call_next(request)
        if request.method != "GET" or request.url.path != "/stats" or resp.status_code != 200:
            return resp
        body = b""
        async for chunk in resp.body_iterator:
            body += chunk
        keep = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
        try:
            out = json.dumps(_fix_stats(json.loads(body)), separators=(",", ":")).encode()
            keep = {k: v for k, v in keep.items() if k.lower() != "content-encoding"}
        except Exception as e:
            print(f"[part97] stats fix skipped: {str(e)[:80]}")
            out = body
        return Response(content=out, status_code=200, headers=keep, media_type="application/json")
except Exception as e:
    print(f"[part97] middleware not added: {e}")


print(f"[part97] v{VERSION} /stats fixes: ci scale, null returns, base_rate, rule_comparison_24h, selection_bias")

# --- part98 ---
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

# --- part99 ---
"""part99 - Evidence-calibrated reasoning (v2.77.0). Changes NO verdict.
Turns the track record into per-signal reasoning, using only what the data shows:
- calibrated_risk: P(bad within 24h) for this risk score, monotone-smoothed (pool adjacent
  violators) from by_risk_bucket, with a 95% interval, base rate and lift
- evidence: which present flags the data supports / contradicts / has never tested
- bad_rate_by_horizon + return_context for the verdict (1h / 6h / 24h, average return)
- reading: a short grounded text agents can quote
- GET /calibration shows the whole table. Needs part96 (wilson, _internal_get, _P96_TASKS).
"""
VERSION = "2.77.0"
app.version = VERSION
app.openapi_schema = None

import asyncio
import time

_P99 = {"model": None, "ts": 0.0, "tried": 0.0}


def _p99_build(st):
    bk = []
    for b in st.get("by_risk_bucket") or []:
        try:
            lo, hi = [int(x) for x in str(b.get("risk_score_range", "")).split("-")]
        except Exception:
            continue
        n, r = int(b.get("n") or 0), b.get("bad_outcome_rate_pct")
        if n and r is not None:
            bk.append((lo, hi, round(r * n / 100.0), n))
    bk.sort()
    blocks = []  # pool adjacent violators: rates must not fall as risk rises
    for i, (_, _, k, n) in enumerate(bk):
        blocks.append([k, n, [i]])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            b2, b1 = blocks.pop(), blocks.pop()
            blocks.append([b1[0] + b2[0], b1[1] + b2[1], b1[2] + b2[2]])
    table = []
    for k, n, idx in blocks:
        rng = f"{bk[idx[0]][0]}-{bk[idx[-1]][1]}"
        for i in idx:
            lo, hi = bk[i][0], bk[i][1]
            table.append({"bucket": f"{lo}-{hi}", "range": rng, "lo": lo, "hi": hi,
                          "p_bad_24h_pct": round(100.0 * k / n, 1),
                          "ci95_pct": wilson(k, n), "n": n, "pooled": len(idx) > 1})
    a = (st.get("performance") or {}).get("all_tracked") or {}
    base = (st.get("base_rate") or {}).get("bad_outcome_rate_pct")
    if base is None and a.get("judged"):
        base = round(100.0 * a.get("bad_outcomes", 0) / a["judged"], 1)
    pv, early = (a.get("verdicts") or {}), (st.get("early_horizons") or {})
    hz = {}
    for v in ("ok", "caution", "avoid"):
        row = {}
        for h in ("1h", "6h"):
            x = ((early.get(h) or {}).get("by_verdict") or {}).get(v) or {}
            row[h] = {"bad_rate_pct": x.get("bad_outcome_rate_pct"), "n": x.get("n")}
        x = pv.get(v) or {}
        row["24h"] = {"bad_rate_pct": x.get("bad_outcome_rate_pct"), "n": x.get("n")}
        full = ((st.get("by_verdict") or {}).get(v) or {}).get("full") or {}
        row["avg_return_pct_24h"] = {"value": full.get("avg_return_pct"), "n": full.get("n")}
        hz[v] = row
    flags = {f["flag"]: f for f in st.get("flags") or [] if f.get("flag")}
    return {"table": table, "base": base, "horizons": hz, "flags": flags,
            "definition": st.get("bad_outcome_definition")}


async def _p99_refresh():
    st = await _internal_get("/stats", 60)
    if st and st.get("available"):
        try:
            _P99["model"], _P99["ts"] = _p99_build(st), time.time()
        except Exception as e:
            print(f"[part99] model: {str(e)[:80]}")
    return _P99["model"]


def _p99_cached():
    if time.time() - _P99["tried"] > 120:
        _P99["tried"] = time.time()
        t = asyncio.create_task(_p99_refresh())
        _P96_TASKS.add(t)
        t.add_done_callback(_P96_TASKS.discard)
    return _P99["model"]


def _p99_calibrate(score, m):
    for row in m["table"]:
        if row["lo"] <= score < row["hi"] + 1 or (score >= 100 and row["hi"] >= 99):
            p, base = row["p_bad_24h_pct"], m["base"]
            return {"p_bad_24h_pct": p, "ci95_pct": row["ci95_pct"], "based_on_n": row["n"],
                    "score_bucket": row["range"], "pooled": row["pooled"], "base_rate_pct": base,
                    "lift_vs_base": round(p / base, 2) if base else None, "horizon_hours": 24,
                    "bad_outcome_definition": m["definition"]}
    return None


def _p99_evidence(flags, m):
    tested, untested = [], []
    for name in flags:
        f = m["flags"].get(name)
        if not f or f.get("n") is None or f["n"] < 20 or f.get("lift") is None:
            untested.append({"flag": name, "n": (f or {}).get("n", 0), "prior_weight": (f or {}).get("prior_weight")})
            continue
        lift = f["lift"]
        effect = "raises" if lift >= 1.1 else "no_support" if lift >= 0.9 else "contradicts"
        tested.append({"flag": name, "effect": effect, "lift": lift, "n": f["n"],
                       "bad_rate_pct": f.get("bad_rate_pct"), "blended_weight": f.get("blended_weight")})
    tested.sort(key=lambda x: -abs(x["lift"] - 1))
    return {"flags": tested, "untested": untested,
            "note": "lift = bad rate vs the same days' overall rate; flags overlap, so this is association, not cause."}


def _p99_reading(score, verdict, cal, ev, m, conf):
    out = []
    if cal:
        lo, hi = cal["ci95_pct"] or ("?", "?")
        out.append(f"Risk score {float(score):g} sits in the {cal['score_bucket']} range: {cal['p_bad_24h_pct']}% of "
                   f"{cal['based_on_n']} past tokens there were bad within 24h (95% CI {lo}-{hi}; base rate "
                   f"{cal['base_rate_pct']}%).")
    for f in ev["flags"][:3]:
        out.append(f"{f['flag']} {f['effect'].replace('_', ' ')} ({f['bad_rate_pct']}% bad, n={f['n']}, lift {f['lift']}).")
    if ev["untested"]:
        out.append("No outcome data yet for: " + ", ".join(u["flag"] for u in ev["untested"][:4]) + ".")
    r = ((m["horizons"].get(verdict) or {}).get("avg_return_pct_24h") or {})
    if r.get("value") is not None:
        out.append(f"Past '{verdict}' verdicts averaged {r['value']}% after 24h (n={r['n']}): the verdict measures "
                   "collapse risk, not upside.")
    if conf and conf.get("level") != "high":
        out.append(f"Data confidence is {conf['level']}: {', '.join(conf.get('reasons') or [])}.")
    return " ".join(out)


_build_prev_p99 = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_p99(client, mint, security, prefetched)
    try:
        if isinstance(result, dict):
            m = _p99_cached()
            if not m:
                result["calibration_status"] = "warming_up"
            else:
                score = float(result.get("risk_score") or 0)
                verdict = (((result.get("decision") or {}).get("verdict")) or result.get("verdict") or "").lower()
                cal = _p99_calibrate(score, m)
                ev = _p99_evidence(result.get("flags") or [], m)
                result["calibrated_risk"] = cal
                result["evidence"] = ev
                result["bad_rate_by_horizon"] = m["horizons"].get(verdict)
                result["reading"] = _p99_reading(score, verdict, cal, ev, m, result.get("decision_confidence"))
                order = result.get("si_reading_order")
                if isinstance(order, dict):
                    pr = order.setdefault("primary", [])
                    for k in ("calibrated_risk", "reading"):
                        if k not in pr:
                            pr.append(k)
    except Exception as e:
        print(f"[part99] {str(e)[:80]}")
    return result, status


@app.get("/calibration", tags=["accuracy"])
async def calibration():
    m = await _p99_refresh() or {}
    return {"version": VERSION, "ready": bool(m), "age_s": int(time.time() - _P99["ts"]) if m else None,
            "base_rate_pct": m.get("base"), "risk_to_p_bad_24h": m.get("table"),
            "bad_rate_by_verdict_horizon": m.get("horizons"),
            "flags": [{k: f.get(k) for k in ("flag", "n", "bad_rate_pct", "lift", "prior_weight", "blended_weight")}
                      for f in (m.get("flags") or {}).values()],
            "note": ("Empirical, from tokens people queried (selection-biased). Monotone-smoothed. "
                     "Association, not causation. Not financial advice.")}


print(f"[part99] v{VERSION} calibrated_risk + evidence + reading -> GET /calibration")

# --- part100 ---
# ---------- v2.78: Shadow outcome wire + fair-use + donate (reviewed) ----------
# B: after resolve_due, feed judged labels into on_outcome_for_si (shadow-avoid etc.)
#    - only ids that really left the "due" set, labelled once (SET NX guard)
#    - a failed/untrusted DexScreener answer NEVER becomes "bad": it is retried instead
#    - set P100_WIRE=0 to switch B off (use that if /stats/shadow-avoid judged already grows)
# C: fair-use copy on /support + /donate (free instance; optional SOL tips)
VERSION = "2.78.0"
app.version = VERSION
app.openapi_schema = None

import asyncio
import os
import time
from typing import Dict, Optional

from fastapi.responses import HTMLResponse, PlainTextResponse

# --- Public free-host tips (optional). Not required to use the API. ---
DONATE_SOL = "3iAVBvE4aU4A5DTKCqzu6jg79UfW6aEnqUD1pjfew18n"
DONATE_NOTE = (
    "TVibex402 is free and open source. If the public instance helps your agents, "
    "you can tip SOL to cover Render/RPC. Never required."
)
FAIR_USE_RPM = os.environ.get("FAIR_USE_RPM", "30")  # keep equal to the real limiter

# ---------------------------------------------------------------------------
# B) Wire outcomes into shadow + SI hooks
# ---------------------------------------------------------------------------
P100_WIRE = os.environ.get("P100_WIRE", "1").lower() not in ("0", "false", "off")
_P100_LABEL_TTL = 7 * 86400
_P100_RETRY: list = []  # [(snapshot, attempts)] when DexScreener could not be trusted
_SOL_DEFAULT = "So11111111111111111111111111111111111111112"


def _p100_val(x):
    return x.get("result") if isinstance(x, dict) else x


def _p100_pair(pairs, mint):
    cand = [p for p in pairs if (p.get("baseToken") or {}).get("address") == mint]
    if not cand:
        return None
    fn = globals().get("pick_best_pair")
    if callable(fn):
        try:
            return fn(cand, mint)
        except Exception:
            pass
    return max(cand, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))


async def _p100_fetch(client, mints, sol) -> Optional[Dict[str, Optional[dict]]]:
    """{mint: pair or None} only when the answer is trustworthy, else None.
    SOL rides along as a canary: if its pair is missing the answer is a rate limit /
    partial reply, not proof that a token's pair is gone."""
    out: Dict[str, Optional[dict]] = {}
    for i in range(0, len(mints), 29):
        chunk = mints[i:i + 29]
        ask = chunk if sol in chunk else chunk + [sol]
        try:
            r = await client.get("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(ask))
            if r.status_code != 200:
                return None
            pairs = (r.json() or {}).get("pairs") or []
        except Exception:
            return None
        if _p100_pair(pairs, sol) is None:
            return None
        for m in chunk:
            out[m] = _p100_pair(pairs, m)
    return out


_prev_resolve_due = resolve_due


async def resolve_due(client: "httpx.AsyncClient") -> int:
    if not P100_WIRE:
        return await _prev_resolve_due(client)
    snaps = []
    try:
        batch = int(globals().get("RESOLVE_BATCH") or 20)
        lim = min(max(batch * 2, 60), 150)
        got = await redis_pipe(client, [["ZRANGEBYSCORE", "due", "-inf", int(time.time()), "LIMIT", 0, lim]])
        ids = (got or [[]])[0] or []
        if ids:
            hashes = await redis_pipe(client, [["HGETALL", f"pred:{i}"] for i in ids])
            for i, h in zip(ids, hashes or []):
                d = to_dict(h)
                if d.get("mint"):
                    d["_id"] = i
                    snaps.append(d)
    except Exception as e:
        print(f"[part100] pre-resolve snap: {e}")

    n = await _prev_resolve_due(client)

    try:
        work = [(d, 0) for d in snaps]
        if snaps:  # keep only what the core resolver really took out of "due"
            left = await redis_pipe(client, [["ZSCORE", "due", d["_id"]] for d in snaps])
            if left and len(left) == len(snaps):
                work = [(d, 0) for d, z in zip(snaps, left) if _p100_val(z) is None]
            else:
                work = []
        work += _P100_RETRY
        _P100_RETRY.clear()
        if not work:
            return n

        horizon = int(globals().get("PRED_HORIZON_S") or 86400)
        now = int(time.time())
        work = [(d, a) for d, a in work if now - int(d.get("ts") or 0) <= horizon * 3]
        mints = sorted({d["mint"] for d, _ in work})
        if not mints:
            return n
        best = await _p100_fetch(client, mints, globals().get("SOL_MINT") or _SOL_DEFAULT)
        if best is None:
            for d, a in work:
                if a < 5 and len(_P100_RETRY) < 300:
                    _P100_RETRY.append((d, a + 1))
            print(f"[part100] label fetch untrusted, {len(work)} snapshot(s) queued for retry")
            return n

        bad_ret = float(globals().get("BAD_RETURN_PCT") or -50)
        bad_liq = float(globals().get("BAD_LIQ_RATIO") or 0.3)
        fn = globals().get("on_outcome_for_si")
        sa = globals().get("shadow_avoid_on_outcome")
        for d, _ in work:
            mint = d["mint"]
            guard = await redis_pipe(client, [["SET", f"si:lab:{d['_id']}", 1, "NX", "EX", _P100_LABEL_TTL]])
            if not (guard and _p100_val(guard[0])):
                continue  # this prediction was already labelled
            p0, l0 = float(d.get("price") or 0), float(d.get("liq") or 0)
            pair = best.get(mint)
            if pair is None:
                ret, liq_ratio = -100.0, 0.0
            else:
                try:
                    p1 = float(pair.get("priceUsd") or 0)
                    l1 = float((pair.get("liquidity") or {}).get("usd") or 0)
                except (TypeError, ValueError):
                    p1, l1 = 0.0, 0.0
                ret = (p1 / p0 - 1) * 100 if p0 > 0 else 0.0
                liq_ratio = l1 / l0 if l0 > 0 else 1.0
            bad = bool(ret <= bad_ret or liq_ratio <= bad_liq)
            meta = {"source": "part100_resolve"}
            try:
                if callable(fn):  # part93 wrapper already calls shadow_avoid_on_outcome
                    try:
                        await fn(client, mint, bad, meta)
                    except TypeError:
                        await fn(client, mint, bad)
                elif callable(sa):
                    await sa(client, mint, bad, meta)
            except Exception as e:
                print(f"[part100] outcome hook: {e}")
    except Exception as e:
        print(f"[part100] post-resolve labels: {e}")
    return n


# ---------------------------------------------------------------------------
# C) Fair use + donate (free product)
# ---------------------------------------------------------------------------
FAIR_USE = """
TVibex402 public instance — FREE, fair use
• About """ + FAIR_USE_RPM + """ requests/minute without a key (429 if exceeded)
• /signals batch: max 10 mints per call
• Cache the same mint 15–30s on the client
• Prefer GET /omni once over polling many small routes
• Heavy use: self-host from GitHub (track-record starts empty on your Redis)
• Not financial advice. Heuristics only.

Optional tips (never required) keep the public host online:
  SOL: """ + DONATE_SOL + """
"""


@app.get("/support", response_class=PlainTextResponse, tags=["product"])
async def support_fair_use():
    return FAIR_USE.strip() + "\n"


@app.get("/donate", tags=["product"])
async def donate_json():
    return {
        "free": True,
        "required": False,
        "asset": "SOL",
        "address": DONATE_SOL,
        "note": DONATE_NOTE,
        "fair_use": "/support",
        "self_host": "https://github.com/TVibex402/signal-api",
        "disclaimer": "Not financial advice. Donations are voluntary tips for hosting/RPC only.",
        "version": VERSION,
    }


@app.get("/donate.html", response_class=HTMLResponse, tags=["product"], include_in_schema=False)
async def donate_html():
    return f"""<!doctype html><html lang="en"><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>TVibex402 — free & tips</title>
<style>
body{{margin:0;font-family:system-ui,sans-serif;background:#070b12;color:#e8eef6;line-height:1.55}}
.wrap{{max-width:640px;margin:0 auto;padding:32px 16px}}
h1{{font-size:1.6rem;background:linear-gradient(120deg,#9945ff,#14f195);-webkit-background-clip:text;color:transparent}}
.card{{background:rgba(18,25,35,.85);border:1px solid rgba(34,48,66,.8);border-radius:14px;padding:18px;margin:16px 0}}
code{{word-break:break-all;color:#14f195}}
.muted{{color:#8b9bb4;font-size:.9rem}}
a{{color:#14f195}}
</style></head><body><div class=wrap>
<h1>Free for agents</h1>
<p class=muted>Open source · measured on <a href="/stats">/stats</a> · not financial advice.</p>
<div class=card>
<strong>Fair use</strong>
<pre style="white-space:pre-wrap;font-size:.85rem">{FAIR_USE.strip()}</pre>
</div>
<div class=card>
<strong>Optional SOL tip</strong>
<p class=muted>{DONATE_NOTE}</p>
<p><code>{DONATE_SOL}</code></p>
</div>
<p class=muted><a href="/agents">/agents</a> · <a href="/support">/support</a> ·
<a href="https://github.com/TVibex402/signal-api">GitHub</a></p>
</div></body></html>"""


# part94 already owns GET /agents/snippets (first registered wins), so replace that route.
if globals().get("AGENT_SNIPPETS"):
    if callable(globals().get("_drop_routes")):
        _drop_routes({"/agents/snippets"})

    @app.get("/agents/snippets", response_class=PlainTextResponse, tags=["product"])
    async def agents_snippets_v100():
        text = AGENT_SNIPPETS.rstrip()
        if "Fair use" not in text:
            text += (
                "\n\n## Fair use (public host)\n"
                f"Free. About {FAIR_USE_RPM} req/min. Batch max 10. Cache mint 15–30s. "
                "429 = slow down or self-host.\n"
                f"Optional SOL tip (never required): {DONATE_SOL}\n"
                "Not financial advice.\n"
            )
        return text


ENV_EXAMPLE = """# .env.example — copy to .env, never commit real secrets
REDIS_URL=
SOLANA_RPC_URL=
JUPITER_API_KEY=
OPERATOR_SECRET=
PRED_ENABLED=true
# Optional tuning
# SI_RES_TEMP=1.25
# SI_RES_RISK_FLOOR=0.18
# P98_ENABLED=1
# P100_WIRE=1
# FAIR_USE_RPM=30
"""


@app.get("/env.example", response_class=PlainTextResponse, tags=["product"], include_in_schema=False)
async def env_example_file():
    return ENV_EXAMPLE


print(f"[part100] v{VERSION} resolve_due→on_outcome (wire={'on' if P100_WIRE else 'off'}) · /support · /donate · /env.example")

# --- part101 ---
# ---------- v2.79: Donate banner on top of the homepage ----------
# A slim bar right under <body> on GET / (add pages with DONATE_BANNER_PATHS="/,/docs").
# Works without touching the page code: a middleware injects it into the HTML.
# If anything fails the original page is returned unchanged. DONATE_BANNER=0 turns it off.
# Needs part100 (DONATE_SOL).
VERSION = "2.79.0"
app.version = VERSION
app.openapi_schema = None

import os
import re

from fastapi.responses import Response

_P101_ON = os.environ.get("DONATE_BANNER", "1").lower() not in ("0", "false", "off")
_P101_PATHS = {p.strip() for p in os.environ.get("DONATE_BANNER_PATHS", "/").split(",") if p.strip()}
_P101_ADDR = globals().get("DONATE_SOL") or ""
_P101_SHORT = (_P101_ADDR[:4] + "…" + _P101_ADDR[-4:]) if len(_P101_ADDR) > 12 else _P101_ADDR

_P101_BANNER = (
    '<style>'
    '.p101d{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;justify-content:center;'
    'padding:8px 36px 8px 12px;position:relative;font:13px/1.4 system-ui,sans-serif;color:#c7d2fe;'
    'background:rgba(99,102,241,.14);border-bottom:1px solid rgba(99,102,241,.4);text-align:center}'
    '.p101d code{color:#a5f3c4;font-family:ui-monospace,monospace}'
    '.p101d a{color:#c7d2fe;text-decoration:underline}'
    '.p101d button{font:inherit;color:#fff;background:#6366f1;border:0;border-radius:8px;padding:3px 10px;cursor:pointer}'
    '.p101d .x{position:absolute;right:6px;top:3px;background:none;color:#c7d2fe;font-size:18px;padding:2px 8px}'
    '</style>'
    '<div class="p101d" id="p101-donate">'
    '<span>Free &amp; open source. Optional SOL tip:</span>'
    '<code>' + _P101_SHORT + '</code>'
    '<button type="button" data-a="' + _P101_ADDR + '" onclick="var b=this;navigator.clipboard.writeText(b.dataset.a)'
    '.then(function(){b.textContent=\'Copied ✓\';setTimeout(function(){b.textContent=\'Copy\'},1500)})'
    '.catch(function(){prompt(\'Copy address\',b.dataset.a)})">Copy</button>'
    '<a href="/donate.html">Details</a>'
    '<button type="button" class="x" aria-label="Close" onclick="this.parentNode.remove()">×</button>'
    '</div>'
)


def _p101_inject(html: str) -> str:
    if "p101-donate" in html:
        return html
    m = re.search(r"<body[^>]*>", html, re.I)
    return html if not m else html[:m.end()] + _P101_BANNER + html[m.end():]


if _P101_ON and _P101_ADDR:
    try:
        @app.middleware("http")
        async def _p101_banner_mw(request, call_next):
            resp = await call_next(request)
            if (request.method != "GET" or request.url.path not in _P101_PATHS or resp.status_code != 200
                    or "text/html" not in resp.headers.get("content-type", "")):
                return resp
            body = b""
            async for chunk in resp.body_iterator:
                body += chunk
            keep = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
            out = body
            try:
                new = _p101_inject(body.decode("utf-8")).encode("utf-8")
                if new != body:
                    out = new
                    keep = {k: v for k, v in keep.items() if k.lower() != "content-encoding"}
            except Exception as e:
                print(f"[part101] banner skipped: {str(e)[:80]}")
            return Response(content=out, status_code=200, headers=keep)
    except Exception as e:
        print(f"[part101] middleware not added: {e}")

print(f"[part101] v{VERSION} donate banner on {sorted(_P101_PATHS)} (on={_P101_ON and bool(_P101_ADDR)})")

# --- part102 ---
# ---------- v2.80: Brand + motion (logo avatar, animated site) ----------
# Serves /logo.png /favicon.ico /favicon.png /apple-touch-icon.png /og.png from the brand files
# (folder brand/ or next to main.py; if a file is missing a built-in SVG logo is used).
# A middleware adds favicon/share tags, a header logo, soft animated background, scroll
# reveal, number count-up and hover polish to HTML pages. Any failure returns the original page.
# Env: P102_ON=0 turns it off, P102_SKIP="/docs,/redoc" lists pages left untouched, BRAND_DIR=path
VERSION = "2.80.0"
app.version = VERSION
app.openapi_schema = None

import os
import re

from fastapi.responses import Response

_P102_ON = os.environ.get("P102_ON", "1").lower() not in ("0", "false", "off")
_P102_SKIP = {p.strip() for p in os.environ.get("P102_SKIP", "/docs,/redoc").split(",") if p.strip()}
_P102_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or "."))
_P102_DIRS = [d for d in (os.environ.get("BRAND_DIR"), os.path.join(_P102_HERE, "brand"), _P102_HERE) if d]

_P102_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs>'
    '<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e5e7eb"/>'
    '<stop offset=".45" stop-color="#8b9bd6"/><stop offset=".7" stop-color="#6ee7c8"/>'
    '<stop offset="1" stop-color="#9ca3af"/></linearGradient></defs>'
    '<rect x="8" y="8" width="84" height="84" rx="18" fill="url(#g)"/>'
    '<rect x="14" y="14" width="72" height="72" rx="13" fill="#f6f6f6"/>'
    '<rect x="31" y="27" width="38" height="10" fill="#000"/><rect x="45" y="27" width="10" height="36" fill="#000"/>'
    '<path d="M24 67Q37 55 50 66T76 66" fill="none" stroke="#000" stroke-width="5" stroke-linecap="round"/></svg>'
)
_P102_FILES = {}


def _p102_load(name):
    if name in _P102_FILES:
        return _P102_FILES[name]
    for d in _P102_DIRS:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            try:
                with open(p, "rb") as fh:
                    _P102_FILES[name] = fh.read()
                return _P102_FILES[name]
            except Exception:
                pass
    return None


_P102_ROUTES = {"/logo.png": ("logo.png",), "/favicon.ico": ("icon-192.png", "logo.png"),
                "/favicon.png": ("icon-192.png", "logo.png"), "/apple-touch-icon.png": ("icon-192.png", "logo.png"),
                "/og.png": ("og.png",)}
if callable(globals().get("_drop_routes")):
    _drop_routes(set(_P102_ROUTES))


def _p102_route(path, names):
    async def handler():
        for n in names:
            data = _p102_load(n)
            if data:
                return Response(content=data, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
        if path == "/og.png":
            return Response(status_code=404)
        return Response(content=_P102_SVG, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})
    app.get(path, include_in_schema=False)(handler)


for _p, _n in _P102_ROUTES.items():
    _p102_route(_p, _n)

_P102_CSS = """
html{scroll-behavior:smooth}
.p102-bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden;opacity:.55}
.p102-bg i{position:absolute;width:60vmax;height:60vmax;border-radius:50%;will-change:transform}
.p102-bg i:nth-child(1){left:-22vmax;top:-26vmax;background:radial-gradient(circle,rgba(99,102,241,.45),transparent 62%);animation:p102a 26s ease-in-out infinite alternate}
.p102-bg i:nth-child(2){right:-28vmax;top:8vh;background:radial-gradient(circle,rgba(168,85,247,.38),transparent 62%);animation:p102b 32s ease-in-out infinite alternate}
.p102-bg i:nth-child(3){left:12vw;bottom:-38vmax;background:radial-gradient(circle,rgba(20,241,149,.2),transparent 62%);animation:p102a 38s ease-in-out infinite alternate-reverse}
.p102-bg b{position:absolute;inset:0;background:radial-gradient(420px circle at var(--mx,50%) var(--my,28%),rgba(129,140,248,.16),transparent 60%)}
@keyframes p102a{to{transform:translate(16vmax,12vmax) scale(1.18)}}
@keyframes p102b{to{transform:translate(-14vmax,18vmax) scale(.9)}}
.p102-bar{position:fixed;left:0;top:0;height:3px;width:100%;transform-origin:0 50%;transform:scaleX(0);z-index:2147483000;background:linear-gradient(90deg,#6366f1,#a855f7,#14f195);pointer-events:none}
.p102-logo{width:36px;height:36px;border-radius:10px;flex:none;filter:drop-shadow(0 0 8px rgba(129,140,248,.6));animation:p102g 4.5s ease-in-out infinite;transition:transform .3s}
.p102-logo:hover{transform:rotate(-6deg) scale(1.1)}
@keyframes p102g{50%{filter:drop-shadow(0 0 16px rgba(168,85,247,.85))}}
.p102-r{opacity:0;transform:translateY(16px);transition:opacity .6s ease,transform .6s ease}
.p102-r.p102-in{opacity:1;transform:none}
.p102-shine{background-size:220% 100%!important;animation:p102s 8s ease-in-out infinite alternate}
@keyframes p102s{from{background-position:0 0}to{background-position:100% 0}}
a,button,input{transition:transform .18s,box-shadow .18s,border-color .18s,background-color .18s,color .18s}
button:hover,.btn:hover,a[class*="btn"]:hover,a[class*="button"]:hover{transform:translateY(-2px);box-shadow:0 10px 26px rgba(99,102,241,.38)}
button:active,.btn:active,a[class*="btn"]:active{transform:translateY(0)}
input:focus,textarea:focus{outline:none;border-color:#818cf8!important;box-shadow:0 0 0 3px rgba(99,102,241,.35)}
::selection{background:rgba(99,102,241,.45)}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}.p102-bg i,.p102-logo,.p102-shine{animation:none!important}.p102-r{opacity:1!important;transform:none!important;transition:none!important}.p102-bar{display:none}}
"""

_P102_JS = r"""
(function(){try{
var d=document,de=d.documentElement,B=d.body;
var reduce=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
function safe(f){try{f()}catch(e){}}
safe(function(){
 var w=d.createTreeWalker(B,NodeFilter.SHOW_TEXT),n,i=0,host=null;
 while((n=w.nextNode())&&i++<600){var p=n.parentElement;
  if(p&&/^\s*TVibe/.test(n.nodeValue)&&!p.closest('script,style,h1,h2,h3,p,li,pre,code,.p101d')){host=p;break}}
 if(!host)return;
 var a=host.closest('a')||host;
 if(a.querySelector('.p102-logo'))return;
 var im=d.createElement('img');im.src='/logo.png';im.alt='TVibex402 logo';im.className='p102-logo';im.width=36;im.height=36;
 a.insertBefore(im,a.firstChild);a.style.display='inline-flex';a.style.alignItems='center';a.style.gap='10px';
});
var bg=d.createElement('div');bg.className='p102-bg';bg.setAttribute('aria-hidden','true');bg.innerHTML='<i></i><i></i><i></i><b></b>';
B.insertBefore(bg,B.firstChild);
var bar=d.createElement('div');bar.className='p102-bar';B.appendChild(bar);
var tk=0;function onS(){if(tk)return;tk=requestAnimationFrame(function(){tk=0;var h=de.scrollHeight-innerHeight;bar.style.transform='scaleX('+(h>0?Math.min(1,scrollY/h):0)+')'})}
addEventListener('scroll',onS,{passive:true});onS();
if(!reduce&&matchMedia('(hover:hover) and (pointer:fine)').matches){var px=0;
 addEventListener('pointermove',function(e){if(px)return;px=requestAnimationFrame(function(){px=0;bg.style.setProperty('--mx',e.clientX+'px');bg.style.setProperty('--my',e.clientY+'px')})},{passive:true})}
safe(function(){d.querySelectorAll('h1,h1 *').forEach(function(e){var c=getComputedStyle(e),k=c.webkitBackgroundClip||c.backgroundClip;if(k==='text')e.classList.add('p102-shine')})});
if(reduce||!('IntersectionObserver' in window)){de.classList.add('p102-on');return}
safe(function(){
 var sel='main>*,section,article,form,[class*="card"],[class*="panel"],[class*="hero"]>*,h1,h2,h3,table,pre';
 var all=[].slice.call(d.querySelectorAll(sel)).filter(function(e){return !e.closest('header,nav,footer,.p101d,.p102-bg,script,style')});
 var ok=all.filter(function(e){return all.filter(function(o){return o!==e&&e.contains(o)}).length<3});
 var els=ok.filter(function(e){return !ok.some(function(o){return o!==e&&o.contains(e)})}).slice(0,60);
 var io=new IntersectionObserver(function(es){es.forEach(function(x){if(!x.isIntersecting)return;var t=x.target;t.classList.add('p102-in');io.unobserve(t);
  setTimeout(function(){t.classList.remove('p102-r','p102-in');t.style.transitionDelay=''},1100)})},{threshold:.08});
 els.forEach(function(e,i){e.classList.add('p102-r');e.style.transitionDelay=Math.min(i,6)*70+'ms';io.observe(e)});
 setTimeout(function(){els.forEach(function(e){e.classList.add('p102-in')})},3500);
});
function fmt(v,dec,c){var s=dec?v.toFixed(dec):String(Math.round(v));return c?Number(s).toLocaleString('en-US',{minimumFractionDigits:dec,maximumFractionDigits:dec}):s}
function wrap(tn,re){var m=re.exec(tn.nodeValue);if(!m)return null;var num=m[2],val=parseFloat(num.replace(/,/g,''));
 if(!(val>=10||m[3]))return null;
 var sp=d.createElement('span');sp.className='p102-n';sp.textContent=num;sp.dataset.v=val;sp.dataset.dec=(num.split('.')[1]||'').length;sp.dataset.c=(num.indexOf(',')>-1||val>=1000)?'1':'0';
 var p=tn.parentNode;p.insertBefore(d.createTextNode(m[1]),tn);p.insertBefore(sp,tn);tn.nodeValue=tn.nodeValue.slice(m[0].length);return sp}
safe(function(){
 var cio=new IntersectionObserver(function(es){es.forEach(function(x){if(!x.isIntersecting)return;cio.unobserve(x.target);var s=x.target,v=+s.dataset.v,dec=+s.dataset.dec,c=s.dataset.c==='1',t0=performance.now();
  (function f(t){var k=Math.min(1,(t-t0)/1100),e=1-Math.pow(1-k,3);s.textContent=fmt(k<1?v*e:v,dec,c);if(k<1)requestAnimationFrame(f)})(t0)})},{threshold:.4});
 var re1=/^(\s*)(\d[\d,]*(?:\.\d+)?)(?=(%)|\s|$)/,re2=/^(\s*)(\d+(?:\.\d+)?)(?=(%))/,left=14;
 d.querySelectorAll('strong,b,[class*="stat"],[class*="metric"],[class*="count"]').forEach(function(e){
  if(left<=0||e.closest('pre,code,table,textarea,script,style,.p101d')||!e.firstChild||e.firstChild.nodeType!==3)return;
  var s=wrap(e.firstChild,re1);if(!s)return;left--;cio.observe(s);s.textContent=fmt(0,+s.dataset.dec,s.dataset.c==='1');
  var nx=e.nextSibling;if(nx&&nx.nodeType===3){var s2=wrap(nx,re2);if(s2){cio.observe(s2);s2.textContent=fmt(0,+s2.dataset.dec,s2.dataset.c==='1')}}});
});
de.classList.add('p102-on');
}catch(e){}})();
"""


def _p102_strip_icons(html):
    def fn(m):
        tag = m.group(0)
        return "" if re.search(r"\brel\s*=\s*[\"']?(?:shortcut\s+icon|icon|apple-touch-icon)\b", tag, re.I) else tag
    return re.sub(r"<link\b(?:\"[^\"]*\"|'[^']*'|[^>\"'])*>", fn, html, flags=re.I)


def _p102_head_tags(html, base):
    png = _p102_load("icon-192.png") or _p102_load("logo.png")
    tags = [f'<link rel="icon" type="{"image/png" if png else "image/svg+xml"}" href="/favicon.png">',
            '<link rel="apple-touch-icon" href="/apple-touch-icon.png">']
    if 'name="theme-color"' not in html:
        tags.append('<meta name="theme-color" content="#07070f">')
    if "og:image" not in html and _p102_load("og.png"):
        u = base + "/og.png"
        tags += [f'<meta property="og:image" content="{u}">', '<meta property="og:image:width" content="1200">',
                 '<meta property="og:image:height" content="630">',
                 '<meta name="twitter:card" content="summary_large_image">', f'<meta name="twitter:image" content="{u}">']
    return "".join(tags)


def _p102_inject(html, base):
    html = _p102_strip_icons(html)
    head = _p102_head_tags(html, base) + '<style id="p102-css">' + _P102_CSS + "</style>"
    m = re.search(r"</head>", html, re.I)
    if m:
        html = html[:m.start()] + head + html[m.start():]
    else:
        m = re.search(r"<body[^>]*>", html, re.I)
        if not m:
            return html
        html = html[:m.end()] + head + html[m.end():]
    js = '<script id="p102-js">' + _P102_JS + "</script>"
    i = html.lower().rfind("</body>")
    return html[:i] + js + html[i:] if i != -1 else html + js


if _P102_ON:
    try:
        @app.middleware("http")
        async def _p102_mw(request, call_next):
            resp = await call_next(request)
            if (request.method != "GET" or resp.status_code != 200 or request.url.path in _P102_SKIP
                    or "text/html" not in resp.headers.get("content-type", "")):
                return resp
            body = b""
            async for chunk in resp.body_iterator:
                body += chunk
            keep = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
            out = body
            try:
                html = body.decode("utf-8")
                if "p102-css" not in html and "swagger-ui" not in html:
                    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
                    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
                    new = _p102_inject(html, f"{proto}://{host}").encode("utf-8")
                    if new != body:
                        out = new
                        keep = {k: v for k, v in keep.items() if k.lower() != "content-encoding"}
            except Exception as e:
                print(f"[part102] skipped: {str(e)[:80]}")
            return Response(content=out, status_code=200, headers=keep)
    except Exception as e:
        print(f"[part102] middleware not added: {e}")

print(f"[part102] v{VERSION} brand+motion (on={_P102_ON}) logo files: "
      f"{'found' if _p102_load('logo.png') else 'missing -> SVG fallback'}")

# --- part103 ---
# ---------- v2.82: Agent-first home + donate + fair-use (complete) ----------
VERSION = "2.82.0"
app.version = VERSION
app.openapi_schema = None

from fastapi.responses import HTMLResponse, PlainTextResponse

DONATE_SOL = "3iAVBvE4aU4A5DTKCqzu6jg79UfW6aEnqUD1pjfew18n"
BASE = "https://signal-api-24q4.onrender.com"
DONATE_NOTE = (
    "TVibex402 is free and open source. If the public instance helps your agents, "
    "you can tip SOL to cover Render/RPC. Never required."
)

FAIR_USE = f"""TVibex402 public instance — FREE, fair use
• About 30 requests/minute without a key (429 if exceeded)
• /signals batch: max 10 mints per call
• Cache the same mint 15–30s on the client
• Prefer GET /omni once over polling many small routes
• Heavy use: self-host from GitHub (your track-record starts empty)
• Not financial advice. Heuristics only.

Optional SOL tip (never required):
  {DONATE_SOL}
"""

HOME_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#070b12">
<meta name="color-scheme" content="dark">
<title>TVibex402 — Solana signals for AI agents</title>
<meta name="description" content="Free Solana token signals for AI agents. One call: verdict, reasons, measured track record. Not financial advice.">
<meta property="og:type" content="website">
<meta property="og:title" content="TVibex402 — Solana signals for AI agents">
<meta property="og:description" content="Verdict + reasons in one JSON. Free, open source, accuracy public on /stats.">
<meta property="og:image" content="{BASE}/og.svg">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>
:root {{
  --bg:#070b12; --card:rgba(15,22,34,.92); --line:rgba(40,56,78,.9);
  --text:#e8eef6; --muted:#8b9bb4; --a:#14f195; --b:#9945ff; --c:#6366f1;
}}
* {{ box-sizing:border-box; margin:0; padding:0 }}
body {{
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.55;
  min-height: 100vh;
}}
.bg {{ position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }}
.bg span {{
  position: absolute; width: 55vmax; height: 55vmax; border-radius: 50%;
  filter: blur(10px); opacity: .42;
}}
.bg span:nth-child(1) {{
  left: -20vmax; top: -25vmax;
  background: radial-gradient(circle, rgba(153,69,255,.55), transparent 65%);
}}
.bg span:nth-child(2) {{
  right: -25vmax; top: 18vh;
  background: radial-gradient(circle, rgba(20,241,149,.28), transparent 65%);
}}
.bg span:nth-child(3) {{
  left: 18vw; bottom: -35vmax;
  background: radial-gradient(circle, rgba(99,102,241,.38), transparent 65%);
}}
.wrap {{ position: relative; z-index: 1; max-width: 960px; margin: 0 auto; padding: 0 1.25rem 4rem }}
nav {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 1.1rem 0; border-bottom: 1px solid var(--line); flex-wrap: wrap; gap: .6rem;
}}
.logo {{ font-weight: 800; letter-spacing: -.03em; font-size: 1.15rem }}
.logo em {{
  font-style: normal;
  background: linear-gradient(120deg, var(--b), var(--a));
  -webkit-background-clip: text; background-clip: text; color: transparent;
}}
nav a {{ color: var(--muted); text-decoration: none; margin-left: 1rem; font-size: .92rem }}
nav a:hover {{ color: var(--text) }}
.hero {{ text-align: center; padding: 3.2rem 0 2rem }}
.badge {{
  display: inline-block; font-size: .72rem; letter-spacing: .07em; text-transform: uppercase;
  color: var(--a); border: 1px solid rgba(20,241,149,.35); padding: .35rem .75rem;
  border-radius: 999px; margin-bottom: 1rem;
}}
h1 {{
  font-size: clamp(2rem, 5.5vw, 3.1rem); font-weight: 800; letter-spacing: -.04em;
  line-height: 1.12; margin-bottom: 1rem;
}}
h1 span {{
  background: linear-gradient(135deg, #a78bfa, #14f195);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}}
.sub {{ color: var(--muted); font-size: 1.08rem; max-width: 560px; margin: 0 auto 1.6rem }}
.sub a {{ color: var(--a) }}
.cta {{ display: flex; flex-wrap: wrap; gap: .7rem; justify-content: center }}
.btn {{
  display: inline-block; padding: .75rem 1.35rem; border-radius: .75rem;
  font-weight: 600; text-decoration: none; font-size: .95rem;
}}
.btn-p {{ background: linear-gradient(135deg, var(--b), var(--c)); color: #fff }}
.btn-g {{ background: rgba(20,241,149,.12); color: var(--a); border: 1px solid rgba(20,241,149,.35) }}
.btn-o {{ border: 1px solid var(--line); color: var(--text) }}
.grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem; margin: 2rem 0;
}}
.card {{
  background: var(--card); border: 1px solid var(--line); border-radius: 1rem;
  padding: 1.15rem 1.2rem;
}}
.card h3 {{ font-size: .95rem; margin-bottom: .4rem }}
.card p {{ color: var(--muted); font-size: .88rem }}
.card code {{ color: var(--a); font-size: .8rem }}
pre {{
  background: #0c121c; border: 1px solid var(--line); border-radius: .85rem;
  padding: 1rem 1.1rem; overflow-x: auto; font-size: .82rem; color: #c7d2fe;
  margin: 1rem 0 0;
}}
section {{ margin: 2.25rem 0 }}
section h2 {{ font-size: 1.15rem; margin-bottom: .75rem }}
.muted {{ color: var(--muted); font-size: .9rem }}
.donate-box {{
  background: linear-gradient(145deg, rgba(153,69,255,.14), rgba(20,241,149,.08));
  border: 1px solid rgba(20,241,149,.32);
  border-radius: 1rem; padding: 1.25rem 1.3rem;
}}
.sol {{
  word-break: break-all; color: var(--a);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .85rem; margin-top: .65rem; user-select: all;
}}
.copy-row {{ margin-top: .75rem; display: flex; flex-wrap: wrap; gap: .5rem; align-items: center }}
.copy-btn {{
  cursor: pointer; border: 1px solid rgba(20,241,149,.4); background: rgba(20,241,149,.1);
  color: var(--a); border-radius: .5rem; padding: .4rem .85rem; font-size: .85rem; font-weight: 600;
}}
footer {{
  margin-top: 3rem; padding-top: 1.25rem; border-top: 1px solid var(--line);
  color: var(--muted); font-size: .85rem; text-align: center;
}}
footer a {{ color: var(--a) }}
</style>
</head>
<body>
<div class="bg" aria-hidden="true"><span></span><span></span><span></span></div>
<div class="wrap">
  <nav>
    <div class="logo">TVibe<em>x402</em></div>
    <div>
      <a href="/agents">Agents</a>
      <a href="/stats">Stats</a>
      <a href="/docs">API</a>
      <a href="#donate">Donate</a>
      <a href="https://github.com/TVibex402/signal-api">GitHub</a>
    </div>
  </nav>

  <header class="hero">
    <div class="badge">Free · Open source · Measured in public</div>
    <h1>Solana token signals<br>for <span>AI agents</span></h1>
    <p class="sub">
      One request → verdict, reasons, and context.
      Track record is public on <a href="/stats">/stats</a>.
      Heuristics only — not financial advice.
    </p>
    <div class="cta">
      <a class="btn btn-p" href="/omni?mint=So11111111111111111111111111111111111111112">Try /omni</a>
      <a class="btn btn-g" href="/stats">Live accuracy</a>
      <a class="btn btn-o" href="/mcp">MCP</a>
    </div>
  </header>

  <div class="grid">
    <div class="card">
      <h3>Primary call</h3>
      <p><code>GET /omni?mint=…</code></p>
      <p>Verdict + decision block agents should trust first.</p>
    </div>
    <div class="card">
      <h3>Prove it</h3>
      <p><code>GET /stats</code></p>
      <p>Precision / recall on judged outcomes — not marketing claims.</p>
    </div>
    <div class="card">
      <h3>MCP</h3>
      <p><code>omni(mint)</code></p>
      <p>Wire into Cursor, Claude, or your agent runtime.</p>
    </div>
    <div class="card">
      <h3>Self-host</h3>
      <p><code>github.com/TVibex402/signal-api</code></p>
      <p>Same code. Your Redis starts its own track record.</p>
    </div>
  </div>

  <section>
    <h2>Quick start</h2>
    <pre>curl -s "{BASE}/omni?mint=So11111111111111111111111111111111111111112" | jq .decision</pre>
    <p class="muted" style="margin-top:.75rem">
      Batch: <code>/signals?mints=a,b,c&amp;view=compact</code> (max 10).
      Cache the same mint 15–30s.
    </p>
  </section>

  <section>
    <h2>Fair use</h2>
    <div class="card">
      <p class="muted">
        Public host is <strong style="color:var(--text)">free</strong>.
        \~30 req/min without a key · batch max 10 · please cache.
        Heavy traffic → self-host or slow down on HTTP 429.
        Full text: <a href="/support" style="color:var(--a)">/support</a>
      </p>
    </div>
  </section>

  <section id="donate">
    <h2>Optional tip (never required)</h2>
    <div class="donate-box">
      <p class="muted">{DONATE_NOTE}</p>
      <p class="sol" id="sol-addr">{DONATE_SOL}</p>
      <div class="copy-row">
        <button type="button" class="copy-btn"
          onclick="navigator.clipboard.writeText('{DONATE_SOL}').then(()=>{{this.textContent='Copied'}}).catch(()=>{{}})">
          Copy address
        </button>
        <a class="btn btn-o" style="padding:.4rem .85rem;font-size:.85rem" href="/donate">/donate JSON</a>
      </div>
    </div>
  </section>

  <footer>
    <p>Not financial advice. Heuristics for agents and research.</p>
    <p style="margin-top:.4rem">
      <a href="/support">/support</a> ·
      <a href="/agents">/agents</a> ·
      <a href="/llms.txt">llms.txt</a> ·
      <a href="https://github.com/TVibex402/signal-api">source</a>
    </p>
  </footer>
</div>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home_v282():
    return HOME_HTML


@app.get("/donate", tags=["product"])
async def donate_json():
    return {{
        "free": True,
        "required": False,
        "asset": "SOL",
        "address": DONATE_SOL,
        "note": DONATE_NOTE,
        "fair_use": "/support",
        "self_host": "https://github.com/TVibex402/signal-api",
        "disclaimer": "Not financial advice. Donations are voluntary tips for hosting/RPC only.",
        "version": VERSION,
    }}


@app.get("/donate.html", response_class=HTMLResponse, tags=["product"], include_in_schema=False)
async def donate_html():
    return f"""<!doctype html><html lang="en"><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Donate — TVibex402</title>
<style>
body{{margin:0;font-family:system-ui,sans-serif;background:#070b12;color:#e8eef6;line-height:1.55}}
.w{{max-width:560px;margin:0 auto;padding:32px 16px}}
h1{{font-size:1.5rem;background:linear-gradient(120deg,#9945ff,#14f195);-webkit-background-clip:text;color:transparent}}
.card{{background:rgba(15,22,34,.9);border:1px solid rgba(40,56,78,.9);border-radius:14px;padding:18px;margin-top:16px}}
code{{word-break:break-all;color:#14f195}} a{{color:#14f195}} .m{{color:#8b9bb4;font-size:.9rem}}
</style></head><body><div class=w>
<h1>Optional SOL tip</h1>
<p class=m>{DONATE_NOTE}</p>
<div class=card><code>{DONATE_SOL}</code></div>
<p class=m style="margin-top:16px"><a href="/">Home</a> · <a href="/support">Fair use</a></p>
</div></body></html>"""


@app.get("/support", response_class=PlainTextResponse, tags=["product"])
async def support_fair_use():
    return FAIR_USE.strip() + "\\n"


print(f"[part103] v{{VERSION}} home+donate+support → GET / · /donate · /support")

# --- part104 ---
# ---------- v2.84: TVibe home - X link, inline mint check (no raw JSON), color-coded result ----------
VERSION = "2.87.0"
app.version = VERSION
app.openapi_schema = None

from fastapi.responses import HTMLResponse, PlainTextResponse

BRAND = "TVibe Signal"
DONATE_SOL = "3iAVBvE4aU4A5DTKCqzu6jg79UfW6aEnqUD1pjfew18n"
BASE = "https://signal-api-24q4.onrender.com"
GITHUB_URL = "https://github.com/TVibex402/signal-api"
X_URL = "https://x.com/realTVibe"
DONATE_NOTE = (
    f"{BRAND} is free and open source. If the public instance helps your agents, "
    "you can tip SOL to cover hosting & RPC. Never required."
)
FAIR_USE = f"""{BRAND} public instance - FREE, fair use
- About 30 requests/minute without a key (429 if exceeded)
- /signals batch: max 10 mints per call
- Cache the same mint 15-30s on the client
- Prefer GET /omni once over polling many small routes
- Heavy use: self-host from GitHub (your track-record starts empty)
- Not financial advice. Heuristics only.

Optional SOL tip (never required):
  {DONATE_SOL}
"""

# Plain (non f-string) blocks: no need to double the braces here.
CHECK_CSS = r"""
body{background-image:linear-gradient(rgba(255,255,255,.022) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.022) 1px,transparent 1px);background-size:46px 46px;background-position:center top}
nav{position:sticky;top:0;z-index:30;background:rgba(7,11,18,.72);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)}
nav a{margin-left:0;padding:.38rem .65rem;border-radius:.6rem}
nav a:hover{background:rgba(255,255,255,.05)}
.navlinks{display:flex;gap:.2rem;align-items:center;flex-wrap:wrap}
nav .pill{display:inline-flex;align-items:center;gap:.4rem;border:1px solid var(--line);background:rgba(15,22,34,.75);color:var(--text);margin-left:.25rem}
nav .pill:hover{border-color:var(--a);background:rgba(20,241,149,.07)}
.ic{width:15px;height:15px;fill:currentColor;flex:none}
@media(max-width:600px){nav{flex-direction:column;align-items:flex-start}.navlinks{width:100%;flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;padding-bottom:.15rem}.navlinks::-webkit-scrollbar{display:none}.navlinks a{white-space:nowrap}}
footer a.fx{display:inline-flex;align-items:center;gap:.3rem}
.hero h1{letter-spacing:-.045em}
.check{max-width:720px;background:linear-gradient(var(--card),var(--card)) padding-box,linear-gradient(135deg,rgba(153,69,255,.7),rgba(20,241,149,.55)) border-box;border:1px solid transparent;box-shadow:0 24px 60px -24px rgba(99,102,241,.45)}
.check h3{font-size:1.05rem}
.check form{flex-wrap:nowrap}
.check form .btn{padding:.7rem 1.05rem;white-space:nowrap}
.check input:focus{outline:none;border-color:var(--a);box-shadow:0 0 0 3px rgba(20,241,149,.12)}
.check form button:disabled{opacity:.6;cursor:wait}
.tryrow{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin-top:.7rem;font-size:.8rem;color:var(--muted)}
.r-try{cursor:pointer;border:1px solid var(--line);background:rgba(10,18,32,.8);color:var(--text);border-radius:999px;padding:.25rem .7rem;font-size:.78rem}
.r-try:hover{border-color:var(--a);color:var(--a)}
.strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.6rem;margin:1.2rem 0}
.strip div{border:1px solid var(--line);background:rgba(15,22,34,.6);border-radius:.8rem;padding:.65rem .85rem}
.strip b{display:block;font-size:.92rem}
.strip span{font-size:.78rem;color:var(--muted)}
.card{transition:border-color .2s}
.card:hover{border-color:rgba(20,241,149,.4)}
#out{margin-top:1rem;text-align:left}
.r-load{display:flex;align-items:center;gap:.6rem;color:var(--muted);font-size:.88rem;padding:.6rem .2rem}
.r-spin{width:18px;height:18px;border:2px solid var(--line);border-top-color:var(--a);border-radius:50%;animation:rsp .8s linear infinite;flex:none}
@keyframes rsp{to{transform:rotate(360deg)}}
.r-err{border:1px solid #6e2523;background:rgba(46,17,18,.8);color:#ffb4b0;border-radius:.75rem;padding:.7rem .9rem;font-size:.88rem}
.res{animation:rin .35s ease both}
@keyframes rin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.r-hero{display:flex;gap:1.1rem;align-items:center;border-radius:1rem;padding:1.1rem;border:1px solid var(--line);background:rgba(17,27,43,.9)}
.r-hero.ok{border-color:rgba(20,241,149,.45);background:linear-gradient(135deg,rgba(20,241,149,.14),rgba(15,22,34,.9))}
.r-hero.warn{border-color:rgba(245,183,59,.5);background:linear-gradient(135deg,rgba(245,183,59,.14),rgba(15,22,34,.9))}
.r-hero.bad{border-color:rgba(242,86,79,.55);background:linear-gradient(135deg,rgba(242,86,79,.15),rgba(15,22,34,.9))}
.r-ring{position:relative;width:88px;height:88px;flex:none}
.r-ring svg{width:88px;height:88px;transform:rotate(-90deg)}
.r-ring circle{fill:none;stroke-width:8;stroke-linecap:round}
.r-ring .bg{stroke:rgba(255,255,255,.09)}
.r-ring .fg{transition:stroke-dashoffset .9s cubic-bezier(.2,.8,.2,1)}
.r-ring.ok .fg{stroke:#14f195}.r-ring.warn .fg{stroke:#f5b73b}.r-ring.bad .fg{stroke:#f2564f}.r-ring.mut .fg{stroke:#8b9bb4}
.r-ring .n{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;font-weight:800;font-size:1.45rem;line-height:1}
.r-ring .n small{font-size:.62rem;color:var(--muted);font-weight:500;margin-top:.2rem}
.r-vtxt{min-width:0}
.r-big{font-size:1.65rem;font-weight:800;letter-spacing:-.025em;display:flex;align-items:center;gap:.55rem;flex-wrap:wrap}
.r-tok{font-size:.9rem;color:var(--muted);font-weight:600;border:1px solid var(--line);border-radius:.5rem;padding:.05rem .5rem}
.r-vtxt p{margin:.35rem 0 0;color:#c9d4e6;font-size:.88rem}
.r-dot{width:12px;height:12px;border-radius:50%;display:inline-block}
.ok .r-dot{background:#14f195;box-shadow:0 0 12px #14f195}
.warn .r-dot{background:#f5b73b;box-shadow:0 0 12px #f5b73b}
.bad .r-dot{background:#f2564f;box-shadow:0 0 12px #f2564f}
.r-mint{margin:.7rem .1rem 0;font-size:.74rem;color:var(--muted);word-break:break-all;font-family:ui-monospace,monospace}
.r-links{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.5rem}
.r-links .btn,.r-tools .btn{padding:.4rem .8rem;font-size:.8rem;border-radius:.6rem}
.r-chips{display:flex;flex-wrap:wrap;gap:.45rem;margin:.8rem 0 .2rem}
.r-chip{display:inline-flex;align-items:center;gap:.35rem;border-radius:999px;padding:.2rem .65rem;font-size:.78rem;border:1px solid var(--line);background:rgba(10,18,32,.8);color:var(--muted)}
.r-chip.ok{color:#14f195;border-color:rgba(20,241,149,.4);background:rgba(11,32,22,.8)}
.r-chip.warn{color:#f5b73b;border-color:rgba(245,183,59,.45);background:rgba(34,26,9,.8)}
.r-chip.bad{color:#f2564f;border-color:rgba(242,86,79,.5);background:rgba(36,14,15,.8)}
.r-h{margin:1.1rem 0 .5rem;font-size:.95rem;font-weight:700;display:flex;align-items:center;gap:.5rem}
.r-h small{font-weight:500;color:var(--muted);font-size:.75rem}
.r-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.55rem;margin-top:.8rem}
.r-tile{background:rgba(17,27,43,.9);border:1px solid var(--line);border-top:2px solid var(--line);border-radius:.75rem;padding:.6rem .75rem}
.r-tile small{display:block;font-size:.72rem;color:var(--muted)}
.r-tile b{font-size:1.12rem;letter-spacing:-.01em}
.r-tile.ok{border-top-color:#14f195}.r-tile.warn{border-top-color:#f5b73b}.r-tile.bad{border-top-color:#f2564f}
.r-grid{display:grid;grid-template-columns:1fr 1fr;gap:.6rem;align-items:start}
@media(max-width:640px){.r-grid{grid-template-columns:1fr}.r-hero{flex-direction:column;align-items:flex-start}.check form{flex-wrap:wrap}}
.r-grp,.r-box{background:rgba(17,27,43,.9);border:1px solid var(--line);border-radius:.8rem;padding:.7rem .85rem}
.r-grp h4,.r-box h3{margin:0 0 .5rem;font-size:.88rem;display:flex;align-items:center;gap:.5rem}
.r-grp h4 b{margin-left:auto;font-size:.75rem;color:var(--muted);font-weight:600}
.r-sym{width:20px;height:20px;border-radius:6px;display:grid;place-items:center;font-size:.75rem;font-weight:800}
.r-grp ul{list-style:none;margin:0;padding:0}
.r-grp li{font-size:.83rem;padding:.3rem 0 .3rem .7rem;border-left:2px solid var(--line);margin-bottom:.25rem;color:#d3ddee}
.r-grp.ok{border-color:rgba(20,241,149,.35)}.r-grp.ok .r-sym{background:rgba(20,241,149,.15);color:#14f195}.r-grp.ok li{border-left-color:#14f195}
.r-grp.warn{border-color:rgba(245,183,59,.4)}.r-grp.warn .r-sym{background:rgba(245,183,59,.15);color:#f5b73b}.r-grp.warn li{border-left-color:#f5b73b}
.r-grp.bad{border-color:rgba(242,86,79,.45)}.r-grp.bad .r-sym{background:rgba(242,86,79,.18);color:#f2564f}.r-grp.bad li{border-left-color:#f2564f}
.r-grp.mut .r-sym{background:rgba(139,155,180,.15);color:var(--muted)}.r-grp.mut li{border-left-color:#33415c;color:var(--muted)}
.r-full{grid-column:1/-1}
.r-vbar{display:flex;height:10px;border-radius:99px;overflow:hidden;background:#0a1220;margin:.2rem 0 .4rem}
.r-vbar i{display:block;height:100%}
.r-vbar i.ok{background:#14f195}.r-vbar i.warn{background:#f5b73b}.r-vbar i.bad{background:#f2564f}
.r-prow{display:flex;gap:.6rem;padding:.5rem 0;border-top:1px solid var(--line)}
.r-prow .r-chip{align-self:flex-start;min-width:72px;justify-content:center}
.r-prow p{margin:.15rem 0 0;font-size:.8rem;color:var(--muted)}
.r-prow small{color:var(--muted)}
.r-sell{display:grid;grid-template-columns:auto 1fr auto;gap:.5rem .75rem;align-items:center;margin-top:.6rem;font-size:.85rem}
.r-bar{height:8px;border-radius:99px;background:#0a1220;overflow:hidden}
.r-bar i{display:block;height:100%;border-radius:99px}
.r-bar i.ok{background:#14f195}.r-bar i.warn{background:#f5b73b}.r-bar i.bad{background:#f2564f}
.r-sell .ok{color:#14f195}.r-sell .warn{color:#f5b73b}.r-sell .bad{color:#f2564f}
.r-note{font-size:.78rem;color:var(--muted);margin:.5rem 0 0}
.r-next{margin:0;padding-left:1.1rem;font-size:.85rem;color:#c9d4e6}
.r-next li{margin:.25rem 0}
.r-tools{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:1rem}
details.r-raw{margin-top:.6rem;background:#08101c;border:1px solid var(--line);border-radius:.65rem;padding:.5rem .75rem}
details.r-raw summary{cursor:pointer;color:var(--muted);font-size:.82rem}
details.r-raw pre{margin:.5rem 0 0;max-height:300px;overflow:auto;font-size:.75rem}

:root{--muted:#9db0ca;--sans:"Inter",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--disp:"Space Grotesk","Inter",ui-sans-serif,system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
body{font-family:var(--sans);font-size:16px;line-height:1.6}
h1,.logo,.r-big,.r-h,.card h3,section h2,.check h3,.strip b{font-family:var(--disp)}
code,pre,.r-mint,.sol,.check input{font-family:var(--mono)}
.sub{font-size:1.08rem;color:#aab9d0}
.check input{font-size:.9rem}
.r-hero.ok .r-big{color:#3df5ad}.r-hero.warn .r-big{color:#ffc94d}.r-hero.bad .r-big{color:#ff6b64}
.r-big{font-size:2.05rem;font-weight:700;line-height:1.1}
.r-tok{font-size:.95rem;font-family:var(--disp);color:#c4d0e4;background:rgba(255,255,255,.06)}
.r-vtxt p{font-size:.96rem;line-height:1.55;color:#dbe5f5}
.r-ring .n{font-family:var(--disp);font-size:1.85rem;font-weight:700}
.r-ring .n small{font-family:var(--sans);font-size:.66rem;color:#aab9d0}
.r-h{font-size:1.2rem;font-weight:700;margin:1.5rem 0 .65rem;letter-spacing:-.01em}
.r-h::before{content:"";width:4px;height:1.1em;border-radius:3px;background:linear-gradient(var(--b),var(--a))}
.r-h small{font-family:var(--sans)}
.r-tile{padding:.7rem .85rem}
.r-tile small{font-size:.8rem;color:#a9b9d0;margin-bottom:.1rem}
.r-tile b{font-family:var(--disp);font-size:1.5rem;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.r-chip{font-size:.84rem;font-weight:600;padding:.28rem .75rem}
.r-grp,.r-box{padding:.85rem 1rem}
.r-grp h4,.r-box h3{font-size:1.05rem;font-family:var(--disp);margin-bottom:.65rem}
.r-grp.ok h4{color:#3df5ad}.r-grp.warn h4{color:#ffc94d}.r-grp.bad h4{color:#ff6b64}.r-grp.mut h4{color:#bdcae0}
.r-grp li{font-size:.97rem;line-height:1.55;padding:.4rem 0 .4rem .85rem;margin-bottom:.35rem;color:#e8eefa}
.r-grp.mut li{color:#b0bfd5}
.num{font-family:var(--mono);font-weight:700;font-size:.9em;padding:.02em .35em;border-radius:.35em;background:rgba(255,255,255,.08);white-space:nowrap;color:#fff}
.r-grp.ok .num{color:#3df5ad;background:rgba(20,241,149,.12)}
.r-grp.warn .num{color:#ffc94d;background:rgba(245,183,59,.14)}
.r-grp.bad .num{color:#ff6b64;background:rgba(242,86,79,.15)}
.r-vtxt .num{background:rgba(255,255,255,.1)}
.r-prow b{font-size:.98rem}
.r-prow p{font-size:.88rem;color:#aab9d0}
.r-sell{font-size:.95rem}
.r-sell b{font-family:var(--mono);font-size:.9rem}
.r-note{font-size:.84rem}
.r-next{font-size:.95rem;line-height:1.6}
.r-mint{font-size:.78rem}
.btn{font-family:var(--sans)}
.r-tile em{display:block;font-style:normal;font-size:.82rem;font-weight:600;margin-top:.1rem;color:var(--muted)}
.r-tile em.ok{color:#3df5ad}.r-tile em.bad{color:#ff6b64}
.r-box .r-sell{margin-top:0}
@media(max-width:600px){nav{position:static}.r-big{font-size:1.8rem}}
@media(prefers-reduced-motion:reduce){.res,.r-spin,.r-ring .fg{animation:none!important;transition:none!important}}
"""

CHECK_JS = r'''
(function(){
var $=function(s){return document.querySelector(s)};
var out=$('#out'),inp=$('#mint'),btn=$('#go');
var B58=/^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
var st=null,token=0;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function vc(v){return {ok:'ok',caution:'warn',avoid:'bad'}[String(v||'').toLowerCase()]||'mut'}
function pct(x){return Math.round((Number(x)||0)*100)}
function chip(t,c){return '<span class="r-chip '+(c||'')+'">'+esc(t)+'</span>'}
function isNum(v){return typeof v==='number'&&isFinite(v)}
function isNumLike(v){return isNum(v)||(typeof v==='string'&&v.trim()!==''&&isFinite(Number(v)))}
function compact(n){n=Number(n);var a=Math.abs(n);if(a>=1e9)return '$'+(n/1e9).toFixed(2)+'B';if(a>=1e6)return '$'+(n/1e6).toFixed(2)+'M';if(a>=1e3)return '$'+(n/1e3).toFixed(1)+'K';return '$'+n.toFixed(0)}
function nice(f){f=String(f||'').replace(/_/g,' ').trim();return f.charAt(0).toUpperCase()+f.slice(1)}
function flagCls(f){f=String(f).toLowerCase();return /dump|sell|rug|drain|honeypot|bundle|sniper/.test(f)?'bad':(/buy|accum/.test(f)?'':'warn')}
function fmtAge(d){if(d<1/24)return Math.max(1,Math.round(d*1440))+' min';if(d<1)return Math.round(d*24)+' h';if(d>=730)return (d/365).toFixed(1)+' yr';return (d<30?Math.round(d*10)/10:Math.round(d))+' d'}
function hl(t){return t.replace(/(\$\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$\d+(?:\.\d+)?|\d+(?:\.\d+)?%\+?|\b\d+\+? ?(?:days?|hours?|h)\b)/g,'<span class="num">$1</span>')}
function tidy(s){return String(s==null?'':s).replace(/\s*\([^()]*\u03b1=\{[^}]*\}\)/,'')}
function copy(text,el){
  function done(){if(el){var o=el.textContent;el.textContent='Copied';setTimeout(function(){el.textContent=o},1200)}}
  function fb(){var t=document.createElement('textarea');t.value=text;document.body.appendChild(t);t.select();try{document.execCommand('copy')}catch(e){}t.remove();done()}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(done,fb)}else fb();
}
function find(o,re,pred,d){
  d=d||0;if(!o||typeof o!=='object'||d>4)return undefined;var k,v;
  for(k in o){if(re.test(k)){v=o[k];if(pred(v))return v}}
  for(k in o){v=o[k];if(v&&typeof v==='object'){var r=find(v,re,pred,d+1);if(r!==undefined)return r}}
  return undefined;
}
function findSizes(o,d){
  d=d||0;if(!o||typeof o!=='object'||d>4)return null;
  if(Array.isArray(o)&&o.length&&o[0]&&typeof o[0]==='object'){
    var ks=Object.keys(o[0]);
    var a=ks.filter(function(k){return /usd|size|amount|notional/i.test(k)&&isNum(o[0][k])})[0];
    var b=ks.filter(function(k){return /loss|impact|slip|cost/i.test(k)&&isNum(o[0][k])})[0];
    if(a&&b)return o.map(function(it){return {size:it[a],loss:it[b],lk:b}});
  }
  for(var k in o){var r=findSizes(o[k],d+1);if(r)return r}
  return null;
}
function lossPct(v,k){v=Number(v);if(/bps/i.test(k))return v/100;if(/pct|percent/i.test(k))return v;return Math.abs(v)<=1?v*100:v}
function fmtUsd(n){return '$'+Number(n).toLocaleString('en-US',{maximumFractionDigits:0})}
function fmtPrice(n){n=Number(n);return '$'+(n>=1?n.toLocaleString('en-US',{maximumFractionDigits:2}):n.toPrecision(4))}
function group(title,sym,c,arr){
  if(!Array.isArray(arr)||!arr.length)return '';
  var li=arr.map(function(x){return '<li>'+hl(esc(tidy(typeof x==='string'?x:(x.label||x.id||JSON.stringify(x)))))+'</li>'}).join('');
  return '<div class="r-grp '+c+'"><h4><span class="r-sym">'+sym+'</span>'+title+'<b>'+arr.length+'</b></h4><ul>'+li+'</ul></div>';
}
function debate(db){
  if(!db)return '';
  var vt=db.votes_weighted||db.votes||{};
  var tot=(vt.ok||0)+(vt.caution||0)+(vt.avoid||0)||1;
  var bar=['ok','caution','avoid'].map(function(k){return '<i class="'+vc(k)+'" style="width:'+((vt[k]||0)/tot*100)+'%"></i>'}).join('');
  var rows=(db.personas||[]).map(function(p){
    return '<div class="r-prow">'+chip(p.verdict,vc(p.verdict))+'<div><b>'+esc(p.persona)+'</b> <small>'+pct(p.confidence)+'%</small><p>'+esc(p.reason)+'</p></div></div>';
  }).join('');
  var ag=db.agreement_weighted!=null?db.agreement_weighted:db.agreement;
  return '<section class="r-box r-full" style="margin:0"><h3>Agent debate '+chip(db.meta_verdict,vc(db.meta_verdict))+'<span style="margin-left:auto;font-weight:500;font-size:.75rem;color:var(--muted)">agreement '+pct(ag)+'%</span></h3><div class="r-vbar">'+bar+'</div>'+rows+'</section>';
}
function tile(label,val,c,sub,sc){return '<div class="r-tile '+(c||'')+'"><small>'+esc(label)+'</small><b>'+esc(val)+'</b>'+(sub?'<em class="'+(sc||'')+'">'+esc(sub)+'</em>':'')+'</div>'}

function b58d(s){var A='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz',n=BigInt(0),i;for(i=0;i<s.length;i++)n=n*BigInt(58)+BigInt(A.indexOf(s[i]));var hex=n.toString(16);if(hex.length%2)hex='0'+hex;var by=[];for(i=0;i<hex.length;i+=2)by.push(parseInt(hex.substr(i,2),16));var z=0;while(z<s.length&&s[z]==='1')z++;if(n===BigInt(0))by=[];return new Uint8Array(new Array(z).fill(0).concat(by))}
function hexBytes(h){var o=new Uint8Array(h.length/2);for(var i=0;i<o.length;i++)o[i]=parseInt(h.substr(i*2,2),16);return o}
async function verifyAtt(a,d){
  var m=$('#vfmsg');
  function say(t,c){if(m)m.innerHTML='<span style="font-weight:600;color:'+c+'">'+esc(t)+'</span>'}
  try{
    var rec=JSON.parse(a.canon);
    if(rec.mint!==d.mint||rec.verdict!==(d.decision||{}).verdict)return say('The signed record does not match the verdict shown.','#ff6b64');
    var dig=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(a.prev+a.canon));
    var hex=Array.from(new Uint8Array(dig)).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join('');
    if(hex!==a.hash)return say('Hash does not match the record.','#ff6b64');
    var key=await crypto.subtle.importKey('raw',b58d(a.pubkey),{name:'Ed25519'},false,['verify']);
    var ok=await crypto.subtle.verify({name:'Ed25519'},key,hexBytes(a.sig),hexBytes(a.hash));
    say(ok?'\u2714 Signature valid (checked in your browser)':'Signature is invalid.',ok?'#3df5ad':'#ff6b64');
  }catch(e){say('This browser cannot check Ed25519. Use the steps at /attest.','#ffc94d')}
}
function survivalHtml(s){
  if(!s)return '';
  var b=find(s,/^bad_rate_by_horizon$/i,function(q){return q&&typeof q==='object'});
  if(!b)return '';
  var keys=Object.keys(b).filter(function(k){return /^\d+h$/.test(k)&&b[k]&&isNum(b[k].bad_rate_pct)}).sort(function(x,y){return parseInt(x)-parseInt(y)});
  if(keys.length<2)return '';
  var pts=[{l:'now',v:100}].concat(keys.map(function(k){return {l:k,v:100-b[k].bad_rate_pct}}));
  var W=300,H=118,x0=24,x1=276,m=pts.length;
  var xy=pts.map(function(p,i){return [x0+i*(x1-x0)/(m-1),96-(p.v/100)*72]});
  var last=pts[m-1].v,c=last>=70?'#14f195':(last>=40?'#f5b73b':'#f2564f');
  var path=xy.map(function(p,i){return (i?'L':'M')+p[0].toFixed(1)+' '+p[1].toFixed(1)}).join(' ');
  var svg='<svg viewBox="0 0 '+W+' '+H+'" width="100%" role="img" aria-label="Survival of past tokens with this verdict"><path d="'+path+'" fill="none" stroke="'+c+'" stroke-width="3" stroke-linejoin="round"/>';
  xy.forEach(function(p,i){svg+='<circle cx="'+p[0].toFixed(1)+'" cy="'+p[1].toFixed(1)+'" r="4" fill="'+c+'"/><text x="'+p[0].toFixed(1)+'" y="'+(p[1]-9).toFixed(1)+'" text-anchor="middle" font-size="11" font-weight="700" fill="#e8eefa">'+(Math.round(pts[i].v*10)/10)+'%</text><text x="'+p[0].toFixed(1)+'" y="112" text-anchor="middle" font-size="10" fill="#9db0ca">'+esc(pts[i].l)+'</text>'});
  svg+='</svg>';
  var ns=keys.map(function(k){return b[k].n}).filter(isNum);
  var nmin=ns.length?Math.min.apply(null,ns):null;
  return '<div class="r-h">Survival of similar verdicts <small>past outcomes, not a forecast</small></div><div class="r-box" style="margin:0">'+svg+'<p class="r-note" style="margin-top:.2rem">Share of past tokens with this verdict that had not collapsed after each time'+(nmin?' (smallest group n='+nmin+')':'')+'. Collapse means price down 50%+ or liquidity down 70%+.</p></div>';
}
function render(first){
  var d=st.d,s=st.s,x=st.x,dc=d.decision||{};
  var v=String(dc.verdict||'unknown').toLowerCase(),c=vc(v);
  var risk=Number(dc.risk_score),hasRisk=dc.risk_score!=null&&isFinite(risk);
  var rc=!hasRisk?'mut':(risk<35?'ok':(risk<65?'warn':'bad'));
  var C=2*Math.PI*34,off=hasRisk?C*(1-Math.min(100,Math.max(0,risk))/100):C;
  var label={ok:'Looks OK',caution:'Use caution',avoid:'High risk'}[v]||v;
  var all=[].concat(dc.positives||[],dc.cautions||[],dc.blockers||[]).join(' | ');
  var src=[s,d];
  function pick(re,pred){for(var i=0;i<src.length;i++){var r=find(src[i],re,pred);if(r!==undefined)return r}}

  var liq=pick(/^(liquidity(_usd)?|liq_usd)$/i,isNum);
  if(liq===undefined){var m1=/Liquidity \$([\d,]+)/.exec(d.summary||'');if(m1)liq=Number(m1[1].replace(/,/g,''))}
  var price=pick(/^(price(_usd)?|priceusd)$/i,isNumLike);
  var age=pick(/^(pair_age_days|age_days|pair_age_d|pair_age)$/i,isNum);
  var ageMin=pick(/^pair_age_minutes$/i,isNum);
  if(age===undefined&&ageMin!==undefined)age=ageMin/1440;
  var pc=s&&s.price_change_pct&&typeof s.price_change_pct==='object'?s.price_change_pct['24h']:undefined;
  var mcap=pick(/^market_cap_usd$/i,isNumLike),vol1=pick(/^volume_1h$/i,isNumLike);
  var buys=s?s.buys_5m:undefined,sells=s?s.sells_5m:undefined;
  var hq=pick(/^holder_quality(_score)?$/i,function(q){return isNum(q)||(q&&isNum(q.score))});
  if(hq&&typeof hq==='object')hq=hq.score;
  var t10=/Top 10 holders own (?:only )?(\d+(?:\.\d+)?)%/i.exec(all);
  var lp=/(\d+(?:\.\d+)?)% of liquidity locked/i.exec(all);

  var tiles='';
  if(liq!==undefined)tiles+=tile('Liquidity',fmtUsd(liq),liq>=100000?'ok':(liq>=20000?'warn':'bad'));
  if(price!==undefined)tiles+=tile('Price',fmtPrice(price),'',isNum(pc)?'24h '+(pc>=0?'+':'')+pc+'%':'',isNum(pc)?(pc>=0?'ok':'bad'):'');
  if(age!==undefined)tiles+=tile('Pair age',fmtAge(age),age<1?'bad':(age<7?'warn':'ok'));
  if(hq!==undefined)tiles+=tile('Holder quality',Math.round(hq)+' / 100',hq>=60?'ok':(hq>=40?'warn':'bad'));
  if(t10)tiles+=tile('Top 10 holders',t10[1]+'%',Number(t10[1])<25?'ok':(Number(t10[1])<50?'warn':'bad'));
  if(lp)tiles+=tile('LP locked or burned',lp[1]+'%',Number(lp[1])>=80?'ok':(Number(lp[1])>=50?'warn':'bad'));
  if(mcap!==undefined)tiles+=tile('Market cap',compact(mcap));
  if(vol1!==undefined)tiles+=tile('Volume 1h',compact(vol1));
  if(isNum(buys)&&isNum(sells))tiles+=tile('Buys / sells 5m',buys+' / '+sells,sells>buys*2?'warn':(buys>sells*2?'ok':''));
  var ow=/One wallet holds (\d+(?:\.\d+)?)%\+? of supply/i.exec(all);
  if(ow)tiles+=tile('Largest wallet',ow[1]+'%+',Number(ow[1])>=30?'bad':'warn');
  if(age===undefined){
    var ao=/Pair older than (\d+) days/i.exec(all),ay=/Pair (?:younger|newer) than (\d+) (days|hours)/i.exec(all);
    if(ao)tiles+=tile('Pair age',ao[1]+'+ d','ok');
    else if(ay)tiles+=tile('Pair age','< '+ay[1]+(ay[2]==='hours'?' h':' d'),'bad');
  }

  var flags=s?find(s,/^flags$/i,Array.isArray):undefined;
  var flagHtml='';
  if(flags&&flags.length)flagHtml='<div class="r-h">Flags</div><div class="r-chips" style="margin-top:0">'+flags.map(function(f){var t=typeof f==='string'?f:(f.label||f.id||f.name||'');return chip(nice(t),flagCls(t))}).join('')+'</div>';

  var sellHtml='';
  if(x){
    var sizes=findSizes(x);
    var grade=find(x,/^(exit_)?grade$/i,function(q){return typeof q==='string'});
    var overall=find(x,/^(overall|overall_verdict|verdict)$/i,function(q){return typeof q==='string'});
    if(sizes&&sizes.length||grade){
      sellHtml='<div class="r-h">Cost to sell <small>Jupiter quote</small></div>';
      var gc=/good|ok|low/i.test(grade||'')?'ok':(/fair|medium|mid|warn|caution/i.test(grade||'')?'warn':(grade?'bad':''));
      var oc=overall?vc(overall):'';
      sellHtml+='<div class="r-chips" style="margin-top:0">'+(grade?chip('Exit grade: '+grade,gc):'')+(overall?chip('Overall: '+overall,oc==='mut'?'':oc):'')+'</div>';
      if(sizes&&sizes.length){
        sellHtml+='<div class="r-sell">'+sizes.slice(0,6).map(function(z){
          var l=lossPct(z.loss,z.lk),lc=l<3?'ok':(l<8?'warn':'bad');
          return '<span>Sell '+fmtUsd(z.size)+'</span><div class="r-bar"><i class="'+lc+'" style="width:'+Math.min(100,Math.max(3,l*4))+'%"></i></div><b class="'+lc+'">'+(Math.round(l*10)/10)+'% lost</b>';
        }).join('')+'</div>';
      }
      sellHtml+='<p class="r-note">A quote does not prove a real sell will succeed.</p>';
    }
  }

  var h='<div class="res">';
  h+='<div class="r-hero '+c+'"><div class="r-ring '+rc+'"><svg viewBox="0 0 88 88" width="88" height="88"><circle class="bg" cx="44" cy="44" r="34"/><circle class="fg" id="fg" cx="44" cy="44" r="34" stroke-dasharray="'+C.toFixed(1)+'" stroke-dashoffset="'+(first?C.toFixed(1):off.toFixed(1))+'" data-off="'+off.toFixed(1)+'"/></svg><div class="n">'+(hasRisk?risk:'?')+'<small>risk / 100</small></div></div>';
  h+='<div class="r-vtxt"><div class="r-big"><i class="r-dot"></i>'+esc(label)+'<span class="r-tok">'+esc(d.token||'')+'</span></div><p>'+hl(esc(tidy(d.summary||'')))+'</p></div></div>';
  h+='<div class="r-mint">'+esc(d.mint||st.mint)+'</div>';
  h+='<div class="r-links"><button type="button" class="btn btn-o" id="ca">Copy address</button><a class="btn btn-o" href="https://dexscreener.com/solana/'+encodeURIComponent(d.mint||st.mint)+'" target="_blank" rel="noopener noreferrer">DexScreener</a><a class="btn btn-o" href="https://solscan.io/token/'+encodeURIComponent(d.mint||st.mint)+'" target="_blank" rel="noopener noreferrer">Solscan</a></div>';

  var chips='';
  if(d.regime&&d.regime.name)chips+=chip('Regime: '+d.regime.name+' ('+pct(d.regime.confidence)+'%)',/risk_off/.test(d.regime.name)?'warn':(/risk_on/.test(d.regime.name)?'ok':''));
  if(d.attention_trap)chips+=chip('Attention trap','warn');
  var t=d.time_to_death;
  if(t&&t.band)chips+=chip('Stress clock: '+t.band+(t.eta_hours?' (~'+t.eta_hours+'h)':''),{slow:'ok',medium:'warn',fast:'bad'}[String(t.band).toLowerCase()]||'');
  var cf=d.counterfactual;
  if(cf&&cf.available&&cf.expected_bad_rate!=null){var r=cf.expected_bad_rate;chips+=chip('Similar cases bad: '+pct(r)+'% (n='+cf.cohort_n+')',r<.25?'ok':(r<.5?'warn':'bad'))}
  var at=d.community&&d.community.attention;
  if(at&&at['24h']!=null)chips+=chip('Attention 24h: '+at['24h'],'');
  var dcf=s&&s.decision_confidence&&s.decision_confidence.level;
  if(dcf)chips+=chip('Data confidence: '+dcf,{high:'ok',medium:'warn',low:'warn'}[String(dcf).toLowerCase()]||'');
  if(chips)h+='<div class="r-chips">'+chips+'</div>';
  if(s&&s.source_note)h+='<p class="r-note">\u24D8 '+esc(s.source_note)+'</p>';
  var at2=d.attestation;
  if(at2&&at2.sig)h+='<p class="r-note"><span class="num">\u2714 Signed #'+esc(at2.chain_n)+'</span> hash '+esc(String(at2.hash).slice(0,12))+'\u2026 \u00B7 <button type="button" class="r-try" id="vf">Verify here</button> \u00B7 <a href="/attest" target="_blank" rel="noopener">how it works</a> <span id="vfmsg"></span></p>';

  if(tiles)h+='<div class="r-tiles">'+tiles+'</div>';
  if(st.pending>0)h+='<p class="r-note">Loading market data and sell cost...</p>';
  var tr=s&&s.track_record_context;
  if(tr&&isNum(tr.bad_outcome_rate)){
    var br=tr.bad_outcome_rate*100,bc=br<25?'ok':(br<50?'warn':'bad');
    h+='<div class="r-h">Track record <small>similar past verdicts</small></div><div class="r-box"><div class="r-sell"><span>Ended badly'+(tr.horizon_hours?' ('+tr.horizon_hours+'h)':'')+'</span><div class="r-bar"><i class="'+bc+'" style="width:'+Math.min(100,Math.max(3,br))+'%"></i></div><b class="'+bc+'">'+(Math.round(br*10)/10)+'%</b></div><p class="r-note">'+(tr.n?'Based on '+tr.n+' judged tokens'+(tr.basis?' ('+esc(String(tr.basis).replace(/^judged tokens with /i,''))+')':'')+'. ':'')+(tr.ci95&&tr.ci95.length===2?'95% range '+tr.ci95[0]+' to '+tr.ci95[1]+'%. ':'')+esc(tr.meaning||'')+'</p></div>';
  }

  h+=survivalHtml(s);
  var unk=(dc.unknowns||[]).filter(function(u){return !(sellHtml&&/Exit cost not checked/i.test(String(u)))});
  h+='<div class="r-h">Signals</div><div class="r-grid">';
  h+=group('Blockers','\u2716','bad',dc.blockers);
  h+=group('Cautions','\u26A0','warn',dc.cautions);
  h+=group('Positives','\u2714','ok',dc.positives);
  h+=group('Unknowns','?','mut',unk);
  h+=group('Pre-rug patterns','\u26A0','warn',d.pre_rug);
  h+=group('What would change this','\u21BB','mut',d.would_change_my_mind);
  h+='</div>';
  h+=flagHtml+sellHtml;
  if(d.debate)h+='<div class="r-h">Agent debate</div><div class="r-grid">'+debate(d.debate)+'</div>';

  var steps=[];
  if((dc.blockers||[]).length)steps.push('Blockers were found. Understand each one before sizing any trade.');
  var sn=(s&&Array.isArray(s.suggested_next))?s.suggested_next:(Array.isArray(dc.next_checks)?dc.next_checks:[]);
  sn.forEach(function(z){if(typeof z==='string'&&!(sellHtml&&/exit check/i.test(z)))steps.push(z.charAt(0).toUpperCase()+z.slice(1).replace(/\.$/,'')+'.')});
  if(!sellHtml&&st.pending<=0&&!sn.length)steps.push('Run the exit check (GET /exit or MCP check_exit) before sizing a trade.');
  steps.push('Verify on-chain (DexScreener, Solscan) before acting.');
  h+='<div class="r-h">Next steps</div><ul class="r-next">'+steps.map(function(z){return '<li>'+esc(z)+'</li>'}).join('')+'</ul>';

  var raw=JSON.stringify({omni:st.d,signal:st.s,exit:st.x},null,2);
  var wasOpen=$('details.r-raw')&&$('details.r-raw').open;
  h+='<div class="r-tools"><button type="button" class="btn btn-o" id="cj">Copy JSON</button><button type="button" class="btn btn-o" id="cl">Copy link</button><a class="btn btn-o" href="/omni?mint='+encodeURIComponent(d.mint||st.mint)+'" target="_blank" rel="noopener">Open JSON</a></div>';
  h+='<details class="r-raw"'+(wasOpen?' open':'')+'><summary>Raw JSON</summary><pre>'+esc(raw)+'</pre></details>';
  h+='<p class="r-note">v'+esc(d.version||'')+' \u00B7 Heuristics only, not financial advice. Data can be late or wrong.</p></div>';
  out.innerHTML=h;
  if(first)requestAnimationFrame(function(){requestAnimationFrame(function(){var f=$('#fg');if(f)f.style.strokeDashoffset=f.getAttribute('data-off')})});
  $('#cj').onclick=function(){copy(raw,this)};
  $('#cl').onclick=function(){copy(location.origin+location.pathname+'?mint='+encodeURIComponent(st.mint),this)};
  $('#ca').onclick=function(){copy(d.mint||st.mint,this)};
  if($('#vf'))$('#vf').onclick=function(){verifyAtt(at2,d)};
}
function showErr(m){out.innerHTML='<div class="r-err">'+esc(m)+'</div>'}
function extra(url,key,my){
  fetch(url,{headers:{'Accept':'application/json'}}).then(function(r){return r.ok?r.json():null}).catch(function(){return null}).then(function(j){
    if(my!==token||!st)return;st[key]=j;st.pending--;render(false);
  });
}
async function run(m){
  m=(m||'').trim();
  if(!B58.test(m)){showErr('That does not look like a Solana mint address. Paste the full CA (32-44 characters).');return}
  var my=++token;st=null;
  btn.disabled=true;btn.textContent='Checking...';
  out.innerHTML='<div class="r-load"><div class="r-spin"></div><span>Checking '+esc(m.slice(0,4))+'...'+esc(m.slice(-4))+' - the first request can take up to 30s if the server is waking up.</span></div>';
  var ctl=new AbortController(),to=setTimeout(function(){ctl.abort()},60000);
  try{
    var r=await fetch('/omni?mint='+encodeURIComponent(m),{signal:ctl.signal,headers:{'Accept':'application/json'}});
    var txt=await r.text();var d=null;try{d=JSON.parse(txt)}catch(e){}
    if(my!==token)return;
    if(r.status===429){showErr('Too many requests. Wait a few seconds and press Check again.')}
    else if(!r.ok||!d){var det=d&&(d.detail||d.error);showErr('Request failed ('+r.status+'). '+(det?(typeof det==='string'?det:JSON.stringify(det)):'Try again in a moment.'))}
    else{
      st={d:d,s:null,x:null,mint:m,pending:2};render(true);
      try{history.replaceState(null,'','?mint='+encodeURIComponent(m))}catch(e){}
      extra('/signal?mint='+encodeURIComponent(m),'s',my);
      extra('/exit?mint='+encodeURIComponent(m),'x',my);
    }
  }catch(e){showErr(e&&e.name==='AbortError'?'Timed out after 60s. Press Check again.':'Network error. Check your connection and try again.')}
  finally{clearTimeout(to);btn.disabled=false;btn.textContent='Check'}
}
$('#f').addEventListener('submit',function(e){e.preventDefault();run(inp.value)});
inp.addEventListener('paste',function(){setTimeout(function(){var v=inp.value.trim();inp.value=v;if(B58.test(v))run(v)},0)});
$('#paste').addEventListener('click',function(){
  if(navigator.clipboard&&navigator.clipboard.readText){navigator.clipboard.readText().then(function(t){inp.value=(t||'').trim();run(inp.value)}).catch(function(){inp.focus()})}else inp.focus();
});
$('#check').addEventListener('click',function(e){var b=e.target.closest('.r-try');if(b){inp.value=b.getAttribute('data-mint');run(inp.value)}});
var q=new URLSearchParams(location.search).get('mint');
if(q){inp.value=q;run(q)}
})();
'''

PROOF_CSS = r"""
#proof h2 small{font-family:var(--sans);font-size:.8rem;color:var(--muted);font-weight:500;margin-left:.5rem}
.pf-tabs{display:flex;gap:.4rem;margin-bottom:.8rem}
.pf-tabs button{cursor:pointer;border:1px solid var(--line);background:rgba(10,18,32,.8);color:var(--muted);border-radius:999px;padding:.3rem .85rem;font-size:.82rem;font-family:var(--sans)}
.pf-tabs button.on{border-color:var(--a);color:var(--a)}
.pf-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.6rem}
.pf-card{background:var(--card);border:1px solid var(--line);border-radius:.9rem;padding:.8rem 1rem}
.pf-card small{display:block;color:var(--muted);font-size:.8rem}
.pf-card b{display:block;font-family:var(--disp);font-size:1.9rem;letter-spacing:-.02em;line-height:1.15}
.pf-card.hl{border-color:rgba(20,241,149,.45);background:linear-gradient(135deg,rgba(20,241,149,.1),var(--card))}
.pf-lead{margin:.9rem 0 .4rem;color:#cfdaec;font-size:.97rem;line-height:1.6}
.pf-box{background:var(--card);border:1px solid var(--line);border-radius:.9rem;padding:.8rem 1rem;margin-top:.7rem}
.pf-box h3{font-family:var(--disp);font-size:1rem;margin:0 0 .5rem}
.pf-box h3 small{font-family:var(--sans);color:var(--muted);font-weight:500;font-size:.78rem;margin-left:.4rem}
.pf-row{display:grid;grid-template-columns:92px 1fr 58px;gap:.15rem .6rem;align-items:center;margin:.5rem 0;font-size:.9rem}
.pf-row small{grid-column:2/4;color:var(--muted);font-size:.75rem}
.pf-row b{font-family:var(--mono);text-align:right;font-size:.88rem}
.pf-bar{position:relative;height:10px;border-radius:99px;background:#0a1220}
.pf-bar i{display:block;height:100%;border-radius:99px}
.pf-bar i.ok{background:#14f195}.pf-bar i.warn{background:#f5b73b}.pf-bar i.bad{background:#f2564f}.pf-bar i.acc{background:linear-gradient(90deg,#9945ff,#14f195)}
.pf-bar u{position:absolute;top:-3px;bottom:-3px;width:2px;background:#fff;opacity:.55}
.pf-rules{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:.6rem;margin-top:.7rem}
.pf-rule{background:var(--card);border:1px solid var(--line);border-radius:.9rem;padding:.8rem 1rem}
.pf-rule.hi{border-color:rgba(153,69,255,.65)}
.pf-rule h4{margin:0;font-family:var(--disp);font-size:1rem}
.pf-rule p{margin:.15rem 0 .4rem;color:var(--muted);font-size:.78rem}
.pf-m{display:grid;grid-template-columns:1fr 52px;gap:.2rem .5rem;margin:.55rem 0;font-size:.82rem;align-items:center}
.pf-m span{grid-column:1/3;color:#c4d0e4}
.pf-m b{font-family:var(--mono);text-align:right;font-size:.85rem}
.pf-m small{grid-column:1/3;color:var(--muted);font-size:.72rem}
#proof details{margin-top:.7rem;color:var(--muted);font-size:.84rem}
#proof details summary{cursor:pointer}
#proof details li{margin:.3rem 0}
"""

PROOF_JS = r'''
(function(){
var sec=document.getElementById('proof');if(!sec)return;
var body=document.getElementById('pf-body'),tabs=document.getElementById('pf-tabs');
var DATA=null,cur='all_tracked';
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function num(x){return typeof x==='number'&&isFinite(x)}
function r1(x){return Math.round(x*10)/10}
function load(u){return fetch(u,{headers:{'Accept':'application/json'}}).then(function(r){return r.ok?r.json():null}).catch(function(){return null})}
function cls(v){return v<40?'ok':(v<70?'warn':'bad')}
function bar(v,c,base){return '<div class="pf-bar"><i class="'+c+'" style="width:'+Math.max(2,Math.min(100,v))+'%"></i>'+(num(base)?'<u style="left:'+Math.min(99,base)+'%" title="base rate"></u>':'')+'</div>'}
function ci(a){return (a&&a.length===2)?'95% range '+a[0]+' to '+a[1]+'%':''}
function metric(label,v,c,sub){if(!num(v))return '';return '<div class="pf-m"><span>'+esc(label)+'</span>'+bar(v,c)+'<b>'+r1(v)+'%</b>'+(sub?'<small>'+esc(sub)+'</small>':'')+'</div>'}
function rule(title,note,o,hi){
  if(!o||!num(o.precision_pct))return '';
  return '<div class="pf-rule'+(hi?' hi':'')+'"><h4>'+esc(title)+'</h4><p>'+esc(note)+' \u00B7 flagged '+esc(o.flagged)+' tokens</p>'
   +metric('Right when it flags',o.precision_pct,'acc',ci(o.precision_ci95_pct))
   +metric('Bad outcomes it catches',o.recall_pct,'acc')
   +metric('Good tokens wrongly flagged',o.false_positive_rate_pct,'warn')+'</div>';
}
function draw(){
  var P=DATA.performance||{},p=P[cur];if(!p){body.innerHTML='';return}
  var base=p.judged?p.bad_outcomes/p.judged*100:null,oa=p.ours_avoid||{},ba=p.baseline_avoid||{},oc=p.ours_avoid_or_caution||{};
  var h='';
  if(num(oa.precision_pct)&&num(base)){
    h+='<div class="pf-cards"><div class="pf-card hl"><small>Avoid is right</small><b>'+r1(oa.precision_pct)+'%</b><small>'+esc(ci(oa.precision_ci95_pct))+'</small></div>'
     +'<div class="pf-card"><small>Base rate, all tracked tokens</small><b>'+r1(base)+'%</b><small>ended badly within '+esc(DATA.horizon_hours||24)+'h</small></div>'
     +'<div class="pf-card"><small>Avoid beats the base rate by</small><b>+'+r1(oa.precision_pct-base)+' pts</b><small>'+esc(p.judged)+' verdicts judged</small></div></div>';
    h+='<p class="pf-lead">Most tokens in this sample fail, so a good verdict must beat <b>'+r1(base)+'%</b>. Avoid reaches <b>'+r1(oa.precision_pct)+'%</b> but catches only <b>'+r1(oa.recall_pct)+'%</b> of bad outcomes.'
     +(num(ba.precision_pct)?' A simple baseline rule catches '+r1(ba.recall_pct)+'% but is right '+r1(ba.precision_pct)+'% of the time and wrongly flags '+r1(ba.false_positive_rate_pct)+'% of good tokens.':'')+'</p>';
  }
  var V=p.verdicts||{},vr='';
  [['ok','OK','ok'],['caution','Caution','warn'],['avoid','Avoid','bad']].forEach(function(x){
    var v=V[x[0]];if(v&&num(v.bad_outcome_rate_pct))vr+='<div class="pf-row"><span>'+x[1]+'</span>'+bar(v.bad_outcome_rate_pct,x[2],base)+'<b>'+r1(v.bad_outcome_rate_pct)+'%</b><small>n='+esc(v.n)+(v.ci95_pct?' \u00B7 '+esc(ci(v.ci95_pct)):'')+'</small></div>';
  });
  if(vr)h+='<div class="pf-box"><h3>Bad outcome rate by verdict <small>white line = base rate</small></h3>'+vr+'</div>';
  var rr=rule('Our avoid','Verdict "avoid"',oa,true)+rule('Baseline rule','Simple liquidity and age rule',ba,false)+rule('Our avoid + caution','Anything not OK',oc,false);
  if(rr)h+='<div class="pf-rules">'+rr+'</div>';
  var B=DATA.by_risk_bucket||[],br='';
  B.forEach(function(b){if(num(b.bad_outcome_rate_pct))br+='<div class="pf-row"><span>Risk '+esc(b.risk_score_range)+'</span>'+bar(b.bad_outcome_rate_pct,cls(b.bad_outcome_rate_pct),base)+'<b>'+r1(b.bad_outcome_rate_pct)+'%</b><small>n='+esc(b.n)+'</small></div>'});
  if(br)h+='<div class="pf-box"><h3>Does a higher risk score mean more failures? <small>all tracked</small></h3>'+br+'</div>';
  var cv=(DATA.caveats||[]).slice(0,2).map(function(c){return '<li>'+esc(c)+'</li>'}).join('');
  h+='<details><summary>How to read this</summary><ul>'+(DATA.bad_outcome_definition?'<li>Bad outcome: '+esc(DATA.bad_outcome_definition)+'.</li>':'')+cv+'<li>'+esc(DATA.resolved||0)+' verdicts judged, '+esc(DATA.pending||0)+' still waiting for their 24h result.</li></ul></details>';
  body.innerHTML=h;
}
function tabsDraw(){
  var P=DATA.performance||{},t='';
  [['all_tracked','All time'],['last_7d','Last 7 days']].forEach(function(x){if(P[x[0]])t+='<button type="button" data-k="'+x[0]+'" class="'+(cur===x[0]?'on':'')+'">'+x[1]+(P[x[0]].days_covered?' ('+P[x[0]].days_covered+'d)':'')+'</button>'});
  tabs.innerHTML=t;
}
tabs.addEventListener('click',function(e){var b=e.target.closest('button');if(!b||!DATA)return;cur=b.getAttribute('data-k');tabsDraw();draw()});
load('/stats').then(function(j){return (j&&j.performance)?j:load('/accuracy')}).then(function(j){
  if(!j||!j.performance){sec.style.display='none';return}
  DATA=j;tabsDraw();draw();
});
})();
'''

HOME_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#070b12">
<meta name="color-scheme" content="dark">
<title>{BRAND} — Solana signals for AI agents</title>
<meta name="description" content="Free Solana token signals for AI agents. Paste a mint, get verdict and reasons. Measured on /stats. Not financial advice.">
<meta property="og:title" content="{BRAND} — Solana signals for AI agents">
<meta property="og:description" content="Free, open source. One call for verdict + reasons. Accuracy public on /stats.">
<meta property="og:image" content="{BASE}/og.svg">
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&amp;family=JetBrains+Mono:wght@500;700&amp;family=Space+Grotesk:wght@600;700&amp;display=swap">
<style>
:root {{
  --bg:#070b12; --card:rgba(15,22,34,.92); --line:rgba(40,56,78,.9);
  --text:#e8eef6; --muted:#8b9bb4; --a:#14f195; --b:#9945ff; --c:#6366f1;
}}
* {{ box-sizing:border-box; margin:0; padding:0 }}
body {{
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.55; min-height: 100vh;
}}
.bg {{ position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }}
.bg span {{
  position: absolute; width: 55vmax; height: 55vmax; border-radius: 50%;
  filter: blur(10px); opacity: .42;
}}
.bg span:nth-child(1) {{
  left: -20vmax; top: -25vmax;
  background: radial-gradient(circle, rgba(153,69,255,.55), transparent 65%);
}}
.bg span:nth-child(2) {{
  right: -25vmax; top: 18vh;
  background: radial-gradient(circle, rgba(20,241,149,.28), transparent 65%);
}}
.bg span:nth-child(3) {{
  left: 18vw; bottom: -35vmax;
  background: radial-gradient(circle, rgba(99,102,241,.38), transparent 65%);
}}
.wrap {{ position: relative; z-index: 1; max-width: 960px; margin: 0 auto; padding: 0 1.25rem 4rem }}
nav {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 1.1rem 0; border-bottom: 1px solid var(--line); flex-wrap: wrap; gap: .6rem;
}}
.logo {{ font-weight: 800; letter-spacing: -.03em; font-size: 1.2rem }}
.logo em {{
  font-style: normal;
  background: linear-gradient(120deg, var(--b), var(--a));
  -webkit-background-clip: text; background-clip: text; color: transparent;
}}
nav a {{ color: var(--muted); text-decoration: none; margin-left: 1rem; font-size: .92rem }}
nav a:hover {{ color: var(--text) }}
.hero {{ text-align: center; padding: 2.8rem 0 1.5rem }}
.badge {{
  display: inline-block; font-size: .72rem; letter-spacing: .07em; text-transform: uppercase;
  color: var(--a); border: 1px solid rgba(20,241,149,.35); padding: .35rem .75rem;
  border-radius: 999px; margin-bottom: 1rem;
}}
h1 {{
  font-size: clamp(2rem, 5.5vw, 3.1rem); font-weight: 800; letter-spacing: -.04em;
  line-height: 1.12; margin-bottom: 1rem;
}}
h1 span {{
  background: linear-gradient(135deg, #a78bfa, #14f195);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}}
.sub {{ color: var(--muted); font-size: 1.05rem; max-width: 560px; margin: 0 auto 1.4rem }}
.sub a {{ color: var(--a) }}
.cta {{ display: flex; flex-wrap: wrap; gap: .7rem; justify-content: center; margin-bottom: 1.25rem }}
.btn {{
  display: inline-block; padding: .75rem 1.35rem; border-radius: .75rem;
  font-weight: 600; text-decoration: none; font-size: .95rem; border: none; cursor: pointer;
}}
.btn-p {{ background: linear-gradient(135deg, var(--b), var(--c)); color: #fff }}
.btn-g {{ background: rgba(20,241,149,.12); color: var(--a); border: 1px solid rgba(20,241,149,.35) }}
.btn-o {{ border: 1px solid var(--line); color: var(--text); background: transparent }}
.check {{
  max-width: 560px; margin: 0 auto 1.5rem; text-align: left;
  background: var(--card); border: 1px solid var(--line); border-radius: 1rem;
  padding: 1.15rem 1.2rem;
}}
.check h3 {{ font-size: .95rem; margin-bottom: .35rem }}
.check form {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .65rem }}
.check input {{
  flex: 1; min-width: 200px; padding: .7rem .9rem; border-radius: .65rem;
  border: 1px solid var(--line); background: #0c121c; color: var(--text);
  font-family: ui-monospace, monospace; font-size: .85rem;
}}
.grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem; margin: 1.5rem 0;
}}
.card {{
  background: var(--card); border: 1px solid var(--line); border-radius: 1rem;
  padding: 1.15rem 1.2rem;
}}
.card h3 {{ font-size: .95rem; margin-bottom: .4rem }}
.card p {{ color: var(--muted); font-size: .88rem }}
.card code {{ color: var(--a); font-size: .8rem }}
pre {{
  background: #0c121c; border: 1px solid var(--line); border-radius: .85rem;
  padding: 1rem 1.1rem; overflow-x: auto; font-size: .82rem; color: #c7d2fe; margin-top: 1rem;
}}
section {{ margin: 2rem 0 }}
section h2 {{ font-size: 1.15rem; margin-bottom: .75rem }}
.muted {{ color: var(--muted); font-size: .9rem }}
.donate-box {{
  background: linear-gradient(145deg, rgba(153,69,255,.14), rgba(20,241,149,.08));
  border: 1px solid rgba(20,241,149,.32); border-radius: 1rem; padding: 1.25rem 1.3rem;
}}
.sol {{
  word-break: break-all; color: var(--a);
  font-family: ui-monospace, monospace; font-size: .85rem; margin-top: .65rem; user-select: all;
}}
.copy-row {{ margin-top: .75rem; display: flex; flex-wrap: wrap; gap: .5rem; align-items: center }}
.copy-btn {{
  cursor: pointer; border: 1px solid rgba(20,241,149,.4); background: rgba(20,241,149,.1);
  color: var(--a); border-radius: .5rem; padding: .4rem .85rem; font-size: .85rem; font-weight: 600;
}}
footer {{
  margin-top: 3rem; padding-top: 1.25rem; border-top: 1px solid var(--line);
  color: var(--muted); font-size: .85rem; text-align: center;
}}
footer a {{ color: var(--a) }}
{CHECK_CSS}
{PROOF_CSS}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<symbol id="i-x" viewBox="0 0 24 24"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></symbol>
<symbol id="i-gh" viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></symbol>
</svg>
<div class="bg" aria-hidden="true"><span></span><span></span><span></span></div>
<div class="wrap">
  <nav>
    <div class="logo">TVibe<em> Signal</em></div>
    <div class="navlinks">
      <a href="/agents">Agents</a>
      <a href="/stats">Stats</a>
      <a href="/docs">API</a>
      <a href="#donate">Donate</a>
      <a class="pill" href="{GITHUB_URL}" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-gh"/></svg>GitHub</a>
      <a class="pill" href="{X_URL}" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-x"/></svg>X</a>
    </div>
  </nav>

  <header class="hero">
    <div class="badge">Free · Open source · Measured in public</div>
    <h1>Solana token signals<br>for <span>AI agents</span></h1>
    <p class="sub">
      One request → verdict, reasons, and context.
      Track record is public on <a href="/stats">/stats</a>.
      Heuristics only — not financial advice.
    </p>
    <div class="cta">
      <a class="btn btn-g" href="/stats">Live accuracy</a>
      <a class="btn btn-o" href="/mcp">MCP</a>
      <a class="btn btn-o" href="/agents">For agents</a>
    </div>
  </header>

  <div class="check" id="check">
    <h3>Check a token</h3>
    <p class="muted" style="font-size:.88rem">Paste a Solana mint address (CA)</p>
    <form id="f" action="/omni" method="get">
      <input id="mint" name="mint" type="text" required spellcheck="false" autocomplete="off"
        autocapitalize="off" autocorrect="off"
        placeholder="So1111… or any token mint" aria-label="Token mint address" />
      <button id="paste" type="button" class="btn btn-o">Paste</button>
      <button id="go" type="submit" class="btn btn-p">Check</button>
    </form>
    <div class="tryrow">Try
      <button type="button" class="r-try" data-mint="So11111111111111111111111111111111111111112">SOL</button>
      <button type="button" class="r-try" data-mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v">USDC</button>
      <button type="button" class="r-try" data-mint="33jENUQnjoitkMFpvNJcSHyLAHFWJuHwT6E3E8CNpump">Dope</button>
      <button type="button" class="r-try" data-mint="CbcyNo7m1amFWqEQm2m4PLv1UNvpcL3C1Ujm6AkzpKoU">e/acc</button>
    </div>
    <div id="out" aria-live="polite"></div>
  </div>

  <div class="strip">
    <div><b>Free</b><span>no key needed</span></div>
    <div><b>Open source</b><span>self-host anytime</span></div>
    <div><b>Public record</b><span>accuracy on /stats</span></div>
    <div><b>MCP ready</b><span>Claude, Cursor, agents</span></div>
  </div>

  <section id="proof">
    <h2>Live accuracy <small>measured on real verdicts, not a backtest</small></h2>
    <div class="pf-tabs" id="pf-tabs"></div>
    <div id="pf-body"><p class="muted">Loading live accuracy...</p></div>
    <p class="muted" style="margin-top:.7rem;font-size:.85rem"><a href="/stats" style="color:var(--a)">Full numbers</a> · <a href="/attest" style="color:var(--a)">Verify signed verdicts</a></p>
  </section>

  <div class="grid">
    <div class="card">
      <h3>Primary call</h3>
      <p><code>GET /omni?mint=…</code></p>
      <p>Verdict + decision block agents should trust first.</p>
    </div>
    <div class="card">
      <h3>Prove it</h3>
      <p><code>GET /stats</code></p>
      <p>Precision / recall on judged outcomes — not marketing claims.</p>
    </div>
    <div class="card">
      <h3>MCP</h3>
      <p><code>omni(mint)</code></p>
      <p>Wire into Cursor, Claude, or your agent runtime.</p>
    </div>
    <div class="card">
      <h3>Self-host</h3>
      <p><code>github.com/TVibex402/signal-api</code></p>
      <p>Same code. Your Redis starts its own track record.</p>
    </div>
  </div>

  <section>
    <h2>Quick start</h2>
    <pre>curl -s "{BASE}/omni?mint=So11111111111111111111111111111111111111112" | jq .decision</pre>
    <p class="muted" style="margin-top:.75rem">
      Batch: <code>/signals?mints=a,b,c&amp;view=compact</code> (max 10). Cache the same mint 15–30s.
    </p>
  </section>

  <section>
    <h2>Fair use</h2>
    <div class="card">
      <p class="muted">
        Public host is <strong style="color:var(--text)">free</strong>.
        ~30 req/min without a key · batch max 10 · please cache.
        Heavy traffic → self-host or slow down on HTTP 429.
        <a href="/support" style="color:var(--a)">/support</a>
      </p>
    </div>
  </section>

  <section id="donate">
    <h2>Optional tip (never required)</h2>
    <div class="donate-box">
      <p class="muted">{DONATE_NOTE}</p>
      <p class="sol">{DONATE_SOL}</p>
      <div class="copy-row">
        <button type="button" class="copy-btn"
          onclick="navigator.clipboard.writeText('{DONATE_SOL}').then(()=>{{this.textContent='Copied'}}).catch(()=>{{}})">
          Copy address
        </button>
        <a class="btn btn-o" style="padding:.4rem .85rem;font-size:.85rem" href="/donate">/donate JSON</a>
      </div>
    </div>
  </section>

  <footer>
    <p>Not financial advice. Heuristics for agents and research.</p>
    <p style="margin-top:.4rem">
      <a href="/support">/support</a> ·
      <a href="/agents">/agents</a> ·
      <a href="/llms.txt">llms.txt</a> ·
      <a href="/attest">/attest</a> ·
      <a href="{GITHUB_URL}" target="_blank" rel="noopener noreferrer">source</a> ·
      <a class="fx" href="{X_URL}" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-x"/></svg>@realTVibe</a>
    </p>
  </footer>
</div>
<script>{CHECK_JS}</script>
<script>{PROOF_JS}</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home_v287():
    return HOME_HTML


@app.get("/donate", tags=["product"])
async def donate_json():
    return {
        "brand": BRAND,
        "free": True,
        "required": False,
        "asset": "SOL",
        "address": DONATE_SOL,
        "note": DONATE_NOTE,
        "fair_use": "/support",
        "self_host": GITHUB_URL,
        "x": X_URL,
        "disclaimer": "Not financial advice. Donations are voluntary tips for hosting/RPC only.",
        "version": VERSION,
    }


@app.get("/support", response_class=PlainTextResponse, tags=["product"])
async def support_fair_use():
    return FAIR_USE.strip() + "\n"


print(f"[part104] v{VERSION} {BRAND} home + market data from /signal + track record + typography + market tiles + sell cost + X link -> GET /")

# --- part105 ---
# part105.py - Verifiable verdicts (v2.88.0)
# Every new /omni verdict gets an Ed25519 signature and is chained by hash to the previous one.
# Once a day the head of the chain is written to Solana as a memo from the same address,
# so anyone can check that a verdict existed before its outcome was known.
# v2.88.1: also keeps decision.verdict consistent with a capped verdict (see _normalize).
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
_NORM_ON = os.environ.get("NORMALIZE_VERDICT", "1") != "0"
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
    last_err="", last_try=0.0, anchoring=False, cache={}, last_flush=0,
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
        items = r.json()
        for x in items:  # Upstash reports a rejected command as {"error": ...} with HTTP 200
            if isinstance(x, dict) and x.get("error"):
                raise RuntimeError("redis rejected a command: " + str(x["error"])[:120])
        return [x.get("result") for x in items]


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
        canon = _canon(rec)
        h = hashlib.sha256((prev + canon).encode()).hexdigest()
        sig = S.sign(bytes.fromhex(h)).hex()
        S.head, S.n, S.day_n = h, S.n + 1, S.day_n + 1
        S.buf.append(["RPUSH", "tv:attest:day:" + day, _canon({"rec": rec, "c": canon, "prev": prev, "h": h, "sig": sig})])
        att = {"record": rec, "canon": canon, "prev": prev, "hash": h, "sig": sig, "pubkey": S.pubs, "chain_n": S.n}
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
        S.last_flush = int(time.time())
        if S.last_err.startswith("redis:"):
            S.last_err = ""
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
        S.last_try = time.time() + 3000  # back off about 1 hour (e.g. address not funded yet)
    finally:
        S.anchoring = False


# ---------------------------------------------------------------- keep decision.verdict consistent
# Some responses say "Verdict capped from ok to caution" (and /signal has a capped top-level
# "verdict") while decision.verdict still says "ok". Agents read decision.verdict first, so we
# make it match. Only ever downgrades (more cautious); never upgrades.
_CAP_RE = re.compile(r"Verdict capped from (ok|caution|avoid) to (ok|caution|avoid)", re.I)
_RANK = {"ok": 0, "caution": 1, "avoid": 2}


def _normalize(d):
    dec = d.get("decision")
    if not isinstance(dec, dict):
        return False
    cur, top = dec.get("verdict"), d.get("verdict")
    target = None
    if d.get("verdict_capped_by") and top in _RANK and top != cur:
        target = top
    if target is None:
        m = _CAP_RE.search(str(d.get("summary") or ""))
        if m:
            target = m.group(2).lower()
    if target in _RANK and cur in _RANK and _RANK[target] > _RANK[cur]:
        dec["verdict_raw"] = cur
        dec["verdict"] = target
        if d.get("verdict_capped_by"):
            dec["capped_by"] = d["verdict_capped_by"]
        return True
    return False


# ---------------------------------------------------------------- middleware: normalize + sign /omni
async def _inject(start, body, path="/omni"):
    if start.get("status") != 200:
        return body
    hs = {k.lower(): v for k, v in start["headers"]}
    if b"content-encoding" in hs or b"json" not in hs.get(b"content-type", b""):
        return body
    d = json.loads(body)
    if not isinstance(d, dict):
        return body
    changed = _normalize(d) if _NORM_ON else False
    if path == "/omni" and _ATT_ON and "attestation" not in d:
        await _load()
        if S.ok:
            att = await _attest(d)
            if att:
                d["attestation"] = att
                changed = True
    if not changed:
        return body
    return json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class _AttestMW:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path") if scope["type"] == "http" else None
        if not (_ATT_ON or _NORM_ON) or path not in ("/omni", "/signal") or scope.get("method") != "GET":
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
                body = await _inject(start, body, path)
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
    "1. hash = sha256(prev + canon) where canon is the exact string in the 'canon' field (the record as JSON with sorted keys, no spaces).",
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
        "anchored_days": len(S.anchors), "unsaved_records": len(S.buf), "last_saved_at": S.last_flush or None,
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

# --- part106 ---
# part106.py - "Cost to sell" block as a standalone add-on (v2.88.2)
# Works on top of any part104 that serves the home page from the global HOME_HTML.
# It injects its own style + script; it does not need part104 to be changed.
# Loader line (after part104/part105, before part7):  ("part106.py", 0, "SKIP"),

EXIT_ADDON = r'''<!--cost-to-sell-addon-->
<style>
#csell{margin-top:1.2rem}
#csell h4{font-size:1.15rem;font-weight:700;margin:0 0 .55rem;display:flex;align-items:center;gap:.5rem;letter-spacing:-.01em}
#csell h4::before{content:"";width:4px;height:1.1em;border-radius:3px;background:linear-gradient(#9945ff,#14f195)}
#csell h4 small{font-weight:500;font-size:.75rem;color:#9db0ca}
.cs-chips{display:flex;flex-wrap:wrap;gap:.45rem;margin-bottom:.5rem}
.cs-chip{border:1px solid rgba(40,56,78,.9);border-radius:999px;padding:.25rem .75rem;font-size:.84rem;font-weight:600;color:#9db0ca;background:rgba(10,18,32,.8)}
.cs-chip.ok{color:#14f195;border-color:rgba(20,241,149,.4);background:rgba(11,32,22,.8)}
.cs-chip.warn{color:#f5b73b;border-color:rgba(245,183,59,.45);background:rgba(34,26,9,.8)}
.cs-chip.bad{color:#f2564f;border-color:rgba(242,86,79,.5);background:rgba(36,14,15,.8)}
.cs-grid{display:grid;grid-template-columns:auto 1fr auto;gap:.55rem .8rem;align-items:center;font-size:.95rem}
.cs-bar{height:8px;border-radius:99px;background:#0a1220;overflow:hidden}
.cs-bar i{display:block;height:100%;border-radius:99px}
.cs-bar i.ok{background:#14f195}.cs-bar i.warn{background:#f5b73b}.cs-bar i.bad{background:#f2564f}
.cs-grid b{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9rem}
.cs-grid b.ok{color:#14f195}.cs-grid b.warn{color:#f5b73b}.cs-grid b.bad{color:#f2564f}
.cs-na{grid-column:2/4;color:#9db0ca}
.cs-note{font-size:.84rem;color:#9db0ca;margin:.55rem 0 0;line-height:1.5}
.cs-btn{cursor:pointer;border:1px solid rgba(40,56,78,.9);background:rgba(10,18,32,.8);color:#e8eef6;border-radius:999px;padding:.25rem .75rem;font-size:.8rem}
.cs-btn:hover{border-color:#14f195}
.cs-warn{background:rgba(17,27,43,.9);border:1px solid rgba(245,183,59,.4);border-radius:.8rem;padding:.6rem .85rem;margin-top:.6rem;font-size:.9rem}
.cs-warn b{color:#ffc94d}
.cs-warn li{margin:.25rem 0}
</style>
<script>
(function(){
var out=document.getElementById('out');if(!out)return;
var cache={},busy={},timer=null;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function isNum(v){return typeof v==='number'&&isFinite(v)}
function find(o,re,pred,d){d=d||0;if(!o||typeof o!=='object'||d>4)return undefined;var k,v;for(k in o){if(re.test(k)){v=o[k];if(pred(v))return v}}for(k in o){v=o[k];if(v&&typeof v==='object'){var r=find(v,re,pred,d+1);if(r!==undefined)return r}}return undefined}
function usd(n){return '$'+Number(n).toLocaleString('en-US',{maximumFractionDigits:0})}
function lossPct(v,k){v=Number(v);if(/bps/i.test(k))return v/100;if(/pct|percent/i.test(k))return v;return Math.abs(v)<=1?v*100:v}
function levels(lv){
  if(!Array.isArray(lv))return [];
  return lv.filter(function(it){return it&&typeof it==='object'}).map(function(it){
    var ks=Object.keys(it);
    var sk=ks.filter(function(k){return /usd|size|amount|notional/i.test(k)&&isNum(it[k])})[0];
    var lk=ks.filter(function(k){return /loss/i.test(k)&&isNum(it[k])})[0]||ks.filter(function(k){return /impact|slip|cost/i.test(k)&&isNum(it[k])})[0];
    var rk=ks.filter(function(k){return /receive|returns|out_usd/i.test(k)&&isNum(it[k])})[0];
    return {size:sk?it[sk]:null,loss:lk?it[lk]:null,lk:lk,status:it.status,recv:rk?it[rk]:null};
  });
}
function vcls(v){v=String(v||'').toLowerCase();return v==='ok'?'ok':(v==='caution'?'warn':(v==='avoid'?'bad':''))}
function retryBtn(){return ' <button type="button" class="cs-btn" data-cs="retry">Retry</button>'}
function build(x){
  var head='<h4>Cost to sell <small>Jupiter quote</small></h4>';
  if(!x||typeof x!=='object'||x.__error)return head+'<p class="cs-note" style="margin-top:0">Sell cost could not be loaded.'+retryBtn()+'</p>';
  var ex=x.exit&&typeof x.exit==='object'?x.exit:null;
  var lv=levels(ex?ex.levels:null),any=lv.some(function(z){return isNum(z.loss)});
  var grade=find(x,/^(exit_)?grade$/i,function(q){return typeof q==='string'});
  var overall=find(x,/^(overall|overall_verdict|combined_verdict|verdict)$/i,function(q){return typeof q==='string'});
  var h=head;
  if(ex&&ex.available===false&&!any){
    return h+'<p class="cs-note" style="margin-top:0">Sell cost is unavailable right now'+(ex.reason?': '+esc(ex.reason):'')+'.'+retryBtn()+'</p>';
  }
  if(!any&&!grade)return h+'<p class="cs-note" style="margin-top:0">No sell cost data for this token.'+retryBtn()+'</p>';
  var gc=/good|ok|low/i.test(grade||'')?'ok':(/fair|medium|mid|warn|caution/i.test(grade||'')?'warn':(grade?'bad':''));
  h+='<div class="cs-chips">'+(grade?'<span class="cs-chip '+gc+'">Exit grade: '+esc(grade)+'</span>':'')+(overall?'<span class="cs-chip '+vcls(overall)+'">Overall: '+esc(overall)+'</span>':'')+'</div>';
  if(lv.length){
    h+='<div class="cs-grid">'+lv.slice(0,6).map(function(z){
      var lab='<span>Sell '+(z.size!=null?usd(z.size):'')+(isNum(z.recv)?' <small style="color:#9db0ca">\u2192 '+usd(z.recv)+'</small>':'')+'</span>';
      if(!isNum(z.loss))return lab+'<span class="cs-na">n/a'+(z.status?' ('+esc(z.status)+')':'')+'</span>';
      var l=lossPct(z.loss,z.lk),c=l<3?'ok':(l<8?'warn':'bad');
      return lab+'<div class="cs-bar"><i class="'+c+'" style="width:'+Math.min(100,Math.max(3,l*4))+'%"></i></div><b class="'+c+'">'+(Math.round(l*10)/10)+'% lost</b>';
    }).join('')+'</div>';
  }
  h+='<p class="cs-note">A quote does not prove a real sell will succeed. Loss includes fees, price impact and price differences.</p>';
  if(Array.isArray(x.reasons)&&x.reasons.length)h+='<div class="cs-warn"><b>Exit check</b><ul>'+x.reasons.map(function(r){return '<li>'+esc(r)+'</li>'}).join('')+'</ul></div>';
  return h;
}
function mintOf(res){var m=res.querySelector('.r-mint');var t=m?String(m.textContent||'').trim():'';if(t)return t;try{return new URLSearchParams(location.search).get('mint')}catch(e){return null}}
function hasOwn(res){var hs=res.querySelectorAll('.r-h');for(var i=0;i<hs.length;i++){if(/^Cost to sell/i.test(String(hs[i].textContent||'').trim()))return true}return false}
function place(res,html){
  var wrap=document.createElement('div');wrap.id='csell';wrap.innerHTML=html;
  var old=res.querySelector('#csell');
  if(old){old.parentNode.replaceChild(wrap,old);return}
  var anchor=null,hs=res.querySelectorAll('.r-h');
  for(var i=0;i<hs.length;i++){if(/^(Agent debate|Next steps)/i.test(String(hs[i].textContent||'').trim())){anchor=hs[i];break}}
  if(!anchor)anchor=res.querySelector('.r-tools');
  if(anchor&&anchor.parentNode)anchor.parentNode.insertBefore(wrap,anchor);else res.appendChild(wrap);
}
function load(mint){
  busy[mint]=1;
  fetch('/exit?mint='+encodeURIComponent(mint),{headers:{'Accept':'application/json'}})
   .then(function(r){return r.ok?r.json():{__error:1}}).catch(function(){return {__error:1}})
   .then(function(j){cache[mint]=j;busy[mint]=0;schedule()});
}
function inject(){
  var res=out.querySelector('.res');if(!res||hasOwn(res)&&!res.querySelector('#csell'))return;
  var mint=mintOf(res);if(!mint)return;
  if(cache[mint]!==undefined){
    var cur=res.querySelector('#csell');
    var html=build(cache[mint]);
    if(!cur||cur.getAttribute('data-m')!==mint+':'+(cache[mint].__error?'e':'d')){place(res,html);var n=res.querySelector('#csell');if(n)n.setAttribute('data-m',mint+':'+(cache[mint].__error?'e':'d'))}
    return;
  }
  if(!res.querySelector('#csell'))place(res,'<h4>Cost to sell <small>Jupiter quote</small></h4><p class="cs-note" style="margin-top:0">Checking sell cost...</p>');
  if(!busy[mint])load(mint);
}
function schedule(){if(timer)return;timer=setTimeout(function(){timer=null;try{inject()}catch(e){}},60)}
out.addEventListener('click',function(e){
  var b=e.target&&e.target.closest?e.target.closest('[data-cs="retry"]'):null;if(!b)return;
  var res=out.querySelector('.res');if(!res)return;var mint=mintOf(res);if(!mint)return;
  delete cache[mint];place(res,'<h4>Cost to sell <small>Jupiter quote</small></h4><p class="cs-note" style="margin-top:0">Checking sell cost...</p>');load(mint);
});
if(window.MutationObserver)new MutationObserver(schedule).observe(out,{childList:true,subtree:true});
schedule();
})();
</script>
'''

try:
    if "<!--cost-to-sell-addon-->" not in HOME_HTML:
        HOME_HTML = HOME_HTML.replace("</body>", EXIT_ADDON + "</body>", 1)
        print("[part106] cost-to-sell add-on injected into the home page")
    else:
        print("[part106] add-on already present")
except NameError:
    print("[part106] HOME_HTML not found - part104 must load before part106")

# --- part107 ---
# part107.py - /verify page + "results by source" box (v2.89.0)
# 1) GET /verify: anyone can paste a signed /omni response and check it in the browser.
# 2) Adds a "results by source" box to the Live accuracy section of the home page
#    (answers the "only tokens people query" criticism with the same stats you already publish).
# Works on top of your current part104/part105; nothing in them needs to change.
# Loader line (after part105/part106, before part7):  ("part107.py", 0, "SKIP"),
from fastapi.responses import HTMLResponse

VERSION = "2.89.0"
app.version = VERSION
app.openapi_schema = None

VERIFY_HTML = r'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark"><meta name="theme-color" content="#070b12">
<title>Verify a TVibe verdict</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#070b12;color:#e8eef6;font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:1.2rem}
.wrap{max-width:720px;margin:0 auto}
a{color:#14f195}
h1{font-size:1.7rem;letter-spacing:-.03em;margin:.8rem 0 .3rem}
p.sub{color:#9db0ca;margin-bottom:1rem}
.card{background:rgba(15,22,34,.92);border:1px solid rgba(40,56,78,.9);border-radius:1rem;padding:1rem;margin-top:.8rem}
label{display:block;font-size:.85rem;color:#9db0ca;margin-bottom:.35rem}
input,textarea{width:100%;background:#0c121c;color:#e8eef6;border:1px solid rgba(40,56,78,.9);border-radius:.65rem;padding:.65rem .8rem;font:.85rem ui-monospace,Menlo,Consolas,monospace}
textarea{min-height:170px;resize:vertical}
.row{display:flex;gap:.5rem}
button{cursor:pointer;border:0;border-radius:.65rem;padding:.65rem 1.1rem;font-weight:700;font-size:.95rem}
.p{background:linear-gradient(135deg,#9945ff,#6366f1);color:#fff}
.o{background:transparent;border:1px solid rgba(40,56,78,.9);color:#e8eef6}
.res{font-size:1.3rem;font-weight:800;margin:.2rem 0 .6rem}
.res.ok{color:#3df5ad}.res.warn{color:#ffc94d}.res.bad{color:#ff6b64}
ul{list-style:none}
li{display:flex;gap:.6rem;padding:.4rem 0;border-top:1px solid rgba(40,56,78,.6);font-size:.92rem;word-break:break-word}
li b{width:1.3rem;flex:none;text-align:center}
li.ok b{color:#3df5ad}li.bad b{color:#ff6b64}li.warn b{color:#ffc94d}li.info b{color:#9db0ca}
.note{color:#9db0ca;font-size:.85rem;margin-top:.6rem}
</style></head><body><div class="wrap">
<p><a href="/">&larr; TVibe Signal</a></p>
<h1>Verify a verdict</h1>
<p class="sub">Every /omni verdict is signed. Check it here without trusting the server: all checks run in your browser.</p>
<div class="card">
<label for="mint">Option 1: fetch a live verdict by mint address and verify it</label>
<div class="row"><input id="mint" placeholder="Solana mint address" spellcheck="false" autocomplete="off" autocapitalize="off"><button id="fetch" class="p">Fetch</button></div>
</div>
<div class="card">
<label for="raw">Option 2: paste a saved /omni response (or just its "attestation" object)</label>
<textarea id="raw" spellcheck="false" placeholder='{"mint": "...", "decision": {...}, "attestation": {...}}'></textarea>
<div class="row" style="margin-top:.6rem"><button id="go" class="p">Verify</button></div>
</div>
<div class="card" id="out"><p class="note">The result appears here.</p></div>
<p class="note">A valid signature shows that this verdict was produced by the holder of the signing key, unchanged. It does not say the verdict is correct. Accuracy is on the home page.</p>
</div>
<script>
(function(){
var $=function(s){return document.getElementById(s)};
var B='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function b58d(s){var n=BigInt(0),i;for(i=0;i<s.length;i++){var k=B.indexOf(s[i]);if(k<0)throw new Error('bad base58');n=n*BigInt(58)+BigInt(k)}var hex=n.toString(16);if(hex.length%2)hex='0'+hex;var by=[];for(i=0;i<hex.length;i+=2)by.push(parseInt(hex.substr(i,2),16));var z=0;while(z<s.length&&s[z]==='1')z++;if(n===BigInt(0))by=[];return new Uint8Array(new Array(z).fill(0).concat(by))}
function hexBytes(h){if(!/^[0-9a-f]*$/i.test(h)||h.length%2)throw new Error('bad hex');var o=new Uint8Array(h.length/2);for(var i=0;i<o.length;i++)o[i]=parseInt(h.substr(i*2,2),16);return o}
async function sha(t){var d=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(t));return Array.from(new Uint8Array(d)).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join('')}
async function check(raw,livePub){
  var steps=[],ok=true,unk=false,j;
  function add(t,m){steps.push({t:t,m:m})}
  try{j=JSON.parse(raw)}catch(e){return {steps:[{t:'bad',m:'That is not valid JSON.'}],ok:false}}
  var a=(j&&j.attestation)?j.attestation:j;
  var miss=['canon','prev','hash','sig','pubkey'].filter(function(k){return !a||typeof a[k]!=='string'});
  if(miss.length)return {steps:[{t:'bad',m:'Missing fields: '+miss.join(', ')+'. Paste a full /omni response or its "attestation" object.'}],ok:false};
  var rec;try{rec=JSON.parse(a.canon)}catch(e){return {steps:[{t:'bad',m:'The signed record is not valid JSON.'}],ok:false}}
  add('ok','Record: '+rec.verdict+' for '+rec.mint+' (risk '+rec.risk+') signed at '+new Date(rec.ts*1000).toISOString()+'.');
  if(j.attestation&&j.decision&&j.mint){
    if(rec.mint===j.mint&&rec.verdict===j.decision.verdict)add('ok','The signed verdict matches the verdict shown in the response.');
    else{add('bad','The signed record does not match the verdict shown in the response.');ok=false}
  }
  try{
    var hex=await sha(a.prev+a.canon);
    if(hex===a.hash)add('ok','Hash matches: sha256(prev + record).');else{add('bad','Hash does not match the record.');ok=false}
  }catch(e){add('warn','This browser cannot compute SHA-256 here.');unk=true}
  try{
    var key=await crypto.subtle.importKey('raw',b58d(a.pubkey),{name:'Ed25519'},false,['verify']);
    var v=await crypto.subtle.verify({name:'Ed25519'},key,hexBytes(a.sig),hexBytes(a.hash));
    if(v)add('ok','Ed25519 signature is valid for '+a.pubkey+'.');else{add('bad','The signature is invalid.');ok=false}
  }catch(e){add('warn','This browser cannot check Ed25519 signatures (try a recent Chrome or Safari).');unk=true}
  if(livePub){
    if(livePub===a.pubkey)add('ok','The public key is the one this server publishes at /attest.');
    else{add('bad','The public key differs from the key this server publishes. This may be forged.');ok=false}
  }else add('warn','Could not read /attest to compare the public key.');
  add('info','Not checked here: the link to the previous verdict, and the daily Solana anchor (look for a memo from this address on Solscan).');
  return {steps:steps,ok:ok,unk:unk,rec:rec,pub:a.pubkey};
}
function show(r){
  var icon={ok:'\u2714',bad:'\u2716',warn:'!',info:'i'};
  var head=r.ok&&!r.unk?'<div class="res ok">Verified</div>':(r.ok?'<div class="res warn">Could not fully verify</div>':'<div class="res bad">Not valid</div>');
  $('out').innerHTML=head+'<ul>'+r.steps.map(function(s){return '<li class="'+s.t+'"><b>'+icon[s.t]+'</b><span>'+esc(s.m)+'</span></li>'}).join('')+'</ul>'
   +(r.pub?'<p class="note"><a href="https://solscan.io/account/'+encodeURIComponent(r.pub)+'" target="_blank" rel="noopener noreferrer">View signer address on Solscan</a></p>':'');
}
async function livePub(){try{var r=await fetch('/attest',{headers:{Accept:'application/json'}});var j=await r.json();return j&&j.pubkey?j.pubkey:null}catch(e){return null}}
$('go').addEventListener('click',async function(){show(await check($('raw').value.trim(),await livePub()))});
$('fetch').addEventListener('click',async function(){
  var m=$('mint').value.trim();if(!m)return;
  $('out').innerHTML='<p class="note">Fetching a live verdict...</p>';
  try{var r=await fetch('/omni?mint='+encodeURIComponent(m),{headers:{Accept:'application/json'}});var t=await r.text();
    try{$('raw').value=JSON.stringify(JSON.parse(t),null,2)}catch(e){$('raw').value=t}
    show(await check(t,await livePub()))}
  catch(e){$('out').innerHTML='<div class="res bad">Could not fetch the verdict.</div>'}
});
window.__tvCheck=check;
})();
</script></body></html>
'''

SOURCE_ADDON = r'''<!--source-breakdown-addon-->
<script>
(function(){
var body=document.getElementById('pf-body');if(!body)return;
var D=null,timer=null;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function num(x){return typeof x==='number'&&isFinite(x)}
function r1(x){return Math.round(x*10)/10}
function jget(u){return fetch(u,{headers:{'Accept':'application/json'}}).then(function(r){return r.ok?r.json():null}).catch(function(){return null})}
function bar(v){return '<div class="pf-bar"><i class="acc" style="width:'+Math.max(2,Math.min(100,v))+'%"></i></div>'}
function box(){
  var S=D&&D.by_source;if(!S)return '';
  var u=S.user,h='<div class="pf-box" id="pf-src"><h3>Is it only the easy cases? <small>results by where the token came from</small></h3>';
  var av=u&&u.verdicts&&u.verdicts.avoid;
  if(u&&num(u.bad_outcome_rate_pct)&&av&&num(av.bad_outcome_rate_pct))
    h+='<p class="pf-lead" style="margin:.2rem 0 .6rem">On the <b>'+esc(u.n)+'</b> tokens people really asked about, avoid was right <b>'+r1(av.bad_outcome_rate_pct)+'%</b> against a <b>'+r1(u.bad_outcome_rate_pct)+'%</b> base rate (+'+r1(av.bad_outcome_rate_pct-u.bad_outcome_rate_pct)+' points).</p>';
  var names=[['user','Asked by users'],['seed_new','New pairs'],['seed_trending','Trending'],['seed_boost','Boosted'],['seed_profile','Profiles'],['untagged','Older']];
  names.forEach(function(x){
    var s=S[x[0]];if(!s)return;var has=num(s.bad_outcome_rate_pct);
    h+='<div class="pf-row"><span style="font-size:.82rem">'+x[1]+'</span>'+(has?bar(s.bad_outcome_rate_pct):'<div class="pf-bar"></div>')+'<b>'+(has?r1(s.bad_outcome_rate_pct)+'%':'n&lt;20')+'</b><small>n='+esc(s.n)+(s.ci95_pct&&s.ci95_pct.length===2?' \u00B7 95% range '+esc(s.ci95_pct[0])+' to '+esc(s.ci95_pct[1])+'%':'')+'</small></div>';
  });
  return h+'<p class="pf-lead" style="font-size:.82rem;color:#9db0ca;margin:.4rem 0 0">Share of tokens that ended badly within 24h. Rates stay hidden under 20 samples. Auto-sampled tokens are not chosen by users, so they are shown separately and not mixed into the headline.</p></div>';
}
function inject(){
  if(!D||!body.firstChild||body.querySelector('#pf-src'))return;
  var t=document.createElement('div');t.innerHTML=box();var node=t.firstChild;if(!node)return;
  var det=body.querySelector('details');
  if(det&&det.parentNode)det.parentNode.insertBefore(node,det);else body.appendChild(node);
}
function schedule(){if(timer)return;timer=setTimeout(function(){timer=null;try{inject()}catch(e){}},60)}
if(window.MutationObserver)new MutationObserver(schedule).observe(body,{childList:true});
jget('/stats').then(function(j){return (j&&j.by_source)?j:jget('/accuracy')}).then(function(j){if(j&&j.by_source){D=j;schedule()}});
})();
</script>
'''


@app.get("/verify", response_class=HTMLResponse, include_in_schema=False)
async def verify_page():
    return VERIFY_HTML


try:
    _h = HOME_HTML
    if "<!--source-breakdown-addon-->" not in _h:
        _h = _h.replace("</body>", SOURCE_ADDON + "</body>", 1)
    if 'href="/verify"' not in _h and '<a href="/attest">/attest</a>' in _h:
        _h = _h.replace('<a href="/attest">/attest</a>', '<a href="/attest">/attest</a> \u00b7\n      <a href="/verify">/verify</a>', 1)
    HOME_HTML = _h
    print("[part107] v%s /verify page + results-by-source box" % VERSION)
except NameError:
    print("[part107] v%s /verify page only (HOME_HTML not found)" % VERSION)

# --- part108 ---
# ---------- v2.90.1: Remaining plan — outcome labels + agent honesty (reviewed) ----------
# 1) resolve_due -> on_outcome_for_si / shadow_avoid / prerug labels (judged > 0)
# 2) decision.valid_for_s always set
# 3) would_change_my_mind filled from unknowns/blockers when empty
# 4) survival_note: pointer only (no new DNA/persona)
# Review fixes vs v2.90.0:
#   - never label a token "bad" because the price fetch FAILED (old code did: failed fetch -> pair None -> bad)
#   - SOL no longer added to the DexScreener request (it crowded out the real tokens and was never used)
#   - pick_best_pair errors fall back to the highest-liquidity pair instead of failing every token
#   - snapshots with no usable start price AND no start liquidity are skipped (cannot be judged)
#   - each snapshot is labelled at most once; callbacks are called once (no blind retry on TypeError)
VERSION = "2.90.1"
app.version = VERSION
app.openapi_schema = None

import inspect
import time
from typing import Any, Dict, List, Optional

_prev_resolve_108 = resolve_due
_LABELED_108: set = set()
_STAT_108 = {"labeled": 0, "bad": 0, "skipped_unjudgeable": 0, "skipped_fetch_failed": 0}


def _call_cb(cb, client, mint, bad, meta):
    """Call an outcome callback once, with the signature it actually has."""
    try:
        params = inspect.signature(cb).parameters.values()
    except (TypeError, ValueError):
        params = []
    plist = list(params)
    takes_meta = len(plist) >= 4 or any(p.kind == p.VAR_POSITIONAL for p in plist)
    return cb(client, mint, bad, meta) if takes_meta else cb(client, mint, bad)


def _best_pair_108(pairs: list, mint: str) -> Optional[dict]:
    cand = [p for p in pairs if (p.get("baseToken") or {}).get("address") == mint]
    if not cand:
        return None
    fn = globals().get("pick_best_pair")
    if callable(fn):
        try:
            r = fn(cand, mint)
            if r is not None:
                return r
        except Exception:
            pass

    def liq(p):
        try:
            return float((p.get("liquidity") or {}).get("usd") or 0)
        except (TypeError, ValueError):
            return 0.0

    return max(cand, key=liq)


# ---- 1) Wrap resolve_due so labels actually land ----
async def resolve_due(client: "httpx.AsyncClient") -> int:
    snaps: List[dict] = []
    try:
        now = int(time.time())
        batch = int(globals().get("RESOLVE_BATCH") or 20)
        got = await redis_pipe(client, [["ZRANGEBYSCORE", "due", "-inf", now, "LIMIT", 0, batch]])
        ids = [i for i in ((got or [[]])[0] or []) if i not in _LABELED_108]
        if ids:
            hashes = await redis_pipe(client, [["HGETALL", f"pred:{i}"] for i in ids])
            for i, h in zip(ids, hashes or []):
                d = to_dict(h)
                if d.get("mint"):
                    d["_id"] = i
                    snaps.append(d)
    except Exception as e:
        print(f"[part108] pre-resolve: {e}")

    n = await _prev_resolve_108(client)
    if not snaps:
        return n

    try:
        mints = sorted({d["mint"] for d in snaps})
        best: Optional[Dict[str, Optional[dict]]] = None  # None = fetch failed -> do not label anything
        try:
            resp = await client.get("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(mints))
            if getattr(resp, "status_code", 200) != 200:
                raise RuntimeError(f"dexscreener status {resp.status_code}")
            pairs = (resp.json() or {}).get("pairs") or []
            if pairs:
                best = {m: _best_pair_108(pairs, m) for m in mints}
        except Exception as e:
            print(f"[part108] price fetch: {e}")
        if best is None:
            _STAT_108["skipped_fetch_failed"] += len(snaps)
            return n  # retry next cycle; a failed fetch is not evidence the token died

        bad_ret = float(globals().get("BAD_RETURN_PCT") or -50)
        bad_liq = float(globals().get("BAD_LIQ_RATIO") or 0.3)
        horizon = int(globals().get("PRED_HORIZON_S") or 86400)
        now = int(time.time())

        for d in snaps:
            mint, sid = d.get("mint"), d.get("_id")
            if not mint:
                continue
            if len(_LABELED_108) > 5000:
                _LABELED_108.clear()
            if sid is not None:
                _LABELED_108.add(sid)
            if now - int(float(d.get("ts") or 0)) > horizon * 3:
                continue
            try:
                p0, l0 = float(d.get("price") or 0), float(d.get("liq") or 0)
            except (TypeError, ValueError):
                p0, l0 = 0.0, 0.0
            if p0 <= 0 and l0 <= 0:
                _STAT_108["skipped_unjudgeable"] += 1  # snapshot has no start price/liquidity: cannot judge
                continue
            pair = best.get(mint)
            if pair is None:
                ret, liq_ratio = -100.0, 0.0  # pair is gone
            else:
                try:
                    p1 = float(pair.get("priceUsd") or 0)
                    l1 = float((pair.get("liquidity") or {}).get("usd") or 0)
                except (TypeError, ValueError):
                    p1, l1 = 0.0, 0.0
                ret = (p1 / p0 - 1) * 100 if p0 > 0 else 0.0
                liq_ratio = l1 / l0 if l0 > 0 else 1.0
            bad = bool(ret <= bad_ret or liq_ratio <= bad_liq)
            _STAT_108["labeled"] += 1
            _STAT_108["bad"] += 1 if bad else 0

            names = ("on_outcome_for_si", "shadow_avoid_on_outcome", "prerug_on_outcome", "residual_on_outcome")
            for name in names:
                cb = globals().get(name)
                if callable(cb):
                    try:
                        await _call_cb(cb, client, mint, bad, {"source": "part108"})
                    except Exception as e:
                        print(f"[part108] {name}: {e}")
    except Exception as e:
        print(f"[part108] post-resolve: {e}")
    return n


# ---- 2–4) Honesty fields on every signal ----
def _valid_for_s(r: dict) -> int:
    conf = (r.get("data_quality") or {}).get("data_confidence")
    try:
        c = float(conf) if conf is not None else 0.7
    except (TypeError, ValueError):
        c = 0.7
    if c >= 0.95:
        return 120
    if c >= 0.8:
        return 60
    if c >= 0.6:
        return 30
    return 15


def _would_change(r: dict) -> List[str]:
    out: List[str] = []
    existing = r.get("would_change_my_mind")
    if isinstance(existing, list) and existing:
        return [str(x) for x in existing][:8]
    dec = r.get("decision") if isinstance(r.get("decision"), dict) else {}
    for u in (dec.get("unknowns") or [])[:4]:
        out.append(f"Resolve: {u}")
    for b in (dec.get("blockers") or [])[:3]:
        out.append(f"Blocker present: {b}")
    if not out:
        out.append("New on-chain evidence (mint/freeze/LP) or large liquidity change.")
        out.append("Clearer market data (end Dex rate-limit / full rugcheck).")
    return out[:8]


def _survival_note(r: dict) -> Optional[dict]:
    return {
        "basis": "measured_cohort",
        "note": "Use early_horizons / survival on /stats and card; not a per-token forecast.",
        "horizons": ["1h", "6h", "24h"],
    }


_build_prev_108 = build_signal


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_108(client, mint, security, *args, **kwargs)
    try:
        r, status = (res[0], res[1]) if isinstance(res, tuple) and len(res) == 2 else (res, "ok")
        if not isinstance(r, dict):
            return res
        dec = r.get("decision")
        if not isinstance(dec, dict):
            dec = {}
            r["decision"] = dec
        if dec.get("verdict") is None and r.get("verdict"):
            dec["verdict"] = r["verdict"]
        if dec.get("risk_score") is None and r.get("risk_score") is not None:
            dec["risk_score"] = r["risk_score"]
        vfs = _valid_for_s(r)
        dec["valid_for_s"] = vfs
        r["valid_for_s"] = vfs
        wcm = _would_change(r)
        r["would_change_my_mind"] = wcm
        dec["would_change_my_mind"] = wcm
        if not r.get("survival_meta"):
            r["survival_meta"] = _survival_note(r)
        return (r, status) if isinstance(res, tuple) else r
    except Exception as e:
        print(f"[part108] honesty wrap: {e}")
        return res


print(f"[part108] v{VERSION} resolve->labels (safe) . valid_for_s . would_change_my_mind")

# --- part109 ---
# ---------- v2.90: Daily public benchmark snapshot (anonymous counts only) ----------
VERSION = "2.90.0"
app.version = VERSION
app.openapi_schema = None

import time
from typing import Any, Dict


@app.get("/benchmark/daily", tags=["accuracy"])
async def benchmark_daily(request: Request):
    """Anonymous daily snapshot others can compare against. No mint list."""
    client = request.app.state.client
    st: Dict[str, Any] = {}
    try:
        if "stats_report" in globals():
            st = await stats_report(client)
    except Exception as e:
        st = {"error": str(e)[:120]}

    perf = (st.get("performance") or {}).get("all_tracked") or {}
    oa = perf.get("ours_avoid") or {}
    ba = perf.get("baseline_avoid") or {}
    judged = int(perf.get("judged") or st.get("resolved") or 0)
    bad = int(perf.get("bad_outcomes") or 0)
    base = round(100.0 * bad / judged, 1) if judged else None
    lift = None
    if base is not None and oa.get("precision_pct") is not None:
        try:
            lift = round(float(oa["precision_pct"]) - float(base), 1)
        except (TypeError, ValueError):
            lift = None

    shadow = {}
    try:
        if PRED_ENABLED and client:
            key = globals().get("SHADOW_AVOID_KEY") or "si:shadow:avoid_rules"
            raw = await redis_pipe(client, [["HGETALL", key]])
            h = to_dict((raw or [{}])[0] or {})
            shadow = {
                "emitted": int(float(h.get("emitted", 0) or 0)),
                "judged": int(float(h.get("judged", 0) or 0)),
                "tp": int(float(h.get("tp", 0) or 0)),
                "fp": int(float(h.get("fp", 0) or 0)),
            }
    except Exception:
        pass

    return {
        "brand": "TVibe Signal",
        "as_of_unix": int(time.time()),
        "horizon_hours": st.get("horizon_hours") or 24,
        "judged": judged,
        "bad_outcomes": bad,
        "base_rate_pct": base,
        "ours_avoid": {
            "precision_pct": oa.get("precision_pct"),
            "recall_pct": oa.get("recall_pct"),
            "precision_ci95_pct": oa.get("precision_ci95_pct"),
        },
        "baseline_avoid": {
            "precision_pct": ba.get("precision_pct"),
            "recall_pct": ba.get("recall_pct"),
        },
        "lift_vs_base_rate_pts": lift,
        "early_horizons": st.get("early_horizons"),
        "shadow_avoid": shadow,
        "disclaimer": "Heuristics, not financial advice. Compare against this public snapshot.",
        "version": VERSION,
    }


print(f"[part109] v{VERSION} GET /benchmark/daily")

# --- part110 ---
# ---------- v2.91.1: Deployer reputation SHADOW (from our outcomes only) (reviewed) ----------
# When a judged outcome is bad/ok and the creator/deployer is known, bump shadow counters.
# Never changes the live verdict. GET /stats/deployer-shadow for research.
# Review fixes vs v2.91.0:
#   - outcome callback is called once with the signature it really has (the old TypeError retry could double-count)
#   - public list needs at least 5 outcomes per wallet (default 10): a wallet labelled "100% bad" on 3 samples is unfair
#   - the endpoint now shows how many outcomes had NO known deployer, so you can see if this feature records anything.
#     (part108 passes no deployer, so until a part stores the creator at verdict time this stays empty.)
VERSION = "2.91.1"
app.version = VERSION
app.openapi_schema = None

import inspect
import json
import time
from typing import Any, Dict, Optional

DEP_KEY = "si:shadow:deployer"
DEP_TTL = 120 * 86400
DEP_MIN_FLOOR = 5
_DEP_STAT = {"recorded": 0, "skipped_no_deployer": 0}


def _dep_field(meta: Optional[dict], result: Optional[dict] = None) -> Optional[str]:
    for src in (meta or {}, result or {}):
        if not isinstance(src, dict):
            continue
        for k in ("creator", "deployer", "deployer_wallet", "creator_wallet", "authority"):
            v = src.get(k)
            if isinstance(v, str) and 32 <= len(v) <= 54:
                return v
        cr = src.get("rugcheck") or src.get("security") or {}
        if isinstance(cr, dict):
            for k in ("creator", "deployer", "mintAuthority"):
                v = cr.get(k)
                if isinstance(v, str) and 32 <= len(v) <= 54 and v not in ("", "11111111111111111111111111111111"):
                    return v
    return None


async def deployer_shadow_on_outcome(client, mint: str, bad: bool, meta: Optional[dict] = None) -> None:
    if not globals().get("PRED_ENABLED") or not client:
        return
    dep = _dep_field(meta)
    if not dep:
        _DEP_STAT["skipped_no_deployer"] += 1
        return
    try:
        cmds = [
            ["HINCRBY", DEP_KEY, f"{dep}:n", 1],
            ["HINCRBY", DEP_KEY, f"{dep}:bad", 1 if bad else 0],
            ["EXPIRE", DEP_KEY, DEP_TTL],
        ]
        await redis_pipe(client, cmds)
        _DEP_STAT["recorded"] += 1
    except Exception as e:
        print(f"[part110] deployer shadow: {e}")


_prev_out_110 = globals().get("on_outcome_for_si")


async def on_outcome_for_si(client, mint: str, bad: bool, meta: Optional[dict] = None, **kwargs):
    if callable(_prev_out_110):
        try:
            plist = list(inspect.signature(_prev_out_110).parameters.values())
        except (TypeError, ValueError):
            plist = []
        takes_meta = len(plist) >= 4 or any(p.kind == p.VAR_POSITIONAL for p in plist)
        try:
            if takes_meta:
                await _prev_out_110(client, mint, bad, meta, **kwargs)
            else:
                await _prev_out_110(client, mint, bad)
        except Exception as e:
            print(f"[part110] previous outcome hook: {e}")
    await deployer_shadow_on_outcome(client, mint, bad, meta)


@app.get("/stats/deployer-shadow", tags=["accuracy"])
async def stats_deployer_shadow(request: Request, min_n: int = 10, limit: int = 30):
    """Shadow only - not used in the live verdict."""
    client = request.app.state.client
    min_n = max(DEP_MIN_FLOOR, min_n)
    rows = []
    try:
        if PRED_ENABLED and client:
            raw = await redis_pipe(client, [["HGETALL", DEP_KEY]])
            h = to_dict((raw or [{}])[0] or {})
            agg: Dict[str, Dict[str, int]] = {}
            for k, v in h.items():
                if not isinstance(k, str) or ":" not in k:
                    continue
                dep, kind = k.rsplit(":", 1)
                if kind not in ("n", "bad"):
                    continue
                agg.setdefault(dep, {"n": 0, "bad": 0})
                agg[dep][kind] = int(float(v or 0))
            for dep, c in agg.items():
                n = c["n"]
                if n < min_n:
                    continue
                rows.append({"deployer": dep, "n": n, "bad": c["bad"],
                             "bad_rate_pct": round(100.0 * c["bad"] / n, 1)})
            rows.sort(key=lambda r: (-(r["bad_rate_pct"] or 0), -r["n"]))
            rows = rows[: max(1, min(limit, 100))]
    except Exception as e:
        return {"version": VERSION, "error": str(e)[:120], "rows": []}
    return {
        "version": VERSION,
        "shadow": True,
        "live_verdict_unchanged": True,
        "min_n": min_n,
        "since_restart": dict(_DEP_STAT),
        "rows": rows,
        "note": "Built only from our judged outcomes when creator/deployer was known. A high bad rate is an association, not proof of intent. Not financial advice.",
    }


print(f"[part110] v{VERSION} deployer shadow -> GET /stats/deployer-shadow")

# --- part111 ---
# ---------- v2.91.1: llms.txt - TVibe Signal, honest agent surface (reviewed) ----------
# Review fixes vs v2.91.0:
#   - an older part may already serve /llms.txt (first route wins), so remove it before registering this one
#   - "\~30" (invalid escape, SyntaxWarning) -> "~30"
#   - GitHub link matched to the one on the home page (TVibex402)
#   - mentions /verify and the attestation field
VERSION = "2.91.1"
app.version = VERSION
app.openapi_schema = None

from fastapi.responses import PlainTextResponse

LLMS_TXT = """# TVibe Signal
> Solana token signals for AI agents. Heuristics, measured in public. Not financial advice.

## Primary interface (use this first)
- HTTP: GET https://signal-api-24q4.onrender.com/omni?mint=<SOLANA_MINT>
- MCP:  https://signal-api-24q4.onrender.com/mcp
- MCP tool: omni(mint)

Trust decision.verdict first. Treat debate / residual / pre_rug as optional context.
When decision.unknowns is non-empty, prefer caution over size.
If decision.verdict_raw is present, the verdict was lowered (capped) from that value.

## Prove it (do not skip)
- GET https://signal-api-24q4.onrender.com/stats
- GET https://signal-api-24q4.onrender.com/benchmark/daily
- Avoid precision vs base rate and vs a simple liquidity/age baseline are published there.
- Only tokens that people query are measured, so this is not a random sample of all tokens.

## Honesty fields on omni / decision
- blockers, cautions, positives, unknowns
- valid_for_s: cache hint in seconds
- would_change_my_mind: what would revise the call
- track_record_context: similar past verdicts (not the probability that this mint fails)

## Signed verdicts
- Every /omni response includes `attestation`: an Ed25519 signature and a hash chain.
- Check one in the browser: https://signal-api-24q4.onrender.com/verify
- Signing key and chain status: GET /attest

## Secondary
- GET /signal?mint=  classic signal
- GET /signals?mints=A,B,C&view=compact  batch, max 10
- GET /exit?mint=  Jupiter sell cost
- GET /health
- GET /stats/deployer-shadow  research only, not live verdict
- GET /stats/shadow-avoid  research only

## Fair use
Free public instance. ~30 req/min. Cache the same mint 15-30s. Heavy use: self-host.
GitHub: https://github.com/TVibex402/signal-api

## Disclaimer
Heuristics for agents and research. Not financial advice. Data can be late or wrong.
"""

try:
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/llms.txt"]
except Exception as _e:
    print("[part111] could not replace an older /llms.txt route:", str(_e)[:100])


@app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
async def llms_txt_v291():
    return LLMS_TXT


print(f"[part111] v{VERSION} /llms.txt TVibe Signal")

# --- part112 ---
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

# --- part113 ---
# part113.py - display fixes on the home page (v2.89.3), works on top of your current part104
# 1) If the summary says "Verdict capped from X to Y", the headline now shows Y (the more cautious verdict)
#    instead of the old "Looks OK" in green.
# 2) Removes the duplicated "Agent debate" heading.
# 3) Keeps the survival chart from stretching into a huge empty box on phones.
# Loader line (after part107, before part7):  ("part113.py", 0, "SKIP"),

FIX_ADDON = r'''<!--display-fixes-addon-->
<style>
.r-box>svg{display:block;max-width:440px;margin:0 auto}
</style>
<script>
(function(){
var out=document.getElementById('out');if(!out)return;
var LABEL={ok:'Looks OK',caution:'Use caution',avoid:'High risk'},CLS={ok:'ok',caution:'warn',avoid:'bad'},timer=null;
function fix(){
  var res=out.querySelector('.res');if(!res)return;
  var hero=res.querySelector('.r-hero');
  if(hero&&!hero.getAttribute('data-cap')){
    hero.setAttribute('data-cap','1');
    var p=hero.querySelector('.r-vtxt p');
    var m=/Verdict capped from (ok|caution|avoid) to (ok|caution|avoid)/i.exec(p?String(p.textContent||''):'');
    if(m){
      var from=m[1].toLowerCase(),to=m[2].toLowerCase();
      hero.classList.remove('ok');hero.classList.remove('warn');hero.classList.remove('bad');hero.classList.add(CLS[to]);
      var big=hero.querySelector('.r-big');
      if(big){for(var i=0;i<big.childNodes.length;i++){var n=big.childNodes[i];if(n.nodeType===3&&String(n.nodeValue).trim()){n.nodeValue=LABEL[to];break}}}
      var chip=document.createElement('span');chip.className='r-chip warn';chip.style.marginTop='.5rem';chip.textContent='Verdict lowered from '+from+' to '+to;
      if(p&&p.parentNode)p.parentNode.appendChild(chip);
    }
  }
  var hs=res.querySelectorAll('.r-h');
  for(var j=0;j<hs.length;j++){
    if(/^Agent debate\s*$/i.test(String(hs[j].textContent||'').trim())){
      var nx=hs[j].nextElementSibling;
      if(nx&&nx.querySelector&&nx.querySelector('.r-box')&&hs[j].parentNode)hs[j].parentNode.removeChild(hs[j]);
    }
  }
}
function schedule(){if(timer)return;timer=setTimeout(function(){timer=null;try{fix()}catch(e){}},40)}
if(window.MutationObserver)new MutationObserver(schedule).observe(out,{childList:true,subtree:true});
schedule();
})();
</script>
'''

try:
    if "<!--display-fixes-addon-->" not in HOME_HTML:
        HOME_HTML = HOME_HTML.replace("</body>", FIX_ADDON + "</body>", 1)
    print("[part113] display fixes injected into the home page")
except NameError:
    print("[part113] HOME_HTML not found - part104 must load before part113")

# --- part114 ---
# part114.py - Telegram bot for TVibe Signal (webhook) - v2.92.0
# People send a Solana mint address to the bot (or use /check <mint>) and it replies with the verdict,
# the main reasons and links. It calls your own /omni in-process, so the answer is the same as on the website
# (including the signed attestation).
#
# Privacy: the bot only looks at messages that contain a Solana address or a command. It stores nothing about
# the chat, usernames or user ids (only in-memory counters at /telegram/status).
#
# Setup (details in the chat): env vars on Render
#   TELEGRAM_BOT_TOKEN       token from BotFather (never commit it, never paste it anywhere public)
#   TELEGRAM_WEBHOOK_SECRET  any long random string (letters, digits, _ or -); required
#   TELEGRAM_GROUP_AUTO=1    optional: also react to any mint address in group chats (needs BotFather /setprivacy -> Disable)
#   PUBLIC_BASE_URL          optional, default https://signal-api-24q4.onrender.com
# Loader line (after part112, before part7):  ("part114.py", 0, "SKIP"),
import asyncio
import html
import os
import re
import time
import types

from fastapi import Request
from fastapi.responses import JSONResponse

VERSION = "2.92.0"
app.version = VERSION
app.openapi_schema = None

_TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
_TG_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
_TG_GROUP_AUTO = os.environ.get("TELEGRAM_GROUP_AUTO", "0") == "1"
_TG_BASE = os.environ.get("PUBLIC_BASE_URL", "https://signal-api-24q4.onrender.com").rstrip("/")
_TG_MINT_RE = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
_TG_MIN_GAP_S = 3.0
_TG_CHAT_PER_MIN = 20
_TG_MAX_MINTS = 2

_TG = types.SimpleNamespace(username="", updates=0, replies=0, errors=0, rate_limited=0,
                            started=int(time.time()), last_user={}, chat_hits={})
_TG_TASKS = set()


def _tg_clean(e):
    return re.sub(r"bot\d+:[\w-]+", "bot<token>", str(e))[:160]


async def _tg_call(method, payload=None):
    import httpx
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://api.telegram.org/bot%s/%s" % (_TG_TOKEN, method), json=payload or {})
        return r.json()


async def _tg_omni(mint):
    """Call our own /omni in-process (same answer, same signing, same cache as the website)."""
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal",
                                 timeout=60) as c:
        r = await c.get("/omni", params={"mint": mint}, headers={"accept": "application/json"})
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, None


def _clip(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "\u2026"


def _tg_format(d, mint):
    dec = d.get("decision") or {}
    v = dec.get("verdict")
    label = {"ok": "Looks OK", "caution": "Use caution", "avoid": "High risk"}.get(v, str(v))
    icon = {"ok": "\U0001F7E2", "caution": "\U0001F7E1", "avoid": "\U0001F534"}.get(v, "\u26AA")
    head = "%s <b>%s</b> \u2014 %s" % (icon, html.escape(_clip(d.get("token") or "token", 40)), html.escape(label))
    if dec.get("risk_score") is not None:
        head += " \u00B7 risk %s/100" % html.escape(str(dec["risk_score"]))
    lines = [head]
    if d.get("summary"):
        lines.append(html.escape(_clip(d["summary"], 300)))
    for title, key, sym, n in (("Blockers", "blockers", "\u2716", 3), ("Cautions", "cautions", "\u26A0", 3),
                               ("Positives", "positives", "\u2714", 3), ("Unknowns", "unknowns", "?", 2)):
        arr = dec.get(key) or []
        if arr:
            lines.append("")
            lines.append("<b>%s</b>" % title)
            for x in arr[:n]:
                lines.append("%s %s" % (sym, html.escape(_clip(x if isinstance(x, str) else x.get("detail", x), 110))))
    att = d.get("attestation") or {}
    if att.get("sig"):
        lines.append("")
        lines.append("\u2714 Signed verdict #%s \u2014 check it at %s/verify" % (html.escape(str(att.get("chain_n"))), _TG_BASE))
    lines.append("")
    lines.append("<i>Heuristic, not financial advice. Data can be late or wrong.</i>")
    text = "\n".join(lines)
    return text if len(text) <= 3900 else text[:3890] + "\u2026"


def _tg_buttons(mint):
    return {"inline_keyboard": [[
        {"text": "Full report", "url": "%s/?mint=%s" % (_TG_BASE, mint)},
        {"text": "DexScreener", "url": "https://dexscreener.com/solana/%s" % mint},
    ]]}


HELP_TEXT = ("<b>TVibe Signal</b>\nSend me a Solana token address (or use <code>/check ADDRESS</code>) "
             "and I reply with a verdict and the reasons behind it.\n\n"
             "I only read messages that contain a Solana address or a command, and I do not store chats.\n"
             "<i>Heuristic, not financial advice.</i>")


def _tg_allowed(chat_id, user_id):
    now = time.time()
    key = (chat_id, user_id)
    if now - _TG.last_user.get(key, 0) < _TG_MIN_GAP_S:
        return False
    hits = [t for t in _TG.chat_hits.get(chat_id, []) if now - t < 60]
    if len(hits) >= _TG_CHAT_PER_MIN:
        _TG.chat_hits[chat_id] = hits
        return False
    hits.append(now)
    _TG.chat_hits[chat_id] = hits
    _TG.last_user[key] = now
    if len(_TG.last_user) > 5000:
        _TG.last_user.clear()
    if len(_TG.chat_hits) > 2000:
        _TG.chat_hits.clear()
    return True


async def _tg_send(chat_id, text, thread, reply_to, buttons=None):
    p = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if thread:
        p["message_thread_id"] = thread
    if reply_to:
        p["reply_to_message_id"] = reply_to
        p["allow_sending_without_reply"] = True
    if buttons:
        p["reply_markup"] = buttons
    res = await _tg_call("sendMessage", p)
    _TG.replies += 1
    return res


async def _tg_username():
    if not _TG.username:
        try:
            r = await _tg_call("getMe")
            _TG.username = ((r or {}).get("result") or {}).get("username", "") or ""
        except Exception as e:
            print("[part114] getMe:", _tg_clean(e))
    return _TG.username


async def _tg_handle(upd):
    msg = upd.get("message")
    if not isinstance(msg, dict):
        return
    text = msg.get("text") or msg.get("caption") or ""
    sender = msg.get("from") or {}
    chat = msg.get("chat") or {}
    chat_id, ctype = chat.get("id"), chat.get("type")
    if not text or sender.get("is_bot") or chat_id is None:
        return
    thread = msg.get("message_thread_id") if msg.get("is_topic_message") else None
    reply_to = msg.get("message_id")
    is_private = ctype == "private"
    uname = (await _tg_username()).lower()

    cmd, rest = "", text
    if text.startswith("/"):
        first, _, rest = text.partition(" ")
        cmd = first.split("@")[0].lower()
        if "@" in first and uname and first.split("@", 1)[1].lower() != uname:
            return  # command meant for another bot
    if cmd in ("/start", "/help"):
        await _tg_send(chat_id, HELP_TEXT, thread, reply_to)
        return

    mentioned = bool(uname) and ("@" + uname) in text.lower()
    replied_to_us = bool(uname) and (((msg.get("reply_to_message") or {}).get("from") or {}).get("username", "")
                                     .lower() == uname)
    wants = bool(cmd in ("/check", "/c", "/signal")) or is_private or mentioned or replied_to_us or _TG_GROUP_AUTO
    if not wants:
        return
    mints = _TG_MINT_RE.findall(rest if cmd else text)
    if not mints:
        if cmd in ("/check", "/c", "/signal"):
            await _tg_send(chat_id, "Send a Solana token address after the command, for example <code>/check ADDRESS</code>.",
                           thread, reply_to)
        return
    if not _tg_allowed(chat_id, sender.get("id")):
        _TG.rate_limited += 1
        return
    seen = []
    for m in mints:
        if m not in seen:
            seen.append(m)
    for mint in seen[:_TG_MAX_MINTS]:
        try:
            await _tg_call("sendChatAction", {"chat_id": chat_id, "action": "typing",
                                              **({"message_thread_id": thread} if thread else {})})
            status, d = await _tg_omni(mint)
            if status == 429:
                await _tg_send(chat_id, "I am busy right now. Please try again in a minute.", thread, reply_to)
            elif status != 200 or not isinstance(d, dict) or not (d.get("decision") or {}).get("verdict"):
                await _tg_send(chat_id, "I could not read <code>%s\u2026</code> as a token. Check the address." % html.escape(mint[:6]),
                               thread, reply_to)
            else:
                await _tg_send(chat_id, _tg_format(d, mint), thread, reply_to, _tg_buttons(mint))
        except Exception as e:
            _TG.errors += 1
            print("[part114] reply failed:", _tg_clean(e))


@app.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request):
    if not _TG_TOKEN or not _TG_SECRET:
        return JSONResponse({"ok": False, "error": "not configured"}, status_code=503)
    if request.headers.get("x-telegram-bot-api-secret-token", "") != _TG_SECRET:
        return JSONResponse({"ok": False}, status_code=403)
    try:
        upd = await request.json()
    except Exception:
        return {"ok": True}
    _TG.updates += 1
    t = asyncio.create_task(_tg_handle(upd))  # answer Telegram at once; the reply is sent when ready
    _TG_TASKS.add(t)
    t.add_done_callback(_TG_TASKS.discard)
    return {"ok": True}


@app.get("/telegram/status", include_in_schema=False)
async def telegram_status():
    return {
        "bot_token_set": bool(_TG_TOKEN), "webhook_secret_set": bool(_TG_SECRET),
        "ready": bool(_TG_TOKEN and _TG_SECRET), "group_auto_detect": _TG_GROUP_AUTO,
        "webhook_url_to_register": _TG_BASE + "/telegram/webhook",
        "updates_received": _TG.updates, "replies_sent": _TG.replies, "rate_limited": _TG.rate_limited,
        "errors": _TG.errors, "since": _TG.started, "version": VERSION,
    }


print("[part114] v%s Telegram bot webhook (%s)" % (VERSION, "ready" if (_TG_TOKEN and _TG_SECRET) else "set TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET"))

# --- part115 ---
# part115.py - Telegram UX polish (after part114) (v2.92.3, reviewed)
# Adds /status and a clearer /help, and turns "API busy" statuses into a friendly message.
# Review fixes vs v2.92.2:
#   - "\~30s" was an invalid escape (SyntaxWarning)
#   - the old wrapper swapped the global _tg_omni during every message; with several messages at once it could
#     restore the wrong function. The wrapper is now installed once.
#   - /status, /help and /start also answered commands meant for OTHER bots ("/start@otherbot") and were not
#     rate-limited. Both fixed. /status no longer shows internal counters to everyone.
#   - removed unused code
VERSION = "2.92.3"
app.version = VERSION
app.openapi_schema = None

import html

_HELP_115 = (
    "<b>TVibe Signal</b>\n"
    "\u2022 <code>/check ADDRESS</code> \u2014 verdict and risk for a Solana token\n"
    "\u2022 In a private chat you can also paste the address\n"
    "\u2022 <code>/status</code> \u2014 is the bot ready\n"
    "\u2022 <code>/help</code> \u2014 this message\n\n"
    "I only read messages that contain a Solana address or a command, and I do not store chats.\n"
    "<i>Heuristic only, not financial advice.</i>"
)

_prev_handle_115 = globals().get("_tg_handle")
_prev_omni_115 = globals().get("_tg_omni")
_prev_send_115 = globals().get("_tg_send")

if callable(_prev_handle_115) and callable(_prev_omni_115) and callable(_prev_send_115):

    async def _tg_omni(mint):
        status, d = await _prev_omni_115(mint)
        if status in (502, 503, 504):
            return 429, None  # part114 then says "I am busy right now, try again in a minute"
        return status, d

    async def _tg_send(chat_id, text, thread, reply_to, buttons=None):
        t = str(text or "")
        low = t.lower()
        if "could not read" in low and "as a token" in low:
            t = ("No verdict for that address right now. The data may be incomplete or the service busy. "
                 "Try again in a minute; the address may still be valid.")
        if buttons is not None:
            return await _prev_send_115(chat_id, t, thread, reply_to, buttons)
        return await _prev_send_115(chat_id, t, thread, reply_to)

    async def _tg_handle(upd):
        try:
            msg = upd.get("message") if isinstance(upd, dict) else None
            if isinstance(msg, dict) and not (msg.get("from") or {}).get("is_bot"):
                text = str(msg.get("text") or "").strip()
                chat = msg.get("chat") or {}
                chat_id = chat.get("id")
                first = text.split(" ", 1)[0].lower() if text.startswith("/") else ""
                cmd, _, target = first.partition("@")
                if chat_id is not None and cmd in ("/status", "/help", "/start"):
                    uname = (await _tg_username()).lower() if "_tg_username" in globals() else ""
                    if target and uname and target != uname:
                        return  # meant for another bot
                    allowed = globals().get("_tg_allowed")
                    if callable(allowed) and not allowed(chat_id, (msg.get("from") or {}).get("id")):
                        return
                    thread = msg.get("message_thread_id") if msg.get("is_topic_message") else None
                    if cmd == "/status":
                        ready = bool(globals().get("_TG_TOKEN") and globals().get("_TG_SECRET"))
                        body = "<b>Bot status</b>\nready: %s\nversion: %s" % (ready, html.escape(VERSION))
                    else:
                        body = _HELP_115
                    await _prev_send_115(chat_id, body, thread, msg.get("message_id"))
                    return
        except Exception as e:
            print("[part115] pre-handler:", str(e)[:100])
        await _prev_handle_115(upd)

    globals()["_tg_omni"] = _tg_omni
    globals()["_tg_send"] = _tg_send
    globals()["_tg_handle"] = _tg_handle
    print("[part115] Telegram UX: /status /help + friendlier busy and no-verdict messages")
else:
    print("[part115] part114 handlers not found - skipped (load part114 before part115)")

# --- part116 ---
# part116.py - System circuit breaker (source health -> soft degrade) (v2.93.1, reviewed)
# Opens when BOTH DexScreener and Solana RPC fail 3 times in a row; agents then see system_stress.
# Review fixes vs v2.93.0:
#   - it could never close again (the "half" state was only computed in a copy), so after ONE outage every
#     verdict stayed capped to caution forever. It now closes after the hold time as soon as a source answers ok.
#   - verdict_capped_by stays a list (part78 uses a list); major assets (SOL, USDC...) are not capped.
VERSION = "2.93.1"
app.version = VERSION
app.openapi_schema = None

import time
from typing import Any, Dict

_CB = {"state": "closed", "opened_at": 0.0, "reason": "", "open_for_s": 90,
       "dex_fail_streak": 0, "rpc_fail_streak": 0}
_CB_STREAK = 3


def circuit_status() -> Dict[str, Any]:
    now = time.time()
    st = dict(_CB)
    if st["state"] == "open" and now - st["opened_at"] >= st["open_for_s"]:
        st["state"] = "half"
    st["now"] = now
    return st


def circuit_record_source(name: str, ok: bool) -> None:
    key = "dex_fail_streak" if name in ("dexscreener", "dex") else (
        "rpc_fail_streak" if name in ("solana_rpc", "rpc") else None)
    if not key:
        return
    _CB[key] = 0 if ok else int(_CB.get(key) or 0) + 1
    now = time.time()
    both_failing = _CB["dex_fail_streak"] >= _CB_STREAK and _CB["rpc_fail_streak"] >= _CB_STREAK
    if both_failing:
        if _CB["state"] == "closed":
            _CB["state"], _CB["opened_at"], _CB["reason"] = "open", now, "dex_and_rpc_failing"
            print("[part116] circuit OPEN:", _CB["reason"])
        elif now - _CB["opened_at"] >= _CB["open_for_s"]:
            _CB["opened_at"] = now  # still failing after the hold time: stay open another round
    elif _CB["state"] == "open" and ok and now - _CB["opened_at"] >= _CB["open_for_s"]:
        _CB["state"], _CB["reason"] = "closed", ""
        print("[part116] circuit CLOSED")


def _add_cap(r: dict, tag: str) -> None:
    cur = r.get("verdict_capped_by")
    lst = list(cur) if isinstance(cur, list) else ([str(cur)] if cur else [])
    if tag not in lst:
        lst.append(tag)
    r["verdict_capped_by"] = lst


def circuit_apply_to_result(r: dict) -> dict:
    if not isinstance(r, dict):
        return r
    st = circuit_status()
    r["system_stress"] = {
        "state": st["state"],
        "reason": st.get("reason") or None,
        "note": "When open/half, prefer smaller size or wait; data may be stale or partial.",
    }
    if st["state"] in ("open", "half") and r.get("asset_class") != "major":
        dec = r.get("decision") if isinstance(r.get("decision"), dict) else None
        if dec is not None:
            cautions = list(dec.get("cautions") or [])
            msg = "System stress: upstream degraded (circuit %s)" % st["state"]
            if msg not in cautions:
                cautions.append(msg)
            dec["cautions"] = cautions
            if r.get("verdict") == "ok":
                r["verdict"] = "caution"
                _add_cap(r, "circuit_breaker")
            if dec.get("verdict") == "ok":
                dec["verdict_raw"] = dec.get("verdict_raw") or "ok"
                dec["verdict"] = "caution"
    return r


_build_prev_116 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_116(client, mint, security, *args, **kwargs)
    try:
        body = res[0] if isinstance(res, tuple) else res
        if isinstance(body, dict):
            src = body.get("sources") or {}
            if isinstance(src, dict):
                for k, v in src.items():
                    if isinstance(v, dict) and "status" in v:
                        circuit_record_source(k, v.get("status") == "ok")
                    elif isinstance(v, str):
                        circuit_record_source(k, v == "ok")
            circuit_apply_to_result(body)
        return res
    except Exception as e:
        print("[part116] apply:", e)
        return res


@app.get("/system/circuit", tags=["ops"], include_in_schema=False)
async def system_circuit():
    return {"version": VERSION, **circuit_status()}


print(f"[part116] v{VERSION} circuit breaker (auto-closes) -> GET /system/circuit")

# --- part117 ---
# part117.py - slippage band helper (v2.93.1, reviewed)
# Review fixes vs v2.93.0:
#   - the old wrapper added a pseudo-unknown ("Slippage/exit: GET /exit...") to decision.unknowns of EVERY token,
#     so agents saw unknowns everywhere (and llms.txt says "unknowns non-empty -> prefer caution"). Removed.
#   - the old wrapper only touched body["exit"], which /signal never has, so it did nothing else. Removed.
#   The sell-cost band for agents now comes from part119 (`sim` on /signal and /omni).
# This file only keeps the helper, so other code that imports it keeps working.
VERSION = "2.93.1"
app.version = VERSION
app.openapi_schema = None

from typing import Any, Dict, Optional


def _slip_band(impact_pct: Optional[float]) -> Dict[str, Any]:
    if impact_pct is None:
        return {"band": "unknown", "impact_pct": None, "note": "No quote yet"}
    x = float(impact_pct)
    band = "tight" if x < 1 else "moderate" if x < 3 else "wide" if x < 8 else "extreme"
    return {"band": band, "impact_pct": round(x, 3),
            "note": "Price impact estimate from a quote - not MEV protection and not a guarantee of fill."}


def enrich_exit_payload(d: dict) -> dict:
    if not isinstance(d, dict):
        return d
    impact = None
    levels = (d.get("exit") or {}).get("levels") if isinstance(d.get("exit"), dict) else d.get("levels")
    if isinstance(levels, list) and levels and isinstance(levels[0], dict):
        for k in ("loss_vs_market_pct", "price_impact_pct", "impact_pct", "slippage_pct"):
            try:
                if levels[0].get(k) is not None:
                    impact = float(levels[0][k])
                    break
            except (TypeError, ValueError):
                pass
    d["slippage"] = _slip_band(impact)
    d["mev_protection"] = {"available": False,
                           "note": "TVibe Signal does not send transactions. MEV protection needs your wallet or router."}
    return d


globals()["enrich_exit_payload"] = enrich_exit_payload
print(f"[part117] v{VERSION} slippage band helper only (no signal changes)")

# --- part118 ---
# part118.py - agent map (v2.93.1, reviewed): GET /agent/brain
# Review fix: it said "/exit has an impact band" - the band is `sim.slippage_band` on /signal and /omni (part119).
VERSION = "2.93.1"
app.version = VERSION
app.openapi_schema = None


@app.get("/agent/brain", tags=["agents"], include_in_schema=False)
async def agent_brain(request: Request):
    """One glance for agents: what is measured, what is shadow, system stress."""
    out = {
        "version": VERSION,
        "role": "on-chain signal + measured track record; social is optional via the agent (X), not scraped here",
        "primary": "GET /omni?mint=",
        "prove": ["GET /stats", "GET /benchmark/daily", "GET /verify"],
        "system": {},
        "shadow": {"note": "See GET /stats/shadow-avoid, /stats/deployer-shadow and /stats/cluster-shadow (research only)"},
        "learning": {
            "online_ml": False,
            "mechanism": "outcomes -> calibration / shadow rules; promote only when measured",
            "offline": "optional feature export for later offline models; not used for live verdicts",
        },
        "sell_cost": "sim.* on /signal and /omni (quote-based); GET /exit?mint= for the full quote. No MEV protection claim.",
        "disclaimer": "Heuristic. Not financial advice.",
    }
    try:
        if "circuit_status" in globals():
            out["system"] = circuit_status()
    except Exception:
        pass
    return out


print(f"[part118] v{VERSION} GET /agent/brain")

# --- part119 ---
# part119.py - Phase 1: light sell simulation via /exit (Jupiter quote) (v2.94.1, reviewed)
# Not a full VM sandbox. A quote does NOT prove every honeypot is detectable.
# Review fixes vs v2.94.0:
#   - when Jupiter was unavailable / rate-limited, the old code treated "no route" as honeypot risk and capped
#     the verdict to caution. An unavailable quote is now UNKNOWN: no warning, no cap.
#   - /exit itself builds a market verdict, so calling /exit from build_signal could call build_signal again
#     (endless nesting). A context flag now blocks that.
#   - a slow quote no longer holds every /omni for ~13s: we wait at most ~6s; the quote keeps loading in the
#     background and the next call uses the cached result. One in-flight request per mint.
#   - no `sizes` parameter (it created a second cache entry next to the home page's /exit call).
#   - major assets are skipped; cache is bounded; verdict_capped_by stays a list.
# Switch off any time with the env var SELL_SIM=0 (each new token costs one Jupiter quote while it is on).
VERSION = "2.94.1"
app.version = VERSION
app.openapi_schema = None

import asyncio
import contextvars
import os
import time
from typing import Any, Dict, Optional

_SIM_TTL_S = 120
_SIM_FAIL_TTL_S = 20
_SIM_WAIT_S = 6.0
_SIM_FETCH_TIMEOUT_S = 15.0
_SIM_SIZE_USD = 100.0
_SIM_MAX = 500
_SIM_CACHE: Dict[str, tuple] = {}      # mint -> (stored_at, ttl, sim)
_SIM_INFLIGHT: Dict[str, Any] = {}
_IN_SIM = contextvars.ContextVar("tv_in_sim", default=False)
_BAD_GRADES = ("bad", "poor", "fail")


def _band(loss: Optional[float]) -> str:
    if loss is None:
        return "unknown"
    return "tight" if loss < 1 else "moderate" if loss < 3 else "wide" if loss < 8 else "extreme"


def _sim_from_exit(body: dict) -> dict:
    ex = body.get("exit") if isinstance(body, dict) else None
    if not isinstance(ex, dict):
        ex = body if isinstance(body, dict) else {}
    base = {"kind": "jupiter_quote_sim", "size_usd": _SIM_SIZE_USD, "mev_protection": False}
    if ex.get("available") is not True:
        return {**base, "status": "unavailable", "sell_ok": None, "honeypot_risk_heuristic": None,
                "note": "Sell quote unavailable right now (%s). Not proof of safety or danger."
                        % (str(ex.get("reason") or "no quote")[:90])}
    route = ex.get("exit_route_found")
    grade = ex.get("grade") or ex.get("exit_verdict") or "unknown"
    loss = receives = None
    levels = ex.get("levels") or []
    if levels and isinstance(levels[0], dict):
        try:
            loss = float(levels[0].get("loss_vs_market_pct"))
        except (TypeError, ValueError):
            loss = None
        try:
            receives = float(levels[0].get("sell_receives_usd"))
        except (TypeError, ValueError):
            receives = None
    risk = (route is False) or (loss is not None and loss >= 25) or (str(grade).lower() in _BAD_GRADES)
    if route is False or (loss is not None and loss >= 50):
        sell_ok = False
    elif route is True:
        sell_ok = True
    else:
        sell_ok = None
    return {**base, "status": "ok", "sell_ok": sell_ok, "route_found": route, "grade": grade,
            "loss_vs_market_pct": loss, "sell_receives_usd": receives, "slippage_band": _band(loss),
            "honeypot_risk_heuristic": bool(risk),
            "note": "Based on a Jupiter sell quote vs market - not a full contract sandbox. "
                    "Cannot detect every sell-block. Not financial advice."}


async def _exit_call(mint: str):
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal",
                                 timeout=_SIM_FETCH_TIMEOUT_S) as c:
        r = await c.get("/exit", params={"mint": mint}, headers={"accept": "application/json"})
        return r.status_code, (r.json() if r.status_code == 200 else None)


def _cache_put(mint: str, ttl: float, sim: Optional[dict]) -> None:
    now = time.time()
    if len(_SIM_CACHE) >= _SIM_MAX:
        for k in [k for k, v in _SIM_CACHE.items() if now - v[0] >= v[1]]:
            _SIM_CACHE.pop(k, None)
        while len(_SIM_CACHE) >= _SIM_MAX:
            _SIM_CACHE.pop(min(_SIM_CACHE, key=lambda k: _SIM_CACHE[k][0]), None)
    _SIM_CACHE[mint] = (now, ttl, sim)


async def _fetch_sim(mint: str) -> Optional[dict]:
    tok = _IN_SIM.set(True)  # anything /exit calls inside must not start another sim
    try:
        status, data = await _exit_call(mint)
        if status != 200 or not isinstance(data, dict):
            _cache_put(mint, _SIM_FAIL_TTL_S, None)
            return None
        sim = _sim_from_exit(data)
        _cache_put(mint, _SIM_TTL_S if sim.get("status") == "ok" else _SIM_FAIL_TTL_S, sim)
        return sim
    except Exception as e:
        print("[part119] sim fetch:", str(e)[:120])
        _cache_put(mint, _SIM_FAIL_TTL_S, None)
        return None
    finally:
        _IN_SIM.reset(tok)


async def _get_sim(mint: str) -> Optional[dict]:
    hit = _SIM_CACHE.get(mint)
    if hit and time.time() - hit[0] < hit[1]:
        return hit[2]
    task = _SIM_INFLIGHT.get(mint)
    if task is None:
        task = asyncio.ensure_future(_fetch_sim(mint))
        _SIM_INFLIGHT[mint] = task
        task.add_done_callback(lambda t, m=mint: _SIM_INFLIGHT.pop(m, None))
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=_SIM_WAIT_S)
    except Exception:
        return None  # the task keeps running; the next call finds the cached result


def _add_cap(body: dict, tag: str) -> None:
    cur = body.get("verdict_capped_by")
    lst = list(cur) if isinstance(cur, list) else ([str(cur)] if cur else [])
    if tag not in lst:
        lst.append(tag)
    body["verdict_capped_by"] = lst


def _apply_sim_to_signal(body: dict, sim: dict) -> dict:
    body["sim"] = sim
    dec = body.get("decision") if isinstance(body.get("decision"), dict) else None
    if dec is None or sim.get("status") != "ok":
        return body
    cautions = list(dec.get("cautions") or [])
    if sim.get("honeypot_risk_heuristic"):
        msg = "Sell quote weak or missing (possible sell friction)"
        if msg not in cautions:
            cautions.append(msg)
        if body.get("verdict") == "ok":
            body["verdict"] = "caution"
            _add_cap(body, "sell_sim")
        if dec.get("verdict") == "ok":
            dec["verdict_raw"] = dec.get("verdict_raw") or "ok"
            dec["verdict"] = "caution"
            dec["capped_by"] = dec.get("capped_by") or ["sell_sim"]
    elif sim.get("sell_ok") and sim.get("slippage_band") in ("wide", "extreme"):
        msg = "Sell quote slippage is %s (about %s%% below market)" % (sim.get("slippage_band"), sim.get("loss_vs_market_pct"))
        if msg not in cautions:
            cautions.append(msg)
    dec["cautions"] = cautions
    dec["unknowns"] = [u for u in (dec.get("unknowns") or [])
                       if "Exit cost not checked" not in str(u) and "Slippage/exit:" not in str(u)]
    return body


_build_prev_119 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_119(client, mint, security, *args, **kwargs)
    if _IN_SIM.get() or os.environ.get("SELL_SIM", "1") == "0":
        return res  # inside our own /exit call, or switched off with SELL_SIM=0
    try:
        body = res[0] if isinstance(res, tuple) else res
        if not isinstance(body, dict):
            return res
        if body.get("asset_class") == "major" or (body.get("decision") or {}).get("asset_class") == "major":
            return res
        st = globals().get("circuit_status")
        if callable(st):
            try:
                if (st() or {}).get("state") == "open":
                    body["sim"] = {"kind": "skipped", "note": "Upstream stressed - sell quote skipped"}
                    return res
            except Exception:
                pass
        sim = await _get_sim(str(mint))
        if sim is None:
            body["sim"] = {"kind": "jupiter_quote_sim", "status": "pending", "sell_ok": None,
                           "note": "Sell quote not ready yet. Not proof of safety or danger."}
        else:
            _apply_sim_to_signal(body, sim)
        return res
    except Exception as e:
        print("[part119] wrap:", str(e)[:120])
        return res


print(f"[part119] v{VERSION} sell-sim via /exit (unavailable = unknown, no recursion) -> sim.* on signal/omni")

# --- part120 ---
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

# --- part121 ---
# part121.py - "Data notice" on the Live accuracy section when the measurement pipeline is degraded (v2.96.0)
# Shows an amber note when /stats says the verdict queue is unreadable (resolved=0 and pending=0 with empty verdict
# tables), the scoring fell back to "static", or the 1h/6h results are missing. Hides itself when data is back.
# Loader line (after part120, before part7):  ("part121.py", 0, "SKIP"),

NOTICE_ADDON = r'''<!--data-notice-addon-->
<script>
(function(){
var body=document.getElementById('pf-body');if(!body)return;
var D=null,timer=null;
function jget(u){return fetch(u,{headers:{'Accept':'application/json'}}).then(function(r){return r.ok?r.json():null}).catch(function(){return null})}
function gaps(d){
  var out=[];
  var bv=d.by_verdict||{},sum=0;
  ['ok','caution','avoid'].forEach(function(k){var f=bv[k]&&bv[k].full;if(f&&typeof f.n==='number')sum+=f.n});
  if(d.resolved===0&&d.pending===0&&sum===0)out.push('the queue of verdicts waiting for their 24h result is not readable');
  if(d.scoring==='static')out.push('the tuned risk weights are not loaded (scoring is "static")');
  var e=d.early_horizons&&d.early_horizons['1h'];
  if(e&&e.n===0&&sum===0)out.push('the 1h and 6h results are missing');
  return out;
}
function inject(){
  if(!D||!body.firstChild||body.querySelector('#pf-notice'))return;
  var g=gaps(D);if(!g.length)return;
  var n=document.createElement('div');n.id='pf-notice';n.className='pf-box';
  n.style.borderColor='rgba(245,183,59,.5)';
  n.innerHTML='<h3 style="color:#ffc94d">Data notice</h3><p class="pf-lead" style="margin:0;font-size:.9rem">Part of the measurement pipeline is temporarily unavailable ('+g.join('; ').replace(/[<>&]/g,'')+'). The numbers below come from verdicts judged before that, and recent verdicts may not be counted yet.</p>';
  body.insertBefore(n,body.firstChild);
}
function schedule(){if(timer)return;timer=setTimeout(function(){timer=null;try{inject()}catch(e){}},60)}
if(window.MutationObserver)new MutationObserver(schedule).observe(body,{childList:true});
jget('/stats').then(function(j){return (j&&j.performance)?j:jget('/accuracy')}).then(function(j){if(j&&j.performance){D=j;schedule()}});
})();
</script>
'''

try:
    if "<!--data-notice-addon-->" not in HOME_HTML:
        HOME_HTML = HOME_HTML.replace("</body>", NOTICE_ADDON + "</body>", 1)
    print("[part121] data notice add-on injected into the home page")
except NameError:
    print("[part121] HOME_HTML not found - part104 must load before part121")

# --- part122 ---
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

# --- part123 ---
# part123.py - stricter check for shadow-rule candidates (v2.97.0)
# GET /stats/rule-candidates reads the numbers already published on /stats and tests each shadow rule against a
# stricter list than the built-in "candidate" flag, which only looks at the avoid side. Read-only: it never changes
# a verdict. Walk-forward (is the gain still there on newer days?) is NOT computed here: it needs per-day outcomes
# for each rule, which /stats does not publish yet.
# Loader line (after part122, before part7):  ("part123.py", 0, "SKIP"),
import time

VERSION = "2.97.0"
app.version = VERSION
app.openapi_schema = None

_RC_CACHE = {"ts": 0.0, "data": None}
_RC_TTL = 300


def _evaluate(stats: dict) -> dict:
    rc = (stats or {}).get("rule_comparison_24h") or {}
    rules = rc.get("rules") or {}
    base = ((stats or {}).get("base_rate") or {}).get("bad_outcome_rate_pct")
    judged = rc.get("judged") or 0
    live = rules.get("live") or {}
    live_ok = live.get("ok_bad_rate_pct")
    out, strong = {}, []
    for name, r in rules.items():
        if name == "live":
            continue
        ci = r.get("precision_ci95_pct") or [None, None]
        checks = {
            "enough_avoid_flags_100": (r.get("avoid_n") or 0) >= 100,
            "precision_lower_bound_10pts_over_base": bool(ci[0] is not None and base is not None and ci[0] >= base + 10),
            "recall_at_least_10pts_over_live": (r.get("recall_vs_live_pts") or -999) >= 10,
            "precision_at_most_3pts_below_live": (r.get("precision_vs_live_pts") or -999) >= -3,
            "ok_group_not_worse_than_live_plus_2": bool(r.get("ok_bad_rate_pct") is not None and live_ok is not None
                                                        and r["ok_bad_rate_pct"] <= live_ok + 2),
            "ok_group_has_50_tokens": (r.get("ok_n") or 0) >= 50,
            "at_least_800_judged": judged >= 800,
        }
        ok = all(checks.values())
        out[name] = {"pass": ok, "builtin_candidate": r.get("candidate"), "checks": checks,
                     "avoid_n": r.get("avoid_n"), "precision_pct": r.get("precision_pct"),
                     "recall_pct": r.get("recall_pct"), "ok_n": r.get("ok_n"), "ok_bad_rate_pct": r.get("ok_bad_rate_pct"),
                     "failed": [k for k, v in checks.items() if not v]}
        if ok:
            strong.append(name)
    return {
        "version": VERSION, "horizon_hours": rc.get("horizon_hours"), "judged": judged,
        "base_rate_pct": base, "live": {"precision_pct": live.get("precision_pct"), "recall_pct": live.get("recall_pct"),
                                        "ok_bad_rate_pct": live_ok},
        "strong_candidates": strong, "rules": out, "live_verdict_unchanged": True,
        "walk_forward": "not computed: /stats publishes no per-day results for shadow rules yet",
        "note": "A rule is only a candidate. Wait for clean data after any outage, check walk-forward, then change the live rule "
                "in a numbered version and say so publicly. Heuristic, not financial advice.",
    }


async def _stats_json():
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal", timeout=30) as c:
        r = await c.get("/stats", headers={"accept": "application/json"})
        return r.json() if r.status_code == 200 else None


@app.get("/stats/rule-candidates", tags=["accuracy"])
async def stats_rule_candidates():
    now = time.time()
    if _RC_CACHE["data"] is not None and now - _RC_CACHE["ts"] < _RC_TTL:
        return _RC_CACHE["data"]
    try:
        st = await _stats_json()
    except Exception as e:
        return {"version": VERSION, "error": str(e)[:120]}
    if not isinstance(st, dict) or not (st.get("rule_comparison_24h") or {}).get("rules"):
        return {"version": VERSION, "error": "no shadow-rule data on /stats right now", "strong_candidates": []}
    data = _evaluate(st)
    _RC_CACHE.update(ts=now, data=data)
    return data


print("[part123] v%s GET /stats/rule-candidates (stricter shadow-rule check)" % VERSION)

# --- part124 ---
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

# --- part125 ---
# part125.py - Phase B filter contract for agents / desks (v2.99.2, reviewed)
# One stable block on every signal: filter.pass, policy, reasons, reading_order.
# Does not change underlying verdict logic - only packages it for downstream gates.
# Review fix vs v2.99.0: filter.pass=true could read as "safe". The block now carries the calibrated history
# (calibrated{p_bad_24h_pct, ci95_pct, based_on_n}) and a pass_note that says what pass means.
# Policies: default | strict | research (strict also fails on shadow flags, sell-sim friction and an open circuit).
# Loader: after part124, before part7.
import os
from typing import Any, Dict, List, Optional

VERSION = "2.99.2"
app.version = VERSION
app.openapi_schema = None

_DEFAULT_POLICY = (os.environ.get("FILTER_DEFAULT_POLICY") or "default").strip().lower()
if _DEFAULT_POLICY not in ("default", "strict", "research"):
    _DEFAULT_POLICY = "default"


def _verdict_of(body: dict) -> str:
    dec = body.get("decision") if isinstance(body.get("decision"), dict) else {}
    return str(dec.get("verdict") or body.get("verdict") or "unknown").lower()


def build_filter_block(body: dict, policy: Optional[str] = None) -> dict:
    pol = (policy or _DEFAULT_POLICY).lower()
    if pol not in ("default", "strict", "research"):
        pol = "default"
    v = _verdict_of(body)
    dec = body.get("decision") if isinstance(body.get("decision"), dict) else {}
    blockers = list(dec.get("blockers") or [])
    cautions = list(dec.get("cautions") or [])
    unknowns = list(dec.get("unknowns") or [])
    reasons: List[str] = []
    fail = False

    if pol == "research":
        if v != "ok":
            reasons.append("research: live verdict=%s" % v)
    else:
        if v != "ok":
            fail = True
            reasons.append("live verdict=%s" % v)
        if blockers:
            fail = True
            reasons.append("blockers=%d" % len(blockers))

    shadow = body.get("shadow_avoid") if isinstance(body.get("shadow_avoid"), dict) else {}
    sim = body.get("sim") if isinstance(body.get("sim"), dict) else {}
    stress = body.get("system_stress") if isinstance(body.get("system_stress"), dict) else {}
    if pol == "strict":
        if shadow.get("would_flag_avoid"):
            fail = True
            reasons.append("shadow_avoid would_flag_avoid (%s)" % ",".join(shadow.get("rules_hit") or [])[:80])
        if sim.get("honeypot_risk_heuristic"):
            fail = True
            reasons.append("sim.honeypot_risk_heuristic")
        if sim.get("sell_ok") is False:
            fail = True
            reasons.append("sim.sell_ok=false")
        if stress.get("state") == "open":
            fail = True
            reasons.append("system_stress=open")

    passed = True if pol == "research" else (not fail)

    cal = body.get("calibrated_risk") if isinstance(body.get("calibrated_risk"), dict) else {}
    calibrated = None
    if cal:
        calibrated = {"p_bad_24h_pct": cal.get("p_bad_24h_pct"), "ci95_pct": cal.get("ci95_pct"),
                      "based_on_n": cal.get("based_on_n"), "base_rate_pct": cal.get("base_rate_pct")}
    if pol == "research":
        pass_note = "research policy never gates: pass is always true. Read the reasons only."
    elif passed:
        pass_note = "pass means the live verdict is ok and no blocker was found. It is not a guarantee."
        if calibrated and calibrated.get("p_bad_24h_pct") is not None:
            pass_note += " Similar past verdicts: %s%% ended badly within 24h (n=%s)." % (
                calibrated["p_bad_24h_pct"], calibrated.get("based_on_n"))
    else:
        pass_note = "pass is false: see reasons."

    return {
        "pass": passed,
        "policy": pol,
        "pass_note": pass_note,
        "live_verdict": v,
        "reasons": reasons[:12],
        "blockers_n": len(blockers),
        "cautions_n": len(cautions),
        "unknowns_n": len(unknowns),
        "calibrated": calibrated,
        "valid_for_s": dec.get("valid_for_s") or body.get("valid_for_s"),
        "system_stress": stress.get("state"),
        "sim_sell_ok": sim.get("sell_ok"),
        "shadow_would_avoid": shadow.get("would_flag_avoid"),
        "reading_order": ["filter.pass", "filter.reasons", "filter.calibrated", "decision.verdict", "decision.blockers",
                          "decision.cautions", "decision.unknowns", "sim", "system_stress"],
        "policies": {
            "default": "pass only if live verdict is ok (and no blockers)",
            "strict": "default + fail on shadow_avoid / sim honeypot-ish / circuit open",
            "research": "always pass=true; reasons only - do not gate size on this policy",
        },
        "disclaimer": "Heuristic filter for agents. Not financial advice. Not a guarantee against rugs or honeypots.",
        "version": VERSION,
    }


def attach_filter(body: dict, policy: Optional[str] = None) -> dict:
    if isinstance(body, dict):
        body["filter"] = build_filter_block(body, policy)
    return body


_build_prev_125 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    policy = kwargs.pop("filter_policy", None)
    res = await _build_prev_125(client, mint, security, *args, **kwargs)
    try:
        body = res[0] if isinstance(res, tuple) else res
        if isinstance(body, dict):
            attach_filter(body, policy)
        return res
    except Exception as e:
        print("[part125] filter:", e)
        return res


@app.get("/filter/policies", tags=["agents"], include_in_schema=False)
async def filter_policies():
    return {
        "version": VERSION,
        "default_policy": _DEFAULT_POLICY,
        "policies": {
            "default": "Gate: pass iff live verdict == ok and no blockers.",
            "strict": "Gate: default + shadow_avoid.would_flag_avoid + sim honeypot-ish + circuit open.",
            "research": "Never gate (pass always true). Use for analysis only.",
        },
        "env": "FILTER_DEFAULT_POLICY=default|strict|research",
        "on_signal": "Every /omni and /signal includes a filter{} block.",
        "note": "Strict is for desks that want fewer false comforts; expect a lower pass rate.",
    }


print("[part125] v%s filter contract (with calibrated history) -> filter.* on signal; GET /filter/policies" % VERSION)

# --- part126 ---
# part126.py - Ensure the Phase B filter (and late fields) on /omni responses (v2.99.2, reviewed)
# /signal already gets filter.* through build_signal; /omni used a path that skipped the final wrappers.
# Review fixes vs v2.99.1:
#   - the wrapper was always async: if the /omni handler is a plain (sync) function FastAPI would have received an
#     un-awaited coroutine. The wrapper now matches the handler type.
#   - when it rebuilds a JSONResponse it keeps the original headers (cache-control etc.).
import functools
import inspect
import json
from typing import Optional


def _enrich_payload(body: dict, policy: Optional[str] = None) -> dict:
    if not isinstance(body, dict):
        return body
    if callable(globals().get("_ensure_shadow_cluster")):
        try:
            _ensure_shadow_cluster(body)
        except Exception:
            pass
    if "system_stress" not in body and callable(globals().get("circuit_status")):
        try:
            st = circuit_status()
            body["system_stress"] = {"state": st.get("state"), "reason": st.get("reason"),
                                     "note": "When open/half, prefer smaller size or wait; data may be stale or partial."}
        except Exception:
            pass
    if callable(globals().get("attach_filter")):
        try:
            attach_filter(body, policy)
        except Exception as e:
            print("[part126] attach_filter:", e)
    elif callable(globals().get("build_filter_block")):
        try:
            body["filter"] = build_filter_block(body, policy)
        except Exception as e:
            print("[part126] build_filter_block:", e)
    return body


def _policy_from(args, kwargs) -> Optional[str]:
    request = kwargs.get("request")
    if request is None:
        for a in args:
            if hasattr(a, "query_params"):
                request = a
                break
    try:
        if request is not None:
            return request.query_params.get("policy") or request.query_params.get("filter_policy")
    except Exception:
        pass
    return None


def _post(res, policy):
    if isinstance(res, dict):
        return _enrich_payload(res, policy)
    body = getattr(res, "body", None)
    if body is not None and hasattr(res, "media_type"):
        try:
            data = json.loads(body.decode() if isinstance(body, (bytes, bytearray)) else body)
            if isinstance(data, dict):
                from fastapi.responses import JSONResponse
                headers = {k: v for k, v in dict(getattr(res, "headers", {}) or {}).items()
                           if k.lower() not in ("content-length", "content-type")}
                return JSONResponse(_enrich_payload(data, policy), status_code=getattr(res, "status_code", 200),
                                    headers=headers)
        except Exception as e:
            print("[part126] omni response wrap:", e)
    return res


def _make_wrapper(endpoint):
    if inspect.iscoroutinefunction(endpoint):
        @functools.wraps(endpoint)
        async def wrapped(*args, **kwargs):
            policy = _policy_from(args, kwargs)
            res = await endpoint(*args, **kwargs)
            return _post(res, policy)
    else:
        @functools.wraps(endpoint)
        def wrapped(*args, **kwargs):
            policy = _policy_from(args, kwargs)
            return _post(endpoint(*args, **kwargs), policy)
    wrapped._tvibe_filter_wrapped = True
    return wrapped


def _wrap_omni_endpoint() -> bool:
    try:
        for route in list(app.routes):
            if (getattr(route, "path", None) or "").rstrip("/") != "/omni":
                continue
            endpoint = getattr(route, "endpoint", None)
            if not callable(endpoint):
                continue
            if getattr(endpoint, "_tvibe_filter_wrapped", False):
                return True
            wrapped = _make_wrapper(endpoint)
            route.endpoint = wrapped
            dep = getattr(route, "dependant", None)
            if dep is not None:
                dep.call = wrapped
            print("[part126] wrapped GET /omni for the filter contract (%s)" % ("async" if inspect.iscoroutinefunction(endpoint) else "sync"))
            return True
    except Exception as e:
        print("[part126] wrap_omni:", e)
    return False


if not _wrap_omni_endpoint():
    print("[part126] /omni route not found or not patchable; /signal still carries filter.* via build_signal")

print("[part126] v2.99.2 /omni gets filter.* (and shadow/stress if helpers exist)")

# --- part127 ---
# part127.py — Phase C cost & reliability surface for agents/desks (v3.0.0)
# Fair-use text, degrade hints, keep-alive, ops pointers. Does not tighten Redis beyond part124.
# Loader: after part126, before part7 → ("part127.py", 0, "SKIP"),
import os
import time
from typing import Any, Dict, Optional

VERSION = "3.0.0"
app.version = VERSION
app.openapi_schema = None

_START = time.time()
_PUBLIC = (os.environ.get("PUBLIC_BASE_URL") or "https://signal-api-24q4.onrender.com").rstrip("/")

# Soft guidance (not a hard global limiter — existing per-route limits still apply)
_FAIR = {
    "tier": "free_public",
    "guidance": {
        "burst_omni_per_min": "Keep automated omni/signal under \~20/min/IP when possible",
        "prefer": "Cache filter.pass + valid_for_s; do not poll the same mint every second",
        "upstream": "DexScreener/Gecko/RPC rate limits are outside TVibe — expect partial or 503 under load",
        "redis": "Shared free Redis: high traffic may degrade track-record writes; self-host if you need dedicated quota",
    },
    "self_host": "https://github.com/TVibe-signal/signal-api",
    "keep_alive": "GET /ping or /health every 10–14 min if on free web dyno",
    "ops": {
        "redis_meter": "/ops/redis",
        "redis_thrift": "/ops/redis-thrift",
        "circuit": "/system/circuit",
        "filter_policies": "/filter/policies",
    },
}


def reliability_snapshot() -> dict:
    stress = None
    if callable(globals().get("circuit_status")):
        try:
            stress = circuit_status()
        except Exception:
            stress = None
    return {
        "version": VERSION,
        "uptime_s": int(time.time() - _START),
        "system_stress": (stress or {}).get("state") if isinstance(stress, dict) else None,
        "fair_use": _FAIR,
        "sla": {
            "class": "best_effort_free",
            "no_uptime_guarantee": True,
            "partial_responses": True,
            "note": "When sources degrade, decision.unknowns and system_stress grow — treat as soft fail, not silent success.",
        },
        "agent_contract": {
            "primary": "GET /omni?mint=",
            "gate": "filter.pass (policy=default|strict|research)",
            "ttl": "filter.valid_for_s / decision.valid_for_s",
            "reading_order": (globals().get("build_filter_block") and "see filter.reading_order on each signal")
            or ["filter.pass", "decision.verdict", "decision.blockers", "sim", "system_stress"],
        },
        "disclaimer": "Heuristic. Not financial advice. Not an exchange or custody service.",
    }


@app.get("/agents/reliability", tags=["agents"], include_in_schema=False)
@app.get("/reliability", tags=["agents"], include_in_schema=False)
async def agents_reliability():
    return reliability_snapshot()


@app.get("/pricing", tags=["agents"], include_in_schema=False)
async def pricing_fair_use():
    """Honest free tier — no fake paid SKUs."""
    return {
        "version": VERSION,
        "public_instance": _PUBLIC,
        "price": "0",
        "currency": "USD",
        "model": "free_public_best_effort",
        "fair_use": _FAIR["guidance"],
        "donate_optional": "See homepage if a SOL donate address is shown — never required for API access",
        "self_host": _FAIR["self_host"],
        "paid_plans": None,
        "note": "No paywall. If you need dedicated Redis/RPC quota, run self-host or bring your own keys.",
        "reliability": "/agents/reliability",
    }


# Attach a compact reliability hint on signal payloads (non-breaking)
_build_prev_127 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_127(client, mint, security, *args, **kwargs)
    try:
        body = res[0] if isinstance(res, tuple) else res
        if isinstance(body, dict):
            body.setdefault(
                "reliability",
                {
                    "class": "best_effort_free",
                    "docs": "/agents/reliability",
                    "fair_use": "/pricing",
                },
            )
            # If circuit open, make filter/reasons already handle strict; still expose hint
            st = body.get("system_stress") if isinstance(body.get("system_stress"), dict) else {}
            if st.get("state") in ("open", "half"):
                body["reliability"]["degraded"] = True
                body["reliability"]["hint"] = "Upstream stress — prefer wait or smaller size; check /system/circuit"
        return res
    except Exception as e:
        print("[part127] ", e)
        return res


# Re-touch /omni enrichment if part126 helpers exist
_prev_enrich = globals().get("_enrich_payload")
if callable(_prev_enrich):
    def _enrich_payload(body, policy=None):  # noqa: N802
        body = _prev_enrich(body, policy)
        if isinstance(body, dict):
            body.setdefault(
                "reliability",
                {"class": "best_effort_free", "docs": "/agents/reliability", "fair_use": "/pricing"},
            )
        return body


print("[part127] v%s Phase C → GET /agents/reliability /pricing + reliability on signal" % VERSION)

# --- part128 ---
# part128.py - GET /pricing: honest free tier (v3.0.2, reviewed)
# Review fix vs v3.0.1: /pricing already existed from an older part (first registered route wins), so neither part127 nor the
# old part128 ever answered. This version removes the older /pricing route(s) first. Browsers get a small page, agents get JSON.
VERSION = "3.0.2"
app.version = VERSION
app.openapi_schema = None

import html as _html
import os

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

try:
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/pricing"]
except Exception as _e:
    print("[part128] could not remove an older /pricing route:", str(_e)[:100])


def _pricing_payload() -> dict:
    base = str(globals().get("_PUBLIC") or os.environ.get("PUBLIC_BASE_URL") or "https://signal-api-24q4.onrender.com").rstrip("/")
    fair = globals().get("_FAIR") if isinstance(globals().get("_FAIR"), dict) else {}
    guidance = fair.get("guidance") if isinstance(fair.get("guidance"), dict) else {
        "prefer": "Cache filter.pass + valid_for_s; avoid polling the same mint every second",
        "upstream": "Dex/Gecko/RPC limits are outside TVibe"}
    return {"version": VERSION, "public_instance": base, "price": "0", "currency": "USD",
            "model": "free_public_best_effort", "fair_use": guidance,
            "self_host": fair.get("self_host") or "https://github.com/TVibex402/signal-api",
            "paid_plans": None, "reliability": "/agents/reliability",
            "note": "No paywall. Self-host if you need a dedicated Redis/RPC quota."}


@app.get("/pricing", tags=["agents"], include_in_schema=False)
async def pricing_fair_use_v3(request: Request):
    try:
        data = _pricing_payload()
        if "text/html" in (request.headers.get("accept") or "") and "json" not in (request.headers.get("accept") or ""):
            items = "".join("<li><b>%s</b>: %s</li>" % (_html.escape(k), _html.escape(str(v))) for k, v in data["fair_use"].items())
            page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                    "<title>TVibe Signal pricing</title><body style='background:#070b12;color:#e8eef6;font:16px/1.6 system-ui;padding:1.2rem;max-width:720px;margin:auto'>"
                    "<h1>Free, best effort</h1><p>No paywall. The public instance is free; self-host if you need a dedicated quota.</p>"
                    "<h3>Fair use</h3><ul>%s</ul><p><a style='color:#14f195' href='%s'>Self-host (GitHub)</a> &middot; "
                    "<a style='color:#14f195' href='/agents/reliability'>Reliability</a> &middot; <a style='color:#14f195' href='/'>Home</a></p>"
                    "<p style='color:#9db0ca'>Heuristic. Not financial advice.</p>" % (items, _html.escape(data["self_host"])))
            return HTMLResponse(page)
        return data
    except Exception as e:
        return JSONResponse({"version": VERSION, "price": "0", "model": "free_public_best_effort", "error": str(e)[:120]}, status_code=200)


print("[part128] v%s /pricing (older route removed first)" % VERSION)

# --- part129 ---
# part129.py — Phase D policy status (read-only, no live rule changes)
VERSION = "3.0.1"
app.version = VERSION
app.openapi_schema = None

@app.get("/filter/phase-d", tags=["agents"], include_in_schema=False)
async def filter_phase_d():
    strong, judged, err = [], None, None
    try:
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal", timeout=30) as c:
            r = await c.get("/stats/rule-candidates")
            d = r.json() if r.status_code == 200 else {}
            strong = d.get("strong_candidates") or []
            judged = d.get("judged")
            err = d.get("error")
    except Exception as e:
        err = str(e)[:120]
    ready = bool(strong) and not err
    return {
        "version": VERSION,
        "phase": "D",
        "live_rules_unchanged": True,
        "promote_ready": ready,
        "strong_candidates": strong,
        "judged": judged,
        "error": err,
        "how_to_use_now": {
            "default": "GET /omni?mint=  → filter.pass",
            "strict": "GET /omni?mint=&policy=strict  (stricter gate, still no silent rule rewrite)",
            "research": "policy=research → pass always true, reasons only",
        },
        "promote_checklist": [
            "strong_candidates non-empty on /stats/rule-candidates",
            "clean data after outages",
            "walk-forward when available",
            "public version bump + changelog before any live rule change",
        ],
        "note": "Phase D does not auto-promote. Empty strong_candidates means wait and feed outcomes.",
    }

print("[part129] v%s GET /filter/phase-d (no auto-promote)" % VERSION)

# --- part130 ---
# part130.py — Show filter.pass on the home token card (Phase B UI)
# Patches HOME_HTML from part104: one chip next to the other status chips.
VERSION = "3.0.2"
app.version = VERSION
app.openapi_schema = None

_INJECT_FROM = "if(chips)h+='<div class=\"r-chips\">'+chips+'</div>';"
_INJECT_TO = (
    "var fl=d.filter;if(fl&&typeof fl==='object'&&fl.pass!=null){"
    "chips=(chips||'')+chip(fl.pass?'Filter: PASS':'Filter: BLOCK',fl.pass?'ok':'bad');"
    "if(fl.policy)chips+=chip('policy '+String(fl.policy),'');"
    "if(!fl.pass&&fl.reasons&&fl.reasons.length)chips+=chip(String(fl.reasons[0]).slice(0,48),'warn');"
    "}"
    "if(chips)h+='<div class=\"r-chips\">'+chips+'</div>';"
)

_CSS_EXTRA = """
<style id="tvibe-filter-chip">
.r-chips .r-chip.ok{border-color:rgba(46,204,113,.45)}
.r-chips .r-chip.bad{border-color:rgba(255,107,100,.5);color:#ffb4b0}
</style>
"""

def _patch_home_html():
    html = globals().get("HOME_HTML")
    if not isinstance(html, str):
        print("[part130] HOME_HTML not found — skip UI patch")
        return False
    if "Filter: PASS" in html or "tvibe-filter-chip" in html:
        print("[part130] already patched")
        return True
    if _INJECT_FROM not in html:
        # alternate quote style
        alt = _INJECT_FROM.replace("\"", "'")
        if alt in html:
            html = html.replace(alt, _INJECT_TO.replace("\"", "'"), 1)
        else:
            print("[part130] chips anchor not found — check part104 render()")
            return False
    else:
        html = html.replace(_INJECT_FROM, _INJECT_TO, 1)
    if "</head>" in html:
        html = html.replace("</head>", _CSS_EXTRA + "</head>", 1)
    elif "</body>" in html:
        html = html.replace("</body>", _CSS_EXTRA + "</body>", 1)
    globals()["HOME_HTML"] = html
    # re-bind / if home closed over old string
    for route in list(app.routes):
        if getattr(route, "path", None) == "/" and getattr(route, "methods", None):
            endpoint = getattr(route, "endpoint", None)
            if callable(endpoint):
                async def _home():
                    return HTMLResponse(globals()["HOME_HTML"])
                try:
                    from fastapi.responses import HTMLResponse
                    route.endpoint = _home
                    if hasattr(route, "dependant") and route.dependant is not None:
                        route.dependant.call = _home
                except Exception as e:
                    print("[part130] route rebind:", e)
    print("[part130] HOME_HTML patched — filter.pass chip on card")
    return True


try:
    from fastapi.responses import HTMLResponse  # noqa: F401
except Exception:
    pass

_ok = _patch_home_html()
print("[part130] v%s filter.pass on web UI (%s)" % (VERSION, "ok" if _ok else "miss"))

# --- part131 ---
# part131.py - Walk-forward from daily snapshots of the shadow-rule totals (v3.0.4)
# /stats publishes only cumulative counts per shadow rule, so "is the gain still there on NEWER data?" cannot be read
# from it. This keeps one small snapshot per UTC day (2 Redis commands per day, 1 read after a restart) and
# subtracts an older snapshot from the latest one: the difference is the performance on tokens judged in between.
#   GET /stats/walk-forward?days=7   per-rule precision/recall/ok-group on the new window + pass/fail checks
#   GET /changelog                   public list of rule versions (edit CHANGELOG below when a rule changes)
#   /stats now also carries rule_version and a pointer to walk-forward.
# Part123's /stats/rule-candidates gets walk_forward + promote_ready (strong candidates that also pass walk-forward).
# Nothing here changes a verdict. Needs part97 (/stats shape) and part123 loaded before it.
# Loader line (after part129/130, before part7):  ("part131.py", 0, "SKIP"),
import json
import math
import os
import time
import types

VERSION = "2.99.3"
app.version = VERSION
app.openapi_schema = None

RULE_VERSION = os.environ.get("RULE_VERSION", "avoid-v1")
_WF_KEY = "si:walkfwd:snaps"
_WF_KEEP = 120
_WF = types.SimpleNamespace(snaps=[], loaded=False, last_day="", persistent=False, err="")

CHANGELOG = [
    {"version": "2.88", "change": "Every /omni verdict is signed (Ed25519) and hash-chained; /verify checks it in the browser."},
    {"version": "2.89", "change": "Results by source on the home page; decision.verdict follows a capped verdict."},
    {"version": "2.91", "change": "llms.txt rewritten; deployer shadow stats (research only)."},
    {"version": "2.92", "change": "Telegram bot answers /check ADDRESS with the same verdict as /omni."},
    {"version": "2.94", "change": "Sell-quote simulation (sim.*) on signals; an unavailable quote is unknown, not a warning."},
    {"version": "2.97", "change": "Redis usage meter and stricter shadow-rule candidate check (/stats/rule-candidates)."},
    {"version": "2.99", "change": "filter.pass contract with policies default | strict | research."},
    {"version": "2.99.3", "change": "Walk-forward on newer data (/stats/walk-forward). Live rule unchanged: " + RULE_VERSION + "."},
]


def _wilson(k: int, n: int, z: float = 1.96):
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def _day(ts=None) -> str:
    return time.strftime("%Y%m%d", time.gmtime(ts if ts is not None else time.time()))


def _extract(stats: dict):
    rules = ((stats or {}).get("shadow_rules") or {}).get("rules") or {}
    if not (rules.get("live") or {}).get("judged"):
        return None
    snap = {"ts": int(time.time()), "rules": {}}
    for name, r in rules.items():
        av, ok = r.get("avoid") or {}, r.get("ok") or {}
        n, rate = int(av.get("n") or 0), av.get("bad_outcome_rate_pct")
        okn, okrate = int(ok.get("n") or 0), ok.get("bad_outcome_rate_pct")
        snap["rules"][name] = {
            "judged": int(r.get("judged") or 0), "bad": int(r.get("bad") or 0),
            "avoid_n": n, "avoid_bad": int(round(n * rate / 100.0)) if rate is not None else None,
            "ok_n": okn, "ok_bad": int(round(okn * okrate / 100.0)) if okrate is not None else None}
    return snap


def _client():
    return getattr(getattr(app, "state", None), "client", None)


async def _load():
    if _WF.loaded:
        return
    _WF.loaded = True
    try:
        if "redis_pipe" in globals() and _client() is not None:
            raw = await redis_pipe(_client(), [["LRANGE", _WF_KEY, 0, _WF_KEEP - 1]])
            items = (raw or [[]])[0] or []
            snaps = []
            for s in items:
                try:
                    snaps.append(json.loads(s))
                except Exception:
                    pass
            snaps.sort(key=lambda x: -x.get("ts", 0))
            if snaps:
                _WF.snaps = snaps
            _WF.persistent = True
    except Exception as e:
        _WF.err = str(e)[:100]


async def _maybe_snapshot(stats: dict):
    day = _day()
    if _WF.last_day == day:
        return
    await _load()
    if _WF.snaps and _day(_WF.snaps[0].get("ts")) == day:
        _WF.last_day = day
        return
    snap = _extract(stats)
    if snap is None:
        return
    _WF.snaps.insert(0, snap)
    del _WF.snaps[_WF_KEEP:]
    _WF.last_day = day
    try:
        if "redis_pipe" in globals() and _client() is not None:
            await redis_pipe(_client(), [["LPUSH", _WF_KEY, json.dumps(snap, separators=(",", ":"))],
                                         ["LTRIM", _WF_KEY, 0, _WF_KEEP - 1]])
    except Exception as e:
        _WF.err = str(e)[:100]


def _wf_compute(days: int = 7) -> dict:
    snaps = _WF.snaps
    if len(snaps) < 2:
        return {"ready": False, "reason": "needs at least 2 daily snapshots (one is stored per day)", "snapshots": len(snaps)}
    L = snaps[0]
    target = L["ts"] - days * 86400
    P = next((s for s in snaps[1:] if s["ts"] <= target), snaps[-1])
    span = round((L["ts"] - P["ts"]) / 86400.0, 1)
    lv_l, lv_p = L["rules"].get("live"), P["rules"].get("live")
    if not lv_l or not lv_p:
        return {"ready": False, "reason": "live rule missing in a snapshot"}
    dj, db = lv_l["judged"] - lv_p["judged"], lv_l["bad"] - lv_p["bad"]
    if dj <= 0 or db < 0:
        return {"ready": False, "reason": "counters reset or no new judged outcomes in this window", "window_days": span}
    base = 100.0 * db / dj
    rows = {}
    for name, a in L["rules"].items():
        b = P["rules"].get(name)
        if not b or a["avoid_bad"] is None or b["avoid_bad"] is None:
            continue
        dn, dab = a["avoid_n"] - b["avoid_n"], a["avoid_bad"] - b["avoid_bad"]
        if dn < 0 or dab < 0 or dab > dn:
            continue
        okn = a["ok_n"] - b["ok_n"]
        okb = (a["ok_bad"] - b["ok_bad"]) if (a["ok_bad"] is not None and b["ok_bad"] is not None) else None
        rows[name] = {"avoid_n": dn, "precision_pct": round(100.0 * dab / dn, 1) if dn else None,
                      "precision_ci95_pct": _wilson(dab, dn), "recall_pct": round(100.0 * dab / db, 1) if db else None,
                      "ok_n": okn, "ok_bad_rate_pct": round(100.0 * okb / okn, 1) if (okb is not None and okn > 0 and 0 <= okb <= okn) else None}
    live = rows.get("live")
    for name, r in rows.items():
        if name == "live" or not live:
            continue
        r["recall_vs_live_pts"] = round((r["recall_pct"] or 0) - (live["recall_pct"] or 0), 1)
        r["precision_vs_live_pts"] = round((r["precision_pct"] or 0) - (live["precision_pct"] or 0), 1)
        ci = r["precision_ci95_pct"]
        checks = {
            "enough_avoid_flags_150": r["avoid_n"] >= 150,
            "precision_lower_bound_10pts_over_base": bool(ci and ci[0] >= base + 10),
            "recall_at_least_10pts_over_live": r["recall_vs_live_pts"] >= 10,
            "precision_at_most_3pts_below_live": r["precision_vs_live_pts"] >= -3,
            "ok_group_not_worse_than_live_plus_2": bool(r["ok_bad_rate_pct"] is not None and live["ok_bad_rate_pct"] is not None
                                                        and r["ok_bad_rate_pct"] <= live["ok_bad_rate_pct"] + 2),
            "ok_group_has_40_tokens": r["ok_n"] >= 40}
        r["checks"], r["pass"] = checks, all(checks.values())
        r["failed"] = [k for k, v in checks.items() if not v]
    return {"ready": True, "window_days": span, "requested_days": days, "judged_in_window": dj,
            "base_rate_pct_in_window": round(base, 1), "from_ts": P["ts"], "to_ts": L["ts"],
            "snapshots": len(snaps), "rules": rows,
            "note": "Only tokens judged inside the window. A rule has to pass here AND on the all-time check before any live change."}


@app.get("/stats/walk-forward", tags=["accuracy"])
async def stats_walk_forward(days: int = 7):
    await _load()
    out = _wf_compute(max(1, min(int(days), 60)))
    out.update({"version": VERSION, "live_verdict_unchanged": True, "persistent": _WF.persistent,
                "storage_error": _WF.err or None, "rule_version": RULE_VERSION})
    return out


@app.get("/changelog", tags=["accuracy"])
async def changelog():
    return {"version": VERSION, "rule_version": RULE_VERSION, "entries": CHANGELOG,
            "policy": "A live rule changes only after the checks on /stats/rule-candidates and /stats/walk-forward pass, "
                      "with a new rule_version and an entry here."}


# part123's candidate list also shows walk-forward and a promote_ready shortlist
_prev_eval_131 = globals().get("_evaluate")
if callable(_prev_eval_131):
    def _evaluate(stats):  # noqa: N802 (part123's route looks this name up at request time)
        d = _prev_eval_131(stats)
        try:
            wf = _wf_compute(7)
            d["walk_forward"] = wf
            for name, row in (d.get("rules") or {}).items():
                row["walk_forward_pass"] = bool(((wf.get("rules") or {}).get(name) or {}).get("pass"))
            d["promote_ready"] = [n for n in (d.get("strong_candidates") or []) if ((wf.get("rules") or {}).get(n) or {}).get("pass")]
        except Exception as e:
            print("[part131] evaluate:", str(e)[:100])
        return d


class _WalkForwardMW:
    """Sees every GET /stats answer: takes the daily snapshot and adds rule_version."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/stats" or scope.get("method") != "GET":
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
                hs = {k.lower(): v for k, v in start["headers"]}
                if start.get("status") == 200 and b"json" in hs.get(b"content-type", b"") and b"content-encoding" not in hs:
                    d = json.loads(body)
                    if isinstance(d, dict):
                        await _maybe_snapshot(d)
                        d["rule_version"] = RULE_VERSION
                        d["walk_forward"] = "/stats/walk-forward"
                        body = json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            except Exception as e:
                print("[part131] stats mw:", str(e)[:100])
            hdrs = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"] + [(b"content-length", str(len(body)).encode())]
            await send({**start, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, cap)


try:
    app.add_middleware(_WalkForwardMW)
except Exception as _e:
    print("[part131] could not add middleware:", str(_e)[:100])

print("[part131] v%s walk-forward from daily snapshots -> GET /stats/walk-forward, /changelog (rule_version=%s)" % (VERSION, RULE_VERSION))

# --- part132 ---
# part132.py - llms.txt for agents (override any earlier /llms.txt) (v3.0.4, reviewed)
# Review fixes vs v3.0.3: "\~120" and "\~30" were invalid escapes (SyntaxWarning, and the text showed a backslash);
# "GET /filter/walk-forward" does not exist, the endpoint is /stats/walk-forward.
# Check that GET /ping exists (the health board at /ops/health reports missing routes); if not, use /health.
VERSION = "3.0.4"
app.version = VERSION
app.openapi_schema = None

from fastapi.responses import PlainTextResponse

_LLMS = """# TVibe Signal
> Solana token **risk** signals for AI agents. Heuristics, measured in public. Not financial advice.
> Free public instance: no paywall on the core signal today. Self-host anytime.

## Primary interface (use this first)
- HTTP: GET https://signal-api-24q4.onrender.com/omni?mint=<SOLANA_MINT>
- Gate: response.filter.pass + response.decision.verdict
- Policies: default | strict | research. GET /filter/policies or ?policy=strict
- MCP:  https://signal-api-24q4.onrender.com/mcp
- MCP tool: omni(mint)

Reading order: filter.pass, filter.reasons, decision.verdict, blockers/cautions/unknowns, sim, system_stress.
Trust decision.* first. Treat debate / residual / dna / shadow_* as optional context only.
When decision.unknowns is non-empty, prefer caution over size.

## Agent pattern (before size)
1. omni(mint) or GET /omni?mint=
2. if filter.pass is false: do not size (or hard-cap)
3. if pass and verdict ok: still read cautions, sim, system_stress
4. cache the mint for valid_for_s seconds (15 to 120, see decision.valid_for_s)

## Prove it
- GET /stats
- GET /stats/rule-candidates
- GET /stats/walk-forward
- GET /benchmark/daily
- GET /verify (check a signed verdict in the browser)

## Fair use (free core, best effort)
- /agents/reliability and /pricing
- about 30 requests per minute. Heavy use: self-host.
- Keep-alive: GET /ping every 10 to 14 minutes (do not save large response bodies)

## Secondary
- /signal, /signals, /exit, /health, /ping

## Repo and social
- https://github.com/TVibe-signal/signal-api
- https://x.com/realTVibe
- Telegram: https://t.me/Gotvibesolbot

## Disclaimer
Heuristics for agents and research. Not financial advice. Data can be late, partial, or wrong.
"""

try:
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/llms.txt"]
except Exception as _e:
    print("[part132] could not drop older /llms.txt:", str(_e)[:100])


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt_free_core():
    return PlainTextResponse(_LLMS, media_type="text/plain; charset=utf-8")


print("[part132] v%s /llms.txt overridden (filter.pass, walk-forward, verify)" % VERSION)

# --- part133 ---
# part133.py - nav: Telegram bot + GitHub org link (v3.0.5, reviewed)
# Review fixes vs v3.0.4:
#   - it assigned _TG and _html. All parts share ONE namespace: _TG is part114's Telegram state object (updates,
#     replies, rate limits, bot username) and _html is part128's html module. After this part loaded, every Telegram
#     webhook raised "'str' object has no attribute 'updates'" and the /pricing page failed. Names are unique now.
#   - removed a condition that was always true.
# Set the GitHub link with the env var GITHUB_URL if the repo moves again.
import os

VERSION = "3.0.5"
app.version = VERSION
app.openapi_schema = None

_TG_LINK = "https://t.me/Gotvibesolbot"
_GITHUB_LINK = os.environ.get("GITHUB_URL", "https://github.com/TVibe-signal/signal-api").rstrip("/")
_X_LINK = "https://x.com/realTVibe"
_OLD_GITHUB = "https://github.com/TVibex402/signal-api"
_X_PILL = ('<a class="pill" href="%s" target="_blank" rel="noopener noreferrer">'
           '<svg class="ic"><use href="#i-x"/></svg>X</a>' % _X_LINK)
_TG_PILL = '<a class="pill" href="%s" target="_blank" rel="noopener noreferrer">Telegram</a>' % _TG_LINK
_HERO_OLD = 'Track record is public on <a href="/stats">/stats</a>.'
_HERO_NEW = (_HERO_OLD + ' Check a mint on the web, <a href="/mcp">MCP</a> or the '
             '<a href="%s" target="_blank" rel="noopener noreferrer">Telegram bot</a>: same verdict as <code>/omni</code>.' % _TG_LINK)


def _patch_page(text: str) -> str:
    text = text.replace(_OLD_GITHUB, _GITHUB_LINK).replace("github.com/TVibex402/signal-api", _GITHUB_LINK.replace("https://", ""))
    if "Gotvibesolbot" not in text:
        if _X_PILL in text:
            text = text.replace(_X_PILL, _X_PILL + "\n      " + _TG_PILL, 1)
        elif "GitHub</a>" in text:
            text = text.replace("GitHub</a>", "GitHub</a>\n      " + _TG_PILL, 1)
        if "Telegram bot" not in text and _HERO_OLD in text:
            text = text.replace(_HERO_OLD, _HERO_NEW, 1)
    return text


_home_page = globals().get("HOME_HTML")
if isinstance(_home_page, str):
    HOME_HTML = _patch_page(_home_page)


class _TgLinkMW:
    """Same fix for pages that are not built from HOME_HTML (/agents, /index.html). Fail-safe."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "GET" or (scope.get("path") or "") not in ("/", "/agents", "/index.html"):
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
                hs = {k.lower(): v for k, v in start.get("headers") or []}
                if start.get("status") == 200 and b"text/html" in hs.get(b"content-type", b"") and b"content-encoding" not in hs:
                    text = body.decode("utf-8", "ignore")
                    patched = _patch_page(text)
                    if patched != text:
                        body = patched.encode("utf-8")
            except Exception:
                pass
            hdrs = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"] + [(b"content-length", str(len(body)).encode())]
            await send({**start, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, cap)


try:
    app.add_middleware(_TgLinkMW)
except Exception as _e:
    print("[part133] mw:", str(_e)[:100])

print("[part133] v%s Telegram %s on the home nav, GitHub link %s" % (VERSION, _TG_LINK, _GITHUB_LINK))

# --- part134 ---
# part134.py - One-page health board + schema check (v2.99.5)
#   GET /ops/health                 one JSON that answers "is TVibe healthy?" (open it on the phone and screenshot it)
#   GET /ops/contract-check?mint=   calls /omni and /signal in-process and lists missing contract fields
#   /omni and /signal now carry schema_version
# The health board tests Redis with a real write + read back, reads /stats, the circuit, the signed-verdict chain,
# the cache, the Redis meter, the Telegram counters and the walk-forward snapshots, then says green / amber / red with
# plain reasons. Every section is optional: a part that is not loaded is reported as "not loaded", never as an error.
# Optional: set OPS_KEY and call /ops/health?key=<value>. Costs 2 Redis commands per call (the write + read test).
# Loader line (after part131, before part7):  ("part134.py", 0, "SKIP"),
import json
import os
import time

from fastapi.responses import JSONResponse

VERSION = "2.99.5"
app.version = VERSION
app.openapi_schema = None

SCHEMA_VERSION = "1.0"
_H_LAST = {"ts": 0.0, "judged": None}
_EXPECTED_ROUTES = ["/omni", "/signal", "/exit", "/stats", "/verify", "/attest", "/llms.txt", "/benchmark/daily", "/ping", "/health", "/pricing",
                    "/stats/rule-candidates", "/stats/walk-forward", "/changelog", "/filter/policies", "/ops/redis",
                    "/system/circuit", "/cachez", "/telegram/status", "/agents/reliability"]
_PARTS = {"signed verdicts (part105)": "_attest", "sell-sim (part119)": "_sim_from_exit", "circuit (part116)": "circuit_status",
          "filter contract (part125)": "build_filter_block", "redis meter (part122)": "_RM", "redis thrift (part124)": "_coalesce_cmds",
          "response cache (part112)": "_CacheMW", "telegram (part114)": "_tg_handle", "walk-forward (part131)": "_wf_compute",
          "rule candidates (part123)": "_evaluate", "outcome labels (part108)": "_LABELED_108"}
_REQ_OMNI = ["decision.verdict", "decision.blockers", "decision.cautions", "decision.unknowns", "decision.valid_for_s",
             "would_change_my_mind", "system_stress", "filter.pass", "filter.reasons", "sim", "attestation"]
_REQ_SIGNAL = ["decision.verdict", "decision.valid_for_s", "would_change_my_mind", "system_stress", "filter.pass", "sim",
               "calibrated_risk", "track_record_context"]


# All parts share ONE namespace, so a later part that reuses a name (for example _TG) silently breaks the earlier one.
_SHAPES = {"_TG": "updates", "S": "sign", "_RM": "commands", "_CS": "hit", "_WF": "snaps", "_CB": "get", "_STATS": "get",
           "_html": "escape"}


def _clashes():
    bad = []
    for name, attr in _SHAPES.items():
        if name in globals() and not hasattr(globals()[name], attr):
            bad.append("%s is a %s now (expected something with .%s)" % (name, type(globals()[name]).__name__, attr))
    return bad


# keep the self-host link the same everywhere (part127/128 default to an older address)
try:
    if isinstance(globals().get("_FAIR"), dict):
        _FAIR["self_host"] = os.environ.get("GITHUB_URL", "https://github.com/TVibe-signal/signal-api")
except Exception:
    pass


def _dig(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return False
        d = d[k]
    return True


async def _asgi_get(path, params=None, timeout=45):
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal", timeout=timeout) as c:
        r = await c.get(path, params=params or {}, headers={"accept": "application/json"})
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, None


def _auth(key):
    need = os.environ.get("OPS_KEY", "")
    return not need or key == need


async def _redis_roundtrip():
    k = "tv:health:ping"
    t0 = time.time()
    try:
        rp = globals().get("_redis")
        if callable(rp):  # part105 helper raises when Redis rejects a command
            res = await rp([["SET", k, "1", "EX", 60], ["GET", k]])
        elif "redis_pipe" in globals():
            client = getattr(getattr(app, "state", None), "client", None)
            res = await redis_pipe(client, [["SET", k, "1", "EX", 60], ["GET", k]])
        else:
            return {"status": "not loaded"}
        ok = bool(res) and len(res) >= 2 and str(res[1]) == "1"
        return {"status": "ok" if ok else "FAILED", "ms": int((time.time() - t0) * 1000),
                "detail": None if ok else "wrote a key but could not read it back (quota or storage problem)"}
    except Exception as e:
        return {"status": "FAILED", "ms": int((time.time() - t0) * 1000), "detail": str(e)[:140]}


@app.get("/ops/health", include_in_schema=False)
async def ops_health(key: str = ""):
    if not _auth(key):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    issues, out = [], {"version": VERSION, "time": int(time.time())}

    # 1) Redis
    out["redis"] = rt = await _redis_roundtrip()
    if rt.get("status") == "FAILED":
        issues.append(("red", "Redis is not writable: %s" % (rt.get("detail") or "")))

    # 2) /stats
    st = {}
    try:
        code, st = await _asgi_get("/stats")
        st = st or {}
    except Exception as e:
        st = {}
        issues.append(("amber", "/stats could not be read: %s" % str(e)[:80]))
    perf = ((st.get("performance") or {}).get("all_tracked") or {})
    bv = st.get("by_verdict") or {}
    vsum = sum(int(((bv.get(k) or {}).get("full") or {}).get("n") or 0) for k in ("ok", "caution", "avoid"))
    judged = perf.get("judged")
    now = time.time()
    grew = None
    if judged is not None and _H_LAST["judged"] is not None and now - _H_LAST["ts"] > 600:
        grew = {"judged_added": judged - _H_LAST["judged"], "hours": round((now - _H_LAST["ts"]) / 3600.0, 1)}
    if judged is not None and now - _H_LAST["ts"] > 600:
        _H_LAST.update(ts=now, judged=judged)
    out["stats"] = {"judged": judged, "days_covered": perf.get("days_covered"), "resolved": st.get("resolved"),
                    "pending": st.get("pending"), "scoring": st.get("scoring"), "verdict_table_total": vsum,
                    "early_1h_n": ((st.get("early_horizons") or {}).get("1h") or {}).get("n"), "growth_since_last_check": grew}
    if st.get("resolved") == 0 and st.get("pending") == 0 and vsum == 0:
        issues.append(("amber", "the queue of verdicts waiting for their 24h result is unreadable (resolved=0, pending=0)"))
    if st.get("scoring") == "static":
        issues.append(("amber", "scoring is 'static': tuned risk weights are not loaded"))
    if grew and grew["hours"] >= 6 and grew["judged_added"] <= 0:
        issues.append(("amber", "no new judged outcomes in the last %s h" % grew["hours"]))

    # 3) signed verdicts
    if callable(globals().get("attest_status")):
        try:
            a = await attest_status()
            out["attest"] = {k: a.get(k) for k in ("enabled", "persistent", "chain_length", "anchored_days", "unsaved_records",
                                                     "last_saved_at", "last_error")}
            if a.get("last_error") and "anchor" not in str(a.get("last_error")):
                issues.append(("amber", "signed-verdict storage error: %s" % str(a["last_error"])[:80]))
            if (a.get("unsaved_records") or 0) > 20:
                issues.append(("amber", "%s signed verdicts are waiting to be saved" % a["unsaved_records"]))
        except Exception as e:
            out["attest"] = {"error": str(e)[:80]}
    else:
        out["attest"] = "not loaded"

    # 4) circuit, cache, Redis meter, Telegram, walk-forward
    if callable(globals().get("circuit_status")):
        try:
            c = circuit_status()
            out["circuit"] = {"state": c.get("state"), "reason": c.get("reason") or None}
            if c.get("state") != "closed":
                issues.append(("amber", "circuit is %s (upstream sources failing)" % c.get("state")))
        except Exception:
            out["circuit"] = "error"
    cs = globals().get("_CS")
    if cs is not None and hasattr(cs, "hit"):
        tot = cs.hit + cs.miss
        out["cache"] = {"hits": cs.hit, "misses": cs.miss, "hit_rate_pct": round(100.0 * cs.hit / tot, 1) if tot else None}
    rm = globals().get("_RM")
    if rm is not None and hasattr(rm, "commands"):
        up_h = max((now - rm.start) / 3600.0, 0.01)
        proj = int(rm.commands / up_h * 24 * 30)
        top = sorted(rm.by_caller.items(), key=lambda kv: -kv[1]["commands"])[:3]
        out["redis_meter"] = {"commands_since_restart": rm.commands, "projected_per_month": proj,
                              "top": [{"where": k, "share_pct": round(100.0 * v["commands"] / rm.commands, 1)} for k, v in top] if rm.commands else []}
        if proj > 500000:
            issues.append(("amber", "projected Redis use is %.1fM commands a month (free plan: 0.5M)" % (proj / 1e6)))
    tg = globals().get("_TG")
    if tg is not None and hasattr(tg, "updates"):
        out["telegram"] = {"ready": bool(globals().get("_TG_TOKEN") and globals().get("_TG_SECRET")), "updates": tg.updates,
                           "replies": tg.replies, "errors": tg.errors}
    wf = globals().get("_WF")
    if wf is not None and hasattr(wf, "snaps"):
        w = globals().get("_wf_compute")(7) if callable(globals().get("_wf_compute")) else {}
        out["walk_forward"] = {"snapshots": len(wf.snaps), "ready": w.get("ready"), "window_days": w.get("window_days"),
                               "persistent": wf.persistent}

    # 5) candidates (shadow rules)
    try:
        code, rc = await _asgi_get("/stats/rule-candidates")
        if isinstance(rc, dict) and "strong_candidates" in rc:
            out["rule_candidates"] = {"strong": rc.get("strong_candidates"), "promote_ready": rc.get("promote_ready"),
                                      "judged": rc.get("judged")}
    except Exception:
        pass

    # 6) what is loaded
    paths = {getattr(r, "path", None) for r in getattr(app, "routes", [])}
    out["routes_missing"] = [p for p in _EXPECTED_ROUTES if p not in paths]
    out["parts_loaded"] = {name: (g in globals()) for name, g in _PARTS.items()}

    out["namespace_clashes"] = _clashes()
    for m in out["namespace_clashes"]:
        issues.append(("red", "global name clash: " + m))

    level = "red" if any(l == "red" for l, _ in issues) else ("amber" if issues else "green")
    out["overall"] = level
    out["issues"] = [m for _, m in issues]
    return out


@app.get("/ops/contract-check", include_in_schema=False)
async def ops_contract_check(mint: str = "", key: str = ""):
    if not _auth(key):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    mint = mint or os.environ.get("CONTRACT_MINT") or "CbcyNo7m1amFWqEQm2m4PLv1UNvpcL3C1Ujm6AkzpKoU"
    res = {"version": VERSION, "schema_version": SCHEMA_VERSION, "mint": mint}
    for name, path, req in (("omni", "/omni", _REQ_OMNI), ("signal", "/signal", _REQ_SIGNAL)):
        try:
            code, d = await _asgi_get(path, {"mint": mint})
            if code != 200 or not isinstance(d, dict):
                res[name] = {"http": code, "ok": False, "missing": req}
                continue
            miss = [p for p in req if not _dig(d, p)]
            res[name] = {"http": code, "ok": not miss, "missing": miss, "schema_version": d.get("schema_version")}
        except Exception as e:
            res[name] = {"ok": False, "error": str(e)[:100]}
    res["note"] = "A missing field is a gap in the contract (it should be null or an unknown, never silently absent). attestation needs part105."
    return res


class _SchemaMW:
    """Adds schema_version to GET /omni and /signal JSON."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") not in ("/omni", "/signal") or scope.get("method") != "GET":
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
                hs = {k.lower(): v for k, v in start["headers"]}
                if start.get("status") == 200 and b"json" in hs.get(b"content-type", b"") and b"content-encoding" not in hs:
                    d = json.loads(body)
                    if isinstance(d, dict) and "schema_version" not in d:
                        d["schema_version"] = SCHEMA_VERSION
                        body = json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            except Exception as e:
                print("[part134] schema mw:", str(e)[:100])
            hdrs = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"] + [(b"content-length", str(len(body)).encode())]
            await send({**start, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, cap)


try:
    app.add_middleware(_SchemaMW)
except Exception as _e:
    print("[part134] could not add middleware:", str(_e)[:100])

print("[part134] v%s GET /ops/health, /ops/contract-check; schema_version=%s on /omni and /signal" % (VERSION, SCHEMA_VERSION))

# --- part135 ---
# part135.py — brand cleanup: TVibex402 → TVibe-signal (web HTML only)
# Does not touch Telegram bot state, verdicts, or live rules.
# Loader (after part133, before part7):  ("part135.py", 0, "SKIP"),

import os

VERSION = "3.0.6"
app.version = VERSION
app.openapi_schema = None

_BRAND_NEW_GH = os.environ.get(
    "GITHUB_URL", "https://github.com/TVibe-signal/signal-api"
).rstrip("/")
_BRAND_OLD_GH = "https://github.com/TVibex402/signal-api"
_BRAND_OLD_HOST = "github.com/TVibex402/signal-api"
_BRAND_NEW_HOST = _BRAND_NEW_GH.replace("https://", "").replace("http://", "")
_BRAND_OLD_ORG = "TVibex402"
_BRAND_NEW_ORG = "TVibe-signal"


def _brand_patch_html(text: str) -> str:
    if not text or _BRAND_OLD_ORG not in text and _BRAND_OLD_HOST not in text:
        return text
    text = text.replace(_BRAND_OLD_GH, _BRAND_NEW_GH)
    text = text.replace(_BRAND_OLD_HOST, _BRAND_NEW_HOST)
    # Visible org mentions in prose (avoid changing unrelated long hashes)
    text = text.replace(_BRAND_OLD_ORG + "/signal-api", _BRAND_NEW_ORG + "/signal-api")
    text = text.replace(_BRAND_OLD_ORG, _BRAND_NEW_ORG)
    return text


_home = globals().get("HOME_HTML")
if isinstance(_home, str) and _BRAND_OLD_ORG in _home:
    HOME_HTML = _brand_patch_html(_home)
    globals()["HOME_HTML"] = HOME_HTML


class _BrandCleanupMW:
    """Patch remaining TVibex402 on HTML responses (/, /agents, /pricing, /docs, …)."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "GET":
            return await self.app(scope, receive, send)
        path = scope.get("path") or ""
        # Skip API JSON paths
        if path.startswith(("/omni", "/signal", "/stats", "/mcp", "/health", "/ping", "/api")):
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
                hs = {k.lower(): v for k, v in (start.get("headers") or [])}
                ctype = hs.get(b"content-type", b"")
                if (
                    start.get("status") == 200
                    and b"text/html" in ctype
                    and b"content-encoding" not in hs
                ):
                    text = body.decode("utf-8", "ignore")
                    patched = _brand_patch_html(text)
                    if patched != text:
                        body = patched.encode("utf-8")
            except Exception:
                pass
            hdrs = [
                (k, v) for k, v in start["headers"] if k.lower() != b"content-length"
            ] + [(b"content-length", str(len(body)).encode())]
            await send({**start, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, cap)


try:
    app.add_middleware(_BrandCleanupMW)
except Exception as e:
    print("[part135] mw:", str(e)[:100])

print(
    "[part135] v%s brand cleanup %s → %s"
    % (VERSION, _BRAND_OLD_ORG, _BRAND_NEW_ORG)
)

# --- part136 ---
# part136.py - Feature lift tracker (v2.99.6): which measurable ideas actually predict a bad outcome?
# Turns several "concepts" into measurable buckets, each recorded when the verdict is made and scored when the outcome is judged:
#   age (Lindy: older pairs live longer?), liquidity depth, liquidity/market-cap, top-10 concentration,
#   hour of day UTC (circadian), 24h price change (reflexivity), buy/sell balance, community unanimity (groupthink).
# For every bucket it shows n, bad rate, a shrunk estimate (Bayesian, pulled toward the average), a 99% interval and the lift.
#   GET /stats/feature-lift?min_n=30
# Research only: nothing here changes a verdict. Cost: 1 Redis write per new token per day + about 19 commands per judged outcome.
# Names start with _fl_ / _FL so they cannot clash with other parts (all parts share one namespace).
# Loader line (after part134, before part7):  ("part135.py", 0, "SKIP"),
import inspect
import json
import math
import re
import time
import types

VERSION = "2.99.6"
app.version = VERSION
app.openapi_schema = None

_FL_KEY = "si:featlift"
_FL_PEND = "si:featlift:p:{}"
_FL_PEND_TTL = 10 * 86400
_FL_TTL = 120 * 86400
_FL_PRIOR = 20      # strength of the pull toward the average for small buckets
_FL_Z99 = 2.576
_FL = types.SimpleNamespace(seen={}, cache_ts=0.0, cache=None, recorded=0, scored=0)

_FL_LABELS = {
    "age": ["<1h", "1-6h", "6-24h", "1-3d", "3-7d", "7-30d", ">30d"],
    "liq": ["<5k", "5-20k", "20-100k", "100-500k", ">500k"],
    "liq_mcap": ["<2%", "2-5%", "5-15%", ">15%"],
    "top10": ["<15%", "15-30%", "30-50%", ">50%"],
    "hour_utc": ["00-04", "04-08", "08-12", "12-16", "16-20", "20-24"],
    "pc24": ["<-30%", "-30..-5%", "-5..+5%", "+5..+30%", ">+30%"],
    "buys": ["few trades", "<30% buys", "30-70% buys", ">70% buys"],
    "community": ["none", "n<10", "mixed", "unanimous"],
}
_FL_NOTES = {
    "age": "Lindy idea: does a longer-lived pair keep living?", "liq": "market depth", "liq_mcap": "depth relative to market cap",
    "top10": "concentration of the top 10 holders", "hour_utc": "time of day (circadian) when the verdict was made",
    "pc24": "price already moved (reflexivity)", "buys": "buy/sell balance over the last 5 minutes",
    "community": "groupthink: does an unanimous small community predict anything?"}


def _fl_pick(x, edges, labels):
    for e, lab in zip(edges, labels):
        if x < e:
            return lab
    return labels[-1]


def _fl_num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _fl_features(body: dict) -> dict:
    fv = {}
    age = _fl_num(body.get("pair_age_minutes"))
    if age is not None:
        fv["age"] = _fl_pick(age, (60, 360, 1440, 4320, 10080, 43200), _FL_LABELS["age"])
    liq, mc = _fl_num(body.get("liquidity_usd")), _fl_num(body.get("market_cap_usd"))
    if liq is not None:
        fv["liq"] = _fl_pick(liq, (5e3, 2e4, 1e5, 5e5), _FL_LABELS["liq"])
        if mc and mc > 0:
            fv["liq_mcap"] = _fl_pick(liq / mc, (0.02, 0.05, 0.15), _FL_LABELS["liq_mcap"])
    sec = body.get("security") if isinstance(body.get("security"), dict) else {}
    t10 = _fl_num(sec.get("top10_holders_pct"))
    if t10 is not None:
        fv["top10"] = _fl_pick(t10, (15, 30, 50), _FL_LABELS["top10"])
    fv["hour_utc"] = _FL_LABELS["hour_utc"][time.gmtime().tm_hour // 4]
    pc = body.get("price_change_pct")
    pc24 = _fl_num(pc.get("24h")) if isinstance(pc, dict) else None
    if pc24 is not None:
        fv["pc24"] = _fl_pick(pc24, (-30, -5, 5, 30), _FL_LABELS["pc24"])
    b, s = _fl_num(body.get("buys_5m")), _fl_num(body.get("sells_5m"))
    if b is not None and s is not None:
        fv["buys"] = "few trades" if b + s < 5 else _fl_pick(b / (b + s), (0.3, 0.7), _FL_LABELS["buys"][1:])
    com = body.get("community") if isinstance(body.get("community"), dict) else {}
    conv = com.get("conviction") if isinstance(com.get("conviction"), dict) else {}
    n = _fl_num(conv.get("n"))
    if n is None:
        fv["community"] = "none"
    elif n < 10:
        fv["community"] = "n<10"
    else:
        m = re.search(r"(\d+(?:\.\d+)?)%", str(com.get("summary") or ""))
        fv["community"] = "unanimous" if (m and float(m.group(1)) >= 95) else "mixed"
    return fv


async def _fl_remember(client, mint: str, body: dict) -> None:
    if not globals().get("PRED_ENABLED") or not client or "redis_pipe" not in globals():
        return
    if body.get("asset_class") == "major" or (body.get("decision") or {}).get("asset_class") == "major":
        return
    now = time.time()
    if now - _FL.seen.get(mint, 0) < 86400:
        return
    fv = _fl_features(body)
    if not fv:
        return
    if len(_FL.seen) > 5000:
        _FL.seen.clear()
    _FL.seen[mint] = now
    await redis_pipe(client, [["SET", _FL_PEND.format(mint), json.dumps(fv, separators=(",", ":")), "NX", "EX", _FL_PEND_TTL]])
    _FL.recorded += 1


async def _fl_score(client, mint: str, bad: bool) -> None:
    key = _FL_PEND.format(mint)
    raw = await redis_pipe(client, [["GET", key]])
    v = (raw or [None])[0]
    if not v:
        return
    fv = json.loads(v)
    cmds = [["HINCRBY", _FL_KEY, "__all__|n", 1]]
    if bad:
        cmds.append(["HINCRBY", _FL_KEY, "__all__|bad", 1])
    for f, b in fv.items():
        cmds.append(["HINCRBY", _FL_KEY, "%s|%s|n" % (f, b), 1])
        if bad:
            cmds.append(["HINCRBY", _FL_KEY, "%s|%s|bad" % (f, b), 1])
    cmds += [["DEL", key], ["EXPIRE", _FL_KEY, _FL_TTL]]
    await redis_pipe(client, cmds)
    _FL.scored += 1


def _fl_wilson(k: int, n: int, z: float):
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def _fl_compute(h: dict, min_n: int) -> dict:
    h = {str(k): int(float(v or 0)) for k, v in (h or {}).items()}
    base_n, base_bad = h.get("__all__|n", 0), h.get("__all__|bad", 0)
    if base_n < max(min_n, 30):
        return {"ready": False, "reason": "needs at least %d judged tokens with recorded features" % max(min_n, 30), "judged": base_n}
    base = 100.0 * base_bad / base_n
    feats, findings = {}, []
    for f, labels in _FL_LABELS.items():
        rows = []
        for b in labels:
            n, bad = h.get("%s|%s|n" % (f, b), 0), h.get("%s|%s|bad" % (f, b), 0)
            if n < min_n:
                if n:
                    rows.append({"bucket": b, "n": n, "note": "too few"})
                continue
            rate = 100.0 * bad / n
            shrunk = 100.0 * (bad + _FL_PRIOR * base / 100.0) / (n + _FL_PRIOR)
            ci = _fl_wilson(bad, n, _FL_Z99)
            if ci[0] > base + 5:
                reading = "clearly riskier than average"
            elif ci[1] < base - 5:
                reading = "clearly safer than average"
            else:
                reading = "no clear difference"
            row = {"bucket": b, "n": n, "bad_rate_pct": round(rate, 1), "shrunk_pct": round(shrunk, 1), "ci99_pct": ci,
                   "lift": round(rate / base, 2) if base else None, "reading": reading}
            rows.append(row)
            if reading != "no clear difference":
                findings.append({"feature": f, **row, "_s": abs(rate - base) * math.sqrt(n)})
        feats[f] = {"about": _FL_NOTES[f], "buckets": rows}
    findings.sort(key=lambda x: -x["_s"])
    for x in findings:
        x.pop("_s", None)
    return {"ready": True, "judged": base_n, "base_rate_pct": round(base, 1), "features": feats, "findings": findings[:12],
            "note": ("Association measured on tokens people queried, not cause. About 35 buckets are compared at a 99% interval, "
                     "so treat one lone finding with care; a real effect shows up again on newer data (see /stats/walk-forward). "
                     "shrunk_pct pulls small buckets toward the average. Research only: no verdict uses this."),
            "live_verdict_unchanged": True}


@app.get("/stats/feature-lift", tags=["accuracy"])
async def stats_feature_lift(min_n: int = 30):
    min_n = max(10, min(int(min_n), 500))
    now = time.time()
    if _FL.cache is not None and now - _FL.cache_ts < 600 and _FL.cache[0] == min_n:
        return _FL.cache[1]
    h = {}
    try:
        client = getattr(getattr(app, "state", None), "client", None)
        if globals().get("PRED_ENABLED") and client and "redis_pipe" in globals():
            raw = await redis_pipe(client, [["HGETALL", _FL_KEY]])
            h = to_dict((raw or [{}])[0] or {}) if "to_dict" in globals() else {}
    except Exception as e:
        return {"version": VERSION, "ready": False, "error": str(e)[:100]}
    out = {"version": VERSION, **_fl_compute(h, min_n), "recorded_since_restart": _FL.recorded, "scored_since_restart": _FL.scored}
    _FL.cache, _FL.cache_ts = (min_n, out), now
    return out


_fl_build_prev = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _fl_build_prev(client, mint, security, *args, **kwargs)
    try:
        body = res[0] if isinstance(res, tuple) else res
        if isinstance(body, dict):
            await _fl_remember(client, str(mint), body)
    except Exception as e:
        print("[part135] record:", str(e)[:100])
    return res


_fl_out_prev = globals().get("on_outcome_for_si")


async def on_outcome_for_si(client, mint: str, bad: bool, meta=None, **kwargs):
    if callable(_fl_out_prev):
        try:
            plist = list(inspect.signature(_fl_out_prev).parameters.values())
        except (TypeError, ValueError):
            plist = []
        takes_meta = len(plist) >= 4 or any(p.kind == p.VAR_POSITIONAL for p in plist)
        try:
            await (_fl_out_prev(client, mint, bad, meta, **kwargs) if takes_meta else _fl_out_prev(client, mint, bad))
        except Exception as e:
            print("[part135] previous outcome hook:", str(e)[:100])
    try:
        if globals().get("PRED_ENABLED") and client and "redis_pipe" in globals():
            await _fl_score(client, mint, bad)
    except Exception as e:
        print("[part135] score:", str(e)[:100])


print("[part135] v%s feature lift tracker -> GET /stats/feature-lift (research only)" % VERSION)

# --- part136: wallet intel (deployer reputation + bundle/fresh-wallet) — research shadow ---
# A) Deployer: pump.fun history + Redis hg:dep outcomes (if present)
# B) Bundle/fresh: top holders with near-zero SOL + high token share
# Never upgrades verdict. May add cautions / research flags only.
# Place BEFORE MCP (part7). Env: WI_ENABLED=1 (default), WI_ESCALATE=0

VERSION = "3.0.7"
try:
    app.version = VERSION
    app.openapi_schema = None
except Exception:
    pass

import asyncio
import json
import os
import time

_WI_ON = os.getenv("WI_ENABLED", "1").lower() in ("1", "true", "yes")
_WI_ESCALATE = os.getenv("WI_ESCALATE", "0").lower() in ("1", "true", "yes")
_WI_CACHE: dict = {}
_WI_STATS = {"runs": 0, "serial": 0, "bundle": 0, "errors": 0}


def _wi_num(x):
    try:
        v = float(x)
        return v if v == v else None
    except Exception:
        return None


async def _wi_rpc(client, method, params):
    fn = globals().get("rpc")
    if not callable(fn):
        return None
    try:
        return await asyncio.wait_for(fn(client, method, params), 2.5)
    except Exception:
        return None


async def _wi_deployer(client, mint, result):
    """Best-effort deployer reputation (pump tokens + optional Redis dep set)."""
    out = {
        "source": None,
        "creator": None,
        "prev_tokens": None,
        "migrated": None,
        "flags": [],
        "notes": [],
    }
    sh = result.get("_shadow") or result.get("shadow") or {}
    pump = sh.get("pump") if isinstance(sh, dict) else None
    if not isinstance(pump, dict) and str(mint).endswith("pump"):
        http = globals().get("_sh_http")
        base = globals().get("_PUMP_API") or "https://frontend-api-v3.pump.fun"
        coin = None
        try:
            if callable(http):
                coin = await asyncio.wait_for(http(client, "pump", f"{base}/coins/{mint}"), 2.5)
            else:
                r = await asyncio.wait_for(client.get(f"{base}/coins/{mint}", timeout=2.5), 3.0)
                coin = r.json() if getattr(r, "status_code", 0) == 200 else None
        except Exception:
            coin = None
        if isinstance(coin, dict):
            pump = {
                "creator": coin.get("creator"),
                "migrated": bool(coin.get("complete")),
                "deployer_prev": None,
                "deployer_migrated": None,
                "flags": [],
            }
            creator = coin.get("creator")
            if creator:
                try:
                    if callable(http):
                        j = await asyncio.wait_for(
                            http(
                                client,
                                "pump",
                                f"{base}/coins/user-created-coins/{creator}",
                                {"offset": 0, "limit": 50, "includeNsfw": "true"},
                            ),
                            2.5,
                        )
                    else:
                        r = await client.get(
                            f"{base}/coins/user-created-coins/{creator}",
                            params={"offset": 0, "limit": 50, "includeNsfw": "true"},
                            timeout=2.5,
                        )
                        j = r.json() if getattr(r, "status_code", 0) == 200 else None
                    coins = j.get("coins") if isinstance(j, dict) else j
                    if isinstance(coins, list):
                        others = [c for c in coins if isinstance(c, dict) and c.get("mint") != mint]
                        n = len(others)
                        mig = sum(1 for c in others if c.get("complete"))
                        pump["deployer_prev"] = n
                        pump["deployer_migrated"] = mig
                        if n >= 8 and (mig / n) < 0.1:
                            pump["flags"].append("serial_deployer")
                except Exception:
                    pass
    if isinstance(pump, dict):
        out["source"] = "pump.fun"
        out["creator"] = pump.get("creator")
        out["prev_tokens"] = pump.get("deployer_prev")
        out["migrated"] = pump.get("deployer_migrated")
        for f in pump.get("flags") or []:
            if f not in out["flags"]:
                out["flags"].append(f)
        n, m = out["prev_tokens"], out["migrated"]
        if isinstance(n, int) and n >= 5 and isinstance(m, int) and n and (m / n) < 0.15:
            if "serial_deployer" not in out["flags"]:
                out["flags"].append("serial_deployer")
            out["notes"].append(
                f"Deployer created ~{n} prior tokens; migrated {m} ({m / n:.0%})"
            )
        creator = out.get("creator")
        pipe = globals().get("redis_pipe")
        if creator and callable(pipe) and globals().get("PRED_ENABLED"):
            try:
                res = await pipe(client, [["SCARD", f"hg:dep:{creator}"]])
                sc = int((res or [0])[0] or 0)
                if sc:
                    out["tracked_mints"] = sc
                    out["notes"].append(f"Seen on {sc} mints in our dep index")
            except Exception:
                pass
    return out


async def _wi_bundle(client, mint, result):
    """Flag bundle-ish top holders: high token % + near-empty SOL."""
    out = {
        "n_checked": 0,
        "near_empty_sol": 0,
        "flags": [],
        "notes": [],
        "samples": [],
    }
    sec = result.get("security") if isinstance(result.get("security"), dict) else {}
    hq = result.get("holder_quality") if isinstance(result.get("holder_quality"), dict) else {}
    tops = sec.get("top_holders") or hq.get("top_owners") or []
    owners = []
    for h in tops[:8]:
        if isinstance(h, dict):
            o = h.get("owner") or h.get("address") or h.get("w")
            pct = _wi_num(h.get("pct") or h.get("percent") or h.get("share"))
        elif isinstance(h, (list, tuple)) and len(h) >= 1:
            o = h[0]
            pct = _wi_num(h[1] if len(h) > 1 else None)
        else:
            continue
        if o and isinstance(o, str) and len(o) >= 32:
            owners.append((o, pct))
    if not owners:
        return out
    addrs = [o for o, _ in owners]
    res = await _wi_rpc(
        client,
        "getMultipleAccounts",
        [addrs, {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}],
    )
    values = ((res or {}).get("result") or {}).get("value") if isinstance(res, dict) else None
    if not isinstance(values, list):
        out["notes"].append("RPC holder balances unavailable")
        return out
    near = 0
    checked = 0
    for i, v in enumerate(values):
        if not isinstance(v, dict):
            continue
        checked += 1
        lamports = int(v.get("lamports") or 0)
        sol = lamports / 1e9
        pct = owners[i][1] if i < len(owners) else None
        if sol < 0.05 and (pct is None or pct >= 1.0):
            near += 1
            if len(out["samples"]) < 3:
                out["samples"].append(
                    {
                        "owner": addrs[i][:6] + "…" + addrs[i][-4:],
                        "sol": round(sol, 4),
                        "pct": pct,
                    }
                )
    out["n_checked"] = checked
    out["near_empty_sol"] = near
    if checked >= 4 and near >= 3:
        out["flags"].append("bundle_like_holders")
        out["notes"].append(
            f"{near}/{checked} top holders have <0.05 SOL (possible bundle/sniper bags)"
        )
    elif checked >= 3 and near >= 2:
        out["flags"].append("fresh_or_thin_wallets")
        out["notes"].append(f"{near}/{checked} top holders look fee-thin")
    return out


async def _wi_run(client, mint, result):
    if not _WI_ON or not isinstance(result, dict):
        return
    now = time.time()
    hit = _WI_CACHE.get(mint)
    if hit and now - hit[0] < 45:
        intel = hit[1]
    else:
        try:
            dep, bun = await asyncio.wait_for(
                asyncio.gather(
                    _wi_deployer(client, mint, result),
                    _wi_bundle(client, mint, result),
                    return_exceptions=True,
                ),
                5.0,
            )
            if isinstance(dep, Exception):
                dep = {"flags": [], "notes": [str(dep)[:80]]}
            if isinstance(bun, Exception):
                bun = {"flags": [], "notes": [str(bun)[:80]]}
            flags = list(dict.fromkeys((dep.get("flags") or []) + (bun.get("flags") or [])))
            intel = {
                "v": 1,
                "shadow": True,
                "deployer": dep,
                "holders": bun,
                "flags": flags,
            }
            _WI_CACHE[mint] = (now, intel)
            if len(_WI_CACHE) > 2000:
                _WI_CACHE.clear()
            _WI_STATS["runs"] += 1
            if "serial_deployer" in flags:
                _WI_STATS["serial"] += 1
            if "bundle_like_holders" in flags or "fresh_or_thin_wallets" in flags:
                _WI_STATS["bundle"] += 1
        except Exception as e:
            _WI_STATS["errors"] += 1
            intel = {"v": 1, "shadow": True, "error": str(e)[:120]}
    result["wallet_intel"] = intel
    if _WI_ESCALATE and isinstance(intel, dict):
        dec = result.get("decision")
        if isinstance(dec, dict):
            cautions = list(dec.get("cautions") or [])
            msg_map = {
                "serial_deployer": "Deployer has many prior tokens with low migrate rate (shadow)",
                "bundle_like_holders": "Several top holders look bundle/sniper-like (thin SOL)",
                "fresh_or_thin_wallets": "Multiple top holders are fee-thin wallets (shadow)",
            }
            for f in intel.get("flags") or []:
                msg = msg_map.get(f, f)
                if msg not in cautions:
                    cautions.append(msg)
            dec["cautions"] = cautions
            result["decision"] = dec
    if intel.get("flags"):
        rf = list(result.get("research_flags") or [])
        for f in intel["flags"]:
            if f not in rf:
                rf.append(f)
        result["research_flags"] = rf


_build_prev_wi = build_signal


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_wi(client, mint, security, *args, **kwargs)
    try:
        if isinstance(res, tuple) and len(res) >= 1 and isinstance(res[0], dict):
            await _wi_run(client, mint, res[0])
            return res
        if isinstance(res, dict):
            await _wi_run(client, mint, res)
            return res
    except Exception as e:
        _WI_STATS["errors"] += 1
        print("[part136] wi:", str(e)[:100])
    return res


try:
    @app.get("/stats/wallet-intel", tags=["stats"], include_in_schema=False)
    async def stats_wallet_intel():
        return {
            "enabled": _WI_ON,
            "escalate": _WI_ESCALATE,
            "stats": dict(_WI_STATS),
            "cache": len(_WI_CACHE),
        }
except Exception as e:
    print("[part136] route skip:", str(e)[:80])

print("[part136] wallet_intel deployer+bundle shadow -> result.wallet_intel /stats/wallet-intel")



# --- part138: agent-first surface (view=agent + agent-card + llms hint) ---
# Clean action contract for agents without SI noise. Free forever spirit.
# GET /omni?mint=...&view=agent
# GET /.well-known/agent-card.json
VERSION = "3.0.8"
try:
    app.version = VERSION
    app.openapi_schema = None
except Exception:
    pass

from fastapi import Query
from fastapi.responses import JSONResponse, PlainTextResponse


def _tvibe_agent_view(pkt: dict) -> dict:
    """Stable, minimal contract for AI agents. Heuristic, not advice."""
    if not isinstance(pkt, dict):
        return {"error": "bad_packet", "nfa": True}
    if pkt.get("error"):
        return {
            "mint": pkt.get("mint"),
            "action": "skip",
            "verdict": "avoid",
            "filter": {"pass": False},
            "confidence": "low",
            "blockers": [str(pkt.get("error"))],
            "cautions": [],
            "unknowns": ["signal_failed"],
            "wallet_intel": {"shadow": True, "flags": []},
            "risk_score": None,
            "valid_for_s": 0,
            "nfa": True,
        }
    dec = pkt.get("decision") if isinstance(pkt.get("decision"), dict) else {}
    f = pkt.get("filter") if isinstance(pkt.get("filter"), dict) else {}
    wi = pkt.get("wallet_intel") if isinstance(pkt.get("wallet_intel"), dict) else {}
    blockers = list(dec.get("blockers") or [])
    cautions = list(dec.get("cautions") or [])[:6]
    unknowns = list(dec.get("unknowns") or [])[:6]
    verdict = (dec.get("verdict") or pkt.get("verdict") or "caution")
    if isinstance(verdict, str):
        verdict = verdict.lower()
    else:
        verdict = "caution"
    pass_ = f.get("pass")
    flags = list(wi.get("flags") or [])
    if pass_ is True and not blockers and verdict != "avoid":
        action = "pass"
    elif verdict == "avoid" or blockers or pass_ is False:
        action = "skip" if (verdict == "avoid" or blockers) else "review"
    else:
        action = "review"
    # confidence: never "high" without clear data; unknowns force low
    if unknowns:
        confidence = "low"
    elif action == "pass" and not flags:
        confidence = "medium"
    else:
        confidence = "medium" if action == "review" else "low"
    return {
        "mint": pkt.get("mint"),
        "action": action,  # pass | review | skip
        "verdict": verdict,
        "filter": {"pass": bool(pass_) if pass_ is not None else False},
        "confidence": confidence,
        "blockers": blockers,
        "cautions": cautions,
        "unknowns": unknowns,
        "wallet_intel": {"shadow": True, "flags": flags},
        "risk_score": dec.get("risk_score") if dec.get("risk_score") is not None else pkt.get("risk_score"),
        "liquidity_usd": pkt.get("liquidity_usd"),
        "valid_for_s": 30,
        "nfa": True,
        "docs": "/llms.txt",
        "full_omni": True,  # omit view=agent for full packet
    }


_AGENT_CARD = {
    "name": "TVibe Signal",
    "description": (
        "Free Solana token risk filter for AI agents. One call: decision + filter.pass + "
        "optional wallet_intel (shadow). Measured track record on /stats. Not financial advice."
    ),
    "url": "https://signal-api-24q4.onrender.com",
    "provider": {"organization": "TVibe Signal", "url": "https://x.com/realTVibe"},
    "version": VERSION,
    "documentationUrl": "https://signal-api-24q4.onrender.com/llms.txt",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    },
    "defaultInputModes": ["text"],
    "defaultOutputModes": ["application/json"],
    "skills": [
        {
            "id": "omni-token-risk",
            "name": "Token risk (omni)",
            "description": "GET /omni?mint=<MINT>&view=agent — action pass|review|skip, filter.pass, blockers, unknowns.",
            "tags": ["solana", "risk", "memecoin", "rug", "agent"],
            "examples": [
                "Check mint CA8q2mkYWZnUNqYmf6pxyxAPZsmSe2EG9P7hHMW5pump",
                "Should an agent size this token? Use view=agent",
            ],
        },
        {
            "id": "track-record",
            "name": "Measured outcomes",
            "description": "GET /stats — how past verdicts performed after horizons.",
            "tags": ["stats", "calibration"],
            "examples": ["Show avoid precision vs baseline"],
        },
        {
            "id": "mcp",
            "name": "MCP tools",
            "description": "Streamable HTTP MCP at /mcp — check_token_risk, check_tokens_batch, check_exit, get_track_record.",
            "tags": ["mcp"],
            "examples": ["Connect MCP client to https://signal-api-24q4.onrender.com/mcp"],
        },
    ],
    "mcp": {"url": "https://signal-api-24q4.onrender.com/mcp", "transport": "streamable-http"},
    "endpoints": {
        "omni": "GET /omni?mint=<MINT>",
        "omni_agent": "GET /omni?mint=<MINT>&view=agent",
        "stats": "GET /stats",
        "health": "GET /health",
        "llms": "GET /llms.txt",
    },
    "pricing": "free",
    "nfa": True,
}


@app.get("/.well-known/agent-card.json", include_in_schema=False)
@app.get("/agent-card.json", include_in_schema=False)
async def agent_card_json():
    return JSONResponse(_AGENT_CARD)


# Rebind /omni with view= query (drop older GET /omni routes that only take mint)
try:
    app.router.routes[:] = [
        r for r in app.router.routes
        if not (
            getattr(r, "path", None) == "/omni"
            and getattr(r, "methods", None)
            and "GET" in (r.methods or set())
        )
    ]
except Exception as _e:
    print("[part138] could not drop old /omni:", str(_e)[:100])


@app.get("/omni", tags=["product"])
async def omni_agent_endpoint(
    request: Request,
    mint: str = Query(..., min_length=32, max_length=64),
    view: str = Query("full", description="full | agent (minimal action contract)"),
):
    wait = rate_limited(client_ip(request), cost=4)
    if wait:
        raise too_many(wait)
    mint = (mint or "").strip()
    if not MINT_RE.match(mint):
        raise HTTPException(status_code=400, detail="Invalid Solana token mint address")
    client = request.app.state.client
    pkt = await build_omni(client, mint)
    if (view or "").strip().lower() in ("agent", "compact", "action"):
        return _tvibe_agent_view(pkt if isinstance(pkt, dict) else {})
    return pkt


_LLMS_AGENT_TAIL = """

## Agent-first (clean input)
- Preferred: GET /omni?mint=<MINT>&view=agent
- Returns only: action (pass|review|skip), verdict, filter.pass, confidence, blockers, cautions, unknowns, wallet_intel.flags, risk_score, valid_for_s, nfa
- Full packet: omit view=agent
- Discovery: GET /.well-known/agent-card.json
- MCP: https://signal-api-24q4.onrender.com/mcp
- Always honor unknowns non-empty → lower confidence; never treat verdict as guarantee
- Not financial advice
"""

try:
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/llms.txt"]
except Exception as _e:
    print("[part138] llms route drop:", str(_e)[:80])

_prev_llms = globals().get("llms_txt_free_core") or globals().get("llms_txt_v291")


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt_agent_first():
    body = ""
    if callable(_prev_llms):
        try:
            prev = await _prev_llms()
            body = prev.body.decode() if hasattr(prev, "body") else (prev if isinstance(prev, str) else str(prev))
        except Exception:
            body = ""
    if not body:
        body = (
            "TVibe Signal — free Solana token risk for agents\n"
            "Primary: GET /omni?mint=<MINT>&view=agent\n"
            "MCP: https://signal-api-24q4.onrender.com/mcp\n"
            "Stats: GET /stats\n"
        )
    if "view=agent" not in body:
        body = body.rstrip() + "\n" + _LLMS_AGENT_TAIL
    return PlainTextResponse(body)


print("[part138] v%s agent-first: /omni?view=agent + /.well-known/agent-card.json + llms" % VERSION)



# --- part139: agent playbook (fixed workflow, no code mutation) ---
# Agents read this and follow steps. Humans gate any code change.
VERSION = "3.0.9"
try:
    app.version = VERSION
    app.openapi_schema = None
except Exception:
    pass

from fastapi.responses import JSONResponse, PlainTextResponse

_BASE = (os.environ.get("PUBLIC_BASE_URL") or "https://signal-api-24q4.onrender.com").rstrip("/")

_PLAYBOOK = {
    "name": "TVibe Signal — Agent Playbook",
    "version": VERSION,
    "nfa": True,
    "principle": "Measure outcomes. Never treat a verdict as a guarantee. Never auto-edit risk rules.",
    "base": _BASE,
    "steps": [
        {
            "id": 1,
            "name": "discover",
            "do": "GET /.well-known/agent-card.json and GET /llms.txt once per session",
            "urls": [f"{_BASE}/.well-known/agent-card.json", f"{_BASE}/llms.txt"],
        },
        {
            "id": 2,
            "name": "screen",
            "do": "GET /omni?mint=<MINT>&view=agent",
            "url_template": f"{_BASE}/omni?mint={{mint}}&view=agent",
            "read": ["action", "filter.pass", "blockers", "unknowns", "confidence", "wallet_intel.flags"],
        },
        {
            "id": 3,
            "name": "branch",
            "rules": [
                {"if": "action == skip OR filter.pass == false OR blockers non-empty", "then": "Do not size a buy. Report blockers."},
                {"if": "unknowns non-empty", "then": "Call check_exit (MCP) or GET /exit?mint= before any size; lower confidence."},
                {"if": "wallet_intel.flags non-empty", "then": "Treat as research shadow only; prefer review, not pass."},
                {"if": "action == pass AND unknowns empty", "then": "Still not advice — optional light size only under user policy."},
            ],
        },
        {
            "id": 4,
            "name": "exit_cost",
            "do": "If considering a position: MCP check_exit or GET /exit?mint=",
            "url_template": f"{_BASE}/exit?mint={{mint}}",
        },
        {
            "id": 5,
            "name": "calibrate",
            "do": "GET /stats periodically (not every mint) to see measured avoid/ok outcomes",
            "url": f"{_BASE}/stats",
        },
        {
            "id": 6,
            "name": "rate_limits",
            "do": "On HTTP 429/503 honor Retry-After. Prefer one /omni over many tiny calls. Batch <= 10.",
        },
        {
            "id": 7,
            "name": "forbidden",
            "do": [
                "Do not invent filter.pass or clear unknowns",
                "Do not claim financial advice",
                "Do not modify TVibe heuristics, thresholds, or deploy code",
                "Do not ignore shadow flags as proven rugs without /stats support",
            ],
        },
    ],
    "mcp": {
        "url": f"{_BASE}/mcp",
        "tools_preferred": [
            "check_token_risk",
            "check_tokens_batch",
            "check_exit",
            "get_track_record",
        ],
    },
    "prompt_stub": (
        "You are a risk gate, not a tipster. For each Solana mint: "
        "1) GET /omni?mint=...&view=agent. "
        "2) If action is skip or filter.pass is false, stop. "
        "3) If unknowns is non-empty, run check_exit before any size. "
        "4) Report action, blockers, unknowns, confidence. "
        "5) Never present verdicts as guarantees. Not financial advice."
    ),
}


@app.get("/agent/playbook", tags=["product"], summary="Fixed workflow for AI agents (no code mutation)")
@app.get("/playbook", include_in_schema=False)
async def agent_playbook_json():
    return JSONResponse(_PLAYBOOK)


@app.get("/agent/playbook.txt", include_in_schema=False)
async def agent_playbook_txt():
    lines = [
        f"# {_PLAYBOOK['name']} v{_PLAYBOOK['version']}",
        f"# NFA={_PLAYBOOK['nfa']}",
        f"# {_PLAYBOOK['principle']}",
        f"BASE={_BASE}",
        "",
        "PROMPT_STUB:",
        _PLAYBOOK["prompt_stub"],
        "",
        "STEPS:",
    ]
    for s in _PLAYBOOK["steps"]:
        lines.append(f"{s['id']}. {s['name']}: {s.get('do') or s.get('rules') or ''}")
    lines += ["", f"MCP={_PLAYBOOK['mcp']['url']}", f"CARD={_BASE}/.well-known/agent-card.json"]
    return PlainTextResponse("\n".join(lines) + "\n")


# Point agent-card skill at playbook if card dict exists
try:
    card = globals().get("_AGENT_CARD")
    if isinstance(card, dict):
        card["version"] = VERSION
        skills = card.setdefault("skills", [])
        if not any(s.get("id") == "playbook" for s in skills if isinstance(s, dict)):
            skills.append({
                "id": "playbook",
                "name": "Agent playbook",
                "description": "GET /agent/playbook — fixed steps: view=agent → exit if unknowns → /stats. No code edits.",
                "tags": ["agent", "workflow"],
                "examples": ["Load playbook once, then screen mints"],
            })
        eps = card.setdefault("endpoints", {})
        eps["playbook"] = "GET /agent/playbook"
except Exception as _e:
    print("[part139] card patch:", str(_e)[:80])

print("[part139] v%s /agent/playbook (+ .txt) fixed agent workflow" % VERSION)


# --- part7 ---
# ---------- MCP server (remote, Streamable HTTP at /mcp) ----------
# Lets Claude and other MCP agents call the API as tools.
# IMPORTANT: this block must stay LAST (it mounts at "/"). A problem in here disables MCP only:
# the REST API keeps running and /health shows mcp_error.
mcp_error: Optional[str] = None
try:
    from mcp.server.fastmcp import Context, FastMCP
    _HAS_MCP = True
except ImportError:  # `mcp` not installed: the REST API still works
    _HAS_MCP = False
    mcp_error = "mcp package not installed"
try:
    from mcp.server.fastmcp.exceptions import ToolError  # message is shown to the model
except Exception:  # noqa: BLE001
    ToolError = ValueError  # type: ignore[misc,assignment]
try:
    from mcp.types import ToolAnnotations
except Exception:  # noqa: BLE001
    ToolAnnotations = None  # type: ignore[assignment,misc]

MCP_INSTRUCTIONS = (
    "Solana token data and risk checks (heuristics, not financial advice). Recommended workflow: "
    "1) check_tokens_batch for a watchlist (ranked, safest first; use min_liq or max_age_minutes to skip junk early) or check_token_risk for one token; "
    "2) if the verdict is not 'avoid', call check_exit to see what selling would cost; "
    "3) call get_track_record once to learn how reliable past verdicts were. "
    "Always read data_quality: if completeness is 'partial' or freshness is 'stale', say so and lower your confidence. "
    "Never present a verdict as a guarantee."
)


def _mcp_key(ctx) -> str:
    try:
        return client_ip(ctx.request_context.request)
    except Exception:  # noqa: BLE001
        return "mcp-unknown"


def _rl(key: str, cost: int = 1):
    wait = rate_limited(key, cost=cost)
    if wait:
        raise ToolError(f"Rate limit exceeded. Retry in {wait}s")


async def _mcp_signal(mint: str, security: bool) -> dict:
    mint = (mint or "").strip()
    if not MINT_RE.match(mint):
        raise ToolError("Invalid Solana token mint address (expected base58, 32-44 characters)")
    try:
        res, _ = await build_signal(app.state.client, mint, security)
    except HTTPException as e:
        raise ToolError(f"{e.detail} (HTTP {e.status_code})")
    return res


def _setup_mcp():
    import inspect

    kwargs: Dict[str, Any] = dict(stateless_http=True, json_response=True, instructions=MCP_INSTRUCTIONS)
    try:
        # FastMCP enables localhost-only Host checks by default, which would reject *.onrender.com.
        # This server is public with no cookies or auth.
        from mcp.server.transport_security import TransportSecuritySettings
        kwargs["transport_security"] = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    except ImportError:
        pass
    srv = FastMCP("TVibex402", **kwargs)

    def supports(fn, name: str) -> bool:
        try:
            return name in inspect.signature(fn).parameters
        except (TypeError, ValueError):
            return False

    def tool(title: str):
        kw: Dict[str, Any] = {}
        if supports(srv.tool, "title"):
            kw["title"] = title
        if ToolAnnotations is not None and supports(srv.tool, "annotations"):
            kw["annotations"] = ToolAnnotations(title=title, readOnlyHint=True, destructiveHint=False,
                                                idempotentHint=True, openWorldHint=True)
        return srv.tool(**kw)

    @tool("Token risk check")
    async def check_token_risk(mint: str, ctx: Context, include_security: bool = True) -> dict:
        """Quick decision for ONE Solana token: verdict (ok/caution/avoid) with reasons, risk score, price, liquidity,
        authorities, top-10 holder % and LP lock %. Start here. Read data_quality before trusting it.
        mint: the token's Solana mint address (base58)."""
        _rl(_mcp_key(ctx))
        return compact_signal(await _mcp_signal(mint, include_security))

    @tool("Token signal (full data)")
    async def get_token_signal(mint: str, ctx: Context, include_security: bool = True) -> dict:
        """Full market and on-chain data for ONE token: price changes, volume, buy pressure, flags, security block,
        summary and suggested next steps. Use when check_token_risk is not enough."""
        _rl(_mcp_key(ctx))
        return await _mcp_signal(mint, include_security)

    @tool("Smart batch check")
    async def check_tokens_batch(mints: List[str], ctx: Context, include_security: bool = True, sort: str = "safest",
                                 only: Optional[str] = None, max_risk: Optional[int] = None,
                                 top: Optional[int] = None, min_liq: Optional[float] = None,
                                 max_age_minutes: Optional[int] = None, min_volume_1h: Optional[float] = None) -> dict:
        """Check up to 10 tokens at once with ONE shared data request. Returns summary.headline (one sentence), results
        ranked by safety (safety_rank 1 = lowest risk) and errors for tokens that failed or are still computing.
        sort: safest (default) | riskiest | input | liquidity | volume_1h. only: keep these verdicts, e.g. 'ok,caution'.
        max_risk: keep risk_score <= this. top: keep the first N after sorting.
        min_liq (USD), max_age_minutes, min_volume_1h: cheap filters applied BEFORE the heavy checks; skipped tokens are
        listed in `skipped` with the reason."""
        key = _mcp_key(ctx)
        try:
            return await build_batch(app.state.client, mints, include_security, sort=sort, only=only, max_risk=max_risk,
                                     top=top, view="compact", min_liq=min_liq, max_age_minutes=max_age_minutes,
                                     min_volume_1h=min_volume_1h, charge=lambda cost: rate_limited(key, cost=cost))
        except HTTPException as e:
            raise ToolError(f"{e.detail} (HTTP {e.status_code})")

    @tool("Exit check (can you sell?)")
    async def check_exit(mint: str, ctx: Context, sizes_usd: Optional[List[float]] = None) -> dict:
        """Can you SELL this token, and at what cost? Quotes selling each size (default $100 and $1000) through Jupiter
        and compares with the market price. Returns combined_verdict (market + exit), loss_vs_market_pct per size and a
        summary. Use after check_token_risk, before sizing a trade. A quote is not proof a real sell will succeed."""
        _rl(_mcp_key(ctx), cost=2)
        mint = (mint or "").strip()
        if not MINT_RE.match(mint):
            raise ToolError("Invalid Solana token mint address (expected base58, 32-44 characters)")
        try:
            return await build_exit_report(app.state.client, mint, clean_sizes(sizes_usd))
        except HTTPException as e:
            raise ToolError(f"{e.detail} (HTTP {e.status_code})")

    @tool("Track record")
    async def get_track_record() -> dict:
        """How often were this service's verdicts right? Measured outcomes about 24h after each verdict, per verdict
        and per flag, with recent examples and caveats. Rates stay null until enough samples exist."""
        return await stats_report(app.state.client)

    return srv


if _HAS_MCP:
    try:
        _srv = _setup_mcp()
        app.mount("/", _srv.streamable_http_app())
        mcp_server = _srv
    except Exception as _e:  # noqa: BLE001  never let MCP problems take the REST API down
        mcp_server = None
        mcp_error = f"{type(_e).__name__}: {str(_e)[:200]}"

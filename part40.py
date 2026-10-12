# ---------- part40: v2.27.0 - /feedback: agents report real exit outcomes ----------
import json as _json

VERSION = "2.27.0"
app.version = VERSION
app.openapi_schema = None

FB_KEY = "fb:list"
FB_MAX = max(100, int(os.getenv("FEEDBACK_MAX", "5000")))
FB_MIN_SHOW = 20


def _fb_num(v, lo, hi):
    try:
        x = float(v)
    except Exception:
        return None
    if x != x or x < lo or x > hi:
        return None
    return round(x, 2)


@app.post("/feedback", tags=["feedback"], summary="Report what really happened when you sold a token")
async def feedback_route(request: Request):
    wait = rate_limited("fb:" + client_ip(request), limit=10)
    if wait:
        raise HTTPException(status_code=429, detail="rate limited", headers={"Retry-After": str(wait)})
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="send JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="send a JSON object")
    mint = str(body.get("mint") or "")
    if not MINT_RE.match(mint):
        raise HTTPException(status_code=422, detail="mint must be a Solana address")
    sell_ok = body.get("sell_ok")
    if not isinstance(sell_ok, bool):
        raise HTTPException(status_code=422, detail="sell_ok must be true or false")
    verdict = str(body.get("verdict_seen") or "")[:10]
    if verdict not in ("ok", "caution", "avoid"):
        verdict = ""
    try:
        trusted = bool(API_KEYS) and request.headers.get("x-api-key") in API_KEYS
    except Exception:
        trusted = False
    row = {"t": int(time.time()), "mint": mint, "sell_ok": sell_ok,
           "slip": _fb_num(body.get("slippage_pct"), -100, 100),
           "usd": _fb_num(body.get("size_usd"), 0, 10000000),
           "quote": _fb_num(body.get("quoted_cost_pct"), -100, 100),
           "v": verdict, "trusted": bool(trusted)}
    res = await redis_pipe(request.app.state.client, [
        ["LPUSH", FB_KEY, _json.dumps(row, separators=(",", ":"))],
        ["LTRIM", FB_KEY, 0, FB_MAX - 1],
    ])
    if res is None:
        raise HTTPException(status_code=503, detail="storage unavailable, retry later")
    return JSONResponse({"ok": True, "trusted": bool(trusted)}, headers={"Cache-Control": "no-store"})


@app.get("/feedback/stats", tags=["feedback"], summary="Aggregate of reported exit outcomes")
async def feedback_stats(request: Request):
    wait = rate_limited("fbs:" + client_ip(request), limit=20)
    if wait:
        raise HTTPException(status_code=429, detail="rate limited", headers={"Retry-After": str(wait)})
    res = await redis_pipe(request.app.state.client, [["LRANGE", FB_KEY, 0, 999]])
    if res is None:
        raise HTTPException(status_code=503, detail="storage unavailable, retry later")
    first = res[0] if res else None
    items = first.get("result") if isinstance(first, dict) else first
    rows = []
    for s in items or []:
        try:
            rows.append(_json.loads(s))
        except Exception:
            pass

    def pct(sub):
        return round(100.0 * sum(1 for r in sub if r.get("sell_ok")) / len(sub), 1) if len(sub) >= FB_MIN_SHOW else None

    slips = sorted(r["slip"] for r in rows if r.get("slip") is not None)
    out = {
        "reports": len(rows),
        "sell_success_pct": pct(rows),
        "median_slippage_pct": slips[len(slips) // 2] if len(slips) >= FB_MIN_SHOW else None,
        "by_verdict": {v: {"n": len([r for r in rows if r.get("v") == v]),
                           "sell_success_pct": pct([r for r in rows if r.get("v") == v])}
                       for v in ("ok", "caution", "avoid")},
        "trusted_reports": sum(1 for r in rows if r.get("trusted")),
        "note": "Self-reported. Rates stay hidden under 20 reports. Anonymous reports are not used to tune verdicts.",
    }
    return JSONResponse(out, headers={"Cache-Control": "no-store"})


try:
    if "POST /feedback" not in LLMS_TXT:
        LLMS_TXT = LLMS_TXT + """
## Feedback
POST /feedback {"mint","sell_ok":true|false,"slippage_pct","size_usd","quoted_cost_pct","verdict_seen"}
Report what really happened when you sold. GET /feedback/stats shows the aggregate.
"""
except NameError:
    pass

print(f"[part40] v{VERSION} /feedback ready (max {FB_MAX} reports)")
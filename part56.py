# ---------- v2.42: Simple Watchlist + Alert ----------
VERSION = "2.42.1"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import List, Optional

WATCH_KEY = "watch:{}"          # watch:{id} → list of mints
WATCH_TTL = 7 * 24 * 3600
ALERT_KEY = "alert:{}"          # alert:{id} → list of recent alerts

def _watch_id(request: Request) -> str:
    """Dùng IP hoặc API key làm id đơn giản."""
    key = request.headers.get("x-api-key")
    if key:
        return "k:" + key[:16]
    return "ip:" + client_ip(request)

@app.post("/watch", tags=["watch"])
async def add_watch(
    request: Request,
    mints: str = Query(..., description="Comma-separated mints, max 10"),
):
    wait = rate_limited(client_ip(request), cost=3)
    if wait:
        raise too_many(wait)

    ids = [m.strip() for m in mints.split(",") if m.strip()][:10]
    valid = [m for m in ids if MINT_RE.match(m)]
    if not valid:
        raise HTTPException(400, "No valid mints")

    wid = _watch_id(request)
    client = request.app.state.client

    if PRED_ENABLED:
        await redis_pipe(client, [
            ["SET", WATCH_KEY.format(wid), json.dumps(valid), "EX", WATCH_TTL],
        ])

    return {"ok": True, "watch_id": wid, "mints": valid, "ttl_hours": 168}

@app.get("/watch", tags=["watch"])
async def get_watch(request: Request):
    wid = _watch_id(request)
    client = request.app.state.client
    if not PRED_ENABLED:
        return {"mints": []}
    raw = await redis_get(client, WATCH_KEY.format(wid))
    mints = json.loads(raw) if raw else []
    return {"watch_id": wid, "mints": mints}

@app.get("/watch/check", tags=["watch"])
async def check_watch(request: Request):
    """Kiểm tra nhanh các mint trong watchlist, trả về những cái đáng chú ý."""
    wait = rate_limited(client_ip(request), cost=5)
    if wait:
        raise too_many(wait)

    wid = _watch_id(request)
    client = request.app.state.client
    raw = await redis_get(client, WATCH_KEY.format(wid)) if PRED_ENABLED else None
    mints = json.loads(raw) if raw else []
    if not mints:
        return {"alerts": [], "note": "No mints in watchlist"}

    alerts = []
    for mint in mints[:8]:
        try:
            sig, _ = await build_signal(client, mint, True)
            verdict = (sig.get("decision") or {}).get("verdict") or sig.get("verdict")
            risk = sig.get("risk_score") or 0
            conv = (sig.get("community") or {}).get("conviction") or {}
            attention = (sig.get("community") or {}).get("attention") or {}

            notable = False
            reasons = []
            if verdict == "avoid" or risk >= 55:
                notable = True
                reasons.append(f"verdict={verdict}, risk={risk}")
            if conv.get("n", 0) >= 5 and conv.get("avoid_pct", 0) >= 60:
                notable = True
                reasons.append(f"community avoid {conv.get('avoid_pct')}%")
            if attention.get("1h", 0) >= 8:
                reasons.append(f"high attention 1h={attention.get('1h')}")

            if notable:
                alerts.append({
                    "mint": mint,
                    "token": sig.get("token"),
                    "verdict": verdict,
                    "risk_score": risk,
                    "reasons": reasons,
                    "community": sig.get("community"),
                })
        except Exception:
            continue

    return {
        "watch_id": wid,
        "checked": len(mints),
        "alerts": alerts,
    }
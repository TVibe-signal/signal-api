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
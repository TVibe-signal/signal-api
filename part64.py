# ---------- v2.46.1: Predictive Attention + Agent Reputation ----------
VERSION = "2.46.1"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Dict, Any, Optional
from collections import defaultdict

# ---------- Predictive Attention ----------
PRED_ATTN_KEY = "predattn:{}"          # predattn:{mint} → score
PRED_ATTN_ZSET = "predattn:top"        # zset score → mint

async def _update_predictive_attention(client, mint: str, attention: dict):
    """Very light predictor: rising short-term attention → higher score."""
    if not PRED_ENABLED or not client:
        return
    try:
        a1 = attention.get("1h", 0)
        a6 = attention.get("6h", 0)
        a24 = attention.get("24h", 0)
        # Simple momentum: 1h heavy relative to 24h
        score = a1 * 3.0 + max(0, a1 - a6 / 6) * 2.0 + min(a24, 40) * 0.1
        if score < 1:
            return
        await redis_pipe(client, [
            ["SET", PRED_ATTN_KEY.format(mint), str(round(score, 2)), "EX", 7200],
            ["ZADD", PRED_ATTN_ZSET, score, mint],
            ["ZREMRANGEBYRANK", PRED_ATTN_ZSET, 0, -101],  # keep top 100
            ["EXPIRE", PRED_ATTN_ZSET, 7200],
        ])
    except Exception:
        pass

@app.get("/predictive-attention", tags=["experimental"])
async def predictive_attention(request: Request, limit: int = 10):
    """Tokens that currently look likely to receive more attention soon."""
    if not PRED_ENABLED:
        return {"enabled": False, "items": []}
    client = request.app.state.client
    limit = max(1, min(limit, 30))
    try:
        res = await redis_pipe(client, [["ZREVRANGE", PRED_ATTN_ZSET, 0, limit - 1, "WITHSCORES"]])
        raw = (res or [[]])[0] or []
        items = []
        for i in range(0, len(raw), 2):
            items.append({"mint": raw[i], "score": float(raw[i + 1])})
        return {"enabled": True, "items": items}
    except Exception:
        return {"enabled": True, "items": []}

# Hook into community recording
_build_prev_pred = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_pred(client, mint, security, prefetched)
    try:
        attn = (result.get("community") or {}).get("attention") or {}
        if attn:
            await _update_predictive_attention(client, mint, attn)
            # Attach a small hint when score is meaningful
            if PRED_ENABLED:
                raw = await redis_get(client, PRED_ATTN_KEY.format(mint))
                if raw:
                    score = float(raw)
                    if score >= 8:
                        result.setdefault("community", {})
                        result["community"]["predictive_score"] = round(score, 1)
    except Exception:
        pass
    return result, status

# ---------- Agent Reputation ----------
REP_KEY = "agentrep:{}"                # agentrep:{id} → hash

def _agent_id(request) -> str:
    key = (request.headers.get("x-api-key") or "").strip()
    if key:
        return "k:" + key[:20]
    return "ip:" + client_ip(request)

async def _bump_reputation(client, agent: str, useful: str):
    if not PRED_ENABLED or not client:
        return
    try:
        field = {"yes": "up", "no": "down", "neutral": "neu"}.get(useful, "neu")
        await redis_pipe(client, [
            ["HINCRBY", REP_KEY.format(agent), field, 1],
            ["HINCRBY", REP_KEY.format(agent), "total", 1],
            ["EXPIRE", REP_KEY.format(agent), 90 * 86400],
        ])
    except Exception:
        pass

async def get_agent_reputation(client, agent: str) -> Dict[str, Any]:
    if not PRED_ENABLED or not client:
        return {"n": 0}
    try:
        raw = await redis_pipe(client, [["HGETALL", REP_KEY.format(agent)]])
        h = to_dict((raw or [{}])[0] or {})
        up = int(h.get("up", 0))
        down = int(h.get("down", 0))
        neu = int(h.get("neu", 0))
        total = int(h.get("total", 0)) or (up + down + neu)
        score = round((up - down) / max(1, total), 3)
        return {"n": total, "up": up, "down": down, "neutral": neu, "score": score}
    except Exception:
        return {"n": 0}

# Patch feedback endpoint to also record reputation
_old_feedback = None
for route in list(app.routes):
    if getattr(route, "path", None) == "/feedback" and "POST" in getattr(route, "methods", set()):
        _old_feedback = route.endpoint
        break

@app.post("/feedback", tags=["community"])
async def feedback_with_rep(
    request: Request,
    mint: str,
    useful: str,
    note: str = "",
):
    if useful not in ("yes", "no", "neutral"):
        raise HTTPException(400, "useful must be yes, no or neutral")
    wait = rate_limited(client_ip(request), cost=2)
    if wait:
        raise too_many(wait)
    if not MINT_RE.match(mint):
        raise HTTPException(400, "Invalid mint")

    client = request.app.state.client
    if " _save_feedback" in globals() or "_save_feedback" in globals():
        await _save_feedback(client, mint, useful, note)
    agent = _agent_id(request)
    await _bump_reputation(client, agent, useful)
    return {"ok": True, "mint": mint, "useful": useful, "agent": agent}

@app.get("/reputation", tags=["experimental"])
async def my_reputation(request: Request):
    client = request.app.state.client
    agent = _agent_id(request)
    rep = await get_agent_reputation(client, agent)
    return {"agent": agent, "reputation": rep}

print(f"[part64] v{VERSION} Predictive Attention + Agent Reputation loaded")
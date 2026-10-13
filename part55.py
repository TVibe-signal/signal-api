# ---------- v2.42: Better MCP tools + Agent Feedback ----------
VERSION = "2.42.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Optional, List

# ---------- Feedback ----------
FEEDBACK_KEY = "fb:{}"          # fb:{mint} → list
FEEDBACK_MAX = 30
FEEDBACK_TTL = 14 * 24 * 3600

async def _save_feedback(client, mint: str, useful: str, note: str = ""):
    if not PRED_ENABLED or not client:
        return
    try:
        entry = json.dumps({
            "u": useful,          # "yes" | "no" | "neutral"
            "n": (note or "")[:120],
            "ts": int(time.time()),
        })
        await redis_pipe(client, [
            ["LPUSH", FEEDBACK_KEY.format(mint), entry],
            ["LTRIM", FEEDBACK_KEY.format(mint), 0, FEEDBACK_MAX - 1],
            ["EXPIRE", FEEDBACK_KEY.format(mint), FEEDBACK_TTL],
        ])
    except Exception:
        pass

async def get_feedback_summary(client, mint: str) -> dict:
    if not PRED_ENABLED or not client:
        return {"n": 0}
    try:
        res = await redis_pipe(client, [["LRANGE", FEEDBACK_KEY.format(mint), 0, FEEDBACK_MAX - 1]])
        items = (res or [[]])[0] or []
        yes = no = neutral = 0
        for raw in items:
            try:
                d = json.loads(raw)
                u = d.get("u")
                if u == "yes": yes += 1
                elif u == "no": no += 1
                else: neutral += 1
            except Exception:
                continue
        n = yes + no + neutral
        return {
            "n": n,
            "useful_pct": round(yes / n * 100, 1) if n else 0,
            "not_useful_pct": round(no / n * 100, 1) if n else 0,
            "neutral_pct": round(neutral / n * 100, 1) if n else 0,
        }
    except Exception:
        return {"n": 0}

# Endpoint feedback (public, rate-limited)
@app.post("/feedback", tags=["community"])
async def submit_feedback(
    request: Request,
    mint: str,
    useful: str = Query(..., regex="^(yes|no|neutral)$"),
    note: str = Query("", max_length=120),
):
    wait = rate_limited(client_ip(request), cost=2)
    if wait:
        raise too_many(wait)
    if not MINT_RE.match(mint):
        raise HTTPException(400, "Invalid mint")
    client = request.app.state.client
    await _save_feedback(client, mint, useful, note)
    return {"ok": True, "mint": mint, "useful": useful}

# ---------- MCP tools bổ sung ----------
# Chỉ hoạt động nếu MCP đã được load (part7)
try:
    if mcp_server is not None:
        @mcp_server.tool()
        async def get_community(mint: str) -> dict:
            """Get community attention + conviction for a token."""
            client = app.state.client
            attn = await get_attention(client, mint) if "get_attention" in globals() else {}
            conv = await get_community_conviction(client, mint) if "get_community_conviction" in globals() else {}
            fb = await get_feedback_summary(client, mint)
            return {
                "mint": mint,
                "attention": attn,
                "conviction": conv,
                "feedback": fb,
            }

        @mcp_server.tool()
        async def explain_verdict(mint: str) -> dict:
            """Explain the current verdict flag by flag."""
            sig, _ = await build_signal(app.state.client, mint, True)
            decision = sig.get("decision") or {}
            return {
                "mint": mint,
                "verdict": decision.get("verdict"),
                "risk_score": sig.get("risk_score"),
                "blockers": decision.get("blockers"),
                "cautions": decision.get("cautions"),
                "positives": decision.get("positives"),
                "community": sig.get("community"),
                "summary": sig.get("summary"),
            }

        @mcp_server.tool()
        async def submit_agent_feedback(mint: str, useful: str, note: str = "") -> dict:
            """Agents can report whether a verdict was useful (yes/no/neutral)."""
            if useful not in ("yes", "no", "neutral"):
                return {"error": "useful must be yes, no or neutral"}
            await _save_feedback(app.state.client, mint, useful, note)
            return {"ok": True, "mint": mint, "useful": useful}

except Exception:
    pass
# ---------- Cập nhật llms.txt cho 3 tính năng mới ----------
if "LLMS_TXT" in globals():
    LLMS_TXT += """

## Community context
Every signal may include a `community` object when enough data exists:
- attention: how many times the mint was queried in 1h / 6h / 24h
- conviction: distribution of recent verdicts (ok / caution / avoid %) + dominant verdict
- summary: short human-readable sentence

Use community as extra context only. It is not financial advice and not a guarantee.

## Agent Feedback
POST /feedback?mint=ADDRESS&useful=yes|no|neutral&note=optional
MCP tool: submit_agent_feedback(mint, useful, note="")

Agents can anonymously report whether a verdict was useful. This helps improve the system over time.

## Simple Watchlist
- POST /watch?mints=A,B,C     → save up to 10 mints (bound to IP or API key, 7-day TTL)
- GET  /watch                 → show current watchlist
- GET  /watch/check           → check watched mints and return notable ones (high risk or strong community avoid)

Useful for agents that want to monitor a small set of tokens without constant full polling.

## New MCP tools
- get_community(mint)           → attention + conviction + feedback summary
- explain_verdict(mint)         → full breakdown of the current decision
- submit_agent_feedback(...)    → report useful / not useful / neutral
"""
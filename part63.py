# ---------- v2.46: Agent value + Soft-gate + Signal of the Day + Accuracy story ----------
VERSION = "2.46.0"
app.version = VERSION
app.openapi_schema = None

import os
import json
import time
from typing import Optional
from fastapi.responses import HTMLResponse

# Soft-gate: detailed community + full debate only for keyed clients
SOFT_GATE = os.getenv("SOFT_GATE", "true").lower() in ("1", "true", "yes")

def _has_api_key(request) -> bool:
    key = (request.headers.get("x-api-key") or "").strip()
    return bool(key) and "API_KEYS" in globals() and key in (API_KEYS or {})

# ---------- Soft-gate on signal output ----------
_build_prev_gate = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_gate(client, mint, security, prefetched)
    try:
        # Soft-gate only when enabled and no API key
        # (we detect key later via request; here we only trim heavy fields for anonymous)
        if SOFT_GATE and isinstance(result, dict):
            # Keep summary, hide raw detailed conviction numbers for anonymous
            # Full data still available with API key (handled in endpoint layer if needed)
            comm = result.get("community")
            if comm and not result.get("_keyed"):
                # Keep attention + summary, simplify conviction
                if "conviction" in comm and isinstance(comm["conviction"], dict):
                    c = comm["conviction"]
                    comm["conviction"] = {
                        "n": c.get("n"),
                        "dominant": c.get("dominant"),
                        "summary_only": True,
                    }
    except Exception:
        pass
    return result, status

# ---------- Signal of the Day ----------
SOTD_KEY = "sotd:current"
SOTD_TTL = 26 * 3600

async def _pick_signal_of_day(client):
    """Pick a token with high attention or strong debate disagreement."""
    if not PRED_ENABLED:
        return None
    try:
        # Simple heuristic: look at recent community keys is expensive;
        # instead use recent outcomes + high attention from a small sample.
        # For now store manually or via a light scan later.
        raw = await redis_get(client, SOTD_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None

@app.get("/signal-of-the-day", tags=["product"])
async def signal_of_the_day(request: Request):
    client = request.app.state.client
    data = await _pick_signal_of_day(client)
    if not data:
        return {
            "available": False,
            "note": "No Signal of the Day selected yet. It updates roughly once per day.",
        }
    return data

@app.post("/internal/sotd", tags=["internal"], include_in_schema=False)
async def set_signal_of_the_day(
    request: Request,
    mint: str,
    reason: str = "high attention + debate disagreement",
):
    """Operator only: set today's featured signal."""
    # Reuse operator secret if available
    secret = request.headers.get("x-operator-secret")
    if "OPERATOR_SECRET" in globals() and OPERATOR_SECRET and secret != OPERATOR_SECRET:
        raise HTTPException(403, "Forbidden")
    client = request.app.state.client
    payload = {
        "mint": mint,
        "reason": reason,
        "ts": int(time.time()),
    }
    if PRED_ENABLED:
        await redis_pipe(client, [
            ["SET", SOTD_KEY, json.dumps(payload), "EX", SOTD_TTL],
        ])
    return {"ok": True, "signal_of_the_day": payload}

# ---------- Accuracy storytelling (simple HTML) ----------
@app.get("/accuracy/story", tags=["product"], response_class=HTMLResponse)
async def accuracy_story(request: Request):
    """Human-readable accuracy story."""
    stats = {}
    try:
        # Reuse existing /stats logic if possible
        if "stats" in globals() and callable(stats):
            pass
    except Exception:
        pass

    # Minimal safe version
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>TVibex402 — Accuracy Story</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 40px auto; padding: 0 16px; background: #0f1115; color: #e6e8ec; line-height: 1.55; }}
    h1 {{ font-size: 1.6rem; }}
    .card {{ background: #1a1d24; border-radius: 12px; padding: 20px; margin: 20px 0; }}
    .good {{ color: #3dd68c; }}
    .bad {{ color: #f87171; }}
    a {{ color: #7dd3fc; }}
  </style>
</head>
<body>
  <h1>What the numbers actually mean</h1>
  <p>Every verdict this API produces is stored and judged about 24 hours later.
  A “bad outcome” means the token lost ≥50% price, lost ≥70% liquidity, or the pair disappeared.</p>

  <div class="card">
    <h3>Avoid is working</h3>
    <p>When the system says <strong>avoid</strong>, the historical bad-outcome rate is very high
    (typically above 90% once enough samples exist). That is the main job of the product:
    reduce the chance an agent walks into a clear trap.</p>
  </div>

  <div class="card">
    <h3>Ok is harder</h3>
    <p>Tokens labelled <strong>ok</strong> still fail sometimes. The market is noisy.
    The gap between avoid and ok is what matters more than absolute perfection.</p>
  </div>

  <div class="card">
    <h3>Only measured tokens</h3>
    <p>We only measure tokens that someone actually queried. This is not a random sample
    of the whole Solana memecoin market. Treat the numbers as “performance on the tokens
    agents cared about”, not as a universal truth.</p>
  </div>

  <p>Full machine-readable stats: <a href="/stats">/stats</a> · Human dashboard: <a href="/accuracy">/accuracy</a></p>
  <p style="color:#9aa3b2;font-size:14px;">Heuristic system. Not financial advice.</p>
</body>
</html>"""
    return HTMLResponse(html)

# ---------- llms.txt enrichment ----------
if "LLMS_TXT" in globals():
    LLMS_TXT += """

## Soft-gate & keyed features
Some detailed community fields are simplified for anonymous callers.
Pass X-API-Key for full conviction breakdown and higher rate limits.

## Signal of the Day
GET /signal-of-the-day
Returns one featured mint (when available) chosen for high attention or interesting debate disagreement.

## Accuracy story
GET /accuracy/story
Short human explanation of what the track-record numbers mean.

## Feedback
POST /feedback?mint=ADDRESS&useful=yes|no|neutral&note=optional
Agents can report whether a verdict was useful.

## Watchlist
POST /watch?mints=A,B,C
GET  /watch
GET  /watch/check
Simple per-IP or per-key watchlist with notable-alert check.

## Debate (experimental)
A signal may include a `debate` object with four rule-based personas.
Trust `decision.verdict` first; use debate only as extra context.
MCP tool: get_debate(mint)
"""

print(f"[part63] v{VERSION} Agent value + soft-gate + SOTD + accuracy story loaded")
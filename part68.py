# ---------- v2.49: SI Outcome Hook (close the learning loop) ----------
VERSION = "2.49.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Optional

# We patch the existing resolve helpers if present.
# Compatible with part42 / part47 style resolvers.

async def _si_on_judged(client, mint: str, bad: bool, src: str = "resolver"):
    """Notify SI layers that an outcome label is known."""
    try:
        if "on_outcome_for_si" in globals():
            await on_outcome_for_si(client, mint, bad)
        else:
            # Fallback: debate + hypo only
            if "score_debate_against_outcome" in globals():
                await score_debate_against_outcome(client, mint, bad)
            if " _touch_hypothesis" in globals() or "_touch_hypothesis" in globals():
                raw = await redis_get(client, f"hypo:pending:{mint}")
                if raw:
                    try:
                        matched = json.loads(raw)
                        for hid in matched:
                            await _touch_hypothesis(client, hid, bad=bad)
                        await redis_pipe(client, [["DEL", f"hypo:pending:{mint}"]])
                    except Exception:
                        pass
        # Light global counter for observability
        if PRED_ENABLED:
            await redis_pipe(client, [
                ["HINCRBY", "si:meta", "outcomes_fed", 1],
                ["HINCRBY", "si:meta", "outcomes_bad" if bad else "outcomes_good", 1],
            ])
    except Exception as e:
        print(f"[part68] SI outcome hook error: {e}")

# ---------- Patch 24h resolver if available ----------
if " _resolve_due_24h" in globals() or "_resolve_due_24h" in globals():
    _resolve_24h_prev = _resolve_due_24h

    async def _resolve_due_24h(client):
        # Run original, then we cannot easily see each judged item without deeper rewrite.
        # So we also patch the lower-level path below.
        return await _resolve_24h_prev(client)

# ---------- Patch dataset / recent writer path (most reliable) ----------
# Many versions push a JSON row into "recent" when judged.
# We intercept by wrapping _dataset_cmds or by scanning after resolve.

_resolve_due_prev = resolve_due if "resolve_due" in globals() else None

if _resolve_due_prev:
    async def resolve_due(client):
        n = await _resolve_due_prev(client)
        # After a resolve batch, read newest recent rows and feed SI once
        try:
            if PRED_ENABLED and n:
                res = await redis_pipe(client, [["LRANGE", "recent", 0, max(0, min(n, 20) - 1)]])
                rows = (res or [[]])[0] or []
                for raw in rows:
                    try:
                        d = json.loads(raw)
                        mint = d.get("mint")
                        if not mint:
                            continue
                        bad = bool(d.get("bad_outcome"))
                        # Only feed if we still have pending SI state
                        pending = await redis_get(client, f"debate:pending:{mint}")
                        hypo_p = await redis_get(client, f"hypo:pending:{mint}")
                        if pending or hypo_p:
                            await _si_on_judged(client, mint, bad, src="recent")
                    except Exception:
                        continue
        except Exception:
            pass
        return n

# ---------- Early horizons (1h / 6h) if present ----------
if "_resolve_early_one" in globals():
    _early_prev = _resolve_early_one

    async def _resolve_early_one(client, hours: int, zset: str):
        n = await _early_prev(client, hours, zset)
        # Early horizons are noisier; only feed debate/hypo lightly via same recent mechanism if desired.
        return n

# ---------- Manual / operator feed endpoint ----------
@app.post("/internal/si-feed", tags=["internal"], include_in_schema=False)
async def si_feed_outcome(
    request: Request,
    mint: str,
    bad: bool,
    x_operator_secret: Optional[str] = None,
):
    """Operator: manually feed an outcome label into SI layers."""
    secret = request.headers.get("x-operator-secret") or x_operator_secret
    if "OPERATOR_SECRET" in globals() and OPERATOR_SECRET:
        if secret != OPERATOR_SECRET:
            raise HTTPException(403, "Forbidden")
    if not MINT_RE.match(mint):
        raise HTTPException(400, "Invalid mint")
    client = request.app.state.client
    await _si_on_judged(client, mint, bad, src="manual")
    return {"ok": True, "mint": mint, "bad": bad}

@app.get("/si/status", tags=["experimental"])
async def si_status(request: Request):
    """Quick view of SI learning health."""
    client = request.app.state.client
    out = {
        "version": VERSION,
        "layers": {
            "causal": "part65" in str(globals().get("VERSION", "")),
            "hypotheses": "list_hypotheses" in globals() or "HYPOTHESIS_TEMPLATES" in globals(),
            "regime": "get_regime" in globals(),
            "debate_learning": "get_debate_leaderboard" in globals(),
            "outcome_hook": True,
        },
    }
    try:
        if PRED_ENABLED:
            raw = await redis_pipe(client, [["HGETALL", "si:meta"]])
            out["meta"] = to_dict((raw or [{}])[0] or {})
            # Compact pointers
            out["endpoints"] = {
                "regime": "/regime",
                "hypotheses": "/hypotheses",
                "debate_scores": "/debate/scores",
                "causal": "/causal/{mint}",
                "evolution": "/evolution",
                "predictive_attention": "/predictive-attention",
                "reputation": "/reputation",
            }
    except Exception:
        pass
    return out

print(f"[part68] v{VERSION} SI Outcome Hook loaded — learning loop closed")
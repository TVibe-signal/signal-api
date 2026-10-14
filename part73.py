# ---------- v2.53: SI Event Log (Soft Event Sourcing) ----------
VERSION = "2.53.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Any, Dict, List, Optional

# Streams (Redis Lists as append-only logs)
EV_GLOBAL = "si:ev:global"          # all events (trimmed)
EV_MINT = "si:ev:mint:{}"           # per-mint stream
EV_META = "si:ev:meta"              # counters
EV_GLOBAL_MAX = 500
EV_MINT_MAX = 80
EV_TTL = 45 * 86400

# Event types (convention)
# signal_seen, verdict_emitted, outcome_judged, community_shift,
# regime_changed, evolution_proposed, hypothesis_updated,
# feedback_received, entity_refreshed, attention_trap, genetic_risk

def _ev(kind: str, mint: Optional[str] = None, payload: Optional[dict] = None) -> dict:
    return {
        "ts": int(time.time()),
        "kind": kind,
        "mint": mint,
        "payload": payload or {},
        "v": 1,
    }

async def si_emit(client, kind: str, mint: Optional[str] = None, payload: Optional[dict] = None) -> bool:
    """Append one event to global + optional per-mint stream."""
    if not PRED_ENABLED or not client:
        return False
    try:
        event = _ev(kind, mint, payload)
        raw = json.dumps(event, separators=(",", ":"), default=str)
        cmds = [
            ["LPUSH", EV_GLOBAL, raw],
            ["LTRIM", EV_GLOBAL, 0, EV_GLOBAL_MAX - 1],
            ["EXPIRE", EV_GLOBAL, EV_TTL],
            ["HINCRBY", EV_META, "n", 1],
            ["HINCRBY", EV_META, f"k:{kind}", 1],
            ["EXPIRE", EV_META, EV_TTL],
        ]
        if mint:
            mk = EV_MINT.format(mint)
            cmds += [
                ["LPUSH", mk, raw],
                ["LTRIM", mk, 0, EV_MINT_MAX - 1],
                ["EXPIRE", mk, EV_TTL],
            ]
        await redis_pipe(client, cmds)
        return True
    except Exception as e:
        print(f"[part73] emit failed: {e}")
        return False

async def si_read_global(client, limit: int = 30) -> List[dict]:
    if not PRED_ENABLED or not client:
        return []
    limit = max(1, min(limit, 100))
    try:
        res = await redis_pipe(client, [["LRANGE", EV_GLOBAL, 0, limit - 1]])
        out = []
        for raw in (res or [[]])[0] or []:
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
        return out
    except Exception:
        return []

async def si_read_mint(client, mint: str, limit: int = 30) -> List[dict]:
    if not PRED_ENABLED or not client:
        return []
    limit = max(1, min(limit, 100))
    try:
        res = await redis_pipe(client, [["LRANGE", EV_MINT.format(mint), 0, limit - 1]])
        out = []
        for raw in (res or [[]])[0] or []:
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
        return out
    except Exception:
        return []

async def si_event_stats(client) -> dict:
    if not PRED_ENABLED or not client:
        return {}
    try:
        raw = await redis_pipe(client, [["HGETALL", EV_META]])
        return to_dict((raw or [{}])[0] or {})
    except Exception:
        return {}

# -------------------- API --------------------

@app.get("/si/events", tags=["entity"])
async def si_events(request: Request, limit: int = 30, mint: Optional[str] = None):
    """Read recent SI events (global or per-mint)."""
    client = request.app.state.client
    if mint:
        if not MINT_RE.match(mint):
            raise HTTPException(400, "Invalid mint")
        events = await si_read_mint(client, mint, limit)
        return {"scope": "mint", "mint": mint, "events": events, "n": len(events)}
    events = await si_read_global(client, limit)
    stats = await si_event_stats(client)
    return {"scope": "global", "events": events, "n": len(events), "stats": stats}

# -------------------- Hooks into pipeline --------------------

_build_prev_ev = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_ev(client, mint, security, prefetched)
    try:
        if not isinstance(result, dict):
            return result, status

        verdict = (result.get("decision") or {}).get("verdict") or result.get("verdict")
        await si_emit(client, "verdict_emitted", mint, {
            "verdict": verdict,
            "risk_score": result.get("risk_score"),
            "dna": result.get("dna"),
        })

        # Meaningful SI flags as events
        if result.get("attention_trap"):
            await si_emit(client, "attention_trap", mint, {})
        if result.get("genetic_risk"):
            await si_emit(client, "genetic_risk", mint, {"dna": result.get("dna")})

        causal_last = ((result.get("causal") or {}).get("last_events") or [])
        for ev in causal_last[:2]:
            kind = ev.get("kind")
            if kind in ("community_shift", "attention_spike", "verdict_change", "debate_split", "risk_jump"):
                await si_emit(client, kind, mint, ev.get("detail") or {})

        if result.get("hypotheses_matched"):
            await si_emit(client, "hypothesis_matched", mint, {
                "ids": result.get("hypotheses_matched"),
            })

        reg = result.get("regime") or {}
        if reg.get("name"):
            # Light dedupe via payload only; high volume is ok with trim
            await si_emit(client, "regime_seen", mint, {
                "name": reg.get("name"),
                "confidence": reg.get("confidence"),
            })

    except Exception:
        pass
    return result, status

# Feed outcome events through SI outcome hook
_prev_on_outcome = globals().get("on_outcome_for_si")

async def on_outcome_for_si(client, mint: str, bad_outcome: bool):
    if _prev_on_outcome:
        try:
            await _prev_on_outcome(client, mint, bad_outcome)
        except Exception:
            pass
    try:
        await si_emit(client, "outcome_judged", mint, {"bad": bool(bad_outcome)})
    except Exception:
        pass

# Wrap feedback if we can observe useful votes
# (part64/70 may already define feedback; emit event best-effort via swarm path)

_prev_refresh_entity = globals().get("refresh_entity")

if _prev_refresh_entity:
    async def refresh_entity(client, force_journal: bool = False):
        entity = await _prev_refresh_entity(client, force_journal=force_journal)
        try:
            await si_emit(client, "entity_refreshed", None, {
                "mood": (entity or {}).get("mood"),
                "integrity": (entity or {}).get("integrity"),
                "age_days": (entity or {}).get("age_days"),
            })
        except Exception:
            pass
        return entity

@app.get("/si/events/stats", tags=["entity"])
async def si_events_stats(request: Request):
    client = request.app.state.client
    return {"stats": await si_event_stats(client), "version": VERSION}

print(f"[part73] v{VERSION} SI Event Log loaded → GET /si/events")
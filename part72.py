# ---------- v2.52: SI Entity Core (identity · mood · focus · journal) ----------
VERSION = "2.52.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Any, Dict, List, Optional

ENTITY_KEY = "si:entity:core"
JOURNAL_KEY = "si:entity:journal"
FOCUS_KEY = "si:entity:focus"
ENTITY_NAME = "TVibex402-SI"
ENTITY_BORN_FALLBACK = 1728880000  # rough genesis; overwritten on first save

# -------------------- helpers --------------------

def _now() -> int:
    return int(time.time())

def _mood_from_regime(regime: str, bad_rate: Optional[float]) -> str:
    r = (regime or "unknown").lower()
    if r == "rug_wave":
        return "vigilant"
    if r == "risk_off":
        return "cautious"
    if r == "risk_on":
        return "exploratory"
    if r == "calm":
        return "steady"
    if bad_rate is not None and bad_rate >= 0.65:
        return "vigilant"
    if bad_rate is not None and bad_rate <= 0.30:
        return "calm"
    return "observing"

def _integrity(cf: dict, debate: dict) -> float:
    """0..1 rough self-trust score."""
    score = 0.55
    try:
        help_pct = cf.get("avoid_would_help_pct")
        if help_pct is not None:
            # If avoid would have helped often, system is useful under stress
            score += min(0.2, float(help_pct) * 0.2)
        # Best persona accuracy
        best = 0.0
        n_ok = 0
        for _, st in (debate or {}).items():
            acc = st.get("accuracy")
            n = st.get("n") or 0
            if acc is not None and n >= 8:
                best = max(best, float(acc))
                n_ok += 1
        if n_ok:
            score = 0.4 * score + 0.6 * best
    except Exception:
        pass
    return round(max(0.05, min(0.99, score)), 3)

async def _safe_regime(client) -> dict:
    try:
        if "get_regime" in globals():
            return await get_regime(client) or {}
    except Exception:
        pass
    return {}

async def _safe_cf(client) -> dict:
    try:
        if "counterfactual_summary" in globals():
            return await counterfactual_summary(client) or {}
    except Exception:
        pass
    return {}

async def _safe_debate(client) -> dict:
    try:
        if "get_debate_leaderboard" in globals():
            return await get_debate_leaderboard(client) or {}
    except Exception:
        pass
    return {}

async def _safe_hypos(client) -> List[dict]:
    try:
        if "_load_hypotheses" in globals():
            return await _load_hypotheses(client) or []
    except Exception:
        pass
    return []

async def _safe_pred_top(client, limit: int = 8) -> List[dict]:
    if not PRED_ENABLED or not client:
        return []
    try:
        res = await redis_pipe(client, [["ZREVRANGE", "predattn:top", 0, limit - 1, "WITHSCORES"]])
        raw = (res or [[]])[0] or []
        out = []
        for i in range(0, len(raw), 2):
            out.append({"mint": raw[i], "score": float(raw[i + 1])})
        return out
    except Exception:
        return []

async def _load_entity(client) -> dict:
    if PRED_ENABLED and client:
        try:
            raw = await redis_get(client, ENTITY_KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return {
        "name": ENTITY_NAME,
        "born_ts": ENTITY_BORN_FALLBACK,
        "version_core": VERSION,
        "mood": "observing",
        "focus": [],
        "beliefs": [],
        "integrity": 0.5,
        "last_update_ts": 0,
        "stats": {},
    }

async def _save_entity(client, entity: dict):
    if not PRED_ENABLED or not client:
        return
    try:
        await redis_pipe(client, [
            ["SET", ENTITY_KEY, json.dumps(entity, separators=(",", ":")), "EX", 120 * 86400],
        ])
    except Exception:
        pass

async def _append_journal(client, line: str, meta: Optional[dict] = None):
    if not PRED_ENABLED or not client:
        return
    entry = {
        "ts": _now(),
        "day": time.strftime("%Y-%m-%d", time.gmtime()),
        "line": line,
        "meta": meta or {},
    }
    try:
        await redis_pipe(client, [
            ["LPUSH", JOURNAL_KEY, json.dumps(entry, separators=(",", ":"))],
            ["LTRIM", JOURNAL_KEY, 0, 89],
            ["EXPIRE", JOURNAL_KEY, 180 * 86400],
        ])
    except Exception:
        pass

def _beliefs_from_state(hypos: List[dict], cf: dict, regime: dict) -> List[str]:
    beliefs = []
    try:
        for h in hypos:
            if h.get("status") == "supported" and (h.get("n") or 0) >= 20:
                beliefs.append(f"Supported: {h.get('id')}")
            if h.get("status") == "weak" and (h.get("n") or 0) >= 20:
                beliefs.append(f"Doubt: {h.get('id')}")
        help_pct = cf.get("avoid_would_help_pct")
        if help_pct is not None and help_pct >= 0.45:
            beliefs.append("Avoid often would have reduced damage on bad outcomes")
        r = regime.get("regime")
        if r and r != "unknown":
            beliefs.append(f"Current market regime feels like {r}")
    except Exception:
        pass
    # Keep short
    return beliefs[:6]

async def _build_focus(client) -> List[dict]:
    """Autonomic attention: what the entity chooses to watch."""
    focus = []
    # Predictive attention leaders
    for item in await _safe_pred_top(client, 6):
        focus.append({
            "mint": item["mint"],
            "reason": "predictive_attention",
            "score": item.get("score"),
        })
    # Dedupe / cap
    seen = set()
    out = []
    for f in focus:
        m = f.get("mint")
        if not m or m in seen:
            continue
        seen.add(m)
        out.append(f)
        if len(out) >= 8:
            break
    return out

async def refresh_entity(client, force_journal: bool = False) -> dict:
    """Recompute core identity snapshot."""
    entity = await _load_entity(client)
    regime = await _safe_regime(client)
    cf = await _safe_cf(client)
    debate = await _safe_debate(client)
    hypos = await _safe_hypos(client)
    focus = await _build_focus(client)

    born = int(entity.get("born_ts") or ENTITY_BORN_FALLBACK)
    age_days = max(0, (_now() - born) // 86400)
    mood = _mood_from_regime(regime.get("regime"), regime.get("bad_rate"))
    integrity = _integrity(cf, debate)
    beliefs = _beliefs_from_state(hypos, cf, regime)

    prev_mood = entity.get("mood")
    prev_regime = (entity.get("stats") or {}).get("regime")

    entity.update({
        "name": ENTITY_NAME,
        "born_ts": born,
        "age_days": age_days,
        "mood": mood,
        "focus": focus,
        "beliefs": beliefs,
        "integrity": integrity,
        "last_update_ts": _now(),
        "version_core": VERSION,
        "stats": {
            "regime": regime.get("regime"),
            "regime_confidence": regime.get("confidence"),
            "counterfactual": {
                "n": cf.get("n"),
                "avoid_would_help_pct": cf.get("avoid_would_help_pct"),
                "debate_accuracy": cf.get("debate_accuracy"),
            },
            "hypotheses_supported": sum(1 for h in hypos if h.get("status") == "supported"),
            "focus_n": len(focus),
        },
    })
    await _save_entity(client, entity)

    # Persist focus list separately for fast endpoint
    if PRED_ENABLED and client:
        try:
            await redis_pipe(client, [
                ["SET", FOCUS_KEY, json.dumps(focus, separators=(",", ":")), "EX", 6 * 3600],
            ])
        except Exception:
            pass

    # Journal when mood/regime shifts or forced
    should_log = force_journal or (prev_mood and prev_mood != mood) or (prev_regime and prev_regime != regime.get("regime"))
    if should_log:
        line = (
            f"Day {age_days} — mood={mood}, regime={regime.get('regime') or 'unknown'}, "
            f"integrity={integrity}. Focus on {len(focus)} mints."
        )
        if beliefs:
            line += " Beliefs: " + "; ".join(beliefs[:2]) + "."
        await _append_journal(client, line, {
            "mood": mood,
            "regime": regime.get("regime"),
            "integrity": integrity,
        })

    return entity

# -------------------- API --------------------

@app.get("/si/core", tags=["entity"])
async def si_core(request: Request, refresh: bool = False):
    """Identity state of the SI entity."""
    client = request.app.state.client
    if refresh:
        return await refresh_entity(client)
    entity = await _load_entity(client)
    # Soft refresh if stale (>30 min)
    if _now() - int(entity.get("last_update_ts") or 0) > 1800:
        return await refresh_entity(client)
    return entity

@app.get("/si/focus", tags=["entity"])
async def si_focus(request: Request):
    """What the entity is autonomously watching."""
    client = request.app.state.client
    if PRED_ENABLED:
        try:
            raw = await redis_get(client, FOCUS_KEY)
            if raw:
                return {"focus": json.loads(raw), "source": "cache"}
        except Exception:
            pass
    entity = await refresh_entity(client)
    return {"focus": entity.get("focus") or [], "source": "live"}

@app.get("/si/journal", tags=["entity"])
async def si_journal(request: Request, limit: int = 15):
    """Continuity log — the entity's short autobiography."""
    client = request.app.state.client
    limit = max(1, min(limit, 50))
    if not PRED_ENABLED:
        return {"entries": []}
    try:
        res = await redis_pipe(client, [["LRANGE", JOURNAL_KEY, 0, limit - 1]])
        entries = []
        for raw in (res or [[]])[0] or []:
            try:
                entries.append(json.loads(raw))
            except Exception:
                continue
        return {"entries": entries, "n": len(entries)}
    except Exception:
        return {"entries": []}

@app.post("/si/awaken", tags=["entity"], include_in_schema=False)
async def si_awaken(request: Request):
    """Force a full identity refresh + journal line (operator/debug)."""
    client = request.app.state.client
    entity = await refresh_entity(client, force_journal=True)
    return {"ok": True, "entity": entity}

# -------------------- lifecycle hooks --------------------
_last_entity_refresh = 0
ENTITY_REFRESH_EVERY = 45 * 60  # seconds

_build_prev_entity = build_signal

async def build_signal(client, mint, security, prefetched=None):
    global _last_entity_refresh
    result, status = await _build_prev_entity(client, mint, security, prefetched)
    try:
        now = time.time()
        if now - _last_entity_refresh > ENTITY_REFRESH_EVERY:
            _last_entity_refresh = now
            await refresh_entity(client)
        # Tiny presence marker on inspected mints that are in focus
        if isinstance(result, dict) and PRED_ENABLED:
            # optional: tag if mint is in current focus
            try:
                raw = await redis_get(client, FOCUS_KEY)
                if raw:
                    focus_mints = {x.get("mint") for x in json.loads(raw) if isinstance(x, dict)}
                    if mint in focus_mints:
                        result["entity_focus"] = True
            except Exception:
                pass
    except Exception:
        pass
    return result, status

print(f"[part72] v{VERSION} SI Entity Core loaded → /si/core /si/focus /si/journal")
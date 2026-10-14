# ---------- v2.48: Self-Generated Hypotheses + Market Regime Detector ----------
VERSION = "2.48.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Dict, Any, List, Optional
from collections import Counter

# =========================
# Market Regime Detector
# =========================
REGIME_KEY = "regime:current"
REGIME_HISTORY = "regime:history"
REGIME_TTL = 48 * 3600

async def _compute_regime(client) -> Dict[str, Any]:
    """Infer a light market regime from recent track-record + community pressure."""
    if not PRED_ENABLED or not client:
        return {"regime": "unknown", "confidence": 0.0}

    try:
        # Use recent outcomes if available
        res = await redis_pipe(client, [["LRANGE", "recent", 0, 39]])
        items = (res or [[]])[0] or []
        bad = 0
        total = 0
        avoids = 0
        for raw in items:
            try:
                d = json.loads(raw)
                total += 1
                if d.get("bad_outcome"):
                    bad += 1
                if d.get("verdict") == "avoid":
                    avoids += 1
            except Exception:
                continue

        if total < 8:
            return {"regime": "unknown", "confidence": 0.2, "n": total}

        bad_rate = bad / total
        avoid_rate = avoids / total

        if bad_rate >= 0.70 and avoid_rate >= 0.45:
            regime, conf = "rug_wave", 0.75
        elif bad_rate >= 0.55:
            regime, conf = "risk_off", 0.65
        elif bad_rate <= 0.30 and avoid_rate <= 0.25:
            regime, conf = "risk_on", 0.60
        elif total >= 15 and bad_rate <= 0.40:
            regime, conf = "calm", 0.55
        else:
            regime, conf = "mixed", 0.45

        return {
            "regime": regime,
            "confidence": conf,
            "n": total,
            "bad_rate": round(bad_rate, 3),
            "avoid_rate": round(avoid_rate, 3),
            "ts": int(time.time()),
        }
    except Exception:
        return {"regime": "unknown", "confidence": 0.0}

async def get_regime(client) -> Dict[str, Any]:
    if not PRED_ENABLED or not client:
        return {"regime": "unknown"}
    try:
        raw = await redis_get(client, REGIME_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    regime = await _compute_regime(client)
    try:
        await redis_pipe(client, [
            ["SET", REGIME_KEY, json.dumps(regime), "EX", REGIME_TTL],
            ["LPUSH", REGIME_HISTORY, json.dumps(regime)],
            ["LTRIM", REGIME_HISTORY, 0, 47],
        ])
    except Exception:
        pass
    return regime

@app.get("/regime", tags=["experimental"])
async def market_regime(request: Request):
    client = request.app.state.client
    return await get_regime(client)

# =========================
# Self-Generated Hypotheses
# =========================
HYPO_KEY = "hypo:active"
HYPO_LOG = "hypo:log"
HYPO_TTL = 30 * 24 * 3600

# Built-in hypothesis templates (system proposes, then tracks)
HYPOTHESIS_TEMPLATES = [
    {
        "id": "pred_attn_high_risk",
        "claim": "If predictive_score >= 10 and risk_score >= 40 then bad outcome rate rises",
        "when": lambda r: (r.get("community") or {}).get("predictive_score", 0) >= 10 and float(r.get("risk_score") or 0) >= 40,
    },
    {
        "id": "debate_split_danger",
        "claim": "If debate agreement < 0.55 and verdict != avoid then higher failure risk",
        "when": lambda r: (r.get("debate") or {}).get("agreement", 1) < 0.55 and ((r.get("decision") or {}).get("verdict") or r.get("verdict")) != "avoid",
    },
    {
        "id": "causal_attention_then_shift",
        "claim": "Attention spike followed by community_shift within same chain predicts stress",
        "when": lambda r: "attention_spike" in ((r.get("causal") or {}).get("recent") or []) and "community_shift" in ((r.get("causal") or {}).get("recent") or []),
    },
    {
        "id": "regime_rug_wave_boost",
        "claim": "During rug_wave regime, caution should be treated closer to avoid",
        "when": lambda r: True,  # applied via regime, not per-token predicate only
    },
]

async def _load_hypotheses(client) -> List[dict]:
    if not PRED_ENABLED:
        return []
    try:
        raw = await redis_get(client, HYPO_KEY)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    # Seed defaults
    seed = []
    for t in HYPOTHESIS_TEMPLATES:
        seed.append({
            "id": t["id"],
            "claim": t["claim"],
            "status": "collecting",
            "n": 0,
            "bad": 0,
            "created_ts": int(time.time()),
        })
    try:
        await redis_pipe(client, [["SET", HYPO_KEY, json.dumps(seed), "EX", HYPO_TTL]])
    except Exception:
        pass
    return seed

async def _touch_hypothesis(client, hypo_id: str, bad: Optional[bool] = None):
    """Increment counters for a hypothesis when a matching token is later judged."""
    hypos = await _load_hypotheses(client)
    changed = False
    for h in hypos:
        if h["id"] == hypo_id:
            h["n"] = int(h.get("n", 0)) + 1
            if bad is True:
                h["bad"] = int(h.get("bad", 0)) + 1
            # Auto status
            if h["n"] >= 25:
                rate = h["bad"] / max(1, h["n"])
                if rate >= 0.65:
                    h["status"] = "supported"
                elif rate <= 0.35:
                    h["status"] = "weak"
                else:
                    h["status"] = "mixed"
            changed = True
            break
    if changed:
        try:
            await redis_pipe(client, [["SET", HYPO_KEY, json.dumps(hypos), "EX", HYPO_TTL]])
        except Exception:
            pass

def _match_hypotheses(result: dict) -> List[str]:
    matched = []
    for t in HYPOTHESIS_TEMPLATES:
        try:
            if t["id"] == "regime_rug_wave_boost":
                continue
            if t["when"](result):
                matched.append(t["id"])
        except Exception:
            continue
    return matched

@app.get("/hypotheses", tags=["experimental"])
async def list_hypotheses(request: Request):
    client = request.app.state.client
    hypos = await _load_hypotheses(client)
    return {"hypotheses": hypos}

# =========================
# Integrate into pipeline
# =========================
_build_prev_si = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_si(client, mint, security, prefetched)

    try:
        # Regime context
        regime = await get_regime(client)
        if regime and regime.get("regime") not in (None, "unknown"):
            result["regime"] = {
                "name": regime.get("regime"),
                "confidence": regime.get("confidence"),
            }
            # Soft adjustment note during rug_wave
            if regime.get("regime") == "rug_wave" and result.get("decision"):
                d = dict(result["decision"])
                unknowns = list(d.get("unknowns") or [])
                note = "Market regime: rug_wave — treat caution more carefully"
                if note not in unknowns:
                    unknowns.append(note)
                d["unknowns"] = unknowns
                result["decision"] = d

        # Hypothesis tags on this signal
        matched = _match_hypotheses(result)
        if matched:
            result["hypotheses_matched"] = matched
            # Mark for later outcome linking
            if PRED_ENABLED:
                await redis_pipe(client, [
                    ["SET", f"hypo:pending:{mint}", json.dumps(matched), "EX", 36 * 3600],
                ])
    except Exception:
        pass

    return result, status

print(f"[part66] v{VERSION} Hypotheses + Market Regime loaded")
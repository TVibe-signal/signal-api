# ---------- v2.54: Omni · Live CF · Time-to-Death · Pre-rug ----------
VERSION = "2.54.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Any, Dict, Optional, List

# -------------------- Live Counterfactual --------------------

async def live_counterfactual(client, result: dict) -> dict:
    """Per-mint: what if avoid / what if debate-meta had been trusted."""
    out = {
        "available": False,
        "note": "Need cohort stats",
    }
    try:
        verdict = (result.get("decision") or {}).get("verdict") or result.get("verdict")
        risk = float(result.get("risk_score") or 0)
        deb = result.get("debate") or {}
        meta = deb.get("meta_verdict_weighted") or deb.get("meta_verdict")
        dna = result.get("dna")

        # Global CF stats
        cf = {}
        if "counterfactual_summary" in globals():
            cf = await counterfactual_summary(client) or {}

        # DNA cohort
        dna_info = {}
        if dna and "dna_risk" in globals():
            dna_info = await dna_risk(client, dna) or {}

        # Track-record context already on signal
        ctx = result.get("track_record_context") or {}
        cohort_bad = ctx.get("bad_outcome_rate")
        cohort_n = ctx.get("n") or 0

        expected_bad = cohort_bad
        if dna_info.get("bad_rate") is not None and (dna_info.get("n") or 0) >= 8:
            # blend DNA with score cohort
            if cohort_bad is not None:
                expected_bad = 0.5 * float(cohort_bad) + 0.5 * float(dna_info["bad_rate"])
            else:
                expected_bad = float(dna_info["bad_rate"])

        avoid_helps = None
        if expected_bad is not None and verdict != "avoid":
            avoid_helps = round(float(expected_bad), 3)

        debate_agree = None
        if meta and verdict and meta != verdict:
            debate_agree = {
                "decision": verdict,
                "debate_meta": meta,
                "disagreement": True,
            }

        out = {
            "available": expected_bad is not None,
            "expected_bad_rate": round(float(expected_bad), 3) if expected_bad is not None else None,
            "cohort_n": cohort_n,
            "dna_n": dna_info.get("n"),
            "if_switch_to_avoid": {
                "applies": verdict != "avoid",
                "estimated_risk_avoided": avoid_helps,
                "meaning": "Approx share of similar cases that ended badly — not a guarantee",
            },
            "debate_vs_decision": debate_agree,
            "global_avoid_would_help_pct": cf.get("avoid_would_help_pct"),
        }
    except Exception:
        pass
    return out

# -------------------- Time-to-Death (hazard sketch) --------------------

def estimate_time_to_death(result: dict) -> dict:
    """
    Heuristic hours-to-bad under stress patterns.
    Not a clock — a risk-timed pressure score mapped to hours.
    """
    try:
        risk = float(result.get("risk_score") or 0)
        flags = set(result.get("flags") or [])
        liq = float(result.get("liquidity_usd") or 0)
        age_m = float(result.get("pair_age_minutes") or 0)
        attn = (result.get("community") or {}).get("attention") or {}
        trap = bool(result.get("attention_trap"))
        genetic = bool(result.get("genetic_risk"))

        pressure = risk
        if "brand_new_pair" in flags or "very_new_pair" in flags:
            pressure += 12
        if "very_low_liquidity" in flags or liq < 30000:
            pressure += 15
        if "extreme_volume_spike" in flags or "dump_risk" in flags:
            pressure += 10
        if trap:
            pressure += 8
        if genetic:
            pressure += 8
        if attn.get("1h", 0) >= 10:
            pressure += 5
        if age_m and age_m < 180:
            pressure += 6

        pressure = max(0, min(120, pressure))
        # Map pressure → expected horizon (hours); higher pressure = faster danger
        if pressure >= 85:
            hours, band = 2.0, "imminent"
        elif pressure >= 70:
            hours, band = 6.0, "short"
        elif pressure >= 50:
            hours, band = 18.0, "same_day"
        elif pressure >= 30:
            hours, band = 48.0, "extended"
        else:
            hours, band = 72.0, "slow"

        return {
            "pressure": round(pressure, 1),
            "eta_hours": hours,
            "band": band,
            "note": "Heuristic stress clock from flags/liquidity/attention — not prophecy",
        }
    except Exception:
        return {"pressure": None, "eta_hours": None, "band": "unknown"}

# -------------------- Pre-rug pattern library --------------------
PRERUG_KEY = "prerug:patterns"

PRE_RUG_PATTERNS = [
    {
        "id": "new_low_liq_spike",
        "when": lambda r: (
            "brand_new_pair" in set(r.get("flags") or [])
            and float(r.get("liquidity_usd") or 0) < 40000
            and "extreme_volume_spike" in set(r.get("flags") or [])
        ),
        "label": "New pair + low liq + volume spike",
    },
    {
        "id": "attention_trap_dump",
        "when": lambda r: bool(r.get("attention_trap")),
        "label": "Attention trap pattern",
    },
    {
        "id": "genetic_cluster_fail",
        "when": lambda r: bool(r.get("genetic_risk")),
        "label": "DNA cohort historically toxic",
    },
    {
        "id": "debate_split_high_risk",
        "when": lambda r: (
            float((r.get("debate") or {}).get("agreement") or 1) < 0.55
            and float(r.get("risk_score") or 0) >= 45
        ),
        "label": "Debate split under elevated risk",
    },
]

def match_prerug(result: dict) -> List[dict]:
    hits = []
    for p in PRE_RUG_PATTERNS:
        try:
            if p["when"](result):
                hits.append({"id": p["id"], "label": p["label"]})
        except Exception:
            continue
    return hits

async def prerug_touch(client, pattern_ids: List[str], bad: Optional[bool] = None):
    if not PRED_ENABLED or not client or not pattern_ids:
        return
    try:
        cmds = []
        for pid in pattern_ids:
            cmds.append(["HINCRBY", PRERUG_KEY, f"{pid}:n", 1])
            if bad is True:
                cmds.append(["HINCRBY", PRERUG_KEY, f"{pid}:bad", 1])
        cmds.append(["EXPIRE", PRERUG_KEY, 90 * 86400])
        await redis_pipe(client, cmds)
    except Exception:
        pass

async def prerug_stats(client) -> dict:
    if not PRED_ENABLED or not client:
        return {}
    try:
        raw = await redis_pipe(client, [["HGETALL", PRERUG_KEY]])
        h = to_dict((raw or [{}])[0] or {})
        stats = {}
        ids = set()
        for k in h:
            if ":" in k:
                ids.add(k.split(":")[0])
        for pid in ids:
            n = int(float(h.get(f"{pid}:n", 0) or 0))
            b = int(float(h.get(f"{pid}:bad", 0) or 0))
            stats[pid] = {"n": n, "bad": b, "bad_rate": round(b / n, 3) if n else None}
        return stats
    except Exception:
        return {}

# -------------------- Omni facade --------------------

async def build_omni(client, mint: str) -> dict:
    sig, status = await build_signal(client, mint, True)
    if not isinstance(sig, dict):
        return {"mint": mint, "error": "signal_failed", "status": status}

    cf = await live_counterfactual(client, sig)
    ttd = estimate_time_to_death(sig)
    prerug = match_prerug(sig)
    for p in prerug:
        await prerug_touch(client, [p["id"]], bad=None)

    entity_bit = {}
    try:
        if "refresh_entity" in globals() or " _load_entity" in globals():
            # cheap load
            if PRED_ENABLED:
                raw = await redis_get(client, "si:entity:core")
                if raw:
                    ent = json.loads(raw)
                    entity_bit = {
                        "mood": ent.get("mood"),
                        "integrity": ent.get("integrity"),
                        "age_days": ent.get("age_days"),
                    }
    except Exception:
        pass

    would_change = []
    dec = sig.get("decision") or {}
    if dec.get("blockers"):
        would_change.append("Clear blockers: " + ", ".join(map(str, dec.get("blockers")[:3])))
    if sig.get("attention_trap"):
        would_change.append("Attention trap clears if attention falls and liquidity stabilizes")
    if ttd.get("band") in ("imminent", "short"):
        would_change.append("Time pressure high — wait for liquidity/age improvement")

    return {
        "mint": mint,
        "token": sig.get("token"),
        "decision": {
            "verdict": dec.get("verdict") or sig.get("verdict"),
            "risk_score": sig.get("risk_score"),
            "blockers": dec.get("blockers"),
            "cautions": dec.get("cautions"),
            "positives": dec.get("positives"),
            "unknowns": dec.get("unknowns"),
        },
        "community": sig.get("community"),
        "debate": sig.get("debate"),
        "regime": sig.get("regime"),
        "causal": sig.get("causal"),
        "dna": sig.get("dna"),
        "genetic_risk": sig.get("genetic_risk"),
        "attention_trap": sig.get("attention_trap"),
        "swarm": sig.get("swarm"),
        "entity": entity_bit,
        "entity_focus": sig.get("entity_focus"),
        "counterfactual": cf,
        "time_to_death": ttd,
        "pre_rug": prerug,
        "would_change_my_mind": would_change,
        "summary": sig.get("summary"),
        "version": VERSION,
    }

@app.get("/omni", tags=["product"])
async def omni_endpoint(request: Request, mint: str):
    """One-call God endpoint for agents."""
    wait = rate_limited(client_ip(request), cost=4)
    if wait:
        raise too_many(wait)
    if not MINT_RE.match(mint):
        raise HTTPException(400, "Invalid mint")
    client = request.app.state.client
    return await build_omni(client, mint)

@app.get("/prerug/stats", tags=["experimental"])
async def prerug_stats_endpoint(request: Request):
    return {"patterns": await prerug_stats(request.app.state.client)}

# Attach CF + TTD onto normal signal too (light)
_build_prev_omni = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_omni(client, mint, security, prefetched)
    try:
        if isinstance(result, dict):
            result["time_to_death"] = estimate_time_to_death(result)
            # live CF only when security full path (heavier)
            if security:
                result["counterfactual"] = await live_counterfactual(client, result)
            hits = match_prerug(result)
            if hits:
                result["pre_rug"] = hits
    except Exception:
        pass
    return result, status

# Outcome → pre-rug stats
_prev_on_outcome2 = globals().get("on_outcome_for_si")

async def on_outcome_for_si(client, mint: str, bad_outcome: bool):
    if _prev_on_outcome2:
        try:
            await _prev_on_outcome2(client, mint, bad_outcome)
        except Exception:
            pass
    try:
        # Best-effort: if pending hypo/debate exists we already score; prerug needs last patterns — skip if unknown
        pass
    except Exception:
        pass

print(f"[part74] v{VERSION} Omni + Live CF + TTD + Pre-rug loaded")
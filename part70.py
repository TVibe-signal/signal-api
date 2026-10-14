# ---------- v2.51: SI Advanced Pack (1-5) ----------
VERSION = "2.51.0"
app.version = VERSION
app.openapi_schema = None

import hashlib
import json
import time
from typing import Any, Dict, List, Optional

# =========================
# 4) Signal DNA
# =========================

def compute_signal_dna(result: dict) -> str:
    """Compact fingerprint of risk shape + regime + community + causal."""
    try:
        risk = int(float(result.get("risk_score") or 0) // 10)
        reg = ((result.get("regime") or {}).get("name") or "unk")[:12]
        dom = ((result.get("community") or {}).get("conviction") or {}).get("dominant") or "na"
        causal = ",".join(((result.get("causal") or {}).get("recent") or [])[:3])
        flags = ",".join(sorted((result.get("flags") or [])[:6]))
        raw = f"{risk}|{reg}|{dom}|{causal}|{flags}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]
    except Exception:
        return "unknown"

DNA_STATS = "dna:stats"  # hash field dna -> n / bad

async def _dna_touch(client, dna: str, bad: Optional[bool] = None):
    if not PRED_ENABLED or not client or not dna or dna == "unknown":
        return
    try:
        cmds = [["HINCRBY", DNA_STATS, f"{dna}:n", 1]]
        if bad is True:
            cmds.append(["HINCRBY", DNA_STATS, f"{dna}:bad", 1])
        cmds.append(["EXPIRE", DNA_STATS, 60 * 86400])
        await redis_pipe(client, cmds)
    except Exception:
        pass

async def dna_risk(client, dna: str) -> dict:
    if not PRED_ENABLED or not client:
        return {"n": 0}
    try:
        raw = await redis_pipe(client, [["HGETALL", DNA_STATS]])
        h = to_dict((raw or [{}])[0] or {})
        n = int(h.get(f"{dna}:n", 0) or 0)
        bad = int(h.get(f"{dna}:bad", 0) or 0)
        return {
            "dna": dna,
            "n": n,
            "bad_rate": round(bad / n, 3) if n else None,
            "genetic_risk": bool(n >= 8 and bad / max(1, n) >= 0.65),
        }
    except Exception:
        return {"dna": dna, "n": 0}

# =========================
# 2) Attention-trap watchdog
# =========================
TRAP_KEY = "trap:flag:{}"  # mint -> 1

def _detect_attention_trap(result: dict) -> bool:
    """attention spike + weak liquidity / dump pressure pattern."""
    try:
        causal = (result.get("causal") or {}).get("recent") or []
        attn = (result.get("community") or {}).get("attention") or {}
        liq = float(result.get("liquidity_usd") or 0)
        flags = set(result.get("flags") or [])
        spike = "attention_spike" in causal or attn.get("1h", 0) >= 10
        fragile = liq < 50000 or "very_low_liquidity" in flags or "extreme_volume_spike" in flags
        dumpish = "heavy_selling" in flags or "whale_dumping" in flags or "dump_risk" in flags
        return bool(spike and (fragile or dumpish))
    except Exception:
        return False

# =========================
# 3) Persona Evolution
# =========================
PERSONA_ADJ = "debate:persona_adj"  # persona -> weight multiplier

async def get_persona_weights(client) -> Dict[str, float]:
    base = {"conservative": 1.0, "aggressive": 1.0, "community": 1.0, "historical": 1.0, "meta": 1.0}
    if not PRED_ENABLED or not client:
        return base
    try:
        # Prefer scored accuracy if available
        if "get_debate_leaderboard" in globals():
            board = await get_debate_leaderboard(client)
            for name, st in (board or {}).items():
                n = st.get("n") or 0
                acc = st.get("accuracy")
                if n >= 12 and acc is not None:
                    # Map accuracy to weight 0.6 .. 1.4
                    base[name] = round(0.6 + max(0.0, min(1.0, float(acc))) * 0.8, 3)
        raw = await redis_pipe(client, [["HGETALL", PERSONA_ADJ]])
        h = to_dict((raw or [{}])[0] or {})
        for k, v in h.items():
            try:
                base[k] = float(v)
            except Exception:
                pass
    except Exception:
        pass
    return base

def evolve_debate(debate: dict, weights: Dict[str, float]) -> dict:
    """Re-weight persona votes using learned weights."""
    if not debate:
        return debate
    try:
        personas = list(debate.get("personas") or [])
        votes = {"ok": 0.0, "caution": 0.0, "avoid": 0.0}
        for p in personas:
            name = p.get("persona") or ""
            conf = float(p.get("confidence") or 0.5) * float(weights.get(name, 1.0))
            v = p.get("verdict") or "caution"
            if v in votes:
                votes[v] += conf
            p = dict(p)
            p["weight"] = round(float(weights.get(name, 1.0)), 3)
        meta = max(votes, key=votes.get)
        total = sum(votes.values()) or 1.0
        out = dict(debate)
        out["votes_weighted"] = {k: round(v, 2) for k, v in votes.items()}
        out["meta_verdict_weighted"] = meta
        out["agreement_weighted"] = round(votes[meta] / total, 2)
        out["persona_weights"] = weights
        return out
    except Exception:
        return debate

# =========================
# 1) Counterfactual Engine
# =========================
CF_KEY = "cf:stats"

async def record_counterfactual(client, decision_verdict: str, debate_meta: Optional[str], bad: bool):
    """Track: what if we trusted avoid / debate meta instead."""
    if not PRED_ENABLED or not client:
        return
    try:
        cmds = [["HINCRBY", CF_KEY, "n", 1]]
        if bad:
            cmds.append(["HINCRBY", CF_KEY, "bad", 1])
        # If decision was not avoid but outcome bad → avoid would have helped
        if bad and decision_verdict and decision_verdict != "avoid":
            cmds.append(["HINCRBY", CF_KEY, "avoid_would_help", 1])
        if debate_meta:
            cmds.append(["HINCRBY", CF_KEY, "debate_n", 1])
            correct = (debate_meta == "avoid" and bad) or (debate_meta == "ok" and not bad) or (debate_meta == "caution")
            if (debate_meta == "avoid" and bad) or (debate_meta == "ok" and not bad):
                cmds.append(["HINCRBY", CF_KEY, "debate_correct", 1])
            elif debate_meta == "caution":
                cmds.append(["HINCRBYFLOAT", CF_KEY, "debate_correct", 0.5])
        cmds.append(["EXPIRE", CF_KEY, 90 * 86400])
        await redis_pipe(client, cmds)
    except Exception:
        pass

async def counterfactual_summary(client) -> dict:
    if not PRED_ENABLED or not client:
        return {}
    try:
        raw = await redis_pipe(client, [["HGETALL", CF_KEY]])
        h = to_dict((raw or [{}])[0] or {})
        n = int(float(h.get("n", 0) or 0))
        bad = int(float(h.get("bad", 0) or 0))
        help_ = int(float(h.get("avoid_would_help", 0) or 0))
        dn = int(float(h.get("debate_n", 0) or 0))
        dc = float(h.get("debate_correct", 0) or 0)
        return {
            "n": n,
            "bad": bad,
            "avoid_would_help": help_,
            "avoid_would_help_pct": round(help_ / bad, 3) if bad else None,
            "debate_accuracy": round(dc / dn, 3) if dn else None,
            "debate_n": dn,
        }
    except Exception:
        return {}

@app.get("/counterfactual", tags=["experimental"])
async def counterfactual_endpoint(request: Request):
    return await counterfactual_summary(request.app.state.client)

# =========================
# 5) Agent Swarm Memory
# =========================
SWARM_KEY = "swarm:{}"  # mint -> hash: agents / useful_yes / useful_no

async def swarm_touch(client, mint: str, agent: str, useful: Optional[str] = None):
    if not PRED_ENABLED or not client:
        return
    try:
        cmds = [
            ["HINCRBY", SWARM_KEY.format(mint), "looks", 1],
            ["SADD", SWARM_KEY.format(mint) + ":agents", agent],
            ["EXPIRE", SWARM_KEY.format(mint), 7 * 86400],
            ["EXPIRE", SWARM_KEY.format(mint) + ":agents", 7 * 86400],
        ]
        if useful == "yes":
            cmds.append(["HINCRBY", SWARM_KEY.format(mint), "yes", 1])
        elif useful == "no":
            cmds.append(["HINCRBY", SWARM_KEY.format(mint), "no", 1])
        await redis_pipe(client, cmds)
    except Exception:
        pass

async def get_swarm(client, mint: str) -> dict:
    if not PRED_ENABLED or not client:
        return {"looks": 0}
    try:
        res = await redis_pipe(client, [
            ["HGETALL", SWARM_KEY.format(mint)],
            ["SCARD", SWARM_KEY.format(mint) + ":agents"],
        ])
        h = to_dict((res or [{}, 0])[0] or {})
        agents = int((res or [None, 0])[1] or 0)
        looks = int(h.get("looks", 0) or 0)
        yes = int(h.get("yes", 0) or 0)
        no = int(h.get("no", 0) or 0)
        judged = yes + no
        return {
            "looks": looks,
            "agents": agents,
            "useful_yes": yes,
            "useful_no": no,
            "useful_rate": round(yes / judged, 3) if judged else None,
        }
    except Exception:
        return {"looks": 0}

# Patch feedback to feed swarm + reputation already handled elsewhere
_build_prev_adv = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_adv(client, mint, security, prefetched)
    try:
        if not isinstance(result, dict):
            return result, status

        # DNA
        dna = compute_signal_dna(result)
        result["dna"] = dna
        info = await dna_risk(client, dna)
        if info.get("genetic_risk"):
            result["genetic_risk"] = True
            d = dict(result.get("decision") or {})
            unknowns = list(d.get("unknowns") or [])
            note = f"Genetic risk: similar DNA failed often (n={info.get('n')}, bad_rate={info.get('bad_rate')})"
            if note not in unknowns:
                unknowns.append(note)
            d["unknowns"] = unknowns
            result["decision"] = d

        # Attention trap
        if _detect_attention_trap(result):
            result["attention_trap"] = True
            d = dict(result.get("decision") or {})
            unknowns = list(d.get("unknowns") or [])
            note = "Attention-trap pattern: rising attention + fragile liquidity/dump pressure"
            if note not in unknowns:
                unknowns.append(note)
            d["unknowns"] = unknowns
            result["decision"] = d

        # Persona evolution on debate
        deb = result.get("debate")
        if deb:
            weights = await get_persona_weights(client)
            result["debate"] = evolve_debate(deb, weights)

        # Swarm snapshot
        sw = await get_swarm(client, mint)
        if sw.get("looks", 0) > 0:
            result["swarm"] = sw

    except Exception:
        pass
    return result, status

# Feed CF + DNA on SI outcome if hook exists
_old_on_outcome = globals().get("on_outcome_for_si")

async def on_outcome_for_si(client, mint: str, bad_outcome: bool):
    if _old_on_outcome:
        try:
            await _old_on_outcome(client, mint, bad_outcome)
        except Exception:
            pass
    try:
        # Counterfactual needs last known verdict/debate — best-effort from pending debate
        raw = await redis_get(client, f"debate:pending:{mint}")
        decision_verdict = None
        debate_meta = None
        if raw:
            data = json.loads(raw)
            debate_meta = data.get("meta")
        await record_counterfactual(client, decision_verdict or "unknown", debate_meta, bad_outcome)
        # DNA: we don't store dna pending here; optional extension
    except Exception:
        pass

@app.get("/si/advanced", tags=["experimental"])
async def si_advanced(request: Request):
    client = request.app.state.client
    return {
        "counterfactual": await counterfactual_summary(client),
        "persona_weights": await get_persona_weights(client),
        "version": VERSION,
    }

print(f"[part70] v{VERSION} SI Advanced Pack loaded (DNA/trap/persona/CF/swarm)")
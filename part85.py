# ---------- v2.63: Attention Residual Fusion (AttnRes-style layer weights) ----------
VERSION = "2.63.0"
app.version = VERSION
app.openapi_schema = None

import math
from typing import Any, Dict, List, Optional, Tuple

# Softmax temperature: lower = sharper focus on strongest layer
RES_TEMP = float(os.getenv("SI_RES_TEMP", "1.25") or 1.25)
# Floor so risk layer never fully disappears
RES_RISK_FLOOR = float(os.getenv("SI_RES_RISK_FLOOR", "0.18") or 0.18)


def _softmax(scores: List[float], temp: float = 1.0) -> List[float]:
    if not scores:
        return []
    t = max(temp, 1e-6)
    m = max(scores)
    exps = [math.exp((s - m) / t) for s in scores]
    z = sum(exps) or 1.0
    return [e / z for e in exps]


def _layer_scores(result: dict) -> Dict[str, float]:
    """Heuristic pre-softmax scores — input-dependent (AttnRes idea, no neural net)."""
    decision = result.get("decision") or {}
    debate = result.get("debate") or {}
    community = result.get("community") or {}
    tr = result.get("track_record_context") or {}
    dq = result.get("data_quality") or {}
    regime = result.get("regime") or {}

    conf = float(decision.get("confidence") or dq.get("data_confidence") or 0.5)
    risk = float(result.get("risk_score") if result.get("risk_score") is not None else 50)

    # risk layer: always present; stronger when data is complete
    s_risk = 1.0 + conf * 1.2 + (0.3 if dq.get("completeness") == "full" else 0.0)

    # debate: stronger with agreement
    agr = float(debate.get("agreement_weighted") or debate.get("agreement") or 0.0)
    s_debate = 0.4 + agr * 2.0
    if debate.get("meta_verdict") or debate.get("meta_verdict_weighted"):
        s_debate += 0.3

    # historical / track-record: stronger with sample size
    n = int(tr.get("n") or 0)
    s_hist = 0.2 + min(2.0, math.sqrt(max(n, 0)) / 5.0)
    if n >= 40:
        s_hist += 0.5
    if n >= 80:
        s_hist += 0.3

    # community: stronger with conviction n
    conv = (community.get("conviction") or {}) if isinstance(community, dict) else {}
    cn = int(conv.get("n") or 0)
    attn = (community.get("attention") or {}) if isinstance(community, dict) else {}
    a24 = int(attn.get("24h") or 0)
    s_comm = 0.15 + min(1.8, math.sqrt(max(cn, 0)) / 4.0) + min(0.5, a24 / 80.0)

    # regime: light prior
    rc = float(regime.get("confidence") or 0.0)
    s_regime = 0.25 + rc * 0.8

    return {
        "risk": s_risk,
        "debate": s_debate,
        "historical": s_hist,
        "community": s_comm,
        "regime": s_regime,
    }


def _verdict_to_num(v: Optional[str]) -> float:
    v = (v or "").lower()
    if v == "ok":
        return 0.0
    if v == "caution":
        return 0.5
    if v == "avoid":
        return 1.0
    return 0.5


def _num_to_verdict(x: float) -> str:
    if x < 0.33:
        return "ok"
    if x < 0.67:
        return "caution"
    return "avoid"


def compute_attention_residuals(result: dict) -> Dict[str, Any]:
    """
    AttnRes-style fusion: each SI layer contributes with input-dependent α.
    Does NOT override hard blockers; only soft-blends advisory layers.
    """
    scores = _layer_scores(result)
    names = list(scores.keys())
    raw = [scores[k] for k in names]
    alphas = _softmax(raw, RES_TEMP)
    alpha = {k: round(a, 4) for k, a in zip(names, alphas)}

    # Enforce risk floor then re-normalize
    if alpha.get("risk", 0) < RES_RISK_FLOOR:
        deficit = RES_RISK_FLOOR - alpha["risk"]
        alpha["risk"] = RES_RISK_FLOOR
        others = [k for k in names if k != "risk"]
        mass = sum(alpha[k] for k in others) or 1.0
        for k in others:
            alpha[k] = round(alpha[k] * (1.0 - RES_RISK_FLOOR) / mass, 4)
        # fix float drift
        s = sum(alpha.values()) or 1.0
        alpha = {k: round(v / s, 4) for k, v in alpha.items()}

    decision = result.get("decision") or {}
    debate = result.get("debate") or {}
    community = result.get("community") or {}
    tr = result.get("track_record_context") or {}
    regime = result.get("regime") or {}

    v_risk = _verdict_to_num(decision.get("verdict") or result.get("verdict"))
    v_debate = _verdict_to_num(
        debate.get("meta_verdict_weighted") or debate.get("meta_verdict")
    )
    # historical: map bad_outcome_rate → avoid-ish signal
    bad = tr.get("bad_outcome_rate")
    if bad is None:
        v_hist = 0.5
    else:
        v_hist = max(0.0, min(1.0, float(bad)))
    conv = (community.get("conviction") or {}) if isinstance(community, dict) else {}
    v_comm = _verdict_to_num(conv.get("dominant"))
    # regime risk_off nudges slightly cautious
    v_reg = 0.55 if (regime.get("name") == "risk_off") else 0.45

    blended = (
        alpha["risk"] * v_risk
        + alpha["debate"] * v_debate
        + alpha["historical"] * v_hist
        + alpha["community"] * v_comm
        + alpha["regime"] * v_reg
    )
    residual_verdict = _num_to_verdict(blended)

    # Never upgrade past a hard blocker avoid
    blockers = decision.get("blockers") or []
    base = (decision.get("verdict") or result.get("verdict") or "caution").lower()
    if blockers or base == "avoid":
        residual_verdict = "avoid" if blockers else residual_verdict
        # if base avoid without blockers, keep avoid
        if base == "avoid":
            residual_verdict = "avoid"

    disagree = residual_verdict != base

    return {
        "alpha": alpha,
        "scores_raw": {k: round(scores[k], 3) for k in names},
        "blended_stress": round(blended, 4),
        "residual_verdict": residual_verdict,
        "base_verdict": base,
        "disagreement": disagree,
        "note": "Input-dependent layer weights (AttnRes-style). Advisory; decision.verdict remains primary unless you opt-in.",
        "version": VERSION,
    }


def attach_attention_residuals(result: dict) -> dict:
    if not isinstance(result, dict):
        return result
    try:
        ar = compute_attention_residuals(result)
        result["attention_residuals"] = ar
        # Optional soft hint on decision (does not replace verdict)
        dec = result.get("decision")
        if isinstance(dec, dict):
            dec = dict(dec)
            dec["residual_verdict"] = ar["residual_verdict"]
            dec["residual_alpha"] = ar["alpha"]
            if ar["disagreement"]:
                unknowns = list(dec.get("unknowns") or [])
                hint = (
                    f"Attention residual suggests {ar['residual_verdict']} "
                    f"(base={ar['base_verdict']}; α={ar['alpha']})"
                )
                if hint not in unknowns:
                    unknowns.append(hint)
                dec["unknowns"] = unknowns
            result["decision"] = dec
    except Exception:
        pass
    return result


_build_prev_res = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_res(client, mint, security, prefetched)
    try:
        if isinstance(result, dict):
            result = attach_attention_residuals(result)
    except Exception:
        pass
    return result, status


# If omni wrapper exists, enrich after it
_omni_prev = globals().get("omni_packet") or globals().get("build_omni")
if callable(_omni_prev):
    async def omni_packet(client, mint, *args, **kwargs):
        pkt = await _omni_prev(client, mint, *args, **kwargs)
        if isinstance(pkt, dict):
            # omni may nest decision at top level already
            return attach_attention_residuals(pkt)
        return pkt


@app.get("/residuals", tags=["experimental"])
async def residuals_inspect(request: Request, mint: str):
    """Compute residual fusion for one mint (runs full signal path)."""
    client = request.app.state.client
    if not mint or not MINT_RE.match(mint):
        return {"ok": False, "error": "invalid mint"}
    result, status = await build_signal(client, mint, True)
    ar = (result or {}).get("attention_residuals") if isinstance(result, dict) else None
    return {
        "ok": True,
        "mint": mint,
        "base_verdict": (result or {}).get("verdict") if isinstance(result, dict) else None,
        "attention_residuals": ar,
        "status": status,
        "version": VERSION,
    }


print(f"[part85] v{VERSION} Attention Residual Fusion loaded → signal/omni + GET /residuals")
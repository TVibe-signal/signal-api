from datetime import datetime, timezone

RULES_VERSION = "2026.11.15.a"
COMMUNITY_MIN_N = 20

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

def calc_decision_confidence(data, unknowns):
    reasons = []
    if unknowns:
        reasons.append(f"{len(unknowns)} unknowns")
    if data.get("freshness") == "stale":
        reasons.append("stale data")
    if data.get("dex_down") or data.get("gecko_down"):
        reasons.append("sources degraded: dexscreener,solana_rpc")
    if data.get("all_price_down"):
        reasons.append("no fallback for market data")
    level = "high" if not reasons else ("low" if len(reasons) >= 2 or data.get("freshness") == "stale" else "medium")
    return {"level": level, "reasons": reasons, "calibrated": False, "note": "Heuristic from data completeness and source health; not yet checked against outcomes."}

def build_community(queries):
    n = len(queries or [])
    if n < COMMUNITY_MIN_N:
        return {"conviction": {"n": n, "dominant": None, "summary": "insufficient_samples"}, "summary": f"insufficient_samples: n={n}, need >={COMMUNITY_MIN_N}", "insufficient_samples": True}
    return {"conviction": {"n": n}, "insufficient_samples": False}

def build_verdict(mint, data, calculate_action):
    unknowns = list(data.get("unknowns", []) or [])
    if data.get("price_age_s", 9999) > 600 and "price_stale" not in unknowns:
        unknowns.append("price_stale")
    if data.get("dex_down") and data.get("gecko_down") and data.get("jupiter_down") and "price_source_all_down" not in unknowns:
        unknowns.append("price_source_all_down")
    if data.get("exit_not_checked") and "Exit cost not checked yet (use check_exit)" not in unknowns:
        unknowns.append("Exit cost not checked yet (use check_exit)")

    confidence = calc_decision_confidence(data, unknowns)
    base_verdict = calculate_action(data)

    must_review = (
        confidence["level"] == "low"
        or data.get("freshness") == "stale"
        or data.get("price_age_s", 0) > 600
        or "price_source_all_down" in unknowns
        or data.get("data_confidence", 1.0) < 0.70
    )

    if must_review:
        action = "review"
        filter_pass = False
        filter_pass_strict = False
        valid_for_s = 30
    else:
        action = base_verdict
        filter_pass = (base_verdict == "ok")
        filter_pass_strict = (filter_pass and confidence["level"] == "high")
        valid_for_s = 360

    asset_class = data.get("asset_class", "memecoin")
    holder_weight = 0 if asset_class == "major" else 0.25
    buy_pressure_weight = 0 if asset_class == "major" else 0.15

    return {
        "verdict": base_verdict,
        "action": action,
        "filter": {"pass": filter_pass, "pass_strict": filter_pass_strict, "live_verdict": base_verdict, "pass_note": "pass means live verdict is ok and no blocker. pass_strict means also high confidence + fresh data. Not a guarantee."},
        "unknowns": unknowns,
        "decision": {"verdict": base_verdict, "blockers": data.get("blockers", []), "cautions": data.get("cautions", []), "unknowns": unknowns, "valid_for_s": valid_for_s},
        "decision_confidence": confidence,
        "data_age_s": data.get("price_age_s"),
        "valid_for_s": valid_for_s,
        "expires_at": _now_iso(),
        "rules_version": RULES_VERSION,
        "weights": {"holder_weight": holder_weight, "buy_pressure_weight": buy_pressure_weight, "asset_class": asset_class},
    }

def build_evidence_counts(observations, inferences, unknowns):
    return {"observations": len(observations or []), "inferences": len(inferences or []), "unverified_flags": 0, "unknowns": len(unknowns or [])}
# part125.py - Phase B filter contract for agents / desks (v2.99.2, reviewed)
# One stable block on every signal: filter.pass, policy, reasons, reading_order.
# Does not change underlying verdict logic - only packages it for downstream gates.
# Review fix vs v2.99.0: filter.pass=true could read as "safe". The block now carries the calibrated history
# (calibrated{p_bad_24h_pct, ci95_pct, based_on_n}) and a pass_note that says what pass means.
# Policies: default | strict | research (strict also fails on shadow flags, sell-sim friction and an open circuit).
# Loader: after part124, before part7.
import os
from typing import Any, Dict, List, Optional

VERSION = "2.99.2"
app.version = VERSION
app.openapi_schema = None

_DEFAULT_POLICY = (os.environ.get("FILTER_DEFAULT_POLICY") or "default").strip().lower()
if _DEFAULT_POLICY not in ("default", "strict", "research"):
    _DEFAULT_POLICY = "default"


def _verdict_of(body: dict) -> str:
    dec = body.get("decision") if isinstance(body.get("decision"), dict) else {}
    return str(dec.get("verdict") or body.get("verdict") or "unknown").lower()


def build_filter_block(body: dict, policy: Optional[str] = None) -> dict:
    pol = (policy or _DEFAULT_POLICY).lower()
    if pol not in ("default", "strict", "research"):
        pol = "default"
    v = _verdict_of(body)
    dec = body.get("decision") if isinstance(body.get("decision"), dict) else {}
    blockers = list(dec.get("blockers") or [])
    cautions = list(dec.get("cautions") or [])
    unknowns = list(dec.get("unknowns") or [])
    reasons: List[str] = []
    fail = False

    if pol == "research":
        if v != "ok":
            reasons.append("research: live verdict=%s" % v)
    else:
        if v != "ok":
            fail = True
            reasons.append("live verdict=%s" % v)
        if blockers:
            fail = True
            reasons.append("blockers=%d" % len(blockers))

    shadow = body.get("shadow_avoid") if isinstance(body.get("shadow_avoid"), dict) else {}
    sim = body.get("sim") if isinstance(body.get("sim"), dict) else {}
    stress = body.get("system_stress") if isinstance(body.get("system_stress"), dict) else {}
    if pol == "strict":
        if shadow.get("would_flag_avoid"):
            fail = True
            reasons.append("shadow_avoid would_flag_avoid (%s)" % ",".join(shadow.get("rules_hit") or [])[:80])
        if sim.get("honeypot_risk_heuristic"):
            fail = True
            reasons.append("sim.honeypot_risk_heuristic")
        if sim.get("sell_ok") is False:
            fail = True
            reasons.append("sim.sell_ok=false")
        if stress.get("state") == "open":
            fail = True
            reasons.append("system_stress=open")

    passed = True if pol == "research" else (not fail)

    cal = body.get("calibrated_risk") if isinstance(body.get("calibrated_risk"), dict) else {}
    calibrated = None
    if cal:
        calibrated = {"p_bad_24h_pct": cal.get("p_bad_24h_pct"), "ci95_pct": cal.get("ci95_pct"),
                      "based_on_n": cal.get("based_on_n"), "base_rate_pct": cal.get("base_rate_pct")}
    if pol == "research":
        pass_note = "research policy never gates: pass is always true. Read the reasons only."
    elif passed:
        pass_note = "pass means the live verdict is ok and no blocker was found. It is not a guarantee."
        if calibrated and calibrated.get("p_bad_24h_pct") is not None:
            pass_note += " Similar past verdicts: %s%% ended badly within 24h (n=%s)." % (
                calibrated["p_bad_24h_pct"], calibrated.get("based_on_n"))
    else:
        pass_note = "pass is false: see reasons."

    return {
        "pass": passed,
        "policy": pol,
        "pass_note": pass_note,
        "live_verdict": v,
        "reasons": reasons[:12],
        "blockers_n": len(blockers),
        "cautions_n": len(cautions),
        "unknowns_n": len(unknowns),
        "calibrated": calibrated,
        "valid_for_s": dec.get("valid_for_s") or body.get("valid_for_s"),
        "system_stress": stress.get("state"),
        "sim_sell_ok": sim.get("sell_ok"),
        "shadow_would_avoid": shadow.get("would_flag_avoid"),
        "reading_order": ["filter.pass", "filter.reasons", "filter.calibrated", "decision.verdict", "decision.blockers",
                          "decision.cautions", "decision.unknowns", "sim", "system_stress"],
        "policies": {
            "default": "pass only if live verdict is ok (and no blockers)",
            "strict": "default + fail on shadow_avoid / sim honeypot-ish / circuit open",
            "research": "always pass=true; reasons only - do not gate size on this policy",
        },
        "disclaimer": "Heuristic filter for agents. Not financial advice. Not a guarantee against rugs or honeypots.",
        "version": VERSION,
    }


def attach_filter(body: dict, policy: Optional[str] = None) -> dict:
    if isinstance(body, dict):
        body["filter"] = build_filter_block(body, policy)
    return body


_build_prev_125 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    policy = kwargs.pop("filter_policy", None)
    res = await _build_prev_125(client, mint, security, *args, **kwargs)
    try:
        body = res[0] if isinstance(res, tuple) else res
        if isinstance(body, dict):
            attach_filter(body, policy)
        return res
    except Exception as e:
        print("[part125] filter:", e)
        return res


@app.get("/filter/policies", tags=["agents"], include_in_schema=False)
async def filter_policies():
    return {
        "version": VERSION,
        "default_policy": _DEFAULT_POLICY,
        "policies": {
            "default": "Gate: pass iff live verdict == ok and no blockers.",
            "strict": "Gate: default + shadow_avoid.would_flag_avoid + sim honeypot-ish + circuit open.",
            "research": "Never gate (pass always true). Use for analysis only.",
        },
        "env": "FILTER_DEFAULT_POLICY=default|strict|research",
        "on_signal": "Every /omni and /signal includes a filter{} block.",
        "note": "Strict is for desks that want fewer false comforts; expect a lower pass rate.",
    }


print("[part125] v%s filter contract (with calibrated history) -> filter.* on signal; GET /filter/policies" % VERSION)

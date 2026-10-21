# part125.py — Phase B filter contract for agents / desks (v2.99.0)
# One stable block on every signal: filter.pass, policy, reasons, reading_order.
# Does not change underlying verdict logic — only packages it for downstream gates.
# Optional query later: policy=default|strict|research (strict uses shadow flags only as annotate unless enabled).
# Loader: after part124, before part7 → ("part125.py", 0, "SKIP"),
import os
from typing import Any, Dict, List, Optional

VERSION = "2.99.0"
app.version = VERSION
app.openapi_schema = None

# default policy: pass only when live verdict is ok (caution/avoid fail the gate)
# strict: also fail when shadow_avoid.would_flag_avoid or sim.honeypot_risk_heuristic
# research: always pass=True but fill reasons (never gate)
_DEFAULT_POLICY = (os.environ.get("FILTER_DEFAULT_POLICY") or "default").strip().lower()
if _DEFAULT_POLICY not in ("default", "strict", "research"):
    _DEFAULT_POLICY = "default"


def _verdict_of(body: dict) -> str:
    dec = body.get("decision") if isinstance(body.get("decision"), dict) else {}
    v = dec.get("verdict") or body.get("verdict") or "unknown"
    return str(v).lower()


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
        # never gate — desk reads reasons only
        if v == "avoid":
            reasons.append("research: live verdict=avoid")
        elif v == "caution":
            reasons.append("research: live verdict=caution")
        elif v != "ok":
            reasons.append("research: live verdict=%s" % v)
    else:
        if v == "avoid":
            fail = True
            reasons.append("live verdict=avoid")
        elif v == "caution":
            fail = True
            reasons.append("live verdict=caution")
        elif v != "ok":
            fail = True
            reasons.append("live verdict=%s" % v)
        if blockers:
            fail = True
            reasons.append("blockers=%d" % len(blockers))

    # strict: extra shadow / sim friction (annotate + fail)
    shadow = body.get("shadow_avoid") if isinstance(body.get("shadow_avoid"), dict) else {}
    sim = body.get("sim") if isinstance(body.get("sim"), dict) else {}
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
        st = body.get("system_stress") if isinstance(body.get("system_stress"), dict) else {}
        if st.get("state") == "open":
            fail = True
            reasons.append("system_stress=open")

    if pol == "research":
        passed = True
    else:
        passed = not fail

    stress = body.get("system_stress") if isinstance(body.get("system_stress"), dict) else {}
    return {
        "pass": passed,
        "policy": pol,
        "live_verdict": v,
        "reasons": reasons[:12],
        "blockers_n": len(blockers),
        "cautions_n": len(cautions),
        "unknowns_n": len(unknowns) if not (unknowns and isinstance(unknowns[0], dict)) else len(unknowns),
        "valid_for_s": dec.get("valid_for_s") or body.get("valid_for_s"),
        "system_stress": stress.get("state"),
        "sim_sell_ok": sim.get("sell_ok"),
        "shadow_would_avoid": shadow.get("would_flag_avoid"),
        "reading_order": [
            "filter.pass",
            "filter.reasons",
            "decision.verdict",
            "decision.blockers",
            "decision.cautions",
            "decision.unknowns",
            "sim",
            "system_stress",
        ],
        "policies": {
            "default": "pass only if live verdict is ok (and no blockers)",
            "strict": "default + fail on shadow_avoid / sim honeypot-ish / circuit open",
            "research": "always pass=true; reasons only — do not gate size on this policy",
        },
        "disclaimer": "Heuristic filter for agents. Not financial advice. Not a guarantee against rugs or honeypots.",
        "version": VERSION,
    }


def attach_filter(body: dict, policy: Optional[str] = None) -> dict:
    if not isinstance(body, dict):
        return body
    body["filter"] = build_filter_block(body, policy)
    return body


_build_prev_125 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    # optional policy from kwargs if callers pass it
    policy = kwargs.pop("filter_policy", None) if isinstance(kwargs, dict) else None
    res = await _build_prev_125(client, mint, security, *args, **kwargs)
    try:
        body = res[0] if isinstance(res, tuple) else res
        if isinstance(body, dict):
            attach_filter(body, policy)
        return res
    except Exception as e:
        print("[part125] filter:", e)
        return res


# If /omni exists as a route that does not always go through final build_signal wrappers,
# middleware-style: patch JSON after the fact is hard; document that build_signal path is source of truth.

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
        "on_signal": "Every /omni (via build_signal) includes filter{} block.",
        "note": "Strict is for desks that want fewer false comforts; expect lower pass rate.",
    }


print("[part125] v%s Phase B filter contract → filter.* on signal; GET /filter/policies" % VERSION)
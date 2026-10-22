# part127.py — Phase C cost & reliability surface for agents/desks (v3.0.0)
# Fair-use text, degrade hints, keep-alive, ops pointers. Does not tighten Redis beyond part124.
# Loader: after part126, before part7 → ("part127.py", 0, "SKIP"),
import os
import time
from typing import Any, Dict, Optional

VERSION = "3.0.0"
app.version = VERSION
app.openapi_schema = None

_START = time.time()
_PUBLIC = (os.environ.get("PUBLIC_BASE_URL") or "https://signal-api-24q4.onrender.com").rstrip("/")

# Soft guidance (not a hard global limiter — existing per-route limits still apply)
_FAIR = {
    "tier": "free_public",
    "guidance": {
        "burst_omni_per_min": "Keep automated omni/signal under \~20/min/IP when possible",
        "prefer": "Cache filter.pass + valid_for_s; do not poll the same mint every second",
        "upstream": "DexScreener/Gecko/RPC rate limits are outside TVibe — expect partial or 503 under load",
        "redis": "Shared free Redis: high traffic may degrade track-record writes; self-host if you need dedicated quota",
    },
    "self_host": "https://github.com/TVibe-signal/signal-api",
    "keep_alive": "GET /ping or /health every 10–14 min if on free web dyno",
    "ops": {
        "redis_meter": "/ops/redis",
        "redis_thrift": "/ops/redis-thrift",
        "circuit": "/system/circuit",
        "filter_policies": "/filter/policies",
    },
}


def reliability_snapshot() -> dict:
    stress = None
    if callable(globals().get("circuit_status")):
        try:
            stress = circuit_status()
        except Exception:
            stress = None
    return {
        "version": VERSION,
        "uptime_s": int(time.time() - _START),
        "system_stress": (stress or {}).get("state") if isinstance(stress, dict) else None,
        "fair_use": _FAIR,
        "sla": {
            "class": "best_effort_free",
            "no_uptime_guarantee": True,
            "partial_responses": True,
            "note": "When sources degrade, decision.unknowns and system_stress grow — treat as soft fail, not silent success.",
        },
        "agent_contract": {
            "primary": "GET /omni?mint=",
            "gate": "filter.pass (policy=default|strict|research)",
            "ttl": "filter.valid_for_s / decision.valid_for_s",
            "reading_order": (globals().get("build_filter_block") and "see filter.reading_order on each signal")
            or ["filter.pass", "decision.verdict", "decision.blockers", "sim", "system_stress"],
        },
        "disclaimer": "Heuristic. Not financial advice. Not an exchange or custody service.",
    }


@app.get("/agents/reliability", tags=["agents"], include_in_schema=False)
@app.get("/reliability", tags=["agents"], include_in_schema=False)
async def agents_reliability():
    return reliability_snapshot()


@app.get("/pricing", tags=["agents"], include_in_schema=False)
async def pricing_fair_use():
    """Honest free tier — no fake paid SKUs."""
    return {
        "version": VERSION,
        "public_instance": _PUBLIC,
        "price": "0",
        "currency": "USD",
        "model": "free_public_best_effort",
        "fair_use": _FAIR["guidance"],
        "donate_optional": "See homepage if a SOL donate address is shown — never required for API access",
        "self_host": _FAIR["self_host"],
        "paid_plans": None,
        "note": "No paywall. If you need dedicated Redis/RPC quota, run self-host or bring your own keys.",
        "reliability": "/agents/reliability",
    }


# Attach a compact reliability hint on signal payloads (non-breaking)
_build_prev_127 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_127(client, mint, security, *args, **kwargs)
    try:
        body = res[0] if isinstance(res, tuple) else res
        if isinstance(body, dict):
            body.setdefault(
                "reliability",
                {
                    "class": "best_effort_free",
                    "docs": "/agents/reliability",
                    "fair_use": "/pricing",
                },
            )
            # If circuit open, make filter/reasons already handle strict; still expose hint
            st = body.get("system_stress") if isinstance(body.get("system_stress"), dict) else {}
            if st.get("state") in ("open", "half"):
                body["reliability"]["degraded"] = True
                body["reliability"]["hint"] = "Upstream stress — prefer wait or smaller size; check /system/circuit"
        return res
    except Exception as e:
        print("[part127] ", e)
        return res


# Re-touch /omni enrichment if part126 helpers exist
_prev_enrich = globals().get("_enrich_payload")
if callable(_prev_enrich):
    def _enrich_payload(body, policy=None):  # noqa: N802
        body = _prev_enrich(body, policy)
        if isinstance(body, dict):
            body.setdefault(
                "reliability",
                {"class": "best_effort_free", "docs": "/agents/reliability", "fair_use": "/pricing"},
            )
        return body


print("[part127] v%s Phase C → GET /agents/reliability /pricing + reliability on signal" % VERSION) 
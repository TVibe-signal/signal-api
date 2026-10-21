# part117.py - slippage band helper (v2.93.1, reviewed)
# Review fixes vs v2.93.0:
#   - the old wrapper added a pseudo-unknown ("Slippage/exit: GET /exit...") to decision.unknowns of EVERY token,
#     so agents saw unknowns everywhere (and llms.txt says "unknowns non-empty -> prefer caution"). Removed.
#   - the old wrapper only touched body["exit"], which /signal never has, so it did nothing else. Removed.
#   The sell-cost band for agents now comes from part119 (`sim` on /signal and /omni).
# This file only keeps the helper, so other code that imports it keeps working.
VERSION = "2.93.1"
app.version = VERSION
app.openapi_schema = None

from typing import Any, Dict, Optional


def _slip_band(impact_pct: Optional[float]) -> Dict[str, Any]:
    if impact_pct is None:
        return {"band": "unknown", "impact_pct": None, "note": "No quote yet"}
    x = float(impact_pct)
    band = "tight" if x < 1 else "moderate" if x < 3 else "wide" if x < 8 else "extreme"
    return {"band": band, "impact_pct": round(x, 3),
            "note": "Price impact estimate from a quote - not MEV protection and not a guarantee of fill."}


def enrich_exit_payload(d: dict) -> dict:
    if not isinstance(d, dict):
        return d
    impact = None
    levels = (d.get("exit") or {}).get("levels") if isinstance(d.get("exit"), dict) else d.get("levels")
    if isinstance(levels, list) and levels and isinstance(levels[0], dict):
        for k in ("loss_vs_market_pct", "price_impact_pct", "impact_pct", "slippage_pct"):
            try:
                if levels[0].get(k) is not None:
                    impact = float(levels[0][k])
                    break
            except (TypeError, ValueError):
                pass
    d["slippage"] = _slip_band(impact)
    d["mev_protection"] = {"available": False,
                           "note": "TVibe Signal does not send transactions. MEV protection needs your wallet or router."}
    return d


globals()["enrich_exit_payload"] = enrich_exit_payload
print(f"[part117] v{VERSION} slippage band helper only (no signal changes)")

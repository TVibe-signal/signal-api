# part117.py — Exit / slippage band for agents (honest; not MEV protection)
VERSION = "2.93.0"
app.version = VERSION
app.openapi_schema = None

from typing import Any, Dict, Optional


def _slip_band(impact_pct: Optional[float]) -> Dict[str, Any]:
    if impact_pct is None:
        return {"band": "unknown", "impact_pct": None, "note": "No quote yet — call /exit"}
    x = float(impact_pct)
    if x < 1:
        band = "tight"
    elif x < 3:
        band = "moderate"
    elif x < 8:
        band = "wide"
    else:
        band = "extreme"
    return {
        "band": band,
        "impact_pct": round(x, 3),
        "note": "Price impact estimate from quote path — not MEV protection and not a guarantee of fill.",
    }


def enrich_exit_payload(d: dict) -> dict:
    if not isinstance(d, dict):
        return d
    # common field names across parts
    impact = None
    for k in ("price_impact_pct", "impact_pct", "slippage_pct", "sell_impact_pct"):
        if d.get(k) is not None:
            try:
                impact = float(d[k])
                break
            except (TypeError, ValueError):
                pass
    # nested
    for nest in ("jupiter", "quote", "sell"):
        n = d.get(nest)
        if isinstance(n, dict) and impact is None:
            for k in ("price_impact_pct", "impact_pct", "slippage_pct"):
                if n.get(k) is not None:
                    try:
                        impact = float(n[k])
                        break
                    except (TypeError, ValueError):
                        pass
    d["slippage"] = _slip_band(impact)
    d["mev_protection"] = {
        "available": False,
        "note": "TVibe Signal does not send transactions. MEV protection requires your wallet/router (e.g. Jito). We only report quote impact when /exit works.",
    }
    return d


# Wrap build_signal lightly: attach exit hint on omni-style dicts
_build_prev_117 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_117(client, mint, security, *args, **kwargs)
    try:
        body = res[0] if isinstance(res, tuple) else res
        if isinstance(body, dict):
            dec = body.get("decision") if isinstance(body.get("decision"), dict) else None
            if dec is not None:
                # point agents to /exit without claiming we already priced slippage
                unk = list(dec.get("unknowns") or [])
                hint = "Slippage/exit: GET /exit?mint=… (impact band when quote works; not MEV protection)"
                if not any("Slippage/exit" in str(u) for u in unk):
                    # only add if exit not already present on body
                    if not body.get("exit") and not body.get("slippage"):
                        unk.append(hint)
                        dec["unknowns"] = unk
            if isinstance(body.get("exit"), dict):
                body["exit"] = enrich_exit_payload(body["exit"])
        return res
    except Exception as e:
        print("[part117] ", e)
        return res


# If an /exit route exists, wrap response via middleware-style dependency is hard;
# expose helper for existing exit handlers:
globals()["enrich_exit_payload"] = enrich_exit_payload

print(f"[part117] v{VERSION} slippage band helper + exit honesty (not MEV shield)")
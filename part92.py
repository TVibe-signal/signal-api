# ---------- v2.70: Multi-horizon accuracy surface ----------
VERSION = "2.70.0"
app.version = VERSION
app.openapi_schema = None

from typing import Any, Dict, List


def build_horizons_panel(stats: dict) -> dict:
    """
    Normalize early_horizons + primary 24h into one agent-facing object.
    48h/7d appear as slots (populated when resolver has written them).
    """
    primary_h = float(stats.get("horizon_hours") or 24)
    early = stats.get("early_horizons") or {}
    late = stats.get("late_horizons") or stats.get("long_horizons") or {}

    def _pack(label: str, block: dict, hours: float) -> dict:
        if not isinstance(block, dict):
            return {"hours": hours, "n": 0, "available": False}
        n = int(block.get("n") or block.get("judged") or 0)
        by_v = block.get("by_verdict") or {}
        return {
            "hours": hours,
            "n": n,
            "available": n > 0,
            "bad_outcome_rate_pct": block.get("bad_outcome_rate_pct"),
            "by_verdict": {
                k: {
                    "n": (by_v.get(k) or {}).get("n"),
                    "bad_outcome_rate_pct": (by_v.get(k) or {}).get("bad_outcome_rate_pct"),
                }
                for k in ("ok", "caution", "avoid")
                if k in by_v
            },
            "avoid_precision_pct": (block.get("shadow_rules") or {}).get("live", {}).get("avoid_precision_pct")
                if isinstance(block.get("shadow_rules"), dict)
                else block.get("avoid_precision_pct"),
            "avoid_recall_pct": (block.get("shadow_rules") or {}).get("live", {}).get("avoid_recall_pct")
                if isinstance(block.get("shadow_rules"), dict)
                else block.get("avoid_recall_pct"),
        }

    horizons = {
        "1h": _pack("1h", early.get("1h") or {}, 1),
        "6h": _pack("6h", early.get("6h") or {}, 6),
        "24h": {
            "hours": primary_h,
            "n": int(stats.get("resolved") or 0),
            "available": True,
            "bad_outcome_definition": stats.get("bad_outcome_definition"),
            "by_verdict": {
                k: {
                    "n": ((stats.get("by_verdict") or {}).get(k) or {}).get("full", {}).get("n")
                        or ((stats.get("by_verdict") or {}).get(k) or {}).get("n"),
                    "bad_outcome_rate_pct": (
                        ((stats.get("by_verdict") or {}).get(k) or {}).get("full", {}) or {}
                    ).get("bad_outcome_rate_pct")
                    or ((stats.get("by_verdict") or {}).get(k) or {}).get("bad_outcome_rate_pct"),
                }
                for k in ("ok", "caution", "avoid")
            },
            "performance_avoid": ((stats.get("performance") or {}).get("all_tracked") or {}).get("ours_avoid"),
        },
        "48h": _pack("48h", late.get("48h") or early.get("48h") or {}, 48),
        "7d": _pack("7d", late.get("7d") or late.get("168h") or early.get("7d") or {}, 168),
    }
    return {
        "version": VERSION,
        "horizons": horizons,
        "note": (
            "1h/6h = early re-check of the same verdict; 24h = primary label. "
            "48h/7d fill when the resolver has enough long-horizon rows (n grows over time)."
        ),
        "agent_hint": "Prefer 24h rates for policy; use 1h/6h only for fast-decay intuition.",
    }


@app.get("/stats/horizons", tags=["accuracy"])
async def stats_horizons(request: Request):
    stats = globals().get("_LAST_STATS") or {}
    # Try live rebuild
    for name in ("build_stats_payload", "stats_payload", "get_track_record_stats"):
        fn = globals().get(name)
        if callable(fn):
            try:
                client = request.app.state.client
                got = await fn(client) if asyncio.iscoroutinefunction(fn) else fn(client)
                if isinstance(got, dict) and got:
                    stats = got
                    break
            except Exception:
                continue
    # Last resort: call underlying /stats endpoint function if wrapped
    return build_horizons_panel(stats if isinstance(stats, dict) else {})


print(f"[part92] v{VERSION} multi-horizon panel → GET /stats/horizons")
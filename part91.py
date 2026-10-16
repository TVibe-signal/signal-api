# ---------- v2.69: Seed cohort stats (selection-bias panel) ----------
VERSION = "2.69.0"
app.version = VERSION
app.openapi_schema = None

import math
from typing import Any, Dict, Optional


def _cohort_rates(block: dict) -> dict:
    """Normalize a by_source / performance slice into agent-friendly rates."""
    if not isinstance(block, dict):
        return {"n": 0}
    out = {"n": int(block.get("n") or block.get("judged") or 0)}
    for k in ("ok", "caution", "avoid"):
        sub = block.get(k) or {}
        if isinstance(sub, dict) and sub.get("n") is not None:
            out[k] = {
                "n": int(sub.get("n") or 0),
                "bad_outcome_rate_pct": sub.get("bad_outcome_rate_pct"),
            }
    oa = block.get("ours_avoid") or block.get("avoid_perf")
    if isinstance(oa, dict):
        out["avoid_precision_pct"] = oa.get("precision_pct")
        out["avoid_recall_pct"] = oa.get("recall_pct")
    elif block.get("avoid_precision_pct") is not None:
        out["avoid_precision_pct"] = block.get("avoid_precision_pct")
        out["avoid_recall_pct"] = block.get("avoid_recall_pct")
    return out


def build_bias_panel(stats: dict) -> dict:
    """
    Surface user vs seed cohorts so agents see selection bias explicitly.
    Uses existing by_source / performance fields when present.
    """
    by_src = stats.get("by_source") or {}
    user = _cohort_rates(by_src.get("user") or {})
    seed_parts = {}
    seed_n = 0
    for key in ("seed_boost", "seed_profile", "seed_trending", "seed_new", "seed"):
        if key in by_src:
            seed_parts[key] = _cohort_rates(by_src[key])
            seed_n += int(seed_parts[key].get("n") or 0)
    untagged = _cohort_rates(by_src.get("untagged") or {})
    panel = {
        "available": bool(by_src),
        "user": user,
        "seed": {"n": seed_n, "parts": seed_parts},
        "untagged": untagged,
        "note": (
            "user = tokens people/agents queried; seed_* = background samples. "
            "Rates on user traffic are selection-biased; compare seed cohort when n>=20."
        ),
        "ready": (user.get("n") or 0) >= 20 or seed_n >= 20,
        "version": VERSION,
    }
    return panel


@app.get("/stats/bias", tags=["accuracy"])
async def stats_bias(request: Request):
    """Selection-bias panel: user vs seed cohorts."""
    client = request.app.state.client
    stats = {}
    # Prefer existing stats builder
    for name in ("build_stats_payload", "stats_payload", "get_track_record_stats"):
        fn = globals().get(name)
        if callable(fn):
            try:
                stats = await fn(client) if asyncio.iscoroutinefunction(fn) else fn(client)
                if isinstance(stats, dict) and stats:
                    break
            except Exception:
                continue
    if not stats:
        # Fallback: hit internal route logic if a global stores last stats
        stats = globals().get("_LAST_STATS") or {}
    return build_bias_panel(stats if isinstance(stats, dict) else {})


# Soft-enrich /stats JSON when the route returns dict via wrapper
_stats_route_prev = None
for r in list(getattr(app, "routes", []) or []):
    path = getattr(r, "path", None)
    if path == "/stats" and hasattr(r, "endpoint"):
        _stats_route_prev = r.endpoint
        break

if callable(_stats_route_prev):
    async def stats_with_bias(request: Request, *args, **kwargs):
        try:
            res = await _stats_route_prev(request, *args, **kwargs)
        except TypeError:
            res = await _stats_route_prev(request)
        if isinstance(res, dict):
            res = dict(res)
            res["selection_bias"] = build_bias_panel(res)
        return res

    # Re-bind if FastAPI allows replacing endpoint
    try:
        for r in app.routes:
            if getattr(r, "path", None) == "/stats" and hasattr(r, "endpoint"):
                r.endpoint = stats_with_bias
                break
    except Exception:
        pass


print(f"[part91] v{VERSION} selection-bias panel → GET /stats/bias (+ /stats.selection_bias when wrap ok)")
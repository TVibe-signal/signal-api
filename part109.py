# ---------- v2.90: Daily public benchmark snapshot (anonymous counts only) ----------
VERSION = "2.90.0"
app.version = VERSION
app.openapi_schema = None

import time
from typing import Any, Dict


@app.get("/benchmark/daily", tags=["accuracy"])
async def benchmark_daily(request: Request):
    """Anonymous daily snapshot others can compare against. No mint list."""
    client = request.app.state.client
    st: Dict[str, Any] = {}
    try:
        if "stats_report" in globals():
            st = await stats_report(client)
    except Exception as e:
        st = {"error": str(e)[:120]}

    perf = (st.get("performance") or {}).get("all_tracked") or {}
    oa = perf.get("ours_avoid") or {}
    ba = perf.get("baseline_avoid") or {}
    judged = int(perf.get("judged") or st.get("resolved") or 0)
    bad = int(perf.get("bad_outcomes") or 0)
    base = round(100.0 * bad / judged, 1) if judged else None
    lift = None
    if base is not None and oa.get("precision_pct") is not None:
        try:
            lift = round(float(oa["precision_pct"]) - float(base), 1)
        except (TypeError, ValueError):
            lift = None

    shadow = {}
    try:
        if PRED_ENABLED and client:
            key = globals().get("SHADOW_AVOID_KEY") or "si:shadow:avoid_rules"
            raw = await redis_pipe(client, [["HGETALL", key]])
            h = to_dict((raw or [{}])[0] or {})
            shadow = {
                "emitted": int(float(h.get("emitted", 0) or 0)),
                "judged": int(float(h.get("judged", 0) or 0)),
                "tp": int(float(h.get("tp", 0) or 0)),
                "fp": int(float(h.get("fp", 0) or 0)),
            }
    except Exception:
        pass

    return {
        "brand": "TVibe Signal",
        "as_of_unix": int(time.time()),
        "horizon_hours": st.get("horizon_hours") or 24,
        "judged": judged,
        "bad_outcomes": bad,
        "base_rate_pct": base,
        "ours_avoid": {
            "precision_pct": oa.get("precision_pct"),
            "recall_pct": oa.get("recall_pct"),
            "precision_ci95_pct": oa.get("precision_ci95_pct"),
        },
        "baseline_avoid": {
            "precision_pct": ba.get("precision_pct"),
            "recall_pct": ba.get("recall_pct"),
        },
        "lift_vs_base_rate_pts": lift,
        "early_horizons": st.get("early_horizons"),
        "shadow_avoid": shadow,
        "disclaimer": "Heuristics, not financial advice. Compare against this public snapshot.",
        "version": VERSION,
    }


print(f"[part109] v{VERSION} GET /benchmark/daily")
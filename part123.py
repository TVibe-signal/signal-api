# part123.py - stricter check for shadow-rule candidates (v2.97.0)
# GET /stats/rule-candidates reads the numbers already published on /stats and tests each shadow rule against a
# stricter list than the built-in "candidate" flag, which only looks at the avoid side. Read-only: it never changes
# a verdict. Walk-forward (is the gain still there on newer days?) is NOT computed here: it needs per-day outcomes
# for each rule, which /stats does not publish yet.
# Loader line (after part122, before part7):  ("part123.py", 0, "SKIP"),
import time

VERSION = "2.97.0"
app.version = VERSION
app.openapi_schema = None

_RC_CACHE = {"ts": 0.0, "data": None}
_RC_TTL = 300


def _evaluate(stats: dict) -> dict:
    rc = (stats or {}).get("rule_comparison_24h") or {}
    rules = rc.get("rules") or {}
    base = ((stats or {}).get("base_rate") or {}).get("bad_outcome_rate_pct")
    judged = rc.get("judged") or 0
    live = rules.get("live") or {}
    live_ok = live.get("ok_bad_rate_pct")
    out, strong = {}, []
    for name, r in rules.items():
        if name == "live":
            continue
        ci = r.get("precision_ci95_pct") or [None, None]
        checks = {
            "enough_avoid_flags_100": (r.get("avoid_n") or 0) >= 100,
            "precision_lower_bound_10pts_over_base": bool(ci[0] is not None and base is not None and ci[0] >= base + 10),
            "recall_at_least_10pts_over_live": (r.get("recall_vs_live_pts") or -999) >= 10,
            "precision_at_most_3pts_below_live": (r.get("precision_vs_live_pts") or -999) >= -3,
            "ok_group_not_worse_than_live_plus_2": bool(r.get("ok_bad_rate_pct") is not None and live_ok is not None
                                                        and r["ok_bad_rate_pct"] <= live_ok + 2),
            "ok_group_has_50_tokens": (r.get("ok_n") or 0) >= 50,
            "at_least_800_judged": judged >= 800,
        }
        ok = all(checks.values())
        out[name] = {"pass": ok, "builtin_candidate": r.get("candidate"), "checks": checks,
                     "avoid_n": r.get("avoid_n"), "precision_pct": r.get("precision_pct"),
                     "recall_pct": r.get("recall_pct"), "ok_n": r.get("ok_n"), "ok_bad_rate_pct": r.get("ok_bad_rate_pct"),
                     "failed": [k for k, v in checks.items() if not v]}
        if ok:
            strong.append(name)
    return {
        "version": VERSION, "horizon_hours": rc.get("horizon_hours"), "judged": judged,
        "base_rate_pct": base, "live": {"precision_pct": live.get("precision_pct"), "recall_pct": live.get("recall_pct"),
                                        "ok_bad_rate_pct": live_ok},
        "strong_candidates": strong, "rules": out, "live_verdict_unchanged": True,
        "walk_forward": "not computed: /stats publishes no per-day results for shadow rules yet",
        "note": "A rule is only a candidate. Wait for clean data after any outage, check walk-forward, then change the live rule "
                "in a numbered version and say so publicly. Heuristic, not financial advice.",
    }


async def _stats_json():
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal", timeout=30) as c:
        r = await c.get("/stats", headers={"accept": "application/json"})
        return r.json() if r.status_code == 200 else None


@app.get("/stats/rule-candidates", tags=["accuracy"])
async def stats_rule_candidates():
    now = time.time()
    if _RC_CACHE["data"] is not None and now - _RC_CACHE["ts"] < _RC_TTL:
        return _RC_CACHE["data"]
    try:
        st = await _stats_json()
    except Exception as e:
        return {"version": VERSION, "error": str(e)[:120]}
    if not isinstance(st, dict) or not (st.get("rule_comparison_24h") or {}).get("rules"):
        return {"version": VERSION, "error": "no shadow-rule data on /stats right now", "strong_candidates": []}
    data = _evaluate(st)
    _RC_CACHE.update(ts=now, data=data)
    return data


print("[part123] v%s GET /stats/rule-candidates (stricter shadow-rule check)" % VERSION)

"""part97 - /stats output fixes + honest comparison (v2.75.0). Changes NO verdict.
A small middleware post-processes GET /stats (original body is returned if anything fails):
- ci95_pct values were x100 (9220 -> 92.2)
- by_risk_bucket avg_return_pct 0.0 (not measured) -> null
- outlier-distorted means (>1000%) hidden
- adds base_rate (+ lift_vs_base), rule_comparison_24h, selection_bias
Needs part96 (wilson, _pct) loaded first.
"""
VERSION = "2.75.0"
app.version = VERSION
app.openapi_schema = None

import json

from fastapi.responses import Response


def _ci_over_100(o):
    if isinstance(o, dict):
        for k, v in o.items():
            if k.endswith("ci95_pct") and isinstance(v, list) and any(
                    isinstance(x, (int, float)) and x > 100 for x in v):
                return True
            if _ci_over_100(v):
                return True
    elif isinstance(o, list):
        return any(_ci_over_100(x) for x in o)
    return False


def _scale_ci(o):
    if isinstance(o, dict):
        for k, v in list(o.items()):
            if k.endswith("ci95_pct") and isinstance(v, list):
                o[k] = [round(x / 100.0, 1) if isinstance(x, (int, float)) else x for x in v]
            else:
                _scale_ci(v)
    elif isinstance(o, list):
        for x in o:
            _scale_ci(x)


def _hide_outliers(o):
    for v in (o.get("by_verdict") or {}).values():
        for blk in (v or {}).values():
            if not isinstance(blk, dict):
                continue
            for f in ("avg_return_pct", "avg_excess_return_pct"):
                x = blk.get(f)
                if isinstance(x, (int, float)) and abs(x) > 1000:
                    blk[f] = None
                    blk["outlier_note"] = "mean hidden: distorted by extreme values (median not tracked yet)"
    for b in o.get("by_risk_bucket") or []:
        if b.get("avg_excess_return_pct") is None and b.get("avg_return_pct") == 0:
            b["avg_return_pct"] = None  # was never measured, 0.0 was misleading


def _base_rate(o):
    a = (o.get("performance") or {}).get("all_tracked") or {}
    j, b = int(a.get("judged") or 0), int(a.get("bad_outcomes") or 0)
    if not j:
        return None
    r = {"judged": j, "bad": b, "bad_outcome_rate_pct": _pct(b, j), "ci95_pct": wilson(b, j),
         "note": "A random token is already 'bad' this often: read precision as lift over this rate."}
    for v in (o.get("by_verdict") or {}).values():
        full = (v or {}).get("full") or {}
        rate = full.get("bad_outcome_rate_pct")
        if rate is not None and r["bad_outcome_rate_pct"]:
            full["lift_vs_base"] = round(rate / r["bad_outcome_rate_pct"], 2)
    return r


def _rule_table(o, base):
    sr = o.get("shadow_rules") or {}
    rules = sr.get("rules") or {}
    live = rules.get("live") or {}
    lp, lr = live.get("avoid_precision_pct"), live.get("avoid_recall_pct")
    out = {}
    for name, r in rules.items():
        av = r.get("avoid") or {}
        n, rate = int(av.get("n") or 0), av.get("bad_outcome_rate_pct")
        if not n or rate is None:
            continue
        ci = wilson(round(rate * n / 100.0), n)
        ok = r.get("ok") or {}
        row = {"avoid_n": n, "precision_pct": rate, "precision_ci95_pct": ci,
               "recall_pct": r.get("avoid_recall_pct"),
               "ok_n": ok.get("n"), "ok_bad_rate_pct": ok.get("bad_outcome_rate_pct")}
        rec = r.get("avoid_recall_pct")
        if name != "live" and None not in (lp, lr, rec):
            d_r, d_p = round(rec - lr, 1), round(rate - lp, 1)
            row["recall_vs_live_pts"], row["precision_vs_live_pts"] = d_r, d_p
            row["candidate"] = bool(n >= 100 and ci and base and ci[0] > base and d_r >= 10 and d_p >= -3)
        out[name] = row
    return {"horizon_hours": sr.get("horizon_hours"), "judged": live.get("judged"), "rules": out,
            "criterion": ("candidate = avoid_n>=100, lower 95% precision bound above the base rate, "
                          "recall at least 10 pts above live, precision at most 3 pts below live. "
                          "Check walk-forward before promoting; live verdict is unchanged.")}


def _cohort_rates(block):
    if not isinstance(block, dict):
        return {"n": 0}
    vs = block.get("verdicts") or {}
    return {"n": int(block.get("n") or 0),
            "bad_outcome_rate_pct": block.get("bad_outcome_rate_pct"),
            "ci95_pct": block.get("ci95_pct"),
            "verdicts": {k: {"n": (vs.get(k) or {}).get("n"),
                             "bad_outcome_rate_pct": (vs.get(k) or {}).get("bad_outcome_rate_pct")}
                         for k in ("ok", "caution", "avoid") if k in vs}}


def build_bias_panel(stats):
    by = (stats or {}).get("by_source") or {}
    user = _cohort_rates(by.get("user") or {})
    parts = {k: _cohort_rates(v) for k, v in by.items() if str(k).startswith("seed")}
    seed_n = sum(p["n"] for p in parts.values())
    t, u = (parts.get("seed_trending") or {}).get("bad_outcome_rate_pct"), user.get("bad_outcome_rate_pct")
    return {
        "available": bool(by), "user": user, "seed": {"n": seed_n, "parts": parts},
        "untagged": _cohort_rates(by.get("untagged") or {}),
        "user_minus_seed_trending_pts": round(u - t, 1) if None not in (u, t) else None,
        "note": ("user = tokens people/agents queried; seed_boost and seed_profile are paid DexScreener "
                 "promotions, seed_trending and seed_new come from GeckoTerminal. Cohorts differ a lot, so "
                 "rates are selection-biased. Rates are hidden under 20 samples."),
        "ready": (user.get("n") or 0) >= 20 or seed_n >= 20, "version": VERSION,
    }


def _fix_stats(d):
    if not isinstance(d, dict) or not d.get("available", True):
        return d
    if _ci_over_100(d):
        _scale_ci(d)
    _hide_outliers(d)
    br = _base_rate(d)
    if br:
        d["base_rate"] = br
    d["rule_comparison_24h"] = _rule_table(d, (br or {}).get("bad_outcome_rate_pct"))
    d["selection_bias"] = build_bias_panel(d)
    d["stats_fixes"] = VERSION
    return d


try:
    @app.middleware("http")
    async def _p97_stats_mw(request, call_next):
        resp = await call_next(request)
        if request.method != "GET" or request.url.path != "/stats" or resp.status_code != 200:
            return resp
        body = b""
        async for chunk in resp.body_iterator:
            body += chunk
        keep = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
        try:
            out = json.dumps(_fix_stats(json.loads(body)), separators=(",", ":")).encode()
            keep = {k: v for k, v in keep.items() if k.lower() != "content-encoding"}
        except Exception as e:
            print(f"[part97] stats fix skipped: {str(e)[:80]}")
            out = body
        return Response(content=out, status_code=200, headers=keep, media_type="application/json")
except Exception as e:
    print(f"[part97] middleware not added: {e}")


print(f"[part97] v{VERSION} /stats fixes: ci scale, null returns, base_rate, rule_comparison_24h, selection_bias")

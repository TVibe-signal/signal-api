"""part99 - Evidence-calibrated reasoning (v2.77.0). Changes NO verdict.
Turns the track record into per-signal reasoning, using only what the data shows:
- calibrated_risk: P(bad within 24h) for this risk score, monotone-smoothed (pool adjacent
  violators) from by_risk_bucket, with a 95% interval, base rate and lift
- evidence: which present flags the data supports / contradicts / has never tested
- bad_rate_by_horizon + return_context for the verdict (1h / 6h / 24h, average return)
- reading: a short grounded text agents can quote
- GET /calibration shows the whole table. Needs part96 (wilson, _internal_get, _P96_TASKS).
"""
VERSION = "2.77.0"
app.version = VERSION
app.openapi_schema = None

import asyncio
import time

_P99 = {"model": None, "ts": 0.0, "tried": 0.0}


def _p99_build(st):
    bk = []
    for b in st.get("by_risk_bucket") or []:
        try:
            lo, hi = [int(x) for x in str(b.get("risk_score_range", "")).split("-")]
        except Exception:
            continue
        n, r = int(b.get("n") or 0), b.get("bad_outcome_rate_pct")
        if n and r is not None:
            bk.append((lo, hi, round(r * n / 100.0), n))
    bk.sort()
    blocks = []  # pool adjacent violators: rates must not fall as risk rises
    for i, (_, _, k, n) in enumerate(bk):
        blocks.append([k, n, [i]])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            b2, b1 = blocks.pop(), blocks.pop()
            blocks.append([b1[0] + b2[0], b1[1] + b2[1], b1[2] + b2[2]])
    table = []
    for k, n, idx in blocks:
        rng = f"{bk[idx[0]][0]}-{bk[idx[-1]][1]}"
        for i in idx:
            lo, hi = bk[i][0], bk[i][1]
            table.append({"bucket": f"{lo}-{hi}", "range": rng, "lo": lo, "hi": hi,
                          "p_bad_24h_pct": round(100.0 * k / n, 1),
                          "ci95_pct": wilson(k, n), "n": n, "pooled": len(idx) > 1})
    a = (st.get("performance") or {}).get("all_tracked") or {}
    base = (st.get("base_rate") or {}).get("bad_outcome_rate_pct")
    if base is None and a.get("judged"):
        base = round(100.0 * a.get("bad_outcomes", 0) / a["judged"], 1)
    pv, early = (a.get("verdicts") or {}), (st.get("early_horizons") or {})
    hz = {}
    for v in ("ok", "caution", "avoid"):
        row = {}
        for h in ("1h", "6h"):
            x = ((early.get(h) or {}).get("by_verdict") or {}).get(v) or {}
            row[h] = {"bad_rate_pct": x.get("bad_outcome_rate_pct"), "n": x.get("n")}
        x = pv.get(v) or {}
        row["24h"] = {"bad_rate_pct": x.get("bad_outcome_rate_pct"), "n": x.get("n")}
        full = ((st.get("by_verdict") or {}).get(v) or {}).get("full") or {}
        row["avg_return_pct_24h"] = {"value": full.get("avg_return_pct"), "n": full.get("n")}
        hz[v] = row
    flags = {f["flag"]: f for f in st.get("flags") or [] if f.get("flag")}
    return {"table": table, "base": base, "horizons": hz, "flags": flags,
            "definition": st.get("bad_outcome_definition")}


async def _p99_refresh():
    st = await _internal_get("/stats", 60)
    if st and st.get("available"):
        try:
            _P99["model"], _P99["ts"] = _p99_build(st), time.time()
        except Exception as e:
            print(f"[part99] model: {str(e)[:80]}")
    return _P99["model"]


def _p99_cached():
    if time.time() - _P99["tried"] > 120:
        _P99["tried"] = time.time()
        t = asyncio.create_task(_p99_refresh())
        _P96_TASKS.add(t)
        t.add_done_callback(_P96_TASKS.discard)
    return _P99["model"]


def _p99_calibrate(score, m):
    for row in m["table"]:
        if row["lo"] <= score < row["hi"] + 1 or (score >= 100 and row["hi"] >= 99):
            p, base = row["p_bad_24h_pct"], m["base"]
            return {"p_bad_24h_pct": p, "ci95_pct": row["ci95_pct"], "based_on_n": row["n"],
                    "score_bucket": row["range"], "pooled": row["pooled"], "base_rate_pct": base,
                    "lift_vs_base": round(p / base, 2) if base else None, "horizon_hours": 24,
                    "bad_outcome_definition": m["definition"]}
    return None


def _p99_evidence(flags, m):
    tested, untested = [], []
    for name in flags:
        f = m["flags"].get(name)
        if not f or f.get("n") is None or f["n"] < 20 or f.get("lift") is None:
            untested.append({"flag": name, "n": (f or {}).get("n", 0), "prior_weight": (f or {}).get("prior_weight")})
            continue
        lift = f["lift"]
        effect = "raises" if lift >= 1.1 else "no_support" if lift >= 0.9 else "contradicts"
        tested.append({"flag": name, "effect": effect, "lift": lift, "n": f["n"],
                       "bad_rate_pct": f.get("bad_rate_pct"), "blended_weight": f.get("blended_weight")})
    tested.sort(key=lambda x: -abs(x["lift"] - 1))
    return {"flags": tested, "untested": untested,
            "note": "lift = bad rate vs the same days' overall rate; flags overlap, so this is association, not cause."}


def _p99_reading(score, verdict, cal, ev, m, conf):
    out = []
    if cal:
        lo, hi = cal["ci95_pct"] or ("?", "?")
        out.append(f"Risk score {float(score):g} sits in the {cal['score_bucket']} range: {cal['p_bad_24h_pct']}% of "
                   f"{cal['based_on_n']} past tokens there were bad within 24h (95% CI {lo}-{hi}; base rate "
                   f"{cal['base_rate_pct']}%).")
    for f in ev["flags"][:3]:
        out.append(f"{f['flag']} {f['effect'].replace('_', ' ')} ({f['bad_rate_pct']}% bad, n={f['n']}, lift {f['lift']}).")
    if ev["untested"]:
        out.append("No outcome data yet for: " + ", ".join(u["flag"] for u in ev["untested"][:4]) + ".")
    r = ((m["horizons"].get(verdict) or {}).get("avg_return_pct_24h") or {})
    if r.get("value") is not None:
        out.append(f"Past '{verdict}' verdicts averaged {r['value']}% after 24h (n={r['n']}): the verdict measures "
                   "collapse risk, not upside.")
    if conf and conf.get("level") != "high":
        out.append(f"Data confidence is {conf['level']}: {', '.join(conf.get('reasons') or [])}.")
    return " ".join(out)


_build_prev_p99 = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_p99(client, mint, security, prefetched)
    try:
        if isinstance(result, dict):
            m = _p99_cached()
            if not m:
                result["calibration_status"] = "warming_up"
            else:
                score = float(result.get("risk_score") or 0)
                verdict = (((result.get("decision") or {}).get("verdict")) or result.get("verdict") or "").lower()
                cal = _p99_calibrate(score, m)
                ev = _p99_evidence(result.get("flags") or [], m)
                result["calibrated_risk"] = cal
                result["evidence"] = ev
                result["bad_rate_by_horizon"] = m["horizons"].get(verdict)
                result["reading"] = _p99_reading(score, verdict, cal, ev, m, result.get("decision_confidence"))
                order = result.get("si_reading_order")
                if isinstance(order, dict):
                    pr = order.setdefault("primary", [])
                    for k in ("calibrated_risk", "reading"):
                        if k not in pr:
                            pr.append(k)
    except Exception as e:
        print(f"[part99] {str(e)[:80]}")
    return result, status


@app.get("/calibration", tags=["accuracy"])
async def calibration():
    m = await _p99_refresh() or {}
    return {"version": VERSION, "ready": bool(m), "age_s": int(time.time() - _P99["ts"]) if m else None,
            "base_rate_pct": m.get("base"), "risk_to_p_bad_24h": m.get("table"),
            "bad_rate_by_verdict_horizon": m.get("horizons"),
            "flags": [{k: f.get(k) for k in ("flag", "n", "bad_rate_pct", "lift", "prior_weight", "blended_weight")}
                      for f in (m.get("flags") or {}).values()],
            "note": ("Empirical, from tokens people queried (selection-biased). Monotone-smoothed. "
                     "Association, not causation. Not financial advice.")}


print(f"[part99] v{VERSION} calibrated_risk + evidence + reading -> GET /calibration")

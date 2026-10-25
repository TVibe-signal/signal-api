# part136.py - Feature lift tracker (v2.99.6): which measurable ideas actually predict a bad outcome?
# Turns several "concepts" into measurable buckets, each recorded when the verdict is made and scored when the outcome is judged:
#   age (Lindy: older pairs live longer?), liquidity depth, liquidity/market-cap, top-10 concentration,
#   hour of day UTC (circadian), 24h price change (reflexivity), buy/sell balance, community unanimity (groupthink).
# For every bucket it shows n, bad rate, a shrunk estimate (Bayesian, pulled toward the average), a 99% interval and the lift.
#   GET /stats/feature-lift?min_n=30
# Research only: nothing here changes a verdict. Cost: 1 Redis write per new token per day + about 19 commands per judged outcome.
# Names start with _fl_ / _FL so they cannot clash with other parts (all parts share one namespace).
# Loader line (after part134, before part7):  ("part135.py", 0, "SKIP"),
import inspect
import json
import math
import re
import time
import types

VERSION = "2.99.6"
app.version = VERSION
app.openapi_schema = None

_FL_KEY = "si:featlift"
_FL_PEND = "si:featlift:p:{}"
_FL_PEND_TTL = 10 * 86400
_FL_TTL = 120 * 86400
_FL_PRIOR = 20      # strength of the pull toward the average for small buckets
_FL_Z99 = 2.576
_FL = types.SimpleNamespace(seen={}, cache_ts=0.0, cache=None, recorded=0, scored=0)

_FL_LABELS = {
    "age": ["<1h", "1-6h", "6-24h", "1-3d", "3-7d", "7-30d", ">30d"],
    "liq": ["<5k", "5-20k", "20-100k", "100-500k", ">500k"],
    "liq_mcap": ["<2%", "2-5%", "5-15%", ">15%"],
    "top10": ["<15%", "15-30%", "30-50%", ">50%"],
    "hour_utc": ["00-04", "04-08", "08-12", "12-16", "16-20", "20-24"],
    "pc24": ["<-30%", "-30..-5%", "-5..+5%", "+5..+30%", ">+30%"],
    "buys": ["few trades", "<30% buys", "30-70% buys", ">70% buys"],
    "community": ["none", "n<10", "mixed", "unanimous"],
}
_FL_NOTES = {
    "age": "Lindy idea: does a longer-lived pair keep living?", "liq": "market depth", "liq_mcap": "depth relative to market cap",
    "top10": "concentration of the top 10 holders", "hour_utc": "time of day (circadian) when the verdict was made",
    "pc24": "price already moved (reflexivity)", "buys": "buy/sell balance over the last 5 minutes",
    "community": "groupthink: does an unanimous small community predict anything?"}


def _fl_pick(x, edges, labels):
    for e, lab in zip(edges, labels):
        if x < e:
            return lab
    return labels[-1]


def _fl_num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _fl_features(body: dict) -> dict:
    fv = {}
    age = _fl_num(body.get("pair_age_minutes"))
    if age is not None:
        fv["age"] = _fl_pick(age, (60, 360, 1440, 4320, 10080, 43200), _FL_LABELS["age"])
    liq, mc = _fl_num(body.get("liquidity_usd")), _fl_num(body.get("market_cap_usd"))
    if liq is not None:
        fv["liq"] = _fl_pick(liq, (5e3, 2e4, 1e5, 5e5), _FL_LABELS["liq"])
        if mc and mc > 0:
            fv["liq_mcap"] = _fl_pick(liq / mc, (0.02, 0.05, 0.15), _FL_LABELS["liq_mcap"])
    sec = body.get("security") if isinstance(body.get("security"), dict) else {}
    t10 = _fl_num(sec.get("top10_holders_pct"))
    if t10 is not None:
        fv["top10"] = _fl_pick(t10, (15, 30, 50), _FL_LABELS["top10"])
    fv["hour_utc"] = _FL_LABELS["hour_utc"][time.gmtime().tm_hour // 4]
    pc = body.get("price_change_pct")
    pc24 = _fl_num(pc.get("24h")) if isinstance(pc, dict) else None
    if pc24 is not None:
        fv["pc24"] = _fl_pick(pc24, (-30, -5, 5, 30), _FL_LABELS["pc24"])
    b, s = _fl_num(body.get("buys_5m")), _fl_num(body.get("sells_5m"))
    if b is not None and s is not None:
        fv["buys"] = "few trades" if b + s < 5 else _fl_pick(b / (b + s), (0.3, 0.7), _FL_LABELS["buys"][1:])
    com = body.get("community") if isinstance(body.get("community"), dict) else {}
    conv = com.get("conviction") if isinstance(com.get("conviction"), dict) else {}
    n = _fl_num(conv.get("n"))
    if n is None:
        fv["community"] = "none"
    elif n < 10:
        fv["community"] = "n<10"
    else:
        m = re.search(r"(\d+(?:\.\d+)?)%", str(com.get("summary") or ""))
        fv["community"] = "unanimous" if (m and float(m.group(1)) >= 95) else "mixed"
    return fv


async def _fl_remember(client, mint: str, body: dict) -> None:
    if not globals().get("PRED_ENABLED") or not client or "redis_pipe" not in globals():
        return
    if body.get("asset_class") == "major" or (body.get("decision") or {}).get("asset_class") == "major":
        return
    now = time.time()
    if now - _FL.seen.get(mint, 0) < 86400:
        return
    fv = _fl_features(body)
    if not fv:
        return
    if len(_FL.seen) > 5000:
        _FL.seen.clear()
    _FL.seen[mint] = now
    await redis_pipe(client, [["SET", _FL_PEND.format(mint), json.dumps(fv, separators=(",", ":")), "NX", "EX", _FL_PEND_TTL]])
    _FL.recorded += 1


async def _fl_score(client, mint: str, bad: bool) -> None:
    key = _FL_PEND.format(mint)
    raw = await redis_pipe(client, [["GET", key]])
    v = (raw or [None])[0]
    if not v:
        return
    fv = json.loads(v)
    cmds = [["HINCRBY", _FL_KEY, "__all__|n", 1]]
    if bad:
        cmds.append(["HINCRBY", _FL_KEY, "__all__|bad", 1])
    for f, b in fv.items():
        cmds.append(["HINCRBY", _FL_KEY, "%s|%s|n" % (f, b), 1])
        if bad:
            cmds.append(["HINCRBY", _FL_KEY, "%s|%s|bad" % (f, b), 1])
    cmds += [["DEL", key], ["EXPIRE", _FL_KEY, _FL_TTL]]
    await redis_pipe(client, cmds)
    _FL.scored += 1


def _fl_wilson(k: int, n: int, z: float):
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def _fl_compute(h: dict, min_n: int) -> dict:
    h = {str(k): int(float(v or 0)) for k, v in (h or {}).items()}
    base_n, base_bad = h.get("__all__|n", 0), h.get("__all__|bad", 0)
    if base_n < max(min_n, 30):
        return {"ready": False, "reason": "needs at least %d judged tokens with recorded features" % max(min_n, 30), "judged": base_n}
    base = 100.0 * base_bad / base_n
    feats, findings = {}, []
    for f, labels in _FL_LABELS.items():
        rows = []
        for b in labels:
            n, bad = h.get("%s|%s|n" % (f, b), 0), h.get("%s|%s|bad" % (f, b), 0)
            if n < min_n:
                if n:
                    rows.append({"bucket": b, "n": n, "note": "too few"})
                continue
            rate = 100.0 * bad / n
            shrunk = 100.0 * (bad + _FL_PRIOR * base / 100.0) / (n + _FL_PRIOR)
            ci = _fl_wilson(bad, n, _FL_Z99)
            if ci[0] > base + 5:
                reading = "clearly riskier than average"
            elif ci[1] < base - 5:
                reading = "clearly safer than average"
            else:
                reading = "no clear difference"
            row = {"bucket": b, "n": n, "bad_rate_pct": round(rate, 1), "shrunk_pct": round(shrunk, 1), "ci99_pct": ci,
                   "lift": round(rate / base, 2) if base else None, "reading": reading}
            rows.append(row)
            if reading != "no clear difference":
                findings.append({"feature": f, **row, "_s": abs(rate - base) * math.sqrt(n)})
        feats[f] = {"about": _FL_NOTES[f], "buckets": rows}
    findings.sort(key=lambda x: -x["_s"])
    for x in findings:
        x.pop("_s", None)
    return {"ready": True, "judged": base_n, "base_rate_pct": round(base, 1), "features": feats, "findings": findings[:12],
            "note": ("Association measured on tokens people queried, not cause. About 35 buckets are compared at a 99% interval, "
                     "so treat one lone finding with care; a real effect shows up again on newer data (see /stats/walk-forward). "
                     "shrunk_pct pulls small buckets toward the average. Research only: no verdict uses this."),
            "live_verdict_unchanged": True}


@app.get("/stats/feature-lift", tags=["accuracy"])
async def stats_feature_lift(min_n: int = 30):
    min_n = max(10, min(int(min_n), 500))
    now = time.time()
    if _FL.cache is not None and now - _FL.cache_ts < 600 and _FL.cache[0] == min_n:
        return _FL.cache[1]
    h = {}
    try:
        client = getattr(getattr(app, "state", None), "client", None)
        if globals().get("PRED_ENABLED") and client and "redis_pipe" in globals():
            raw = await redis_pipe(client, [["HGETALL", _FL_KEY]])
            h = to_dict((raw or [{}])[0] or {}) if "to_dict" in globals() else {}
    except Exception as e:
        return {"version": VERSION, "ready": False, "error": str(e)[:100]}
    out = {"version": VERSION, **_fl_compute(h, min_n), "recorded_since_restart": _FL.recorded, "scored_since_restart": _FL.scored}
    _FL.cache, _FL.cache_ts = (min_n, out), now
    return out


_fl_build_prev = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _fl_build_prev(client, mint, security, *args, **kwargs)
    try:
        body = res[0] if isinstance(res, tuple) else res
        if isinstance(body, dict):
            await _fl_remember(client, str(mint), body)
    except Exception as e:
        print("[part135] record:", str(e)[:100])
    return res


_fl_out_prev = globals().get("on_outcome_for_si")


async def on_outcome_for_si(client, mint: str, bad: bool, meta=None, **kwargs):
    if callable(_fl_out_prev):
        try:
            plist = list(inspect.signature(_fl_out_prev).parameters.values())
        except (TypeError, ValueError):
            plist = []
        takes_meta = len(plist) >= 4 or any(p.kind == p.VAR_POSITIONAL for p in plist)
        try:
            await (_fl_out_prev(client, mint, bad, meta, **kwargs) if takes_meta else _fl_out_prev(client, mint, bad))
        except Exception as e:
            print("[part135] previous outcome hook:", str(e)[:100])
    try:
        if globals().get("PRED_ENABLED") and client and "redis_pipe" in globals():
            await _fl_score(client, mint, bad)
    except Exception as e:
        print("[part135] score:", str(e)[:100])


print("[part135] v%s feature lift tracker -> GET /stats/feature-lift (research only)" % VERSION)

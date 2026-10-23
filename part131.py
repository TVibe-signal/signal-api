# part131.py - Walk-forward from daily snapshots of the shadow-rule totals (v3.0.4)
# /stats publishes only cumulative counts per shadow rule, so "is the gain still there on NEWER data?" cannot be read
# from it. This keeps one small snapshot per UTC day (2 Redis commands per day, 1 read after a restart) and
# subtracts an older snapshot from the latest one: the difference is the performance on tokens judged in between.
#   GET /stats/walk-forward?days=7   per-rule precision/recall/ok-group on the new window + pass/fail checks
#   GET /changelog                   public list of rule versions (edit CHANGELOG below when a rule changes)
#   /stats now also carries rule_version and a pointer to walk-forward.
# Part123's /stats/rule-candidates gets walk_forward + promote_ready (strong candidates that also pass walk-forward).
# Nothing here changes a verdict. Needs part97 (/stats shape) and part123 loaded before it.
# Loader line (after part129/130, before part7):  ("part131.py", 0, "SKIP"),
import json
import math
import os
import time
import types

VERSION = "2.99.3"
app.version = VERSION
app.openapi_schema = None

RULE_VERSION = os.environ.get("RULE_VERSION", "avoid-v1")
_WF_KEY = "si:walkfwd:snaps"
_WF_KEEP = 120
_WF = types.SimpleNamespace(snaps=[], loaded=False, last_day="", persistent=False, err="")

CHANGELOG = [
    {"version": "2.88", "change": "Every /omni verdict is signed (Ed25519) and hash-chained; /verify checks it in the browser."},
    {"version": "2.89", "change": "Results by source on the home page; decision.verdict follows a capped verdict."},
    {"version": "2.91", "change": "llms.txt rewritten; deployer shadow stats (research only)."},
    {"version": "2.92", "change": "Telegram bot answers /check ADDRESS with the same verdict as /omni."},
    {"version": "2.94", "change": "Sell-quote simulation (sim.*) on signals; an unavailable quote is unknown, not a warning."},
    {"version": "2.97", "change": "Redis usage meter and stricter shadow-rule candidate check (/stats/rule-candidates)."},
    {"version": "2.99", "change": "filter.pass contract with policies default | strict | research."},
    {"version": "2.99.3", "change": "Walk-forward on newer data (/stats/walk-forward). Live rule unchanged: " + RULE_VERSION + "."},
]


def _wilson(k: int, n: int, z: float = 1.96):
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def _day(ts=None) -> str:
    return time.strftime("%Y%m%d", time.gmtime(ts if ts is not None else time.time()))


def _extract(stats: dict):
    rules = ((stats or {}).get("shadow_rules") or {}).get("rules") or {}
    if not (rules.get("live") or {}).get("judged"):
        return None
    snap = {"ts": int(time.time()), "rules": {}}
    for name, r in rules.items():
        av, ok = r.get("avoid") or {}, r.get("ok") or {}
        n, rate = int(av.get("n") or 0), av.get("bad_outcome_rate_pct")
        okn, okrate = int(ok.get("n") or 0), ok.get("bad_outcome_rate_pct")
        snap["rules"][name] = {
            "judged": int(r.get("judged") or 0), "bad": int(r.get("bad") or 0),
            "avoid_n": n, "avoid_bad": int(round(n * rate / 100.0)) if rate is not None else None,
            "ok_n": okn, "ok_bad": int(round(okn * okrate / 100.0)) if okrate is not None else None}
    return snap


def _client():
    return getattr(getattr(app, "state", None), "client", None)


async def _load():
    if _WF.loaded:
        return
    _WF.loaded = True
    try:
        if "redis_pipe" in globals() and _client() is not None:
            raw = await redis_pipe(_client(), [["LRANGE", _WF_KEY, 0, _WF_KEEP - 1]])
            items = (raw or [[]])[0] or []
            snaps = []
            for s in items:
                try:
                    snaps.append(json.loads(s))
                except Exception:
                    pass
            snaps.sort(key=lambda x: -x.get("ts", 0))
            if snaps:
                _WF.snaps = snaps
            _WF.persistent = True
    except Exception as e:
        _WF.err = str(e)[:100]


async def _maybe_snapshot(stats: dict):
    day = _day()
    if _WF.last_day == day:
        return
    await _load()
    if _WF.snaps and _day(_WF.snaps[0].get("ts")) == day:
        _WF.last_day = day
        return
    snap = _extract(stats)
    if snap is None:
        return
    _WF.snaps.insert(0, snap)
    del _WF.snaps[_WF_KEEP:]
    _WF.last_day = day
    try:
        if "redis_pipe" in globals() and _client() is not None:
            await redis_pipe(_client(), [["LPUSH", _WF_KEY, json.dumps(snap, separators=(",", ":"))],
                                         ["LTRIM", _WF_KEY, 0, _WF_KEEP - 1]])
    except Exception as e:
        _WF.err = str(e)[:100]


def _wf_compute(days: int = 7) -> dict:
    snaps = _WF.snaps
    if len(snaps) < 2:
        return {"ready": False, "reason": "needs at least 2 daily snapshots (one is stored per day)", "snapshots": len(snaps)}
    L = snaps[0]
    target = L["ts"] - days * 86400
    P = next((s for s in snaps[1:] if s["ts"] <= target), snaps[-1])
    span = round((L["ts"] - P["ts"]) / 86400.0, 1)
    lv_l, lv_p = L["rules"].get("live"), P["rules"].get("live")
    if not lv_l or not lv_p:
        return {"ready": False, "reason": "live rule missing in a snapshot"}
    dj, db = lv_l["judged"] - lv_p["judged"], lv_l["bad"] - lv_p["bad"]
    if dj <= 0 or db < 0:
        return {"ready": False, "reason": "counters reset or no new judged outcomes in this window", "window_days": span}
    base = 100.0 * db / dj
    rows = {}
    for name, a in L["rules"].items():
        b = P["rules"].get(name)
        if not b or a["avoid_bad"] is None or b["avoid_bad"] is None:
            continue
        dn, dab = a["avoid_n"] - b["avoid_n"], a["avoid_bad"] - b["avoid_bad"]
        if dn < 0 or dab < 0 or dab > dn:
            continue
        okn = a["ok_n"] - b["ok_n"]
        okb = (a["ok_bad"] - b["ok_bad"]) if (a["ok_bad"] is not None and b["ok_bad"] is not None) else None
        rows[name] = {"avoid_n": dn, "precision_pct": round(100.0 * dab / dn, 1) if dn else None,
                      "precision_ci95_pct": _wilson(dab, dn), "recall_pct": round(100.0 * dab / db, 1) if db else None,
                      "ok_n": okn, "ok_bad_rate_pct": round(100.0 * okb / okn, 1) if (okb is not None and okn > 0 and 0 <= okb <= okn) else None}
    live = rows.get("live")
    for name, r in rows.items():
        if name == "live" or not live:
            continue
        r["recall_vs_live_pts"] = round((r["recall_pct"] or 0) - (live["recall_pct"] or 0), 1)
        r["precision_vs_live_pts"] = round((r["precision_pct"] or 0) - (live["precision_pct"] or 0), 1)
        ci = r["precision_ci95_pct"]
        checks = {
            "enough_avoid_flags_150": r["avoid_n"] >= 150,
            "precision_lower_bound_10pts_over_base": bool(ci and ci[0] >= base + 10),
            "recall_at_least_10pts_over_live": r["recall_vs_live_pts"] >= 10,
            "precision_at_most_3pts_below_live": r["precision_vs_live_pts"] >= -3,
            "ok_group_not_worse_than_live_plus_2": bool(r["ok_bad_rate_pct"] is not None and live["ok_bad_rate_pct"] is not None
                                                        and r["ok_bad_rate_pct"] <= live["ok_bad_rate_pct"] + 2),
            "ok_group_has_40_tokens": r["ok_n"] >= 40}
        r["checks"], r["pass"] = checks, all(checks.values())
        r["failed"] = [k for k, v in checks.items() if not v]
    return {"ready": True, "window_days": span, "requested_days": days, "judged_in_window": dj,
            "base_rate_pct_in_window": round(base, 1), "from_ts": P["ts"], "to_ts": L["ts"],
            "snapshots": len(snaps), "rules": rows,
            "note": "Only tokens judged inside the window. A rule has to pass here AND on the all-time check before any live change."}


@app.get("/stats/walk-forward", tags=["accuracy"])
async def stats_walk_forward(days: int = 7):
    await _load()
    out = _wf_compute(max(1, min(int(days), 60)))
    out.update({"version": VERSION, "live_verdict_unchanged": True, "persistent": _WF.persistent,
                "storage_error": _WF.err or None, "rule_version": RULE_VERSION})
    return out


@app.get("/changelog", tags=["accuracy"])
async def changelog():
    return {"version": VERSION, "rule_version": RULE_VERSION, "entries": CHANGELOG,
            "policy": "A live rule changes only after the checks on /stats/rule-candidates and /stats/walk-forward pass, "
                      "with a new rule_version and an entry here."}


# part123's candidate list also shows walk-forward and a promote_ready shortlist
_prev_eval_131 = globals().get("_evaluate")
if callable(_prev_eval_131):
    def _evaluate(stats):  # noqa: N802 (part123's route looks this name up at request time)
        d = _prev_eval_131(stats)
        try:
            wf = _wf_compute(7)
            d["walk_forward"] = wf
            for name, row in (d.get("rules") or {}).items():
                row["walk_forward_pass"] = bool(((wf.get("rules") or {}).get(name) or {}).get("pass"))
            d["promote_ready"] = [n for n in (d.get("strong_candidates") or []) if ((wf.get("rules") or {}).get(n) or {}).get("pass")]
        except Exception as e:
            print("[part131] evaluate:", str(e)[:100])
        return d


class _WalkForwardMW:
    """Sees every GET /stats answer: takes the daily snapshot and adds rule_version."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") != "/stats" or scope.get("method") != "GET":
            return await self.app(scope, receive, send)
        held, chunks = {}, []

        async def cap(msg):
            if msg["type"] == "http.response.start":
                held["start"] = msg
                return
            if msg["type"] != "http.response.body" or "start" not in held:
                return await send(msg)
            chunks.append(msg.get("body", b""))
            if msg.get("more_body"):
                return
            body, start = b"".join(chunks), held["start"]
            try:
                hs = {k.lower(): v for k, v in start["headers"]}
                if start.get("status") == 200 and b"json" in hs.get(b"content-type", b"") and b"content-encoding" not in hs:
                    d = json.loads(body)
                    if isinstance(d, dict):
                        await _maybe_snapshot(d)
                        d["rule_version"] = RULE_VERSION
                        d["walk_forward"] = "/stats/walk-forward"
                        body = json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            except Exception as e:
                print("[part131] stats mw:", str(e)[:100])
            hdrs = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"] + [(b"content-length", str(len(body)).encode())]
            await send({**start, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, cap)


try:
    app.add_middleware(_WalkForwardMW)
except Exception as _e:
    print("[part131] could not add middleware:", str(_e)[:100])

print("[part131] v%s walk-forward from daily snapshots -> GET /stats/walk-forward, /changelog (rule_version=%s)" % (VERSION, RULE_VERSION))

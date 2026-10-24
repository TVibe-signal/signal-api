# part134.py - One-page health board + schema check (v2.99.5)
#   GET /ops/health                 one JSON that answers "is TVibe healthy?" (open it on the phone and screenshot it)
#   GET /ops/contract-check?mint=   calls /omni and /signal in-process and lists missing contract fields
#   /omni and /signal now carry schema_version
# The health board tests Redis with a real write + read back, reads /stats, the circuit, the signed-verdict chain,
# the cache, the Redis meter, the Telegram counters and the walk-forward snapshots, then says green / amber / red with
# plain reasons. Every section is optional: a part that is not loaded is reported as "not loaded", never as an error.
# Optional: set OPS_KEY and call /ops/health?key=<value>. Costs 2 Redis commands per call (the write + read test).
# Loader line (after part131, before part7):  ("part134.py", 0, "SKIP"),
import json
import os
import time

from fastapi.responses import JSONResponse

VERSION = "2.99.5"
app.version = VERSION
app.openapi_schema = None

SCHEMA_VERSION = "1.0"
_H_LAST = {"ts": 0.0, "judged": None}
_EXPECTED_ROUTES = ["/omni", "/signal", "/exit", "/stats", "/verify", "/attest", "/llms.txt", "/benchmark/daily", "/ping", "/health", "/pricing",
                    "/stats/rule-candidates", "/stats/walk-forward", "/changelog", "/filter/policies", "/ops/redis",
                    "/system/circuit", "/cachez", "/telegram/status", "/agents/reliability"]
_PARTS = {"signed verdicts (part105)": "_attest", "sell-sim (part119)": "_sim_from_exit", "circuit (part116)": "circuit_status",
          "filter contract (part125)": "build_filter_block", "redis meter (part122)": "_RM", "redis thrift (part124)": "_coalesce_cmds",
          "response cache (part112)": "_CacheMW", "telegram (part114)": "_tg_handle", "walk-forward (part131)": "_wf_compute",
          "rule candidates (part123)": "_evaluate", "outcome labels (part108)": "_LABELED_108"}
_REQ_OMNI = ["decision.verdict", "decision.blockers", "decision.cautions", "decision.unknowns", "decision.valid_for_s",
             "would_change_my_mind", "system_stress", "filter.pass", "filter.reasons", "sim", "attestation"]
_REQ_SIGNAL = ["decision.verdict", "decision.valid_for_s", "would_change_my_mind", "system_stress", "filter.pass", "sim",
               "calibrated_risk", "track_record_context"]


# All parts share ONE namespace, so a later part that reuses a name (for example _TG) silently breaks the earlier one.
_SHAPES = {"_TG": "updates", "S": "sign", "_RM": "commands", "_CS": "hit", "_WF": "snaps", "_CB": "get", "_STATS": "get",
           "_html": "escape"}


def _clashes():
    bad = []
    for name, attr in _SHAPES.items():
        if name in globals() and not hasattr(globals()[name], attr):
            bad.append("%s is a %s now (expected something with .%s)" % (name, type(globals()[name]).__name__, attr))
    return bad


# keep the self-host link the same everywhere (part127/128 default to an older address)
try:
    if isinstance(globals().get("_FAIR"), dict):
        _FAIR["self_host"] = os.environ.get("GITHUB_URL", "https://github.com/TVibe-signal/signal-api")
except Exception:
    pass


def _dig(d, path):
    for k in path.split("."):
        if not isinstance(d, dict) or k not in d:
            return False
        d = d[k]
    return True


async def _asgi_get(path, params=None, timeout=45):
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal", timeout=timeout) as c:
        r = await c.get(path, params=params or {}, headers={"accept": "application/json"})
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, None


def _auth(key):
    need = os.environ.get("OPS_KEY", "")
    return not need or key == need


async def _redis_roundtrip():
    k = "tv:health:ping"
    t0 = time.time()
    try:
        rp = globals().get("_redis")
        if callable(rp):  # part105 helper raises when Redis rejects a command
            res = await rp([["SET", k, "1", "EX", 60], ["GET", k]])
        elif "redis_pipe" in globals():
            client = getattr(getattr(app, "state", None), "client", None)
            res = await redis_pipe(client, [["SET", k, "1", "EX", 60], ["GET", k]])
        else:
            return {"status": "not loaded"}
        ok = bool(res) and len(res) >= 2 and str(res[1]) == "1"
        return {"status": "ok" if ok else "FAILED", "ms": int((time.time() - t0) * 1000),
                "detail": None if ok else "wrote a key but could not read it back (quota or storage problem)"}
    except Exception as e:
        return {"status": "FAILED", "ms": int((time.time() - t0) * 1000), "detail": str(e)[:140]}


@app.get("/ops/health", include_in_schema=False)
async def ops_health(key: str = ""):
    if not _auth(key):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    issues, out = [], {"version": VERSION, "time": int(time.time())}

    # 1) Redis
    out["redis"] = rt = await _redis_roundtrip()
    if rt.get("status") == "FAILED":
        issues.append(("red", "Redis is not writable: %s" % (rt.get("detail") or "")))

    # 2) /stats
    st = {}
    try:
        code, st = await _asgi_get("/stats")
        st = st or {}
    except Exception as e:
        st = {}
        issues.append(("amber", "/stats could not be read: %s" % str(e)[:80]))
    perf = ((st.get("performance") or {}).get("all_tracked") or {})
    bv = st.get("by_verdict") or {}
    vsum = sum(int(((bv.get(k) or {}).get("full") or {}).get("n") or 0) for k in ("ok", "caution", "avoid"))
    judged = perf.get("judged")
    now = time.time()
    grew = None
    if judged is not None and _H_LAST["judged"] is not None and now - _H_LAST["ts"] > 600:
        grew = {"judged_added": judged - _H_LAST["judged"], "hours": round((now - _H_LAST["ts"]) / 3600.0, 1)}
    if judged is not None and now - _H_LAST["ts"] > 600:
        _H_LAST.update(ts=now, judged=judged)
    out["stats"] = {"judged": judged, "days_covered": perf.get("days_covered"), "resolved": st.get("resolved"),
                    "pending": st.get("pending"), "scoring": st.get("scoring"), "verdict_table_total": vsum,
                    "early_1h_n": ((st.get("early_horizons") or {}).get("1h") or {}).get("n"), "growth_since_last_check": grew}
    if st.get("resolved") == 0 and st.get("pending") == 0 and vsum == 0:
        issues.append(("amber", "the queue of verdicts waiting for their 24h result is unreadable (resolved=0, pending=0)"))
    if st.get("scoring") == "static":
        issues.append(("amber", "scoring is 'static': tuned risk weights are not loaded"))
    if grew and grew["hours"] >= 6 and grew["judged_added"] <= 0:
        issues.append(("amber", "no new judged outcomes in the last %s h" % grew["hours"]))

    # 3) signed verdicts
    if callable(globals().get("attest_status")):
        try:
            a = await attest_status()
            out["attest"] = {k: a.get(k) for k in ("enabled", "persistent", "chain_length", "anchored_days", "unsaved_records",
                                                     "last_saved_at", "last_error")}
            if a.get("last_error") and "anchor" not in str(a.get("last_error")):
                issues.append(("amber", "signed-verdict storage error: %s" % str(a["last_error"])[:80]))
            if (a.get("unsaved_records") or 0) > 20:
                issues.append(("amber", "%s signed verdicts are waiting to be saved" % a["unsaved_records"]))
        except Exception as e:
            out["attest"] = {"error": str(e)[:80]}
    else:
        out["attest"] = "not loaded"

    # 4) circuit, cache, Redis meter, Telegram, walk-forward
    if callable(globals().get("circuit_status")):
        try:
            c = circuit_status()
            out["circuit"] = {"state": c.get("state"), "reason": c.get("reason") or None}
            if c.get("state") != "closed":
                issues.append(("amber", "circuit is %s (upstream sources failing)" % c.get("state")))
        except Exception:
            out["circuit"] = "error"
    cs = globals().get("_CS")
    if cs is not None and hasattr(cs, "hit"):
        tot = cs.hit + cs.miss
        out["cache"] = {"hits": cs.hit, "misses": cs.miss, "hit_rate_pct": round(100.0 * cs.hit / tot, 1) if tot else None}
    rm = globals().get("_RM")
    if rm is not None and hasattr(rm, "commands"):
        up_h = max((now - rm.start) / 3600.0, 0.01)
        proj = int(rm.commands / up_h * 24 * 30)
        top = sorted(rm.by_caller.items(), key=lambda kv: -kv[1]["commands"])[:3]
        out["redis_meter"] = {"commands_since_restart": rm.commands, "projected_per_month": proj,
                              "top": [{"where": k, "share_pct": round(100.0 * v["commands"] / rm.commands, 1)} for k, v in top] if rm.commands else []}
        if proj > 500000:
            issues.append(("amber", "projected Redis use is %.1fM commands a month (free plan: 0.5M)" % (proj / 1e6)))
    tg = globals().get("_TG")
    if tg is not None and hasattr(tg, "updates"):
        out["telegram"] = {"ready": bool(globals().get("_TG_TOKEN") and globals().get("_TG_SECRET")), "updates": tg.updates,
                           "replies": tg.replies, "errors": tg.errors}
    wf = globals().get("_WF")
    if wf is not None and hasattr(wf, "snaps"):
        w = globals().get("_wf_compute")(7) if callable(globals().get("_wf_compute")) else {}
        out["walk_forward"] = {"snapshots": len(wf.snaps), "ready": w.get("ready"), "window_days": w.get("window_days"),
                               "persistent": wf.persistent}

    # 5) candidates (shadow rules)
    try:
        code, rc = await _asgi_get("/stats/rule-candidates")
        if isinstance(rc, dict) and "strong_candidates" in rc:
            out["rule_candidates"] = {"strong": rc.get("strong_candidates"), "promote_ready": rc.get("promote_ready"),
                                      "judged": rc.get("judged")}
    except Exception:
        pass

    # 6) what is loaded
    paths = {getattr(r, "path", None) for r in getattr(app, "routes", [])}
    out["routes_missing"] = [p for p in _EXPECTED_ROUTES if p not in paths]
    out["parts_loaded"] = {name: (g in globals()) for name, g in _PARTS.items()}

    out["namespace_clashes"] = _clashes()
    for m in out["namespace_clashes"]:
        issues.append(("red", "global name clash: " + m))

    level = "red" if any(l == "red" for l, _ in issues) else ("amber" if issues else "green")
    out["overall"] = level
    out["issues"] = [m for _, m in issues]
    return out


@app.get("/ops/contract-check", include_in_schema=False)
async def ops_contract_check(mint: str = "", key: str = ""):
    if not _auth(key):
        return JSONResponse({"error": "forbidden"}, status_code=403)
    mint = mint or os.environ.get("CONTRACT_MINT") or "CbcyNo7m1amFWqEQm2m4PLv1UNvpcL3C1Ujm6AkzpKoU"
    res = {"version": VERSION, "schema_version": SCHEMA_VERSION, "mint": mint}
    for name, path, req in (("omni", "/omni", _REQ_OMNI), ("signal", "/signal", _REQ_SIGNAL)):
        try:
            code, d = await _asgi_get(path, {"mint": mint})
            if code != 200 or not isinstance(d, dict):
                res[name] = {"http": code, "ok": False, "missing": req}
                continue
            miss = [p for p in req if not _dig(d, p)]
            res[name] = {"http": code, "ok": not miss, "missing": miss, "schema_version": d.get("schema_version")}
        except Exception as e:
            res[name] = {"ok": False, "error": str(e)[:100]}
    res["note"] = "A missing field is a gap in the contract (it should be null or an unknown, never silently absent). attestation needs part105."
    return res


class _SchemaMW:
    """Adds schema_version to GET /omni and /signal JSON."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") not in ("/omni", "/signal") or scope.get("method") != "GET":
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
                    if isinstance(d, dict) and "schema_version" not in d:
                        d["schema_version"] = SCHEMA_VERSION
                        body = json.dumps(d, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            except Exception as e:
                print("[part134] schema mw:", str(e)[:100])
            hdrs = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"] + [(b"content-length", str(len(body)).encode())]
            await send({**start, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, cap)


try:
    app.add_middleware(_SchemaMW)
except Exception as _e:
    print("[part134] could not add middleware:", str(_e)[:100])

print("[part134] v%s GET /ops/health, /ops/contract-check; schema_version=%s on /omni and /signal" % (VERSION, SCHEMA_VERSION))

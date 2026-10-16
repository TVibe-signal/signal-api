# ---------- v2.62.1: fix at the source + force benchmark route ----------
VERSION = "2.62.1"
app.version = VERSION
app.openapi_schema = None

# ===== A. Fix top-10 = 0 at the source (part3 calls build_security(raw_sec, pool_ids), sync) =====
_build_security_prev = build_security


def build_security(*a, **k):
    out = _build_security_prev(*a, **k)
    try:
        if isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], dict):
            sec, fl = out
            t = sec.get("top10_holders_pct")
            if isinstance(t, (int, float)) and not isinstance(t, bool) and t <= 0:
                sec = dict(sec)
                sec["top10_holders_pct"] = None  # unknown, not 0%
                return sec, fl
    except Exception:
        pass
    return out


# ===== B. part83's _fix_missing now also cleans the nested security dict =====
def _fix_missing(r):
    if not isinstance(r, dict):
        return r
    r = dict(r)
    sec = r.get("security")
    if isinstance(sec, dict):
        sec = dict(sec)
        r["security"] = sec
    major = r.get("asset_class") == "major"
    for d in (r, sec):
        if not isinstance(d, dict):
            continue
        if major and d.get("lp_locked_pct") == 0:
            d["lp_locked_pct"] = None  # LP lock is not meaningful for SOL/USDC/USDT
        t = d.get("top10_holders_pct")
        if isinstance(t, (int, float)) and not isinstance(t, bool) and t <= 0:
            d["top10_holders_pct"] = None
    if not major and "top10_holders_pct" in r and r["top10_holders_pct"] is None:
        dq = dict(r.get("data_quality") or {})
        miss = list(dq.get("missing") or [])
        if "top10_holders_pct" not in miss:
            miss.append("top10_holders_pct")
            dq["missing"] = miss
            dq["completeness"] = "partial"
            try:
                dq["data_confidence"] = min(float(dq.get("data_confidence", 1.0)), 0.7)
            except Exception:
                dq["data_confidence"] = 0.7
            r["data_quality"] = dq
    return r


# ===== C. /benchmark/prerug must win regardless of route order =====
_routes_logged = False


def _log_routes_once():
    global _routes_logged
    if _routes_logged:
        return
    _routes_logged = True
    try:
        owners = [
            f"{getattr(r.endpoint, '__name__', '?')}@{getattr(r.endpoint, '__module__', '?')}"
            for r in app.router.routes
            if getattr(r, "path", None) == "/benchmark/prerug"
        ]
        print(f"[part84] /benchmark/prerug owners (first wins): {owners}")
        print(f"[part84] build_signal={getattr(build_signal, '__name__', '?')} "
              f"build_security={getattr(build_security, '__name__', '?')}")
    except Exception as e:
        print(f"[part84] route log failed: {e!r}")


@app.middleware("http")
async def _prerug_override(request: Request, call_next):
    _log_routes_once()
    if request.method == "GET" and request.url.path == "/benchmark/prerug":
        try:
            return await benchmark_prerug_v3(request)
        except HTTPException as e:
            return JSONResponse(status_code=e.status_code, content={"detail": e.detail},
                                headers=getattr(e, "headers", None))
    return await call_next(request)


print(f"[part84] v{VERSION} source fix (top10) + nested security + prerug override loaded")

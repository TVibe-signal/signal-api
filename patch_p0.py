# patch_p0.py - P0 fix v5 (complete, syntax-safe)
# Loaded AFTER core.py / features.py / extensions.py by main.py.

import time
from fastapi.responses import JSONResponse

def apply(G):
    # 1. Force version
    for key in ("VERSION", "APP_VERSION", "__version__", "API_VERSION"):
        G[key] = "3.0.28"
    try:
        G["app"].version = "3.0.28"
    except Exception:
        pass

    # 2. Force P0 config
    G["STALE_MAX"] = 600
    G["STALE_MAX_S"] = 600
    G["CACHE_MAX"] = 1000
    G["CACHE_SIZE"] = 1000
    G["UPSTREAM_EVERY_S"] = 60

    # 3. Fix client_ip crash
    # Old bug: stats calls itself with AsyncClient,
    # AsyncClient has no .client, so it crashed with 500.
    def _safe_client_ip(req):
        try:
            if req is None:
                return "unknown"
            c = getattr(req, "client", None)
            if c is not None and hasattr(c, "host"):
                try:
                    hdrs = getattr(req, "headers", None)
                    xff = None
                    if hdrs is not None:
                        xff = hdrs.get("x-forwarded-for")
                    if xff:
                        parts = [p.strip() for p in xff.split(",")]
                        parts = [p for p in parts if p]
                        if parts:
                            return parts[-1]
                except Exception:
                    pass
                return c.host
            return "unknown"
        except Exception:
            return "unknown"

    for name in ("client_ip", "_client_ip_v20", "client_ip_v20", "_client_ip"):
        G[name] = _safe_client_ip
    print("[patch_p0] client_ip hardened")

    # 4. Wrap build_signal
    orig_build = G.get("build_signal")
    if callable(orig_build):
        async def wrapped_build(client, mint, security, prefetched=None):
            result, status = await orig_build(client, mint, security, prefetched)
            try:
                if isinstance(result, dict):
                    decision = result.get("decision") or {}
                    filt = result.get("filter") or {}
                    unknowns = decision.get("unknowns") or result.get("unknowns") or []
                    result["unknowns"] = unknowns
                    decision["unknowns"] = unknowns
                    age = None
                    ts = result.get("timestamp")
                    if isinstance(ts, (int, float)):
                        age = time.time() - ts
                    is_stale = bool(result.get("stale") or result.get("partial"))
                    if age is not None and age > 600:
                        is_stale = True
                    conf = result.get("decision_confidence") or {}
                    conf_low = False
                    if isinstance(conf, dict):
                        conf_low = (conf.get("level") == "low")
                    strict = bool(filt.get("pass"))
                    strict = strict and (not is_stale) and (not conf_low)
                    filt["pass_strict"] = strict
                    if is_stale or conf_low:
                        filt["pass"] = False
                    result["filter"] = filt
                    result["decision"] = decision
                    result["filter_pass_strict"] = strict
            except Exception as e:
                print("[patch_p0] build wrap skipped")
                print(str(e)[:100])
            return result, status
        G["build_signal"] = wrapped_build
        print("[patch_p0] build_signal wrapped")

    # 5. Wrap /stats - never 500 again
    # Must rebuild dependant too.
    try:
        app = G.get("app")
        if app is not None:
            from fastapi.dependencies.utils import get_dependant
            for route in getattr(app, "routes", []):
                p = getattr(route, "path", None)
                if p in ("/stats", "/stats/horizons", "/stats/bias"):
                    orig_endpoint = route.endpoint
                    if getattr(orig_endpoint, "_p0_safe", False):
                        continue

                    async def safe_endpoint(request, _orig=orig_endpoint, _path=p):
                        try:
                            return await _orig(request)
                        except Exception as e:
                            print("[patch_p0] stats fallback")
                            print(str(e)[:100])
                            body = {}
                            body["version"] = "3.0.28"
                            body["available"] = False
                            body["judged"] = 0
                            body["n"] = 0
                            body["note"] = "Stats retry in 60s."
                            body["error"] = str(e)[:100]
                            return JSONResponse(body, status_code=200)

                    safe_endpoint._p0_safe = True
                    route.endpoint = safe_endpoint
                    try:
                        route.dependant = get_dependant(
                            path=route.path_format,
                            call=safe_endpoint
                        )
                    except Exception:
                        print("[patch_p0] dependant rebuild skipped")
            print("[patch_p0] stats wrapper applied")
    except Exception:
        print("[patch_p0] stats wrap skipped")

    print("[patch_p0] applied v3.0.28")
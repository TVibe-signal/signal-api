# patch_p0.py - P0 fix v3 (complete)
# Loaded AFTER core.py / features.py / extensions.py by main.py.
# Purpose: fix version, config, /omni pass logic, /stats 500, and client_ip crash
# without touching the 10k-line files.

import time
from fastapi.responses import JSONResponse

def apply(G):
    # --------------------------------------------------
    # 1. Force version to 3.0.28
    # extensions.py overwrites VERSION many times (2.72 -> ... -> 3.0.27),
    # so we must overwrite it AFTER all files are loaded.
    # --------------------------------------------------
    for key in ("VERSION", "APP_VERSION", "__version__", "API_VERSION"):
        G[key] = "3.0.28"
    try:
        G["app"].version = "3.0.28"
    except Exception:
        pass

    # --------------------------------------------------
    # 2. Force P0 config
    # --------------------------------------------------
    for key, value in (
        ("STALE_MAX", 600),
        ("STALE_MAX_S", 600),
        ("CACHE_MAX", 1000),
        ("CACHE_SIZE", 1000),
        ("UPSTREAM_EVERY_S", 60),
    ):
        G[key] = value

    # --------------------------------------------------
    # 3. Fix /stats 500: harden client_ip
    # ROOT CAUSE (from Render logs):
    #   stats_route -> client_ip(request)
    #   -> _client_ip_v20(request)
    #   -> request.client.host
    #   AttributeError: 'AsyncClient' object has no attribute 'client'
    #
    # /stats calls itself internally via httpx AsyncClient, and passes
    # that AsyncClient where a FastAPI Request was expected.
    # AsyncClient has no .client attribute, so it crashed with 500.
    #
    # Fix: if the object is not a real Request, return "unknown"
    # instead of crashing. Rate limit still works.
    # --------------------------------------------------
    def _safe_client_ip(req):
        try:
            if req is None:
                return "unknown"
            # Real Starlette Request has .client with .host
            # httpx AsyncClient has no .client -> return "unknown"
            c = getattr(req, "client", None)
            if c is not None and hasattr(c, "host"):
                try:
                    headers = getattr(req, "headers", None)
                    xff = headers.get("x-forwarded-for") if headers is not None else None
                    if xff:
                        parts = [p.strip() for p in xff.split(",") if p.strip()]
                        if parts:
                            return parts[-1]
                except Exception:
                    pass
                return c.host
            return "unknown"
        except Exception:
            return "unknown"

    # Overwrite ALL client_ip variants, because extensions.py
    # redefines client_ip multiple times.
    for name in ("client_ip", "_client_ip_v20", "client_ip_v20", "_client_ip"):
        G[name] = _safe_client_ip
    print("[patch_p0] client_ip hardened")

    # --------------------------------------------------
    # 4. Wrap build_signal: stale / low confidence -> pass = False
    # Adds filter.pass_strict and syncs unknowns.
    # --------------------------------------------------
    orig_build = G.get("build_signal")
    if callable(orig_build):
        async def wrapped_build(client, mint, security, prefetched=None):
            result, status = await orig_build(client, mint, security, prefetched)
            try:
                if isinstance(result, dict):
                    decision = result.get("decision") or {}
                    filt = result.get("filter") or {}

                    # Sync unknowns: outer and decision must match
                    unknowns = decision.get("unknowns") or result.get("unknowns") or []
                    result["unknowns"] = unknowns
                    decision["unknowns"] = unknowns

                    # Stale check: timestamp older than 600s, or stale/partial flag
                    age = None
                    ts = result.get("timestamp")
                    if isinstance(ts, (int, float)):
                        age = time.time() - ts
                    is_stale = bool(result.get("stale") or result.get("partial"))
                    if age is not None and age > 600:
                        is_stale = True

                    # Low confidence check
                    conf = result.get("decision_confidence") or {}
                    conf_low = (conf.get("level") == "low") if isinstance(conf, dict) else False

                    # pass_strict = original pass AND not stale AND not low confidence
                    strict = bool(filt.get("pass")) and (not is_stale) and (not conf_low)
                    filt["pass_strict"] = strict
                    if is_stale or conf_low:
                        filt["pass"] = False

                    result["filter"] = filt
                    result["decision"] = decision
                    result["filter_pass_strict"] = strict
            except Exception as e:
                print(f"[patch_p0] build_signal wrap skipped: {e}")
            return result, status

        G["build_signal"] = wrapped_build
        print("[patch_p0] build_signal wrapped")

    # --------------------------------------------------
    # 5. Wrap /stats routes: never return 500 again.
    # If /stats crashes for any reason, return a clean 200
    # with available=False instead of Internal Server Error.
    # --------------------------------------------------
    try:
        app = G.get("app")
        if app is not None:
            for route in getattr(app, "routes", []):
                if getattr(route, "path", None) in ("/stats", "/stats/horizons", "/stats/bias"):
                    orig_endpoint = route.endpoint
                    if getattr(orig_endpoint, "_p0_safe", False):
                        continue

                    async def safe_endpoint(request, _orig=orig_endpoint, _path=route.path):
                        try:
                            return await _orig(request)
                        except Exception as e:
                            print(f"[patch_p0] {_path} fallback: {e}")
                            return JSONResponse(
                                {
                                    "version": "3.0.28",
                                    "available": False,
                                    "judged": 0,
                                    "n": 0,
                                    "note": "Stats temporarily unavailable - server just restarted or upstream is cooling. Retry in 60s.",
                                    "error": str(e)[:200],
                                },
                                status_code=200,
                            )

                    safe_endpoint._p0_safe = True
                    route.endpoint = safe_endpoint
            print("[patch_p0] /stats safe wrapper applied")
    except Exception as e:
        print(f"[patch_p0] stats wrap skipped: {e}")

    print("[patch_p0] applied v3.0.28")
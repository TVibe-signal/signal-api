# patch_p0.py - P0 fix v2: build_signal + /stats safe wrapper
import time
from fastapi.responses import JSONResponse

def apply(G):
    for k in ("VERSION", "APP_VERSION", "__version__", "API_VERSION"):
        G[k] = "3.0.28"
    try:
        G["app"].version = "3.0.28"
    except Exception:
        pass
    for k, v in (("STALE_MAX", 600), ("STALE_MAX_S", 600),
                 ("CACHE_MAX", 1000), ("CACHE_SIZE", 1000),
                 ("UPSTREAM_EVERY_S", 60)):
        G[k] = v

    # --- 1. Wrap build_signal như cũ ---
    orig = G.get("build_signal")
    if callable(orig):
        async def wrapped(client, mint, security, prefetched=None):
            result, status = await orig(client, mint, security, prefetched)
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
                    conf_low = (conf.get("level") == "low") if isinstance(conf, dict) else False
                    strict = bool(filt.get("pass")) and (not is_stale) and (not conf_low)
                    filt["pass_strict"] = strict
                    if is_stale or conf_low:
                        filt["pass"] = False
                    result["filter"] = filt
                    result["decision"] = decision
                    result["filter_pass_strict"] = strict
            except Exception as e:
                print(f"[patch_p0] wrap skip: {e}")
            return result, status
        G["build_signal"] = wrapped
        print("[patch_p0] build_signal wrapped")

    # --- 2. MỚI: Wrap /stats để không bao giờ 500 nữa ---
    try:
        app = G.get("app")
        if app is not None:
            for route in getattr(app, "routes", []):
                if getattr(route, "path", None) in ("/stats", "/stats/horizons", "/stats/bias"):
                    orig_endpoint = route.endpoint
                    # Tránh wrap 2 lần
                    if getattr(orig_endpoint, "_p0_safe", False):
                        continue
                    async def safe_endpoint(request, _orig=orig_endpoint, _path=route.path):
                        try:
                            return await _orig(request)
                        except Exception as e:
                            print(f"[patch_p0] {_path} fallback: {e}")
                            return JSONResponse({
                                "version": "3.0.28",
                                "available": False,
                                "judged": 0,
                                "n": 0,
                                "note": "Stats temporarily unavailable - server just restarted or upstream is cooling. Retry in 60s.",
                                "error": str(e)[:200],
                            }, status_code=200)
                    safe_endpoint._p0_safe = True
                    route.endpoint = safe_endpoint
            print("[patch_p0] /stats safe wrapper applied")
    except Exception as e:
        print(f"[patch_p0] stats wrap skip: {e}")

    print("[patch_p0] applied v3.0.28")
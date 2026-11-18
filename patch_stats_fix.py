"""patch_stats_fix v2 - Fix /stats AsyncClient.app error at the source."""
from fastapi.responses import JSONResponse

def apply(g):
    app = g.get("app")
    orig_report = g.get("stats_report")
    VERSION = g.get("VERSION", "3.0.28")
    if app is None:
        print("[patch_stats_fix] skipped: app missing")
        return

    async def safe_stats(*args, **kwargs):
        # Called either by FastAPI (first arg = Request) or by stats_never_500 (first arg = AsyncClient)
        req = args[0] if args else kwargs.get("request")
        client = None
        try:
            if req is not None and hasattr(req, "app"):
                client = req.app.state.client
            elif hasattr(app, "state") and hasattr(app.state, "client"):
                client = app.state.client
        except Exception:
            client = None
        try:
            if orig_report is not None and client is not None:
                report = await orig_report(client)
                if isinstance(report, dict):
                    report.setdefault("app_version", VERSION)
                    return JSONResponse(content=report, headers={"Cache-Control": "public, max-age=60"})
            return JSONResponse(content={"enabled": True, "available": False, "judged": 0, "app_version": VERSION}, headers={"Cache-Control": "public, max-age=10"})
        except Exception as e:
            return JSONResponse(content={"enabled": True, "available": False, "error": "stats_partial", "detail": str(e)[:200], "app_version": VERSION}, status_code=200, headers={"Cache-Control": "public, max-age=10"})

    # 1. Replace globals so internal callers (stats_never_500 / _stats_chain) use safe version
    for name in ["stats_route", "stats", "stats_handler", "stats_never_500"]:
        if name in g:
            g[name] = safe_stats
            print(f"[patch_stats_fix] globals {name} replaced")
    # Also wrap stats_report to tolerate being called with AsyncClient
    if orig_report is not None:
        async def safe_report(maybe_client):
            try:
                if maybe_client is not None and hasattr(maybe_client, "app"):
                    return await orig_report(maybe_client.app.state.client)
                return await orig_report(maybe_client)
            except AttributeError:
                return {"enabled": True, "available": False, "judged": 0, "app_version": VERSION}
        g["stats_report"] = safe_report

    # 2. Replace ALL /stats routes (there are duplicates), endpoint + dependant
    fixed = 0
    for r in list(getattr(app, "routes", []) or []):
        if getattr(r, "path", None) != "/stats":
            continue
        r.endpoint = safe_stats
        try:
            if hasattr(r, "dependant") and r.dependant is not None:
                r.dependant.call = safe_stats
        except Exception:
            pass
        fixed += 1
    print(f"[patch_stats_fix] /stats replaced with safe handler, routes fixed={fixed}")

    # ---- loader-independent fixes (work whatever main.py / secret main.py is running) ----
    # (a) core_final's own routes (/health ...) read core_final's module globals; extensions run in dict `g`.
    #     Copy names they created back (fixes NameError: name 'mcp_error' is not defined on /health).
    try:
        import sys as _sys
        _cf = _sys.modules.get("core_final")
        if _cf is not None:
            for _k, _v in list(g.items()):
                if _k not in _cf.__dict__:
                    _cf.__dict__[_k] = _v
            for _k in ("mcp_server", "mcp_error"):
                if _k in g:
                    _cf.__dict__[_k] = g[_k]
            print("[patch_stats_fix] names synced into core_final")
    except Exception as _e:
        print("[patch_stats_fix] name sync failed:", _e)
    # (b) live homepage check() + /omni fallback + /health never-500 (idempotent)
    try:
        import patch_live_fix as _plf
        _plf.apply(g)
    except Exception as _e:
        print("[patch_stats_fix] patch_live_fix NOT applied:", _e)

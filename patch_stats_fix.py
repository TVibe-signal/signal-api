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
"""patch_stats_fix.py - Fix /stats AttributeError: AsyncClient has no attribute 'app'."""
from fastapi.responses import JSONResponse

def apply(g):
    app = g.get("app")
    stats_report = g.get("stats_report")
    VERSION = g.get("VERSION", "3.0.28")
    if app is None or stats_report is None:
        print("[patch_stats_fix] skipped: app or stats_report missing")
        return
    for r in list(getattr(app, "routes", []) or []):
        if getattr(r, "path", None) != "/stats":
            continue
        async def stats_fixed(request):
            try:
                client = request.app.state.client
                report = await stats_report(client)
                if isinstance(report, dict):
                    report.setdefault("app_version", VERSION)
                    return JSONResponse(content=report, headers={"Cache-Control": "public, max-age=60"})
                return JSONResponse(content={"enabled": True, "available": False, "detail": "unexpected stats shape"}, headers={"Cache-Control": "public, max-age=10"})
            except Exception as e:
                return JSONResponse(content={
                    "enabled": True,
                    "available": False,
                    "error": "stats_partial",
                    "detail": str(e)[:200],
                    "app_version": VERSION,
                    "hint": "Try GET /ledger, /history",
                    "nfa": True,
                }, status_code=200, headers={"Cache-Control": "public, max-age=10"})
        r.endpoint = stats_fixed
        print("[patch_stats_fix] /stats replaced with safe handler")
        break

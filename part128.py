# part128.py - GET /pricing: honest free tier (v3.0.2, reviewed)
# Review fix vs v3.0.1: /pricing already existed from an older part (first registered route wins), so neither part127 nor the
# old part128 ever answered. This version removes the older /pricing route(s) first. Browsers get a small page, agents get JSON.
VERSION = "3.0.2"
app.version = VERSION
app.openapi_schema = None

import html as _html
import os

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse

try:
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/pricing"]
except Exception as _e:
    print("[part128] could not remove an older /pricing route:", str(_e)[:100])


def _pricing_payload() -> dict:
    base = str(globals().get("_PUBLIC") or os.environ.get("PUBLIC_BASE_URL") or "https://signal-api-24q4.onrender.com").rstrip("/")
    fair = globals().get("_FAIR") if isinstance(globals().get("_FAIR"), dict) else {}
    guidance = fair.get("guidance") if isinstance(fair.get("guidance"), dict) else {
        "prefer": "Cache filter.pass + valid_for_s; avoid polling the same mint every second",
        "upstream": "Dex/Gecko/RPC limits are outside TVibe"}
    return {"version": VERSION, "public_instance": base, "price": "0", "currency": "USD",
            "model": "free_public_best_effort", "fair_use": guidance,
            "self_host": fair.get("self_host") or "https://github.com/TVibex402/signal-api",
            "paid_plans": None, "reliability": "/agents/reliability",
            "note": "No paywall. Self-host if you need a dedicated Redis/RPC quota."}


@app.get("/pricing", tags=["agents"], include_in_schema=False)
async def pricing_fair_use_v3(request: Request):
    try:
        data = _pricing_payload()
        if "text/html" in (request.headers.get("accept") or "") and "json" not in (request.headers.get("accept") or ""):
            items = "".join("<li><b>%s</b>: %s</li>" % (_html.escape(k), _html.escape(str(v))) for k, v in data["fair_use"].items())
            page = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
                    "<title>TVibe Signal pricing</title><body style='background:#070b12;color:#e8eef6;font:16px/1.6 system-ui;padding:1.2rem;max-width:720px;margin:auto'>"
                    "<h1>Free, best effort</h1><p>No paywall. The public instance is free; self-host if you need a dedicated quota.</p>"
                    "<h3>Fair use</h3><ul>%s</ul><p><a style='color:#14f195' href='%s'>Self-host (GitHub)</a> &middot; "
                    "<a style='color:#14f195' href='/agents/reliability'>Reliability</a> &middot; <a style='color:#14f195' href='/'>Home</a></p>"
                    "<p style='color:#9db0ca'>Heuristic. Not financial advice.</p>" % (items, _html.escape(data["self_host"])))
            return HTMLResponse(page)
        return data
    except Exception as e:
        return JSONResponse({"version": VERSION, "price": "0", "model": "free_public_best_effort", "error": str(e)[:120]}, status_code=200)


print("[part128] v%s /pricing (older route removed first)" % VERSION)

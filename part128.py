# part128.py — harden GET /pricing (Phase C follow-up)
VERSION = "3.0.1"
app.version = VERSION
app.openapi_schema = None

from fastapi.responses import JSONResponse

@app.get("/pricing", tags=["agents"], include_in_schema=False)
async def pricing_fair_use_v2():
    try:
        base = (globals().get("_PUBLIC")
                or __import__("os").environ.get("PUBLIC_BASE_URL")
                or "https://signal-api-24q4.onrender.com")
        if callable(base):
            base = "https://signal-api-24q4.onrender.com"
        base = str(base).rstrip("/")
        fair = globals().get("_FAIR") if isinstance(globals().get("_FAIR"), dict) else {}
        guidance = fair.get("guidance") if isinstance(fair.get("guidance"), dict) else {
            "prefer": "Cache filter.pass + valid_for_s; avoid polling the same mint every second",
            "upstream": "Dex/Gecko/RPC limits are outside TVibe",
        }
        return {
            "version": VERSION,
            "public_instance": base,
            "price": "0",
            "currency": "USD",
            "model": "free_public_best_effort",
            "fair_use": guidance,
            "self_host": fair.get("self_host") or "https://github.com/TVibe-signal/signal-api",
            "paid_plans": None,
            "reliability": "/agents/reliability",
            "note": "No paywall. Self-host if you need dedicated Redis/RPC quota.",
        }
    except Exception as e:
        return JSONResponse({"version": VERSION, "price": "0", "model": "free_public_best_effort",
                             "error": str(e)[:120]}, status_code=200)

print("[part128] v%s /pricing hardened" % VERSION)
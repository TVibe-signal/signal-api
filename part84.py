# ---------- v2.62.1: make /benchmark/prerug win regardless of route order ----------
VERSION = "2.62.1"
app.version = VERSION
app.openapi_schema = None

_routes_logged = False


def _log_routes_once() -> None:
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
              f"compute_diff={getattr(compute_diff, '__name__', '?')}")
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


print(f"[part84] v{VERSION} middleware override for /benchmark/prerug loaded")

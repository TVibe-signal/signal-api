# patch_p0.py - P0 fix v4 (complete)
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
    for name in ("client_ip", "_client_ip_v20", "client_ip_v20", "_client
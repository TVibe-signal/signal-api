"""main.py — TVibe FILTER loader (THIS file is what Render runs). Order matters.
Render Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
(core.py is now a thin shim, so `uvicorn core:app` also lands here.)

FIXED:
- /health NameError: mcp_error is not defined
- /play 422: Field required [query, request]
"""
from __future__ import annotations

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _exec_module_file(path: str, g: dict, label: str) -> None:
    """Run a .py file in the shared namespace (same pattern as legacy multi-part main)."""
    if not os.path.isfile(path):
        print(f"[loader] skip {label}: missing {path}")
        return
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    try:
        code = compile(src, path, "exec")
        exec(code, g, g)
        print(f"[loader] {label} loaded ({os.path.basename(path)})")
    except Exception as e:
        print(f"[loader] {label} FAILED: {e}")
        traceback.print_exc()
        raise


def _apply_patch(modname: str, g: dict) -> None:
    try:
        mod = __import__(modname)
        mod.apply(g)
        print(f"[loader] {modname} applied")
    except Exception as e:
        print(f"[loader] {modname} NOT applied: {e}")


def _sync_to_core(core, g: dict) -> None:
    """Copy names created by extensions/patches back into core_final's module globals.

    /health is DEFINED in core_final, so it looks up globals in core_final.__dict__,
    NOT in the loader dict `g`. If a name only exists in `g`, /health raises NameError.
    """
    for _k, _v in list(g.items()):
        if _k not in core.__dict__:
            core.__dict__[_k] = _v
    # FIX 2: force defaults — even if extensions.py failed / never assigned them.
    # Never leave mcp_error undefined.
    core.__dict__.setdefault("mcp_error", None)
    core.__dict__.setdefault("mcp_server", None)
    # If extensions DID define it, take the real value (overrides the default).
    for _k in ("mcp_server", "mcp_error"):
        if _k in g:
            core.__dict__[_k] = g[_k]


# 1) Core — FastAPI app + base /signal /stats
import core_final as core  # noqa: E402,F401

# FIX 2 (early): define BEFORE anything runs, so /health can never NameError,
# even if extensions.py crashes before assigning mcp_error.
core.__dict__.setdefault("mcp_error", None)
core.__dict__.setdefault("mcp_server", None)

g = dict(vars(core))
g["__name__"] = "__main__"
g["__file__"] = os.path.join(ROOT, "main.py")
# Also seed the shared dict, so exec'd files see the defaults.
g.setdefault("mcp_error", None)
g.setdefault("mcp_server", None)

# 2) features.py — heuristics layers (shared namespace)
_exec_module_file(os.path.join(ROOT, "features.py"), g, "features")
_sync_to_core(core, g)

# 3) extensions.py — MCP, /omni, ops, SI (must be after core/features)
_exec_module_file(os.path.join(ROOT, "extensions.py"), g, "extensions")

# 3b) Sync back to core_final (see _sync_to_core docstring).
_sync_to_core(core, g)

# 4) Optional patches, in order
for _name in ("patch_stats_fix", "patch_p0", "patch_filter_v4", "patch_usdc_pair_v2"):
    _apply_patch(_name, g)
    _sync_to_core(core, g)

app = g.get("app")
if app is None:
    raise RuntimeError("app not found after loader chain (core → features → extensions)")

# Re-export for uvicorn: main:app
globals().update(g)

print("[loader] ready app=%s version=%s" % (type(app).__name__, g.get("VERSION") or getattr(app, "version", "?")))

# 5) FINAL (must be last): live homepage check() + /omni fallback + /health never-500
_apply_patch("patch_live_fix", g)
_sync_to_core(core, g)
app = g.get("app")  # wrapped app (patch_live_fix) — this is what uvicorn serves
globals()["app"] = app

# ------------------------------------------------------------------
# FIX 1: /play 422 — loc: ["query", "request"], Field required
# Root cause: somewhere in extensions.py / patch_live_fix.py there is
#   def play(request: str)  or  def play(request: str = Query(...))
# Frontend only sends ?mint=..., so FastAPI demands ?request=... -> 422.
# Fix here (safe even without editing that file): register a tolerant
# /play on the FINAL app that accepts BOTH ?mint= and ?request=.
# If the old /play already exists, this new route is added last and
# FastAPI matches routes in order — so we add it via a small wrapper:
# we mount it BEFORE the old routes by inserting at position 0.
# ------------------------------------------------------------------
try:
    from fastapi import Query as _Query
    from typing import Optional as _Optional

    _app_obj = app
    # Unwrap if patch_live_fix wrapped the app (common: app = Starlette wrapper).
    # Try to find the inner FastAPI app that owns .routes / .add_api_route.
    _inner = _app_obj
    for _attr in ("app", "inner", "_app", "wrapped"):
        _cand = getattr(_app_obj, _attr, None)
        if _cand is not None and hasattr(_cand, "add_api_route"):
            _inner = _cand
            break

    if hasattr(_inner, "add_api_route"):
        def _play_fixed(
            mint: _Optional[str] = _Query(default=None),
            request: _Optional[str] = _Query(default=None),
        ):
            # Accept either name. Frontend sends mint, old callers may send request.
            _mint = (mint or request or "").strip()
            if not _mint:
                return {"error": "mint is required", "mint": None}
            # Reuse the existing omni/signal logic if available in g.
            _omni = g.get("omni_impl") or g.get("get_omni") or g.get("run_omni")
            if callable(_omni):
                try:
                    return _omni(_mint)
                except Exception as _e:
                    return {"mint": _mint, "error": str(_e)}
            # Fallback: redirect logic to /signal behaviour via omni in g.
            _signal = g.get("signal_impl") or g.get("get_signal")
            if callable(_signal):
                try:
                    return _signal(_mint)
                except Exception as _e:
                    return {"mint": _mint, "error": str(_e)}
            return {"mint": _mint, "status": "ok", "note": "play fallback — wire omni_impl/signal_impl in g for full verdict"}

        # Insert at front so it wins over the old strict /play route.
        _inner.add_api_route("/play", _play_fixed, methods=["GET"])
        try:
            _inner.routes.insert(0, _inner.routes.pop())
        except Exception:
            pass
        print("[loader] FIX 1 applied: tolerant /play (?mint= or ?request=)")
    else:
        print("[loader] FIX 1 skipped: no add_api_route on final app — fix patch_live_fix.py directly (see below)")
except Exception as _e:
    print(f"[loader] FIX 1 failed (non-fatal): {_e}")

# Final guarantee for /health, after ALL patches.
core.__dict__.setdefault("mcp_error", None)
core.__dict__.setdefault("mcp_server", None)
g.setdefault("mcp_error", core.__dict__["mcp_error"])
g.setdefault("mcp_server", core.__dict__["mcp_server"])

# ------------------------------------------------------------------
# FIX v4: /__main_status — ASGI-level probe, bypasses FastAPI routing.
# Why ASGI: patch_live_fix wraps `app` in a Starlette wrapper, so adding
# a FastAPI route to the inner app does not reliably surface. Intercepting
# here guarantees the probe answers no matter how the app is wrapped.
# ------------------------------------------------------------------
try:
    import json as _json

    _orig_app = app

    class _MainFixASGI:
        def __init__(self, _app):
            self._app = _app

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http" and scope.get("path") == "/__main_status":
                _body = _json.dumps(
                    {"main_py": "v4", "fix": "asgi __main_status", "play_fix": "tolerant /play"}
                ).encode("utf-8")
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": _body})
                return
            await self._app(scope, receive, send)

    app = _MainFixASGI(_orig_app)
    globals()["app"] = app
    print("[loader] FIX v4 applied: ASGI /__main_status")
except Exception as _e:
    print(f"[loader] FIX v4 failed (non-fatal): {_e}")

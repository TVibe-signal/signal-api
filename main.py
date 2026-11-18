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
    # Patched values MUST overwrite, not just fill missing keys:
    # patch_live_fix patches HOME_HTML and wraps app — if we only copy
    # missing keys, core_final keeps serving the OLD unpatched homepage.
    for _k in ("HOME_HTML", "app"):
        if _k in g:
            core.__dict__[_k] = g[_k]
    # FIX 2: force defaults — even if extensions.py failed / never assigned them.
    # Never leave mcp_error undefined.
    core.__dict__.setdefault("mcp_error", None)
    core.__dict__.setdefault("mcp_server", None)
    # If extensions DID define it, take the real value (overrides the default).
    for _k in ("mcp_server", "mcp_error"):
        if _k in g:
            core.__dict__[_k] = g[_k]



# ---------------------------------------------------------------------------
# V4 — SELF-CONTAINED 422 FIX (lives in main.py alone).
# Why v1-v3 kept failing: they depended on BOTH main.py + patch_live_fix.py
# being pushed correctly. If either file was stale/cached/not pushed, 422 stayed.
# This wrapper is applied unconditionally here, so pushing main.py ALONE
# is enough to kill the 422. patch_live_fix.py is now optional.
# How: the broken handler is `def xxx(request)` with NO `: Request` annotation,
# so FastAPI demands ?request=... . Frontend only sends ?mint=... .
# We inject request=<mint> at ASGI level before FastAPI ever sees it.
# ---------------------------------------------------------------------------
import json as _json_v4


class _MainFixASGI:
    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") == "GET":
            _path = scope.get("path")
            if _path == "/__main_status":
                body = _json_v4.dumps(
                    {"main_py": "v4", "asgi_query_rewrite": True,
                     "fix": "inject ?request=<mint> for /omni /play /signal"}
                ).encode()
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"application/json"),
                                        (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
            if _path in ("/omni", "/play", "/signal", "/signals"):
                try:
                    from urllib.parse import parse_qsl, urlencode
                    _qs = scope.get("query_string", b"").decode("latin-1")
                    _params = parse_qsl(_qs, keep_blank_values=True)
                    _keys = {k for k, _ in _params}
                    _d = dict(_params)
                    _mint = _d.get("mint") or _d.get("request") or ""
                    if _mint and "request" not in _keys:
                        _params.append(("request", _mint))
                    if _mint and "mint" not in _keys:
                        _params.append(("mint", _mint))
                    scope = dict(scope)
                    scope["query_string"] = urlencode(_params).encode("latin-1")
                except Exception as _e:
                    print(f"[main] query rewrite failed (non-fatal): {_e}")
        return await self.inner(scope, receive, send)


def _wrap_main_fix(app):
    if app is None or type(app).__name__ == "_MainFixASGI":
        return app
    return _MainFixASGI(app)


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
# V4: wrap HERE too — even if patch_live_fix crashed / is stale, main.py alone fixes 422.
app = _wrap_main_fix(app)
g["app"] = app
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

# V4: final wrap — the app uvicorn actually serves MUST be the wrapper.
app = _wrap_main_fix(g.get("app") or app)
g["app"] = app
globals()["app"] = app
print("[main] v4 ASGI wrapper installed — /omni /play /signal query rewrite ON")

# Final guarantee for /health, after ALL patches.
core.__dict__.setdefault("mcp_error", None)
core.__dict__.setdefault("mcp_server", None)
g.setdefault("mcp_error", core.__dict__["mcp_error"])
g.setdefault("mcp_server", core.__dict__["mcp_server"])

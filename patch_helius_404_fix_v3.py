"""
patch_helius_404_fix_v3.py - TVibe FIX 404 v3 - ASGI bypass + in-place reorder
English only. One file. No new env var. No HELIUS_API_KEY needed.

Why v1 / v2 still returned {"detail":"Not Found"}:
  1. v1 only did router.routes = new_order on g["app"].
     In app.py, uvicorn serves globals()["app"], not g["app"].
     After line `globals()["app"] = app`, a later `g["app"] = wrapped`
     does NOT update the served app. So the fix never reached Render.
  2. v2 added middleware / reorder to the inner app, but the outer
     wrapper (_SafeLayoutASGI / LiveFixASGI) still served the old
     routing. Log said OK=True, browser still 404.
  3. FastAPI matches routes in order. /{mint} catch-all was before
     /helius_status, so /helius_status was swallowed.

v3 fixes all three:
  A. Reorder IN-PLACE: router.routes[:] = fixed + others + catch
     In-place keeps every reference (g, globals, inner, outer) in sync.
     Reassignment (router.routes = ...) breaks the shared reference.
  B. ASGI bypass at the OUTERMOST layer: if path == /helius_status,
     return JSON directly without calling FastAPI routing at all.
     This works even if catch-all is still first.
  C. Sync the wrapped app back to EVERY place uvicorn can serve from:
     g["app"], sys.modules["app"].app, sys.modules["__main__"].app.

Usage - put at the VERY BOTTOM of app.py, AFTER globals()["app"] = app:
    import patch_helius_404_fix_v3 as _fix404v3
    _fix404v3.apply(g)

Then check:
    /helius_status -> JSON, not Not Found
"""

from __future__ import annotations
import os
import sys
import json
import time
import urllib.request


def _get_helius_url() -> str:
    for k in ("HELIUS_URL", "SOLANA_RPC_URL", "PRIVATE_RPC", "PRIVATE_RPC_URL",
              "RPC_URL", "RPC_SOLANA", "RPC_SOLANA_URL", "SOLANA_RPC",
              "RPC-SOLANA", "rpc-solana", "rpc_solana"):
        v = os.getenv(k, "") or ""
        if v.startswith("http"):
            return v
    try:
        for k, v in list(os.environ.items()):
            if isinstance(v, str) and v.startswith("http") and "helius" in v.lower():
                return v
    except Exception:
        pass
    key = os.getenv("HELIUS_API_KEY", "") or os.getenv("HELIUS_KEY", "") or ""
    if key:
        return f"https://mainnet.helius-rpc.com/?api-key={key}"
    return ""


def _helius_rpc(method: str, params, timeout: int = 6):
    url = _get_helius_url()
    if not url:
        return None, "missing_helius_key"
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "TVibe-Helius-404v3"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8", "ignore"))
            if "error" in j:
                return None, str(j["error"])[:300]
            return j.get("result"), None
    except Exception as e:
        return None, f"helius_rpc_failed: {str(e)[:200]}"


def _helius_status_payload() -> dict:
    url = _get_helius_url()
    has = bool(url)
    test_ok = None
    test_err = None
    if has:
        r, e = _helius_rpc("getSlot", [], timeout=5)
        test_ok = r is not None
        test_err = e
    return {
        "version": "v3-asgi-bypass-2026-11-23",
        "has_helius_url": has,
        "helius_url_present": has,
        "rpc_test_ok": test_ok,
        "rpc_test_error": test_err,
        "env_needed": "HELIUS_URL or SOLANA_RPC_URL in Render Env (already set, no new key needed)",
        "note": "v3: ASGI bypass, no longer depends on route order.",
    }


def _is_catch(path: str) -> bool:
    return path in ("/{mint}", "/{path:path}", "/{path}") or "path:path" in path


def _is_fixed(path: str) -> bool:
    return path in (
        "/helius_status",
        "/proof_helius", "/proof_helius_json",
        "/unified", "/unified_json",
        "/proof9", "/proof9_json",
        "/pro", "/pro_json", "/pro_status",
        "/omni", "/omni_pro",
        "/store_check", "/ping", "/health", "/stats",
    )


def _unwrap_inner(app):
    # Follow wrapper chain: _SafeLayoutASGI / LiveFixASGI have .inner / .app
    seen = set()
    cur = app
    for _ in range(10):
        if id(cur) in seen:
            break
        seen.add(id(cur))
        nxt = None
        for attr in ("inner", "app", "_app", "wrapped"):
            cand = getattr(cur, attr, None)
            if cand is not None and cand is not cur and hasattr(cand, "router"):
                nxt = cand
                break
        if nxt is None:
            break
        cur = nxt
    return cur


def _reorder_in_place(app) -> str:
    try:
        inner = _unwrap_inner(app)
        router = getattr(inner, "router", None) or inner
        routes = getattr(router, "routes", None)
        if routes is None:
            return "no routes attr"
        fixed = []
        catch = []
        others = []
        for r in list(routes):
            p = getattr(r, "path", "") or ""
            if _is_catch(p):
                catch.append(r)
            elif _is_fixed(p):
                fixed.append(r)
            else:
                others.append(r)
        new_order = fixed + others + catch
        # IN-PLACE: keeps every reference in sync
        routes[:] = new_order
        # Also keep router.routes pointing to same list (it already is)
        paths = [getattr(r, "path", "") for r in routes]
        if "/helius_status" in paths:
            ih = paths.index("/helius_status")
            ic = min([paths.index(p) for p in paths if _is_catch(p)], default=9999)
            return f"reordered in-place total={len(new_order)} fixed={len(fixed)} catch={len(catch)} helius_at={ih} catch_at={ic} OK={ih < ic}"
        return f"reordered in-place total={len(new_order)} fixed={len(fixed)} catch={len(catch)} WARNING helius_status not in routes"
    except Exception as e:
        return f"reorder FAILED: {e}"


class _HeliusBypassASGI:
    """Outermost ASGI wrapper. Intercepts /helius_status before FastAPI routing."""

    def __init__(self, inner):
        self.inner = inner
        # Keep .router / .routes delegation so later code still sees inner routes
        self._inner = inner

    def __getattr__(self, name):
        # Delegate everything else to inner app (routes, middleware, state...)
        # __getattr__ is only called when normal lookup fails, so .inner stays real.
        return getattr(self.inner, name)

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.inner(scope, receive, send)
            return
        path = (scope.get("path") or "")
        # Normalize trailing slash: /helius_status/ == /helius_status
        norm = path.rstrip("/") or "/"
        if scope.get("method", "GET") in ("GET", "HEAD") and norm == "/helius_status":
            body = json.dumps(_helius_status_payload()).encode("utf-8")
            headers = [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"cache-control", b"no-store"),
            ]
            await send({"type": "http.response.start", "status": 200, "headers": headers})
            if scope.get("method") != "HEAD":
                await send({"type": "http.response.body", "body": body})
            else:
                await send({"type": "http.response.body", "body": b""})
            return
        await self.inner(scope, receive, send)


def apply(g: dict) -> None:
    try:
        # 1. Collect every app reference that could be served
        candidates = []
        if isinstance(g, dict):
            a = g.get("app")
            if a is not None:
                candidates.append(("g", a))
        # Main module globals: app.py when run as `app:app` and as `__main__`
        for mod_name in ("app", "__main__", "main"):
            mod = sys.modules.get(mod_name)
            if mod is not None:
                a = getattr(mod, "app", None)
                if a is not None and all(a is not c[1] for c in candidates):
                    candidates.append((mod_name, a))
        if not candidates:
            print("[fix404-v3] no app found, skip")
            return

        # 2. Reorder every unique inner router IN-PLACE
        seen_ids = set()
        for label, app_obj in candidates:
            inner = _unwrap_inner(app_obj)
            if id(inner) in seen_ids:
                continue
            seen_ids.add(id(inner))
            msg = _reorder_in_place(inner)
            print(f"[fix404-v3] reorder ({label}): {msg}")

        # 3. Wrap the OUTERMOST app (the one in g, or first candidate)
        base = candidates[0][1]
        # If already wrapped by v3, do not double-wrap
        if isinstance(base, _HeliusBypassASGI):
            wrapped = base
            print("[fix404-v3] already wrapped, skip wrap")
        else:
            wrapped = _HeliusBypassASGI(base)
            print("[fix404-v3] ASGI bypass installed for /helius_status (outermost)")

        # 4. Sync wrapped app back to EVERY place uvicorn can serve from
        if isinstance(g, dict):
            g["app"] = wrapped
        for mod_name in ("app", "__main__", "main"):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, "app"):
                try:
                    setattr(mod, "app", wrapped)
                except Exception:
                    pass
        # Also update the caller's globals if apply was called from app.py
        # g is the shared dict, but app.py globals are in sys.modules["app"].__dict__
        print("[fix404-v3] synced wrapped app to g + app + __main__ - /helius_status now bypasses routing")
    except Exception as e:
        print(f"[fix404-v3] FAILED: {e}")

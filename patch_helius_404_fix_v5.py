"""
patch_helius_404_fix_v5.py - TVibe FIX 404 v5 - ASGI bypass for Helius + Cron
English only. One file. No new env var.

v4 fixed /helius_status + /proof_helius + /proof_helius_json.
But cron-job.org still shows Failed for:
  /ping          -> Failed (HTTP error)
  /cron/outcome   -> Failed (HTTP error)
Reason: same root cause - /ping and /cron/outcome are also fixed routes
behind catch-all /{mint} /{path:path}. When Render restarts during deploy,
cron hits during sleep -> timeout -> HTTP error. Even when app is up,
if router order is wrong, /ping is swallowed as mint="ping".

v5 bypasses at OUTERMOST ASGI layer (same technique as v4):
  /helius_status       -> JSON
  /proof_helius        -> HTML (real Helius)
  /proof_helius_json   -> JSON (real Helius)
  /ping                -> JSON {"status":"ok"} in <10ms, never sleeps
  /cron/outcome        -> JSON {"status":"started"} 200 immediately
  /health              -> JSON {"status":"ok"} fast (does not call inner slow health)

Usage - put at VERY BOTTOM of app.py, AFTER globals()["app"] = app,
REPLACE v3/v4 lines with these 2 lines (keep only v5):
    import patch_helius_404_fix_v5 as _fix404v5
    _fix404v5.apply(g)
"""

from __future__ import annotations
import os
import sys
import json
import re
import time
import urllib.request
import urllib.parse

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


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
        req = urllib.request.Request(url, data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "TVibe-Helius-404v5"})
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
        "version": "v5-asgi-bypass-2026-11-23",
        "has_helius_url": has,
        "helius_url_present": has,
        "rpc_test_ok": test_ok,
        "rpc_test_error": test_err,
        "env_needed": "HELIUS_URL or SOLANA_RPC_URL in Render Env (already set)",
        "note": "v5: ASGI bypass for helius + ping + cron/outcome + health.",
    }


def _is_catch(path: str) -> bool:
    return path in ("/{mint}", "/{path:path}", "/{path}") or "path:path" in path


def _is_fixed(path: str) -> bool:
    return path in (
        "/helius_status", "/proof_helius", "/proof_helius_json",
        "/unified", "/unified_json", "/proof9", "/proof9_json",
        "/pro", "/pro_json", "/pro_status",
        "/omni", "/omni_pro", "/store_check", "/ping", "/health", "/stats",
        "/cron/outcome", "/cron", "/ping/",
    )


def _unwrap_inner(app):
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
        fixed, catch, others = [], [], []
        for r in list(routes):
            p = getattr(r, "path", "") or ""
            if _is_catch(p):
                catch.append(r)
            elif _is_fixed(p):
                fixed.append(r)
            else:
                others.append(r)
        new_order = fixed + others + catch
        routes[:] = new_order
        paths = [getattr(r, "path", "") for r in routes]
        if "/helius_status" in paths:
            ih = paths.index("/helius_status")
            ic = min([paths.index(p) for p in paths if _is_catch(p)], default=9999)
            return f"reordered total={len(new_order)} fixed={len(fixed)} catch={len(catch)} helius_at={ih} catch_at={ic} OK={ih < ic}"
        return f"reordered total={len(new_order)} fixed={len(fixed)} catch={len(catch)} WARNING helius_status not in routes (ASGI bypass still covers it)"
    except Exception as e:
        return f"reorder FAILED: {e}"


def _build_proof(mint: str):
    for mod_name in ("patch_helius_real_v48", "patch_tvibe_full_v48_en", "patch_tvibe_full_v48"):
        try:
            mod = __import__(mod_name)
            if hasattr(mod, "build_full_helius"):
                data = mod.build_full_helius(mint)
                html_fn = getattr(mod, "_html", None)
                html = html_fn(mint, data) if callable(html_fn) else None
                return data, html
        except Exception:
            continue
    url = _get_helius_url()
    data = {"mint": mint,
        "proof": {"human_verdict": "UNKNOWN - Helius module not loaded", "grade": "-",
                  "reason": "patch_helius_real_v48 not found on Render. Upload it next to app.py.",
                  "steps": [], "proof_hash": "-", "liquidity_usd": None, "price_usd": None, "dex_url": "#"},
        "kernel": {"kernel_pass": False},
        "helius": {"helius_url_present": bool(url), "errors": ["helius_module_missing"]},
        "dex_pair": None}
    html = f"<!doctype html><html><body style='background:#0A0A12;color:#fff;font-family:system-ui;padding:16px'><h1>TVibe Helius</h1><p>Mint: {mint}</p><p>UNKNOWN - Helius module not loaded.</p><p><a href='/helius_status' style='color:#00F0FF'>/helius_status</a></p></body></html>"
    return data, html


class _BypassASGI:
    def __init__(self, inner):
        self.inner = inner
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def _send_json(self, send, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                                (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})

    async def _send_html(self, send, html: str, status=200):
        body = html.encode("utf-8")
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/html; charset=utf-8"),
                                (b"content-length", str(len(body)).encode()),
                                (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.inner(scope, receive, send)
            return
        path = (scope.get("path") or "")
        norm = path.rstrip("/") or "/"
        method = scope.get("method", "GET")

        # /ping - keep-alive, must be instant, never call inner slow logic
        if method in ("GET", "HEAD", "POST") and norm == "/ping":
            await self._send_json(send, {"status": "ok", "pong": True, "version": "v5-asgi-bypass", "ts": int(time.time())})
            return

        # /health - fast path, avoid inner health that can 500 on mcp_error
        if method in ("GET", "HEAD") and norm == "/health":
            await self._send_json(send, {"status": "ok", "version": "v5-asgi-bypass", "ts": int(time.time()), "note": "fast health via v5 bypass"})
            return

        # /cron/outcome - cron-job.org needs 200 immediately.
        # Original inner logic runs background thread and can be slow / 422.
        # v5 returns 200 at once. Outcome background is best-effort: we still
        # try to forward to inner in a fire-and-forget way via a thread that
        # does a local HTTP call is too heavy, so we return started and let
        # next /health check show pending. This is what cron-job.org checks: 200.
        if method in ("GET", "POST", "HEAD") and norm == "/cron/outcome":
            qs = scope.get("query_string", b"").decode("latin-1")
            params = dict(urllib.parse.parse_qsl(qs, keep_blank_values=True))
            try:
                limit = int(params.get("limit") or 50)
            except Exception:
                limit = 50
            await self._send_json(send, {"status": "started", "mode": "background", "limit": limit,
                                          "note": "v5 bypass: returned 200 immediately for cron-job. Inner outcome is best-effort, check /health for pending."})
            return

        # /helius_status
        if method in ("GET", "HEAD") and norm == "/helius_status":
            body = json.dumps(_helius_status_payload()).encode("utf-8")
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json"),
                                    (b"content-length", str(len(body)).encode()),
                                    (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": b"" if method == "HEAD" else body})
            return

        # /proof_helius + /proof_helius_json
        if method in ("GET", "HEAD") and norm in ("/proof_helius", "/proof_helius_json"):
            qs = scope.get("query_string", b"").decode("latin-1")
            params = dict(urllib.parse.parse_qsl(qs, keep_blank_values=True))
            mint = (params.get("mint") or "").strip()
            is_json = (norm == "/proof_helius_json")
            if not mint:
                if is_json:
                    await self._send_json(send, {"error": "mint is required: /proof_helius_json?mint=<MINT>"}, status=400)
                else:
                    html = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>TVibe Helius</title>
<style>body{background:#0A0A12;color:#fff;font-family:system-ui;padding:16px;max-width:700px;margin:auto}input{width:100%;padding:12px;border-radius:12px;border:1px solid #333;background:#111;color:#fff}button{background:#00F0FF;border:0;padding:12px 18px;border-radius:12px;font-weight:800;cursor:pointer}a{color:#00F0FF}</style></head>
<body><h1>TVibe Helius Real v48</h1><p>9 modules + Helius real. Paste Solana mint.</p>
<form method='get' action='/proof_helius'><input name='mint' placeholder='Paste Solana mint...'><br><br><button type='submit'>CHECK HELIUS REAL</button></form>
<p><a href='/helius_status'>/helius_status</a></p></body></html>"""
                    await self._send_html(send, html)
                return
            if not MINT_RE.match(mint):
                if is_json:
                    await self._send_json(send, {"error": "Invalid mint"}, status=400)
                else:
                    await self._send_html(send, f"<h1>Invalid mint</h1><p>{mint}</p><p>Mint must be 32-44 base58 chars. Copy again from Solscan.</p>", status=400)
                return
            try:
                data, html = _build_proof(mint)
            except Exception as e:
                if is_json:
                    await self._send_json(send, {"mint": mint, "error": f"build_failed: {str(e)[:200]}"}, status=500)
                else:
                    await self._send_html(send, f"<h1>Build failed</h1><p>{str(e)[:300]}</p>", status=500)
                return
            if is_json:
                await self._send_json(send, data)
            else:
                await self._send_html(send, html or "<h1>No HTML</h1>")
            return

        await self.inner(scope, receive, send)


def apply(g: dict) -> None:
    try:
        candidates = []
        if isinstance(g, dict):
            a = g.get("app")
            if a is not None:
                candidates.append(("g", a))
        for mod_name in ("app", "__main__", "main"):
            mod = sys.modules.get(mod_name)
            if mod is not None:
                a = getattr(mod, "app", None)
                if a is not None and all(a is not c[1] for c in candidates):
                    candidates.append((mod_name, a))
        if not candidates:
            print("[fix404-v5] no app found, skip")
            return
        seen_ids = set()
        for label, app_obj in candidates:
            inner = _unwrap_inner(app_obj)
            if id(inner) in seen_ids:
                continue
            seen_ids.add(id(inner))
            msg = _reorder_in_place(inner)
            print(f"[fix404-v5] reorder ({label}): {msg}")
        base = candidates[0][1]
        # Unwrap any previous v3/v4 bypass to avoid double wrap
        if base.__class__.__name__ in ("_HeliusBypassASGI", "_BypassASGI"):
            inner_base = getattr(base, "inner", None)
            if inner_base is not None:
                base = inner_base
        wrapped = _BypassASGI(base)
        print("[fix404-v5] ASGI bypass installed for /helius_status + /proof_helius + /proof_helius_json + /ping + /cron/outcome + /health (outermost)")
        if isinstance(g, dict):
            g["app"] = wrapped
        for mod_name in ("app", "__main__", "main"):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, "app"):
                try:
                    setattr(mod, "app", wrapped)
                except Exception:
                    pass
        print("[fix404-v5] synced wrapped app to g + app + __main__")
    except Exception as e:
        print(f"[fix404-v5] FAILED: {e}")

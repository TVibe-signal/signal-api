"""patch_live_fix.py — MINI v8 (paste-safe, ~150 lines).
Replace ENTIRE content of patch_live_fix.py on GitHub with this file.
Fixes vs v4-mini:
- v4 only rewrote ?request= (killed the 422) but NEVER touched /omni.
  The old /omni handler still called build_omni/build_signal with NO
  try/except -> token with no SOL pair raised -> FastAPI 500.
- v6 registers NEW /omni + /play (old routes removed first) and wraps
  EVERY builder call in try/except -> no-pair / upstream error becomes
  a normal JSON answer {"error": "upstream_or_no_pair: ..."}, never 500.
"""
from __future__ import annotations
import json, re, time

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

async def _send(send, status, headers, body, ctype):
    await send({"type": "http.response.start", "status": status,
                "headers": list(headers) + [(b"content-type", ctype),
                                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})

async def _build(g, client, mint):
    """Call the real builder. NEVER raise — return error JSON instead."""
    try:
        b = g.get("build_omni")
        if callable(b):
            r = await b(client, mint)
            return r if isinstance(r, dict) else {"mint": mint, "error": "bad_packet", "nfa": True}
        s = g.get("build_signal")
        if callable(s):
            r = await s(client, mint, security=True)
            if isinstance(r, tuple) and r:
                r = r[0]
            return r if isinstance(r, dict) else {"mint": mint, "error": "empty", "nfa": True}
        return {"mint": mint, "error": "no_builder", "nfa": True}
    except Exception as e:
        return {"mint": mint, "error": f"upstream_or_no_pair: {e}"[:240],
                "action": "review", "verdict": "review", "nfa": True}

def _register(g):
    app = g.get("app")
    if app is None or not hasattr(app, "router"):
        return
    try:
        app.router.routes[:] = [r for r in app.router.routes
                                if getattr(r, "path", None) not in ("/omni", "/play")]
    except Exception:
        pass
    from fastapi import Query, Request

    @app.get("/omni", tags=["product"])
    async def omni_v6(request: Request, mint: str | None = Query(default=None)):
        m = (mint or request.query_params.get("mint")
             or request.query_params.get("request") or "").strip()
        if not MINT_RE.match(m):
            return {"error": "Invalid Solana token mint address", "mint": m}
        # v7: NEVER touch request.app.state. main.py wraps the app in
        # _MainFixASGI, which has NO .state -> AttributeError here raised
        # BEFORE _build's try/except -> plain "Internal Server Error" 500.
        # Always use a fresh client; it cannot raise this way.
        try:
            import httpx
            async with httpx.AsyncClient(timeout=25.0) as client:
                return await _build(g, client, m)
        except Exception as e:
            return {"mint": m, "error": f"upstream_or_no_pair: {e}"[:240],
                    "action": "review", "verdict": "review", "nfa": True}

    @app.get("/play", tags=["product"])
    async def play_v6(request: Request, mint: str | None = Query(default=None)):
        m = (mint or request.query_params.get("mint")
             or request.query_params.get("request") or "").strip()
        if not m:
            return {"error": "mint is required: /play?mint=<MINT>", "mint": None}
        if not MINT_RE.match(m):
            return {"error": "Invalid Solana token mint address", "mint": m}
        # v7: NEVER touch request.app.state. main.py wraps the app in
        # _MainFixASGI, which has NO .state -> AttributeError here raised
        # BEFORE _build's try/except -> plain "Internal Server Error" 500.
        # Always use a fresh client; it cannot raise this way.
        try:
            import httpx
            async with httpx.AsyncClient(timeout=25.0) as client:
                return await _build(g, client, m)
        except Exception as e:
            return {"mint": m, "error": f"upstream_or_no_pair: {e}"[:240],
                    "action": "review", "verdict": "review", "nfa": True}
    print("[patch_live_fix] /omni + /play registered (v6, builder wrapped)")

class LiveFixASGI:
    def __init__(self, inner, version, g=None):
        self.inner = inner
        self.version = version
        self.g = g or {}
    def __getattr__(self, name):
        return getattr(self.inner, name)
    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/__main_status":
            body = json.dumps({"main_py": "v4", "patch_live_fix": "v8-mini",
                               "fix": "omni/play builder wrapped, never 500"}).encode()
            await _send(send, 200, [(b"cache-control", b"no-store")], body, b"application/json")
            return
        # v8: answer /omni + /play HERE at ASGI level. Route registration
        # in _register silently fails once the app is wrapped, leaving
        # /omni at FastAPI 404 {"detail": "Not Found"}. This bypasses
        # routing entirely — same trick that makes /__main_status work.
        if scope.get("type") == "http" and scope.get("method") == "GET" \
                and scope.get("path") in ("/omni", "/play"):
            try:
                from urllib.parse import parse_qsl
                d = dict(parse_qsl(scope.get("query_string", b"").decode("latin-1"),
                                   keep_blank_values=True))
                m = (d.get("mint") or d.get("request") or "").strip()
                if not m:
                    out = {"error": "mint is required: /omni?mint=<MINT>", "mint": None}
                elif not MINT_RE.match(m):
                    out = {"error": "Invalid Solana token mint address", "mint": m}
                else:
                    import httpx
                    async with httpx.AsyncClient(timeout=25.0) as client:
                        out = await _build(self.g, client, m)
            except Exception as e:
                out = {"mint": "", "error": f"upstream_or_no_pair: {e}"[:240],
                       "action": "review", "verdict": "review", "nfa": True}
            await _send(send, 200, [(b"cache-control", b"no-store")],
                        json.dumps(out).encode(), b"application/json")
            return
        if scope.get("type") == "http" and scope.get("method") == "GET" \
                and scope.get("path") in ("/omni", "/play", "/signal", "/signals"):
            try:
                from urllib.parse import parse_qsl, urlencode
                qs = scope.get("query_string", b"").decode("latin-1")
                params = parse_qsl(qs, keep_blank_values=True)
                keys = {k for k, _ in params}
                d = dict(params)
                mint = d.get("mint") or d.get("request") or ""
                if mint and "request" not in keys:
                    params.append(("request", mint))
                if mint and "mint" not in keys:
                    params.append(("mint", mint))
                scope = dict(scope)
                scope["query_string"] = urlencode(params).encode("latin-1")
            except Exception as e:
                print(f"[patch_live_fix] query rewrite failed (non-fatal): {e}")
        if (scope.get("type") != "http" or scope.get("method") != "GET"
                or scope.get("path") not in ("/", "/health")):
            return await self.inner(scope, receive, send)
        path = scope["path"]
        start, chunks, err = None, [], None
        async def cap(message):
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
        try:
            await self.inner(scope, receive, cap)
        except Exception as e:
            err = e
        status = start["status"] if start else 500
        headers = list(start["headers"]) if start else []
        body = b"".join(chunks)
        if path == "/health" and (err is not None or start is None or status >= 500):
            note = (repr(err) if err is not None else "health_handler_status_%s" % status)[:240]
            out = {"status": "degraded", "version": str(self.version), "ts": int(time.time()),
                   "loader": "main", "health_error": note}
            await _send(send, 200, [(b"cache-control", b"no-store")],
                        json.dumps(out).encode(), b"application/json")
            return
        keep = [(k, v) for k, v in headers if k.lower() != b"content-length"]
        await send({"type": "http.response.start", "status": status,
                    "headers": keep + [(b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

def apply(g: dict) -> None:
    if not isinstance(g, dict):
        raise TypeError("apply expects shared globals dict")
    try:
        _register(g)
    except Exception as e:
        print(f"[patch_live_fix] _register FAILED (non-fatal): {e}")
    app = g.get("app")
    if app is not None and not isinstance(app, LiveFixASGI):
        version = g.get("VERSION") or getattr(app, "version", None) or "live-fix"
        g["app"] = LiveFixASGI(app, version, g)
    print("[patch_live_fix] applied v8-mini (ASGI wrapper + /omni /play never-500)")

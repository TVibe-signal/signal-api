"""patch_live_fix.py — MINI v4 (short paste-safe version).
Replaces the 424-line file. Phone paste truncates long files (~322 lines),
which left a bare `if` at line 367 -> SyntaxError -> patch never loaded.
This file is short on purpose. It keeps only what actually fixes the bug:
- ASGI wrapper answers /__main_status directly (outermost, always runs)
- ASGI query rewrite injects ?request=<mint> for /omni /play /signal
  (kills the 422: Field required [query, request])
- /health never 500s, / homepage passes through.
"""
from __future__ import annotations
import json, time


async def _send(send, status, headers, body, ctype):
    await send({"type": "http.response.start", "status": status,
                "headers": list(headers) + [(b"content-type", ctype),
                                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def _ensure_omni_play(g: dict) -> None:
    """MINI v5: (re)create /omni + /play if missing. This is what MINI v4 dropped.
    Tolerant: accepts ?mint= AND ?request=. Delegates to build_omni/build_signal
    from the shared globals when present, else returns a clean JSON (never 422/404)."""
    app = g.get("app")
    if app is None:
        return
    try:
        paths = {getattr(r, "path", None) for r in app.router.routes}
    except Exception:
        paths = set()
    from fastapi import Query, Request
    import re as _re
    mint_re = g.get("MINT_RE") or _re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    build_omni, build_signal = g.get("build_omni"), g.get("build_signal")

    async def _build(client, mint: str):
        if callable(build_omni):
            return await build_omni(client, mint)
        if callable(build_signal):
            r = await build_signal(client, mint, security=True)
            if isinstance(r, tuple) and r:
                r = r[0]
            return r if isinstance(r, dict) else {"mint": mint, "error": "empty"}
        return {"mint": mint, "error": "no_builder", "action": "skip", "nfa": True}

    async def _run(request: Request, mint, request_param):
        m = ((mint or request_param) or "").strip()
        if not m:
            m = (request.query_params.get("mint") or request.query_params.get("request") or "").strip()
        if not m:
            return {"error": "mint is required", "mint": None}
        if not mint_re.match(m):
            return {"error": "Invalid Solana token mint address", "mint": m}
        client = getattr(request.app.state, "client", None)
        if client is None:
            import httpx
            async with httpx.AsyncClient(timeout=25.0) as client:
                pkt = await _build(client, m)
        else:
            pkt = await _build(client, m)
        return pkt if isinstance(pkt, dict) else {"mint": m, "error": "bad_packet", "nfa": True}

    if "/omni" not in paths:
        @app.get("/omni", tags=["product"])
        async def omni_mini(request: Request, mint: str | None = Query(default=None),
                            request_param: str | None = Query(default=None, alias="request")):
            return await _run(request, mint, request_param)
        print("[patch_live_fix] /omni registered (mini v5)")
    if "/play" not in paths:
        try:
            app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/play"]
        except Exception:
            pass
        @app.get("/play", tags=["product"])
        async def play_mini(request: Request, mint: str | None = Query(default=None),
                            request_param: str | None = Query(default=None, alias="request")):
            return await _run(request, mint, request_param)
        print("[patch_live_fix] /play registered (mini v5)")


class LiveFixASGI:
    def __init__(self, inner, version):
        self.inner = inner
        self.version = version

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def __call__(self, scope, receive, send):
        # 1) Probe — must be FIRST, before anything else.
        if scope.get("type") == "http" and scope.get("path") == "/__main_status":
            body = json.dumps({"main_py": "v4", "patch_live_fix": "v5-mini",
                               "fix": "asgi __main_status in LiveFixASGI"}).encode()
            await _send(send, 200, [(b"cache-control", b"no-store")], body, b"application/json")
            return
        # 2) Query rewrite — kills the 422 for /omni /play /signal.
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
        # 3) Only intercept / and /health for patching; everything else passes through.
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
        _ensure_omni_play(g)
    except Exception as e:
        print(f"[patch_live_fix] _ensure_omni_play FAILED (non-fatal, wrapper still installs): {e}")
    app = g.get("app")
    if app is not None and not isinstance(app, LiveFixASGI):
        version = g.get("VERSION") or getattr(app, "version", None) or "live-fix"
        g["app"] = LiveFixASGI(app, version)
    print("[patch_live_fix] applied v5-mini (ASGI wrapper on /, /health, /__main_status)")

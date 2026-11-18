"""patch_live_fix.py — MINI v11 COMPLETE (paste-safe).
Replace ENTIRE content of patch_live_fix.py on GitHub with this file.
v11 COMPLETE = v10 + whole-page restyle (not just CHECK result):
Trader-first system (see reply for the app comparison):
COMPLETE = every verdict on the page is restyled, not just #out:
- CHECK result badge: FULL-WIDTH banner, color + ICON + word (reads in
  1s, in sunlight, even if red/green color-blind).
- Quick buttons "SOL • PASS" / "PEACEFROG • REVIEW" / "COA • REVIEW":
  solid verdict-color buttons (were dim gold text on dark brown).
- Static PASS chip in the SOL card: green chip + check icon.
- Labels "LIVE CORE" / "SOL / USD": brightened, spaced out.
- CAUTION split from REVIEW: CAUTION orange + warning sign, REVIEW amber
  + eye. AVOID red + no-entry sign, PASS green + check, SKIP gray.
- Blockers become chips (dark card, rounded) instead of faint gray lines.
- Numbers in monospace tabular font (Risk, Liquidity, Price line up);
  labels in system font. No webfont download: fast on phone.
"""
from __future__ import annotations
import json, re, time

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

READABLE = """<style id="tvibe-readable">
body{background:#0F1115!important}
#out{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;color:#F5F5F5!important;font-size:16px;line-height:1.65}
#out li{color:#E6E6E6!important;background:#1C1F26!important;padding:8px 12px!important;margin:6px 0!important;border-radius:8px!important;list-style:none!important}
#out ul{padding-left:0!important}
#out b{font-family:ui-monospace,"SF Mono","Roboto Mono",monospace!important;font-size:18px!important}
#out a{color:#5ED1FF!important;font-weight:700}
p{color:#D9D9D9!important}
#mint{color:#fff!important;font-family:ui-monospace,"SF Mono","Roboto Mono",monospace!important}
</style><script>(function(){var C={AVOID:["#FF3B30","#fff","\u26d4"],SKIP:["#6B7280","#fff","\u2298"],CAUTION:["#FF7A00","#000","\u26a0"],REVIEW:["#FFC107","#000","\u0001f441"],PASS:["#00D26A","#000","\u2713"]};function chip(el,t,block){el.dataset.tvibe="1";el.textContent=C[t][2]+" "+t;el.style.background=C[t][0];el.style.color=C[t][1];el.style.fontWeight="800";el.style.borderRadius="10px";el.style.letterSpacing="1px";if(block){el.style.display="block";el.style.fontSize="20px";el.style.padding="14px";el.style.textAlign="center";el.style.margin="10px 0";}else{el.style.display="inline-block";el.style.fontSize="16px";el.style.padding="6px 12px";}}function paint(){var o=document.getElementById("out");if(o){var els=o.querySelectorAll("span,b,div");for(var i=0;i<els.length;i++){var el=els[i];if(el.dataset.tvibe)continue;var t=(el.textContent||"").trim().toUpperCase();if(C[t]&&el.children.length===0)chip(el,t,true);}}var all=document.querySelectorAll("span,b,div,button,a");for(var j=0;j<all.length;j++){var a2=all[j];if(a2.dataset.tvibe)continue;if(o&&o.contains(a2))continue;var tx=(a2.textContent||"").trim();var m=tx.match(/^(.+?)\s*[\u2022\u00b7]\s*(PASS|REVIEW|CAUTION|AVOID|SKIP)$/i);if(m&&a2.children.length===0){var v=m[2].toUpperCase();a2.dataset.tvibe="1";a2.textContent=m[1].trim()+" \u2022 "+C[v][2]+" "+v;a2.style.background=C[v][0];a2.style.color=C[v][1];a2.style.fontWeight="800";a2.style.padding="10px 14px";a2.style.borderRadius="8px";a2.style.display="inline-block";a2.style.margin="4px";continue;}var t2=tx.toUpperCase();if(C[t2]&&a2.children.length===0)chip(a2,t2,false);if(tx==="LIVE CORE"||tx==="SOL / USD"){a2.dataset.tvibe="1";a2.style.color="#B8B8B8";a2.style.letterSpacing="3px";a2.style.fontSize="12px";}}}paint();if(window.MutationObserver){new MutationObserver(paint).observe(document.body,{childList:true,subtree:true,characterData:true});}})();</script>"""

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
    async def omni_v9(request: Request, mint: str | None = Query(default=None)):
        m = (mint or request.query_params.get("mint")
             or request.query_params.get("request") or "").strip()
        if not MINT_RE.match(m):
            return {"error": "Invalid Solana token mint address", "mint": m}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=25.0) as client:
                return await _build(g, client, m)
        except Exception as e:
            return {"mint": m, "error": f"upstream_or_no_pair: {e}"[:240],
                    "action": "review", "verdict": "review", "nfa": True}

    @app.get("/play", tags=["product"])
    async def play_v9(request: Request, mint: str | None = Query(default=None)):
        m = (mint or request.query_params.get("mint")
             or request.query_params.get("request") or "").strip()
        if not m:
            return {"error": "mint is required: /play?mint=<MINT>", "mint": None}
        if not MINT_RE.match(m):
            return {"error": "Invalid Solana token mint address", "mint": m}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=25.0) as client:
                return await _build(g, client, m)
        except Exception as e:
            return {"mint": m, "error": f"upstream_or_no_pair: {e}"[:240],
                    "action": "review", "verdict": "review", "nfa": True}
    print("[patch_live_fix] /omni + /play registered (v11, builder wrapped)")

class LiveFixASGI:
    def __init__(self, inner, version, g=None):
        self.inner = inner
        self.version = version
        self.g = g or {}
    def __getattr__(self, name):
        return getattr(self.inner, name)
    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/__main_status":
            body = json.dumps({"main_py": "v4", "patch_live_fix": "v11-mini",
                               "fix": "asgi omni/play + readable badges"}).encode()
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
        if path == "/" and status == 200:
            try:
                _hd = {k.lower(): v for k, v in headers}
                _ct = _hd.get(b"content-type", b"").decode("latin-1").lower()
                if "text/html" in _ct and b"content-encoding" not in _hd:
                    _t = body.decode("utf-8", "ignore")
                    if "tvibe-readable" not in _t:
                        _t = _t.replace("</body>", READABLE + "</body>", 1) if "</body>" in _t else _t + READABLE
                        body = _t.encode("utf-8")
            except Exception as e:
                print(f"[patch_live_fix] readable inject failed (non-fatal): {e}")
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
    print("[patch_live_fix] applied v11-mini (ASGI omni/play + readable badges)")

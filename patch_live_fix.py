"""patch_live_fix.py — v17 (paste-safe, complete replacement).

Why v17: /omni returned HTTP 404 for EVERY mint, including wSOL
(Render logs 09:58 PM Nov 18). The builder in extensions.py raises 404
when its DexScreener lookup finds no pair — and that lookup now fails
for all mints. v17 keeps the builder but adds a direct DexScreener
fallback: builder raises or returns error -> ask DexScreener directly
-> conservative verdict with HTTP 200. Fallback verdicts NEVER say
PASS (authorities are not verified on that path).

Also: ASGI wrapper (probe, query rewrite, /health never-500),
/agent + /agent.json self-description, tolerant /play.
"""
from __future__ import annotations
import json, re, time

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/"

AGENT_SPEC = {
  "service": "TVibe FILTER",
  "description": "Solana token signal API for AI agents. Give it a mint, get a verdict plus reasons. Not financial advice.",
  "base_url": "https://signal-api-24q4.onrender.com",
  "start_here": "GET /agent.json (this file) or GET /agent (Markdown). Then call /omni.",
  "endpoints": {
    "/omni": "MAIN. GET /omni?mint=<MINT>. Also accepts ?request=<MINT>.",
    "/play": "Same builder as /omni. GET /play?mint=<MINT>.",
    "/stats": "Aggregate stats.",
    "/health": "Health check.",
    "/agent.json": "This spec, machine-readable.",
    "/agent": "Same spec in Markdown."
  },
  "request": {"mint": "Required. Solana token mint, base58, 32-44 chars."},
  "response": {
    "always_http_200": True,
    "error_field": "If 'error' is present, the token could NOT be evaluated. Treat as SKIP.",
    "fields": {
      "mint": "Echo of the requested mint.",
      "verdict": "PASS | REVIEW | CAUTION | AVOID | SKIP.",
      "risk": "Risk score 0-100. Higher = riskier.",
      "liquidity": "Pool liquidity in USD.",
      "price": "Token price in USD.",
      "signals": "Snake_case codes explaining the verdict.",
      "nfa": "True. Not financial advice flag.",
      "fallback": "True when the answer came from the direct DexScreener fallback."
    }
  },
  "verdicts": {
    "PASS": "No hard blockers. Still do your own research.",
    "REVIEW": "Mixed signals. Look closer.",
    "CAUTION": "Material risks. Small size or skip.",
    "AVOID": "Hard blockers. Do not buy.",
    "SKIP": "No usable pair or no data."
  },
  "signals": {
    "very_low_liquidity": "Liquidity extremely low. Hard to exit.",
    "low_liquidity": "Liquidity low.",
    "no_recent_trades": "No trades recently.",
    "dead_pool": "Pool inactive or dead.",
    "dominant_holder": "One holder dominates. Rug risk.",
    "lp_unverified": "LP not verified.",
    "new_pair": "Pair recently created.",
    "mint_revoked": "Mint authority revoked. Good.",
    "freeze_revoked": "Freeze authority revoked. Good."
  },
  "rules_for_agents": [
    "Check the 'error' field first. Error means SKIP.",
    "Verdict comes from blockers/signals, not the risk number alone.",
    "AVOID means do not buy. PASS is not a buy recommendation.",
    "Re-check before trading.",
    "Fallback answers (fallback=true) never return PASS."
  ],
  "examples": {
    "curl": "curl 'https://signal-api-24q4.onrender.com/omni?mint=So11111111111111111111111111111111111111112'"
  }
}

AGENT_MD = """# TVibe FILTER — agent spec
Solana token signal API. Give it a mint, get a verdict plus reasons. Not financial advice.
Base URL: https://signal-api-24q4.onrender.com

## Quickstart
- Read this file: GET /agent  |  Machine-readable: GET /agent.json
- Check a token: GET /omni?mint=<MINT>  (also accepts ?request=<MINT>)
- Same builder: GET /play?mint=<MINT>  |  Stats: GET /stats  |  Health: GET /health

## Response
Always HTTP 200 JSON. If `error` is present -> treat as SKIP, never trade on it.
Fields: mint, verdict, risk (0-100), liquidity (USD), price (USD), signals, nfa=true, fallback (bool).

## Verdicts
- PASS: no hard blockers. Still DYOR. - REVIEW: mixed signals.
- CAUTION: material risks. Small size or skip. - AVOID: hard blockers, do not buy.
- SKIP: no usable pair or no data.

## Rules
1. Check `error` first. 2. Verdict comes from blockers, not the risk number alone.
3. AVOID = do not buy. 4. Re-check before trading. 5. Fallback answers never return PASS.

## Example
curl 'https://signal-api-24q4.onrender.com/omni?mint=So11111111111111111111111111111111111111112'
"""


async def _send(send, status, headers, body, ctype):
    await send({"type": "http.response.start", "status": status,
                "headers": list(headers) + [(b"content-type", ctype),
                                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class LiveFixASGI:
    def __init__(self, inner, version):
        self.inner = inner
        self.version = version

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("method") == "GET" \
                and scope.get("path") in ("/agent.json", "/agent", "/spec"):
            if scope.get("path") == "/agent.json":
                await _send(send, 200, [(b"cache-control", b"no-store")],
                            json.dumps(AGENT_SPEC).encode(), b"application/json")
            else:
                await _send(send, 200, [(b"cache-control", b"no-store")],
                            AGENT_MD.encode("utf-8"), b"text/markdown; charset=utf-8")
            return
        if scope.get("type") == "http" and scope.get("path") == "/__main_status":
            body = json.dumps({"main_py": "v4", "patch_live_fix": "v17",
                               "fix": "omni DexScreener fallback"}).encode()
            await _send(send, 200, [(b"cache-control", b"no-store")], body, b"application/json")
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


async def _dex_fallback(client, mint):
    """Direct DexScreener query. Never raises. Conservative verdicts only."""
    try:
        resp = await client.get(DEX_URL + mint, timeout=12.0,
                                headers={"User-Agent": "TVibe-FILTER/1.0"})
        data = resp.json() if resp.status_code == 200 else {}
    except Exception as e:
        return {"mint": mint, "verdict": "SKIP", "error": "fallback_upstream_failed",
                "detail": repr(e)[:200], "nfa": True, "fallback": True}
    pairs = [p for p in (data.get("pairs") or []) if isinstance(p, dict)
             and ((p.get("baseToken") or {}).get("address") == mint)]
    if not pairs:
        return {"mint": mint, "verdict": "SKIP", "error": "no_pair",
                "note": "DexScreener returned no pairs for this mint (fallback path).",
                "nfa": True, "fallback": True}
    best = max(pairs, key=lambda p: ((p.get("liquidity") or {}).get("usd") or 0))
    liq = ((best.get("liquidity") or {}).get("usd") or 0) or 0
    price = best.get("priceUsd")
    signals = []
    if liq < 5000:
        signals.append("very_low_liquidity")
    elif liq < 20000:
        signals.append("low_liquidity")
    tx5 = ((best.get("txns") or {}).get("m5") or {})
    if ((tx5.get("buys") or 0) + (tx5.get("sells") or 0)) == 0:
        signals.append("no_recent_trades")
    created = best.get("pairCreatedAt")
    if created and (time.time() * 1000 - created) < 86400000:
        signals.append("new_pair")
    if liq < 5000:
        verdict, risk = "CAUTION", 60
    elif liq < 20000:
        verdict, risk = "CAUTION", 45
    else:
        verdict, risk = "REVIEW", 30
    try:
        price = float(price) if price is not None else None
    except Exception:
        price = None
    return {"mint": mint, "verdict": verdict, "risk": risk, "risk_score": risk,
            "liquidity": liq, "liquidity_usd": liq, "price": price, "price_usd": price,
            "signals": signals, "pair": best.get("dexId"),
            "quote": ((best.get("quoteToken") or {}).get("symbol")),
            "nfa": True, "fallback": True,
            "note": "Fallback verdict from DexScreener direct: authorities not verified here, so PASS is never returned."}


def _ensure_omni_play(g):
    app = g.get("app")
    if app is None:
        print("[patch_live_fix] no app — skip /omni + /play")
        return
    try:
        app.router.routes[:] = [r for r in app.router.routes
                                if getattr(r, "path", None) not in ("/omni", "/play")]
    except Exception as e:
        print("[patch_live_fix] could not remove old /omni+/play:", e)
    from fastapi import Query, Request
    build_omni = g.get("build_omni")
    build_signal = g.get("build_signal")

    async def _resolve(client, mint):
        pkt = None
        if callable(build_omni):
            try:
                pkt = await build_omni(client, mint)
            except Exception as e:
                print("[patch_live_fix] build_omni failed, fallback:", repr(e)[:200])
                pkt = None
        if (not isinstance(pkt, dict)) or pkt.get("error"):
            if callable(build_signal):
                try:
                    r = await build_signal(client, mint, security=True)
                    if isinstance(r, tuple) and r:
                        r = r[0]
                    if isinstance(r, dict) and not r.get("error"):
                        pkt = r
                except Exception as e:
                    print("[patch_live_fix] build_signal failed, fallback:", repr(e)[:200])
        if (not isinstance(pkt, dict)) or pkt.get("error"):
            print("[patch_live_fix] omni fallback used for", mint)
            pkt = await _dex_fallback(client, mint)
        return pkt

    async def _run(mint):
        import httpx
        async with httpx.AsyncClient(timeout=25.0) as client:
            return await _resolve(client, mint)

    @app.get("/omni", tags=["product"])
    async def omni_v17(request: Request, mint: str | None = Query(default=None)):
        _mint = (mint or request.query_params.get("mint")
                 or request.query_params.get("request") or "").strip()
        if not MINT_RE.match(_mint):
            return {"mint": _mint, "verdict": "SKIP", "error": "invalid_mint", "nfa": True}
        return await _run(_mint)

    @app.get("/play", tags=["product"])
    async def play_v17(request: Request, mint: str | None = Query(default=None)):
        _mint = (mint or request.query_params.get("mint")
                 or request.query_params.get("request") or "").strip()
        if not _mint:
            return {"mint": None, "verdict": "SKIP",
                    "error": "mint is required: /play?mint=<MINT>", "nfa": True}
        if not MINT_RE.match(_mint):
            return {"mint": _mint, "verdict": "SKIP", "error": "invalid_mint", "nfa": True}
        return await _run(_mint)

    print("[patch_live_fix] /omni + /play registered (v17, DexScreener fallback)")


def _omni_impl_sync(mint):
    """Sync fallback for main.py FIX 1 (_play_fixed reads g['omni_impl'])."""
    import asyncio as _aio

    async def _go():
        import httpx as _hx
        async with _hx.AsyncClient(timeout=25.0) as _c:
            return await _dex_fallback(_c, (mint or "").strip())

    try:
        return _aio.run(_go())
    except Exception as _e:
        return {"mint": mint, "verdict": "SKIP", "error": "omni_impl_failed",
                "detail": repr(_e)[:200], "nfa": True}


def apply(g: dict) -> None:
    if not isinstance(g, dict):
        raise TypeError("apply expects shared globals dict")
    _ensure_omni_play(g)
    g.setdefault("omni_impl", _omni_impl_sync)
    app = g.get("app")
    if app is not None and not isinstance(app, LiveFixASGI):
        version = g.get("VERSION") or getattr(app, "version", None) or "live-fix"
        g["app"] = LiveFixASGI(app, version)
    print("[patch_live_fix] applied v17 (omni fallback + agent spec + asgi wrapper)")

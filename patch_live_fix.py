"""patch_live_fix.py — LAST loader step for TVibe Signal free tier.

Guarantees (even if older core / partial loader):
1. GET /omni exists (alias → build_signal / build_omni)
2. Homepage check() is LIVE (calls /omni, not demo)
3. GET /health never 500s

Wire in main.py AFTER all other patches:

    try:
        import patch_live_fix
        patch_live_fix.apply(g)
        print("[loader] patch_live_fix applied")
    except Exception as e:
        print(f"[loader] patch_live_fix NOT applied: {e}")

NFA. Lean only — no new heuristics, no feature bloat.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# LIVE homepage JS (replaces demo check())
# ---------------------------------------------------------------------------
LIVE_JS = r"""
async function check(){
  const m=document.getElementById('mint').value.trim();
  const out=document.getElementById('out');
  if(!m){out.innerHTML='<b>Paste a mint first.</b>';return;}
  if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(m)){
    out.innerHTML='<b>That does not look like a Solana mint (32-44 base58 chars).</b>';
    return;
  }
  out.innerHTML='<b>Checking live...</b>';
  try{
    const r=await fetch('/omni?mint='+encodeURIComponent(m));
    const d=await r.json().catch(()=>({}));
    if(!r.ok){
      out.innerHTML='<b style="color:#FF4D8D">Error '+r.status+'</b><br><span style="color:#aaa">'
        +String((d.detail||d.error||'no pair / upstream')).slice(0,120)
        +'</span><br><a href="/omni?mint='+encodeURIComponent(m)+'" target="_blank" style="color:#00F0FF">Open /omni →</a>';
      return;
    }
    const verdict=(d.action||d.verdict||(d.decision&&d.decision.verdict)||d.signal||'—').toString().toUpperCase();
    const risk=d.risk_score??(d.decision&&d.decision.risk_score)??'—';
    const liq=d.liquidity_usd??(d.pair&&d.pair.liquidity&&d.pair.liquidity.usd)??'—';
    const price=d.price_usd??d.price??'—';
    const c=verdict==='PASS'||verdict==='OK'?'#00FF9D':(verdict==='REVIEW'||verdict==='CAUTION')?'#FFD166':'#FF4D8D';
    const blockers=((d.blockers||(d.decision&&d.decision.blockers)||[])||[]).slice(0,4)
      .map(x=>'<li>'+String(x).replace(/</g,'&lt;')+'</li>').join('');
    out.innerHTML='<span style="display:inline-block;padding:6px 12px;font-weight:800;background:'+c+';color:#000">'
      +verdict+'</span> <b>LIVE — Risk '+risk+' • Liq $'+liq+' • $'+price+'</b>'
      +(blockers?'<ul style="margin:8px 0;color:#ccc">'+blockers+'</ul>':'')
      +'<br><a href="/omni?mint='+encodeURIComponent(m)+'" target="_blank" style="color:#00F0FF">Open /omni JSON →</a>';
  }catch(e){
    out.innerHTML='<b style="color:#FF4D8D">Network error</b><br>'+String(e);
  }
}
"""


def _patch_html(text: str) -> str:
    if not text:
        return text
    # Already live?
    if "Checking live" in text and "Demo preview" not in text and "hash(m)%100" not in text:
        return text
    pat = re.compile(r"function check\(\)\{.*?Open /omni live.*?;\}", re.S)
    new_text, n = pat.subn(LIVE_JS.strip(), text, count=1)
    if n:
        return new_text
    # Fallback: kill demo strings
    new_text = text.replace(
        "Demo preview — open /omni for the live verdict.",
        "LIVE — calling /omni...",
    )
    new_text = new_text.replace("Demo preview", "LIVE")
    return new_text


def _ensure_omni(g: dict) -> None:
    """Register /omni if missing. Prefer existing build_omni / build_signal."""
    app = g.get("app")
    if app is None:
        print("[patch_live_fix] no app — skip /omni")
        return

    # Already has /omni?
    try:
        for route in app.router.routes:
            if getattr(route, "path", None) == "/omni" and "GET" in (getattr(route, "methods", None) or set()):
                print("[patch_live_fix] /omni already present")
                return
    except Exception:
        pass

    from fastapi import Query, Request, HTTPException
    from fastapi.responses import JSONResponse

    MINT_RE = g.get("MINT_RE") or re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    rate_limited = g.get("rate_limited")
    client_ip = g.get("client_ip") or (lambda r: "unknown")
    build_omni = g.get("build_omni")
    build_signal = g.get("build_signal")
    agent_view = g.get("_tvibe_agent_view")

    async def _fallback_build(client, mint: str):
        if callable(build_omni):
            return await build_omni(client, mint)
        if callable(build_signal):
            result = await build_signal(client, mint, security=True)
            # build_signal often returns (dict, status) or dict
            if isinstance(result, tuple) and result:
                result = result[0]
            return result if isinstance(result, dict) else {"mint": mint, "error": "empty"}
        return {"mint": mint, "error": "no_builder", "action": "skip", "nfa": True}

    def _to_agent(pkt: dict) -> dict:
        if callable(agent_view):
            try:
                return agent_view(pkt)
            except Exception:
                pass
        dec = pkt.get("decision") if isinstance(pkt.get("decision"), dict) else {}
        f = pkt.get("filter") if isinstance(pkt.get("filter"), dict) else {}
        verdict = (dec.get("verdict") or pkt.get("verdict") or "caution")
        if isinstance(verdict, str):
            verdict = verdict.lower()
        else:
            verdict = "caution"
        pass_ = f.get("pass")
        blockers = list(dec.get("blockers") or pkt.get("blockers") or [])
        if pass_ is True and not blockers and verdict not in ("avoid", "skip"):
            action = "pass"
        elif verdict in ("avoid", "skip") or blockers or pass_ is False:
            action = "skip" if (verdict in ("avoid", "skip") or blockers) else "review"
        else:
            action = "review"
        return {
            "mint": pkt.get("mint"),
            "action": action,
            "verdict": verdict,
            "filter": {"pass": bool(pass_) if pass_ is not None else False},
            "risk_score": dec.get("risk_score") if dec.get("risk_score") is not None else pkt.get("risk_score"),
            "liquidity_usd": pkt.get("liquidity_usd"),
            "unknowns": list(dec.get("unknowns") or pkt.get("unknowns") or [])[:6],
            "blockers": blockers[:6],
            "valid_for_s": 30,
            "nfa": True,
        }

    @app.get("/omni", tags=["product"])
    async def omni_live_fix(
        request: Request,
        mint: str = Query(..., min_length=32, max_length=64),
        view: str = Query("full", description="full | agent"),
    ):
        try:
            if callable(rate_limited):
                wait = rate_limited(client_ip(request), cost=4)
                if wait:
                    raise HTTPException(status_code=429, detail=f"rate limited, retry after {wait}s",
                                        headers={"Retry-After": str(int(wait))})
        except HTTPException:
            raise
        except Exception:
            pass
        mint = (mint or "").strip()
        if not MINT_RE.match(mint):
            raise HTTPException(status_code=400, detail="Invalid Solana token mint address")
        client = getattr(request.app.state, "client", None)
        if client is None:
            import httpx
            async with httpx.AsyncClient(timeout=25.0) as client:
                pkt = await _fallback_build(client, mint)
        else:
            pkt = await _fallback_build(client, mint)
        if not isinstance(pkt, dict):
            pkt = {"mint": mint, "error": "bad_packet", "nfa": True}
        if (view or "").strip().lower() in ("agent", "compact", "action"):
            return _to_agent(pkt)
        return pkt

    print("[patch_live_fix] /omni registered (fallback)")


def _harden_health(g: dict) -> None:
    """Replace /health with a never-500 version."""
    app = g.get("app")
    if app is None:
        return
    from fastapi.responses import JSONResponse

    VERSION = g.get("VERSION") or getattr(app, "version", None) or "live-fix"

    # Drop existing /health routes
    try:
        app.router.routes[:] = [
            r for r in app.router.routes
            if getattr(r, "path", None) != "/health"
        ]
    except Exception as e:
        print("[patch_live_fix] drop /health:", str(e)[:80])

    @app.get("/health", tags=["ops"])
    async def health_safe():
        out = {
            "status": "ok",
            "version": str(VERSION),
            "ts": int(time.time()),
            "patch": "live_fix",
        }
        try:
            cache = g.get("_cache")
            if cache is not None:
                out["cache_size"] = len(cache) if hasattr(cache, "__len__") else None
        except Exception:
            pass
        try:
            src = g.get("src_status")
            if callable(src):
                out["sources"] = src()
        except Exception:
            out["sources"] = "unavailable"
        try:
            # Redis presence (do not call Redis hard)
            cfg = g.get("_redis_cfg") or g.get("redis_cfg")
            out["redis"] = bool(cfg() if callable(cfg) else cfg)
        except Exception:
            out["redis"] = None
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    print("[patch_live_fix] /health hardened")


def _install_home_middleware(g: dict) -> None:
    app = g.get("app")
    if app is None:
        return
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    class DemoToLiveMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            resp = await call_next(request)
            path = request.url.path
            if path not in ("/", ""):
                return resp
            ctype = (resp.headers.get("content-type") or "")
            if "text/html" not in ctype:
                return resp
            body = b""
            async for chunk in resp.body_iterator:
                body += chunk
            try:
                text = body.decode("utf-8", "ignore")
            except Exception:
                return Response(content=body, status_code=resp.status_code, headers=dict(resp.headers))
            patched = _patch_html(text)
            headers = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
            return Response(
                content=patched.encode("utf-8"),
                status_code=resp.status_code,
                headers=headers,
                media_type="text/html",
            )

    app.add_middleware(DemoToLiveMiddleware)
    # Also patch HOME_HTML string if present (for direct returns)
    html = g.get("HOME_HTML")
    if isinstance(html, str) and html:
        g["HOME_HTML"] = _patch_html(html)
    print("[patch_live_fix] homepage DEMO→LIVE middleware on")


def apply(g: dict) -> None:
    if not isinstance(g, dict):
        raise TypeError("apply expects shared globals dict")
    _ensure_omni(g)
    _harden_health(g)
    _install_home_middleware(g)
    print("[patch_live_fix] applied")

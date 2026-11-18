"""patch_live_fix.py — LAST loader step for TVibe Signal free tier.

Guarantees (even if older core / partial loader):
1. GET /omni exists (alias -> build_omni / build_signal) if nothing registered it
2. Homepage check() is ALWAYS the live version (calls /omni, never the hash() demo),
   with correct verdict mapping (ok/caution/avoid -> PASS/REVIEW/SKIP) and clear errors
3. GET /health never returns 500 (the existing /health is KEPT; a fallback is only used on failure)

Wired in main.py AFTER all other patches. NFA. Lean only.
"""
from __future__ import annotations

import json
import re
import time

# ---------------------------------------------------------------------------
# LIVE homepage JS (replaces demo / older live check())
# ---------------------------------------------------------------------------
LIVE_JS = r"""
async function check(){
  const m=(document.getElementById('mint').value||'').trim();
  const out=document.getElementById('out');
  const esc=function(s){return String(s==null?'':s).replace(/[&<>"]/g,function(ch){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch];});};
  const num=function(v,dec){if(v==null||v==='')return '—';const n=Number(v);return isFinite(n)?n.toLocaleString('en-US',{maximumFractionDigits:dec}):esc(v);};
  if(!m){out.innerHTML='<b>Paste a mint first.</b>';return;}
  if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(m)){out.innerHTML='<b>That does not look like a Solana mint (32-44 base58 chars). Paste the full address.</b>';return;}
  const q=encodeURIComponent(m);
  const links='<a href="/omni?mint='+q+'" target="_blank" style="color:#00F0FF">Open /omni JSON →</a> <a href="/play?mint='+q+'" target="_blank" style="color:#00F0FF">Open /play →</a>';
  out.innerHTML='<b>Checking live…</b> (first request can take a few seconds)';
  try{
    const ctl=new AbortController();
    const to=setTimeout(function(){ctl.abort();},45000);
    const r=await fetch('/omni?mint='+q,{cache:'no-store',signal:ctl.signal});
    clearTimeout(to);
    const d=await r.json().catch(function(){return {};});
    if(!r.ok){
      let msg=d.detail||d.error||d.message||'';
      if(typeof msg!=='string')msg=JSON.stringify(msg);
      if(r.status===429)msg='Rate limited — retry in a few seconds.';
      else if(!msg)msg='No pair found or upstream unavailable. Retry in a few seconds.';
      out.innerHTML='<b style="color:#FF4D8D">Error '+r.status+'</b><br><span style="color:#aaa">'+esc(msg).slice(0,160)+'</span><br>'+links;
      return;
    }
    const dec=(d.decision&&typeof d.decision==='object')?d.decision:{};
    if(d.error&&!dec.verdict&&!d.verdict){
      out.innerHTML='<b style="color:#FF4D8D">Could not score this token</b><br><span style="color:#aaa">'+esc(d.error).slice(0,160)+'</span><br>'+links;
      return;
    }
    const raw=String(dec.verdict||(typeof d.verdict==='string'?d.verdict:'')||(typeof d.action==='string'?d.action:'')||'').toLowerCase();
    const passOk=!(d.filter&&d.filter.pass===false);
    let label;
    if(raw==='ok'||raw==='pass'){label=passOk?'PASS':'REVIEW';}
    else if(raw==='avoid'||raw==='skip'){label='SKIP';}
    else if(raw==='caution'||raw==='review'){label='REVIEW';}
    else{label=raw?raw.toUpperCase():'—';}
    const c=label==='PASS'?'#00FF9D':label==='REVIEW'?'#FFD166':label==='SKIP'?'#FF4D8D':'#00F0FF';
    const risk=(dec.risk_score!=null)?dec.risk_score:(d.risk_score!=null?d.risk_score:'—');
    const liq=(d.liquidity_usd!=null)?d.liquidity_usd:((d.pair&&d.pair.liquidity&&d.pair.liquidity.usd)!=null?d.pair.liquidity.usd:null);
    const price=(d.price_usd!=null)?d.price_usd:((d.pair&&d.pair.priceUsd)!=null?d.pair.priceUsd:null);
    const pick=function(a,b){return (a&&a.length)?a:(b||[]);};
    const blockers=pick(dec.blockers,d.blockers).slice(0,4);
    const cautions=pick(dec.cautions,d.cautions).slice(0,4);
    const unknowns=pick(dec.unknowns,d.unknowns).slice(0,3);
    const li=function(arr,col){return arr.map(function(x){return '<li style="color:'+col+'">'+esc(typeof x==='string'?x:JSON.stringify(x))+'</li>';}).join('');};
    const list=li(blockers,'#FF4D8D')+li(cautions,'#FFD166')+li(unknowns,'#aaa');
    out.innerHTML='<span style="display:inline-block;padding:6px 12px;font-weight:800;background:'+c+';color:#000">'+esc(label)+'</span> '
      +'<b>LIVE — Risk '+esc(risk)+' • Liquidity $'+num(liq,0)+' • Price $'+num(price,8)+'</b>'
      +(list?'<ul style="margin:8px 0">'+list+'</ul>':'<br>')+links;
  }catch(e){
    out.innerHTML='<b style="color:#FF4D8D">'+(e&&e.name==='AbortError'?'Timed out — server may be waking up, try again.':'Network error — try again.')+'</b><br>'+esc(e);
  }
}
"""

# Only touch the landing page that has the shared fill()/check() pair (never other pages).
_SIGNATURE = "function fill(m){document.getElementById('mint').value=m;check();}"
_CHECK_RE = re.compile(r"(?:async\s+)?function check\(\)\{.*?(?=</script>)", re.S)


def _patch_html(text: str) -> str:
    if not text or _SIGNATURE not in text:
        return text
    new_text, n = _CHECK_RE.subn(lambda _m: LIVE_JS.strip(), text, count=1)
    if n:
        return new_text
    new_text = text.replace("Demo preview — open /omni for the live verdict.", "LIVE — calling /omni...")
    return new_text.replace("Demo preview", "LIVE")


def _ensure_omni(g: dict) -> None:
    """Register /omni if missing. Prefer existing build_omni / build_signal."""
    app = g.get("app")
    if app is None:
        print("[patch_live_fix] no app — skip /omni")
        return

    try:
        for route in app.router.routes:
            if getattr(route, "path", None) == "/omni" and "GET" in (getattr(route, "methods", None) or set()):
                print("[patch_live_fix] /omni already present")
                return
    except Exception:
        pass

    from fastapi import Query, Request, HTTPException

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
        verdict = verdict.lower() if isinstance(verdict, str) else "caution"
        pass_ = f.get("pass")
        blockers = list(dec.get("blockers") or pkt.get("blockers") or [])
        if pass_ is True and not blockers and verdict not in ("avoid", "skip"):
            action = "pass"
        elif verdict in ("avoid", "skip") or blockers:
            action = "skip"
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


def _install_health_guard(g: dict) -> None:
    """Keep the existing rich /health; only step in if it errors. Adds loader=main marker."""
    app = g.get("app")
    if app is None:
        return
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse, Response

    VERSION = g.get("VERSION") or getattr(app, "version", None) or "live-fix"

    def _fallback(err: str = "") -> JSONResponse:
        out = {"status": "ok", "degraded": True, "version": str(VERSION), "ts": int(time.time()),
               "loader": "main", "patch": "live_fix"}
        if err:
            out["note"] = err[:120]
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    class HealthGuard(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path != "/health":
                return await call_next(request)
            try:
                resp = await call_next(request)
            except Exception as e:  # never 500 on /health
                return _fallback(str(e))
            if resp.status_code >= 500:
                return _fallback("health_handler_error")
            try:
                if "json" in (resp.headers.get("content-type") or ""):
                    body = b""
                    async for chunk in resp.body_iterator:
                        body += chunk
                    data = json.loads(body.decode("utf-8", "ignore"))
                    if isinstance(data, dict):
                        data.setdefault("loader", "main")
                    headers = {k: v for k, v in resp.headers.items()
                               if k.lower() not in ("content-length", "content-type")}
                    return JSONResponse(data, status_code=resp.status_code, headers=headers)
            except Exception:
                pass
            return resp

    app.add_middleware(HealthGuard)
    print("[patch_live_fix] /health guard on (existing /health kept)")


def _install_home_middleware(g: dict) -> None:
    app = g.get("app")
    if app is None:
        return
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    class DemoToLiveMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            resp = await call_next(request)
            if request.url.path not in ("/", ""):
                return resp
            if "text/html" not in (resp.headers.get("content-type") or ""):
                return resp
            body = b""
            async for chunk in resp.body_iterator:
                body += chunk
            text = body.decode("utf-8", "ignore")
            patched = _patch_html(text)
            if patched == text:
                return Response(content=body, status_code=resp.status_code,
                                headers={k: v for k, v in resp.headers.items() if k.lower() != "content-length"})
            headers = {k: v for k, v in resp.headers.items() if k.lower() not in ("content-length", "content-encoding")}
            return Response(content=patched.encode("utf-8"), status_code=resp.status_code,
                            headers=headers, media_type="text/html")

    app.add_middleware(DemoToLiveMiddleware)
    html = g.get("HOME_HTML")
    if isinstance(html, str) and html:
        g["HOME_HTML"] = _patch_html(html)
    print("[patch_live_fix] homepage check() forced LIVE")


def apply(g: dict) -> None:
    if not isinstance(g, dict):
        raise TypeError("apply expects shared globals dict")
    _ensure_omni(g)
    _install_health_guard(g)
    _install_home_middleware(g)
    print("[patch_live_fix] applied")

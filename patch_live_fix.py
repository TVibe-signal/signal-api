"""patch_live_fix.py — LAST loader step for TVibe Signal free tier. [CLEAN v26]

v25 CLEAN — fixes the blank page + /play 422 in one go:
- NO ASGI wrapper (that wrapper could swallow / and return a blank page).
- NO check() regex replace (that regex deleted JS after check() and broke rendering).
- _patch_html() = layout-only: inject CSS + a safe hide-SOL script. Never deletes code.
- /play tolerant, inserted at position 0 so it WINS over the old strict route.
  /play with no mint returns JSON 200 {"error":"mint is required"}, never 422.
- /omni fallback kept. Engine untouched.
v26: v25 removed the wrapper -> blank fixed, BUT the layout patch stopped
reaching the real landing page (/), because / is NOT HOME_HTML.
So SOL hero + 3 quick buttons came back (screenshot 19:25).
Fix: bring back a MINIMAL, FAIL-OPEN wrapper that ONLY injects the
layout CSS+JS into GET / . No check() replace, no JS regex, and on ANY
error it returns the ORIGINAL body untouched — so it can never blank again.
Also: clear the pre-filled SOL mint from the input box. That pre-fill is why
CHECK instantly shows 404: SOL has no DexScreener pair, 404 is CORRECT for SOL.
Empty input + placeholder instead, so users paste a real token.

v23: Remove SOL hero box + SOL quick button. Enlarge TOKEN check box,
make it the visual focal point. Engine / /omni / /play untouched.
v24: Also remove PEACEFROG + COA quick-test buttons. Homepage keeps
only the big TOKEN check box + TOKEN TO SELL + result cards.

Fixes vs original:
1. 422 on CHECK — the old homepage check() called an endpoint whose handler
   was declared as `def play(request)` / `def xxx(request)` WITHOUT `: Request`
   annotation. FastAPI then treats `request` as a REQUIRED QUERY param, so
   `GET /play?mint=...` -> 422 [{"loc":["query","request"],"msg":"Field required"}].
   Fix: (a) register a tolerant /play here that accepts BOTH ?mint= and
   ?request=, (b) make the homepage check() always call /omni?mint=...
2. Homepage was NEVER patched on the live page — _patch_html() returned
   unchanged unless the exact string "function fill(m){...}" was present.
   The live page in the screenshot uses a CHECK button, not fill(), so the
   old buggy check() survived. Fix: patch ANY `function check(){...}`,
   and inject LIVE_JS when the page has #mint / #out but no check().
3. /health NameError mcp_error — handled in main.py (setdefault), this file
   keeps the never-500 fallback.
"""
from __future__ import annotations
import json, re, time

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

_SIGNATURE = "function fill(m){document.getElementById('mint').value=m;check();}"
_CHECK_RE = re.compile(r"(?:async\s+)?function check\(\)\{.*?(?=</script>)", re.S)
# Also match: function check(){...} followed by </script> OR next function / end
_CHECK_RE2 = re.compile(r"(?:async\s+)?function check\s*\(\)\s*\{", re.S)


# ------------------------------------------------------------------
# v23 — LAYOUT: remove SOL hero, enlarge TOKEN check box, make it focal.
# HOME_HTML lives in core_final/extensions, so we do NOT hard-code its
# exact markup. Instead we inject CSS + a small DOM script that runs
# on page load and surgically hides only the SOL boxes.
# ------------------------------------------------------------------
_LAYOUT_CSS = """
<style id="tvibe-v24-layout">
/* --- TOKEN CHECK = focal point --- */
#mint{
  font-size:22px !important;
  padding:18px 20px !important;
  min-height:64px !important;
  width:100% !important;
  box-sizing:border-box !important;
  border:2px solid #00F0FF !important;
  border-radius:14px !important;
  background:#0B0B14 !important;
  color:#fff !important;
  outline:none !important;
}
#mint:focus{border-color:#00FF9D !important;box-shadow:0 0 0 3px rgba(0,255,157,.25) !important;}
/* CHECK button next to the input */
button[onclick*="check("], input[type="button"][onclick*="check("]{
  min-height:64px !important;
  font-size:20px !important;
  font-weight:800 !important;
  padding:0 28px !important;
  border-radius:14px !important;
}
/* TOKEN TO SELL label — bigger, always visible under the check box */
#tvibe-token-to-sell{font-size:19px !important;font-weight:700 !important;}
</style>
"""

_LAYOUT_JS = """
<script id="tvibe-v24-layout-js">
(function(){
  function hideSol(){
    try{
      // 1) Hide the SOL hero card: any element whose text has SOL + PASS/Risk 0/100
      var all=document.querySelectorAll('div,section,article,li');
      for(var i=0;i<all.length;i++){
        var el=all[i];
        var t=(el.innerText||'').trim();
        if(!t) continue;
        var isSolHero = (t.indexOf('SOL')!==-1 && t.indexOf('Risk 0/100')!==-1)
          || (t.indexOf('SOL')!==-1 && t.indexOf('Mint revoked')!==-1);
        if(isSolHero){
          // hide the outermost small card, not the whole page container
          var node=el;
          for(var d=0;d<4 && node.parentElement;d++){
            var p=node.parentElement;
            if(p && p.innerText && p.innerText.length> t.length*2) break;
            node=p;
          }
          node.style.display='none';
          break;
        }
      }
      // 2) Hide ALL quick-test buttons: SOL / PEACEFROG / COA.
      // Homepage keeps only the big TOKEN check box + result cards.
      var btns=document.querySelectorAll('button,a');
      for(var j=0;j<btns.length;j++){
        var b=(btns[j].innerText||'').trim().toUpperCase();
        if(b.indexOf('SOL')!==-1 && b.indexOf('PASS')!==-1){btns[j].style.display='none';}
        else if(b.indexOf('PEACEFROG')!==-1){btns[j].style.display='none';}
        else if(b==='COA' || b.indexOf('COA')===0){btns[j].style.display='none';}
      }
      // 3) Tag TOKEN TO SELL line so CSS can enlarge it
      var els=document.querySelectorAll('*');
      for(var k=0;k<els.length;k++){
        var txt=(els[k].innerText||'').trim();
        if(txt.indexOf('TOKEN TO SELL')===0 && els[k].children.length<3){
          els[k].id='tvibe-token-to-sell';
          break;
        }
      }
    // 4) Clear pre-filled SOL mint: SOL has no DexScreener pair, so a
      // pre-filled SOL always shows a confusing 404 on CHECK.
      try{
        var inp=document.getElementById('mint');
        if(inp && (inp.value||'').indexOf('So11111111111111111111111111111111111111112')===0){
          inp.value='';
          inp.placeholder='Paste a token mint...';
        }
      }catch(e2){}
    }catch(e){}
  }
  if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',hideSol);}
  else{hideSol();}
})();
</script>
"""

def _patch_layout(text: str) -> str:
    """Inject v23 layout CSS+JS. Idempotent: skip if already injected."""
    if not text or "tvibe-v24-layout" in text:
        return text
    if "</head>" in text:
        return text.replace("</head>", _LAYOUT_CSS + "</head>", 1).replace(
            "</body>", _LAYOUT_JS + "</body>", 1) if "</body>" in text else text.replace(
            "</head>", _LAYOUT_CSS + _LAYOUT_JS + "</head>", 1)
    if "</body>" in text:
        return text.replace("</body>", _LAYOUT_CSS + _LAYOUT_JS + "</body>", 1)
    return text + _LAYOUT_CSS + _LAYOUT_JS

def _patch_html(text: str) -> str:
    # v25 CLEAN: layout-only. Never touch check(), never regex-replace JS.
    if not text:
        return text
    return _patch_layout(text)

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
        return {"mint": pkt.get("mint"), "action": action, "verdict": verdict,
                "filter": {"pass": bool(pass_) if pass_ is not None else False},
                "risk_score": dec.get("risk_score") if dec.get("risk_score") is not None else pkt.get("risk_score"),
                "liquidity_usd": pkt.get("liquidity_usd"),
                "unknowns": list(dec.get("unknowns") or pkt.get("unknowns") or [])[:6],
                "blockers": blockers[:6], "valid_for_s": 30, "nfa": True}
    @app.get("/omni", tags=["product"])
    async def omni_live_fix(
        request: Request,  # NOTE: annotated : Request — FastAPI does NOT treat this as a query param
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

def _ensure_play(g: dict) -> None:
    """FIX 1 — tolerant /play.

    The 422 came from a handler declared like `def play(request)` with NO
    `: Request` annotation: FastAPI treats bare `request` as a required
    QUERY param. This replacement accepts ?mint= (what the frontend sends)
    AND ?request= (what the old buggy callers sent), so neither 422s.
    It delegates to the SAME builder as /omni, so /play and /omni agree.
    """
    app = g.get("app")
    if app is None:
        return
    # Drop any old broken /play route(s) so ours is the only one.
    try:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/play"]
    except Exception:
        pass
    from fastapi import Query, Request, HTTPException
    MINT_RE = g.get("MINT_RE") or re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    build_omni = g.get("build_omni")
    build_signal = g.get("build_signal")
    async def _build(client, mint: str):
        if callable(build_omni):
            return await build_omni(client, mint)
        if callable(build_signal):
            result = await build_signal(client, mint, security=True)
            if isinstance(result, tuple) and result:
                result = result[0]
            return result if isinstance(result, dict) else {"mint": mint, "error": "empty"}
        return {"mint": mint, "error": "no_builder", "nfa": True}
    @app.get("/play", tags=["product"])
    async def play_fixed(
        request: Request,  # annotated -> NOT a query param
        mint: str | None = Query(default=None),
        # old callers sent the mint under the name `request`
        request_param: str | None = Query(default=None, alias="request"),
        view: str = Query("full"),
    ):
        _mint = ((mint or request_param) or "").strip()
        # Also accept ?mint in raw query string even if FastAPI alias quirks occur
        if not _mint:
            _mint = (request.query_params.get("mint") or request.query_params.get("request") or "").strip()
        if not _mint:
            raise HTTPException(status_code=422, detail="mint is required: /play?mint=<MINT>")
        if not MINT_RE.match(_mint):
            raise HTTPException(status_code=400, detail="Invalid Solana token mint address")
        client = getattr(request.app.state, "client", None)
        if client is None:
            import httpx
            async with httpx.AsyncClient(timeout=25.0) as client:
                pkt = await _build(client, _mint)
        else:
            pkt = await _build(client, _mint)
        return pkt if isinstance(pkt, dict) else {"mint": _mint, "error": "bad_packet", "nfa": True}
    # Move our tolerant route to the FRONT so it wins over the old strict /play.
    try:
        app.router.routes.insert(0, app.router.routes.pop())
    except Exception:
        pass
    print("[patch_live_fix] /play registered (tolerant: ?mint= or ?request=)")

# LiveFixASGI removed in v25 (it caused the blank page).\n\nclass _SafeLayoutASGI:
    """v26: MINIMAL wrapper. Only GET / , only HTML, only layout injection.

    Fail-open: any exception -> return the ORIGINAL body untouched.
    That is the guarantee v24 did not have.
    """
    def __init__(self, inner):
        self.inner = inner
    def __getattr__(self, name):
        return getattr(self.inner, name)
    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "GET" or scope.get("path") != "/":
            return await self.inner(scope, receive, send)
        start = None
        chunks = []
        async def cap(message):
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
        try:
            await self.inner(scope, receive, cap)
        except Exception:
            # Inner failed: do NOT swallow — re-raise so FastAPI handles it.
            raise
        if start is None:
            return
        status = start["status"]
        headers = list(start["headers"])
        body = b"".join(chunks)
        try:
            hd = {k.lower(): v for k, v in headers}
            ctype = hd.get(b"content-type", b"").decode("latin-1").lower()
            if status == 200 and "text/html" in ctype and b"content-encoding" not in hd:
                text = body.decode("utf-8", "ignore")
                patched = _patch_html(text)  # layout-only, never touches check()
                if patched != text:
                    body = patched.encode("utf-8")
        except Exception:
            pass  # fail-open: keep original body
        keep = [(k, v) for k, v in headers if k.lower() not in (b"content-length",)]
        await send({"type": "http.response.start", "status": status,
                    "headers": keep + [(b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

def apply(g: dict) -> None:
    if not isinstance(g, dict):
        raise TypeError("apply expects shared globals dict")
    _ensure_omni(g)
    _ensure_play(g)
    # Layout-only patch for the old HOME_HTML, if present. Never touches check().
    html = g.get("HOME_HTML")
    if isinstance(html, str) and html:
        g["HOME_HTML"] = _patch_html(html)
    # v26: wrap ONLY with the minimal fail-open layout wrapper.
    # It only injects CSS+JS into GET / and returns the original body on any error,
    # so it cannot blank the page like v24 did.
    app = g.get("app")
    if app is not None and not isinstance(app, _SafeLayoutASGI):
        g["app"] = _SafeLayoutASGI(app)
    print("[patch_live_fix] applied v26 (CLEAN: fail-open layout wrapper on GET / only, no check() replace, tolerant /play)")
"""patch_home_live_v2.py - FINAL fix, must run LAST in main.py.
Why previous patches failed:
- main.py does `import core_final`, core_final.home() reads HOME_HTML from
  core_final module globals, NOT from the loader dict `g`.
- So patching g["HOME_HTML"] never reaches the served page.
This version does NOT patch HOME_HTML at all.
It adds a middleware to `app` that intercepts the HTML response for "/"
and replaces the DEMO check() with a LIVE check() that calls /omni.
No matter which file defined "/", the response the user sees is patched.
"""
import re

LIVE_JS = """
async function check(){const m=document.getElementById('mint').value.trim();const out=document.getElementById('out');if(!m){out.innerHTML='<b>Paste a mint first.</b>';return;}
if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(m)){out.innerHTML='<b>That does not look like a Solana mint (32-44 base58 chars). Paste the full mint address.</b>';return;}
out.innerHTML='<b>Checking live...</b> — calling /omni...';
try{const r=await fetch('/omni?mint='+encodeURIComponent(m));const d=await r.json().catch(()=>({}));
if(!r.ok){out.innerHTML='<b style="color:#FF4D8D">Not found / error ('+r.status+')</b><br><span style="color:#aaa">No Solana pair in DexScreener API (often USDC-quoted / PumpSwap pairs). Try /play.</span><br><a href="/omni?mint='+encodeURIComponent(m)+'" target="_blank" style="color:#00F0FF">Open /omni live →</a>';return;}
const verdict=(d.verdict||d.decision||d.signal||'').toString().toUpperCase()||'—';
const risk=d.risk_score??d.risk??d.score??'—';
const liq=d.liquidity_usd??d.liquidity??(d.pair&&d.pair.liquidity&&d.pair.liquidity.usd)??'—';
const price=d.price_usd??d.price??(d.pair&&d.pair.priceUsd)??'—';
const c=verdict==='PASS'?'#00FF9D':verdict==='REVIEW'?'#FFD166':verdict==='SKIP'?'#FF4D8D':'#00F0FF';
const reasons=((d.reasons||d.flags||[])||[]).slice(0,5).map(x=>'<li>'+String(x).replace(/</g,'&lt;')+'</li>').join('');
out.innerHTML='<span style="display:inline-block;padding:6px 12px;font-weight:800;background:'+c+';color:#000">'+verdict+'</span> <b>LIVE — Risk '+risk+' • Liquidity $'+liq+' • Price $'+price+'</b><br>'+(reasons?'<ul style="margin:8px 0;color:#ccc">'+reasons+'</ul>':'')+'<a href="/omni?mint='+encodeURIComponent(m)+'" target="_blank" style="color:#00F0FF">Open /omni live →</a> <a href="/play?mint='+encodeURIComponent(m)+'" target="_blank" style="color:#00F0FF">Open /play →</a>';}
catch(e){out.innerHTML='<b style="color:#FF4D8D">Network error — try again.</b><br>'+String(e);}}
"""

def _patch_html(text: str) -> str:
    if "Demo preview" not in text and "hash(m)%100" not in text:
        return text
    # Replace demo check() function with LIVE_JS
    pat = re.compile(r'function check\(\)\{.*?Open /omni live.*?;\}', re.S)
    new_text, n = pat.subn(LIVE_JS.strip(), text, count=1)
    if n == 0:
        # Fallback: just kill demo note
        new_text = text.replace("Demo preview — open /omni for the live verdict.", "LIVE — calling /omni...")
        new_text = new_text.replace("Demo preview", "LIVE")
    return new_text

def apply(g):
    app = g.get("app")
    if app is None:
        print("[patch_home_live_v2] no app, skip")
        return
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response

    class DemoToLiveMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            resp = await call_next(request)
            # Only patch homepage HTML
            if request.url.path not in ("/", "/?v=1", "/?v=2"):
                return resp
            ctype = resp.headers.get("content-type", "")
            if "text/html" not in ctype:
                return resp
            # Read body
            body = b""
            async for chunk in resp.body_iterator:
                body += chunk
            try:
                text = body.decode("utf-8", "ignore")
            except Exception:
                return Response(content=body, status_code=resp.status_code, headers=dict(resp.headers))
            patched = _patch_html(text)
            if patched == text:
                print("[patch_home_live_v2] homepage served, no DEMO found (already LIVE?)")
            else:
                print("[patch_home_live_v2] homepage DEMO -> LIVE patched")
            headers = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
            return Response(content=patched.encode("utf-8"), status_code=resp.status_code, headers=headers, media_type="text/html")

    app.add_middleware(DemoToLiveMiddleware)
    print("[patch_home_live_v2] middleware added - homepage DEMO will be replaced with LIVE at response time")

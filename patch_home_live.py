"""patch_home_live.py - MUST run LAST in main.py, after extensions.
It replaces the DEMO check() in whatever HOME_HTML is currently serving
(core_final or extensions) with a LIVE check() that calls /omni.
Why: main.py loads core_final -> features -> extensions, extensions redefines
HOME_HTML, so patching only core_final.py never reaches the served page.
"""
import re

DEMO_MARKER = "Demo preview"
LIVE_JS = """
async function check(){const m=document.getElementById('mint').value.trim();const out=document.getElementById('out');if(!m){out.innerHTML='<b>Paste a mint first.</b>';return;}
if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(m)){out.innerHTML='<b>That does not look like a Solana mint (32-44 base58 chars). Paste the full mint address.</b>';return;}
out.innerHTML='<b>Checking live...</b> — calling /omni...';
try{const r=await fetch('/omni?mint='+encodeURIComponent(m));const d=await r.json().catch(()=>({}));
if(!r.ok){out.innerHTML='<b style="color:#FF4D8D">Not found / error ('+r.status+')</b><br><span style="color:#aaa">This token has no Solana pair in DexScreener API (often USDC-quoted / PumpSwap pairs). Try /play for full detail.</span><br><a href="/omni?mint='+encodeURIComponent(m)+'" target="_blank" style="color:#00F0FF">Open /omni live →</a>';return;}
const verdict=(d.verdict||d.decision||d.signal||'').toString().toUpperCase()||'—';
const risk=d.risk_score??d.risk??d.score??'—';
const liq=d.liquidity_usd??d.liquidity??(d.pair&&d.pair.liquidity&&d.pair.liquidity.usd)??'—';
const price=d.price_usd??d.price??(d.pair&&d.pair.priceUsd)??'—';
const c=verdict==='PASS'?'#00FF9D':verdict==='REVIEW'?'#FFD166':verdict==='SKIP'?'#FF4D8D':'#00F0FF';
const reasons=((d.reasons||d.flags||[])||[]).slice(0,5).map(x=>'<li>'+String(x).replace(/</g,'&lt;')+'</li>').join('');
out.innerHTML='<span style="display:inline-block;padding:6px 12px;font-weight:800;background:'+c+';color:#000">'+verdict+'</span> <b>LIVE — Risk '+risk+' • Liquidity $'+liq+' • Price $'+price+'</b><br>'+(reasons?'<ul style="margin:8px 0;color:#ccc">'+reasons+'</ul>':'')+'<a href="/omni?mint='+encodeURIComponent(m)+'" target="_blank" style="color:#00F0FF">Open /omni live →</a> <a href="/play?mint='+encodeURIComponent(m)+'" target="_blank" style="color:#00F0FF">Open /play →</a>';}
catch(e){out.innerHTML='<b style="color:#FF4D8D">Network error — try again.</b><br>'+String(e);}}
"""

def apply(g):
    html = g.get("HOME_HTML", "")
    if not html:
        print("[patch_home_live] no HOME_HTML found, skip")
        return
    orig_len = len(html)
    # 1) Replace any demo check() function: function check(){...} up to the matching closing for that function
    # Demo pattern: function check(){const m=... Demo preview ...} - replace whole function with LIVE_JS
    # Simplest robust: replace the demo note + hash logic by swapping the entire <script> block that contains Demo preview
    if DEMO_MARKER in html:
        # Replace the demo check function block: find 'function check(){' ... up to 'Open /omni live' + closing
        # Use regex to replace from 'function check(){' to the first '}' after 'Open /omni live'
        pattern = re.compile(r'function check\(\)\{.*?Open /omni live.*?;\}', re.S)
        new_html, n = pattern.subn(LIVE_JS.strip(), html, count=1)
        if n:
            html = new_html
            print(f"[patch_home_live] replaced demo check() with LIVE check() (n={n})")
        else:
            # Fallback: just replace the demo note text so user sees LIVE instead of DEMO
            html = html.replace(DEMO_MARKER, "LIVE — calling /omni...")
            print("[patch_home_live] fallback: replaced Demo preview text only")
    else:
        print("[patch_home_live] no Demo preview in HOME_HTML, already live or different template")
    # 2) Also ensure no hash-demo remains
    if "hash(m)%100" in html:
        html = html.replace("hash(m)%100", "0")
        print("[patch_home_live] removed hash demo")
    g["HOME_HTML"] = html
    # Also update module globals so home() in core_final / extensions sees it
    try:
        import core_final as _cf
        _cf.HOME_HTML = html
    except Exception:
        pass
    try:
        import extensions as _ex
        _ex.HOME_HTML = html
    except Exception:
        pass
    print(f"[patch_home_live] done len {orig_len} -> {len(html)}")

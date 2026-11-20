"""TVibe FILTER v37 - PRO UI. Upload as app.py (overwrite)."""
import time, urllib.request, json
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="TVibe Signal")
VERSION = "v37-pro-ui"
SOL_MINT = "So11111111111111111111111111111111111111112"

HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TVibe Signal</title>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#070b12;color:#e8eef5;margin:0;padding:16px}
.top{max-width:620px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;padding:6px 2px 14px}
.logo{font-weight:800;font-size:19px;letter-spacing:.02em}
.badge{font-size:11px;background:#12231a;color:#4ade80;border:1px solid #1e3a2a;padding:5px 9px;border-radius:999px}
.card{max-width:620px;margin:0 auto;background:#101826;border:1px solid #1f2d40;border-radius:18px;padding:20px}
h1{font-size:24px;margin:0} .sub{color:#9fb0c3;font-size:13px;margin:6px 0 18px;line-height:1.5}
label{font-size:12px;color:#9fb0c3;letter-spacing:.12em;font-weight:700}
input{width:100%;margin-top:8px;padding:16px;font-size:16px;border-radius:12px;border:1px solid #2a3a4d;background:#070b12;color:#fff;outline:none}
input:focus{border-color:#22c55e}
button.check{width:100%;margin-top:12px;padding:16px;font-size:18px;font-weight:800;border:0;border-radius:12px;background:#22c55e;color:#04120a;cursor:pointer}
button.check:disabled{opacity:.6}
#out{margin-top:16px;display:none}
.verdict{font-size:32px;font-weight:900;line-height:1.1}
.verdict small{display:block;font-size:13px;font-weight:600;color:#9fb0c3;margin-top:4px}
.reason{margin:12px 0 0;font-size:14px;line-height:1.6;color:#dbe6f2}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}
.cell{background:#070b12;border:1px solid #1f2d40;border-radius:12px;padding:11px}
.cell span{display:block;font-size:11px;color:#9fb0c3;letter-spacing:.08em}
.cell b{font-size:15px}
.mint{margin-top:12px;font-size:12px;color:#9fb0c3;word-break:break-all}
.row{display:flex;gap:8px;margin-top:12px}
.row button{flex:1;padding:11px;border-radius:10px;border:1px solid #2a3a4d;background:#16222f;color:#e8eef5;cursor:pointer;font-weight:700}
details{margin-top:14px;background:#070b12;border:1px solid #1f2d40;border-radius:12px;padding:10px}
details summary{cursor:pointer;font-size:12px;color:#9fb0c3;font-weight:700}
pre{white-space:pre-wrap;word-break:break-all;font-size:11px;line-height:1.5;color:#cbd5e1;margin:10px 0 0}
.hint{max-width:620px;margin:12px auto 0;color:#7d8ea3;font-size:12px;text-align:center}
.sell{color:#f87171}.hold{color:#4ade80}.watch{color:#facc15}
</style></head><body>
<div class="top"><div class="logo">TVibe Signal</div><div class="badge">LIVE - v37</div></div>
<div class="card">
<h1>Check before you sell</h1><div class="sub">Paste a token mint. We check liquidity, volume and age - then give you a clear verdict.</div>
<label>TOKEN TO SELL</label>
<input id="mint" placeholder="Paste token mint..." autocomplete="off">
<button type="button" class="check" id="btn" onclick="check()">CHECK</button>
<div id="out">
<div class="verdict" id="v"></div>
<div class="reason" id="r"></div>
<div class="grid">
<div class="cell"><span>PRICE</span><b id="p1">-</b></div>
<div class="cell"><span>LIQUIDITY</span><b id="p2">-</b></div>
<div class="cell"><span>VOLUME 24H</span><b id="p3">-</b></div>
<div class="cell"><span>AGE / DEX</span><b id="p4">-</b></div>
</div>
<div class="mint" id="m"></div>
<div class="row">
<button type="button" onclick="copyText()">Copy verdict</button>
<button type="button" onclick="copyJson()">Copy JSON for agent</button>
</div>
<details><summary>FOR AGENT - Raw JSON</summary><pre id="j"></pre></details>
</div>
<div id="empty" style="margin-top:16px;color:#9fb0c3;font-size:14px">Paste a mint then press CHECK.</div>
</div>
<div class="hint">Not financial advice. Low liquidity = hard to exit.</div>
<script>
var lastJson=null;
async function check(){
  var m=document.getElementById('mint').value.trim();
  var out=document.getElementById('out'); var empty=document.getElementById('empty'); var btn=document.getElementById('btn');
  if(!m){empty.style.display='block'; empty.textContent='Paste a mint first.'; return;}
  btn.disabled=true; empty.style.display='block'; empty.textContent='Checking...'; out.style.display='none';
  try{
    var r=await fetch('/check?mint='+encodeURIComponent(m));
    var j=await r.json(); lastJson=j;
    if(j.error){empty.textContent='X '+j.error; btn.disabled=false; return;}
    var v=document.getElementById('v'); v.textContent=j.verdict;
    v.className='verdict '+(j.verdict.indexOf('SELL')>-1?'sell':(j.verdict.indexOf('HOLD')>-1?'hold':'watch'));
    document.getElementById('r').textContent=j.reason;
    document.getElementById('p1').textContent='$'+j.price;
    document.getElementById('p2').textContent='$'+Number(j.liquidity).toLocaleString();
    document.getElementById('p3').textContent='$'+Number(j.volume).toLocaleString();
    document.getElementById('p4').textContent=j.age_h+'h / '+j.dex;
    document.getElementById('m').textContent='Mint: '+j.mint;
    document.getElementById('j').textContent=JSON.stringify(j,null,2);
    empty.style.display='none'; out.style.display='block';
  }catch(e){ empty.textContent='Network error, try again.'; }
  btn.disabled=false;
}
function copyText(){ if(!lastJson) return; var t=lastJson.verdict+' - '+lastJson.reason+' | Price $'+lastJson.price+' | Liq $'+lastJson.liquidity+' | Vol $'+lastJson.volume; navigator.clipboard.writeText(t); alert('Copied verdict'); }
function copyJson(){ if(!lastJson) return; navigator.clipboard.writeText(JSON.stringify(lastJson)); alert('Copied JSON for agent'); }
</script></body></html>"""

@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION}

@app.get("/", response_class=HTMLResponse)
def home():
    return HTML

@app.get("/check")
def check(mint: str = Query(default="")):
    m = (mint or "").strip()
    if not m:
        return JSONResponse({"error": "mint is required"}, status_code=400)
    if m == SOL_MINT:
        return {"mint": m, "verdict": "SKIP", "reason": "SOL is the base currency, not a pump token. Paste a real token mint.", "price": 0, "liquidity": 0, "volume": 0, "age_h": 0, "dex": "-"}
    try:
        req = urllib.request.Request(f"https://api.dexscreener.com/latest/dex/tokens/{m}", headers={"User-Agent": "TVibe/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
    except Exception as e:
        return {"mint": m, "verdict": "WATCH", "reason": f"DexScreener unreachable, fail-open. ({e})", "price": 0, "liquidity": 0, "volume": 0, "age_h": 0, "dex": "-"}
    pairs = data.get("pairs") or []
    if not pairs:
        return {"mint": m, "verdict": "SELL", "reason": "No trading pair found. No liquidity = no buyer.", "price": 0, "liquidity": 0, "volume": 0, "age_h": 0, "dex": "-"}
    p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
    liq = (p.get("liquidity") or {}).get("usd") or 0
    vol = (p.get("volume") or {}).get("h24") or 0
    price = float(p.get("priceUsd") or 0)
    age_h = round((time.time()*1000 - (p.get("pairCreatedAt") or time.time()*1000)) / 3600000, 1)
    dex = p.get("dexId") or "-"
    if liq < 5000:
        v, why = "SELL", f"Liquidity too low (${liq:,.0f}). Hard to exit without big slippage."
    elif vol < 1000:
        v, why = "WATCH", f"Volume 24h too low (${vol:,.0f}). No demand right now."
    elif liq >= 20000 and vol >= liq * 0.5:
        v, why = "HOLD / BUY", f"Healthy liquidity (${liq:,.0f}) + active volume (${vol:,.0f})."
    else:
        v, why = "WATCH", f"Liquidity ${liq:,.0f}, volume ${vol:,.0f}. Not strong enough to chase."
    return {"mint": m, "verdict": v, "reason": why, "price": price, "liquidity": liq, "volume": vol, "age_h": age_h, "dex": dex, "url": p.get("url") or ""}

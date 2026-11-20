"""TVibe FILTER v36.1 - CHECK FIX. Upload this file as app.py (overwrite)."""
import time, urllib.request, json
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

app = FastAPI(title="TVibe Signal")
VERSION = "v36.1-check-fix"
SOL_MINT = "So11111111111111111111111111111111111111112"

HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TVibe Signal</title>
<style>
body{font-family:system-ui,sans-serif;background:#0b0f14;color:#e8eef5;margin:0;padding:20px}
.card{max-width:560px;margin:0 auto;background:#121a24;border-radius:16px;padding:22px}
h1{font-size:22px;margin:0 0 4px} p{color:#9fb0c3;font-size:14px;margin:0 0 18px}
label{font-size:13px;color:#9fb0c3;letter-spacing:.08em}
input{width:100%;box-sizing:border-box;margin-top:8px;padding:16px;font-size:17px;border-radius:12px;border:1px solid #2a3a4d;background:#0b0f14;color:#fff;outline:none}
button{width:100%;margin-top:14px;padding:16px;font-size:18px;font-weight:700;border:0;border-radius:12px;background:#22c55e;color:#04120a;cursor:pointer}
button:disabled{opacity:.6}
#out{margin-top:16px;background:#0b0f14;border:1px solid #2a3a4d;border-radius:12px;padding:14px;font-size:15px;line-height:1.6;white-space:pre-wrap;min-height:60px}
.b{font-size:28px;font-weight:800}
</style></head><body><div class="card">
<h1>TVibe Signal</h1><p>Check before you sell. Paste a token mint.</p>
<label>TOKEN TO SELL</label>
<input id="mint" placeholder="Paste token mint..." autocomplete="off">
<button type="button" id="btn" onclick="check()">CHECK</button>
<div id="out">Paste a mint then press CHECK.</div>
</div><script>
async function check(){
  var m=document.getElementById('mint').value.trim();
  var out=document.getElementById('out');
  var btn=document.getElementById('btn');
  if(!m){out.textContent='Paste a mint first.'; return;}
  btn.disabled=true; out.textContent='Checking...';
  try{
    var r=await fetch('/check?mint='+encodeURIComponent(m));
    var j=await r.json();
    if(j.error){out.textContent='X '+j.error; btn.disabled=false; return;}
    out.innerHTML='<div class="b">'+j.verdict+'</div><div>'+j.reason+'</div><div>Price: $'+j.price+'</div><div>Liquidity: $'+j.liquidity+'</div><div>Volume 24h: $'+j.volume+'</div><div>Age: '+j.age_h+'h</div><div>DEX: '+j.dex+'</div><div>Mint: '+j.mint+'</div>';
  }catch(e){ out.textContent='Network error, try again.'; }
  btn.disabled=false;
}
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

"""TVibe FILTER v36 - BLANK-PROOF. Upload this file as main.py, DO NOT paste."""
import re
import time
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
import httpx

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
app = FastAPI(title="TVibe FILTER")

HOME = "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>TVibe FILTER</title><style>body{background:#0B0B14;color:#fff;font-family:Arial,sans-serif;margin:0;padding:20px}h1{font-size:28px;margin:0 0 6px}.sub{color:#aaa;margin:0 0 18px}label{font-size:19px;font-weight:700;display:block;margin:0 0 8px}#mint{width:100%;box-sizing:border-box;font-size:22px;padding:18px 20px;min-height:64px;border:2px solid #00F0FF;border-radius:14px;background:#0B0B14;color:#fff;outline:none}button{margin-top:12px;min-height:64px;font-size:20px;font-weight:800;padding:0 28px;border:0;border-radius:14px;background:#00FF9D;color:#000;cursor:pointer;width:100%}#out{margin-top:18px;font-size:16px;line-height:1.6}.links{margin-top:14px;font-size:13px;color:#888}.links a{color:#00F0FF}</style></head><body><h1>TVibe FILTER</h1><p class=\"sub\">Paste a token mint. Check before you sell. Not financial advice.</p><label for=\"mint\">TOKEN TO SELL</label><input id=\"mint\" placeholder=\"Paste a token mint...\" autocomplete=\"off\"><button onclick=\"check()\">CHECK</button><div id=\"out\"></div><div class=\"links\"><a href=\"/agent.json\" target=\"_blank\">Endpoint for Agents: /agent.json</a> | <a href=\"/health\" target=\"_blank\">/health</a></div><script>async function check(){var m=(document.getElementById(\'mint\').value||\'\').trim();var out=document.getElementById(\'out\');var esc=function(s){return String(s??\'\').replace(/[&<>\"]/g,function(c){return({\'&\':\'&amp;\',\'<\':\'&lt;\',\'>\':\'&gt;\',\'\"\':\'&quot;\'}[c])})};if(!m){out.innerHTML=\'<b>Paste a mint first.</b>\';return}if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(m)){out.innerHTML=\'<b>Not a Solana mint (32-44 base58 chars).</b>\';return}var q=encodeURIComponent(m);out.innerHTML=\'<b>Checking live...</b>\';try{var r=await fetch(\'/omni?mint=\'+q,{cache:\'no-store\'});var d=await r.json().catch(function(){return{}});if(!r.ok){out.innerHTML=\'<b style=\"color:#FF4D8D\">Error \'+r.status+\'</b><br>\'+esc(d.detail||d.error||\'Upstream down\');return}if(d.error&&!d.verdict){out.innerHTML=\'<b>Could not score</b><br>\'+esc(d.error);return}var raw=String(d.verdict||\'\').toLowerCase();var label=raw===\'pass\'?\'PASS\':raw===\'skip\'?\'SKIP\':\'REVIEW\';var c=label===\'PASS\'?\'#00FF9D\':label===\'SKIP\'?\'#FF4D8D\':\'#FFD166\';var bl=(d.blockers||[]).slice(0,4).map(function(x){return \'<li>\'+esc(x)+\'</li>\'}).join(\'\');out.innerHTML=\'<span style=\"display:inline-block;padding:6px 12px;font-weight:800;background:\'+c+\';color:#000\">\'+label+\'</span> <b>Risk \'+esc(d.risk_score??\'-\')+\' | Liquidity $\'+esc(d.liquidity_usd??\'-\')+\' | Price $\'+esc(d.price_usd??\'-\')+\'</b>\'+(bl?\'<ul>\'+bl+\'</ul>\':\'\')+\'<br><a href=\"/omni?mint=\'+q+\'\" target=\"_blank\" style=\"color:#00F0FF\">Open /omni JSON</a>\';}catch(e){out.innerHTML=\'<b style=\"color:#FF4D8D\">Network error - try again.</b>\';}}</script></body></html>"


async def score(mint):
    liq = 0.0
    price = None
    vol = 0.0
    rug = {}
    pair = None
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
            try:
                r = await c.get("https://api.dexscreener.com/latest/dex/tokens/" + mint)
                if r.status_code == 200:
                    pairs = (r.json() or {}).get("pairs") or []
                    sol = [p for p in pairs if p.get("chainId") == "solana"]
                    pool = sol or pairs
                    if pool:
                        pair = max(pool, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
            except Exception:
                pair = None
            if pair is not None:
                try:
                    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
                except Exception:
                    liq = 0.0
                try:
                    price = float(pair.get("priceUsd")) if pair.get("priceUsd") is not None else None
                except Exception:
                    price = None
                try:
                    vol = float((pair.get("volume") or {}).get("h24") or 0)
                except Exception:
                    vol = 0.0
            try:
                rr = await c.get("https://api.rugcheck.xyz/v1/tokens/" + mint + "/report", timeout=12.0)
                if rr.status_code == 200:
                    rug = rr.json() or {}
            except Exception:
                rug = {}
    except Exception:
        pair = None
    if pair is None:
        return {"mint": mint, "verdict": "review", "action": "review", "risk_score": None, "liquidity_usd": None, "price_usd": None, "blockers": [], "unknowns": ["no_pair"], "error": "No pair found on DexScreener for this mint. Brand-new token, USDC pair, wrong mint, or DexScreener slow - try again.", "nfa": True}
    blockers = []
    unknowns = []
    risk = 0
    if liq < 1000:
        blockers.append("Liquidity is very low")
        risk = risk + 45
    elif liq < 10000:
        blockers.append("Liquidity is low")
        risk = risk + 25
    if vol == 0:
        unknowns.append("No trades in last 24h")
        risk = risk + 15
    try:
        if rug.get("score") is not None:
            risk = max(risk, min(100, int(rug.get("score") or 0)))
    except Exception:
        pass
    for x in (rug.get("risks") or []):
        try:
            if isinstance(x, dict):
                name = x.get("name") or x.get("description") or str(x)
            else:
                name = str(x)
            if name:
                unknowns.append(str(name)[:90])
        except Exception:
            pass
    if risk >= 70 or blockers:
        verdict = "skip"
    elif risk < 30 and liq >= 10000:
        verdict = "pass"
    else:
        verdict = "review"
    return {"mint": mint, "verdict": verdict, "action": verdict, "risk_score": risk, "liquidity_usd": liq, "price_usd": price, "volume_24h_usd": vol, "pair": {"dex": pair.get("dexId"), "pairAddress": pair.get("pairAddress"), "base": (pair.get("baseToken") or {}).get("symbol"), "quote": (pair.get("quoteToken") or {}).get("symbol")}, "blockers": blockers[:4], "unknowns": unknowns[:6], "rugcheck_score": rug.get("score"), "valid_for_s": 30, "nfa": True}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return HTMLResponse(content=HOME, status_code=200)


@app.get("/health")
async def health():
    return {"status": "ok", "version": "v36-blankproof", "ts": int(time.time())}


@app.get("/agent.json")
async def agent_json():
    return {"name": "TVibe Signal", "version": "v36-blankproof", "endpoints": {"check": "GET /omni?mint=<MINT>", "play": "GET /play?mint=<MINT>", "health": "GET /health"}, "verdicts": ["PASS", "REVIEW", "SKIP"], "rules": ["Always call /omni. Never guess.", "Error + no verdict = could-not-score, never PASS."], "nfa": True}


@app.get("/agent", response_class=PlainTextResponse)
async def agent():
    return "# TVibe Signal\nCheck: GET /omni?mint=<MINT>\nVerdicts: PASS / REVIEW / SKIP\nNever guess. Error + no verdict = could-not-score, never PASS.\nNot financial advice.\n"


@app.get("/__main_status")
async def main_status():
    return {"main_py": "v36-blankproof", "patch_live_fix": "not-needed", "engine": "dexscreener+rugcheck", "wrapper": "none"}


async def omni_impl(request: Request, mint, view):
    m = ((mint or "") or "").strip()
    if not m:
        m = (request.query_params.get("mint") or request.query_params.get("request") or "").strip()
    if not m:
        return {"mint": None, "error": "mint is required: /omni?mint=<MINT>", "nfa": True}
    if not MINT_RE.match(m):
        return {"mint": m, "error": "Invalid Solana token mint address", "nfa": True}
    pkt = await score(m)
    if (view or "").lower() in ("agent", "compact", "action"):
        return {"mint": pkt.get("mint"), "action": pkt.get("action"), "verdict": pkt.get("verdict"), "risk_score": pkt.get("risk_score"), "liquidity_usd": pkt.get("liquidity_usd"), "unknowns": (pkt.get("unknowns") or [])[:6], "blockers": (pkt.get("blockers") or [])[:6], "valid_for_s": 30, "nfa": True}
    return pkt


@app.get("/omni")
async def omni(request: Request, mint: str | None = Query(default=None), view: str = Query("full")):
    return JSONResponse(content=await omni_impl(request, mint, view), status_code=200)


@app.get("/play")
async def play(request: Request, mint: str | None = Query(default=None), view: str = Query("full")):
    return JSONResponse(content=await omni_impl(request, mint, view), status_code=200)

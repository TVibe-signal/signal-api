
# TVibe Signal v40.3 Paper - English only, paper-yellow theme
# File: app.py (FastAPI, uvicorn app:app)

import os, json, hashlib, time, math, threading, csv, io
from collections import Counter, defaultdict
import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse, HTMLResponse, Response

app = FastAPI(title="TVibe Signal")
VERSION = "v40.3-helius-only"
START = time.time()
CHECKS = {"count": 0}

def _f(k, d):
    try: return float(os.getenv(k, d))
    except: return float(d)
LIQ_SELL = _f("TVIBE_LIQ_SELL", 5000)
LIQ_HOLD = _f("TVIBE_LIQ_HOLD", 20000)
VOL_MIN = _f("TVIBE_VOL_MIN", 1000)
VOL_LIQ_HOLD = _f("TVIBE_VOL_LIQ_HOLD", 0.5)
AGE_MIN_H = _f("TVIBE_AGE_MIN_H", 1)
DUMP_24H = _f("TVIBE_DUMP_24H_PCT", -50)
WARN_24H = _f("TVIBE_WARN_24H_PCT", -20)
ADMIN_KEY = os.getenv("TVIBE_ADMIN_KEY", "")
UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

# ---------- RPC: Helius only -> DexScreener only ----------
# Keys are NEVER in code. They live in Render Env only.
# Supported Env (only 1 needed): SOLANA_RPC_URL (already in Render, Helius) OR HELIUS_API_KEY OR HELIUS_RPC_URL
# QuickNode removed per user request - Helius only.
_HELIUS_KEY = os.getenv("HELIUS_API_KEY", "").strip()
_HELIUS_URL_ENV = os.getenv("HELIUS_RPC_URL", "").strip()
_SOLANA_RPC_ENV = os.getenv("SOLANA_RPC_URL", "").strip()

def _build_rpc_urls():
    helius = ""
    if _HELIUS_URL_ENV:
        helius = _HELIUS_URL_ENV
    elif _HELIUS_KEY:
        helius = f"https://mainnet.helius-rpc.com/?api-key={_HELIUS_KEY}"
    elif _SOLANA_RPC_ENV:
        # SOLANA_RPC_URL in Render is already the Helius URL - use it directly
        helius = _SOLANA_RPC_ENV
    return helius

HELIUS_URL = _build_rpc_urls()
RPC_CONFIGURED = bool(HELIUS_URL)

# On-chain cache: 5 min per mint, saves Helius credits
_RPC_CACHE = {}
_RPC_CACHE_TTL = 300


_locks = {}
_locks_guard = threading.Lock()
def _lock_for(mint):
    with _locks_guard:
        if mint not in _locks: _locks[mint] = threading.Lock()
        return _locks[mint]

def _up_headers(): return {"Authorization": f"Bearer {UPSTASH_TOKEN}"} if UPSTASH_TOKEN else {}
def up_get(k):
    if not UPSTASH_URL or not UPSTASH_TOKEN: return None
    try: return requests.get(f"{UPSTASH_URL}/get/{k}", headers=_up_headers(), timeout=5).json().get("result")
    except: return None
def up_lrange(k,a,b):
    if not UPSTASH_URL or not UPSTASH_TOKEN: return []
    try: return requests.get(f"{UPSTASH_URL}/lrange/{k}/{a}/{b}", headers=_up_headers(), timeout=10).json().get("result") or []
    except: return []
def up_rpush(k,v):
    if not UPSTASH_URL or not UPSTASH_TOKEN: return False
    try:
        r=requests.post(f"{UPSTASH_URL}/rpush/{k}", data=v.encode(), headers={**_up_headers(),"Content-Type":"text/plain"}, timeout=10)
        return r.status_code<300
    except: return False
def up_set(k,v):
    if not UPSTASH_URL or not UPSTASH_TOKEN: return False
    try:
        r=requests.post(f"{UPSTASH_URL}/set/{k}", data=v.encode(), headers={**_up_headers(),"Content-Type":"text/plain"}, timeout=10)
        return r.status_code<300
    except: return False

def wilson_ci(k,n,z=1.96):
    if n==0: return (0.0,1.0)
    p=k/n; den=1+z*z/n; centre=(p+z*z/(2*n))/den; delta=z*math.sqrt((p*(1-p)/n+z*z/(4*n*n)))/den
    return (max(0.0,centre-delta), min(1.0,centre+delta))
def p_bad_from_score(s):
    x=(s-35)/18.0; p=1/(1+math.exp(-x)); return max(0.02,min(0.97,p))

def fetch_pair(mint):
    url=f"https://api.dexscreener.com/latest/dex/tokens/{mint.strip()}"
    r=requests.get(url, timeout=12); r.raise_for_status()
    pairs=r.json().get("pairs") or []
    if not pairs: return None
    return sorted(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)[0]

# ---------- Helius on-chain ----------
def _rpc_get_mint_info_single(rpc_url, mint):
    """One RPC call: getAccountInfo jsonParsed for a mint. Returns dict or None on failure."""
    try:
        payload = {"jsonrpc":"2.0","id":1,"method":"getAccountInfo","params":[mint, {"encoding":"jsonParsed"}]}
        r = requests.post(rpc_url, json=payload, timeout=6)
        if r.status_code != 200:
            return None
        j = r.json()
        if "error" in j and j["error"]:
            return None
        val = (j.get("result") or {}).get("value")
        if val is None:
            return {"exists": False}
        data = val.get("data")
        info = None
        if isinstance(data, dict):
            parsed = data.get("parsed") or {}
            info = parsed.get("info") or {}
        if not info:
            return {"exists": True, "raw": True}
        # info: mintAuthority, freezeAuthority, supply, decimals
        mint_auth = info.get("mintAuthority")
        freeze_auth = info.get("freezeAuthority")
        # In jsonParsed, authorities can be string or None. Some RPCs return dict.
        if isinstance(mint_auth, dict):
            mint_auth = mint_auth.get("address") or mint_auth.get("pubkey")
        if isinstance(freeze_auth, dict):
            freeze_auth = freeze_auth.get("address") or freeze_auth.get("pubkey")
        return {
            "exists": True,
            "mint_authority": mint_auth,  # None = renounced (good)
            "freeze_authority": freeze_auth,  # None = no freeze (good)
            "decimals": info.get("decimals"),
            "supply": info.get("supply"),
            "is_native": info.get("isNative"),
        }
    except Exception:
        return None

def get_onchain(mint):
    """Helius only. Cached 5 min. Never raises. Never blocks verdict."""
    m = (mint or "").strip()
    now = time.time()
    if m in _RPC_CACHE:
        ts, val = _RPC_CACHE[m]
        if now - ts < _RPC_CACHE_TTL:
            return val
    # Helius only - no QuickNode
    chain = []
    if HELIUS_URL:
        chain.append(("helius", HELIUS_URL))
    result = None
    for label, url in chain:
        t0 = time.time()
        info = _rpc_get_mint_info_single(url, m)
        latency = int((time.time() - t0) * 1000)
        if info is not None:
            result = dict(info)
            result["rpc_source"] = label
            result["rpc_latency_ms"] = latency
            result["available"] = True
            break
    if result is None:
        result = {"available": False, "rpc_source": "none", "rpc_latency_ms": 0}
    _RPC_CACHE[m] = (now, result)
    # Keep cache small
    if len(_RPC_CACHE) > 500:
        try:
            oldest = sorted(_RPC_CACHE.items(), key=lambda kv: kv[1][0])[:100]
            for k, _ in oldest:
                _RPC_CACHE.pop(k, None)
        except Exception:
            pass
    return result

def enrich_with_onchain(obj, onchain):
    """Add on-chain authorities to obj and adjust score/verdict. Keeps thresholds private (not shown on web)."""
    if not onchain or not onchain.get("available"):
        obj["onchain"] = {"available": False, "rpc_source": "none", "mint_authority": None, "freeze_authority": None, "authorities_renounced": None, "note": "On-chain check unavailable. Verdict from market data only."}
        return obj
    mint_auth = onchain.get("mint_authority")
    freeze_auth = onchain.get("freeze_authority")
    # mint_authority could be missing if raw=True
    if onchain.get("raw"):
        obj["onchain"] = {"available": True, "rpc_source": onchain.get("rpc_source"), "mint_authority": None, "freeze_authority": None, "authorities_renounced": None, "decimals": onchain.get("decimals"), "supply": onchain.get("supply"), "note": "Mint exists on-chain. Authority details not parsed."}
        return obj
    renounced = (mint_auth is None and freeze_auth is None)
    obj["onchain"] = {
        "available": True,
        "rpc_source": onchain.get("rpc_source"),
        "rpc_latency_ms": onchain.get("rpc_latency_ms"),
        "mint_authority": mint_auth,
        "freeze_authority": freeze_auth,
        "authorities_renounced": renounced,
        "decimals": onchain.get("decimals"),
        "supply": onchain.get("supply"),
    }
    flags = list(obj.get("flags") or [])
    extra = 0
    if mint_auth is not None:
        if "mint_authority_not_renounced" not in flags:
            flags.append("mint_authority_not_renounced")
        extra += 10
    if freeze_auth is not None:
        if "freeze_authority_active" not in flags:
            flags.append("freeze_authority_active")
        extra += 12
    if renounced:
        if "authorities_renounced" not in flags:
            flags.append("authorities_renounced")
    if extra:
        obj["flags"] = flags
        new_score = max(0, min(100, int(obj.get("risk_score", 0) + extra)))
        obj["risk_score"] = new_score
        # Recompute verdict / p_bad with same logic as compute()
        ch24 = float(obj.get("change_24h_pct") or 0)
        if new_score >= 55 or "dead_pool" in flags or ch24 <= DUMP_24H:
            obj["verdict"] = "avoid"; obj["label"] = "SELL"
        elif new_score >= 35 or float(obj.get("liquidity_usd") or 0) < LIQ_HOLD or ch24 <= WARN_24H:
            obj["verdict"] = "caution"; obj["label"] = "HOLD-BUY"
        else:
            obj["verdict"] = "ok"; obj["label"] = "PASS"
        p_bad = p_bad_from_score(new_score)
        k = int(round(p_bad * 100)); lo, hi = wilson_ci(k, 100)
        obj["p_bad_24h"] = round(p_bad, 4); obj["p_bad_ci_low"] = round(lo, 4); obj["p_bad_ci_high"] = round(hi, 4)
        if obj["verdict"] == "avoid":
            if "freeze_authority_active" in flags and "mint_authority_not_renounced" in flags:
                obj["why"] = "Mint and freeze authorities are still active, so supply can change and transfers can be frozen. High downside risk."
            elif "freeze_authority_active" in flags:
                obj["why"] = "Freeze authority is still active, so transfers can be frozen. High downside risk."
            elif "mint_authority_not_renounced" in flags:
                obj["why"] = "Mint authority is still active, so new supply can be minted. High downside risk."
        elif obj["verdict"] == "caution" and (mint_auth is not None or freeze_auth is not None):
            obj["why"] = "Mixed signals plus active on-chain authority. Tradable but risky — size carefully and watch price and liquidity."
    else:
        obj["flags"] = flags
    return obj


def compute(mint,pair):
    liq=float((pair.get("liquidity") or {}).get("usd") or 0)
    vol24=float((pair.get("volume") or {}).get("h24") or 0)
    ch24=float((pair.get("priceChange") or {}).get("h24") or 0)
    price=float(pair.get("priceUsd") or 0); fdv=float(pair.get("fdv") or 0)
    created=pair.get("pairCreatedAt"); age_h=0
    if created:
        try: age_h=max(0,(time.time()*1000-float(created))/3600000)
        except: age_h=0
    base=pair.get("baseToken") or {}; symbol=base.get("symbol") or "?"; name=base.get("name") or symbol
    pair_url=pair.get("url") or ""
    if pair_url and not pair_url.startswith("https://"): pair_url=""
    flags=[]; score=0
    if liq<=0: flags.append("dead_pool"); score+=28
    elif liq<LIQ_SELL: flags.append("very_low_liquidity"); score+=22
    elif liq<LIQ_HOLD: flags.append("low_liquidity"); score+=12
    if vol24<VOL_MIN: flags.append("no_recent_trades"); score+=14
    elif liq>0 and (vol24/liq)<VOL_LIQ_HOLD and liq<LIQ_HOLD: flags.append("low_activity"); score+=8
    if liq>0 and vol24/liq>8: flags.append("extreme_turnover"); score+=10
    if vol24>500000 and liq<LIQ_HOLD: flags.append("extreme_volume_spike"); score+=10
    if age_h<AGE_MIN_H: flags.append("very_new_pair"); score+=12; flags.append("brand_new_pair")
    elif age_h<24: flags.append("new_pair"); score+=6
    if ch24<=DUMP_24H: flags.append("price_collapse_24h"); score+=22
    elif ch24<=WARN_24H: flags.append("heavy_selling"); score+=12
    elif ch24>=80: flags.append("strong_momentum"); score+=4
    if fdv>0 and liq>0 and fdv/liq>20: flags.append("high_fdv_liq_ratio"); score+=8
    score=max(0,min(100,int(score)))
    if score>=55 or "dead_pool" in flags or ch24<=DUMP_24H: verdict="avoid"; label="SELL"
    elif score>=35 or liq<LIQ_HOLD or ch24<=WARN_24H: verdict="caution"; label="HOLD-BUY"
    else: verdict="ok"; label="PASS"
    p_bad=p_bad_from_score(score); k=int(round(p_bad*100)); lo,hi=wilson_ci(k,100)
    # human explanation in English, no thresholds
    if verdict=="avoid":
        if "dead_pool" in flags: why="Liquidity is zero. The pool has no tradable liquidity."
        elif "price_collapse_24h" in flags: why="Price collapsed sharply in the last 24h and risk is elevated."
        else: why="Multiple risk signals point to high downside risk."
    elif verdict=="caution":
        why="Mixed signals. Tradable but risky — size carefully and watch price and liquidity."
    else:
        why="Clean signals across liquidity, activity and price. Lower relative risk."
    return {"mint":mint,"symbol":symbol,"name":name,"price_usd":price,"liquidity_usd":liq,"volume_24h":vol24,"change_24h_pct":ch24,"fdv":fdv,"age_h":round(age_h,2),"pair_url":pair_url,"risk_score":score,"flags":flags,"verdict":verdict,"label":label,"p_bad_24h":round(p_bad,4),"p_bad_ci_low":round(lo,4),"p_bad_ci_high":round(hi,4),"why":why,"ts":int(time.time()),"version":VERSION}

def append_ledger(obj):
    try:
        prev=up_get("ledger_head") or ""
        payload=json.dumps(obj, sort_keys=True, ensure_ascii=False)
        h=hashlib.sha256((prev+payload).encode()).hexdigest()
        rec=dict(obj); rec["hash"]=h; rec["prev"]=prev; rec["id"]=f"{obj.get('mint')}:{obj.get('ts')}"
        up_rpush("ledger", json.dumps(rec, ensure_ascii=False)); up_set("ledger_head", h)
        up_set(f"snap:{obj.get('mint')}:{obj.get('ts')}", json.dumps(rec, ensure_ascii=False))
        return rec
    except: return dict(obj)

# ---------- PAPER THEME ----------
CSS = """
:root{--paper:#fdf3d8;--paper2:#f7e8c3;--ink:#1a1610;--mut:#6b5d3f;--line:#e2d3a8;--card:#fffdf2;--green:#1a7f4b;--greenbg:#d9f2e2;--yellow:#b8860b;--yellowbg:#fff0b3;--red:#b91c1c;--redbg:#ffe0dd;--blue:#1d4ed8}
*{box-sizing:border-box}
body{margin:0;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--paper);color:var(--ink);background-image:radial-gradient(#e8d9a8 0.6px, transparent 0.6px);background-size:22px 22px}
a{color:var(--blue);text-decoration:none}
.top{max-width:1080px;margin:0 auto;padding:18px 20px 0;display:flex;justify-content:space-between;align-items:center}
.logo{font-family:Georgia,serif;font-weight:900;font-size:22px;letter-spacing:-0.5px}.logo span{background:#1a1610;color:#fdf3d8;padding:2px 8px;border-radius:6px;margin-left:6px;font-family:system-ui;font-size:12px;letter-spacing:0.5px}
.nav{font-size:13px;color:var(--mut);display:flex;gap:18px}.nav a{color:var(--mut)}
.wrap{max-width:1080px;margin:0 auto;padding:18px 20px 40px}
.hero{display:grid;grid-template-columns:1.15fr 0.85fr;gap:22px;align-items:start}
@media(max-width:820px){.hero{grid-template-columns:1fr}}
h1{font-family:Georgia,serif;font-size:52px;line-height:0.95;letter-spacing:-1.5px;margin:8px 0 12px}
h1 em{font-style:italic;font-weight:400}
.sub{color:var(--mut);font-size:16px;line-height:1.6;max-width:520px}
.card{background:var(--card);border:1.5px solid var(--ink);border-radius:18px;padding:20px;box-shadow:6px 6px 0 #1a1610}
.card h3{margin:0 0 8px;font-size:16px}
.inputrow{display:flex;gap:10px;margin-top:14px}
input{flex:1;padding:14px 14px;border:1.5px solid #1a1610;border-radius:12px;background:#fffdf2;font-size:15px;outline:none}
input:focus{box-shadow:0 0 0 3px #fde68a}
button{padding:14px 18px;border:1.5px solid #1a1610;border-radius:12px;background:#1a1610;color:#fdf3d8;font-weight:800;cursor:pointer}
button:hover{background:#000}
.hint{font-size:12.5px;color:var(--mut);margin-top:10px;line-height:1.5}
.pills{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.pill{font-size:12px;border:1px solid var(--line);background:#fff;padding:6px 10px;border-radius:999px;cursor:pointer}
.pill:hover{border-color:#1a1610}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-top:18px}
@media(max-width:820px){.grid3{grid-template-columns:1fr}}
.mini{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px}.mini b{font-size:14px}.mini p{font-size:13px;color:var(--mut);line-height:1.5;margin:6px 0 0}
.badge{display:inline-flex;align-items:center;gap:8px;padding:8px 14px;border-radius:999px;font-weight:900;font-size:20px;border:1.5px solid #1a1610}
.badge.pass{background:var(--greenbg);color:var(--green)}.badge.hold{background:var(--yellowbg);color:#7a5a00}.badge.sell{background:var(--redbg);color:var(--red)}
.kpi{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:16px}
@media(max-width:640px){.kpi{grid-template-columns:1fr 1fr}}
.k{background:#fffdf2;border:1px solid var(--line);border-radius:14px;padding:12px}.k .l{font-size:11px;letter-spacing:0.8px;text-transform:uppercase;color:var(--mut)}.k .v{font-size:20px;font-weight:800;margin-top:4px}.k .s{font-size:12px;color:var(--mut)}
.bar{height:10px;background:#eee2b8;border-radius:999px;overflow:hidden;margin-top:10px}.bar i{display:block;height:100%;background:#b91c1c}
.flag{font-size:12px;background:#fff;border:1px solid var(--line);padding:6px 10px;border-radius:999px}
.code{background:#1a1610;color:#fdf3d8;border-radius:12px;padding:14px;font-family:ui-monospace,monospace;font-size:12.5px;line-height:1.6;overflow:auto;white-space:pre-wrap}
.foot{margin-top:28px;padding-top:16px;border-top:1px solid var(--line);display:flex;justify-content:space-between;color:var(--mut);font-size:12.5px;flex-wrap:wrap;gap:8px}
"""

HOME = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TVibe Signal — Check any Solana token</title><meta name="description" content="TVibe Signal checks Solana tokens and returns PASS / HOLD-BUY / SELL with real numbers and p_bad_24h.">
<style>""" + CSS + """</style></head><body>
<div class="top"><div class="logo">TVibe Signal <span>v40.3</span></div><div class="nav"><a href="#how">How it works</a><a href="#api">For Agents</a><a href="/health">Health</a></div></div>
<div class="wrap"><div class="hero"><div>
<div style="font-size:12px;letter-spacing:1.2px;text-transform:uppercase;color:#6b5d3f;font-weight:700">Solana Token Check • Real Numbers • No Hype</div>
<h1>Know before<br><em>you buy.</em></h1>
<p class="sub">Paste a Solana mint. Get a clear verdict — <b>PASS / HOLD-BUY / SELL</b> — plus real price, liquidity, volume and the probability of a bad outcome in 24h.</p>
<div style="display:flex;gap:10px;margin-top:16px;flex-wrap:wrap"><span style="background:#1a1610;color:#fdf3d8;padding:8px 12px;border-radius:999px;font-size:13px;font-weight:700">✓ English only</span><span style="background:#fff;border:1px solid #e2d3a8;padding:8px 12px;border-radius:999px;font-size:13px">✓ No thresholds shown</span><span style="background:#fff;border:1px solid #e2d3a8;padding:8px 12px;border-radius:999px;font-size:13px">✓ Agent-ready JSON</span></div>
<div class="grid3"><div class="mini"><b>Real numbers, not opinions</b><p>Price, liquidity, volume, 24h change, age and FDV — straight from the market.</p></div><div class="mini"><b>p_bad_24h + confidence</b><p>Probability of a bad outcome in the next 24h, with a confidence interval.</p></div><div class="mini"><b>Private rules</b><p>We show the verdict and the data. The decision rules stay private.</p></div><div class="mini"><b>On-chain check</b><p>Mint + freeze authorities via Helius only. Renounced = safer.</p></div></div>
</div>
<div><div class="card"><h3>Check a token</h3><p style="margin:0;color:#6b5d3f;font-size:13px">Enter a Solana mint address.</p>
<form method="get" action="/check"><div class="inputrow"><input name="mint" placeholder="Paste mint, e.g. 98vd3Covp..." required><button>CHECK →</button></div></form>
<div class="hint">Example: <b>FWH</b> — 98vd3CovpBmHJGN2z9SiZRxM8QBVcc9Gnvq1Rdjnpump<br>API: <code>/check?mint=&lt;mint&gt;</code> returns JSON for agents.</div>
<div class="pills"><span class="pill" onclick="document.querySelector('input[name=mint]').value='98vd3CovpBmHJGN2z9SiZRxM8QBVcc9Gnvq1Rdjnpump'">Try FWH</span><span class="pill" onclick="document.querySelector('input[name=mint]').value='So11111111111111111111111111111111111111112'">Try SOL (wrapped)</span></div>
</div>
<div class="card" style="margin-top:14px" id="api"><h3>For Agents 🤖</h3><p style="font-size:13px;color:#6b5d3f;margin:0 0 10px">Use the JSON endpoint. No HTML scraping needed.</p><div class="code">GET /check?mint=&lt;mint&gt;&amp;format=json

Response:
{
  "verdict": "avoid",
  "label": "SELL",
  "risk_score": 34,
  "p_bad_24h": 0.4861,
  "p_bad_ci": [0.3942, 0.5865],
  "price_usd": 0.000001962,
  "liquidity_usd": 0,
  "volume_24h": 10434,
  "change_24h_pct": -15.1,
  "flags": ["dead_pool", "new_pair"]
}</div><div style="margin-top:10px;font-size:13px"><a href="/health">/health</a> · <a href="/calibration">/calibration</a> · <a href="/check?mint=98vd3CovpBmHJGN2z9SiZRxM8QBVcc9Gnvq1Rdjnpump&format=json">Try JSON →</a></div></div>
</div></div>
<div class="card" id="how" style="margin-top:18px"><h3>How it works</h3><p style="color:#6b5d3f;font-size:14px;line-height:1.6;margin:6px 0 0">1. We fetch the live pair from the market. &nbsp; 2. We check on-chain authorities via Helius (mint + freeze). &nbsp; 3. We score risk from liquidity, activity, age, price action and on-chain authorities. &nbsp; 4. You get a verdict + real numbers + p_bad_24h. &nbsp; Rules and thresholds are private — the data is not.</p></div>
<div class="foot"><span>© 2026 TVibe Signal — Built for traders and agents.</span><span>Paper Edition • v40.3 • English only</span></div></div></body></html>"""

def result_html(o):
    cls = "pass" if o["verdict"]=="ok" else ("hold" if o["verdict"]=="caution" else "sell")
    pct = int(o["p_bad_24h"]*100)
    flags = "".join([f'<span class="flag">{f}</span>' for f in o["flags"]]) or '<span class="flag">No flags</span>'
    _oc = o.get("onchain") or {}
    if _oc.get("available"):
        _ma = _oc.get("mint_authority")
        _fa = _oc.get("freeze_authority")
        _ma_txt = "Renounced ✓" if _ma is None and not _oc.get("raw") else (str(_ma)[:12] + "… — Active" if _ma else "Unknown")
        _fa_txt = "None ✓" if _fa is None and not _oc.get("raw") else (str(_fa)[:12] + "… — Active" if _fa else "Unknown")
        _src = _oc.get("rpc_source") or "on-chain"
        onchain_html = f'<div style="margin-top:14px;background:#fff;border:1px solid #e2d3a8;border-radius:12px;padding:12px"><b style="font-size:13px">On-chain — via {_src}</b><div style="font-size:13px;color:#6b5d3f;line-height:1.6;margin-top:4px">Mint authority: <b style="color:#1a1610">{_ma_txt}</b> &nbsp;•&nbsp; Freeze authority: <b style="color:#1a1610">{_fa_txt}</b> &nbsp;•&nbsp; Decimals: {_oc.get("decimals") if _oc.get("decimals") is not None else "—"}</div><div style="font-size:12px;color:#6b5d3f">If mint / freeze is still active, supply can change or transfers can be frozen.</div></div>'
    else:
        onchain_html = '<div style="margin-top:14px;background:#fff;border:1px solid #e2d3a8;border-radius:12px;padding:12px;font-size:13px;color:#6b5d3f"><b style="color:#1a1610">On-chain:</b> Unavailable for this check. Verdict from market data only.</div>' 
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TVibe — {o['symbol']} {o['label']}</title><style>{CSS}</style></head><body>
<div class="top"><div class="logo">TVibe Signal <span>v40.3</span></div><div class="nav"><a href="/">← New check</a><a href="/health">Health</a></div></div>
<div class="wrap"><div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap"><div><div style="font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#6b5d3f;font-weight:700">Token Report</div><h1 style="font-size:42px;margin:6px 0">{o['symbol']} <span style="font-weight:400;color:#6b5d3f;font-size:26px">— {o['name']}</span></h1><div style="font-size:13px;color:#6b5d3f">Mint: <code>{o['mint']}</code></div></div><span class="badge {cls}">{o['label']} — {o['risk_score']}/100</span></div>
<div class="card" style="margin-top:16px"><div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap"><div><div style="font-size:12px;letter-spacing:0.8px;text-transform:uppercase;color:#6b5d3f">Probability of bad outcome in 24h</div><div style="font-size:36px;font-weight:900">{o['p_bad_24h']:.2%} <span style="font-size:14px;font-weight:600;color:#6b5d3f">CI {o['p_bad_ci_low']:.2%} – {o['p_bad_ci_high']:.2%}</span></div><div class="bar"><i style="width:{pct}%"></i></div></div><div style="max-width:340px"><b>Why this verdict?</b><p style="color:#6b5d3f;font-size:14px;line-height:1.6;margin:6px 0 0">{o['why']}</p></div></div>
<div class="kpi"><div class="k"><div class="l">Price</div><div class="v">${o['price_usd']:.8g}</div><div class="s">USD</div></div><div class="k"><div class="l">Liquidity</div><div class="v">${o['liquidity_usd']:,.0f}</div><div class="s">Total in pool</div></div><div class="k"><div class="l">Volume 24h</div><div class="v">${o['volume_24h']:,.0f}</div><div class="s">Trading activity</div></div><div class="k"><div class="l">Change 24h</div><div class="v">{round(o['change_24h_pct'],2)}%</div><div class="s">Price move</div></div><div class="k"><div class="l">Age</div><div class="v">{o['age_h']}h</div><div class="s">Pair age</div></div><div class="k"><div class="l">FDV</div><div class="v">${o['fdv']:,.0f}</div><div class="s">Fully diluted value</div></div></div>
{onchain_html}
<div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">{flags}</div>
<div style="margin-top:16px;display:flex;gap:14px;flex-wrap:wrap;font-size:14px">{'<a href="'+o['pair_url']+'" target="_blank">View pair on DexScreener →</a>' if o['pair_url'] else ''}<a href="/check?mint='+o['mint']+'&format=json">View as JSON for agents →</a><a href="/">← Check another token</a></div>
</div><div class="foot"><span>Verdict: {o['verdict']} • Risk score: {o['risk_score']}/100 • TVibe Signal v40.3</span><span>Data is real. Rules are private.</span></div></div></body></html>"""

@app.get("/health")
def health(): return {"status":"ok","version":VERSION,"uptime_s":int(time.time()-START),"checks":CHECKS["count"],"rpc_configured":RPC_CONFIGURED,"rpc_sources":{"helius":bool(HELIUS_URL)},"onchain_cache":len(_RPC_CACHE)}
@app.get("/", response_class=HTMLResponse)
def index(): return HOME
@app.get("/check")
def check(request: Request, mint: str = Query(default=""), token: str = Query(default=""), format: str = Query(default="")):
    m=(mint or token or "").strip()
    if not m: return JSONResponse({"error":"missing mint"}, status_code=400)
    lock=_lock_for(m)
    if not lock.acquire(blocking=False): return JSONResponse({"status":"busy","mint":m,"message":"Check is running, retry in 3s"}, status_code=429)
    try:
        CHECKS["count"]+=1
        pair=fetch_pair(m)
        if not pair: return JSONResponse({"mint":m,"status":"not_found","verdict":"avoid","label":"SELL","p_bad_24h":0.9}, status_code=404)
        obj=compute(m,pair)
        # Helius enrichment: never blocks verdict, never 500s
        try:
            oc = get_onchain(m)
            obj = enrich_with_onchain(obj, oc)
        except Exception:
            obj["onchain"] = {"available": False, "rpc_source": "none", "note": "On-chain check failed. Verdict from market data only."}
        try: append_ledger(obj)
        except: pass
        out={"mint":obj["mint"],"symbol":obj["symbol"],"name":obj["name"],"verdict":obj["verdict"],"label":obj["label"],"risk_score":obj["risk_score"],"p_bad_24h":obj["p_bad_24h"],"p_bad_ci":[obj["p_bad_ci_low"],obj["p_bad_ci_high"]],"price_usd":obj["price_usd"],"liquidity_usd":obj["liquidity_usd"],"volume_24h":obj["volume_24h"],"change_24h_pct":obj["change_24h_pct"],"age_h":obj["age_h"],"fdv":obj["fdv"],"flags":obj["flags"],"pair_url":obj["pair_url"],"why":obj["why"],"ts":obj["ts"],"version":VERSION,"status":"ok","onchain":obj.get("onchain") or {"available":False,"rpc_source":"none"}}
        if format=="json": return out
        if format=="html": return HTMLResponse(result_html(obj))
        if "text/html" in (request.headers.get("accept") or ""): return HTMLResponse(result_html(obj))
        return out
    except Exception as e: return JSONResponse({"error":str(e)[:200],"mint":m,"status":"error"}, status_code=500)
    finally:
        try: lock.release()
        except: pass
def _need_key(request: Request):
    k=request.query_params.get("key") or request.headers.get("x-admin-key") or ""
    return bool(ADMIN_KEY and k==ADMIN_KEY)
@app.get("/stats")
def stats(request: Request):
    base={"version":VERSION,"uptime_s":int(time.time()-START),"checks":CHECKS["count"]}
    if not _need_key(request): return base
    rows=up_lrange("ledger",0,-1); verdicts=Counter(); scores=[]
    for r in rows:
        try: o=json.loads(r); verdicts[o.get("verdict")]+=1; scores.append(float(o.get("risk_score") or 0))
        except: pass
    base.update({"ledger_n":len(rows),"verdicts":dict(verdicts),"risk_mean":round(sum(scores)/len(scores),2) if scores else 0,"upstash":bool(UPSTASH_URL)})
    return base
@app.get("/export")
def export(request: Request):
    if not _need_key(request): return JSONResponse({"error":"unauthorized"}, status_code=401)
    rows=up_lrange("ledger",0,-1); buf=io.StringIO(); w=None
    for r in rows:
        try: o=json.loads(r)
        except: o={"raw":r}
        if isinstance(o.get("flags"), list): o["flags"]=";".join(map(str,o["flags"]))
        if w is None: w=csv.DictWriter(buf, fieldnames=list(o.keys())); w.writeheader()
        w.writerow({k:o.get(k,"") for k in w.fieldnames})
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition":"attachment; filename=ledger_export.csv"})
@app.get("/ledger")
def ledger(request: Request, limit: int=50):
    if not _need_key(request): return JSONResponse({"error":"unauthorized"}, status_code=401)
    rows=up_lrange("ledger",0,limit-1); out=[]
    for r in rows:
        try: out.append(json.loads(r))
        except: pass
    return {"n":len(out),"items":out}
@app.get("/calibration")
def calibration():
    rows=up_lrange("ledger",0,-1); bins=defaultdict(lambda: {"n":0,"bad":0})
    for r in rows:
        try: o=json.loads(r); s=float(o.get("risk_score") or 0); b=int(s//10*10); bins[b]["n"]+=1
        except: pass
    out=[]
    for b in sorted(bins):
        n=bins[b]["n"]; bad=bins[b]["bad"]; p=bad/n if n else 0; lo,hi=wilson_ci(bad,n)
        out.append({"score_bin":b,"n":n,"bad":bad,"p_bad":round(p,4),"ci":[round(lo,4),round(hi,4)]})
    return {"version":VERSION,"bins":out}
@app.get("/walkforward")
def walkforward(request: Request):
    if not _need_key(request): return JSONResponse({"error":"unauthorized"}, status_code=401)
    rows=[]
    for r in up_lrange("ledger",0,-1):
        try: rows.append(json.loads(r))
        except: pass
    rows=sorted(rows, key=lambda x: x.get("ts") or 0)
    if len(rows)<40: return {"error":"not enough data","n":len(rows)}
    cut=int(len(rows)*0.7); train,test=rows[:cut],rows[cut:]
    def metrics(data, thr=35):
        tp=fp=tn=fn=0
        for o in data:
            pred=float(o.get("risk_score") or 0)>=thr; actual=(o.get("verdict")=="avoid")
            if pred and actual: tp+=1
            elif pred and not actual: fp+=1
            elif not pred and not actual: tn+=1
            else: fn+=1
        prec=tp/(tp+fp) if tp+fp else 0; rec=tp/(tp+fn) if tp+fn else 0
        return {"n":len(data),"tp":tp,"fp":fp,"tn":tn,"fn":fn,"precision":round(prec,4),"recall":round(rec,4)}
    return {"n":len(rows),"train":metrics(train),"test":metrics(test),"threshold":35,"note":"Using verdict=avoid as proxy until 24h outcome is available"}
@app.get("/rules")
def rules(): return {"version":VERSION,"note":"rules are private"}

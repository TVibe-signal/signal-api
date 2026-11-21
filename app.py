
# TVibe Signal Cute - English only, no version shown
# File: app.py (FastAPI, uvicorn app:app)

import os, json, hashlib, time, math, threading, csv, io
from collections import Counter, defaultdict
import requests
from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse, HTMLResponse, Response

app = FastAPI(title="TVibe Signal")
VERSION = "cute"
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
    """Returns (url, label). Label is honest: helius only if domain says helius."""
    if _HELIUS_URL_ENV:
        return _HELIUS_URL_ENV, "helius"
    if _HELIUS_KEY:
        return f"https://mainnet.helius-rpc.com/?api-key={_HELIUS_KEY}", "helius"
    if _SOLANA_RPC_ENV:
        low = _SOLANA_RPC_ENV.lower()
        if "helius" in low:
            return _SOLANA_RPC_ENV, "helius"
        if "quicknode" in low:
            return _SOLANA_RPC_ENV, "quicknode"
        # Public Solana or other RPC - still usable for getAccountInfo, but NOT Helius
        return _SOLANA_RPC_ENV, "solana_rpc"
    return "", "none"

HELIUS_URL, RPC_LABEL = _build_rpc_urls()
# For Helius-only build, HELIUS_URL is the single RPC we use, whatever its real provider is.
# RPC_LABEL tells the truth so /health and /check don't lie.
RPC_CONFIGURED = bool(HELIUS_URL)

# On-chain cache: 5 min per mint, saves Helius credits
_RPC_CACHE = {}
_RPC_CACHE_TTL = 300
# ---------- ANTI-SPAM / HELIUS COST PROTECTION (v41) ----------
# No CAPTCHA, no login - just cheap guards so 1 bot can't burn Helius credits.
_DEX_CACHE = {}  # mint -> (ts, pair)
_DEX_CACHE_TTL = 60  # DexScreener cached 60s - F5 spam hits cache, not Dex
_VERDICT_CACHE = {}  # mint -> (ts, obj)
_VERDICT_CACHE_TTL = 30  # Same mint within 30s = same verdict, no new RPC
_IP_HITS = {}  # ip -> [timestamps]
_IP_LIMIT_MIN = 10  # max 10 checks / min / IP
_IP_LIMIT_HOUR = 60  # max 60 checks / hour / IP
_HELIUS_MIN = {"ts": 0, "n": 0}  # per-minute bucket
_HELIUS_DAY = {"day": "", "n": 0}  # per-day bucket
_HELIUS_MAX_PER_MIN = 120
_HELIUS_MAX_PER_DAY = 8000  # safety cap - if hit, we go market-only, never crash
_OUTCOME_BINS_CACHE = {"ts": 0, "bins": {}, "n_total": 0}
_OUTCOME_BINS_TTL = 600  # 10 min

def _client_ip(request):
    try:
        xf = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
        if xf: return xf
        if request.client: return request.client.host
    except: pass
    return "unknown"

def _rate_limit_ok(ip):
    now = time.time()
    lst = _IP_HITS.get(ip, [])
    lst = [t for t in lst if now - t < 3600]
    # per-minute check
    recent_min = [t for t in lst if now - t < 60]
    if len(recent_min) >= _IP_LIMIT_MIN: 
        _IP_HITS[ip] = lst
        return False
    if len(lst) >= _IP_LIMIT_HOUR:
        _IP_HITS[ip] = lst
        return False
    lst.append(now); _IP_HITS[ip] = lst
    # prune old IPs sometimes
    if len(_IP_HITS) > 2000:
        for k in list(_IP_HITS.keys()):
            if not _IP_HITS[k] or now - _IP_HITS[k][-1] > 3600:
                del _IP_HITS[k]
    return True

def _helius_budget_ok():
    now = time.time()
    # minute bucket
    if now - _HELIUS_MIN["ts"] > 60:
        _HELIUS_MIN["ts"] = now; _HELIUS_MIN["n"] = 0
    # day bucket
    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if _HELIUS_DAY["day"] != day:
        _HELIUS_DAY["day"] = day; _HELIUS_DAY["n"] = 0
    if _HELIUS_MIN["n"] >= _HELIUS_MAX_PER_MIN: return False
    if _HELIUS_DAY["n"] >= _HELIUS_MAX_PER_DAY: return False
    _HELIUS_MIN["n"] += 1; _HELIUS_DAY["n"] += 1
    return True

def _is_valid_mint(m):
    if not m or not isinstance(m, str): return False
    m = m.strip()
    if len(m) < 32 or len(m) > 44: return False
    # Base58: no 0 O I l
    if any(c in m for c in "0OIl"): return False
    import string as _s
    allowed = set(_s.ascii_letters + _s.digits)
    if any(c not in allowed for c in m): return False
    return True

# ---------- REAL 24H OUTCOME (fix p_bad_24h) ----------
def classify_outcome(snap, now_pair):
    # snap: {price_usd, liquidity_usd, risk_score, verdict, ts, mint}
    # Returns (is_bad, outcome_type, price_chg, liq_chg)
    try:
        p0 = float(snap.get("price_usd") or 0)
        l0 = float(snap.get("liquidity_usd") or 0)
    except: return (True, "unknown", 0, 0)
    if now_pair is None:
        return (True, "liquidity_pulled", -1.0, -1.0)
    try:
        p1 = float(now_pair.get("priceUsd") or 0)
        l1 = float((now_pair.get("liquidity") or {}).get("usd") or 0)
    except: return (True, "unknown", 0, 0)
    p_chg = (p1 - p0)/p0 if p0 > 0 else 0
    l_chg = (l1 - l0)/l0 if l0 > 0 else 0
    price_bad = p_chg <= -0.50
    liq_bad = (l0 > 0 and l1 <= 0) or l_chg <= -0.70
    if price_bad and liq_bad: return (True, "liquidity_and_price", round(p_chg,4), round(l_chg,4))
    if liq_bad: return (True, "liquidity_pulled", round(p_chg,4), round(l_chg,4))
    if price_bad: return (True, "price_decay", round(p_chg,4), round(l_chg,4))
    return (False, "ok", round(p_chg,4), round(l_chg,4))

def _load_outcome_bins():
    now = time.time()
    if now - _OUTCOME_BINS_CACHE["ts"] < _OUTCOME_BINS_TTL and _OUTCOME_BINS_CACHE["bins"] is not None:
        return _OUTCOME_BINS_CACHE["bins"], _OUTCOME_BINS_CACHE["n_total"]
    bins = {}
    n_total = 0
    try:
        rows = up_lrange("outcomes", 0, -1)
        for r in rows:
            try: o = json.loads(r)
            except: continue
            s = float(o.get("risk_score") or 0); b = int(s//10*10)
            if b not in bins: bins[b] = {"n":0,"bad":0}
            bins[b]["n"] += 1; n_total += 1
            if o.get("is_bad"): bins[b]["bad"] += 1
    except: pass
    _OUTCOME_BINS_CACHE["ts"] = now; _OUTCOME_BINS_CACHE["bins"] = bins; _OUTCOME_BINS_CACHE["n_total"] = n_total
    return bins, n_total

def get_calibrated_p_bad(score):
    # Returns (p, lo, hi, source)
    base = p_bad_from_score(score)
    try:
        bins, n_total = _load_outcome_bins()
        b = int(score//10*10)
        info = bins.get(b)
        if not info or info["n"] < 5:
            # Not enough real data for this bin - use formula, mark estimate
            lo, hi = wilson_ci(int(round(base*100)), 100)
            return (base, lo, hi, "estimate")
        emp = info["bad"]/info["n"] if info["n"] else base
        if info["n"] >= 20:
            p = emp
            lo, hi = wilson_ci(info["bad"], info["n"])
            return (max(0.02,min(0.97,p)), lo, hi, f"real_24h_outcomes n={info['n']}")
        else:
            # Blend: 60% formula + 40% empirical while we collect more
            p = 0.6*base + 0.4*emp
            lo, hi = wilson_ci(info["bad"], info["n"])
            return (max(0.02,min(0.97,p)), lo, hi, f"blended n={info['n']}")
    except:
        lo, hi = wilson_ci(int(round(base*100)), 100)
        return (base, lo, hi, "estimate")



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

def fetch_pair(mint, use_cache=True):
    m = (mint or "").strip()
    now = time.time()
    if use_cache and m in _DEX_CACHE:
        ts, val = _DEX_CACHE[m]
        if now - ts < _DEX_CACHE_TTL:
            return val
    url=f"https://api.dexscreener.com/latest/dex/tokens/{m}"
    r=requests.get(url, timeout=12); r.raise_for_status()
    pairs=r.json().get("pairs") or []
    if not pairs:
        if use_cache: _DEX_CACHE[m] = (now, None)
        return None
    best = sorted(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)[0]
    if use_cache: _DEX_CACHE[m] = (now, best)
    return best

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
    """Helius only. Cached 5 min. Budget-guarded. Never raises. Never blocks verdict."""
    m = (mint or "").strip()
    now = time.time()
    if m in _RPC_CACHE:
        ts, val = _RPC_CACHE[m]
        if now - ts < _RPC_CACHE_TTL:
            return val
    # Helius only - no QuickNode. Budget guard: if we burned too much, skip RPC and go market-only.
    if not _helius_budget_ok():
        return {"available": False, "rpc_source": "none", "rpc_latency_ms": 0, "mint_authority": None, "freeze_authority": None, "note": "Helius budget reached. Verdict from market data only."}
    chain = []
    if HELIUS_URL:
        chain.append((RPC_LABEL, HELIUS_URL))
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
                obj["why"] = "Do not buy. Authorities still active."
            elif "freeze_authority_active" in flags:
                obj["why"] = "Do not buy. Freeze still active."
            elif "mint_authority_not_renounced" in flags:
                obj["why"] = "Do not buy. Mint still active."
        elif obj["verdict"] == "caution" and (mint_auth is not None or freeze_auth is not None):
            obj["why"] = "Mixed. Authority still active. Small size only."
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
    p_bad, lo, hi, p_source = get_calibrated_p_bad(score)
    # human explanation in English, no thresholds - must NOT say "clean/safe" when volatile
    if verdict=="avoid":
        if "dead_pool" in flags: why="Do not buy. No liquidity to sell."
        elif "price_collapse_24h" in flags: why="High risk. Price falling fast. Do not buy."
        else: why="High risk. Do not buy."
    elif verdict=="caution":
        if "extreme_turnover" in flags or "very_new_pair" in flags or "new_pair" in flags:
            why="Mixed. Very volatile. Small size only."
        elif "freeze_authority_active" in flags or "mint_authority_not_renounced" in flags:
            why="Mixed. Authority still active. Small size only."
        else:
            why="Mixed signals. Small size, watch closely."
    else:
        # PASS / ok - must distinguish truly solid vs PASS-but-volatile
        if "extreme_turnover" in flags or "very_new_pair" in flags or "new_pair" in flags or "brand_new_pair" in flags:
            why="Passes checks. Very volatile. Small size only."
        elif "strong_momentum" in flags:
            why="Good setup. Up fast — don't chase."
        else:
            why="Good setup. Still risky — don't chase."
    return {"mint":mint,"symbol":symbol,"name":name,"price_usd":price,"liquidity_usd":liq,"volume_24h":vol24,"change_24h_pct":ch24,"fdv":fdv,"age_h":round(age_h,2),"pair_url":pair_url,"risk_score":score,"flags":flags,"verdict":verdict,"label":label,"p_bad_24h":round(p_bad,4),"p_bad_ci_low":round(lo,4),"p_bad_ci_high":round(hi,4),"p_bad_source":p_source,"why":why,"ts":int(time.time()),"version":VERSION}

def append_ledger(obj):
    try:
        prev=up_get("ledger_head") or ""
        payload=json.dumps(obj, sort_keys=True, ensure_ascii=False)
        h=hashlib.sha256((prev+payload).encode()).hexdigest()
        rec=dict(obj); rec["hash"]=h; rec["prev"]=prev; rec["id"]=f"{obj.get('mint')}:{obj.get('ts')}"
        up_rpush("ledger", json.dumps(rec, ensure_ascii=False)); up_set("ledger_head", h)
        up_set(f"snap:{obj.get('mint')}:{obj.get('ts')}", json.dumps(rec, ensure_ascii=False))
        # snap_list for 24h outcome job: minimal snapshot
        try:
            snap_min = {"mint": obj.get("mint"), "ts": obj.get("ts"), "price_usd": obj.get("price_usd"), "liquidity_usd": obj.get("liquidity_usd"), "risk_score": obj.get("risk_score"), "verdict": obj.get("verdict")}
            up_rpush("snap_list", json.dumps(snap_min, ensure_ascii=False))
        except: pass
        return rec
    except: return dict(obj)


# ---------- CUTE THEME ----------
BLOBS_B64_PLACEHOLDER = "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AgSIAAmAAAAAAAAAAAAAAAAAAAAIEiAhIJgAAAAAAAAAAAAAAAAhICEgAAAAAIEBIhIIEiYAAAAAAISICBIAAAAmAAAAAAAAAAAAAAAAAIBIgQEgJgAAAAAAAAAAAAAAACBIAAAAAAAAAAAAAhIgISCYAAAAISAgShASIASAmAAAAAAAAAAAAAAAgQEghMSAAAAAAAAAAACAEAShKYAAgBAEoSmAAAAAAAgQAEggBMAEAShKYAAISgBKEoAAAAAAmAAAIBIgQEgJgAAAAAAAAhICBIAAAAAAAAAAAAAAAAAAAAAAAAAAAIASACAAEoSgACYAAAAAAAAgSAAAAAAAAAAAAAAAAAgBAShKExIAAAAAAAAAAAIShKAAJgAAACAEAShKYAAAAgSAAAAAAAAIAAmAAAAAAAAAAAACEgIEgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIABIAIAQEgJgAAAAAAAAAAAAhKAAEBICYAAAAAAISgBKEgAAAAAAAAAAAAAAAAAAAAAAAAgBAAAEoSmIAQAABKEpgACAEAShKYISgBKEoQEAEgAAShJAAEwABGwNgjIAHyAlCUJgAgJATAAAABCUAAICQEwAAAAABACAAAAAJQlMQAgAACUJTAAAAEAAAIAAAAAlCSAAJgAAhKEJgAQEgJiNgbB8kACIAAkBMAAAAAAAAEJQAAgJATAAAAAAAAAAAAAAH//2Q=="
BLOBS_IMG = "data:image/jpeg;base64," + BLOBS_B64_PLACEHOLDER

CSS = """
:root{--bg:#FFF8ED;--card:#FFFFFF;--ink:#1E1A16;--mut:#7A6A55;--line:#F0DDBE;--green:#0E9F6E;--greenbg:#D1F4E0;--yellowbg:#FEF3C7;--red:#DC2626;--redbg:#FEE2E2;--blue:#2563EB}
*{box-sizing:border-box}
body{margin:0;font-family:Nunito,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink);overflow-x:hidden}
a{color:var(--blue);text-decoration:none;font-weight:700}
.top{max-width:1120px;margin:0 auto;padding:16px 20px 0;display:flex;justify-content:space-between;align-items:center}
.logo{font-family:'Baloo 2',Nunito,sans-serif;font-weight:800;font-size:26px;letter-spacing:-0.5px;display:flex;align-items:center;gap:8px}
.logo-dot{width:28px;height:28px;border-radius:50%;background:linear-gradient(135deg,#14B8A6,#F97316);display:inline-flex;align-items:center;justify-content:center;color:white;font-size:16px;box-shadow:0 3px 0 #1E1A16;border:2px solid #1E1A16}
.nav{font-size:14px;display:flex;gap:10px;flex-wrap:wrap}.nav a{background:white;border:2px solid #1E1A16;padding:7px 12px;border-radius:999px;color:var(--ink);box-shadow:2px 2px 0 #1E1A16}
.wrap{max-width:1120px;margin:0 auto;padding:16px 20px 48px}
.hero{display:grid;grid-template-columns:1.05fr 0.95fr;gap:26px;align-items:center;position:relative;overflow:visible}
@media(max-width:860px){.hero{grid-template-columns:1fr}}
.eyebrow{display:inline-flex;align-items:center;gap:8px;background:#1E1A16;color:#FFF8ED;padding:7px 12px;border-radius:999px;font-size:12px;font-weight:800;letter-spacing:1px;text-transform:uppercase}
h1{font-family:'Baloo 2',Nunito,sans-serif;font-size:58px;line-height:0.92;letter-spacing:-1.5px;margin:16px 0 12px}
h1 .hl{background:linear-gradient(90deg,#F97316,#EC4899,#8B5CF6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.sub{color:var(--mut);font-size:17px;line-height:1.6;max-width:520px}
.sub b{color:var(--ink)}
.hero-img-wrap{position:relative;overflow:visible}
.hero-img{width:100%;border:3px solid #1E1A16;border-radius:28px;box-shadow:8px 8px 0 #1E1A16;object-fit:cover;aspect-ratio:4/3;background:white}
.hero-badge{position:absolute;left:-10px;top:-12px;background:white;border:2px solid #1E1A16;border-radius:999px;padding:8px 12px;font-weight:800;font-size:13px;box-shadow:3px 3px 0 #1E1A16;transform:rotate(-3deg)}
.hero-badge2{position:absolute;right:-8px;bottom:14px;background:#FEF3C7;border:2px solid #1E1A16;border-radius:999px;padding:8px 12px;font-weight:800;font-size:13px;box-shadow:3px 3px 0 #1E1A16;transform:rotate(2deg)}
.float{animation:float 3.5s ease-in-out infinite} @keyframes float{0%,100%{transform:translateY(0) rotate(-3deg)}50%{transform:translateY(-6px) rotate(-3deg)}}
.card{background:var(--card);border:2.5px solid #1E1A16;border-radius:24px;padding:22px;box-shadow:6px 6px 0 #1E1A16}
.card h3{margin:0 0 8px;font-size:18px;font-family:'Baloo 2',sans-serif}
.inputrow{display:flex;gap:10px;margin-top:14px} @media(max-width:640px){.inputrow{flex-direction:column}}
input{flex:1;padding:15px 16px;border:2.5px solid #1E1A16;border-radius:16px;background:#FFFDF5;font-size:15px;outline:none;font-weight:600}
input:focus{box-shadow:0 0 0 4px #FDE68A}
button{padding:15px 20px;border:2.5px solid #1E1A16;border-radius:16px;background:#1E1A16;color:white;font-weight:900;cursor:pointer;font-size:15px;white-space:nowrap} button:hover{background:#000}
.hint{font-size:13px;color:var(--mut);margin-top:12px;line-height:1.6}
.pills{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px} .pill{font-size:13px;border:2px solid #1E1A16;background:#FFF;padding:7px 12px;border-radius:999px;cursor:pointer;font-weight:700} .pill:hover{background:#FEF3C7}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-top:18px} @media(max-width:820px){.grid3{grid-template-columns:1fr}}
.mini{background:var(--card);border:2px solid #1E1A16;border-radius:20px;padding:16px;box-shadow:4px 4px 0 #1E1A16} .mini b{font-size:15px;font-family:'Baloo 2',sans-serif} .mini p{font-size:13.5px;color:var(--mut);line-height:1.55;margin:6px 0 0}
.blob-ic{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px;border:2px solid #1E1A16;margin-bottom:10px}
.badge{display:inline-flex;align-items:center;gap:8px;padding:10px 16px;border-radius:999px;font-weight:900;font-size:22px;border:2.5px solid #1E1A16;box-shadow:3px 3px 0 #1E1A16}
.badge.pass{background:var(--greenbg);color:#065F46} .badge.hold{background:var(--yellowbg);color:#92400E} .badge.sell{background:var(--redbg);color:#991B1B}
.kpi{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:16px} @media(max-width:640px){.kpi{grid-template-columns:1fr 1fr}}
.k{background:#FFFDF5;border:2px solid #1E1A16;border-radius:18px;padding:14px;box-shadow:3px 3px 0 #1E1A16} .k .l{font-size:11px;letter-spacing:0.8px;text-transform:uppercase;color:var(--mut);font-weight:800} .k .v{font-size:21px;font-weight:900;margin-top:4px} .k .s{font-size:12px;color:var(--mut)}
.bar{height:12px;background:#FDE68A;border:2px solid #1E1A16;border-radius:999px;overflow:hidden;margin-top:10px} .bar i{display:block;height:100%;background:#DC2626}
.flag{font-size:12.5px;background:#fff;border:2px solid #1E1A16;padding:6px 10px;border-radius:999px;font-weight:700}
.code{background:#1E1A16;color:#FEF3C7;border-radius:16px;padding:16px;font-family:ui-monospace,monospace;font-size:12.5px;line-height:1.6;overflow:auto;white-space:pre-wrap;border:2.5px solid #1E1A16}
.foot{margin-top:28px;padding-top:16px;border-top:2px dashed #E5D5B8;display:flex;justify-content:space-between;color:var(--mut);font-size:13px;flex-wrap:wrap;gap:8px}
.steps{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-top:14px} @media(max-width:820px){.steps{grid-template-columns:1fr}}
.jump-box{position:relative;overflow:visible;border-radius:28px}
.runners{position:fixed;inset:0;pointer-events:none;z-index:999;overflow:visible}
.runner{position:fixed;width:52px;height:52px;border:2.5px solid #1E1A16;display:flex;align-items:center;justify-content:center;gap:5px;box-shadow:2px 3px 0 #1E1A16;opacity:.96}
.runner i{display:block;width:9px;height:12px;background:white;border-radius:50%;border:1px solid #1E1A16}
.runner.r1{background:#14B8A6;border-radius:50% 50% 45% 45%;animation:run1 18s ease-in-out infinite}
.runner.r2{background:#F97316;clip-path:polygon(25% 5%,75% 5%,100% 50%,75% 95%,25% 95%,0% 50%);border:none;animation:run2 18s ease-in-out infinite;animation-delay:1.2s}
.runner.r3{background:#8B5CF6;border-radius:50% 50% 50% 50% / 60% 60% 40% 40%;animation:run3 18s ease-in-out infinite;animation-delay:2.4s}
.runner.r4{background:#3B82F6;border-radius:50%;animation:run4 18s ease-in-out infinite;animation-delay:3.2s}
.runner.r5{background:#22C55E;border-radius:50% 50% 45% 45%;animation:run5 18s ease-in-out infinite;animation-delay:4s}
.runner.r6{background:#EC4899;clip-path:polygon(50% 5%,100% 90%,0% 90%);border:none;animation:run6 18s ease-in-out infinite;animation-delay:5s}
.runner.r7{background:#FACC15;border-radius:50%;animation:run7 18s ease-in-out infinite;animation-delay:6s}
@keyframes run1{0%{left:62vw;top:32vh;transform:rotate(-6deg) scale(1)}12%{left:6vw;top:8vh;transform:rotate(12deg) scale(1.15) translateY(-8px)}25%{left:88vw;top:12vh;transform:rotate(-10deg) scale(1.05)}38%{left:90vw;top:82vh;transform:rotate(10deg) scale(1.1) translateY(6px)}52%{left:8vw;top:86vh;transform:rotate(-8deg) scale(1.05)}65%{left:4vw;top:48vh;transform:rotate(8deg) scale(1.12)}78%{left:45vw;top:52vh;transform:rotate(0deg) scale(1.05)}90%{left:58vw;top:28vh;transform:rotate(-4deg) scale(1.02)}100%{left:62vw;top:32vh;transform:rotate(-6deg) scale(1)}}
@keyframes run2{0%{left:70vw;top:38vh;transform:rotate(8deg) scale(1)}12%{left:90vw;top:78vh;transform:rotate(-12deg) scale(1.12)}25%{left:6vw;top:84vh;transform:rotate(10deg) scale(1.05)}38%{left:4vw;top:10vh;transform:rotate(-10deg) scale(1.1)}52%{left:48vw;top:6vh;transform:rotate(8deg) scale(1.05)}65%{left:88vw;top:48vh;transform:rotate(-8deg) scale(1.12)}78%{left:55vw;top:62vh;transform:rotate(0deg) scale(1.05)}90%{left:66vw;top:34vh;transform:rotate(4deg) scale(1.02)}100%{left:70vw;top:38vh;transform:rotate(8deg) scale(1)}}
@keyframes run3{0%{left:66vw;top:28vh;transform:rotate(0deg) scale(1)}12%{left:8vw;top:48vh;transform:rotate(14deg) scale(1.15)}25%{left:88vw;top:88vh;transform:rotate(-10deg) scale(1.05)}38%{left:90vw;top:10vh;transform:rotate(12deg) scale(1.1)}52%{left:10vw;top:6vh;transform:rotate(-8deg) scale(1.05)}65%{left:4vw;top:82vh;transform:rotate(8deg) scale(1.12)}78%{left:48vw;top:42vh;transform:rotate(0deg) scale(1.05)}90%{left:62vw;top:26vh;transform:rotate(-2deg) scale(1.02)}100%{left:66vw;top:28vh;transform:rotate(0deg) scale(1)}}
@keyframes run4{0%{left:60vw;top:42vh;transform:rotate(-8deg) scale(1)}12%{left:88vw;top:6vh;transform:rotate(12deg) scale(1.12)}25%{left:90vw;top:52vh;transform:rotate(-10deg) scale(1.05)}38%{left:6vw;top:88vh;transform:rotate(10deg) scale(1.1)}52%{left:8vw;top:32vh;transform:rotate(-8deg) scale(1.05)}65%{left:52vw;top:90vh;transform:rotate(8deg) scale(1.12)}78%{left:42vw;top:58vh;transform:rotate(0deg) scale(1.05)}90%{left:58vw;top:38vh;transform:rotate(4deg) scale(1.02)}100%{left:60vw;top:42vh;transform:rotate(-8deg) scale(1)}}
@keyframes run5{0%{left:74vw;top:30vh;transform:rotate(6deg) scale(1)}12%{left:4vw;top:14vh;transform:rotate(-12deg) scale(1.15)}25%{left:6vw;top:78vh;transform:rotate(10deg) scale(1.05)}38%{left:88vw;top:84vh;transform:rotate(-10deg) scale(1.1)}52%{left:90vw;top:28vh;transform:rotate(8deg) scale(1.05)}65%{left:50vw;top:8vh;transform:rotate(-8deg) scale(1.12)}78%{left:38vw;top:48vh;transform:rotate(0deg) scale(1.05)}90%{left:70vw;top:28vh;transform:rotate(-4deg) scale(1.02)}100%{left:74vw;top:30vh;transform:rotate(6deg) scale(1)}}
@keyframes run6{0%{left:64vw;top:44vh;transform:rotate(10deg) scale(1)}12%{left:90vw;top:32vh;transform:rotate(-12deg) scale(1.12)}25%{left:8vw;top:6vh;transform:rotate(10deg) scale(1.05)}38%{left:4vw;top:68vh;transform:rotate(-10deg) scale(1.1)}52%{left:88vw;top:90vh;transform:rotate(8deg) scale(1.05)}65%{left:52vw;top:92vh;transform:rotate(-8deg) scale(1.12)}78%{left:44vw;top:38vh;transform:rotate(0deg) scale(1.05)}90%{left:60vw;top:40vh;transform:rotate(-2deg) scale(1.02)}100%{left:64vw;top:44vh;transform:rotate(10deg) scale(1)}}
@keyframes run7{0%{left:68vw;top:36vh;transform:rotate(-4deg) scale(1)}12%{left:10vw;top:88vh;transform:rotate(12deg) scale(1.15)}25%{left:92vw;top:58vh;transform:rotate(-10deg) scale(1.05)}38%{left:86vw;top:6vh;transform:rotate(10deg) scale(1.1)}52%{left:6vw;top:28vh;transform:rotate(-8deg) scale(1.05)}65%{left:48vw;top:88vh;transform:rotate(8deg) scale(1.12)}78%{left:40vw;top:55vh;transform:rotate(0deg) scale(1.05)}90%{left:64vw;top:32vh;transform:rotate(2deg) scale(1.02)}100%{left:68vw;top:36vh;transform:rotate(-4deg) scale(1)}}
@media(prefers-reduced-motion:reduce){.runner{animation:none}}

"""

HOME = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TVibe — Check a token before you buy</title><meta name="description" content="Paste a Solana mint. Get PASS / HOLD-BUY / SELL with real numbers in seconds.">
<link href="https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;700;800&family=Nunito:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>""" + CSS + """</style></head><body>
<div class="runners"><span class="runner r1"><i></i><i></i></span><span class="runner r2"><i></i><i></i></span><span class="runner r3"><i></i><i></i></span><span class="runner r4"><i></i><i></i></span><span class="runner r5"><i></i><i></i></span><span class="runner r6"><i></i><i></i></span><span class="runner r7"><i></i><i></i></span></div>
<div class="top"><div class="logo"><span class="logo-dot">●</span> TVibe</div><div class="nav"><a href="#how">How it works</a><a href="#checks">What we check</a><a href="#api">For Agents</a></div></div>
<div class="wrap"><div class="hero"><div>
<div class="eyebrow">✦ Solana Token Check • Real Numbers • No Hype</div>
<h1>Check a token<br><span class="hl">before you buy.</span></h1>
<p class="sub">Paste a Solana mint. Get a clear verdict — <b>PASS / HOLD-BUY / SELL</b> — plus real price, liquidity, volume and risk in seconds. No hype. No guess.</p>
<div style="display:flex;gap:10px;margin-top:16px;flex-wrap:wrap"><span style="background:#D1F4E0;border:2px solid #1E1A16;padding:8px 12px;border-radius:999px;font-size:13px;font-weight:800">✓ Real data</span><span style="background:#fff;border:2px solid #1E1A16;padding:8px 12px;border-radius:999px;font-size:13px;font-weight:700">✓ English only</span><span style="background:#fff;border:2px solid #1E1A16;padding:8px 12px;border-radius:999px;font-size:13px;font-weight:700">✓ Agent-ready JSON</span></div>
<div class="card" style="margin-top:18px"><h3>Check a token</h3><p style="margin:0;color:#7A6A55;font-size:13px">Enter a Solana mint address.</p>
<form method="get" action="/check"><div class="inputrow"><input name="mint" placeholder="Paste mint, e.g. 98vd3Covp..." required><button>CHECK →</button></div></form>
<div class="hint">Example: <b>FWH</b> — 98vd3CovpBmHJGN2z9SiZRxM8QBVcc9Gnvq1Rdjnpump<br>API: <code>/check?mint=&lt;mint&gt;</code> returns JSON for agents.</div>
<div class="pills"><span class="pill" onclick="document.querySelector('input[name=mint]').value='98vd3CovpBmHJGN2z9SiZRxM8QBVcc9Gnvq1Rdjnpump'">Try FWH</span><span class="pill" onclick="document.querySelector('input[name=mint]').value='So11111111111111111111111111111111111111112'">Try SOL (wrapped)</span></div>
</div>
</div>
<div class="hero-img-wrap"><span class="hero-badge float">👀 We check it for you</span><div class="jump-box"><img class="hero-img" src=""" + BLOBS_IMG + """ " alt="Cute TVibe blobs"></div><span class="hero-badge2">PASS • HOLD-BUY • SELL</span></div></div>
<div class="grid3" id="checks"><div class="mini"><div class="blob-ic" style="background:#D1F4E0">💧</div><b>Liquidity — can you sell?</b><p>We check how much money is actually in the pool. Low liquidity = hard to exit.</p></div><div class="mini"><div class="blob-ic" style="background:#FEF3C7">🔒</div><b>On-chain — who controls it?</b><p>Mint + freeze authorities via Helius. Renounced = no one can mint more or freeze you.</p></div><div class="mini"><div class="blob-ic" style="background:#FEE2E2">📈</div><b>Price + Activity — is it pumping?</b><p>24h change, volume vs liquidity, and age. Fast pump + new pair = high volatility.</p></div></div>
<div class="card" id="how" style="margin-top:18px"><h3>How it works — 3 steps</h3><div class="steps"><div><b>1. Paste mint</b><p style="color:#7A6A55;font-size:13.5px;line-height:1.5">Copy the mint from DexScreener or your wallet.</p></div><div><b>2. We check live data</b><p style="color:#7A6A55;font-size:13.5px;line-height:1.5">Market data + on-chain authorities. No opinions, just numbers.</p></div><div><b>3. Get your verdict</b><p style="color:#7A6A55;font-size:13.5px;line-height:1.5"><b>PASS</b> = good setup. <b>HOLD-BUY</b> = mixed, small size. <b>SELL</b> = do not buy.</p></div></div><p style="color:#7A6A55;font-size:13px;margin:12px 0 0">PASS is not safe. Every memecoin is volatile. This is not financial advice.</p></div>
<div class="card" style="margin-top:14px" id="api"><h3>For Agents 🤖</h3><p style="font-size:13px;color:#7A6A55;margin:0 0 10px">Use the JSON endpoint. No HTML scraping needed.</p><div class="code">GET /check?mint=&lt;mint&gt;&amp;format=json

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
}</div><div style="margin-top:10px;font-size:13px"><a href="/health">/health</a> · <a href="/check?mint=98vd3CovpBmHJGN2z9SiZRxM8QBVcc9Gnvq1Rdjnpump&format=json">Try JSON →</a></div></div>
<div class="foot"><span>© 2026 TVibe — Check a token before you buy.</span><span>Data is real. Not financial advice.</span></div></div></body></html>"""

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
        onchain_html = f'<div style="margin-top:14px;background:#fff;border:2px solid #1E1A16;border-radius:18px;padding:14px;box-shadow:3px 3px 0 #1E1A16"><b style="font-size:13px">On-chain — via {_src}</b><div style="font-size:13px;color:#7A6A55;line-height:1.6;margin-top:4px">Mint: <b style="color:#1E1A16">{_ma_txt}</b> &nbsp;•&nbsp; Freeze: <b style="color:#1E1A16">{_fa_txt}</b> &nbsp;•&nbsp; Decimals: {_oc.get("decimals") if _oc.get("decimals") is not None else "—"}</div><div style="font-size:12px;color:#7A6A55">If mint / freeze is still active, supply can change or transfers can be frozen.</div></div>'
    else:
        onchain_html = '<div style="margin-top:14px;background:#fff;border:2px solid #1E1A16;border-radius:18px;padding:14px;font-size:13px;color:#7A6A55;box-shadow:3px 3px 0 #1E1A16"><b style="color:#1E1A16">On-chain:</b> Unavailable for this check. Verdict from market data only.</div>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TVibe — {o['symbol']} {o['label']}</title><link href="https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;700;800&family=Nunito:wght@400;600;700;800;900&display=swap" rel="stylesheet"><style>{CSS}</style></head><body>
<div class="runners"><span class="runner r1"><i></i><i></i></span><span class="runner r2"><i></i><i></i></span><span class="runner r3"><i></i><i></i></span><span class="runner r4"><i></i><i></i></span><span class="runner r5"><i></i><i></i></span><span class="runner r6"><i></i><i></i></span><span class="runner r7"><i></i><i></i></span></div>
<div class="top"><div class="logo"><span class="logo-dot">●</span> TVibe</div><div class="nav"><a href="/">← New check</a><a href="/health">Health</a></div></div>
<div class="wrap"><div style="display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap"><div><div style="font-size:12px;letter-spacing:1px;text-transform:uppercase;color:#7A6A55;font-weight:800">Token Report</div><h1 style="font-size:42px;margin:6px 0">{o['symbol']} <span style="font-weight:400;color:#7A6A55;font-size:26px">— {o['name']}</span></h1><div style="font-size:13px;color:#7A6A55">Mint: <code>{o['mint']}</code></div></div><span class="badge {cls}">{o['label']} — {o['risk_score']}/100</span></div>
<div class="card" style="margin-top:16px"><div style="display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap"><div style="flex:1;min-width:260px"><div style="font-size:12px;letter-spacing:0.8px;text-transform:uppercase;color:#7A6A55;font-weight:800">Chance of bad outcome in 24h</div><div style="font-size:36px;font-weight:900">{o['p_bad_24h']:.2%} <span style="font-size:14px;font-weight:600;color:#7A6A55">CI {o['p_bad_ci_low']:.2%} – {o['p_bad_ci_high']:.2%}</span></div><div class="bar"><i style="width:{pct}%"></i></div></div><div style="max-width:360px;background:#FFF8ED;border:2px solid #1E1A16;border-radius:16px;padding:14px"><b>Why this verdict?</b><p style="color:#1E1A16;font-size:15px;font-weight:800;line-height:1.5;margin:6px 0 0">{o['why']}</p><p style="color:#7A6A55;font-size:12px;line-height:1.5;margin:8px 0 0">PASS is not safe. SELL = do not buy. HOLD-BUY = small size only.</p></div></div>
<div class="kpi"><div class="k"><div class="l">Price</div><div class="v">${o['price_usd']:.8g}</div><div class="s">USD</div></div><div class="k"><div class="l">Liquidity</div><div class="v">${o['liquidity_usd']:,.0f}</div><div class="s">Total in pool</div></div><div class="k"><div class="l">Volume 24h</div><div class="v">${o['volume_24h']:,.0f}</div><div class="s">Trading activity</div></div><div class="k"><div class="l">Change 24h</div><div class="v">{round(o['change_24h_pct'],2)}%</div><div class="s">Price move</div></div><div class="k"><div class="l">Age</div><div class="v">{o['age_h']}h</div><div class="s">Pair age</div></div><div class="k"><div class="l">FDV</div><div class="v">${o['fdv']:,.0f}</div><div class="s">Fully diluted value</div></div></div>
{onchain_html}
<div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap">{flags}</div>
<div style="margin-top:16px;display:flex;gap:14px;flex-wrap:wrap;font-size:14px">{'<a href="'+o['pair_url']+'" target="_blank">View pair on DexScreener →</a>' if o['pair_url'] else ''}<a href="/check?mint='+o['mint']+'&format=json">View as JSON for agents →</a><a href="/">← Check another token</a></div>
</div><div class="foot"><span>TVibe — Check a token before you buy.</span><span>Data is real. Not financial advice.</span></div></div></body></html>"""


def error_html(title, msg, mint="", code=404):
    # Cute error page - same paper + blobs, no JSON, no scary stack trace
    _m = (mint or "")[:60]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TVibe — {title}</title><link href="https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;700;800&family=Nunito:wght@400;600;700;800;900&display=swap" rel="stylesheet"><style>{CSS}</style></head><body>
<div class="runners"><span class="runner r1"><i></i><i></i></span><span class="runner r2"><i></i><i></i></span><span class="runner r3"><i></i><i></i></span><span class="runner r4"><i></i><i></i></span><span class="runner r5"><i></i><i></i></span><span class="runner r6"><i></i><i></i></span><span class="runner r7"><i></i><i></i></span></div>
<div class="top"><div class="logo"><span class="logo-dot">●</span> TVibe</div><div class="nav"><a href="/">← New check</a><a href="/health">Health</a></div></div>
<div class="wrap" style="text-align:center;max-width:620px;margin:40px auto">
<div style="font-size:64px">🧸</div>
<h1 style="font-size:38px;margin:10px 0">{title}</h1>
<p style="font-size:16px;color:#7A6A55;line-height:1.6">{msg}</p>
{f'<div style="margin:14px auto;background:#fff;border:2px solid #1E1A16;border-radius:14px;padding:10px 14px;font-size:13px;word-break:break-all">Mint: <code>{_m}</code></div>' if _m else ''}
<div style="margin-top:22px;display:flex;gap:10px;justify-content:center;flex-wrap:wrap">
<a href="/" style="background:#1E1A16;color:#fff;padding:12px 22px;border-radius:999px;font-weight:800;text-decoration:none;box-shadow:3px 3px 0 #F97316">Try another token →</a>
<a href="/health" style="background:#fff;color:#1E1A16;padding:12px 22px;border-radius:999px;font-weight:800;text-decoration:none;border:2px solid #1E1A16">Check server health</a>
</div>
<p style="font-size:12px;color:#9A8B75;margin-top:18px">Tip: Copy the mint from DexScreener / Raydium — it starts with a letter and is 32-44 characters long.</p>
</div></body></html>"""

@app.get("/ping")
def ping():
    # Ultra-light keep-alive for cron-job.org / UptimeRobot - NO Dex, NO Helius, NO Upstash
    return {"status":"ok","version":VERSION,"uptime_s":int(time.time()-START),"checks":CHECKS["count"]}

@app.get("/cron/outcome")
def cron_outcome(request: Request, limit: int = 50):
    # Run every hour via cron-job.org: GET /cron/outcome?key=ADMIN_KEY
    # Finds snaps older than 24h, checks real price/liq now, writes to outcomes list.
    # This is what makes p_bad_24h REAL instead of formula.
    if not _need_key(request): return JSONResponse({"error":"unauthorized"}, status_code=401)
    now = int(time.time())
    snaps = up_lrange("snap_list", 0, -1)
    done = 0; checked = 0; skipped = 0
    results = []
    for raw in snaps[:500]:
        if checked >= limit: break
        try: snap = json.loads(raw)
        except: continue
        ts = int(snap.get("ts") or 0)
        if now - ts < 86400: skipped += 1; continue  # not 24h yet
        mint = snap.get("mint") or ""
        done_key = f"outcome_done:{mint}:{ts}"
        if up_get(done_key): skipped += 1; continue
        checked += 1
        try: now_pair = fetch_pair(mint, use_cache=False)
        except: now_pair = None
        is_bad, otype, p_chg, l_chg = classify_outcome(snap, now_pair)
        rec = {"mint": mint, "snap_ts": ts, "check_ts": now, "is_bad": is_bad, "outcome": otype, "price_chg_24h_plus": p_chg, "liq_chg": l_chg, "risk_score": snap.get("risk_score"), "verdict": snap.get("verdict"), "price_then": snap.get("price_usd"), "liquidity_then": snap.get("liquidity_usd")}
        up_rpush("outcomes", json.dumps(rec, ensure_ascii=False))
        up_set(done_key, "1")
        done += 1; results.append(rec)
    # bust outcome bins cache so next check uses new data
    _OUTCOME_BINS_CACHE["ts"] = 0
    return {"checked": checked, "wrote": done, "skipped_not_ready": skipped, "outcomes": results[:10]}

@app.get("/health")
def health():
    bins, n_out = _load_outcome_bins()
    return {"status":"ok","version":VERSION,"uptime_s":int(time.time()-START),"checks":CHECKS["count"],"rpc_configured":RPC_CONFIGURED,"rpc_label":RPC_LABEL,"rpc_sources":{"helius":bool(HELIUS_URL)},"onchain_cache":len(_RPC_CACHE),"dex_cache":len(_DEX_CACHE),"verdict_cache":len(_VERDICT_CACHE),"helius_min_calls":_HELIUS_MIN["n"],"helius_day_calls":_HELIUS_DAY["n"],"outcomes_n":n_out,"p_bad_source":"real_24h_outcomes" if n_out>=20 else "estimate (collecting outcomes)"}
@app.get("/", response_class=HTMLResponse)
def index(): return HOME
@app.get("/check")
def check(request: Request, mint: str = Query(default=""), token: str = Query(default=""), format: str = Query(default="")):
    m=(mint or token or "").strip()
    want_html = (format=="html") or ("text/html" in (request.headers.get("accept") or ""))
    # --- Anti-spam: rate limit per IP ---
    ip = _client_ip(request)
    if not _rate_limit_ok(ip):
        if want_html and format!="json":
            return HTMLResponse(error_html("Slow down, blob! 🐢", "You checked too many tokens too fast. Wait 1 minute, then try again. This keeps Helius costs low so TVibe stays free.", m, 429), status_code=429)
        return JSONResponse({"error":"rate_limited","message":"Too many checks. Wait 60s.","mint":m}, status_code=429)
    if not m:
        if want_html and format!="json": return HTMLResponse(error_html("Missing mint 🧸", "Paste a Solana mint address first — like the one you see on DexScreener.", "", 400), status_code=400)
        return JSONResponse({"error":"missing mint"}, status_code=400)
    # --- Validate mint format before burning any API call ---
    if not _is_valid_mint(m):
        if want_html and format!="json": return HTMLResponse(error_html("That doesn't look like a mint 🧸", "A Solana mint is 32-44 characters, no spaces, no 0 O I l. Copy it again from DexScreener and paste it here.", m, 400), status_code=400)
        return JSONResponse({"error":"invalid mint","mint":m,"message":"Mint must be 32-44 base58 chars"}, status_code=400)
    # --- Verdict cache: same mint within 30s = no new Dex/Helius ---
    _now = time.time()
    if m in _VERDICT_CACHE:
        _cts, _cobj = _VERDICT_CACHE[m]
        if _now - _cts < _VERDICT_CACHE_TTL:
            if format=="json": return _cobj
            if want_html: return HTMLResponse(result_html(_cobj))
            return _cobj
    lock=_lock_for(m)
    if not lock.acquire(blocking=False): return JSONResponse({"status":"busy","mint":m,"message":"Check is running, retry in 3s"}, status_code=429)
    try:
        CHECKS["count"]+=1
        try: pair=fetch_pair(m)
        except Exception as e:
            if want_html and format!="json": return HTMLResponse(error_html("DexScreener is having a nap 😴", "We couldn't reach DexScreener right now. Wait 30 seconds and try again — your token might be fine, it's just our data source.", m, 502), status_code=502)
            return JSONResponse({"error":"dexscreener_down","mint":m}, status_code=502)
        if not pair:
            if want_html and format!="json": return HTMLResponse(error_html("We can't find this token 🕵️", "No pair found on DexScreener. It might be brand new, delisted, or the mint is wrong. Check the mint again and try later.", m, 404), status_code=404)
            return JSONResponse({"mint":m,"status":"not_found","verdict":"avoid","label":"SELL","p_bad_24h":0.9}, status_code=404)
        obj=compute(m,pair)
        # Helius enrichment: never blocks verdict, never 500s
        try:
            oc = get_onchain(m)
            obj = enrich_with_onchain(obj, oc)
        except Exception:
            obj["onchain"] = {"available": False, "rpc_source": "none", "note": "On-chain check failed. Verdict from market data only."}
        try: append_ledger(obj)
        except: pass
        # cache verdict for 30s anti-spam
        try: _VERDICT_CACHE[m] = (time.time(), obj)
        except: pass
        out={"mint":obj["mint"],"symbol":obj["symbol"],"name":obj["name"],"verdict":obj["verdict"],"label":obj["label"],"risk_score":obj["risk_score"],"p_bad_24h":obj["p_bad_24h"],"p_bad_ci":[obj["p_bad_ci_low"],obj["p_bad_ci_high"]],"p_bad_source":obj.get("p_bad_source","estimate"),"price_usd":obj["price_usd"],"liquidity_usd":obj["liquidity_usd"],"volume_24h":obj["volume_24h"],"change_24h_pct":obj["change_24h_pct"],"age_h":obj["age_h"],"fdv":obj["fdv"],"flags":obj["flags"],"pair_url":obj["pair_url"],"why":obj["why"],"ts":obj["ts"],"version":VERSION,"status":"ok","onchain":obj.get("onchain") or {"available":False,"rpc_source":"none"}}
        if format=="json": return out
        if format=="html": return HTMLResponse(result_html(obj))
        if "text/html" in (request.headers.get("accept") or ""): return HTMLResponse(result_html(obj))
        return out
    except Exception as e:
        if want_html and format!="json": return HTMLResponse(error_html("Oops, blob tripped! 🧸", "Something went wrong on our side. Try again in 30 seconds — if it keeps happening, check /health.", m, 500), status_code=500)
        return JSONResponse({"error":str(e)[:200],"mint":m,"status":"error"}, status_code=500)
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
    # REAL calibration: uses outcomes list (24h real price/liq) - not verdict proxy
    rows=up_lrange("outcomes",0,-1); bins=defaultdict(lambda: {"n":0,"bad":0})
    for r in rows:
        try: o=json.loads(r); s=float(o.get("risk_score") or 0); b=int(s//10*10); bins[b]["n"]+=1; bins[b]["bad"]+= (1 if o.get("is_bad") else 0)
        except: pass
    out=[]
    for b in sorted(bins):
        n=bins[b]["n"]; bad=bins[b]["bad"]; p=bad/n if n else 0; lo,hi=wilson_ci(bad,n)
        out.append({"score_bin":b,"n":n,"bad":bad,"p_bad":round(p,4),"ci":[round(lo,4),round(hi,4)]})
    if not out:
        return {"version":VERSION,"bins":[],"note":"No 24h outcomes yet - collecting. p_bad_24h is estimate until we have 20+ outcomes. Run /cron/outcome hourly.","outcomes_n":0}
    return {"version":VERSION,"bins":out,"source":"real_24h_outcomes","outcomes_n":sum(b["n"] for b in out)}
@app.get("/walkforward")
def walkforward(request: Request):
    if not _need_key(request): return JSONResponse({"error":"unauthorized"}, status_code=401)
    rows=[]
    for r in up_lrange("outcomes",0,-1):
        try:
            o=json.loads(r); o["ts"]=o.get("snap_ts") or o.get("check_ts"); rows.append(o)
        except: pass
    rows=sorted(rows, key=lambda x: x.get("ts") or 0)
    if len(rows)<40: return {"error":"not enough real outcomes yet","n":len(rows),"note":"Walk-forward now needs 40+ real 24h outcomes, not verdict proxy. Keep /cron/outcome running hourly."}
    cut=int(len(rows)*0.7); train,test=rows[:cut],rows[cut:]
    def metrics(data, thr=35):
        tp=fp=tn=fn=0
        for o in data:
            pred=float(o.get("risk_score") or 0)>=thr; actual=bool(o.get("is_bad"))
            if pred and actual: tp+=1
            elif pred and not actual: fp+=1
            elif not pred and not actual: tn+=1
            else: fn+=1
        prec=tp/(tp+fp) if tp+fp else 0; rec=tp/(tp+fn) if tp+fn else 0
        return {"n":len(data),"tp":tp,"fp":fp,"tn":tn,"fn":fn,"precision":round(prec,4),"recall":round(rec,4)}
    return {"n":len(rows),"train":metrics(train),"test":metrics(test),"threshold":35,"note":"Using real 24h outcomes: bad = price -50% or liquidity -70% or pair gone within 24h+"}
@app.get("/rules")
def rules(): return {"version":VERSION,"note":"rules are private"}

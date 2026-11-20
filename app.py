"""TVibe Signal v38 - "Check before you sell". Upload as app.py (overwrite).
Needs only: fastapi + uvicorn (no extra packages). Data: DexScreener -> GeckoTerminal fallback.
Public endpoints: /  /check?mint=  /health  /llms.txt  /docs
"""
import json, os, re, time, threading, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

VERSION = "v38"
RULES_VERSION = "2026-11-20"
SOL_MINT = "So11111111111111111111111111111111111111112"
UA = {"User-Agent": "TVibeSignal/38 (+https://x.com/realTVibe)", "Accept": "application/json"}
STARTED = time.time()
JUP_KEY = os.environ.get("JUPITER_API_KEY", "").strip()          # optional. Free key: portal.jup.ag
JUP_BASE = "https://api.jup.ag" if JUP_KEY else "https://lite-api.jup.ag"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
CACHE_TTL = 25          # seconds a result is served from cache
STALE_MAX = 900         # seconds an old result may be shown if all sources fail
RATE_PER_MIN = 40       # requests / minute / IP on /check
DISCLAIMER = "Heuristic signal from public market data. Not financial advice. Low liquidity = hard to exit."

# ---- thresholds (private, used for verdict only) ----
T = {"liq_sell": 5000, "liq_hold": 20000, "vol_min": 1000, "vol_liq_hold": 0.5,
     "age_min_h": 1, "dump_24h_pct": -50, "warn_24h_pct": -20,
     "exit_sell_loss_pct": 30, "exit_watch_loss_pct": 10, "exit_sizes_usd": [100, 1000]}
THRESHOLDS = [
    {"key": "liq_sell", "label": "Liquidity below this = SELL", "value": "$%s" % format(T["liq_sell"], ",")},
    {"key": "liq_hold", "label": "Liquidity needed for HOLD / BUY", "value": "$%s" % format(T["liq_hold"], ",")},
    {"key": "vol_min", "label": "Volume 24h below this = WATCH", "value": "$%s" % format(T["vol_min"], ",")},
    {"key": "vol_liq_hold", "label": "Volume 24h / liquidity needed for HOLD / BUY", "value": "%sx" % T["vol_liq_hold"]},
    {"key": "age_min_h", "label": "Younger than this = WATCH", "value": "%s hour" % T["age_min_h"]},
    {"key": "dump_24h_pct", "label": "Price change 24h at or below this = WATCH", "value": "%s%%" % T["dump_24h_pct"]},
    {"key": "exit_sell_loss_pct", "label": "Selling $100 loses at least this much (Jupiter quote) = SELL", "value": "%s%%" % T["exit_sell_loss_pct"]},
    {"key": "exit_watch_loss_pct", "label": "Selling $100 loses at least this much = WATCH", "value": "%s%%" % T["exit_watch_loss_pct"]},
]
DECISION_ORDER = [
    "1. RugCheck says the token is rugged -> SELL.",
    "2. Liquidity < $5,000 -> SELL (hard to exit, big slippage).",
    "3. A $100 sell quote on Jupiter loses 30% or more -> SELL (exit too costly).",
    "4. Volume 24h < $1,000 -> WATCH (no demand).",
    "5. Price down 50% or more in 24h -> WATCH (possible dump).",
    "6. Pair younger than 1 hour -> WATCH (too new to trust).",
    "7. RugCheck danger flag, or mint / freeze authority still active, or a $100 sell loses 10% or more -> WATCH.",
    "8. Liquidity >= $20,000 and volume 24h >= 0.5x liquidity -> HOLD / BUY, but only when security and exit data were both checked. If either is missing it becomes WATCH.",
    "9. Anything else -> WATCH.",
    "No market data from any source -> UNKNOWN (no verdict is given; retry).",
    "If security (RugCheck) or exit (Jupiter) data is missing, the verdict uses market data only and the result lists it in `unknowns`. Do not size a trade while unknowns exist.",
]
SCORE_TEXT = ("Health score 0-100 = liquidity (up to 40: $50k+ is full) + turnover volume/liquidity (up to 30) "
              "+ age (up to 15: 24h+ is full) + 24h momentum (up to 15: 0% or better is full, -50% is zero). "
              "Then limited by verdict: SELL max 35, WATCH max 69, HOLD / BUY min 70.")
STATUS_TEXT = "pass = good, warn = caution (can cause WATCH), fail = triggers SELL, info = shown for context only, does not change the verdict."

app = FastAPI(title="TVibe Signal", version=VERSION,
              description="Check a Solana token before you sell. One request, one verdict from live data.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

# ---------------------------------------------------------------- helpers
def num(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None

def iso(ts=None):
    return datetime.fromtimestamp(ts or time.time(), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def usd(n):
    return "n/a" if n is None else "${:,.0f}".format(n)

def pstr(p):
    if p is None:
        return "n/a"
    return ("%.12f" % p).rstrip("0").rstrip(".") if p < 1 else "%.4f" % p

def age_label(h):
    if h is None:
        return None
    if h < 1:
        return "%dm" % int(h * 60)
    if h < 48:
        return "%dh %dm" % (int(h), int((h - int(h)) * 60))
    return "%dd %dh" % (int(h // 24), int(h % 24))

B58 = re.compile(r"[1-9A-HJ-NP-Za-km-z]+")
def extract_mint(raw):
    for tok in B58.findall(raw or ""):
        if 32 <= len(tok) <= 44:
            return tok
    return None

def http_json(url, tries=2, timeout=6, headers=None):
    err = "error"
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=dict(UA, **(headers or {}))), timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            err = "HTTP %d" % e.code
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                try:
                    w = min(float(e.headers.get("Retry-After") or 0), 3) or 0.8 * (i + 1)
                except Exception:
                    w = 0.8 * (i + 1)
                time.sleep(w)
                continue
            break
        except Exception as e:
            err = type(e).__name__
            if i < tries - 1:
                time.sleep(0.5)
                continue
    raise RuntimeError(err)

def tx(d, k):
    v = (d or {}).get(k) or {}
    b, s = v.get("buys"), v.get("sells")
    return {"buys": b, "sells": s} if b is not None and s is not None else None

# ---------------------------------------------------------------- data sources
def src_dex(m):
    d = http_json("https://api.dexscreener.com/latest/dex/tokens/" + m)
    out = []
    for p in d.get("pairs") or []:
        bt = p.get("baseToken") or {}
        if p.get("chainId") != "solana" or bt.get("address") != m:
            continue
        pc, vol, t = p.get("priceChange") or {}, p.get("volume") or {}, p.get("txns") or {}
        out.append({
            "symbol": bt.get("symbol"), "name": bt.get("name"), "price": num(p.get("priceUsd")),
            "liq": num((p.get("liquidity") or {}).get("usd")) or 0, "vol24": num(vol.get("h24")) or 0, "vol1": num(vol.get("h1")),
            "chg": {k: num(pc.get(k)) for k in ("m5", "h1", "h6", "h24")},
            "tx": {"h1": tx(t, "h1"), "h24": tx(t, "h24")},
            "fdv": num(p.get("fdv")), "mcap": num(p.get("marketCap")), "created_ms": p.get("pairCreatedAt"),
            "dex": p.get("dexId"), "pair": p.get("pairAddress"), "url": p.get("url")})
    return out

def src_gecko(m):
    d = http_json("https://api.geckoterminal.com/api/v2/networks/solana/tokens/%s/pools?page=1" % m)
    out = []
    for p in d.get("data") or []:
        a, rel = p.get("attributes") or {}, p.get("relationships") or {}
        if ((rel.get("base_token") or {}).get("data") or {}).get("id") != "solana_" + m:
            continue
        pc, vol, t = a.get("price_change_percentage") or {}, a.get("volume_usd") or {}, a.get("transactions") or {}
        created = None
        try:
            created = int(datetime.fromisoformat(a["pool_created_at"].replace("Z", "+00:00")).timestamp() * 1000)
        except Exception:
            pass
        addr = a.get("address")
        out.append({
            "symbol": (a.get("name") or "").split(" / ")[0] or None, "name": None, "price": num(a.get("base_token_price_usd")),
            "liq": num(a.get("reserve_in_usd")) or 0, "vol24": num(vol.get("h24")) or 0, "vol1": num(vol.get("h1")),
            "chg": {k: num(pc.get(k)) for k in ("m5", "h1", "h6", "h24")},
            "tx": {"h1": tx(t, "h1"), "h24": tx(t, "h24")},
            "fdv": num(a.get("fdv_usd")), "mcap": num(a.get("market_cap_usd")), "created_ms": created,
            "dex": ((rel.get("dex") or {}).get("data") or {}).get("id"), "pair": addr,
            "url": "https://www.geckoterminal.com/solana/pools/%s" % addr if addr else None})
    return out

def src_rugcheck(m):
    d = http_json("https://api.rugcheck.xyz/v1/tokens/%s/report" % m, tries=1, timeout=8)
    tk = d.get("token") or {}
    risks = []
    for x in d.get("risks") or []:
        if isinstance(x, dict):
            risks.append({"name": str(x.get("name") or "risk")[:80], "level": str(x.get("level") or "info"),
                          "description": str(x.get("description") or "")[:160], "value": x.get("value")})
    lp = [num((mk.get("lp") or {}).get("lpLockedPct")) for mk in (d.get("markets") or []) if isinstance(mk, dict)]
    lp = [x for x in lp if x is not None]
    tops = d.get("topHolders") or []
    top10 = round(sum((num(h.get("pct")) or 0) for h in tops[:10] if isinstance(h, dict)), 2) if tops else None
    def auth(key):
        if key in d:
            return bool(d.get(key))
        if key in tk:
            return bool(tk.get(key))
        return None
    dec = tk.get("decimals")
    return {"source": "rugcheck", "rugged": bool(d.get("rugged")), "risk_score": num(d.get("score_normalised")),
            "mint_authority_active": auth("mintAuthority"), "freeze_authority_active": auth("freezeAuthority"),
            "lp_locked_pct": max(lp) if lp else None, "top10_holders_pct": top10, "holders": d.get("totalHolders"),
            "decimals": int(dec) if isinstance(dec, (int, float)) else None, "risks": risks[:8]}

def jup_quote(m, price, dec, size):
    amount = int(size / price * (10 ** dec))
    if amount <= 0:
        raise RuntimeError("amount is 0")
    url = "%s/swap/v1/quote?inputMint=%s&outputMint=%s&amount=%d&slippageBps=1000" % (JUP_BASE, m, USDC, amount)
    d = http_json(url, tries=1, timeout=6, headers={"x-api-key": JUP_KEY} if JUP_KEY else None)
    out = num(d.get("outAmount"))
    if out is None:
        raise RuntimeError(str(d.get("error") or "no route")[:60])
    got = out / 1e6
    return {"size_usd": size, "out_usd": round(got, 2), "loss_pct": round((1 - got / size) * 100, 2), "route_hops": len(d.get("routePlan") or [])}

SOURCES = (("dexscreener", src_dex), ("geckoterminal", src_gecko))
SRC_N = {n: [0, 0] for n in ("dexscreener", "geckoterminal", "rugcheck", "jupiter")}
SRC_STATE = {n: {"ok": None, "last_ok_at": None, "last_error": None} for n in ("dexscreener", "geckoterminal", "rugcheck", "jupiter")}

def mark(name, ok, err=None):
    SRC_N[name][0 if ok else 1] += 1
    SRC_STATE[name].update(ok=ok, last_error=err)
    if ok:
        SRC_STATE[name]["last_ok_at"] = iso()

def fetch_market(m):
    tried, pairs, used = [], [], None
    for name, fn in SOURCES:
        try:
            res = fn(m)
            tried.append({"name": name, "ok": True, "pairs": len(res)})
            SRC_N[name][0] += 1
            SRC_STATE[name].update(ok=True, last_ok_at=iso(), last_error=None)
            if res:
                pairs, used = res, name
                break
        except Exception as e:
            tried.append({"name": name, "ok": False, "error": str(e)})
            SRC_N[name][1] += 1
            SRC_STATE[name].update(ok=False, last_error=str(e))
    return pairs, used, tried

# ---------------------------------------------------------------- verdict logic (public rules)
def decide(liq, vol, ch24, age_h, sec=None, ext=None):
    q100 = next((q for q in (ext or {}).get("quotes", []) if q["size_usd"] == 100), None)
    if sec and sec.get("rugged"):
        return "SELL", "sell", "red", "RugCheck flags this token as rugged."
    if liq < T["liq_sell"]:
        return "SELL", "sell", "red", "Liquidity too low (%s). Hard to exit without big slippage." % usd(liq)
    if q100 and q100["loss_pct"] >= T["exit_sell_loss_pct"]:
        return "SELL", "sell", "red", "Selling $100 would lose about %.0f%% (Jupiter quote). Exit is too costly." % q100["loss_pct"]
    if vol < T["vol_min"]:
        return "WATCH", "watch", "yellow", "Volume 24h too low (%s). No demand right now." % usd(vol)
    if ch24 is not None and ch24 <= T["dump_24h_pct"]:
        return "WATCH", "watch", "yellow", "Price is down %.0f%% in 24h. Possible dump." % abs(ch24)
    if age_h is not None and age_h < T["age_min_h"]:
        return "WATCH", "watch", "yellow", "Pair is only %s old. Too new to trust." % age_label(age_h)
    if sec:
        danger = [r["name"] for r in sec.get("risks", []) if r.get("level") == "danger"]
        if danger:
            return "WATCH", "watch", "yellow", "RugCheck danger flag: %s." % danger[0]
        if sec.get("mint_authority_active") or sec.get("freeze_authority_active"):
            return "WATCH", "watch", "yellow", "Mint or freeze authority is still active. The creator can change supply or freeze wallets."
    if q100 and q100["loss_pct"] >= T["exit_watch_loss_pct"]:
        return "WATCH", "watch", "yellow", "Selling $100 would lose about %.0f%% (Jupiter quote). Exit is costly." % q100["loss_pct"]
    if liq >= T["liq_hold"] and vol >= liq * T["vol_liq_hold"]:
        return "HOLD / BUY", "hold", "green", "Healthy liquidity (%s) + active volume (%s)." % (usd(liq), usd(vol))
    return "WATCH", "watch", "yellow", "Liquidity %s, volume %s. Not strong enough to chase." % (usd(liq), usd(vol))

ACTIONS = {"sell": "Avoid buying. Exit risk is high.", "watch": "Wait and watch. Not a clear signal.",
           "hold": "Looks healthy right now.", "unknown": "No verdict. Retry in a few seconds.", "skip": "Not applicable."}

def chk(cid, label, value, rule, status, note):
    return {"id": cid, "label": label, "value": value, "status": status, "note": note}

def build_checks(mk, sec=None, ext=None, deep=True):
    liq, vol, ratio, ch, age = mk["liquidity_usd"], mk["volume_24h_usd"], mk["vol_liq_ratio"], mk["price_change_pct"]["h24"], mk["age_hours"]
    c = [chk("liquidity", "Liquidity", usd(liq), "SELL < $%s, healthy >= $%s" % (format(T["liq_sell"], ","), format(T["liq_hold"], ",")),
             "fail" if liq < T["liq_sell"] else "warn" if liq < T["liq_hold"] else "pass",
             "Money in the pool you would sell into. Low = big slippage.")]
    c.append(chk("volume_24h", "Volume 24h", usd(vol), "WATCH < $%s" % format(T["vol_min"], ","),
                 "warn" if vol < T["vol_min"] else "pass", "Trading activity. No volume = no buyers."))
    c.append(chk("turnover", "Volume / liquidity", "n/a" if ratio is None else "%.2fx" % ratio,
                 "HOLD needs >= %sx" % T["vol_liq_hold"], "pass" if (ratio or 0) >= T["vol_liq_hold"] else "warn",
                 "How much of the pool trades per day."))
    if age is None:
        c.append(chk("age", "Pair age", "unknown", "WATCH < %s hour" % T["age_min_h"], "info", "Source did not give a creation time."))
    else:
        c.append(chk("age", "Pair age", age_label(age), "WATCH < %s hour" % T["age_min_h"],
                     "warn" if age < T["age_min_h"] else "pass", "Brand-new pairs are the riskiest."))
    if ch is None:
        c.append(chk("momentum", "Price change 24h", "n/a", "WATCH <= %s%%" % T["dump_24h_pct"], "info", "No data."))
    else:
        c.append(chk("momentum", "Price change 24h", "%+.1f%%" % ch, "WATCH <= %s%%" % T["dump_24h_pct"],
                     "warn" if ch <= T["warn_24h_pct"] else "pass", "Big drops often mean holders are dumping."))
    t1 = mk["txns"].get("h1")
    if t1 and t1["buys"] + t1["sells"] >= 20:
        heavy = t1["sells"] > 1.5 * t1["buys"]
        c.append(chk("sell_pressure", "Sells vs buys (1h)", "%d sells / %d buys" % (t1["sells"], t1["buys"]), "info only",
                     "info", "More sells than buys right now." if heavy else "Buying and selling look balanced."))
    if sec:
        c.append(chk("rugged", "RugCheck rugged flag", "YES" if sec["rugged"] else "no", "rugged = SELL", "fail" if sec["rugged"] else "pass", "RugCheck marks tokens that were already rugged."))
        au = sec.get("mint_authority_active"), sec.get("freeze_authority_active")
        if au[0] is None and au[1] is None:
            c.append(chk("authorities", "Mint / freeze authority", "unknown", "active = WATCH", "info", "RugCheck did not return authority data."))
        else:
            bad = bool(au[0] or au[1])
            c.append(chk("authorities", "Mint / freeze authority", "mint %s, freeze %s" % ("ACTIVE" if au[0] else "revoked", "ACTIVE" if au[1] else "revoked"),
                         "active = WATCH", "warn" if bad else "pass", "Active authority lets the creator mint more supply or freeze wallets."))
        dn = [r for r in sec.get("risks", []) if r.get("level") == "danger"]
        c.append(chk("danger_risks", "RugCheck danger flags", str(len(dn)), "any = WATCH", "warn" if dn else "pass", dn[0]["name"] if dn else "No danger-level flags."))
        if sec.get("lp_locked_pct") is not None:
            c.append(chk("lp_locked", "LP locked", "%.0f%%" % sec["lp_locked_pct"], "info only", "info", "Locked LP means the creator cannot pull the pool quickly."))
        if sec.get("top10_holders_pct") is not None:
            c.append(chk("top10", "Top 10 holders", "%.1f%%" % sec["top10_holders_pct"], "info only", "info", "High concentration means a few wallets can dump."))
    elif deep:
        c.append(chk("security", "Security (RugCheck)", "not checked", "-", "info", "RugCheck did not answer. Verdict uses market data only."))
    if ext and ext.get("quotes"):
        for q in ext["quotes"]:
            L = q["loss_pct"]
            st = "fail" if (q["size_usd"] == 100 and L >= T["exit_sell_loss_pct"]) else "warn" if (q["size_usd"] == 100 and L >= T["exit_watch_loss_pct"]) else "pass"
            c.append(chk("exit_%d" % q["size_usd"], "Sell $%s" % format(q["size_usd"], ","), "get ~$%s (%.1f%% cost)" % (format(q["out_usd"], ",.0f"), L),
                         "$100: SELL >= %s%%, WATCH >= %s%%" % (T["exit_sell_loss_pct"], T["exit_watch_loss_pct"]) if q["size_usd"] == 100 else "info only",
                         st if q["size_usd"] == 100 else ("info" if st == "pass" else "info"), "Jupiter quote to USDC. A quote is not proof that a sell will succeed."))
    elif deep:
        c.append(chk("exit", "Exit cost (Jupiter)", "not checked", "-", "info", (ext or {}).get("error") or "No quote available right now."))
    return c

def score_of(mk, code):
    liq, vol, age, ch = mk["liquidity_usd"], mk["volume_24h_usd"], mk["age_hours"], mk["price_change_pct"]["h24"]
    s = min(liq / 50000.0, 1) * 40 + min((vol / liq) if liq else 0, 1) * 30
    s += (min(age / 24.0, 1) if age is not None else 0.5) * 15
    s += (15 if ch is None else max(0.0, min(1.0, (ch + 50) / 50.0)) * 15)
    s = int(round(s))
    return min(s, 35) if code == "sell" else min(s, 69) if code == "watch" else max(s, 70)

# ---------------------------------------------------------------- result building
def shell(m, verdict, code, level, reason, tried, **extra):
    r = {"ok": code != "unknown", "mint": m, "verdict": verdict, "code": code, "level": level, "score": None,
         "action": ACTIONS[code], "reason": reason, "summary": "%s - %s" % (verdict, reason), "symbol": None, "name": None,
         "market": None, "security": None, "exit": None, "unknowns": [], "checks": [], "data": {"source": None, "sources_tried": tried, "fetched_at": iso(), "age_s": 0, "cached": False, "stale": False},
         "rules_version": RULES_VERSION, "disclaimer": DISCLAIMER,
         "price": None, "liquidity": None, "volume": None, "age_h": None, "dex": None, "url": None}
    r.update(extra)
    return r

def evaluate(m, deep=True):
    ex = ThreadPoolExecutor(max_workers=4)
    rug_f = ex.submit(src_rugcheck, m) if deep else None
    try:
        pairs, used, tried = fetch_market(m)
        if not pairs:
            if all(t["ok"] for t in tried):
                return shell(m, "SELL", "sell", "red", "No trading pair found on %s. No liquidity = no buyer (or the mint is wrong / too new to be indexed)." %
                             " or ".join(t["name"] for t in tried), tried)
            errs = "; ".join("%s: %s" % (t["name"], t.get("error", "no pair")) for t in tried)
            return shell(m, "UNKNOWN", "unknown", "gray", "Data sources are busy or rate-limited (%s). No verdict was made." % errs, tried, retry_after_s=8)
        p = max(pairs, key=lambda x: x["liq"])
        sec = None
        if rug_f is not None:
            try:
                sec = rug_f.result(timeout=9)
                mark("rugcheck", True)
            except Exception as e:
                mark("rugcheck", False, str(e)[:60] or type(e).__name__)
        ext = None
        if deep:
            ext = {"checked": False, "source": "jupiter", "quotes": [], "error": None}
            dec = (sec or {}).get("decimals")
            sizes = [z for z in T["exit_sizes_usd"] if p["liq"] and z <= p["liq"] * 0.8]
            if not p["price"]:
                ext["error"] = "No price to size the quote."
            elif dec is None:
                ext["error"] = "Token decimals unknown (needs RugCheck)."
            elif not sizes:
                ext["error"] = "Liquidity too small for the quote sizes."
            else:
                futs = [(z, ex.submit(jup_quote, m, p["price"], dec, z)) for z in sizes]
                errs = []
                for z, f in futs:
                    try:
                        ext["quotes"].append(f.result(timeout=8))
                    except Exception as e:
                        errs.append(str(e)[:60] or type(e).__name__)
                if ext["quotes"]:
                    ext["checked"] = True
                    mark("jupiter", True)
                else:
                    ext["error"] = "Jupiter quote failed: %s" % (errs[0] if errs else "no answer")
                    mark("jupiter", False, errs[0] if errs else None)
        now_ms = time.time() * 1000
        age_h = round(max(now_ms - p["created_ms"], 0) / 3600000.0, 2) if p.get("created_ms") else None
        ratio = round(p["vol24"] / p["liq"], 3) if p["liq"] else None
        mk = {"price_usd": p["price"], "liquidity_usd": p["liq"], "liquidity_all_pairs_usd": round(sum(x["liq"] for x in pairs), 2),
              "volume_24h_usd": p["vol24"], "volume_1h_usd": p["vol1"], "vol_liq_ratio": ratio,
              "market_cap_usd": p["mcap"], "fdv_usd": p["fdv"], "price_change_pct": p["chg"], "txns": p["tx"],
              "age_hours": age_h, "age_label": age_label(age_h), "dex": p["dex"], "pair_address": p["pair"],
              "pair_url": p["url"], "pairs_count": len(pairs)}
        verdict, code, level, why = decide(p["liq"], p["vol24"], p["chg"]["h24"], age_h, sec, ext)
        unk = []
        if deep and not sec:
            unk.append("security_not_checked")
        if deep and not (ext and ext.get("checked")):
            unk.append("exit_not_checked")
        if code == "hold" and unk:
            verdict, code, level = "WATCH", "watch", "yellow"
            why = "Market data looks healthy, but %s. Retry before trusting it." % " and ".join(
                ["security was not checked" if u == "security_not_checked" else "exit cost was not checked" for u in unk])
        sc = score_of(mk, code)
        sym = p["symbol"] or "token"
        r = shell(m, verdict, code, level, why, tried)
        r.update(score=sc, symbol=p["symbol"], name=p["name"], market=mk, security=sec, exit=ext, unknowns=unk,
                 checks=build_checks(mk, sec, ext, deep),
                 summary="%s (%s) - %s | score %d/100 | price %s | liquidity %s | volume 24h %s | age %s | %s%s" % (
                     verdict, sym, why, sc, pstr(p["price"]), usd(p["liq"]), usd(p["vol24"]), age_label(age_h) or "n/a", p["dex"] or "n/a",
                     (" | unknowns: " + ", ".join(unk)) if unk else ""),
                 price=p["price"], liquidity=p["liq"], volume=p["vol24"], age_h=age_h, dex=p["dex"], url=p["url"])
        r["data"]["source"] = used
        return r
    finally:
        ex.shutdown(wait=False)

_cache, _lock, _hits = {}, threading.Lock(), {}
ST = {"checks": 0, "mints": set(), "codes": {}, "hits": 0, "ms": [], "tape": []}

def log_check(res, ms):
    with _lock:
        ST["checks"] += 1
        ST["mints"].add(res["mint"])
        ST["codes"][res["code"]] = ST["codes"].get(res["code"], 0) + 1
        ST["hits"] += 1 if res["data"].get("cached") else 0
        ST["ms"] = (ST["ms"] + [ms])[-200:]
        ST["tape"] = ([{"mint": res["mint"], "symbol": res.get("symbol"), "verdict": res["verdict"], "code": res["code"],
                        "score": res.get("score"), "t": int(time.time())}] + ST["tape"])[:10]

@app.get("/stats")
def stats():
    n, ms = ST["checks"], sorted(ST["ms"])
    srcs = {k: {"ok": SRC_STATE[k]["ok"], "ok_n": v[0], "fail_n": v[1], "success_pct": round(100.0 * v[0] / (v[0] + v[1])) if v[0] + v[1] else None,
                "last_error": SRC_STATE[k]["last_error"]} for k, v in SRC_N.items()}
    return {"version": VERSION, "rules_version": RULES_VERSION, "since": iso(STARTED), "uptime_s": int(time.time() - STARTED), "checks": n,
            "unique_tokens": len(ST["mints"]), "verdicts": dict(ST["codes"]), "cache_hit_pct": round(100.0 * ST["hits"] / n) if n else None,
            "median_ms": ms[len(ms) // 2] if ms else None, "sources": srcs, "tape": ST["tape"],
            "note": "In-memory counters since the last restart of the free host. This is usage, not a track record of verdict accuracy."}

def cached_evaluate(m, deep=True):
    now = time.time()
    key = (m, deep)
    with _lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return stamp(hit[1], hit[0], cached=True)
    res = evaluate(m, deep)
    if res["code"] != "unknown":
        with _lock:
            if len(_cache) > 2000:
                _cache.clear()
            _cache[key] = (now, res)
        return res
    if hit and now - hit[0] < STALE_MAX:
        old = stamp(hit[1], hit[0], cached=True, stale=True)
        old["data"]["sources_tried"] = res["data"]["sources_tried"]
        return old
    return res

def stamp(res, ts, cached=False, stale=False):
    r = dict(res)
    r["data"] = dict(res["data"], cached=cached, stale=stale, age_s=int(time.time() - ts), fetched_at=iso(ts))
    return r

def over_limit(ip):
    now = time.time()
    with _lock:
        if len(_hits) > 5000:
            _hits.clear()
        q = [t for t in _hits.get(ip, []) if now - t < 60]
        if len(q) >= RATE_PER_MIN:
            _hits[ip] = q
            return int(60 - (now - q[0])) + 1
        q.append(now)
        _hits[ip] = q
    return 0

# ---------------------------------------------------------------- endpoints
@app.get("/health")
def health():
    mkt = [SRC_STATE[n] for n in ("dexscreener", "geckoterminal")]
    ok = [s for s in mkt if s["ok"]]
    bad = [s for s in mkt if s["ok"] is False]
    status = "degraded" if bad and not ok else "ok"
    return {"status": status, "version": VERSION, "rules_version": RULES_VERSION, "uptime_s": int(time.time() - STARTED),
            "cache_entries": len(_cache), "sources": SRC_STATE, "time": iso()}

@app.get("/rules")
def rules():
    return {"version": RULES_VERSION, "note": "Rules are private to prevent gaming."}

@app.get("/llms.txt", response_class=PlainTextResponse)
def llms():
    return ("# TVibe Signal %s\n> Check a Solana token before you sell. One request, one verdict, live market, security and exit data.\n\n"
            "GET /check?mint=<SOLANA_MINT>  -> JSON\n"
            "Read: verdict (SELL | WATCH | HOLD / BUY | UNKNOWN | SKIP), code (sell|watch|hold|unknown|skip), level (red|yellow|green|gray),\n"
            "score (0-100), reason, summary (one line for LLMs), market{price_usd, liquidity_usd, volume_24h_usd, age_hours, ...},\n"
            "checks[] (id, value, status pass|warn|fail|info), data{source, fetched_at, stale, sources_tried},\n"
            "security{rugged, mint/freeze authority, lp_locked_pct, top10_holders_pct, risks[]} (RugCheck), exit{quotes[{size_usd, out_usd, loss_pct}]} (Jupiter),\n"
            "unknowns[] (non-empty = do not size a trade). Add ?deep=0 for market data only (faster).\n"
            "If code is 'unknown' (HTTP 503) wait retry_after_s and retry. Never treat output as financial advice.\n\n"
            "GET /rules   version only (rules are private)\nGET /health  source status\nGET /docs    OpenAPI\n" % VERSION)

@app.get("/check")
def check(request: Request, mint: str = Query(default=""), deep: int = Query(default=1)):
    m = extract_mint((mint or "").strip())
    if not m:
        return JSONResponse({"ok": False, "code": "bad_request", "error": "Paste a valid Solana token mint (32-44 characters)."}, status_code=400)
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    wait = over_limit(ip)
    if wait:
        return JSONResponse({"ok": False, "code": "rate_limited", "error": "Too many requests. Retry in %ds." % wait, "retry_after_s": wait},
                            status_code=429, headers={"Retry-After": str(wait)})
    if m == SOL_MINT:
        res = shell(m, "SKIP", "skip", "gray", "SOL is the base currency, not a pump token. Paste a real token mint.", [], symbol="SOL", name="Solana")
        return JSONResponse(res, headers={"Cache-Control": "no-store"})
    t0 = time.time()
    res = cached_evaluate(m, bool(deep))
    log_check(res, int((time.time() - t0) * 1000))
    if res["code"] == "unknown":
        return JSONResponse(res, status_code=503, headers={"Retry-After": "8", "Cache-Control": "no-store"})
    return JSONResponse(res, headers={"Cache-Control": "no-store", "X-Data-Source": str(res["data"]["source"])})

@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE

# ---------------------------------------------------------------- web page
PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#060a12">
<title>TVibe Signal - Check before you sell</title>
<meta name="description" content="Paste a Solana token mint. Get a clear verdict with liquidity, volume, age and live market, security and exit data. Built for people and AI agents.">
<meta property="og:title" content="TVibe Signal - Check before you sell">
<meta property="og:description" content="One request, one verdict, live market, security and exit data.">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%2322c55e'/%3E%3Cpath d='M5 17h5l3-8 5 14 3-6h6' fill='none' stroke='%23041208' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E">
<style>
:root{--bg:#060a12;--card:rgba(16,24,38,.78);--line:#1f2d40;--mut:#8fa3b8;--txt:#e8eef5;--g:#22c55e;--y:#fbbf24;--r:#f43f5e;--n:#94a3b8;--b:#60a5fa}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html{background:var(--bg)}
body{margin:0;font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:var(--txt);background:var(--bg);min-height:100vh;padding:14px 14px 40px;line-height:1.45}
.bg{position:fixed;inset:0;z-index:-1;overflow:hidden;background:radial-gradient(1200px 600px at 50% -10%,#0d1b2e 0,transparent 60%)}
.bg:before,.bg:after{content:"";position:absolute;width:420px;height:420px;border-radius:50%;filter:blur(90px);opacity:.28;animation:float 18s ease-in-out infinite}
.bg:before{background:#22c55e;left:-120px;top:20%}.bg:after{background:#3b82f6;right:-140px;top:55%;animation-delay:-9s}
@keyframes float{50%{transform:translate(40px,-50px) scale(1.15)}}
.wrap{max-width:1040px;margin:0 auto}
.top{max-width:1040px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;padding:8px 2px 16px}
.logo{display:flex;align-items:center;gap:10px;font-weight:800;font-size:20px;letter-spacing:.01em}
.logo i{width:32px;height:32px;border-radius:9px;background:linear-gradient(135deg,#22c55e,#16a34a);display:grid;place-items:center;box-shadow:0 0 22px rgba(34,197,94,.45)}
.badge{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:700;background:#0f1b2b;color:var(--mut);border:1px solid var(--line);padding:6px 11px;border-radius:999px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--n)}
.badge.ok .dot{background:var(--g);box-shadow:0 0 0 0 rgba(34,197,94,.6);animation:pulse 2s infinite}.badge.ok{color:#86efac}
.badge.bad .dot{background:var(--y)}.badge.bad{color:var(--y)}
@keyframes pulse{70%{box-shadow:0 0 0 8px rgba(34,197,94,0)}100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}}
.card{background:var(--card);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border:1px solid var(--line);border-radius:22px;padding:22px;box-shadow:0 20px 60px rgba(0,0,0,.35);margin-bottom:14px}
h1{font-size:28px;line-height:1.15;margin:0 0 6px;letter-spacing:-.01em}
.sub{color:var(--mut);font-size:14px;margin:0 0 18px}
label{display:block;font-size:11px;color:var(--mut);letter-spacing:.14em;font-weight:800;margin-bottom:8px}
.inp{position:relative}
input{width:100%;padding:16px 92px 16px 16px;font-size:16px;border-radius:14px;border:1px solid #2a3a4d;background:#050810;color:#fff;outline:none;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;transition:.2s}
input:focus{border-color:var(--g);box-shadow:0 0 0 3px rgba(34,197,94,.18)}
.inp button{position:absolute;right:8px;top:8px;bottom:8px;padding:0 14px;border-radius:10px;border:1px solid #2a3a4d;background:#14202f;color:var(--txt);font-weight:700;font-size:13px;cursor:pointer}
.go{width:100%;margin-top:12px;padding:16px;font-size:17px;font-weight:900;letter-spacing:.06em;border:0;border-radius:14px;color:#04120a;cursor:pointer;background:linear-gradient(135deg,#4ade80,#22c55e);box-shadow:0 8px 28px rgba(34,197,94,.35);transition:.15s}
.go:active{transform:scale(.985)}.go:disabled{opacity:.65;cursor:wait}
.recent{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.chip{display:flex;align-items:center;gap:7px;font-size:12px;font-weight:700;padding:6px 10px;border-radius:999px;background:#0c1521;border:1px solid var(--line);color:var(--txt);cursor:pointer}
.chip i{width:8px;height:8px;border-radius:50%}
#msg{margin-top:14px;font-size:14px;color:var(--mut)}
#msg.err{color:#fda4af}
.sk{height:14px;border-radius:8px;background:linear-gradient(90deg,#122033 25%,#1b2d45 50%,#122033 75%);background-size:200% 100%;animation:sh 1.2s infinite;margin-top:12px}
@keyframes sh{to{background-position:-200% 0}}
.banner{margin-top:14px;padding:10px 12px;border-radius:12px;background:rgba(251,191,36,.1);border:1px solid rgba(251,191,36,.35);color:#fde68a;font-size:13px}
.hero{margin-top:18px;display:flex;gap:16px;align-items:center;padding:16px;border-radius:18px;border:1px solid var(--line);background:linear-gradient(135deg,rgba(255,255,255,.03),transparent);animation:rise .5s ease both}
@keyframes rise{from{opacity:0;transform:translateY(10px)}}
.hero.green{border-color:rgba(34,197,94,.45);box-shadow:0 0 40px rgba(34,197,94,.12)}
.hero.yellow{border-color:rgba(251,191,36,.45);box-shadow:0 0 40px rgba(251,191,36,.1)}
.hero.red{border-color:rgba(244,63,94,.5);box-shadow:0 0 40px rgba(244,63,94,.14)}
.ring{position:relative;width:108px;height:108px;flex:none}
.ring svg{width:100%;height:100%}
.rt{fill:none;stroke:#16243a;stroke-width:10}
.rf{fill:none;stroke-width:10;stroke-linecap:round;transition:stroke-dashoffset 1.1s cubic-bezier(.2,.8,.2,1)}
.green .rf{stroke:var(--g)}.yellow .rf{stroke:var(--y)}.red .rf{stroke:var(--r)}.gray .rf{stroke:var(--n)}
.rn{position:absolute;inset:0;display:grid;place-content:center;text-align:center}
.rn b{font-size:28px;line-height:1}.rn span{font-size:10px;color:var(--mut);letter-spacing:.12em;margin-top:3px}
.vk{font-size:11px;letter-spacing:.14em;color:var(--mut);font-weight:800}
.vt{font-size:34px;font-weight:900;line-height:1.05;margin:2px 0}
.green .vt{color:var(--g)}.yellow .vt{color:var(--y)}.red .vt{color:var(--r)}.gray .vt{color:var(--n)}
.va{font-size:14px;color:var(--txt)}
.tok{font-size:13px;color:var(--mut);margin-top:4px}
.reason{margin:14px 2px 0;font-size:15px}
.meta{margin:8px 2px 0;font-size:12px;color:var(--mut)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}
.tile{background:#050810;border:1px solid var(--line);border-radius:14px;padding:12px}
.tile span{display:block;font-size:10.5px;color:var(--mut);letter-spacing:.12em;font-weight:800}
.tile b{display:block;font-size:19px;margin-top:3px;word-break:break-word}
.tile small{display:block;color:var(--mut);font-size:12px;margin-top:2px}
.up{color:var(--g)}.dn{color:var(--r)}
.chg{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px}
.chg div{background:#050810;border:1px solid var(--line);border-radius:12px;padding:8px;text-align:center}
.chg span{display:block;font-size:10.5px;color:var(--mut);font-weight:800;letter-spacing:.1em}
.chg b{font-size:14px}
.pb{margin-top:12px}.pl{display:flex;justify-content:space-between;font-size:12px;color:var(--mut);margin-bottom:5px}
.bar{height:9px;border-radius:99px;background:rgba(244,63,94,.7);overflow:hidden}.bar i{display:block;height:100%;background:var(--g);border-radius:99px 0 0 99px}
h3{font-size:12px;letter-spacing:.14em;color:var(--mut);margin:22px 0 10px;font-weight:800}
.ck{display:flex;gap:12px;padding:11px 0;border-top:1px solid #16243a}
.ck:first-of-type{border-top:0}
.ic{flex:none;width:26px;height:26px;border-radius:50%;display:grid;place-items:center;font-weight:900;font-size:13px}
.pass .ic{background:rgba(34,197,94,.16);color:var(--g)}.warn .ic{background:rgba(251,191,36,.16);color:var(--y)}
.fail .ic{background:rgba(244,63,94,.18);color:var(--r)}.info .ic{background:rgba(96,165,250,.16);color:var(--b)}
.ck .t{display:flex;justify-content:space-between;gap:10px;font-weight:700;font-size:14px}
.ck .t em{font-style:normal;text-align:right}
.ck small{display:block;color:var(--mut);font-size:12px;margin-top:2px}
.row{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:16px}
.btn{padding:12px;border-radius:12px;border:1px solid #2a3a4d;background:#14202f;color:var(--txt);font-weight:700;font-size:13.5px;cursor:pointer;text-align:center;text-decoration:none;display:block}
.btn:active{transform:scale(.98)}
.btn.pri{background:#0f2a1b;border-color:#1e5a38;color:#86efac}
details{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:4px 18px;margin-bottom:12px}
summary{cursor:pointer;padding:14px 0;font-weight:800;font-size:14px;list-style:none;display:flex;justify-content:space-between}
summary::after{content:"+";color:var(--mut);font-size:18px}details[open] summary::after{content:"-"}
details p,details li{font-size:13.5px;color:#cbd5e1}
details ol{padding-left:18px;margin:0 0 10px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:12px}
td{padding:8px 0;border-top:1px solid #16243a;vertical-align:top}td:last-child{text-align:right;font-weight:800;white-space:nowrap;padding-left:10px}
pre{background:#050810;border:1px solid var(--line);border-radius:12px;padding:12px;font-size:11.5px;line-height:1.55;overflow:auto;max-height:340px;margin:8px 0 12px;white-space:pre-wrap;word-break:break-all;color:#cbd5e1}
code{font-family:ui-monospace,Menlo,monospace;font-size:12px;color:#a7f3d0}
.k{color:#93c5fd}.s{color:#fcd34d}.n{color:#f9a8d4}
.rk{display:inline-block;margin:4px 6px 0 0;padding:5px 10px;border-radius:999px;font-size:12px;font-weight:700;border:1px solid var(--line);background:#0c1521}
.rk.danger{color:#fda4af;border-color:rgba(244,63,94,.5);background:rgba(244,63,94,.1)}.rk.warn{color:#fde68a;border-color:rgba(251,191,36,.45);background:rgba(251,191,36,.08)}.rk.info,.rk.good{color:#bfdbfe}
.ex{display:flex;justify-content:space-between;align-items:center;gap:10px;background:#050810;border:1px solid var(--line);border-radius:14px;padding:12px;margin-top:8px}
.ex b{font-size:15px}.ex small{display:block;color:var(--mut);font-size:12px}.exl{font-size:20px;font-weight:900}
.note{font-size:13px;color:var(--mut);margin-top:8px}
.foot{text-align:center;color:#6b7f95;font-size:12px;margin-top:20px}.foot a{color:var(--mut);margin:0 6px}
#toast{position:fixed;left:50%;bottom:26px;transform:translate(-50%,30px);background:#0f2a1b;border:1px solid #1e5a38;color:#bbf7d0;padding:10px 16px;border-radius:12px;font-weight:700;font-size:13px;opacity:0;pointer-events:none;transition:.25s;z-index:9}
#toast.on{opacity:1;transform:translate(-50%,0)}
.hero0{text-align:center;padding:22px 0 10px}
.eye{display:inline-block;font:700 11px ui-monospace,Menlo,monospace;letter-spacing:.2em;color:#4ade80;border:1px solid #1e5a38;border-radius:99px;padding:6px 14px;background:rgba(34,197,94,.07)}
.big{font-size:clamp(34px,7vw,66px);line-height:1.02;margin:14px 0 12px;letter-spacing:-.035em;font-weight:900}
.big span{background:linear-gradient(90deg,#4ade80,#22d3ee);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero0 p{color:var(--mut);max-width:620px;margin:0 auto;font-size:15px}
.mon{position:relative;margin:22px auto 8px;max-width:920px;height:160px;border:1px solid #16352a;border-radius:22px;overflow:hidden;background:repeating-linear-gradient(0deg,rgba(34,197,94,.06) 0 1px,transparent 1px 26px),repeating-linear-gradient(90deg,rgba(34,197,94,.06) 0 1px,transparent 1px 26px),#040a10;box-shadow:inset 0 0 70px rgba(34,197,94,.09),0 0 50px rgba(34,197,94,.08)}
#ecg{position:absolute;inset:0;width:100%;height:100%;-webkit-mask-image:linear-gradient(90deg,transparent,#000 10%,#000 90%,transparent);mask-image:linear-gradient(90deg,transparent,#000 10%,#000 90%,transparent)}
.mon b,.mon em{position:absolute;top:12px;font:700 11px ui-monospace,Menlo,monospace;letter-spacing:.14em;font-style:normal}.mon b{left:16px}.mon em{right:16px;color:#4b6a5b}
.chk{max-width:700px;margin:0 auto 18px}.ct{font-size:20px;margin:0 0 6px}
.sec{margin:34px 0}.sh{font:800 12px ui-monospace,Menlo,monospace;letter-spacing:.2em;color:var(--mut);margin:0 0 14px}.sh i{font-weight:500;letter-spacing:.04em;color:#5f738a;margin-left:8px;font-style:normal}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.sc{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px}.sc span{display:block;font:700 10.5px ui-monospace,Menlo,monospace;letter-spacing:.14em;color:var(--mut)}.sc b{display:block;font:800 24px ui-monospace,Menlo,monospace;margin-top:4px;color:#e8fff1}
.mix{display:flex;height:10px;border-radius:99px;overflow:hidden;background:#16243a;margin-top:14px;gap:2px}.mix i{display:block}
.mixlg{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px;color:var(--mut);margin-top:8px}.mixlg i{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.two{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin-top:14px}
.box{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:14px 16px}.box h4{margin:0 0 6px;font:800 11px ui-monospace,Menlo,monospace;letter-spacing:.16em;color:var(--mut)}
.tp{display:flex;align-items:center;gap:10px;padding:9px 0;border-top:1px solid #16243a;font-size:13px}.tp:first-of-type{border-top:0}.tp[data-m]{cursor:pointer}
.tp i{flex:none;width:8px;height:8px;border-radius:50%}.tp b{flex:none}.tp span{color:var(--mut);flex:1}.tp em{font-style:normal;color:#6b7f95;font-size:11px;max-width:45%;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lg4{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.lg{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px}.lg svg{width:100%;height:40px}.lg svg path{fill:none;stroke-width:2.4;stroke-linejoin:round;stroke-linecap:round}
.lg b{display:block;font-size:16px;margin:8px 0 4px}.lg p{margin:0;font-size:13px;color:var(--mut)}.lg .n{font:900 30px ui-monospace,Menlo,monospace;color:#1f3a2c}
@media(max-width:380px){.hero{flex-direction:column;text-align:center}.vt{font-size:30px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body>
<div class="bg"></div>
<header class="top">
 <div class="logo"><i><svg width="20" height="20" viewBox="0 0 32 32"><path d="M3 17h6l4-9 6 16 4-7h6" fill="none" stroke="#04120a" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/></svg></i>TVibe Signal</div>
 <div class="badge" id="badge"><span class="dot"></span><span id="btxt">LIVE - __V__</span></div>
</header>
<main class="wrap">
 <section class="hero0"><span class="eye">SOLANA TOKEN VITALS - LIVE</span>
  <h1 class="big">Take the pulse of any token <span>before you sell.</span></h1>
  <p>Paste a mint. Four public data sources are read in seconds and the token gets a rhythm: steady, irregular or flatline. Verdict from live market, security and exit data.</p>
  <div class="mon"><canvas id="ecg"></canvas><b id="rl">STANDBY</b><em>RHYTHM = VERDICT, NOT PRICE</em></div></section>
 <section class="card chk" id="chk">
  <h2 class="ct">Check before you sell</h2>
  <p class="sub">Paste a Solana token mint. We check liquidity, volume, age, momentum, security (RugCheck) and exit cost (Jupiter), then give you a clear verdict. Verdict from live market, security and exit data.</p>
  <label for="mint">TOKEN MINT</label>
  <div class="inp"><input id="mint" placeholder="Paste token mint..." autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="go"><button type="button" id="pasteBtn">Paste</button></div>
  <button type="button" class="go" id="btn">CHECK</button>
  <div class="recent" id="recent"></div>
  <div id="msg">Paste a mint, then press CHECK.</div>
  <div id="out"></div>
 </section>
<section class="sec"><h2 class="sh">LIVE NUMBERS <i>counted by this server since its last restart</i></h2>
  <div class="stats" id="stats"></div><div class="mix" id="mix"></div><div class="mixlg" id="mixlg"></div>
  <div class="two"><div class="box"><h4>DATA SOURCES (SUCCESS RATE)</h4><div id="srcs"></div></div><div class="box"><h4>LIVE TAPE (TAP TO RE-CHECK)</h4><div id="tape"></div></div></div></section>
 <section class="sec"><h2 class="sh">READ THE RHYTHM</h2><div class="lg4">
  <div class="lg"><svg viewBox="0 0 120 40"><path stroke="#22c55e" d="M0 22H16l4-3 4 3H38l4 4 5-20 5 26 4-10H70l4-3 4 3H120"/></svg><b style="color:#22c55e">HOLD / BUY</b><p>Liquidity, volume, security and exit cost all pass.</p></div>
  <div class="lg"><svg viewBox="0 0 120 40"><path stroke="#fbbf24" d="M0 22H10l4-3 4 3h8l3 5 4-18 4 22 3-8h12l3-3 3 3 8 0 3 6 5-24 4 20H120"/></svg><b style="color:#fbbf24">WATCH</b><p>Something is weak: volume, age, price drop, authority or exit cost.</p></div>
  <div class="lg"><svg viewBox="0 0 120 40"><path stroke="#f43f5e" d="M0 20H120"/></svg><b style="color:#f43f5e">SELL</b><p>Rugged, almost no liquidity, or selling is too costly to exit.</p></div>
  <div class="lg"><svg viewBox="0 0 120 40"><path stroke="#94a3b8" stroke-dasharray="5 7" d="M0 20H120"/></svg><b style="color:#94a3b8">UNKNOWN</b><p>No data right now. No verdict is made. Retry.</p></div></div></section>
 <section class="sec"><h2 class="sh">HOW IT WORKS</h2><div class="lg4">
  <div class="lg"><div class="n">01</div><b>Paste a mint</b><p>Any Solana token address. Pasting a link that contains the mint works too.</p></div>
  <div class="lg"><div class="n">02</div><b>Four sources read it</b><p>DexScreener and GeckoTerminal (market), RugCheck (security), Jupiter (exit quotes).</p></div>
  <div class="lg"><div class="n">03</div><b>Rules, not opinions</b><p>Fixed rules check market, security and exit cost. Each check shows value and status.</p></div>
  <div class="lg"><div class="n">04</div><b>Agents welcome</b><p>Same answer as JSON at /check. CORS open, no key, llms.txt included.</p></div></div></section>
 <details id="how"><summary>How the verdict works</summary><div id="howBody"><p>Loading rules...</p></div></details>
 <details id="agent"><summary>For AI agents and developers</summary><div id="agentBody"></div></details>
 <details><summary>Honest limits</summary><p>Verdicts are heuristics from public data, not financial advice or a security audit. The numbers above are usage counters held in memory and reset when the free host restarts: they are not a track record of how accurate verdicts turned out. A Jupiter quote is not proof that a sell will succeed. Sources can be late, rate-limited or wrong; when they fail the page says so instead of guessing.</p></details>
 <div class="foot">Not financial advice. Low liquidity = hard to exit.<br>
  <a href="https://github.com/TVibe-signal/signal-api" target="_blank" rel="noopener">GitHub</a>|<a href="/docs">API docs</a>|<a href="/stats">Stats JSON</a>|<a href="/health">Status</a>|<a href="/llms.txt">llms.txt</a>|<a href="https://x.com/realTVibe" target="_blank" rel="noopener">@realTVibe</a></div>
</main>
<div id="toast"></div>
<script>
var $=function(s){return document.querySelector(s)};
var esc=function(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})};
var last=null,busy=false,retryT=null,retryN=0;
var SUB='\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089';
function fUsd(n){if(n==null)return '\u2014';if(n>=1e9)return '$'+(n/1e9).toFixed(2)+'B';if(n>=1e6)return '$'+(n/1e6).toFixed(2)+'M';return '$'+Math.round(n).toLocaleString('en-US')}
function fPrice(p){if(p==null)return '\u2014';if(p>=1)return '$'+p.toLocaleString('en-US',{maximumFractionDigits:4});if(p>=0.01)return '$'+p.toFixed(5);if(p<=0)return '$0';
 var z=Math.floor(-Math.log10(p));var d=String(Math.round(p*Math.pow(10,z+4))).slice(0,4);
 if(z>=4){var zs=String(z).split('').map(function(c){return SUB[+c]}).join('');return '$0.0'+zs+d}
 return '$'+p.toFixed(z+4)}
function fPct(n){if(n==null)return '\u2014';return (n>0?'+':'')+n.toFixed(1)+'%'}
function cls(n){return n==null?'':(n>=0?'up':'dn')}
function toast(t){var e=$('#toast');e.textContent=t;e.classList.add('on');clearTimeout(toast.t);toast.t=setTimeout(function(){e.classList.remove('on')},1800)}
function copy(t,m){var done=function(){toast(m||'Copied')};
 if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(t).then(done,function(){fb(t);done()})}else{fb(t);done()}}
function fb(t){var a=document.createElement('textarea');a.value=t;a.style.position='fixed';a.style.opacity='0';document.body.appendChild(a);a.select();try{document.execCommand('copy')}catch(e){}a.remove()}
function hl(o){return JSON.stringify(o,null,2).replace(/("(?:\\.|[^"\\])*")(\s*:)?|\b(?:true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g,function(m,s,c){
 if(s)return c?'<span class="k">'+esc(s)+'</span>'+c:'<span class="s">'+esc(s)+'</span>';return '<span class="n">'+esc(m)+'</span>'})}
function getMint(t){var a=(t||'').match(/[1-9A-HJ-NP-Za-km-z]+/g)||[];for(var i=0;i<a.length;i++)if(a[i].length>=32&&a[i].length<=44)return a[i];return null}
function setMsg(t,e){var m=$('#msg');m.className=e?'err':'';m.textContent=t}
var LV={green:'#22c55e',yellow:'#fbbf24',red:'#f43f5e',gray:'#94a3b8'};
function hist(){try{return JSON.parse(localStorage.getItem('tvs_h')||'[]')}catch(e){return []}}
function addHist(j){try{var h=hist().filter(function(x){return x.mint!==j.mint});h.unshift({mint:j.mint,sym:j.symbol||j.mint.slice(0,4)+'...',lv:j.level});localStorage.setItem('tvs_h',JSON.stringify(h.slice(0,6)))}catch(e){}drawHist()}
function drawHist(){var h=hist();$('#recent').innerHTML=h.map(function(x){return '<button type="button" class="chip" data-m="'+esc(x.mint)+'"><i style="background:'+(LV[x.lv]||LV.gray)+'"></i>'+esc(x.sym)+'</button>'}).join('')}
function tile(l,v,s,c){return '<div class="tile"><span>'+l+'</span><b class="'+(c||'')+'">'+v+'</b>'+(s?'<small>'+s+'</small>':'')+'</div>'}
function secBlock(j){var s=j.security;
 if(!s)return '<h3>SECURITY (RUGCHECK)</h3><div class="note">Not checked: RugCheck did not answer. Treat security as unknown.</div>';
 var yn=function(v,bad){return v==null?['\u2014','']:(v?['ACTIVE','dn']:['Revoked','up'])};
 var ma=yn(s.mint_authority_active),fa=yn(s.freeze_authority_active);
 var h='<h3>SECURITY (RUGCHECK)</h3><div class="grid">'+tile('MINT AUTHORITY',ma[0],'can create more supply',ma[1])+tile('FREEZE AUTHORITY',fa[0],'can freeze wallets',fa[1])
  +tile('LP LOCKED',s.lp_locked_pct==null?'\u2014':s.lp_locked_pct.toFixed(0)+'%','pool cannot be pulled fast')
  +tile('TOP 10 HOLDERS',s.top10_holders_pct==null?'\u2014':s.top10_holders_pct.toFixed(1)+'%',s.holders!=null?Number(s.holders).toLocaleString()+' holders':'')+'</div>';
 if(s.rugged)h+='<div class="banner" style="background:rgba(244,63,94,.12);border-color:rgba(244,63,94,.5);color:#fda4af">RugCheck marks this token as RUGGED.</div>';
 h+='<div style="margin-top:6px">'+(s.risks&&s.risks.length?s.risks.map(function(r){return '<span class="rk '+esc(r.level)+'" title="'+esc(r.description)+'">'+esc(r.name)+'</span>'}).join(''):'<span class="rk good">No risk flags listed</span>')+'</div>';
 return h}
function exitBlock(j){var e=j.exit;
 if(!e||!e.quotes||!e.quotes.length)return '<h3>EXIT COST (JUPITER)</h3><div class="note">Not checked: '+esc((e&&e.error)||'no quote available')+'.</div>';
 return '<h3>EXIT COST (JUPITER)</h3>'+e.quotes.map(function(q){var bad=q.loss_pct>=10;return '<div class="ex"><div><b>Sell $'+q.size_usd.toLocaleString()+'</b><small>you get about $'+q.out_usd.toLocaleString()+' USDC - '+q.route_hops+' hop'+(q.route_hops===1?'':'s')+'</small></div><div class="exl '+(q.loss_pct>=30?'dn':(bad?'':'up'))+'" style="'+(bad&&q.loss_pct<30?'color:var(--y)':'')+'">'+(q.loss_pct>0?'-':'+')+Math.abs(q.loss_pct).toFixed(1)+'%</div></div>'}).join('')+'<div class="note">Quote is not proof that a sell will succeed.</div>'}
function pbar(l,t){if(!t)return '';var tot=t.buys+t.sells;if(!tot)return '';var bp=Math.round(t.buys/tot*100);
 return '<div class="pb"><div class="pl"><span>'+l+'</span><span>'+t.buys.toLocaleString()+' buys / '+t.sells.toLocaleString()+' sells</span></div><div class="bar"><i style="width:'+bp+'%"></i></div></div>'}
function render(j){
 setRhythm(j.code);var mk=j.market,d=j.data||{},L=j.level||'gray',C=2*Math.PI*52,h='';
 if(d.stale)h+='<div class="banner">Live sources are rate-limited. Showing the last known data from '+d.age_s+'s ago.</div>';
 h+='<div class="hero '+L+'"><div class="ring"><svg viewBox="0 0 120 120"><circle class="rt" cx="60" cy="60" r="52"/><circle class="rf" id="rf" cx="60" cy="60" r="52" stroke-dasharray="'+C+'" stroke-dashoffset="'+C+'" transform="rotate(-90 60 60)"/></svg><div class="rn"><b>'+(j.score==null?'?':j.score)+'</b><span>SCORE</span></div></div>';
 h+='<div><div class="vk">VERDICT</div><div class="vt">'+esc(j.verdict)+'</div><div class="va">'+esc(j.action)+'</div>';
 if(j.symbol||j.name)h+='<div class="tok">'+esc(j.symbol||'')+(j.name?' - '+esc(j.name):'')+'</div>';
 h+='</div></div><p class="reason">'+esc(j.reason)+'</p>';
 h+='<div class="meta">'+(d.source?'Source: '+esc(d.source)+' - ':'')+(d.stale?'stale ':(d.cached?'cached ':'live '))+'- updated '+(d.age_s||0)+'s ago ('+esc(d.fetched_at||'')+')</div>';
 if(j.unknowns&&j.unknowns.length&&mk)h+='<div class="banner">Unknowns: '+esc(j.unknowns.join(', '))+'. Do not size a trade on this alone.</div>';
 if(j.code==='unknown'||!mk){
  h+='<h3>WHAT WE TRIED</h3>'+(d.sources_tried||[]).map(function(s){return '<div class="ck '+(s.ok?'pass':'fail')+'"><div class="ic">'+(s.ok?'\u2713':'\u2715')+'</div><div style="flex:1"><div class="t"><span>'+esc(s.name)+'</span><em>'+(s.ok?s.pairs+' pairs':esc(s.error))+'</em></div></div></div>'}).join('');
  if(j.code==='unknown')h+='<div class="row"><button class="btn pri" data-act="retry">Retry now</button><button class="btn" data-act="json">Copy JSON for agent</button></div><div class="meta" id="cd"></div>';
  else h+='<div class="row"><button class="btn" data-act="verdict">Copy verdict</button><button class="btn" data-act="json">Copy JSON for agent</button></div>';
 }else{
  var c=mk.price_change_pct||{},pc=c.h24;
  h+='<div class="grid">'+tile('PRICE',fPrice(mk.price_usd),'24h <span class="'+cls(pc)+'">'+fPct(pc)+'</span>')
   +tile('LIQUIDITY',fUsd(mk.liquidity_usd),mk.pairs_count>1?'all pools '+fUsd(mk.liquidity_all_pairs_usd):'1 pool')
   +tile('VOLUME 24H',fUsd(mk.volume_24h_usd),mk.volume_1h_usd!=null?'1h '+fUsd(mk.volume_1h_usd):'')
   +tile('AGE / DEX',esc(mk.age_label||'\u2014'),esc(mk.dex||'\u2014'))
   +tile('MARKET CAP',fUsd(mk.market_cap_usd!=null?mk.market_cap_usd:mk.fdv_usd),'FDV '+fUsd(mk.fdv_usd))
   +tile('VOL / LIQ',mk.vol_liq_ratio==null?'\u2014':mk.vol_liq_ratio.toFixed(2)+'x','daily turnover')+'</div>';
  h+='<div class="chg">'+[['5M',c.m5],['1H',c.h1],['6H',c.h6],['24H',c.h24]].map(function(x){return '<div><span>'+x[0]+'</span><b class="'+cls(x[1])+'">'+fPct(x[1])+'</b></div>'}).join('')+'</div>';
  h+=pbar('Last 1h',mk.txns&&mk.txns.h1)+pbar('Last 24h',mk.txns&&mk.txns.h24);
  h+=secBlock(j)+exitBlock(j);
  h+='<h3>WHY THIS VERDICT</h3>'+(j.checks||[]).map(function(k){return '<div class="ck '+k.status+'"><div class="ic">'+({pass:'\u2713',warn:'!',fail:'\u2715',info:'i'}[k.status])+'</div><div style="flex:1"><div class="t"><span>'+esc(k.label)+'</span><em>'+esc(k.value)+'</em></div><small>'+esc(k.note)+'</small></div></div>'}).join('');
  h+='<div class="row"><button class="btn pri" data-act="verdict">Copy verdict</button><button class="btn" data-act="json">Copy JSON for agent</button><button class="btn" data-act="share">Share link</button>'+(mk.pair_url?'<a class="btn" href="'+esc(mk.pair_url)+'" target="_blank" rel="noopener">Open chart</a>':'<span></span>')+'</div>';
 }
 h+='<details style="margin-top:14px"><summary>FOR AGENT - Raw JSON</summary><pre>'+hl(j)+'</pre></details>';
 $('#out').innerHTML=h;
 requestAnimationFrame(function(){requestAnimationFrame(function(){var r=$('#rf');if(r&&j.score!=null)r.style.strokeDashoffset=C*(1-j.score/100)})});
}
function stopRetry(){clearTimeout(retryT);retryT=null}
function countdown(s){var e=$('#cd');if(!e)return;if(s<=0){e.textContent='Retrying...';return}e.textContent='Auto retry in '+s+'s ('+retryN+'/2)';retryT=setTimeout(function(){countdown(s-1)},1000)}
async function run(raw,auto){
 if(busy)return;var m=getMint(raw);
 if(!m){setMsg("That does not look like a Solana mint address (32-44 letters and numbers).",true);return}
 stopRetry();if(!auto)retryN=0;busy=true;$('#btn').disabled=true;$('#btn').textContent='CHECKING...';
 setMsg('Reading market data...');$('#out').innerHTML='<div class="sk"></div><div class="sk" style="width:70%"></div><div class="sk" style="width:85%"></div>';
 try{
  var r=await fetch('/check?mint='+encodeURIComponent(m));var j=await r.json();
  if(!j.verdict){$('#out').innerHTML='';setMsg(j.error||'Something went wrong. Try again.',true);if(j.retry_after_s){}}
  else{last=j;setMsg('');render(j);try{history.replaceState(null,'','?mint='+m)}catch(e){}
   if(j.code!=='unknown')addHist(j);
   else if(retryN<2){retryN++;var s=j.retry_after_s||8;countdown(s);retryT=setTimeout(function(){retryT=null;run(m,true)},s*1000)}}
 }catch(e){$('#out').innerHTML='';setMsg('Network error. Check your connection and try again.',true)}
 busy=false;$('#btn').disabled=false;$('#btn').textContent='CHECK';
}
document.addEventListener('click',function(e){
 var t=e.target.closest('[data-act],[data-m]');if(!t)return;
 if(t.dataset.m){$('#mint').value=t.dataset.m;$('#chk').scrollIntoView({behavior:'smooth'});run(t.dataset.m);return}
 var a=t.dataset.act;if(!last)return;
 if(a==='verdict')copy(last.summary,'Verdict copied');
 else if(a==='json')copy(JSON.stringify(last),'JSON copied for agent');
 else if(a==='share')copy(location.origin+'/?mint='+last.mint,'Share link copied');
 else if(a==='retry'){retryN=0;run(last.mint)}
});
$('#btn').addEventListener('click',function(){run($('#mint').value)});
$('#mint').addEventListener('keydown',function(e){if(e.key==='Enter')run(this.value)});
$('#pasteBtn').addEventListener('click',async function(){
 try{var t=await navigator.clipboard.readText();$('#mint').value=t.trim();run(t)}catch(e){$('#mint').focus();toast('Long-press the box and paste')}});
function showRules(j){
  $('#howBody').innerHTML='<p>Verdicts come from fixed rules. Details are private to prevent gaming.</p>'
}
function showAgent(){var o=location.origin;
 var prompt='Before you buy, sell or mention a Solana token, call GET '+o+'/check?mint=<MINT>. Read verdict, code, score, reason and checks. If code is "unknown" wait retry_after_s and retry. This is a heuristic, not financial advice.';
 $('#agentBody').innerHTML='<p>One request, one JSON verdict. No API key. CORS is open. Add <code>&deep=0</code> for market data only (faster).</p><pre>curl "'+esc(o)+'/check?mint=&lt;MINT&gt;"</pre>'
  +'<table><tr><td><code>verdict</code> / <code>code</code></td><td>SELL, WATCH, HOLD / BUY, UNKNOWN, SKIP</td></tr><tr><td><code>level</code></td><td>red, yellow, green, gray</td></tr><tr><td><code>score</code></td><td>0-100 health score</td></tr><tr><td><code>summary</code></td><td>one line for LLMs</td></tr><tr><td><code>market</code></td><td>price, liquidity, volume, age, txns</td></tr><tr><td><code>checks[]</code></td><td>every check with value and status</td></tr><tr><td><code>security</code></td><td>RugCheck: authorities, LP lock, holders, risks</td></tr><tr><td><code>exit</code></td><td>Jupiter sell quotes ($100, $1,000)</td></tr><tr><td><code>unknowns[]</code></td><td>missing data. Non-empty = do not size</td></tr><tr><td><code>data</code></td><td>source, age, stale, sources_tried</td></tr></table>'
  +'<p>HTTP 503 = no data right now, retry after the <code>Retry-After</code> header. HTTP 429 = rate limited ('+'40 per minute per IP).</p><button class="btn pri" id="cp">Copy agent prompt</button><div style="height:12px"></div>';
 $('#cp').onclick=function(){copy(prompt,'Agent prompt copied')}}

async function boot(){
 drawHist();showAgent();loadStats();setInterval(loadStats,15000);
 try{var h=await (await fetch('/health')).json();var b=$('#badge');b.className='badge '+(h.status==='ok'?'ok':'bad');$('#btxt').textContent=(h.status==='ok'?'LIVE':'DEGRADED')+' - '+h.version}catch(e){}
 try{showRules(await (await fetch('/rules')).json())}catch(e){$('#howBody').innerHTML='<p>Verdicts come from fixed rules. Details are private.</p>'}
 var q=new URLSearchParams(location.search).get('mint');if(q){$('#mint').value=q;run(q)}
}
var cv=$('#ecg'),cx=cv.getContext('2d'),mode='idle',W=0,H=0,RM=window.matchMedia&&matchMedia('(prefers-reduced-motion:reduce)').matches;
var CLR={idle:'#22c55e',hold:'#22c55e',watch:'#fbbf24',sell:'#f43f5e',unknown:'#94a3b8',skip:'#94a3b8'},LB={idle:'STANDBY',hold:'STEADY - HOLD / BUY',watch:'IRREGULAR - WATCH',sell:'FLATLINE - SELL',unknown:'NO SIGNAL - UNKNOWN',skip:'N/A'};
function setRhythm(c){mode=CLR[c]?c:'idle';var l=$('#rl');l.textContent=LB[mode];l.style.color=CLR[mode];if(RM)draw(0)}
function sz(){var r=cv.getBoundingClientRect(),d=window.devicePixelRatio||1;W=r.width;H=r.height;cv.width=W*d;cv.height=H*d;cx.setTransform(d,0,0,d,0,0)}
function beat(p){p=p-Math.floor(p);if(p>.1&&p<.18)return .14*Math.sin((p-.1)/.08*Math.PI);if(p>=.28&&p<.31)return -.18*(p-.28)/.03;if(p>=.31&&p<.34)return -.18+1.18*(p-.31)/.03;if(p>=.34&&p<.38)return 1-1.4*(p-.34)/.04;if(p>=.38&&p<.41)return -.4+.4*(p-.38)/.03;if(p>.52&&p<.7)return .24*Math.sin((p-.52)/.18*Math.PI);return 0}
function draw(ts){var m=mode,c=CLR[m],s=ts/1000*(m==='watch'?150:110);cx.clearRect(0,0,W,H);cx.lineWidth=2.4;cx.strokeStyle=c;cx.shadowColor=c;cx.shadowBlur=14;cx.setLineDash(m==='unknown'||m==='skip'?[6,9]:[]);cx.beginPath();
 for(var x=0;x<=W;x+=2){var y=0,u=x+s;if(m==='idle'||m==='hold')y=beat(u/(m==='hold'?230:340));else if(m==='watch')y=beat(u/200+.35*Math.sin(u/130))*(.55+.45*Math.sin(u/90));else if(m==='sell')y=.015*Math.sin(x*.9+ts/50);
  var yy=H/2-y*H*.36;x?cx.lineTo(x,yy):cx.moveTo(x,yy)}
 cx.stroke();if(!RM)requestAnimationFrame(draw)}
sz();addEventListener('resize',function(){sz();if(RM)draw(0)});requestAnimationFrame(draw);
function ago(t){var s=Math.max(0,Math.floor(Date.now()/1000-t));return s<60?s+'s':s<3600?Math.floor(s/60)+'m':Math.floor(s/3600)+'h'}
function upt(s){var h=Math.floor(s/3600),m=Math.floor(s%3600/60);return h>=24?Math.floor(h/24)+'d '+h%24+'h':h+'h '+m+'m'}
async function loadStats(){try{var j=await (await fetch('/stats')).json(),c=j.verdicts||{},n=j.checks,V=[['sell','SELL','#f43f5e'],['watch','WATCH','#fbbf24'],['hold','HOLD','#22c55e'],['unknown','UNKNOWN','#94a3b8']];
 $('#stats').innerHTML=[['CHECKS',n.toLocaleString()],['UNIQUE TOKENS',j.unique_tokens.toLocaleString()],['UPTIME',upt(j.uptime_s)],['MEDIAN SPEED',j.median_ms==null?'\u2014':j.median_ms+' ms'],['CACHE HIT',j.cache_hit_pct==null?'\u2014':j.cache_hit_pct+'%']].map(function(x){return '<div class="sc"><span>'+x[0]+'</span><b>'+esc(x[1])+'</b></div>'}).join('');
 $('#mix').innerHTML=n?V.map(function(v){return '<i style="flex:'+(c[v[0]]||0)+';background:'+v[2]+'"></i>'}).join(''):'';
 $('#mixlg').innerHTML=n?V.map(function(v){return '<span><i style="background:'+v[2]+'"></i>'+v[1]+' '+(c[v[0]]||0)+' ('+Math.round((c[v[0]]||0)/n*100)+'%)</span>'}).join(''):'No checks yet since the last restart. Be the first.';
 $('#srcs').innerHTML=Object.keys(j.sources).map(function(k){var s=j.sources[k];return '<div class="tp"><i style="background:'+(s.ok===false?'#fbbf24':s.ok?'#22c55e':'#94a3b8')+'"></i><b>'+k+'</b><span>'+(s.success_pct==null?'no calls yet':s.success_pct+'% ('+s.ok_n+'/'+(s.ok_n+s.fail_n)+')')+'</span><em>'+(s.last_error?esc(s.last_error):'')+'</em></div>'}).join('');
 $('#tape').innerHTML=j.tape.length?j.tape.map(function(t){return '<div class="tp" data-m="'+esc(t.mint)+'"><i style="background:'+(LV[{sell:'red',watch:'yellow',hold:'green'}[t.code]||'gray'])+'"></i><b>'+esc(t.symbol||t.mint.slice(0,4)+'...'+t.mint.slice(-4))+'</b><span>'+esc(t.verdict)+(t.score!=null?' - '+t.score:'')+'</span><em>'+ago(t.t)+'</em></div>'}).join(''):'<div class="note">No checks yet.</div>'}catch(e){}}
boot();
</script></body></html>""".replace("__V__", VERSION)

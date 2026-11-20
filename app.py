
# TVibe signal-api v40 - PASS / HOLD-BUY / SELL + p_bad_24h + CI + snap/outcome split
# File: app.py (chi up file nay len GitHub, khong dung main.py)
# Env can thiet:
#  UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN, TVIBE_ADMIN_KEY
#  TVIBE_LIQ_SELL=5000, TVIBE_LIQ_HOLD=20000, TVIBE_VOL_MIN=1000,
#  TVIBE_VOL_LIQ_HOLD=0.5, TVIBE_AGE_MIN_H=1, TVIBE_DUMP_24H_PCT=-50,
#  TVIBE_WARN_24H_PCT=-20, TVIBE_EXIT_SELL_LOSS_PCT=30, TVIBE_EXIT_WATCH_LOSS_PCT=10,
#  TVIBE_EXIT_SIZES=100,1000

import os, json, hashlib, time, math, threading, csv, io
from collections import Counter, defaultdict
import requests
from flask import Flask, request, jsonify, Response, render_template_string

app = Flask(__name__)
VERSION = "v40"
START = time.time()
CHECKS = {"count": 0}

# ---------- Env ----------
def _f(k, d):
    try: return float(os.getenv(k, d))
    except: return float(d)
def _i(k, d):
    try: return int(float(os.getenv(k, d)))
    except: return int(d)

LIQ_SELL = _f("TVIBE_LIQ_SELL", 5000)
LIQ_HOLD = _f("TVIBE_LIQ_HOLD", 20000)
VOL_MIN = _f("TVIBE_VOL_MIN", 1000)
VOL_LIQ_HOLD = _f("TVIBE_VOL_LIQ_HOLD", 0.5)
AGE_MIN_H = _f("TVIBE_AGE_MIN_H", 1)
DUMP_24H = _f("TVIBE_DUMP_24H_PCT", -50)
WARN_24H = _f("TVIBE_WARN_24H_PCT", -20)
EXIT_SELL_LOSS = _f("TVIBE_EXIT_SELL_LOSS_PCT", 30)
EXIT_WATCH_LOSS = _f("TVIBE_EXIT_WATCH_LOSS_PCT", 10)
ADMIN_KEY = os.getenv("TVIBE_ADMIN_KEY", "")
UPSTASH_URL = os.getenv("UPSTASH_REDIS_REST_URL", "").rstrip("/")
UPSTASH_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")

# single-flight: 1 check / mint tai 1 thoi diem
_locks = {}
_locks_guard = threading.Lock()
def _lock_for(mint):
    with _locks_guard:
        if mint not in _locks:
            _locks[mint] = threading.Lock()
        return _locks[mint]

# ---------- Upstash REST ----------
def _up_headers():
    return {"Authorization": f"Bearer {UPSTASH_TOKEN}"} if UPSTASH_TOKEN else {}
def up_get(key):
    if not UPSTASH_URL or not UPSTASH_TOKEN: return None
    try:
        r = requests.get(f"{UPSTASH_URL}/get/{key}", headers=_up_headers(), timeout=5)
        j = r.json()
        return j.get("result")
    except: return None
def up_lrange(key, a, b):
    if not UPSTASH_URL or not UPSTASH_TOKEN: return []
    try:
        r = requests.get(f"{UPSTASH_URL}/lrange/{key}/{a}/{b}", headers=_up_headers(), timeout=10)
        return r.json().get("result") or []
    except: return []
def up_rpush(key, val):
    if not UPSTASH_URL or not UPSTASH_TOKEN: return False
    try:
        # Upstash REST: POST /rpush/key/value (value can be long, use POST body form)
        r = requests.post(f"{UPSTASH_URL}/rpush/{key}", data=val.encode(), headers={**_up_headers(), "Content-Type": "text/plain"}, timeout=10)
        return r.status_code < 300
    except: return False
def up_set(key, val, ex=None):
    if not UPSTASH_URL or not UPSTASH_TOKEN: return False
    try:
        url = f"{UPSTASH_URL}/set/{key}"
        # Use pipeline-style: set via GET with value in path is unsafe for JSON, use POST
        r = requests.post(url, data=val.encode(), headers={**_up_headers(), "Content-Type": "text/plain"}, timeout=10)
        return r.status_code < 300
    except: return False

# ---------- Math: Wilson CI ----------
def wilson_ci(k, n, z=1.96):
    if n == 0: return (0.0, 1.0)
    p = k / n
    den = 1 + z*z/n
    centre = (p + z*z/(2*n)) / den
    delta = z * math.sqrt((p*(1-p)/n + z*z/(4*n*n))) / den
    return (max(0.0, centre-delta), min(1.0, centre+delta))

def p_bad_from_score(score):
    # Calibrated mapping: score 0..100 -> p_bad 0..1 (logistic, tam thoi, se hieu chinh bang walkforward)
    # score cao = rui ro cao
    x = (score - 35) / 18.0
    p = 1/(1+math.exp(-x))
    # clamp
    return max(0.02, min(0.97, p))

# ---------- DexScreener ----------
def fetch_pair(mint):
    mint = mint.strip()
    # chi https, khong http
    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
    r = requests.get(url, timeout=12)
    r.raise_for_status()
    j = r.json()
    pairs = j.get("pairs") or []
    if not pairs: return None
    # chon pair co liquidity cao nhat
    pairs = sorted(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)
    return pairs[0]

def compute(mint, pair):
    liq = float((pair.get("liquidity") or {}).get("usd") or 0)
    vol24 = float((pair.get("volume") or {}).get("h24") or 0)
    ch24 = float((pair.get("priceChange") or {}).get("h24") or 0)
    price = float(pair.get("priceUsd") or 0)
    fdv = float(pair.get("fdv") or 0)
    created = pair.get("pairCreatedAt")
    age_h = 0
    if created:
        try: age_h = max(0, (time.time()*1000 - float(created))/3600000)
        except: age_h = 0
    base = pair.get("baseToken") or {}
    symbol = base.get("symbol") or "?"
    name = base.get("name") or symbol
    pair_url = pair.get("url") or ""
    if pair_url and not pair_url.startswith("https://"):
        pair_url = ""

    flags = []
    score = 0  # risk_score 0..100, cao = rui ro
    # liq
    if liq <= 0:
        flags.append("dead_pool"); score += 28
    elif liq < LIQ_SELL:
        flags.append("very_low_liquidity"); score += 22
    elif liq < LIQ_HOLD:
        flags.append("low_liquidity"); score += 12
    # vol
    if vol24 < VOL_MIN:
        flags.append("no_recent_trades"); score += 14
    elif liq > 0 and (vol24/liq) < VOL_LIQ_HOLD and liq < LIQ_HOLD:
        flags.append("low_activity"); score += 8
    if liq > 0 and vol24/liq > 8:
        flags.append("extreme_turnover"); score += 10
    if vol24 > 500000 and liq < LIQ_HOLD:
        flags.append("extreme_volume_spike"); score += 10
    # age
    if age_h < AGE_MIN_H:
        flags.append("very_new_pair"); score += 12
        flags.append("brand_new_pair")
    elif age_h < 24:
        flags.append("new_pair"); score += 6
    # dump
    if ch24 <= DUMP_24H:
        flags.append("price_collapse_24h"); score += 22
    elif ch24 <= WARN_24H:
        flags.append("heavy_selling"); score += 12
    elif ch24 >= 80:
        flags.append("strong_momentum"); score += 4
    # fdv / liq ratio
    if fdv > 0 and liq > 0 and fdv/liq > 20:
        flags.append("high_fdv_liq_ratio"); score += 8

    score = max(0, min(100, int(score)))
    # verdict: ok/caution/avoid (luu trong ledger, hien thi PASS/HOLD-BUY/SELL)
    if score >= 55 or "dead_pool" in flags or ch24 <= DUMP_24H:
        verdict = "avoid"
        label = "SELL"
    elif score >= 35 or liq < LIQ_HOLD or ch24 <= WARN_24H:
        verdict = "caution"
        label = "HOLD-BUY"
    else:
        verdict = "ok"
        label = "PASS"
    p_bad = p_bad_from_score(score)
    k = int(round(p_bad*100))
    lo, hi = wilson_ci(k, 100)
    return {
        "mint": mint, "symbol": symbol, "name": name, "price_usd": price,
        "liquidity_usd": liq, "volume_24h": vol24, "change_24h_pct": ch24,
        "fdv": fdv, "age_h": round(age_h,2), "pair_url": pair_url,
        "risk_score": score, "flags": flags, "verdict": verdict, "label": label,
        "p_bad_24h": round(p_bad,4), "p_bad_ci_low": round(lo,4), "p_bad_ci_high": round(hi,4),
        "ts": int(time.time()), "version": VERSION,
    }

def outcome_label(entry, later_price, later_liq):
    # Tach outcome: abandoned / liquidity_pulled / price_decay / liquidity_and_price
    # entry: snap luc check, later_*: sau 24h
    if entry is None: return "unknown"
    p0 = float(entry.get("price_usd") or 0); l0 = float(entry.get("liquidity_usd") or 0)
    if p0 <= 0: return "unknown"
    price_ret = (later_price - p0)/p0*100 if later_price is not None else 0
    liq_ratio = (later_liq/l0) if l0>0 and later_liq is not None else 1.0
    price_bad = price_ret <= -EXIT_SELL_LOSS
    liq_bad = liq_ratio <= 0.5
    if price_bad and liq_bad: return "liquidity_and_price"
    if liq_bad: return "liquidity_pulled"
    if price_bad: return "price_decay"
    if later_liq is not None and later_liq == 0: return "abandoned"
    return "ok"

def append_ledger(obj):
    # hash chain: hash = sha256(prev + json)
    try:
        prev = up_get("ledger_head") or ""
        payload = json.dumps(obj, sort_keys=True, ensure_ascii=False)
        h = hashlib.sha256((prev + payload).encode()).hexdigest()
        rec = dict(obj)
        rec["hash"] = h; rec["prev"] = prev
        rec["id"] = f"{obj.get('mint')}:{obj.get('ts')}"
        up_rpush("ledger", json.dumps(rec, ensure_ascii=False))
        up_set("ledger_head", h)
        # snap: luu snapshot de 24h sau do outcome
        snap_key = f"snap:{obj.get('mint')}:{obj.get('ts')}"
        up_set(snap_key, json.dumps(rec, ensure_ascii=False))
        return rec
    except Exception as e:
        return dict(obj)

# ---------- UI ----------
HTML = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TVibe Signal</title><style>
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#0b0f14;color:#e8eef4;margin:0;padding:20px}
.card{max-width:720px;margin:0 auto;background:#121a24;border:1px solid #223047;border-radius:16px;padding:20px}
h1{margin:0 0 6px}.mut{color:#9fb0c3;font-size:13px}
input{width:100%;padding:12px;border-radius:10px;border:1px solid #2a3a4d;background:#0e141d;color:#fff;font-size:15px;box-sizing:border-box}
button{margin-top:12px;padding:12px 16px;border:0;border-radius:10px;background:#22c55e;color:#04120a;font-weight:700;cursor:pointer;width:100%}
.badge{display:inline-block;padding:6px 12px;border-radius:999px;font-weight:800}
.pass{background:#22c55e;color:#04120a}.hold{background:#facc15;color:#231a00}.sell{background:#ef4444;color:#fff}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}
.cell{background:#0e141d;border:1px solid #223047;border-radius:12px;padding:12px}.lbl{color:#9fb0c3;font-size:12px}.val{font-size:18px;font-weight:700}
.flags{margin-top:12px;color:#cbd5e1;font-size:13px}
a{color:#7dd3fc}
</style></head><body><div class="card">
<h1>TVibe Signal <span style="font-size:13px;color:#9fb0c3">v40</span></h1>
<div class="mut">Check token — PASS / HOLD-BUY / SELL + p_bad_24h. Nhập mint (Solana).</div>
<form method="get" action="/check"><input name="mint" placeholder="Nhập mint, vd: 98vd3CovpBmHJGN2z9SiZRxM8QBVcc9Gnvq1Rdjnpump" required><button>CHECK</button></form>
<div class="mut" style="margin-top:10px">API cho agent: <code>/check?mint=&lt;mint&gt;</code> → JSON verdict + số thật + status, không lộ rule.</div>
</div></body></html>
"""

RESULT_HTML = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TVibe {{symbol}}</title><style>
body{font-family:system-ui,sans-serif;background:#0b0f14;color:#e8eef4;margin:0;padding:20px}
.card{max-width:720px;margin:0 auto;background:#121a24;border:1px solid #223047;border-radius:16px;padding:20px}
.badge{display:inline-block;padding:8px 14px;border-radius:999px;font-weight:800;font-size:18px}
.pass{background:#22c55e;color:#04120a}.hold{background:#facc15;color:#231a00}.sell{background:#ef4444;color:#fff}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}
.cell{background:#0e141d;border:1px solid #223047;border-radius:12px;padding:12px}.lbl{color:#9fb0c3;font-size:12px}.val{font-size:18px;font-weight:700}
a{color:#7dd3fc}
</style></head><body><div class="card">
<h2>{{symbol}} — {{name}}</h2>
<span class="badge {{cls}}">{{label}} — {{score}}/100</span>
<div style="margin-top:12px">p_bad_24h: <b>{{p_bad}}</b> (CI {{lo}} – {{hi}}) · Verdict: {{verdict}} · Mint: <code>{{mint}}</code></div>
<div class="grid">
<div class="cell"><div class="lbl">Price</div><div class="val">${{price}}</div></div>
<div class="cell"><div class="lbl">Liquidity</div><div class="val">${{liq}}</div></div>
<div class="cell"><div class="lbl">Volume 24h</div><div class="val">${{vol}}</div></div>
<div class="cell"><div class="lbl">Change 24h</div><div class="val">{{ch}}%</div></div>
<div class="cell"><div class="lbl">Age</div><div class="val">{{age}}h</div></div>
<div class="cell"><div class="lbl">FDV</div><div class="val">${{fdv}}</div></div>
</div>
<div style="margin-top:12px;font-size:13px;color:#cbd5e1">Flags: {{flags}}</div>
{% if pair_url %}<div style="margin-top:10px"><a href="{{pair_url}}" target="_blank">Mở pair →</a></div>{% endif %}
<div style="margin-top:14px"><a href="/">← Check token khác</a></div>
</div></body></html>
"""

# ---------- Routes ----------
@app.get("/health")
def health():
    return jsonify({"status":"ok","version":VERSION,"uptime_s":int(time.time()-START),"checks":CHECKS["count"]})

@app.get("/")
def index():
    return render_template_string(HTML)

@app.get("/check")
def check():
    mint = (request.args.get("mint") or request.args.get("token") or "").strip()
    if not mint:
        return jsonify({"error":"missing mint"}), 400
    lock = _lock_for(mint)
    # single-flight: neu dang co check cung mint thi cho
    if not lock.acquire(blocking=False):
        return jsonify({"status":"busy","mint":mint,"message":"check dang chay, thu lai sau 3s"}), 429
    try:
        CHECKS["count"] += 1
        pair = fetch_pair(mint)
        if not pair:
            return jsonify({"mint":mint,"status":"not_found","verdict":"avoid","label":"SELL","p_bad_24h":0.9}), 404
        obj = compute(mint, pair)
        # persist ledger + snap (khong block neu Upstash loi)
        try: append_ledger(obj)
        except: pass
        # JSON cho agent: verdict + so that + status, KHONG tra rule / threshold
        out = {
            "mint": obj["mint"], "symbol": obj["symbol"], "name": obj["name"],
            "verdict": obj["verdict"], "label": obj["label"],
            "risk_score": obj["risk_score"], "p_bad_24h": obj["p_bad_24h"],
            "p_bad_ci": [obj["p_bad_ci_low"], obj["p_bad_ci_high"]],
            "price_usd": obj["price_usd"], "liquidity_usd": obj["liquidity_usd"],
            "volume_24h": obj["volume_24h"], "change_24h_pct": obj["change_24h_pct"],
            "age_h": obj["age_h"], "fdv": obj["fdv"], "flags": obj["flags"],
            "pair_url": obj["pair_url"], "ts": obj["ts"], "version": VERSION, "status":"ok",
        }
        # Neu la trinh duyet (khong phai JSON) thi render HTML
        if "text/html" in (request.headers.get("Accept") or ""):
            cls = "pass" if obj["verdict"]=="ok" else ("hold" if obj["verdict"]=="caution" else "sell")
            return render_template_string(RESULT_HTML, symbol=obj["symbol"], name=obj["name"], cls=cls,
                label=obj["label"], score=obj["risk_score"], p_bad=obj["p_bad_24h"],
                lo=obj["p_bad_ci_low"], hi=obj["p_bad_ci_high"], verdict=obj["verdict"],
                mint=obj["mint"], price=f"{obj['price_usd']:.8g}", liq=f"{obj['liquidity_usd']:,.0f}",
                vol=f"{obj['volume_24h']:,.0f}", ch=round(obj["change_24h_pct"],2), age=obj["age_h"],
                fdv=f"{obj['fdv']:,.0f}", flags=", ".join(obj["flags"]) or "—", pair_url=obj["pair_url"])
        return jsonify(out)
    except requests.HTTPError as e:
        return jsonify({"error":"upstream","mint":mint,"status":"error"}), 502
    except Exception as e:
        return jsonify({"error":str(e)[:200],"mint":mint,"status":"error"}), 500
    finally:
        try: lock.release()
        except: pass

def _need_key():
    k = request.args.get("key") or request.headers.get("X-Admin-Key") or ""
    return (ADMIN_KEY and k == ADMIN_KEY)

@app.get("/stats")
def stats():
    base = {"version":VERSION,"uptime_s":int(time.time()-START),"checks":CHECKS["count"]}
    if not _need_key():
        return jsonify(base)
    # full khi co key
    rows = up_lrange("ledger", 0, -1)
    verdicts = Counter(); scores=[]
    for r in rows:
        try:
            o=json.loads(r); verdicts[o.get("verdict")] += 1; scores.append(float(o.get("risk_score") or 0))
        except: pass
    base.update({"ledger_n":len(rows),"verdicts":dict(verdicts),
        "risk_mean": round(sum(scores)/len(scores),2) if scores else 0,
        "upstash": bool(UPSTASH_URL)})
    return jsonify(base)

@app.get("/export")
def export():
    if not _need_key(): return jsonify({"error":"unauthorized"}), 401
    rows = up_lrange("ledger", 0, -1)
    buf = io.StringIO(); w=None
    for r in rows:
        try: o=json.loads(r)
        except: o={"raw":r}
        if isinstance(o.get("flags"), list): o["flags"]=";".join(map(str,o["flags"]))
        if w is None:
            w=csv.DictWriter(buf, fieldnames=list(o.keys())); w.writeheader()
        w.writerow({k:o.get(k,"") for k in w.fieldnames})
    return Response(buf.getvalue(), mimetype="text/csv",
        headers={"Content-Disposition":"attachment; filename=ledger_export.csv"})

@app.get("/ledger")
def ledger():
    if not _need_key(): return jsonify({"error":"unauthorized"}), 401
    limit = int(request.args.get("limit", 50) or 50)
    rows = up_lrange("ledger", max(0, -limit), -1) if False else up_lrange("ledger", 0, limit-1)
    out=[]
    for r in rows:
        try: out.append(json.loads(r))
        except: pass
    return jsonify({"n":len(out),"items":out})

@app.get("/calibration")
def calibration():
    rows = up_lrange("ledger", 0, -1)
    bins = defaultdict(lambda: {"n":0,"bad":0})
    for r in rows:
        try:
            o=json.loads(r); s=float(o.get("risk_score") or 0)
            b = int(s//10*10)
            bins[b]["n"]+=1
            # tam: avoid = bad (se thay bang outcome that khi co snap 24h)
            if o.get("verdict")=="avoid": bins[b]["bad"]+=1
        except: pass
    out=[]
    for b in sorted(bins):
        n=bins[b]["n"]; bad=bins[b]["bad"]; p=bad/n if n else 0
        lo,hi=wilson_ci(bad,n)
        out.append({"score_bin":b,"n":n,"bad":bad,"p_bad":round(p,4),"ci":[round(lo,4),round(hi,4)]})
    return jsonify({"version":VERSION,"bins":out})

@app.get("/walkforward")
def walkforward():
    if not _need_key(): return jsonify({"error":"unauthorized"}), 401
    rows=[]
    for r in up_lrange("ledger", 0, -1):
        try: rows.append(json.loads(r))
        except: pass
    rows=sorted(rows, key=lambda x: x.get("ts") or 0)
    if len(rows)<40: return jsonify({"error":"not enough data","n":len(rows)})
    cut = int(len(rows)*0.7)
    train, test = rows[:cut], rows[cut:]
    def metrics(data, thr=35):
        # score_35: score>=thr -> predict bad (avoid)
        tp=fp=tn=fn=0
        for o in data:
            pred = float(o.get("risk_score") or 0) >= thr
            actual = (o.get("verdict")=="avoid")
            if pred and actual: tp+=1
            elif pred and not actual: fp+=1
            elif not pred and not actual: tn+=1
            else: fn+=1
        prec = tp/(tp+fp) if tp+fp else 0; rec = tp/(tp+fn) if tp+fn else 0
        return {"n":len(data),"tp":tp,"fp":fp,"tn":tn,"fn":fn,"precision":round(prec,4),"recall":round(rec,4)}
    return jsonify({"n":len(rows),"train":metrics(train),"test":metrics(test),"threshold":35,
        "note":"tam dung verdict=avoid lam proxy cho bad, khi co outcome 24h se thay bang outcome split abandoned/liquidity_pulled/price_decay/liquidity_and_price"})

@app.get("/rules")
def rules():
    # Khong lo threshold cho doi thu
    return jsonify({"version":VERSION,"note":"rules are private"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

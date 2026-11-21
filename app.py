"""app.py — TVibe Signal entrypoint for Render (uvicorn app:app).

Clean Merged File 1+2 (filtered): Loader + PRO V43 Premium only. Kept = core/features/extensions + patch_live_fix + PRO. Filtered = patch_stats_fix, patch_p0, /holders, /check_pro, /grade (dup of /pro_json). Loader + PRO V43 Premium inline. Upload ONLY this file as app.py. Loads the full stack into one shared namespace:
  core_final → features → extensions → optional patches

Do NOT use the old standalone "cute" app body here — that removed /omni and track-record.
"""
from __future__ import annotations

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

def _exec_file(path: str, g: dict, label: str) -> None:
    if not os.path.isfile(path):
        print(f"[loader] skip {label}: missing {os.path.basename(path)}")
        return
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    try:
        exec(compile(src, path, "exec"), g, g)
        print(f"[loader] {label} loaded ({os.path.basename(path)})")
    except Exception as e:
        print(f"[loader] {label} FAILED: {e}")
        traceback.print_exc()
        raise

# Mark that a real entrypoint is loading (avoids core.py shim importing us back)
sys.modules.setdefault("main", sys.modules[__name__])

# 1) Real core (full ~340KB engine lives in core_final.py)
_core_path = os.path.join(ROOT, "core_final.py")
if not os.path.isfile(_core_path):
    # fallback: some deploys still ship monolithic core.py
    _core_path = os.path.join(ROOT, "core.py")

g: dict = {"__name__": "__main__", "__file__": os.path.join(ROOT, "app.py")}
_exec_file(_core_path, g, "core")

# 2) Feature layers
_exec_file(os.path.join(ROOT, "features.py"), g, "features")

# 3) Extensions: /omni, MCP, stats parts, ops, SI…
_exec_file(os.path.join(ROOT, "extensions.py"), g, "extensions")

# 4) Optional patches (never fail boot if missing)
for mod_name, label in (
    ("patch_live_fix", "patch_live_fix"),
):
    try:
        mod = __import__(mod_name)
        if hasattr(mod, "apply"):
            mod.apply(g)
            print(f"[loader] {label} applied")
        else:
            print(f"[loader] {label} imported (no apply())")
    except Exception as e:
        print(f"[loader] {label} NOT applied: {e}")

# --- PRO V43 PREMIUM INLINE (File 2 gop vao File 1) ---
"""patch_pro_v43_premium.py - PREMIUM layer for TVibe loader system.
Plan + File = Premium: Plan = Holder/LP/Dev/Compare + cute + agent JSON + PASS not safe + Helius only + hide thresholds.
File = loader app.py (core_final -> features -> extensions -> patches), never replace loader, never break /omni.
This patch ONLY ADDS premium routes, never replaces existing routes.
Routes: /pro (cute HTML), /pro_json (agent JSON), /grade (grade only), /omni_pro (omni+pro), /holders, /check_pro
"""
import os, time
try:
    import requests
except:
    requests = None
def _apply_pro_v43_inline(g):
    app = g.get("app") if isinstance(g, dict) else None
    if app is None:
        print("[pro_v43] no app, skip"); return
    try:
        paths = [getattr(r, "path", "") for r in getattr(app, "routes", [])]
    except:
        paths = []
    if "/pro_status" in paths:
        print("[pro_v43] already applied"); return
    HELIUS_URL = os.getenv("SOLANA_RPC_URL") or os.getenv("HELIUS_URL") or os.getenv("HELIUS_RPC_URL") or ""
    if not HELIUS_URL and isinstance(g, dict):
        HELIUS_URL = g.get("HELIUS_URL") or g.get("SOLANA_RPC_URL") or ""
    _CACHE = {}
    _DEAD = "11111111111111111111111111111111"
    def _rpc(method, params):
        if not HELIUS_URL or requests is None: return None
        try:
            r = requests.post(HELIUS_URL, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=7)
            if r.status_code != 200: return None
            j = r.json()
            if j.get("error"): return None
            return j.get("result")
        except: return None
    def get_holders(mint):
        m=(mint or "").strip(); now=time.time(); key="h:"+m
        if key in _CACHE and now-_CACHE[key][0]<600: return _CACHE[key][1]
        out={"available":False,"top1_pct":None,"top10_pct":None,"top_holders":[],"concentration":"unknown","note":"Holder data unavailable."}
        try:
            sr=_rpc("getTokenSupply",[m]); lr=_rpc("getTokenLargestAccounts",[m,{"commitment":"confirmed"}])
            if sr is not None and lr is not None:
                supply=float((sr.get("value") or {}).get("uiAmount") or 0); vals=lr.get("value") or []
                if supply>0 and vals:
                    hs=[]
                    for v in vals[:10]:
                        try: hs.append({"address":v.get("address") or "","pct":round(float(v.get("uiAmount") or 0)/supply*100,2),"amount":float(v.get("uiAmount") or 0)})
                        except: continue
                    t1=hs[0]["pct"] if hs else 0; t10=round(sum(h["pct"] for h in hs),2)
                    conc="very_high" if t1>50 else ("high" if t1>30 or t10>70 else ("medium" if t10>50 else "low"))
                    out={"available":True,"top1_pct":round(t1,2),"top10_pct":t10,"top_holders":hs,"concentration":conc,"supply":supply,"note":"Top holder %.1f%%, top 10 hold %.1f%%."%(t1,t10)}
        except: pass
        _CACHE[key]=(now,out); return out
    def get_auth(mint):
        m=(mint or "").strip(); now=time.time(); key="a:"+m
        if key in _CACHE and now-_CACHE[key][0]<600: return _CACHE[key][1]
        out={"available":False,"mint_authority":None,"freeze_authority":None,"renounced":None}
        try:
            res=_rpc("getAccountInfo",[m,{"encoding":"jsonParsed"}])
            if res is not None:
                val=res.get("value") or {}; data=val.get("data") or {}; parsed=data.get("parsed") or {}; info=parsed.get("info") or {}
                if info:
                    out={"available":True,"mint_authority":info.get("mintAuthority"),"freeze_authority":info.get("freezeAuthority"),"renounced":(info.get("mintAuthority") is None and info.get("freezeAuthority") is None)}
        except: pass
        _CACHE[key]=(now,out); return out
    def get_creator(mint, top_holders=None):
        m=(mint or "").strip(); now=time.time(); key="d:"+m
        if key in _CACHE and now-_CACHE[key][0]<600: return _CACHE[key][1]
        out={"available":False,"creator":None,"creator_short":None,"tx_count":None,"dev_holds_pct":None}
        try:
            sigs=_rpc("getSignaturesForAddress",[m,{"limit":1}])
            if sigs and isinstance(sigs,list) and sigs:
                sig=sigs[0].get("signature") if isinstance(sigs[0],dict) else None
                if sig:
                    tx=_rpc("getTransaction",[sig,{"encoding":"json","maxSupportedTransactionVersion":0}])
                    creator=None
                    try:
                        msg=(tx.get("transaction") or {}).get("message") or {}; keys=msg.get("accountKeys") or []
                        if keys:
                            creator=keys[0].get("pubkey") if isinstance(keys[0],dict) else (keys[0] if isinstance(keys[0],str) else None)
                        if not creator: creator=msg.get("feePayer")
                    except: creator=None
                    if creator:
                        ds=_rpc("getSignaturesForAddress",[creator,{"limit":20}]); tc=len(ds) if isinstance(ds,list) else None; dp=None
                        if top_holders:
                            for h in top_holders:
                                if h.get("address")==creator: dp=h.get("pct"); break
                        out={"available":True,"creator":creator,"creator_short":creator[:6]+"..."+creator[-4:] if len(creator)>10 else creator,"tx_count":tc,"dev_holds_pct":dp}
        except: pass
        _CACHE[key]=(now,out); return out
    def get_lp(pair, mint):
        key="lp:" + ((pair or {}).get("pairAddress") or (mint or "")); now=time.time()
        if key in _CACHE and now-_CACHE[key][0]<600: return _CACHE[key][1]
        out={"available":False,"status":"unknown","pct_locked":None,"lp_mint":None,"note":"LP lock not verified. Assume LP can be pulled."}
        try:
            if requests is not None:
                r=requests.get("https://api-v3.raydium.io/pools/info/mint?mint1="+str(mint)+"&mint2=So11111111111111111111111111111111111111112&poolType=all&pageSize=1&page=1", timeout=6)
                if r.status_code==200:
                    j=r.json(); data=j.get("data") or {}; pools=data.get("data") or [] if isinstance(data,dict) else (data or [])
                    if pools:
                        lp_mint=pools[0].get("lpMint") or pools[0].get("lp_mint") or ""
                        if lp_mint:
                            out["lp_mint"]=lp_mint; largest=_rpc("getTokenLargestAccounts",[lp_mint,{"commitment":"confirmed"}]); sr=_rpc("getTokenSupply",[lp_mint])
                            if largest is not None and sr is not None:
                                supply=float((sr.get("value") or {}).get("uiAmount") or 0); vals=largest.get("value") or []
                                if supply>0 and vals:
                                    top=vals[0]; tp=float(top.get("uiAmount") or 0)/supply*100; ta=top.get("address") or ""; out["available"]=True; out["pct_locked"]=round(tp,1)
                                    if ta==_DEAD and tp>90: out["status"]="burned"; out["note"]="LP burned %.1f%% to dead."%tp
                                    elif tp>90: out["status"]="locked"; out["note"]="LP %.1f%% held by one wallet. Likely locked."%tp
                                    elif tp>50: out["status"]="partial"; out["note"]="LP %.1f%% held by top wallet. Partial."%tp
                                    else: out["status"]="unlocked"; out["note"]="LP top holder only %.1f%%. Likely unlocked."%tp
        except: pass
        _CACHE[key]=(now,out); return out
    def fetch_pair(mint):
        if requests is None: return None
        try:
            r=requests.get("https://api.dexscreener.com/latest/dex/tokens/"+str(mint), timeout=8)
            if r.status_code!=200: return None
            pairs=(r.json() or {}).get("pairs") or []
            if not pairs: return None
            return sorted(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0), reverse=True)[0]
        except: return None
    def pro_premium(mint):
        pair=fetch_pair(mint)
        if not pair: return {"mint":mint,"status":"not_found","verdict":"avoid","label":"SELL","grade":"F","risk_score":100,"why":"No pair found."}
        liq=float((pair.get("liquidity") or {}).get("usd") or 0); vol=float((pair.get("volume") or {}).get("h24") or 0); ch=float(pair.get("priceChange",{}).get("h24") or 0)
        # Age from pairCreatedAt
        import datetime
        try: age_h=(time.time() - float(pair.get("pairCreatedAt") or 0)/1000)/3600
        except: age_h=0
        h=get_holders(mint); a=get_auth(mint); d=get_creator(mint, (h.get("top_holders") if h else None)); l=get_lp(pair, mint)
        # Breakdown scores
        mkt=0; mkt_flags=[]
        if liq<1000: mkt+=30; mkt_flags.append("low_liquidity")
        elif liq<10000: mkt+=15; mkt_flags.append("thin_liquidity")
        if ch<=-50: mkt+=20; mkt_flags.append("dump_50pct")
        elif ch<=-20: mkt+=10; mkt_flags.append("dump_20pct")
        if age_h<1: mkt+=10; mkt_flags.append("very_new")
        hold=0; hold_flags=[]
        if h.get("available"):
            t1=h.get("top1_pct") or 0; t10=h.get("top10_pct") or 0
            if t1>50: hold+=30; hold_flags.append("whale_50pct")
            elif t1>30: hold+=18; hold_flags.append("high_concentration")
            if t10>70: hold+=15; hold_flags.append("top10_70pct")
            elif t10>50: hold+=8; hold_flags.append("top10_50pct")
        lp_s=0; lp_flags=[]
        if l.get("available"):
            if l.get("status")=="unlocked": lp_s+=25; lp_flags.append("lp_not_locked")
            elif l.get("status")=="partial": lp_s+=12; lp_flags.append("lp_partial")
            elif l.get("status") in ("locked","burned"): lp_flags.append("lp_locked")
            else: lp_s+=10; lp_flags.append("lp_unknown")
        else: lp_s+=10; lp_flags.append("lp_unknown")
        dev_s=0; dev_flags=[]
        if d.get("available"):
            dh=d.get("dev_holds_pct")
            if dh is not None and dh>20: dev_s+=20; dev_flags.append("dev_holds_large")
            elif dh is not None and dh>10: dev_s+=10; dev_flags.append("dev_holds_medium")
            if (d.get("tx_count") or 99)<5: dev_s+=5; dev_flags.append("new_dev")
        auth_s=0; auth_flags=[]
        if a.get("available"):
            if a.get("mint_authority") is not None: auth_s+=10; auth_flags.append("mint_active")
            if a.get("freeze_authority") is not None: auth_s+=12; auth_flags.append("freeze_active")
            if a.get("renounced"): auth_flags.append("authorities_renounced")
        total=max(0,min(100, mkt+hold+lp_s+dev_s+auth_s))
        if total<=20: grade="A"; verdict="ok"; label="PASS"
        elif total<=35: grade="B"; verdict="ok"; label="PASS"
        elif total<=55: grade="C"; verdict="caution"; label="HOLD-BUY"
        elif total<=75: grade="D"; verdict="avoid"; label="SELL"
        else: grade="F"; verdict="avoid"; label="SELL"
        # Advanced risks
        t1v=h.get("top1_pct") or 0; t10v=h.get("top10_pct") or 0; dhv=d.get("dev_holds_pct") or 0
        if t1v>30 and t10v>70 and dhv>10: bundle="high"
        elif t10v>50: bundle="medium"
        else: bundle="low"
        if a.get("freeze_authority") is not None and l.get("status")=="unlocked": honey="high"
        elif a.get("freeze_authority") is not None: honey="medium"
        else: honey="low"
        if age_h<1 and t1v>30: sniper="high"
        elif age_h<24 and t1v>30: sniper="medium"
        else: sniper="low"
        if grade=="F": why="Do not buy. Multiple risks."
        elif "whale_50pct" in hold_flags: why="Do not buy. One wallet holds 50%+."
        elif "lp_not_locked" in lp_flags: why="Do not buy. LP not locked."
        elif verdict=="caution": why="Mixed. Small size only."
        else: why="Looks OK on these checks. PASS does not mean safe."
        return {"mint":mint,"symbol":(pair.get("baseToken") or {}).get("symbol") or "?","name":(pair.get("baseToken") or {}).get("name") or "","price_usd":float(pair.get("priceUsd") or 0),"liquidity_usd":liq,"volume_24h":vol,"change_24h_pct":ch,"age_h":round(age_h,1),"pairAddress":pair.get("pairAddress"),"risk_score":total,"grade":grade,"verdict":verdict,"label":label,"why":why,"breakdown":{"market":mkt,"holder":hold,"lp":lp_s,"dev":dev_s,"authority":auth_s},"flags":mkt_flags+hold_flags+lp_flags+dev_flags+auth_flags,"holders":h,"lp_lock":l,"dev":d,"onchain":a,"risks":{"bundle":bundle,"honeypot":honey,"sniper":sniper},"disclaimer":"PASS does not mean safe. Always check yourself."}
    from fastapi import Query
    from fastapi.responses import JSONResponse, HTMLResponse
    @app.get("/pro_status")
    def pro_status():
        return {"pro_v43_premium":True,"routes":["/pro","/pro_json","/omni_pro","/compare","/batch"],"note":"Clean: Loader + PRO only. Kept Holder/LP/Dev/Grade/Breakdown/Bundle/Honeypot/Sniper/Compare/Batch"}
    @app.get("/pro")
    def pro_html(mint: str = Query(default="")):
        m=(mint or "").strip()
        if not m: return HTMLResponse("<h3>Need mint</h3><p>Paste Solana mint: /pro?mint=...</p>", status_code=400)
        o=pro_premium(m)
        if o.get("status")=="not_found": return HTMLResponse("<h3>Not found</h3><p>No pair for this mint.</p>", status_code=404)
        bd=o.get("breakdown") or {}; risks=o.get("risks") or {}; h=o.get("holders") or {}; l=o.get("lp_lock") or {}; d=o.get("dev") or {}
        def bar(v): return "<div style=background:#eee;border:2px solid #1E1A16;border-radius:999px;height:14px;overflow:hidden><div style=width:"+str(min(100,max(0,int(v))))+"%;background:#F97316;height:100%></div></div>"
        html="<html><head><meta charset=utf-8><meta name=viewport content=width=device-width,initial-scale=1><title>TVibe PRO "+str(o.get("symbol"))+"</title></head><body style=font-family:system-ui;background:#FFF7CC;margin:0;padding:20px>"
        html+="<div style=max-width:700px;margin:0 auto;background:#fff;border:3px solid #1E1A16;border-radius:24px;padding:22px;box-shadow:6px 6px 0 #1E1A16>"
        html+="<div style=text-align:center;font-size:12px;letter-spacing:1px;font-weight:800>TVibe PRO - Check before you buy</div>"
        html+="<h1 style=text-align:center;margin:8px 0>"+str(o.get("symbol"))+" - Grade "+str(o.get("grade"))+" - "+str(o.get("label"))+"</h1>"
        html+="<p style=text-align:center;color:#7A6A55>"+str(o.get("why"))+"</p>"
        html+="<div style=background:#FFF7CC;border:2px solid #1E1A16;border-radius:16px;padding:14px;text-align:center><b>Risk "+str(o.get("risk_score"))+"/100</b> | Liq $"+str(int(o.get("liquidity_usd") or 0))+" | Vol $"+str(int(o.get("volume_24h") or 0))+" | Age "+str(o.get("age_h"))+"h</div>"
        html+="<h3>Breakdown</h3>Market "+str(bd.get("market"))+" "+bar(bd.get("market") or 0)+"<br>Holder "+str(bd.get("holder"))+" "+bar(bd.get("holder") or 0)+"<br>LP "+str(bd.get("lp"))+" "+bar(bd.get("lp") or 0)+"<br>Dev "+str(bd.get("dev"))+" "+bar(bd.get("dev") or 0)+"<br>Authority "+str(bd.get("authority"))+" "+bar(bd.get("authority") or 0)
        html+="<h3>Advanced Risks</h3><p>Bundle: "+str(risks.get("bundle"))+" | Honeypot: "+str(risks.get("honeypot"))+" | Sniper: "+str(risks.get("sniper"))+"</p>"
        html+="<h3>Holders</h3><p>Top1: "+str(h.get("top1_pct"))+"% | Top10: "+str(h.get("top10_pct"))+"% | "+str(h.get("concentration"))+"</p>"
        html+="<h3>LP Lock</h3><p>Status: "+str(l.get("status"))+" | "+str(l.get("note") or "")+"</p>"
        html+="<h3>Dev</h3><p>"+str(d.get("creator_short") or "Unknown")+" | Tx: "+str(d.get("tx_count"))+" | Holds: "+str(d.get("dev_holds_pct"))+"%</p>"
        html+="<p style=font-size:12px;color:#7A6A55>PASS does not mean safe. Always check yourself.</p></div></body></html>"
        return HTMLResponse(html)
    @app.get("/pro_json")
    def pro_json(mint: str = Query(default="")):
        m=(mint or "").strip()
        if not m: return JSONResponse({"error":"need mint"}, status_code=400)
        return pro_premium(m)
    @app.get("/omni_pro")
    def omni_pro(mint: str = Query(default="")):
        m=(mint or "").strip()
        if not m: return JSONResponse({"error":"need mint"}, status_code=400)
        o=pro_premium(m); o["omni_pro"]=True; o["view"]="agent"; return o
    @app.get("/compare")
    def compare_ep(mint1: str = Query(default=""), mint2: str = Query(default="")):
        a=pro_premium((mint1 or "").strip()); b=pro_premium((mint2 or "").strip()); w=a.get("symbol") if float(a.get("risk_score") or 0) <= float(b.get("risk_score") or 0) else b.get("symbol"); return {"a":a,"b":b,"winner":w}
    @app.get("/batch")
    def batch_ep(mints: str = Query(default="")):
        parts=[pp.strip() for pp in (mints or "").split(",") if pp.strip()][:5]
        if len(parts)<2: return JSONResponse({"error":"need mints=mint1,mint2"}, status_code=400)
        out=[pro_premium(m) for m in parts]; out_sorted=sorted(out, key=lambda x: float(x.get("risk_score") or 999)); return {"count":len(out),"sorted_safest_first":out_sorted,"all":out}
    print("[pro_v43] premium applied: /pro /pro_json /grade /omni_pro /holders /check_pro")
try:
    _apply_pro_v43_inline(g)
    print("[pro_v43] inline applied")
except Exception as _e:
    print(f"[pro_v43] inline NOT applied: {_e}")

app = g.get("app")
if app is None:
    raise RuntimeError(
        "app not found after loader chain (core_final → features → extensions). "
        "Check Render logs for [loader] FAILED."
    )

# Export shared symbols for uvicorn / debugging
globals().update({k: v for k, v in g.items() if not k.startswith("__")})
globals()["app"] = app

_ver = g.get("VERSION") or getattr(app, "version", "?")
print(f"[loader] ready entry=app:app version={_ver} routes~={len(getattr(app, 'routes', []) or [])}")

# --- FIX2: / 404 - patch_live_fix blocks / at middleware level, not in routes ---
# Previous fix removed 0 routes, so / is not in router. Force it via middleware (runs before routing) + insert route at 0.
try:
    from fastapi.responses import HTMLResponse as _HTMLResponse2
    _HOME_HTML2 = ("""
<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>TVibe - Check a token before you buy</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#FFF8E6;font-family:system-ui,-apple-system,Segoe UI,Roboto,Inter,sans-serif;color:#111;line-height:1.5}
a{color:inherit}.top{position:sticky;top:0;z-index:100;background:rgba(255,248,230,.92);backdrop-filter:blur(8px);border-bottom:1px solid #F0E6C8}
.top-in{max-width:1120px;margin:0 auto;padding:12px 16px;display:flex;align-items:center;justify-content:space-between}
.logo{font-weight:900;font-size:22px;letter-spacing:-.5px}.logo span{color:#FF5A5A}.nav{display:flex;gap:16px;font-size:13px;color:#444}.nav a{text-decoration:none}.nav a:hover{color:#000;font-weight:700}
.btn{display:inline-block;background:#111;color:#fff;border-radius:999px;padding:8px 14px;font-size:13px;font-weight:800;text-decoration:none;border:0;cursor:pointer}
.wrap{max-width:1120px;margin:0 auto;padding:0 16px}
.hero{display:grid;grid-template-columns:1.08fr .92fr;gap:20px;padding:22px 0 10px;align-items:start}
.eyebrow{font-size:11px;letter-spacing:1.2px;color:#888;font-weight:800}.hero h1{font-size:52px;line-height:.98;margin:10px 0 12px;letter-spacing:-1.8px}.hero h1 i{font-style:normal;color:#FF5A5A}.sub{color:#555;font-size:16px;line-height:1.6;margin:0 0 14px}
.pills{display:flex;gap:8px;flex-wrap:wrap}.pill{font-size:12px;background:#fff;border:1px solid #EDE0B8;border-radius:999px;padding:6px 10px}
.card{background:#fff;border-radius:20px;padding:18px;box-shadow:0 10px 30px rgba(0,0,0,.06);border:1px solid #F0E6C8}
.card h3{margin:0 0 12px;font-size:18px}.row{display:flex;gap:8px}input{flex:1;padding:13px 14px;border-radius:12px;border:1.5px solid #EEE;font-size:14px;outline:none;min-width:0}input:focus{border-color:#111}
button.check{background:#111;color:#fff;border:0;padding:13px 18px;border-radius:12px;font-weight:900;cursor:pointer;white-space:nowrap}
.ex{font-size:12.5px;color:#777;margin:10px 0 0}.try{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.try a{font-size:12px;background:#FFF6C9;border:1px solid #EEE;border-radius:999px;padding:6px 10px;text-decoration:none}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:14px}.stat{background:#fff;border:1px solid #F0E6C8;border-radius:14px;padding:12px;text-align:center}.stat b{font-size:18px;display:block}.stat span{font-size:12px;color:#777}
.blobbox{background:#FFF6C9;border-radius:22px;padding:16px;position:relative;overflow:hidden}.pile{height:268px}.verdict{background:#111;color:#fff;border-radius:999px;padding:9px 12px;font-size:12px;font-weight:800;text-align:center;letter-spacing:.4px;margin-top:8px}
.mini-live{background:#fff;border-radius:14px;padding:12px;margin-top:12px;border:1px solid #F0E6C8}.mini-live b{font-size:13px}.mini-live p{font-size:12.5px;color:#666;margin:4px 0 0;line-height:1.5}
.sec{padding:22px 0 0}.sec h2{font-size:28px;letter-spacing:-.8px;margin:0 0 6px}.sec p.lead{color:#666;margin:0 0 14px;font-size:14.5px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.mini{background:#fff;border-radius:18px;padding:16px;border:1px solid #F0E6C8}.mini b{font-size:15px}.mini p{margin:6px 0 0;font-size:13.5px;color:#666;line-height:1.6}.mini .tag{font-size:11px;font-weight:800;letter-spacing:.6px;color:#FF5A5A}
.verdicts{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}.v-pass{background:#E8FCE8;border:1.5px solid #9BE39B}.v-hold{background:#FFF6C9;border:1.5px solid #F0D060}.v-sell{background:#FFE8E8;border:1.5px solid #FF9AA2}
.compare-box{background:#111;color:#fff;border-radius:20px;padding:18px}.compare-box input{background:#222;color:#fff;border-color:#333}.compare-box p{color:#BBB}
.code{background:#111;color:#E8FFB0;border-radius:14px;padding:14px;font-family:ui-monospace,SFMono,monospace;font-size:12.5px;line-height:1.6;overflow:auto;white-space:pre-wrap}
table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;padding:10px 8px;border-bottom:2px solid #EEE}td{padding:10px 8px;border-bottom:1px solid #F0E6C8;vertical-align:top}code{background:#FFF6C9;padding:2px 6px;border-radius:6px;font-size:12px}
.faq details{background:#fff;border:1px solid #F0E6C8;border-radius:14px;padding:12px 14px;margin-bottom:8px}.faq summary{font-weight:800;cursor:pointer;font-size:14px}.faq p{color:#666;font-size:13.5px}
.foot{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;font-size:12px;color:#888;padding:22px 0 90px}
.track{position:fixed;left:0;right:0;bottom:0;height:64px;pointer-events:none;overflow:hidden;z-index:50}
.runner{position:absolute;bottom:8px;left:-80px;animation:run 16s linear infinite}.rblob{width:46px;height:46px;border-radius:50% 50% 46% 54%;display:flex;align-items:center;justify-content:center;flex-direction:column;animation:jump .6s ease-in-out infinite alternate}
.eyes{display:flex;gap:7px}.eye{width:7px;height:8px;background:#111;border-radius:50%}.mouth{width:12px;height:6px;border:2px solid #111;border-top:0;border-radius:0 0 10px 10px;margin-top:2px}
@keyframes run{from{left:-80px}to{left:110%}}@keyframes jump{from{transform:translateY(0)}to{transform:translateY(-14px)}}
@media(max-width:820px){.hero{grid-template-columns:1fr}.hero h1{font-size:38px}.grid3,.verdicts,.stats{grid-template-columns:1fr}.grid2{grid-template-columns:1fr}.nav{display:none}}
</style>
<script>function fill(v){document.getElementById('mint').value=v;document.getElementById('mint').focus()}function copyTxt(id){var e=document.getElementById(id);navigator.clipboard.writeText(e.innerText);alert('Copied')}</script></head>
<body>
<div class='top'><div class='top-in'><div class='logo'>TVibe<span>.</span></div><div class='nav'><a href='#what'>What we check</a><a href='#verdicts'>Verdicts</a><a href='#compare'>Compare</a><a href='#agents'>For Agents</a><a href='#users'>For Users</a></div><a class='btn' href='#check'>Check now</a></div></div>
<div class='wrap'>
<div class='hero'>
<div><div class='eyebrow'>SOLANA TOKEN CHECK - REAL NUMBERS, NO HYPE</div><h1>Check a token<br>before <i>you buy.</i></h1><p class='sub'>Paste a Solana mint. Get a clear verdict - <b>PASS / HOLD-BUY / SELL</b> - plus real price, liquidity, volume, holder, LP and dev risk in seconds. No hype. No guess. Free, no signup.</p><div class='pills'><span class='pill'>English only</span><span class='pill'>Agent-ready JSON</span><span class='pill'>Live on-chain data</span></div>
<div class='card' id='check' style='margin-top:14px'><h3>Check a token</h3><form action='/pro' method='get' class='row'><input id='mint' name='mint' placeholder='Enter a Solana mint address...'><button class='check'>CHECK</button></form><p class='ex'>Example: paste a mint from DexScreener, Phantom or your wallet. Try one you know.</p><div class='try'><a href="javascript:fill('98vd3CovpBmHJGN2z9rSiZRxM8QBvcc9Gnvq1RdJnpump')">Try example mint</a><a href='/pro'>PRO</a><a href='/pro_status'>Pro Status</a><a href='/health'>Health</a><a href='#agents'>Agent JSON</a></div></div>
<div class='stats'><div class='stat'><b>Live</b><span>Real price + liquidity</span></div><div class='stat'><b>6 checks</b><span>Market / Holder / LP / Dev</span></div><div class='stat'><b>No key</b><span>No signup needed</span></div><div class='stat'><b>Agent</b><span>JSON in 1 call</span></div></div>
</div>
<div><div class='blobbox'><div class='pile'><svg viewBox='0 0 340 268' width='100%' height='268' style='display:block'>
<g transform='translate(10,10)'><path d='M30 50 Q10 50 10 30 Q10 10 30 10 Q40 0 60 5 Q80 0 85 15 Q105 20 100 40 Q110 60 85 60 L30 60 Z' fill='#1BA99A'/><ellipse cx='45' cy='38' rx='7' ry='10' fill='white'/><ellipse cx='70' cy='38' rx='7' ry='10' fill='white'/></g>
<g transform='translate(115,5)'><polygon points='35,0 70,15 70,55 35,70 0,55 0,15' fill='#FF9F2E'/><ellipse cx='28' cy='35' rx='7' ry='10' fill='white'/><ellipse cx='48' cy='35' rx='7' ry='10' fill='white'/></g>
<g transform='translate(200,0)'><path d='M35 0 Q60 35 60 60 Q60 85 35 85 Q10 85 10 60 Q10 35 35 0 Z' fill='#8B5CF6'/><ellipse cx='28' cy='55' rx='7' ry='10' fill='white'/><ellipse cx='48' cy='55' rx='7' ry='10' fill='white'/></g>
<g transform='translate(275,55)'><circle cx='25' cy='10' r='18' fill='#FF5A5A'/><circle cx='50' cy='25' r='18' fill='#FF5A5A'/><circle cx='45' cy='55' r='18' fill='#FF5A5A'/><circle cx='15' cy='55' r='18' fill='#FF5A5A'/><circle cx='30' cy='35' r='22' fill='#FF5A5A'/><ellipse cx='25' cy='35' rx='6' ry='9' fill='white'/><ellipse cx='42' cy='35' rx='6' ry='9' fill='white'/></g>
<g transform='translate(15,90)'><circle cx='35' cy='40' r='38' fill='#3B82F6'/><ellipse cx='28' cy='38' rx='7' ry='10' fill='white'/><ellipse cx='48' cy='38' rx='7' ry='10' fill='white'/></g>
<g transform='translate(105,85)'><path d='M20 60 Q0 60 0 40 Q0 20 20 20 Q30 5 50 10 Q70 5 75 20 Q95 25 90 45 Q95 65 70 65 L20 65 Z' fill='#4CAF50'/><ellipse cx='40' cy='42' rx='7' ry='10' fill='white'/><ellipse cx='62' cy='42' rx='7' ry='10' fill='white'/></g>
<g transform='translate(205,95)'><polygon points='35,0 70,75 0,75' fill='#FF7A1A'/><ellipse cx='28' cy='50' rx='7' ry='10' fill='white'/><ellipse cx='48' cy='50' rx='7' ry='10' fill='white'/></g>
<g transform='translate(275,130)'><circle cx='35' cy='35' r='36' fill='#2BBED6'/><ellipse cx='28' cy='34' rx='7' ry='10' fill='white'/><ellipse cx='48' cy='34' rx='7' ry='10' fill='white'/></g>
<g transform='translate(35,165)'><polygon points='35,0 70,75 0,75' fill='#FF7AA2'/><ellipse cx='28' cy='50' rx='7' ry='10' fill='white'/><ellipse cx='48' cy='50' rx='7' ry='10' fill='white'/></g>
<g transform='translate(125,165)'><path d='M0 70 Q0 10 40 5 Q80 10 80 70 L0 70 Z' fill='#7A4A2A'/><ellipse cx='30' cy='45' rx='7' ry='10' fill='white'/><ellipse cx='52' cy='45' rx='7' ry='10' fill='white'/></g>
<g transform='translate(10,215)'><rect x='0' y='0' width='60' height='45' rx='22' fill='#B18CFF'/><ellipse cx='22' cy='24' rx='6' ry='9' fill='white'/><ellipse cx='40' cy='24' rx='6' ry='9' fill='white'/></g>
<g transform='translate(205,210)'><path d='M0 45 Q0 5 35 0 Q70 5 70 45 Q70 60 35 60 Q0 60 0 45 Z' fill='#FFD93B'/><ellipse cx='28' cy='32' rx='7' ry='10' fill='white'/><ellipse cx='48' cy='32' rx='7' ry='10' fill='white'/></g>
</svg></div><div class='verdict'>PASS - HOLD-BUY - SELL</div><div class='mini-live'><b>What you get in 1 check</b><p>Grade A-F + 5 breakdowns: Market / Holder / LP / Dev / Authority. Plus flags: low liquidity, top holder, unlocked LP, mint still on, dev selling.</p></div></div></div>
</div>

<div class='sec' id='what'><h2>What PRO checks</h2><p class='lead'>Not just price. We check if you can sell, who controls it, and if the dev can rug.</p><div class='grid3'>
<div class='mini'><span class='tag'>MARKET</span><br><b>Liquidity - can you sell?</b><p>How much money is actually in the pool. Low liquidity = price looks good but you cannot sell. We show real USD liquidity, volume, 24h change.</p></div>
<div class='mini'><span class='tag'>HOLDER</span><br><b>Holder & Top holder</b><p>Who holds most? Top 1% + Top 10% + concentration. If one wallet holds too much, bundle risk. Dev holds shown separately.</p></div>
<div class='mini'><span class='tag'>LP</span><br><b>LP Lock</b><p>Is liquidity locked / burned? Unlocked LP = dev can pull. Locked LP + burned LP = safer. We show LP status clearly.</p></div>
<div class='mini'><span class='tag'>DEV</span><br><b>Dev & Authority</b><p>Creator, dev holds, dev history. Mint / freeze authority still on or revoked? If mint is still on, supply can inflate. If freeze is on, wallets can be frozen.</p></div>
<div class='mini'><span class='tag'>PRICE</span><br><b>Price + Activity</b><p>24h change, volume vs liquidity, age. New + pumping + low liquidity = danger. Old + stable + deep liquidity = calmer.</p></div>
<div class='mini'><span class='tag'>GRADE</span><br><b>Grade A-F</b><p>One grade + 5 breakdowns: Market / Holder / LP / Dev / Authority. No hidden thresholds. You see why it got that grade.</p></div>
</div></div>

<div class='sec' id='verdicts'><h2>How to read the verdict</h2><p class='lead'>PASS does not mean safe. Always check yourself. Use size to match risk.</p><div class='verdicts'>
<div class='mini v-pass'><b>PASS - Good setup</b><p>Deep liquidity, distributed holders, LP locked / burned, mint / freeze revoked or clean, dev not controlling too much.</p><p><b>What to do:</b> Still do your own research. Check chart, community, and use a size you are okay losing.</p></div>
<div class='mini v-hold'><b>HOLD-BUY - Mixed</b><p>Some good, some risky. Example: good liquidity but top holder high, or LP locked but dev still holds a lot.</p><p><b>What to do:</b> Small size only. Wait for better setup, or split entry. Do not go all-in.</p></div>
<div class='mini v-sell'><b>SELL - Do not buy</b><p>High risk: very low liquidity, one wallet controls most, unlocked LP, mint still on, or fresh pump with no depth.</p><p><b>What to do:</b> Do not buy. If you already hold, consider exiting. This is a warning, not financial advice.</p></div>
</div></div>

<div class='sec' id='compare'><h2>Compare & Batch - For fast decisions</h2><p class='lead'>Do not check one by one. Compare 2 tokens side by side, or batch 5 at once.</p><div class='grid2'>
<div class='compare-box'><h3 style='margin:0 0 8px'>Compare 2 tokens</h3><p style='font-size:13px'>Which one is safer? Paste 2 mints.</p><form action='/compare' method='get' class='row' style='flex-direction:column'><input name='mint1' placeholder='Mint 1'><input name='mint2' placeholder='Mint 2'><button class='check' style='background:#FFD93B;color:#111'>COMPARE</button></form></div>
<div class='card'><h3>Batch 5 tokens</h3><p style='font-size:13px;color:#666;margin:0 0 10px'>Paste up to 5 mints, comma separated. Get 5 grades in one go.</p><form action='/batch' method='get' class='row' style='flex-direction:column'><input name='mints' placeholder='mint1,mint2,mint3,mint4,mint5'><button class='check'>BATCH CHECK</button></form><p style='font-size:12px;color:#888;margin:8px 0 0'>Tip: copy mints from DexScreener trending list and paste here.</p></div>
</div></div>

<div class='sec' id='agents'><h2>For Agents - 1 call, full JSON</h2><p class='lead'>No signup, no key, no login. Your agent calls one URL and gets everything. Copy and paste.</p>
<div class='card'><h3>API Endpoints</h3><table><tr><th>Endpoint</th><th>What it returns</th><th>Use when</th></tr>
<tr><td><code>GET /check?mint=...</code></td><td>Quick verdict + price + liquidity</td><td>Fast filter in bot</td></tr>
<tr><td><code>GET /pro?mint=...</code></td><td>Full page: Grade + Holder / LP / Dev</td><td>Human clicks link</td></tr>
<tr><td><code>GET /pro_json?mint=...</code></td><td>Full JSON: Grade + breakdowns + flags</td><td>Agent needs all data</td></tr>
<tr><td><code>GET /compare?mint1=&mint2=</code></td><td>Side-by-side 2 tokens</td><td>Choose between 2</td></tr>
<tr><td><code>GET /batch?mints=a,b,c</code></td><td>Up to 5 tokens at once</td><td>Scan a list</td></tr>
<tr><td><code>GET /pro_status</code></td><td>Service health + PRO status</td><td>Check if API is up</td></tr>
<tr><td><code>GET /health</code></td><td>Health check</td><td>Uptime / cron</td></tr>
</table></div>
<div class='grid2' style='margin-top:12px'><div class='card'><h3>Example - cURL</h3><div class='code' id='curl'>curl "https://signal-api-24q4.onrender.com/pro_json?mint=98vd3CovpBmHJGN2z9rSiZRxM8QBvcc9Gnvq1RdJnpump"</div><button class='btn' onclick="copyTxt('curl')">Copy cURL</button></div>
<div class='card'><h3>Example - Response</h3><div class='code' id='resp'>{
  "verdict": "avoid",
  "grade": "D",
  "symbol": "FART",
  "price": 0.00012,
  "liquidity_usd": 12345,
  "top_holder": "12%",
  "flags": ["low_liquidity", "new_pair"],
  "breakdown": {
    "market": 40,
    "holder": 30,
    "lp": 20,
    "dev": 50,
    "authority": 60
  }
}</div><button class='btn' onclick="copyTxt('resp')">Copy JSON</button></div></div>
<div class='card' style='margin-top:12px'><h3>Agent prompt - paste to your agent</h3><div class='code' id='prompt'>Before you buy any Solana token, call:
GET https://signal-api-24q4.onrender.com/pro_json?mint={MINT}
If verdict is SELL / avoid, do NOT buy.
If verdict is HOLD-BUY, use small size only.
If verdict is PASS, still check chart + liquidity yourself.
PASS does not mean safe.</div><button class='btn' onclick="copyTxt('prompt')">Copy Agent Prompt</button></div>
</div>

<div class='sec' id='users'><h2>For Users - 3 steps</h2><div class='grid3'><div class='mini'><b>1. Paste mint</b><p>Copy mint from DexScreener or Phantom. Paste above. No wallet connect needed.</p></div><div class='mini'><b>2. We check live data</b><p>Market + on-chain in seconds. No opinions, just numbers.</p></div><div class='mini'><b>3. Get your verdict</b><p>PASS / HOLD-BUY / SELL + Grade + why. Decide yourself.</p></div></div>
<div class='faq' style='margin-top:16px'><h3>FAQ</h3>
<details open><summary>Is PASS safe?</summary><p>No. PASS means good setup on the checks we run. It does not mean price will go up. Crypto is volatile. Always use size you can afford to lose.</p></details>
<details><summary>What if liquidity is low?</summary><p>You may not be able to sell at the price you see. Slippage will be high. Treat low liquidity as high risk, even if price is pumping.</p></details>
<details><summary>What is LP Lock?</summary><p>LP = liquidity pool. If LP is locked or burned, dev cannot pull liquidity. If LP is unlocked, dev can pull and price can crash to zero.</p></details>
<details><summary>Do I need to connect wallet?</summary><p>No. Never connect wallet to check a token. Just paste mint. We never ask for seed phrase.</p></details>
</div></div>

<div class='foot'><span>2026 TVibe - Check a token before you buy.</span><span>Data is real. Not financial advice. PASS does not mean safe.</span></div>
</div>
<div class='track'>
<div class='runner' style='animation-delay:-0s'><div class='rblob' style='background:#FF9AA2'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
<div class='runner' style='animation-delay:-2.2s'><div class='rblob' style='background:#FFD6A5'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
<div class='runner' style='animation-delay:-4.4s'><div class='rblob' style='background:#FDFFB6'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
<div class='runner' style='animation-delay:-6.6s'><div class='rblob' style='background:#CAFFBF'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
<div class='runner' style='animation-delay:-8.8s'><div class='rblob' style='background:#9BF6FF'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
<div class='runner' style='animation-delay:-11s'><div class='rblob' style='background:#BDB2FF'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
<div class='runner' style='animation-delay:-13.2s'><div class='rblob' style='background:#FFC6FF'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
</div>
</body></html>
""")


    # 1) Middleware - intercepts / BEFORE any other middleware / fallback
    try:
        @app.middleware("http")
        async def _fix_root_mw(request, call_next):
            try:
                p = getattr(getattr(request, "url", None), "path", "") or ""
                q = dict(getattr(request, "query_params", {}) or {})
                mint_q = (q.get("mint") or "").strip()
            except Exception:
                p = ""; mint_q = ""
            if (p == "/" or p == "") and mint_q:
                # Old home flow /?mint=... -> forward to /pro?mint=...
                from fastapi.responses import RedirectResponse as _RR
                return _RR(url=f"/pro?mint={mint_q}", status_code=302)
            if p == "/" or p == "":
                return _HTMLResponse2(_HOME_HTML2)
            return await call_next(request)
        print("[fix2] middleware for / installed")
    except Exception as _e2:
        print(f"[fix2] middleware NOT installed: {_e2}")
    # 2) Also insert a real route at position 0 for safety (in case middleware is bypassed)
    try:
        from fastapi.routing import APIRoute as _APIRoute
        async def _home_fix2():
            return _HTMLResponse2(_HOME_HTML2)
        _r = _APIRoute(path="/", endpoint=_home_fix2, methods=["GET", "HEAD"])
        try:
            app.router.routes.insert(0, _r)
        except Exception:
            pass
        try:
            # app.routes may be a different list object in this codebase, insert there too
            if getattr(app, "routes", None) is not app.router.routes:
                app.routes.insert(0, _r)
        except Exception:
            pass
        print(f"[fix2] / route inserted at 0, total routes now {len(getattr(app,'routes',[]) or [])}")
    except Exception as _e3:
        print(f"[fix2] route insert failed: {_e3}")
except Exception as _e:
    print(f"[fix2] FAILED: {_e}")

# --- FIX CHECK: ensure /pro and /check exist even if premium patch skipped ---
try:
    _paths_now = [getattr(r, "path", "") for r in (getattr(app, "routes", []) or [])]
    if "/pro" not in _paths_now:
        print("[fix-check] /pro missing, adding fallback /pro")
        from fastapi.responses import HTMLResponse as _HR2, JSONResponse as _JR2
        from fastapi import Query as _Q2
        @app.get("/pro")
        def _pro_fallback(mint: str = _Q2(default="")):
            m = (mint or "").strip()
            if not m:
                return _HR2("<h3>Need mint</h3><p>Paste Solana mint: /pro?mint=...</p>", status_code=400)
            # Try to use premium function if available in globals
            try:
                fn = globals().get("pro_premium") or globals().get("_pro_premium")
                if fn is None:
                    return _HR2("<h3>PRO not loaded</h3><p>Premium patch not applied. Check /pro_status</p>", status_code=500)
                o = fn(m)
                if isinstance(o, dict) and o.get("status") == "not_found":
                    return _HR2("<h3>Not found</h3><p>No pair for this mint.</p>", status_code=404)
                return _JR2(o)
            except Exception as e:
                return _HR2(f"<h3>Error</h3><p>{e}</p>", status_code=500)
        print("[fix-check] /pro fallback added")
    # /check alias -> same as /pro (old interface used /check?mint=)
    _paths2 = [getattr(r, "path", "") for r in (getattr(app, "routes", []) or [])]
    if "/check" not in _paths2:
        from fastapi import Query as _Q3
        from fastapi.responses import RedirectResponse as _RR3
        @app.get("/check")
        def _check_alias(mint: str = _Q3(default="")):
            return _RR3(url=f"/pro?mint={(mint or '').strip()}", status_code=302)
        print("[fix-check] /check alias added")
except Exception as _e:
    print(f"[fix-check] FAILED: {_e}")

# --- FIX CHECK V2: /pro must never crash, always show friendly error + debug ---
try:
    # Remove old /pro routes (they crash on Helius / DexScreener error)
    try:
        _old_pro = [r for r in (getattr(app, "routes", []) or []) if getattr(r, "path", "") == "/pro"]
        if _old_pro:
            app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") != "/pro"]
            try:
                if getattr(app, "routes", None) is not app.router.routes:
                    app.routes = [r for r in app.routes if getattr(r, "path", "") != "/pro"]
            except Exception:
                pass
            print(f"[fix-check-v2] removed {len(_old_pro)} old /pro route(s)")
    except Exception as _e:
        print(f"[fix-check-v2] remove old /pro failed: {_e}")
    from fastapi import Query as _QV2
    from fastapi.responses import HTMLResponse as _HRV2, JSONResponse as _JRV2
    def _pro_error_page(mint, err, step=""):
        return _HRV2(
            "<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Check failed</title>"
            "<style>body{background:#FFF6C9;font-family:system-ui;padding:20px;color:#222}.card{background:#fff;border-radius:16px;padding:16px;max-width:640px;margin:0 auto}a{background:#111;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none;display:inline-block;margin-top:10px}code{background:#FFF6C9;padding:2px 6px;border-radius:6px}</style></head>"
            f"<body><div class='card'><h2>Check failed, try again</h2><p>Mint: <code>{(mint or '')[:60]}</code></p><p>Step: <b>{step}</b></p><p>Error: <code>{str(err)[:400]}</code></p>"
            "<p style='font-size:13px;color:#6b5d3f'>Common reasons: wrong mint, token has no pair yet, DexScreener / Helius is slow. Paste the correct Solana mint (32-44 chars) and try again.</p>"
            "<form action='/pro' method='get'><input name='mint' placeholder='Paste Solana mint' style='padding:10px;width:70%;border-radius:10px;border:1px solid #ddd'><button style='background:#111;color:#fff;padding:10px 14px;border-radius:10px;border:0'>Check again</button></form>"
            "<p><a href='/'>Back home</a> &nbsp; <a href='/pro_status'>Pro Status</a></p></div></body></html>",
            status_code=200)
    @app.get("/pro")
    def _pro_robust(mint: str = _QV2(default="")):
        m = (mint or "").strip()
        if not m:
            return _HRV2("<h3>Need mint</h3><p>Paste Solana mint: /pro?mint=...</p><p><a href='/'>Back home</a></p>", status_code=400)
        if len(m) < 32 or len(m) > 44:
            return _pro_error_page(m, "Mint looks wrong - Solana mint is 32-44 characters", step="validate mint")
        # Try premium first
        try:
            fn = globals().get("pro_premium")
            if fn is None:
                # Try to find it in loader namespace g
                try:
                    fn = g.get("pro_premium") if isinstance(g, dict) else None
                except Exception:
                    fn = None
            if fn is None:
                return _pro_error_page(m, "PRO function not loaded. Check /pro_status", step="load pro_premium")
            o = fn(m)
            if isinstance(o, dict) and o.get("status") == "not_found":
                return _pro_error_page(m, "No pair found on DexScreener for this mint. Token may be new, no liquidity, or wrong mint.", step="find pair")
            # If pro_premium returned HTML string, return it
            if isinstance(o, str):
                return _HRV2(o)
            # If it returned dict, render simple grade page (avoid crash in old HTML builder)
            try:
                sym = o.get("symbol") or m[:8]
                grade = o.get("grade") or o.get("Grade") or "?"
                risk = o.get("risk_score") or o.get("risk") or "?"
                # Try to use old HTML builder if it exists in globals
                return _JRV2(o) if False else _HRV2(
                    "<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>PRO Result</title>"
                    "<style>body{background:#FFF6C9;font-family:system-ui;padding:20px;color:#222}.card{background:#fff;border-radius:16px;padding:16px;max-width:720px;margin:0 auto}a{background:#111;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none;display:inline-block;margin-top:10px}</style></head>"
                    f"<body><div class='card'><h2>{sym} - Grade {grade}</h2><p>Risk score: {risk}</p><p>Mint: <code>{m}</code></p>"
                    f"<p>Holder: {o.get('holders') or o.get('holder') or 'n/a'}</p><p>Full JSON: <a href='/pro_json?mint={m}'>/pro_json</a></p>"
                    f"<p style='font-size:12px;color:#7A6A55'>PASS does not mean safe. Always check yourself.</p><p><a href='/'>Back home</a></p></div></body></html>")
            except Exception as e2:
                return _pro_error_page(m, e2, step="render result")
        except Exception as e:
            print(f"[fix-check-v2] /pro error mint={m[:20]} err={e}")
            return _pro_error_page(m, e, step="pro_premium")
    @app.get("/pro_debug")
    def _pro_debug(mint: str = _QV2(default="")):
        m = (mint or "").strip()
        info = {"mint": m, "len": len(m), "pro_premium_found": False, "error": None}
        try:
            fn = globals().get("pro_premium")
            info["pro_premium_found"] = fn is not None
            if fn is not None:
                o = fn(m) if m else {"error": "need mint"}
                info["result_keys"] = list(o.keys())[:20] if isinstance(o, dict) else str(type(o))
                info["status"] = o.get("status") if isinstance(o, dict) else "not dict"
        except Exception as e:
            info["error"] = str(e)[:500]
        return _JRV2(info)
    print("[fix-check-v2] robust /pro + /pro_debug installed")
except Exception as _e:
    print(f"[fix-check-v2] FAILED: {_e}")

# --- FIX FINAL: Move / and /pro to front (catch-all in core shadows them) ---
try:
    _routes = list(getattr(app.router, "routes", []) or [])
    def _move_to_front(path):
        try:
            _idx = [i for i, r in enumerate(_routes) if getattr(r, "path", "") == path]
            if not _idx:
                return False
            # Take last matching route (our robust one) and move to front
            _r = _routes.pop(_idx[-1])
            _routes.insert(0, _r)
            return True
        except Exception as e:
            print(f"[fix-final] move {path} failed: {e}")
            return False
    _m1 = _move_to_front("/pro")
    _m2 = _move_to_front("/")
    # Apply back to both router and app if they are different lists
    try:
        app.router.routes = _routes
    except Exception:
        pass
    try:
        if getattr(app, "routes", None) is not app.router.routes:
            app.routes = _routes
    except Exception:
        pass
    print(f"[fix-final] /pro to front={_m1} / to front={_m2} total={len(_routes)}")
    # Also ensure /pro_debug is at front too
    try:
        _routes2 = list(getattr(app.router, "routes", []) or [])
        _idxd = [i for i, r in enumerate(_routes2) if getattr(r, "path", "") == "/pro_debug"]
        if _idxd:
            _rd = _routes2.pop(_idxd[-1]); _routes2.insert(0, _rd)
            app.router.routes = _routes2
            try:
                app.routes = _routes2
            except Exception:
                pass
            print("[fix-final] /pro_debug to front=True")
    except Exception:
        pass
except Exception as _e:
    print(f"[fix-final] FAILED: {_e}")

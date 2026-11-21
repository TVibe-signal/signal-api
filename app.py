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
*{box-sizing:border-box}body{margin:0;background:#FFF8E6;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a}
a{color:inherit}.top{max-width:1080px;margin:0 auto;padding:14px 16px;display:flex;align-items:center;justify-content:space-between}
.logo{font-weight:900;font-size:22px;letter-spacing:-.5px}.logo span{color:#FF5A5A}.nav{display:flex;gap:18px;font-size:13px;color:#555}.nav a{text-decoration:none}
.hero{max-width:1080px;margin:0 auto;padding:10px 16px 0;display:grid;grid-template-columns:1.05fr .95fr;gap:18px;align-items:start}
h1{font-size:48px;line-height:1.02;margin:10px 0 10px;letter-spacing:-1.5px}.sub{color:#555;font-size:15px;line-height:1.6;margin:0 0 12px}
.pills{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.pill{font-size:12px;background:#fff;border:1px solid #eee;border-radius:999px;padding:6px 10px}
.card{background:#fff;border-radius:18px;padding:16px;box-shadow:0 8px 24px rgba(0,0,0,.06);border:1px solid #f0e6c8}
.card h3{margin:0 0 10px}.row{display:flex;gap:8px}input{flex:1;padding:12px;border-radius:12px;border:1.5px solid #eee;font-size:14px;outline:none}input:focus{border-color:#111}
button{background:#111;color:#fff;border:0;padding:12px 16px;border-radius:12px;font-weight:800;cursor:pointer}
.ex{font-size:12px;color:#777;margin:10px 0 0}.try{display:flex;gap:8px;margin-top:10px}.try a{font-size:12px;background:#FFF6C9;border:1px solid #eee;border-radius:999px;padding:6px 10px;text-decoration:none}
.blobbox{background:#FFF6C9;border-radius:20px;padding:16px;position:relative;overflow:hidden}
.pile{position:relative;height:260px}.pile-blob{position:absolute;border-radius:50% 50% 46% 54%;display:flex;align-items:center;justify-content:center;flex-direction:column;box-shadow:inset -6px -6px 0 rgba(0,0,0,.05)}
.eyes{display:flex;gap:7px}.eye{width:7px;height:8px;background:#111;border-radius:50%}.mouth{width:12px;height:6px;border:2px solid #111;border-top:0;border-radius:0 0 10px 10px;margin-top:2px}
.verdict{margin-top:12px;background:#111;color:#fff;border-radius:999px;padding:8px 12px;font-size:12px;font-weight:800;text-align:center;letter-spacing:.4px}
.three{max-width:1080px;margin:16px auto 0;padding:0 16px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.mini{background:#fff;border-radius:16px;padding:14px;border:1px solid #f0e6c8}.mini b{font-size:14px}.mini p{margin:6px 0 0;font-size:13px;color:#666;line-height:1.5}
.how{max-width:1080px;margin:16px auto 0;padding:0 16px}.how-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:10px}
.agents{max-width:1080px;margin:16px auto 0;padding:0 16px}.code{background:#111;color:#E8FFB0;border-radius:14px;padding:14px;font-family:ui-monospace,monospace;font-size:12.5px;line-height:1.6;overflow:auto;white-space:pre}
.foot{max-width:1080px;margin:16px auto 0;padding:0 16px 90px;display:flex;justify-content:space-between;font-size:12px;color:#888}
.track{position:fixed;left:0;right:0;bottom:0;height:64px;background:transparent;pointer-events:none;overflow:hidden;z-index:50}
.runner{position:absolute;bottom:8px;left:-80px;animation:run 16s linear infinite}.rblob{width:46px;height:46px;border-radius:50% 50% 46% 54%;display:flex;align-items:center;justify-content:center;flex-direction:column;animation:jump .6s ease-in-out infinite alternate}
@keyframes run{from{left:-80px}to{left:110%}}
@keyframes jump{from{transform:translateY(0)}to{transform:translateY(-14px)}}
@media(max-width:760px){.hero{grid-template-columns:1fr}h1{font-size:36px}.three,.how-grid{grid-template-columns:1fr}.nav{display:none}}
</style></head>
<body>
<div class='top'><div class='logo'>TVibe<span>.</span></div><div class='nav'><a href='#how'>How it works</a><a href='#what'>What we check</a><a href='#agents'>For Agents</a></div></div>
<div class='hero'>
<div><div style='font-size:11px;letter-spacing:1px;color:#888'>SOLANA TOKEN CHECK - REAL NUMBERS, NO HYPE</div><h1>Check a token<br>before you buy.</h1><p class='sub'>Paste a Solana mint. Get a clear verdict - <b>PASS / HOLD-BUY / SELL</b> - plus real price, liquidity, volume and risk in seconds. No hype. No guess.</p><div class='pills'><span class='pill'>English only</span><span class='pill'>Agent-ready JSON</span></div>
<div class='card'><h3>Check a token</h3><form action='/pro' method='get' class='row'><input name='mint' placeholder='Enter a Solana mint address...'><button>CHECK</button></form><p class='ex'>Example: Fartcoin - try a token you know.</p><div class='try'><a href='/pro'>Try PRO</a><a href='/pro_status'>Pro Status</a><a href='/health'>Health</a></div></div>
</div>
<div><div class='blobbox'><div class='pile'>
<div class='pile-blob' style='left:8%;top:8%;width:64px;height:64px;background:#FF9AA2'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div>
<div class='pile-blob' style='left:28%;top:2%;width:58px;height:58px;background:#FFD6A5'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div>
<div class='pile-blob' style='left:48%;top:10%;width:70px;height:70px;background:#FDFFB6'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div>
<div class='pile-blob' style='left:68%;top:4%;width:52px;height:52px;background:#CAFFBF'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div>
<div class='pile-blob' style='left:82%;top:18%;width:60px;height:60px;background:#9BF6FF'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div>
<div class='pile-blob' style='left:14%;top:42%;width:56px;height:56px;background:#BDB2FF'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div>
<div class='pile-blob' style='left:36%;top:44%;width:62px;height:62px;background:#FFC6FF'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div>
<div class='pile-blob' style='left:58%;top:46%;width:54px;height:54px;background:#FFAFCC'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div>
<div class='pile-blob' style='left:74%;top:50%;width:66px;height:66px;background:#A0C4FF'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div>
<div class='pile-blob' style='left:22%;top:70%;width:50px;height:50px;background:#B5E48C'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div>
<div class='pile-blob' style='left:46%;top:72%;width:58px;height:58px;background:#FFD166'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div>
<div class='pile-blob' style='left:66%;top:74%;width:52px;height:52px;background:#FF8FA3'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div>
</div><div class='verdict'>PASS - HOLD-BUY - SELL</div></div></div>
</div>
<div class='three' id='what'><div class='mini'><b>Liquidity - can you sell?</b><p>We check how much money is actually in the pool, not just price. Low liquidity = you may not be able to sell.</p></div><div class='mini'><b>On-chain - who controls it?</b><p>Mint / freeze authorities, holder concentration, dev wallet. If one wallet controls it, it is risky.</p></div><div class='mini'><b>Price + Activity - is it pumping?</b><p>24h change, volume vs liquidity, and age. New + pumping + low liquidity = danger.</p></div></div>
<div class='how' id='how'><h3 style='margin:0'>How it works - 3 steps</h3><div class='how-grid'><div class='mini'><b>1. Paste mint</b><p>Copy the mint from DexScreener or your wallet.</p></div><div class='mini'><b>2. We check live data</b><p>Market data + on-chain authorities. No opinions, just numbers.</p></div><div class='mini'><b>3. Get your verdict</b><p>PASS = good setup. HOLD-BUY = mixed, small size. SELL = do not buy.</p></div></div></div>
<div class='agents' id='agents'><h3 style='margin:0 0 8px'>For Agents</h3><p style='font-size:13px;color:#666;margin:0 0 8px'>Use the JSON endpoint. No signup, no key needed.</p><div class='code'>GET /check?mint=...  /pro_json?mint=...
{
  "verdict": "avoid",
  "symbol": "FART",
  "price": 0.00012,
  "liquidity_usd": 12345,
  "top_holder": "12%",
  "flags": ["low_liquidity", "new_pair"]
}</div><p style='font-size:12px;color:#888'>PASS does not mean safe. Always check yourself.</p></div>
<div class='foot'><span>2026 TVibe - Check a token before you buy.</span><span>Data is real. Not financial advice.</span></div>
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

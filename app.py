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
<title>TVibe Signal - Check Solana Token</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#FFF6C9;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#222;padding:0 0 40px}
.wrap{max-width:860px;margin:0 auto;padding:18px 14px}
.header{display:flex;align-items:center;gap:12px}.logo{width:52px;height:52px;background:#111;color:#fff;border-radius:16px;display:flex;align-items:center;justify-content:center;font-size:28px;transform:rotate(-4deg)}
h1{margin:0;font-size:32px;letter-spacing:-0.5px}.sub{color:#6b5d3f;margin:6px 0 14px;font-size:14px}
.stage{background:#fff;border-radius:20px;padding:14px 14px 8px;overflow:hidden;position:relative;box-shadow:0 6px 20px rgba(0,0,0,.06);border:2px solid #ffe9a8}
.stage-title{font-weight:800;font-size:13px;letter-spacing:.6px;color:#8a7a4a}
.track{position:relative;height:110px;margin-top:8px;overflow:hidden;background:#FFF6C9;border-radius:14px}
.runner{position:absolute;bottom:12px;left:-80px;animation:run 14s linear infinite}
.blob{width:56px;height:56px;border-radius:50% 50% 46% 54%;display:flex;align-items:center;justify-content:center;flex-direction:column;animation:jump .7s ease-in-out infinite alternate;box-shadow:inset -6px -6px 0 rgba(0,0,0,.06)}
.eyes{display:flex;gap:8px}.eye{width:8px;height:9px;background:#111;border-radius:50%}.mouth{width:14px;height:7px;border:2px solid #111;border-top:0;border-radius:0 0 12px 12px;margin-top:3px}
.b1{background:#FF9AA2}.b2{background:#FFD6A5}.b3{background:#FDFFB6}.b4{background:#CAFFBF}.b5{background:#9BF6FF}.b6{background:#BDB2FF}.b7{background:#FFC6FF}
.r1{animation-delay:0s}.r1 .blob{animation-delay:0s}
.r2{animation-delay:1.8s}.r2 .blob{animation-delay:.1s}
.r3{animation-delay:3.6s}.r3 .blob{animation-delay:.2s}
.r4{animation-delay:5.4s}.r4 .blob{animation-delay:.3s}
.r5{animation-delay:7.2s}.r5 .blob{animation-delay:.4s}
.r6{animation-delay:9s}.r6 .blob{animation-delay:.5s}
.r7{animation-delay:10.8s}.r7 .blob{animation-delay:.6s}
@keyframes run{0%{left:-80px;transform:rotate(0)}45%{left:88%}50%{left:88%;transform:rotate(0)}55%{left:88%}100%{left:-80px;transform:rotate(-360deg)}}
@keyframes jump{from{transform:translateY(0) scale(1,1)}to{transform:translateY(-18px) scale(.96,1.05)}}
.card{background:#fff;border-radius:20px;padding:16px;margin:14px 0;box-shadow:0 6px 20px rgba(0,0,0,.06);border:2px solid #ffe9a8}
.card h3{margin:0 0 10px}.row{display:flex;gap:8px}input{flex:1;padding:12px;border-radius:12px;border:1.5px solid #eee;font-size:15px;outline:none}input:focus{border-color:#111}
button{background:#111;color:#fff;border:0;padding:12px 16px;border-radius:12px;font-weight:800;cursor:pointer}
.pills{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.pill{background:#111;color:#fff;padding:9px 13px;border-radius:999px;text-decoration:none;font-size:13px;font-weight:700}.pill.light{background:#FFF6C9;color:#111;border:1.5px solid #111}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}.feat{background:#FFF6C9;border-radius:16px;padding:12px}.feat b{font-size:14px}.feat p{margin:6px 0 0;font-size:12.5px;color:#6b5d3f;line-height:1.5}
.note{font-size:12px;color:#8a7a4a;text-align:center;margin-top:10px}
@media(max-width:520px){.grid{grid-template-columns:1fr}h1{font-size:26px}}
</style></head>
<body><div class='wrap'>
<div class='header'><div class='logo'>&#9679;</div><div><h1>TVibe Signal</h1><div class='sub'>Check a Solana token before you buy. PASS does not mean safe.</div></div></div>
<div class='stage'><div class='stage-title'>7 FRIENDS ON PATROL - THEY CHECK, YOU DECIDE</div><div class='track'>
<div class='runner r1'><div class='blob b1'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
<div class='runner r2'><div class='blob b2'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
<div class='runner r3'><div class='blob b3'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
<div class='runner r4'><div class='blob b4'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
<div class='runner r5'><div class='blob b5'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
<div class='runner r6'><div class='blob b6'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
<div class='runner r7'><div class='blob b7'><div class='eyes'><div class='eye'></div><div class='eye'></div></div><div class='mouth'></div></div></div>
</div></div>
<div class='card'><h3>Check token</h3><form action='/pro' method='get' class='row'><input name='mint' placeholder='Paste Solana mint'><button>Check PRO</button></form><p style='font-size:13px;color:#6b5d3f'>Paste mint, then see Grade + Holder / LP / Dev. Example: try a token you know.</p><div class='pills'><a class='pill' href='/pro'>PRO</a><a class='pill' href='/pro_status'>Pro Status</a><a class='pill' href='/health'>Health</a><a class='pill light' href='/play'>Playground</a></div></div>
<div class='card'><h3>What PRO checks</h3><div class='grid'><div class='feat'><b>Holder & Top holder</b><p>Who holds most? Top 1% + Top 10% + concentration. Bundle risk if one wallet holds too much.</p></div><div class='feat'><b>LP Lock</b><p>Is liquidity locked / burned? Unlocked LP = dev can pull.</p></div><div class='feat'><b>Dev & Authority</b><p>Creator, dev holds, mint / freeze authority still on or revoked?</p></div><div class='feat'><b>Grade A-F</b><p>One grade + 5 breakdowns: Market / Holder / LP / Dev / Authority. No hidden thresholds.</p></div></div><div class='pills'><a class='pill light' href='/compare'>Compare 2 tokens</a><a class='pill light' href='/batch'>Batch 5 tokens</a><a class='pill light' href='/pro_json'>Agent JSON</a></div></div>
<div class='note'>PASS does not mean safe. Always check yourself. &bull; TVibe Signal</div>
</div></body></html>
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

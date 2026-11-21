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
    _HOME_HTML2 = ("<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>TVibe Signal</title>"
        "<style>body{background:#FFF6C9;font-family:system-ui;padding:20px;color:#222}input{padding:10px;width:78%;border-radius:10px;border:1px solid #ddd}a,button{background:#111;color:#fff;padding:10px 14px;border-radius:10px;text-decoration:none;border:0}.card{background:#fff;border-radius:16px;padding:16px;margin:14px 0}</style></head>"
        "<body><h1>TVibe Signal</h1><p>Check a Solana token before you buy. PASS does not mean safe.</p>"
        "<div class='card'><h3>Check token</h3><form action='/pro' method='get'><input name='mint' placeholder='Paste Solana mint'><button>Check PRO</button></form>"
        "<p style='font-size:13px'>Paste mint, then see Grade + Holder / LP / Dev.</p></div>"
        "<div class='card'><h3>Quick links</h3><p><a href='/pro_status'>Pro Status</a> &nbsp; <a href='/health'>Health</a> &nbsp; <a href='/play'>Playground</a> &nbsp; <a href='/pro'>PRO</a></p>"
        "<p style='font-size:13px'>Agent JSON: /pro_json?mint=... &nbsp; Compare: /compare?mint1=...&mint2=...</p></div>"
        "<p style='font-size:12px;color:#7A6A55'>PASS does not mean safe. Always check yourself.</p></body></html>")
    # 1) Middleware - intercepts / BEFORE any other middleware / fallback
    try:
        @app.middleware("http")
        async def _fix_root_mw(request, call_next):
            try:
                p = getattr(getattr(request, "url", None), "path", "") or ""
            except Exception:
                p = ""
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

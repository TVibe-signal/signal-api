"""app.py — TVibe Signal entrypoint for Render (uvicorn app:app).

Clean Merged File 1+2 (filtered): Loader + PRO V43 Premium only. Kept = core/features/extensions + patch_live_fix + PRO. Filtered = patch_stats_fix, patch_p0, /holders, /check_pro, /grade (dup of /pro_json). Loader + PRO V43 Premium inline. Upload ONLY this file as app.py. Loads the full stack into one shared namespace:
  core_final → features → extensions → optional patches

Do NOT use the old standalone "cute" app body here — that removed /omni and track-record.
"""
from __future__ import annotations

import os
import sys
import re
import traceback
from urllib.parse import quote as _urlquote
from fastapi import Request  # module-level: FastAPI resolves 'Request' annotations from module globals

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
    import pro_engine as _pe

    def _core_rpc():
        # keep compatibility with RPC urls that the core layer already resolved
        if isinstance(g, dict):
            for k in ("HELIUS_URL", "SOLANA_RPC_URL", "PRIVATE_RPC", "PRIVATE_RPC_URL", "RPC_URL"):
                v = g.get(k)
                if isinstance(v, str) and v.startswith("http"):
                    return v
        return ""
    _pe.set_rpc_resolver(_core_rpc)

    def pro_premium(mint):
        return _pe.analyze(mint)
    from fastapi import Query
    from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
    def _guard(request, cost=1):
        ok, retry, scope = _pe.allow_request(_pe.client_ip(request), cost)
        if ok:
            return None
        return JSONResponse({"error": "rate_limited", "scope": scope, "retry_after_s": retry},
                            status_code=429, headers={"Retry-After": str(retry)})

    def _json(o):
        if isinstance(o, dict) and o.get("status") == "source_error":
            return JSONResponse(o, status_code=503, headers={"Retry-After": "20"})
        return JSONResponse(o)

    @app.get("/pro_status")
    def pro_status():
        return {"pro_v45": True, "pro_v43_premium": True,
                "routes": ["/pro", "/pro_json", "/omni_pro", "/compare", "/batch", "/check"],
                "engine": _pe.status(),
                "note": "PRO engine v45: owner-resolved holders, oldest-tx creator, burn-only LP safe, unverified when data is missing"}

    _ASSET_RE = re.compile(r"^blob-[0-9a-f]{10}\.png$")

    @app.get("/assets/{fname}")
    def _asset(fname: str):
        if not _ASSET_RE.match(fname):
            return JSONResponse({"error": "not_found"}, status_code=404)
        p = os.path.join(ROOT, "assets", fname)
        if not os.path.isfile(p):
            return JSONResponse({"error": "not_found"}, status_code=404)
        return FileResponse(p, media_type="image/png",
                            headers={"Cache-Control": "public, max-age=31536000, immutable"})

    @app.get("/pro")
    def pro_html(request: Request, mint: str = Query(default="")):
        m=(mint or "").strip()
        if not m: return HTMLResponse("<h3>Need mint</h3><p>Paste Solana mint: /pro?mint=...</p>", status_code=400)
        if not _pe.valid_mint(m): return HTMLResponse("<h3>Not a valid mint</h3><p>A Solana mint is a base58 address of 32-44 characters. Example: /pro?mint=DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263</p>", status_code=400)
        _blk=_guard(request)
        if _blk is not None: return HTMLResponse("<h3>Too many checks</h3><p>Please wait a little and try again.</p>", status_code=429, headers={"Retry-After": _blk.headers.get("retry-after","30")})
        o=pro_premium(m)
        if o.get("status")=="source_error": return HTMLResponse("<h3>Market data is busy</h3><p>Try again in about a minute.</p>", status_code=503, headers={"Retry-After":"20"})
        if o.get("status") in ("not_found","invalid"): return HTMLResponse("<html><head><meta charset=utf-8><meta name=viewport content=width=device-width,initial-scale=1><title>Not found</title><style>body{margin:0;background:#FFF8E6;font-family:system-ui;padding:20px} .card{max-width:560px;margin:40px auto;background:#fff;border-radius:20px;padding:22px;text-align:center} a{display:inline-block;background:#111;color:#fff;padding:10px 16px;border-radius:999px;text-decoration:none;margin-top:12px}</style></head><body><div class=card><h2>Not found</h2><p>No pair for this mint. Token may be new or wrong mint.</p><a href=/>Back home</a></div></body></html>", status_code=404)
        bd=o.get("breakdown") or {}; risks=o.get("risks") or {}; h=o.get("holders") or {}; l=o.get("lp_lock") or {}; d=o.get("dev") or {}
        sym=str(o.get("symbol") or "?"); grade=str(o.get("grade") or "?"); label=str(o.get("label") or "")
        risk=int(o.get("risk_score") or 0)
        # Badge color by verdict
        if label=="PASS" or grade in ("A","B"):
            badge_bg="#E8FCE8"; badge_bd="#9BE39B"; badge_txt="#1A6A1A"; verdict_txt="OK TO BUY"; verdict_sub="Setup looks good on these checks. Still use a size you can afford to lose."; action_txt="If you buy: use normal size you can afford to lose. Not 100% safe."; action_bg="#E8FCE8"
        elif label=="SELL" or grade in ("D","F"):
            badge_bg="#FFE8E8"; badge_bd="#FF9AA2"; badge_txt="#A11"; verdict_txt="DON'T BUY"; verdict_sub="Too risky on these checks."; action_txt="Don't buy. Wait for a better setup."; action_bg="#FFE8E8"
        else:
            badge_bg="#FFF6C9"; badge_bd="#F0D060"; badge_txt="#7A5A00"; verdict_txt="NOT A CLEAR YES"; verdict_sub="Mixed. Only small size if you buy."; action_txt="If you buy: SMALL size only. Don't ape. If it drops, cut."; action_bg="#FFF6C9"
        def bar(v):
            vv=max(0,min(100,int(v or 0)))
            col="#22C55E" if vv<30 else ("#FACC15" if vv<60 else "#F97316")
            return f"<div style=\"background:#F1EAD0;border-radius:999px;height:12px;overflow:hidden\"><div style=\"width:{vv}%;background:{col};height:12px;border-radius:999px\"></div></div>"
        def row(name, val):
            return f"<div style=\"display:flex;justify-content:space-between;font-size:13px;margin:2px 0\"><span style=\"color:#666\">{name}</span><b>{val}</b></div>{bar(val)}<div style=\"height:10px\"></div>"
        liq=int(o.get("liquidity_usd") or 0); vol=int(o.get("volume_24h") or 0); age=o.get("age_h")
        try: age_s=f"{float(age):.1f}h"
        except: age_s=str(age or "?")
        # 7 blob runners for pro page - reuse same blob images (injected via placeholder, replaced below)
        blobs_html_pro = """<div class='blob-run' style='animation:wanderLR 11s linear infinite;animation-delay:0s'><img src='/assets/blob-5406cf7843.png' style='width:62px;height:auto;display:block' alt='blob teal'></div>
<div class='blob-run' style='animation:wanderRL 13s linear infinite;animation-delay:-2s'><img src='/assets/blob-9a83c61405.png' style='width:56px;height:auto;display:block' alt='blob orange'></div>
<div class='blob-run' style='animation:wanderLR 12s linear infinite;animation-delay:-4s'><img src='/assets/blob-1db680f448.png' style='width:66px;height:auto;display:block' alt='blob purple'></div>
<div class='blob-run' style='animation:orbit 16s linear infinite;animation-delay:-1s'><img src='/assets/blob-b5ba2dfede.png' style='width:58px;height:auto;display:block' alt='blob blue'></div>
<div class='blob-run' style='animation:wanderRL 11.5s linear infinite;animation-delay:-6s'><img src='/assets/blob-b9aa4d9a62.png' style='width:60px;height:auto;display:block' alt='blob green'></div>
<div class='blob-run' style='animation:wanderLR 14s linear infinite;animation-delay:-3s'><img src='/assets/blob-1495e2fe71.png' style='width:54px;height:auto;display:block' alt='blob pink'></div>
<div class='blob-run' style='animation:wanderRL 12.5s linear infinite;animation-delay:-8s'><img src='/assets/blob-4b0ce8cb62.png' style='width:62px;height:auto;display:block' alt='blob yellow'></div>
<div class='blob-run' style='animation:wanderLR 13.5s linear infinite;animation-delay:-5s'><img src='/assets/blob-80bfeec6c9.png' style='width:60px;height:auto;display:block' alt='blob red'></div>
<div class='blob-run' style='animation:orbit 18s linear infinite;animation-delay:-7s'><img src='/assets/blob-ddb63a1dc0.png' style='width:64px;height:auto;display:block' alt='blob brown'></div>
"""
        # Human reasons - plain English for normal buyers, not pros
        try: age_f=999 if age is None else float(age)
        except: age_f=999
        lp_unknown = str(l.get("status") or "").lower() in ("unknown","unverified","none","")
        _reasons=[]
        if age is None: _reasons.append("Token age unknown - treat as risky")
        if label=="UNVERIFIED": _reasons.append("On-chain data unavailable - could not verify holders / authorities")
        try: _ratio=float(vol)/float(liq) if liq>0 else 0
        except: _ratio=0
        if age_f<24:
            _reasons.append(f"Token is only {age_s} old - very new")
        elif age_f<72:
            _reasons.append(f"Token is {age_s} old - still new")
        if lp_unknown:
            _reasons.append("LP lock NOT verified - dev could pull liquidity")
        elif str(l.get("status") or "")=="unlocked":
            _reasons.append("LP is NOT locked - dev can pull liquidity")
        elif str(l.get("status") or "")=="partial":
            _reasons.append("LP is only partly burned")
        elif str(l.get("status") or "")=="single_wallet":
            _reasons.append("LP is held by one wallet and NOT burned - it can be pulled")
        if _ratio>30:
            _reasons.append(f"Volume is {int(_ratio)}x liquidity - looks washed / too high")
        elif _ratio>8:
            _reasons.append(f"Volume is {int(_ratio)}x liquidity - quite high")
        _t1=float(h.get("top1_pct") or 0); _t10=float(h.get("top10_pct") or 0)
        if _t1>20:
            _reasons.append(f"1 wallet holds {_t1:.1f}% - whale risk")
        elif _t1>10:
            _reasons.append(f"1 wallet holds {_t1:.1f}% - watch it")
        if _t10>50:
            _reasons.append(f"Top 10 wallets hold {_t10:.1f}% - concentrated")
        elif _t10>35:
            _reasons.append(f"Top 10 wallets hold {_t10:.1f}% - a bit concentrated")
        if d.get("dev_holds_pct") is None:
            _reasons.append("We don't know how much dev holds")
        elif float(d.get("dev_holds_pct") or 0)>10:
            _reasons.append(f"Dev holds {float(d.get('dev_holds_pct')):.1f}% - high")
        _on=o.get("onchain") or {}
        if _on.get("freeze_authority") is not None:
            _reasons.append("Dev can still freeze - could block selling")
        if _on.get("mint_authority") is not None:
            _reasons.append("Dev can still mint more tokens")
        if not _reasons:
            _reasons.append("No big red flag on these checks")
        _reasons_html="".join([f"<li style='margin:4px 0'>{r}</li>" for r in _reasons[:4]])
        caution_html = f"<div style='background:#fff;border:1.5px solid #F0E6C8;border-radius:14px;padding:12px;text-align:left;margin:12px 0'><b>Why in plain English:</b><ul style='margin:6px 0 0 18px;padding:0;font-size:13px;color:#333'>{_reasons_html}</ul></div><div style='background:{action_bg};border:1.5px solid #E5D5A0;border-radius:14px;padding:10px 12px;font-size:13px;text-align:left'><b>What to do:</b> {action_txt}</div>"
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TVibe PRO {sym}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#FFF8E6;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#111;line-height:1.5;padding-bottom:30px}}
.blob-run{{position:fixed;left:-180px;z-index:1;pointer-events:none;animation-name:runAround;animation-timing-function:linear;animation-iteration-count:infinite}}
.blob-run img{{animation:bob .8s ease-in-out infinite alternate}}

.blob-run{{position:fixed;z-index:1;pointer-events:none;opacity:.95}}
.blob-run img{{animation:bob .9s ease-in-out infinite alternate}}
@keyframes bob{{from{{transform:translateY(0) scale(1) rotate(-2deg)}}to{{transform:translateY(-12px) scale(1.04) rotate(2deg)}}}}
@keyframes wanderLR{{0%{{left:-12vw;top:12vh;transform:rotate(-6deg)}}15%{{top:4vh;transform:rotate(4deg)}}30%{{top:22vh;transform:rotate(-3deg)}}45%{{top:8vh;transform:rotate(5deg)}}60%{{top:28vh;transform:rotate(-4deg)}}75%{{top:12vh;transform:rotate(3deg)}}90%{{top:20vh;transform:rotate(-2deg)}}100%{{left:110vw;top:14vh;transform:rotate(6deg)}}}}
@keyframes wanderRL{{0%{{left:110vw;top:18vh;transform:rotate(6deg)}}15%{{top:30vh;transform:rotate(-4deg)}}30%{{top:8vh;transform:rotate(3deg)}}45%{{top:24vh;transform:rotate(-5deg)}}60%{{top:6vh;transform:rotate(4deg)}}75%{{top:26vh;transform:rotate(-3deg)}}90%{{top:10vh;transform:rotate(2deg)}}100%{{left:-12vw;top:20vh;transform:rotate(-6deg)}}}}
@keyframes orbit{{0%{{left:8vw;top:10vh;transform:rotate(0deg)}}20%{{left:78vw;top:6vh;transform:rotate(8deg)}}40%{{left:88vw;top:58vh;transform:rotate(-8deg)}}60%{{left:42vw;top:78vh;transform:rotate(6deg)}}80%{{left:4vw;top:52vh;transform:rotate(-6deg)}}100%{{left:8vw;top:10vh;transform:rotate(0deg)}}}}
@keyframes runAround{{0%{{left:-180px;transform:translateY(0) rotate(-4deg)}}25%{{transform:translateY(-18px) rotate(3deg)}}50%{{transform:translateY(10px) rotate(-2deg)}}75%{{transform:translateY(-14px) rotate(2deg)}}100%{{left:110vw;transform:translateY(0) rotate(-4deg)}}}}
@keyframes bob{{from{{transform:translateY(0) scale(1)}}to{{transform:translateY(-10px) scale(1.03)}}}}
.wrap{{max-width:680px;margin:0 auto;padding:16px;position:relative;z-index:2}}
.top{{text-align:center;font-size:11px;letter-spacing:1.2px;font-weight:800;color:#888;margin:8px 0 10px}}
.card{{background:#fff;border-radius:22px;padding:20px;border:1px solid #F0E6C8;box-shadow:0 10px 30px rgba(0,0,0,.06)}}
.badge{{background:{badge_bg};border:1.5px solid {badge_bd};color:{badge_txt};border-radius:999px;padding:8px 14px;font-weight:900;font-size:14px;display:inline-block}}
.kpi{{display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin:14px 0}}
.kpi div{{background:#FFF8E6;border:1px solid #F0E6C8;border-radius:14px;padding:10px;text-align:center}}
.kpi b{{font-size:15px;display:block}} .kpi span{{font-size:11px;color:#888}}
.mini{{background:#fff;border:1px solid #F0E6C8;border-radius:16px;padding:14px;margin-top:10px}}
.mini h3{{margin:0 0 8px;font-size:15px}}
.btn{{display:inline-block;background:#111;color:#fff;border-radius:999px;padding:10px 16px;text-decoration:none;font-weight:800;font-size:13px;margin:4px 4px 0 0}}
input{{padding:12px;border-radius:12px;border:1.5px solid #EEE;width:70%;font-size:14px}}
@media(max-width:640px){{.kpi{{grid-template-columns:1fr 1fr}}}}
</style></head><body>
<div class="blob-layer">{blobs_html_pro}</div>
<div class="wrap"><div class="top">TVIBE PRO - CHECK BEFORE YOU BUY</div>
<div class="card" style="text-align:center"><div class="badge">{sym} - Grade {grade} - {label}</div><h1 style="margin:10px 0 6px;font-size:32px">{verdict_txt}</h1><p style="color:#666;margin:0;font-size:14px">{verdict_sub}</p>
<div class="kpi"><div><b>Risk {risk}/100</b><span>Risk score</span></div><div><b>${liq:,}</b><span>Liquidity</span></div><div><b>${vol:,}</b><span>Volume 24h</span></div><div><b>{age_s}</b><span>Age</span></div></div>
{caution_html}<div style="text-align:left"><h3 style="margin:0 0 2px">Breakdown</h3><p style="margin:0 0 8px;color:#888;font-size:12px">Low = good. Empty bar = score 0, not broken.</p>{row("Market - How new + volume", bd.get("market") or 0)}{row("Holder - Whale risk", bd.get("holder") or 0)}{row("LP - Can dev pull?", bd.get("lp") or 0)}{row("Dev - Dev holds", bd.get("dev") or 0)}{row("Authority - Can dev mint / freeze?", bd.get("authority") or 0)}</div>
</div>
<div class="mini"><h3>Advanced Risks - In plain English</h3><p style="margin:0;color:#555;font-size:13px">Many wallets, 1 person? <b>{risks.get("bundle")}</b> &nbsp;|&nbsp; Can you sell? <b>{risks.get("honeypot")}</b> &nbsp;|&nbsp; Bot bought first? <b>{risks.get("sniper")}</b></p><p style="margin:6px 0 0;color:#888;font-size:12px">low = no sign found. medium/high = be careful.</p></div>
<div class="mini"><h3>Holders - Who holds it?</h3><p style="margin:0;color:#555;font-size:14px">1 wallet holds <b>{h.get("top1_pct")}%</b> &nbsp;|&nbsp; Top 10 hold <b>{h.get("top10_pct")}%</b></p><p style="margin:6px 0 0;color:#888;font-size:12px">If 1 wallet holds a lot, it can dump on you.</p></div>
<div class="mini"><h3>LP Lock - Can dev pull the money?</h3><p style="margin:0;color:#555;font-size:14px">Status: <b>{l.get("status")}</b> &nbsp;|&nbsp; {l.get("note") or ""}</p><p style="margin:6px 0 0;color:#888;font-size:12px">Locked = safer. Unknown / unlocked = dev could pull.</p></div>
<div class="mini"><h3>Dev - Who made it?</h3><p style="margin:0;color:#555;font-size:14px">{d.get("creator_short") or "Unknown"} &nbsp;|&nbsp; Tx: <b>{d.get("tx_count")}</b> &nbsp;|&nbsp; Holds: <b>{d.get("dev_holds_pct")}%</b></p><p style="margin:6px 0 0;color:#888;font-size:12px">If dev holds a lot or is brand new, be careful.</p></div>
<p style="font-size:12px;color:#888;text-align:center;margin:14px 0">Not financial advice. Even OK TO BUY does not mean safe. Always check yourself.</p>
<div style="text-align:center"><a class="btn" href="/">Back home</a><a class="btn" href="/pro_json?mint={m}">Agent JSON</a><a class="btn" href="/pro_status">Pro Status</a></div>
<form action="/pro" method="get" style="text-align:center;margin-top:14px"><input name="mint" placeholder="Paste another Solana mint"><button class="btn" style="border:0;cursor:pointer">Check again</button></form>
</div></body></html>"""
        return HTMLResponse(html)
    _BAD_MINT = {"error": "invalid_mint", "detail": "Expected a Solana mint: base58, 32-44 characters."}

    @app.get("/pro_json")
    def pro_json(request: Request, mint: str = Query(default="")):
        m=(mint or "").strip()
        if not m: return JSONResponse({"error":"need mint"}, status_code=400)
        if not _pe.valid_mint(m): return JSONResponse(_BAD_MINT, status_code=400)
        blk=_guard(request)
        if blk is not None: return blk
        return _json(pro_premium(m))

    @app.get("/omni_pro")
    def omni_pro(request: Request, mint: str = Query(default="")):
        m=(mint or "").strip()
        if not m: return JSONResponse({"error":"need mint"}, status_code=400)
        if not _pe.valid_mint(m): return JSONResponse(_BAD_MINT, status_code=400)
        blk=_guard(request)
        if blk is not None: return blk
        o=pro_premium(m); o["omni_pro"]=True; o["view"]="agent"
        return _json(o)

    @app.get("/compare")
    def compare_ep(request: Request, mint1: str = Query(default=""), mint2: str = Query(default="")):
        m1=(mint1 or "").strip(); m2=(mint2 or "").strip()
        if not (_pe.valid_mint(m1) and _pe.valid_mint(m2)): return JSONResponse({"error":"need two valid mints: /compare?mint1=...&mint2=..."}, status_code=400)
        blk=_guard(request, 2)
        if blk is not None: return blk
        a,b=_pe.analyze_many([m1,m2])
        ok=lambda x: x.get("status") in ("ok","partial") and x.get("risk_score") is not None
        note=None; w=None
        if ok(a) and ok(b):
            if a["verdict"]=="avoid" and b["verdict"]=="avoid": note="Both look risky - neither is a good pick."
            w=a.get("symbol") if a["risk_score"]<=b["risk_score"] else b.get("symbol")
        else: note="Could not fully score both tokens - no winner picked."
        return {"a":a,"b":b,"winner":w,"note":note}

    @app.get("/batch")
    def batch_ep(request: Request, mints: str = Query(default="")):
        parts=list(dict.fromkeys(pp.strip() for pp in (mints or "").split(",") if pp.strip()))[:5]
        good=[p for p in parts if _pe.valid_mint(p)]; bad=[p[:50] for p in parts if not _pe.valid_mint(p)]
        if not good: return JSONResponse({"error":"need mints=mint1,mint2 (valid Solana mints)","invalid":bad}, status_code=400)
        blk=_guard(request, len(good))
        if blk is not None: return blk
        out=_pe.analyze_many(good)
        out_sorted=sorted(out, key=lambda x: float(x.get("risk_score") if x.get("risk_score") is not None else 999))
        return {"count":len(out),"sorted_safest_first":out_sorted,"all":out,"invalid":bad}

    if "/check" not in paths:
        @app.get("/check")
        def check_ep(request: Request, mint: str = Query(default="")):
            m=(mint or "").strip()
            if not m: return JSONResponse({"error":"need mint"}, status_code=400)
            if not _pe.valid_mint(m): return JSONResponse(_BAD_MINT, status_code=400)
            blk=_guard(request)
            if blk is not None: return blk
            return _json(_pe.agent_view(pro_premium(m)))
    print("[pro_v45] premium applied: /pro /pro_json /omni_pro /compare /batch /check /assets")
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
.blob-run{position:fixed;left:-180px;z-index:1;opacity:.92;pointer-events:none;animation-name:runAround;animation-timing-function:linear;animation-iteration-count:infinite}
.blob-run img{animation:bob .8s ease-in-out infinite alternate}
@keyframes runAround{0%{left:-180px;transform:translateY(0) rotate(-4deg)}25%{transform:translateY(-18px) rotate(3deg)}50%{transform:translateY(10px) rotate(-2deg)}75%{transform:translateY(-14px) rotate(2deg)}100%{left:110vw;transform:translateY(0) rotate(-4deg)}}
@keyframes bob{from{transform:translateY(0) scale(1)}to{transform:translateY(-10px) scale(1.03)}}
.blob-run{position:fixed;z-index:1;pointer-events:none;opacity:.95}
.blob-run img{animation:bob .9s ease-in-out infinite alternate}
@keyframes bob{from{transform:translateY(0) scale(1) rotate(-2deg)}to{transform:translateY(-12px) scale(1.04) rotate(2deg)}}
@keyframes wanderLR{0%{left:-12vw;top:12vh;transform:rotate(-6deg)}15%{top:4vh;transform:rotate(4deg)}30%{top:22vh;transform:rotate(-3deg)}45%{top:8vh;transform:rotate(5deg)}60%{top:28vh;transform:rotate(-4deg)}75%{top:12vh;transform:rotate(3deg)}90%{top:20vh;transform:rotate(-2deg)}100%{left:110vw;top:14vh;transform:rotate(6deg)}}
@keyframes wanderRL{0%{left:110vw;top:18vh;transform:rotate(6deg)}15%{top:30vh;transform:rotate(-4deg)}30%{top:8vh;transform:rotate(3deg)}45%{top:24vh;transform:rotate(-5deg)}60%{top:6vh;transform:rotate(4deg)}75%{top:26vh;transform:rotate(-3deg)}90%{top:10vh;transform:rotate(2deg)}100%{left:-12vw;top:20vh;transform:rotate(-6deg)}}
@keyframes orbit{0%{left:8vw;top:10vh;transform:rotate(0deg)}20%{left:78vw;top:6vh;transform:rotate(8deg)}40%{left:88vw;top:58vh;transform:rotate(-8deg)}60%{left:42vw;top:78vh;transform:rotate(6deg)}80%{left:4vw;top:52vh;transform:rotate(-6deg)}100%{left:8vw;top:10vh;transform:rotate(0deg)}}


.eyes{display:flex;gap:7px}.eye{width:7px;height:8px;background:#111;border-radius:50%}.mouth{width:12px;height:6px;border:2px solid #111;border-top:0;border-radius:0 0 10px 10px;margin-top:2px}
}@keyframes jump{from{transform:translateY(0)}to{transform:translateY(-14px)}}
@media(max-width:820px){.hero{grid-template-columns:1fr}.hero h1{font-size:38px}.grid3,.verdicts,.stats{grid-template-columns:1fr}.grid2{grid-template-columns:1fr}.nav{display:none}}
</style>
<script>function fill(v){document.getElementById('mint').value=v;document.getElementById('mint').focus()}function copyTxt(id){var e=document.getElementById(id);navigator.clipboard.writeText(e.innerText);alert('Copied')}</script></head>
<body>
<div class='top'><div class='top-in'><div class='logo'>TVibe<span>.</span></div><div class='nav'><a href='#what'>What we check</a><a href='#verdicts'>Verdicts</a><a href='#compare'>Compare</a><a href='#agents'>For Agents</a><a href='#users'>For Users</a></div><a class='btn' href='#check'>Check now</a></div></div>
<div class='wrap'>
<div class='hero'>
<div><div class='eyebrow'>SOLANA TOKEN CHECK - REAL NUMBERS, NO HYPE</div><h1>Check a token<br>before <i>you buy.</i></h1><p class='sub'>Paste a Solana mint. Get a clear verdict - <b>PASS / HOLD-BUY / SELL</b> - plus real price, liquidity, volume, holder, LP and dev risk in seconds. No hype. No guess. Free, no signup.</p><div class='pills'><span class='pill'>English only</span><span class='pill'>Agent-ready JSON</span><span class='pill'>Live on-chain data</span></div>
<div class='card' id='check' style='margin-top:14px'><h3>Check a token</h3><form action='/pro' method='get' class='row'><input id='mint' name='mint' placeholder='Enter a Solana mint address...'><button class='check'>CHECK</button></form><p class='ex'>Example: paste a mint from DexScreener, Phantom or your wallet. Try one you know.</p><div class='try'><a href="javascript:fill('DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263')">Try example mint</a><a href='/pro'>PRO</a><a href='/pro_status'>Pro Status</a><a href='/health'>Health</a><a href='#agents'>Agent JSON</a></div></div>
<div class='stats'><div class='stat'><b>Live</b><span>Real price + liquidity</span></div><div class='stat'><b>6 checks</b><span>Market / Holder / LP / Dev</span></div><div class='stat'><b>No key</b><span>No signup needed</span></div><div class='stat'><b>Agent</b><span>JSON in 1 call</span></div></div>
</div>
<div><div class='blobbox'><div class='pile' style='height:auto;text-align:center'><img src='/assets/blob-018b1f1bbc.png' style='width:100%;max-width:360px;height:auto;display:block;margin:0 auto' alt='TVibe blobs'></div><div class='verdict'>PASS - HOLD-BUY - SELL</div><div class='mini-live'><b>What you get in 1 check</b><p>Grade A-F + 5 breakdowns: Market / Holder / LP / Dev / Authority. Plus flags: low liquidity, top holder, unlocked LP, mint still on, dev selling.</p></div></div></div>
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
<div class='grid2' style='margin-top:12px'><div class='card'><h3>Example - cURL</h3><div class='code' id='curl'>curl "https://signal-api-24q4.onrender.com/pro_json?mint=DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"</div><button class='btn' onclick="copyTxt('curl')">Copy cURL</button></div>
<div class='card'><h3>Example - Response (illustrative values)</h3><div class='code' id='resp'>{
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
If verdict is SELL / avoid, do NOT buy. If verdict is unverified (or confidence is low), do NOT size - retry later.
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
<div class='blob-layer'>
<div class='blob-run' style='animation:wanderLR 11s linear infinite;animation-delay:0s'><img src='/assets/blob-5406cf7843.png' style='width:62px;height:auto;display:block' alt='blob teal'></div>
<div class='blob-run' style='animation:wanderRL 13s linear infinite;animation-delay:-2s'><img src='/assets/blob-9a83c61405.png' style='width:56px;height:auto;display:block' alt='blob orange'></div>
<div class='blob-run' style='animation:wanderLR 12s linear infinite;animation-delay:-4s'><img src='/assets/blob-1db680f448.png' style='width:66px;height:auto;display:block' alt='blob purple'></div>
<div class='blob-run' style='animation:orbit 16s linear infinite;animation-delay:-1s'><img src='/assets/blob-b5ba2dfede.png' style='width:58px;height:auto;display:block' alt='blob blue'></div>
<div class='blob-run' style='animation:wanderRL 11.5s linear infinite;animation-delay:-6s'><img src='/assets/blob-b9aa4d9a62.png' style='width:60px;height:auto;display:block' alt='blob green'></div>
<div class='blob-run' style='animation:wanderLR 14s linear infinite;animation-delay:-3s'><img src='/assets/blob-1495e2fe71.png' style='width:54px;height:auto;display:block' alt='blob pink'></div>
<div class='blob-run' style='animation:wanderRL 12.5s linear infinite;animation-delay:-8s'><img src='/assets/blob-4b0ce8cb62.png' style='width:62px;height:auto;display:block' alt='blob yellow'></div>
<div class='blob-run' style='animation:wanderLR 13.5s linear infinite;animation-delay:-5s'><img src='/assets/blob-80bfeec6c9.png' style='width:60px;height:auto;display:block' alt='blob red'></div>
<div class='blob-run' style='animation:orbit 18s linear infinite;animation-delay:-7s'><img src='/assets/blob-ddb63a1dc0.png' style='width:64px;height:auto;display:block' alt='blob brown'></div>
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
                return _RR(url="/pro?mint=" + _urlquote(mint_q, safe=""), status_code=302)
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

# --- RESCUE v44: ALL fixed routes BEFORE catch-all /{mint} /{path:path} ---
# Root cause of /omni + /pro 404: core_final registers /{mint} and /{path:path}.
# Any route registered AFTER those is unreachable → plain "Not Found".
try:
    _rt = list(getattr(app.router, "routes", []) or [])

    def _is_catch(r):
        p = (getattr(r, "path", None) or "").rstrip("/")
        # path templates
        raw = getattr(r, "path", None) or ""
        if raw in ("/{mint}", "/{path:path}", "/{path}"):
            return True
        if "path:path" in raw:
            return True
        if raw == "/{mint}":
            return True
        return False

    _fixed, _catch = [], []
    for _r in _rt:
        (_catch if _is_catch(_r) else _fixed).append(_r)

    # Stable priority for agent + PRO + health (first match wins among equals)
    _prio = [
        "/omni", "/signal", "/signals", "/stats", "/health", "/mcp", "/ping",
        "/pro", "/pro_json", "/pro_status", "/omni_pro", "/compare", "/batch", "/check",
        "/cron/outcome", "/export", "/ledger", "/methodology", "/history",
        "/llms.txt", "/skill.json", "/rules", "/agent/playbook", "/docs", "/openapi.json",
        "/",
    ]
    _rank = {p: i for i, p in enumerate(_prio)}

    def _sort_key(r):
        p = getattr(r, "path", "") or ""
        return (_rank.get(p, 500), p)

    _fixed_sorted = sorted(_fixed, key=_sort_key)
    _new = _fixed_sorted + _catch
    try:
        app.router.routes[:] = _new
    except Exception:
        app.router.routes = _new
    try:
        if getattr(app, "routes", None) is not app.router.routes:
            app.routes = list(app.router.routes)
    except Exception:
        pass
    _front = [getattr(r, "path", "") for r in list(app.router.routes)[:20]]
    _has_omni = any(getattr(r, "path", "") == "/omni" for r in app.router.routes)
    print(f"[rescue-v44] routes={len(_new)} catch={len(_catch)} omni_present={_has_omni}")
    print(f"[rescue-v44] front={_front}")
except Exception as _e:
    print(f"[rescue-v44] FAILED: {_e}")


# --- RESCUE: /stats never hard-500 for public UI ---
try:
    from fastapi import Request
    from fastapi.responses import JSONResponse
    import inspect as _inspect_v44

    _stats_ep = None
    for _r in list(getattr(app.router, "routes", []) or []):
        if getattr(_r, "path", None) == "/stats" and hasattr(_r, "endpoint"):
            _stats_ep = _r.endpoint
            _stats_route = _r
            break

    if _stats_ep is not None:
        async def _stats_soft(request: Request = None):
            try:
                if request is not None and "request" in str(_inspect_v44.signature(_stats_ep)):
                    out = await _stats_ep(request)
                else:
                    try:
                        out = await _stats_ep()
                    except TypeError:
                        out = await _stats_ep(request)
                return out
            except Exception as e:
                return JSONResponse(
                    {
                        "available": False,
                        "error": "stats_partial",
                        "detail": str(e)[:200],
                        "hint": "Try /pro_json?mint=… or /health; track-record recovering",
                        "nfa": True,
                    },
                    status_code=200,
                )

        _stats_route.endpoint = _stats_soft
        dep = getattr(_stats_route, "dependant", None)
        if dep is not None:
            try:
                dep.call = _stats_soft
            except Exception:
                pass
        print("[rescue-v44] /stats soft-wrapper installed")
    else:
        print("[rescue-v44] /stats route not found to wrap")
except Exception as _e:
    print(f"[rescue-v44] stats wrap FAILED: {_e}")

print("[rescue-v44] done")

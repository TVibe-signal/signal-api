"""app.py — TVibe Signal entrypoint for Render (uvicorn app:app).
Built from new 147KB app.py + pro-engine.py (hyphen-safe loader).

Clean Merged File 1+2 (filtered): Loader + PRO V43 Premium only. Kept = core/features/extensions + patch_live_fix + PRO. Filtered = patch_stats_fix, patch_p0, /holders, /check_pro, /grade (dup of /pro_json). Loader + PRO V43 Premium inline. Upload this file as app.py + pro-engine.py (or pro_engine.py) next to it. Loads the full stack into one shared namespace:
  core_final → features → extensions → optional patches

Do NOT use the old standalone "cute" app body here — that removed /omni and track-record.
"""
from __future__ import annotations

import os
import sys
import re
import traceback
from urllib.parse import quote as _urlquote, urlparse as _urlparse
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
    if "/pro_status" in paths and "/store_check" in paths:
        print("[pro_v43] already applied"); return
    if "/pro_status" in paths:
        print("[pro_v43] pro_status exists, will still add missing /store_check")
    # --- PRO ENGINE loader: supports BOTH pro_engine.py and pro-engine.py ---
    # pro-engine.py has a hyphen, so `import pro_engine` fails on Render.
    # Try normal import first, then load by file path.
    import importlib.util as _ilu
    def _load_pro_engine():
        try:
            import pro_engine as _m
            print("[pro_engine] loaded via import pro_engine")
            return _m
        except ImportError:
            pass
        for _fname in ("pro_engine.py", "pro-engine.py"):
            _p = os.path.join(ROOT, _fname)
            if os.path.isfile(_p):
                _spec = _ilu.spec_from_file_location("pro_engine", _p)
                _m2 = _ilu.module_from_spec(_spec)
                sys.modules["pro_engine"] = _m2
                _spec.loader.exec_module(_m2)
                print(f"[pro_engine] loaded from {_fname}")
                return _m2
        raise ImportError("pro_engine NOT FOUND: upload pro-engine.py (or pro_engine.py) next to app.py")
    _pe = _load_pro_engine()

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
    from fastapi.responses import JSONResponse, HTMLResponse
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
                "build": "v45-blobs-inline-2026-11-21",
                "engine": _pe.status(),
                "note": "PRO engine v45: owner-resolved holders, oldest-tx creator, burn-only LP safe, unverified when data is missing"}

    @app.get("/store_check")
    async def store_check(request: Request):
        """Why is the track-record store (Upstash REST) unreachable? Never prints the token."""
        ok, retry, _scope = _pe.allow_request(_pe.client_ip(request), 5)
        if not ok:
            return JSONResponse({"error": "rate_limited", "retry_after_s": retry}, status_code=429,
                                headers={"Retry-After": str(retry)})
        # FIX store_check: core_final does NOT always put REDIS_URL in g.
        # Fallback to real Render env names: UPSTASH_REDIS_REST_URL / TOKEN.
        def _env_or_g(*names):
            for _n in names:
                try:
                    _v = (g.get(_n) if isinstance(g, dict) else "") or ""
                except Exception:
                    _v = ""
                if isinstance(_v, str) and _v.strip():
                    return _v.strip()
                _e = (os.getenv(_n) or "").strip()
                if _e:
                    return _e
            return ""
        url = _env_or_g("UPSTASH_REDIS_REST_URL", "REDIS_URL", "UPSTASH_URL")
        tok = _env_or_g("UPSTASH_REDIS_REST_TOKEN", "REDIS_TOKEN", "UPSTASH_TOKEN")
        out = {"UPSTASH_REDIS_REST_URL_set": bool(url), "UPSTASH_REDIS_REST_TOKEN_set": bool(tok)}
        if not (url and tok):
            out["verdict"] = "missing env var(s) on Render"
            return out
        pu = _urlparse(url)
        host = pu.netloc
        out.update({"url_scheme": pu.scheme, "url_host": (host[:5] + "..." + host[-14:]) if len(host) > 22 else host,
                    "token_length": len(tok), "token_has_whitespace": tok != tok.strip() or " " in tok})
        if pu.scheme != "https":
            out["verdict"] = "URL must be the REST url (https://xxxx.upstash.io), not a redis:// / rediss:// address"
            return out
        try:
            client = getattr(request.app.state, "client", None)
            hdr = {"Authorization": "Bearer " + tok}
            if client is not None:
                r = await client.post(url.rstrip("/") + "/pipeline", json=[["PING"]], headers=hdr, timeout=6.0)
            else:
                try:
                    import httpx as _hx
                    async with _hx.AsyncClient() as _c:
                        r = await _c.post(url.rstrip("/") + "/pipeline", json=[["PING"]], headers=hdr, timeout=6.0)
                except ImportError:
                    # Render has requests even if httpx is missing - use sync requests in thread
                    import requests as _rq
                    _rr = _rq.post(url.rstrip("/") + "/pipeline", json=[["PING"]], headers=hdr, timeout=6.0)
                    class _R: pass
                    r = _R(); r.status_code = _rr.status_code; r.text = _rr.text or ""
            out["http_status"] = r.status_code
            out["body"] = (r.text or "")[:160]
            if r.status_code == 200 and "PONG" in (r.text or ""):
                out["verdict"] = "OK - store answers PING (health shows it again within 5 minutes)"
            elif r.status_code in (401, 403):
                out["verdict"] = "token rejected - copy the REST token again from the Upstash database page"
            elif r.status_code == 404:
                out["verdict"] = "URL not found - database deleted/paused or URL wrong"
            else:
                out["verdict"] = "unexpected answer - see body"
        except Exception as e:
            out["error"] = type(e).__name__
            out["detail"] = str(e)[:140]
            out["verdict"] = "cannot reach Upstash from Render (DNS / timeout / wrong host)"
        return out

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
        blobs_html_pro = """<div class='blob-run' style='animation:wanderLR 11s linear infinite;animation-delay:0s'><img src='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIAAAABYCAMAAAAKjQ+7AAAAkFBMVEUZn5sen5wioJ0boJ6b3t3T9vZTsa52zssAeXkLy887xcJgxb3/AAD///8A/wBJn6cAAP8Af6QAf/8LnWcVr8tru8MArsAA/38zzJlIbZGqVaqCx7r/AP8DqKkAAAD3+/sA//8oqKsMpJwPsa4OpaYOmpgCp6kLpacLnKwIpqcGpqcGqKoFqKgCtrYos7Ou6Oa2qGs8AAAAMHRSTlMdXeeo/////wIH//8BAQEMAQcDDQv//wIFBwP/Af4A/wH8/v61/C7O/ZFvEksM/v/BJQPhAAAFuUlEQVR42u1aa3fjKAwVkKTJtJ3uzOzsGxuwjfEz///fLTi24wfGJE2O98PqnJm0UY2uL5JAAgj8hGlxqS8f0MvlGY+BIfAX9gFQFAWcLLqqLBFCWdxKpn/xG9rrr45QACrLPCMxISTOZPEjGL1dBShNEkoVpXVEW4kRfHsIgO+QZ1najBld/pEs/zW4QniDjFBO55LmAJ8EwIIC8ng8bBRRrkhetBC+vku7+QYCKtjnGAAUW0fmOJPQIND2E8GXEGACnwEAkNHJ2/3W/ZCkhoSASaL/wA6gcQcC7G4A2rUotdOrv0wMCUzG4mrMKrEzHpw6G/u4bj6a/3GamxnidEUQuwuAsS9wNCFVDL/AHBv61xBguAeAsa+4EBZyDemq+eQ+9p1+sAhAx5bdt6JBODbeUK+ZN5mjuBVARaigDxNOc7gNQIEwfaikS44I9vyn448/FgGRtzAAxBXYt8+AEXR68wZwSUAPloVYhCUCHi+k8gXwB+L8CQBw6QeAaQI4FY/0gdYT8sqPgVPeZbvHSdSuzMwHgCSCPmMKOJY+AP4JHp2Drk7gBSCAjD8JAC/Zug+woEzpswDYlqQ5gJw+TWyZ4PEAomVFanGCmQ+cyNMIiGi5CoAFctUFRJKoJZ0pjxwAUHD0AuBKgkLUX74sbYKMypXBsiIoiuMKAGsW6Lfeqt7twzA8H8T8/Q7n/T7c77i9StAPY5oXMpPHT0wB/mnMa9m/TslOXjrVYWke9LtlMY2LOxhod6DJIexkP+YgGqrqxOlEo0XJF0D7CvtwgCDpNsZNltGqTnvGzqVsFI0zAOAC8BIO5O+kddemRBipXtwUZBDcAUB7ltgNrewPnHalo+D7oersBjCkAOYFgVpKcOIwtLIPf2LeRezAAxodtwSJMGCTLhztANhR7wbsAGrtZyMCwnCHee+CE9WrsIay0mnk4odHZgOgvywWFmOzR5kBSDof5FPVi7AnE5PBjIfG0sKANi/LzL4Z0sDrOYBr6ZycJyrl2NNhPVo/CTBqtcV0wXua0dTEyvnqr3MAwhmJIu3WpSuAY5Fj1bUe7CvNTQDcCxrOqgkDTMYJpc52x3wKFlUriUBPAzadvgGANxk3vQ9XSSKmVtRgIViPgrFLmz3yAMCbVzU2ygNheGhjUDuomuaBtaEU5/m3rz2Ad0nw2n7KoB7N9JkPQlScxwG6CkDxFK4MVATzaLi02AAITl+HFOjFSPQdkNFasK+V1x4VWgDvTNcifK0YiwzZAy/QG4/ukcj0qnY3uKAJA23QdE1gsSFofew6CbvJNIvD2RIdrq3dhQJoGjL+tUVn5sxFtKDa4cS3skYXBm7oR9QcH3bn3e5FTO1rFz28GFWzU/JEEP9oAKAbisFa78oXi3dlduVR5Pv+3FBgZoHU9NaeVLQ85k0DlRoAQyvd7meKOVJpPCDaxr7eomsAZlXfyD6NNQOIbidCA4AtARgGgGwNIN4SAPkfAEAVbxaDW/uA2NwJo/9AFOhUDHG0nQ8oxKAgfDsnwHopKtCmURhsuhhpAhi4m0JPJ0Az8CfaKgs0pRGw7ShAp0tldNyGAoyKrjbchAKOqr48r7aggMhL6/5SGz4lGQm3/d+HLZq7T+qaVpQaF+Oqr2QXXytF8MuoS9beVxB3vaVStv6DWnrAXOhAs07pCaVU3cGAUk6lmnGgV740h2DeK169MlALcyDE20J4TPYNCCPNPlgPLAC5PTGiJCvLOPF7+aXYJ2h6v+76KwPi8gGRST1xMk8Tnvi9vHG2XrIcmTuOH86DS8c0JIk5ZGA6b2sIVhe72orzTkpZSCmvdzzN5T/mOrb7rudhiiGqTdWflUXjNzp4ToPD5TjrJJe9AOtkeimVrR9e/6Uh9KcAlwMRjlNSjo6ZZNmJrDo5Ll6FXbK8eHz/AQj1d1Obq6pl5Xntds2YD4DmcQbm+uxg5gL2CFtW+Rez2PiBMd4HEwAAAABJRU5ErkJggg==' style='width:62px;height:auto;display:block' alt='blob teal'></div>
<div class='blob-run' style='animation:wanderRL 13s linear infinite;animation-delay:-2s'><img src='data:image/png;base64,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' style='width:56px;height:auto;display:block' alt='blob orange'></div>
<div class='blob-run' style='animation:wanderLR 12s linear infinite;animation-delay:-4s'><img src='data:image/png;base64,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' style='width:66px;height:auto;display:block' alt='blob purple'></div>
<div class='blob-run' style='animation:orbit 16s linear infinite;animation-delay:-1s'><img src='data:image/png;base64,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' style='width:58px;height:auto;display:block' alt='blob blue'></div>
<div class='blob-run' style='animation:wanderRL 11.5s linear infinite;animation-delay:-6s'><img src='data:image/png;base64,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' style='width:60px;height:auto;display:block' alt='blob green'></div>
<div class='blob-run' style='animation:wanderLR 14s linear infinite;animation-delay:-3s'><img src='data:image/png;base64,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' style='width:54px;height:auto;display:block' alt='blob pink'></div>
<div class='blob-run' style='animation:wanderRL 12.5s linear infinite;animation-delay:-8s'><img src='data:image/png;base64,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' style='width:62px;height:auto;display:block' alt='blob yellow'></div>
<div class='blob-run' style='animation:wanderLR 13.5s linear infinite;animation-delay:-5s'><img src='data:image/png;base64,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' style='width:60px;height:auto;display:block' alt='blob red'></div>
<div class='blob-run' style='animation:orbit 18s linear infinite;animation-delay:-7s'><img src='data:image/png;base64,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' style='width:64px;height:auto;display:block' alt='blob brown'></div>
<div class='blob-run' style='animation:wanderRL 12s linear infinite;animation-delay:-9s'><img src='data:image/png;base64,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' style='width:58px;height:auto;display:block' alt='blob orange triangle'></div>
<div class='blob-run' style='animation:wanderLR 15s linear infinite;animation-delay:-10s'><img src='data:image/png;base64,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' style='width:56px;height:auto;display:block' alt='blob cyan'></div>
<div class='blob-run' style='animation:orbit 17s linear infinite;animation-delay:-4s'><img src='data:image/png;base64,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' style='width:54px;height:auto;display:block' alt='blob lavender'></div>
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
<div><div class='blobbox'><div class='pile' style='height:auto;text-align:center'><img src='data:image/png;base64,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' style='width:100%;max-width:360px;height:auto;display:block;margin:0 auto' alt='TVibe blobs'></div><div class='verdict'>PASS - HOLD-BUY - SELL</div><div class='mini-live'><b>What you get in 1 check</b><p>Grade A-F + 5 breakdowns: Market / Holder / LP / Dev / Authority. Plus flags: low liquidity, top holder, unlocked LP, mint still on, dev selling.</p></div></div></div>
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
<div class='blob-run' style='animation:wanderLR 11s linear infinite;animation-delay:0s'><img src='data:image/png;base64,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' style='width:62px;height:auto;display:block' alt='blob teal'></div>
<div class='blob-run' style='animation:wanderRL 13s linear infinite;animation-delay:-2s'><img src='data:image/png;base64,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' style='width:56px;height:auto;display:block' alt='blob orange'></div>
<div class='blob-run' style='animation:wanderLR 12s linear infinite;animation-delay:-4s'><img src='data:image/png;base64,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' style='width:66px;height:auto;display:block' alt='blob purple'></div>
<div class='blob-run' style='animation:orbit 16s linear infinite;animation-delay:-1s'><img src='data:image/png;base64,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' style='width:58px;height:auto;display:block' alt='blob blue'></div>
<div class='blob-run' style='animation:wanderRL 11.5s linear infinite;animation-delay:-6s'><img src='data:image/png;base64,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' style='width:60px;height:auto;display:block' alt='blob green'></div>
<div class='blob-run' style='animation:wanderLR 14s linear infinite;animation-delay:-3s'><img src='data:image/png;base64,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' style='width:54px;height:auto;display:block' alt='blob pink'></div>
<div class='blob-run' style='animation:wanderRL 12.5s linear infinite;animation-delay:-8s'><img src='data:image/png;base64,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' style='width:62px;height:auto;display:block' alt='blob yellow'></div>
<div class='blob-run' style='animation:wanderLR 13.5s linear infinite;animation-delay:-5s'><img src='data:image/png;base64,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' style='width:60px;height:auto;display:block' alt='blob red'></div>
<div class='blob-run' style='animation:orbit 18s linear infinite;animation-delay:-7s'><img src='data:image/png;base64,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' style='width:64px;height:auto;display:block' alt='blob brown'></div>
<div class='blob-run' style='animation:wanderRL 12s linear infinite;animation-delay:-9s'><img src='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAMAAAD04JH5AAAAkFBMVEXyZx7gmmTwcCDneFjzz6zugiPpjlP67NP2kCbjiEnosY3sbSrzbizkgzTneUfleEb//wDud0bihDbqhkn/OxK+c1D///9/AAB/fwD/AP///39/f3+/bz+wiWL/AH/7eCoAAAD6eBj5+/X0gjD/AAD8eS73dyvyekb2eCr6eCr3dyr0dzDvhEb+fAj4dyr7587h6eueAAAAMHRSTlMR+/QU/+od/xZc/2GkmmHsAZprmQQPAQICAQICEA0C/gD+//0BEM/9ry1Pjf0GcP9Y2vzBAAAJi0lEQVR42sWbiXbjKgxAMY6dPWnSZeatVAXvS/7/7x7gJcaA7bhxn87pZNpicxEgCYmiz+/K2z8uQuj93Z33OPpG1+wT+X5yvR6y7Hg8bpGP+I9+EAD57ukSxyEApZSQMD5ufR/9GAAT3Z+jKCIARAqlOCv94GcAGHKvITFIvEfoBwCYv81AiAYA+PWxaUDz+r96vG9D/+JnFx99LAvA3K0HFgAhl21QLAnANtsQE6F/AwEV/4TlkgAs2HoYY9k7aPrne4F/XFzEFgMotp5Z86RelEIJh8nb8WGAt+Ro7x9anRyTt2UAXGv/FQDB1f9JGUyzy+jhCSBDEwB19wDhtlgCAG2P1UI3A9y3BdDXtFgAIMiIDUCO/g5A8gt6OoCwAGDbA9qGDK/BrycDoNSjQMlUwVv0XACEjsLOTBaI3eKJADz+2XqUUDIZgfulcd/8gAYCPxZ29hGA6FR8PE8DwgRR3QHBAABxtsXTAIKrJ4evEpjDksYWEHpMiicBFOmx2l1Kf9AF6JPwYBUgQ8VTAJh/5O+nZgDoOsPeL/E+eHkGwJsMwrQJ72pAnwvAQOGw3zwBoHBfwaNmDwi2FUgB8y84oA/2TQDGnSC1hoBjRjncb9zvaiCQUdAkgr5O+DfnoUmYBFBsjvQbANEFBd8DQFt5+psFINftAf35DYA/CvfiecNGrx+Y9f1iufkGgIu20QNO2HhcOqTBfAC0dVoHNGB4h6EOG0uMOg7w5r+S3GR5HxK838wDYJ/BK1EUMA+AHJLNPA0UfALMvuexOTgfNsUcgN/FaycCmQ8AkcUcjQGg07ldAU3oPQNCPHBI3McB0IavgGiyBxoWo2MeAyi5F44GfPBD69B0VhoEYEUaGwzL7JWQbV7YYwBJbDX3cwDOZfDHQwBFGpqOgvONAdZ3AhrMBcRVwiMyp0JmmSN/OsBLUDbni4lbbRwM74vpAEEakqlOePLMHPo+AQ3nAioA+iQAHtXkFzQVoFHA9KPgFA3kTommAbw0CnAeABjfBiSPk48pAAyVoTnIEf3IU/IclwRAvb3LJgC83W0QBVDGJ95CYS4AVwH6axSAhyEl6QBAZ4ZzUh8SR5SQU6s9ROMaCNK4nwFsAKI6MBxbnHmem90yeU1exgAK1Qk0AHWn1SqgpEmLWvohucWL4LLjl80AnQm4v0/M/X0VwJwNUQHQcI+GAVQFyASozMKLh/OodYeqhQJcrxeOiYldPfyUnWfFIEChKkACyKXPhx05UnoGChoRlRTsODvHofcChqaNyLmfU5AxHxlqUypHRkm0W93W6/Vq5xAxDdAFoNW/Dm/xdeMtMNXPMlFtjo5tjdMEkGT9/qkYGt/C+Wr9VcnaEZrxuhtc8ji7W91i5VQb0WCguaZSZNUAC3QFVLkhoKuvVm4OwfcTY9UJJV6nxdoxA3h8NCRrNgLSbXAa25yZs/7qEmCtYOXtui1WjuWoKgq9zUbQAYLM0j1W+hfv7+1FCv0WZ+tu9Y6BBUCbgHbtnFfq678c0kvd053a4OZEVoPpnZARwNVWoOhfmF/s3NTXcxV46gw4q36Ls9Vg47gKD5F2EukNSqygqkTefzsfYE/BfRVJFVj6x+QaMB2g5wRI63f5R18BX187FUBTAJ8lG0AUQSir3MgYCPdqgfLLWWuvX6mNHQNiNOCtM1HZQ8MrsDFwAuBrGACICTEiJotdufPYRT0NfPQnQHiOWgvYALCmYwDrvJvPVgC4nAJVA6xQFSBMae0EzQA31eMbW8AAgJMgBeBFVQDNlczYBACTBnoJfQWAnlwFICgVBYgKlXTtVUg2AECtAKtcrWioAGIjIEscWFvxjvYMa3yl+qI+ovDKkeKMNMO871w4eVGdgEgyk672RgEMLdar82BuE7IOgBqG3CPhAQCHdIolYDJEu2EAkrktwCbJtDhUqcfkBlOsToGpRTQMcGzWANOcgBJLiFia7LQZcHopZL1FlA8DvLaL0O1sQd6ZuKLVt2DaHOwiql4eyNcGSwwDMfq53DQauDsBKoNvXRGAV30FRKAgen0V8LDQVMG4S5wwpDuB+ugLvXN/3x2t756ONgCO4pBvXEXUAkDlOOOkNkRdJyB0iaXDVgF4JNmdhNsu15MTkTJNuwjXbLZERgtQlM1QIi0L2HwrUqb3mPMmIk7am6WoGxPIFpgMAOQtAPOP9Tmr2TVA1CKF/AVfms0s3HZOx6zdh8l91qppca5PsGaACPMdwiMCCRCctBVnO286uxUXR4TkYC4Y5Y5osTPFQtCLc8O0kADMjUdzTd3jVU4Bw1Bi3nOc3FLPuj+XexyAyV3QVYA1E0zrHUJzOmzeq8dpPgpAGoDCjacCyKQHYAyWMh6lcnuB2ELGUvcdAEuAggMwdJqQC++axiHbWhHYp0fxzHHywgF++zFMBGgCmZmZagVASCmDUrSHgTyP7h3ra8STS0XqHQ8VQAal/hFMdV+tCH4X+kAd2QpwbgDQxuvkntTwzZZ5gik1kyaRpAQVLUDUasDde6ZOjXkNxVSN9Y+hH1X1AcIUievpGUwEmDp080HIAMA9gdBARmDC9uqeLKZlzWkHgZgB5NnQvUxL9sP8QpG2LapU8wwAeBZApYjqdOxm03T7fIBQpur+T4CkuiV5aZfLYML5OQDd7dwAZISCZfeQRaTZCzWAnxFr1LwMBciLfrUZ4ACXEQBYCqCUFUQkooGBG4ILAqRvEqBAB0ot4cBiK6ECqPOEKInxEABZGoBxAnKOyE+L9IUyTceCJAtz0rudvrjUFQNUFYmasyn8JMBnJ1cs8jOTrwwuAMDPB5wAfnIGehoQlZoQzw+4HxV+wikDtWBRVFkygEUo+hYl557AVQFYtRK9ZUasA1SeQMmWy3Ww0CzoNtUAsOQ6mAZgqFkuBnCuN4FWsklj/KwOO8dg3bGfm5t1WtUsKcOozVc+JHTIpbYIUVUIDBMLwOevoAxnXaKd0LjNdpGw9G3Fa/Yr2GMyIyCpDoMwhCRSJ/IPFcOT+8t+f6DgOnjgJGboTjkYNz8GHGLP88KsTNNTwIYuMLjBfs5mEAkiqhdGwlhKlqVJkmwQF9f9c+QWjYu21+s1Dlsh0M0J9yPW+lMmcWT+qXooK6WkSVBJe6eWTbhJ5QcIbbYnLvuUS1mN4hjHh8MBd/rHQmrFi6Ee+FeZSmn63bBZf2XDKdlLwYUx9i9zfSQlcbmcykyXwyFLUSIF/WZSPpUPxh6/Xc+Y8Vnku3d5R+77u/v+N1dYoD438c93/gPGL8JZo38eMAAAAABJRU5ErkJggg==' style='width:58px;height:auto;display:block' alt='blob orange triangle'></div>
<div class='blob-run' style='animation:wanderLR 15s linear infinite;animation-delay:-10s'><img src='data:image/png;base64,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' style='width:56px;height:auto;display:block' alt='blob cyan'></div>
<div class='blob-run' style='animation:orbit 17s linear infinite;animation-delay:-4s'><img src='data:image/png;base64,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' style='width:54px;height:auto;display:block' alt='blob lavender'></div>
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
        "/pro", "/pro_json", "/pro_status", "/store_check", "/omni_pro", "/compare", "/batch", "/check",
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

# --- GUARANTEE /store_check always exists (fix Not Found) ---
# Root cause: _apply_pro returns early if /pro_status already exists in core,
# so /store_check inside it never gets registered. This block re-installs it
# AFTER rescue sorting, directly on app, so it cannot be skipped.
try:
    from fastapi import Request as _ReqGC
    from fastapi.responses import JSONResponse as _JRGC
    # Remove any old /store_check so we don't have duplicates
    try:
        app.router.routes[:] = [r for r in list(app.router.routes) if getattr(r, "path", "") != "/store_check"]
    except Exception:
        pass
    @app.get("/store_check")
    async def store_check_guaranteed(request: _ReqGC):
        """Why is Upstash unreachable? Never prints token. Guaranteed route."""
        try:
            import os as _osGC
            url = (_osGC.getenv("UPSTASH_REDIS_REST_URL") or _osGC.getenv("REDIS_URL") or "").strip()
            tok = (_osGC.getenv("UPSTASH_REDIS_REST_TOKEN") or _osGC.getenv("REDIS_TOKEN") or "").strip()
            # Also try loader globals if env missing
            try:
                if not url and isinstance(g, dict):
                    url = (g.get("UPSTASH_REDIS_REST_URL") or g.get("REDIS_URL") or "").strip()
                if not tok and isinstance(g, dict):
                    tok = (g.get("UPSTASH_REDIS_REST_TOKEN") or g.get("REDIS_TOKEN") or "").strip()
            except Exception:
                pass
            out = {"UPSTASH_REDIS_REST_URL_set": bool(url), "UPSTASH_REDIS_REST_TOKEN_set": bool(tok)}
            if not (url and tok):
                out["verdict"] = "missing env var(s) on Render"
                return out
            from urllib.parse import urlparse as _upGC
            pu = _upGC(url)
            host = pu.netloc
            out.update({"url_scheme": pu.scheme, "url_host": (host[:5] + "..." + host[-14:]) if len(host) > 22 else host,
                        "token_length": len(tok), "token_has_whitespace": tok != tok.strip() or " " in tok})
            if pu.scheme != "https":
                out["verdict"] = "URL must be the REST url (https://xxxx.upstash.io), not a redis:// / rediss:// address"
                return out
            try:
                import requests as _rqGC
                _rr = _rqGC.post(url.rstrip("/") + "/pipeline", json=[["PING"]], headers={"Authorization": "Bearer " + tok}, timeout=6.0)
                out["http_status"] = _rr.status_code
                out["body"] = (_rr.text or "")[:160]
                if _rr.status_code == 200 and "PONG" in (_rr.text or ""):
                    out["verdict"] = "OK - store answers PING (health shows it again within 5 minutes)"
                elif _rr.status_code in (401, 403):
                    out["verdict"] = "token rejected - copy the REST token again from the Upstash database page"
                elif _rr.status_code == 404:
                    out["verdict"] = "URL not found - database deleted/paused or URL wrong"
                else:
                    out["verdict"] = "unexpected answer - see body"
            except Exception as e:
                out["error"] = type(e).__name__
                out["detail"] = str(e)[:140]
                out["verdict"] = "cannot reach Upstash from Render (DNS / timeout / wrong host)"
            return out
        except Exception as e:
            return _JRGC({"error": type(e).__name__, "detail": str(e)[:140]}, status_code=500)
    print("[store_check] guaranteed route installed")
except Exception as _eGC:
    print(f"[store_check] guarantee FAILED: {_eGC}")

print("[rescue-v44] done")

# --- STORE_CHECK via middleware (bypass router shadowing) ---
# Root cause: /store_check IS in router.routes (front list shows it) but a
# catch-all / earlier route still matches it first -> 404.
# Middleware runs BEFORE routing, so it cannot be shadowed.
try:
    from fastapi.responses import JSONResponse as _JRSM
    @app.middleware("http")
    async def _store_check_mw(request, call_next):
        try:
            _p = getattr(getattr(request, "url", None), "path", "") or ""
        except Exception:
            _p = ""
        if _p == "/store_check" or _p == "/store_check/":
            try:
                import os as _osSM
                url = (_osSM.getenv("UPSTASH_REDIS_REST_URL") or _osSM.getenv("REDIS_URL") or "").strip()
                tok = (_osSM.getenv("UPSTASH_REDIS_REST_TOKEN") or _osSM.getenv("REDIS_TOKEN") or "").strip()
                try:
                    if not url and isinstance(g, dict):
                        url = (g.get("UPSTASH_REDIS_REST_URL") or g.get("REDIS_URL") or "").strip()
                    if not tok and isinstance(g, dict):
                        tok = (g.get("UPSTASH_REDIS_REST_TOKEN") or g.get("REDIS_TOKEN") or "").strip()
                except Exception:
                    pass
                out = {"UPSTASH_REDIS_REST_URL_set": bool(url), "UPSTASH_REDIS_REST_TOKEN_set": bool(tok)}
                if not (url and tok):
                    out["verdict"] = "missing env var(s) on Render"
                    return _JRSM(out)
                from urllib.parse import urlparse as _upSM
                pu = _upSM(url)
                host = pu.netloc
                out.update({"url_scheme": pu.scheme, "url_host": (host[:5] + "..." + host[-14:]) if len(host) > 22 else host,
                            "token_length": len(tok), "token_has_whitespace": tok != tok.strip() or " " in tok})
                if pu.scheme != "https":
                    out["verdict"] = "URL must be the REST url (https://xxxx.upstash.io), not a redis:// / rediss:// address"
                    return _JRSM(out)
                try:
                    import requests as _rqSM
                    _rr = _rqSM.post(url.rstrip("/") + "/pipeline", json=[["PING"]], headers={"Authorization": "Bearer " + tok}, timeout=6.0)
                    out["http_status"] = _rr.status_code
                    out["body"] = (_rr.text or "")[:160]
                    if _rr.status_code == 200 and "PONG" in (_rr.text or ""):
                        out["verdict"] = "OK - store answers PING (health shows it again within 5 minutes)"
                    elif _rr.status_code in (401, 403):
                        out["verdict"] = "token rejected - copy the REST token again from the Upstash database page"
                    elif _rr.status_code == 404:
                        out["verdict"] = "URL not found - database deleted/paused or URL wrong"
                    else:
                        out["verdict"] = "unexpected answer - see body"
                except Exception as e:
                    out["error"] = type(e).__name__
                    out["detail"] = str(e)[:140]
                    out["verdict"] = "cannot reach Upstash from Render (DNS / timeout / wrong host)"
                return _JRSM(out)
            except Exception as e:
                return _JRSM({"error": type(e).__name__, "detail": str(e)[:140]}, status_code=500)
        return await call_next(request)
    print("[store_check] middleware installed (bypass router)")
except Exception as _eSM:
    print(f"[store_check] middleware FAILED: {_eSM}")
try:
    import patch_agent_fire_v46
    patch_agent_fire_v46.apply(g if "g" in dir() and isinstance(g, dict) else globals())
    print("[loader] patch_agent_fire_v46 applied")
except Exception as _e_fire:
    print(f"[loader] patch_agent_fire_v46 NOT applied: {_e_fire}")


# ======================================================================
# FIX FINAL v3 — /cron/outcome: sua 422 Unprocessable Entity
# Log Render moi nhat (10:57 PM, commit 71f1032) cho thay:
#   GET /cron/outcome -> 422 Unprocessable Content
#   cron-job.org cung bao 422
# Ly do: ban v2 dinh nghia ham moi la
#   async def _cron_outcome_no_key(request, limit: int = 50, ...)
#   ma khong ghi kieu cho `request`.
# FastAPI hieu `request` khong co type = 1 query param BAT BUOC
# ten la `request`. Cron-job goi /cron/outcome khong co ?request=...
# nen FastAPI tra 422 "thieu param request".
# Ban v3 sua: request: Request (co type) + chi nhan param optional.
# Van giu: bo key, tra 200 ngay, chay nen.
# Sau deploy, log phai co: [fix-outcome-final-v3] installed, replaced=N
# Cron URL: https://signal-api-24q4.onrender.com/cron/outcome (khong ?key=)
# ======================================================================
try:
    import threading as _fx3_th
    import sys as _fx3_sys
    from fastapi import Request as _ReqV3
    _fx3_app = globals().get("app")
    _fx3_g = globals().get("g") if isinstance(globals().get("g"), dict) else {}
    _fx3_router = getattr(_fx3_app, "router", _fx3_app)
    _fx3_all = list(getattr(_fx3_router, "routes", []) or [])
    _fx3_old = [r for r in _fx3_all if getattr(r, "path", "") == "/cron/outcome"]
    _fx3_orig = getattr(_fx3_old[0], "endpoint", None) if _fx3_old else None
    _fx3_orig_globals = getattr(_fx3_orig, "__globals__", {}) or {} if _fx3_orig else {}
    print(f"[fix-outcome-final-v3] found {len(_fx3_old)} old /cron/outcome route(s), orig={'yes' if _fx3_orig else 'no'}")
    try:
        _has_ping = any(getattr(r, "path", "") == "/ping" for r in _fx3_all)
        if not _has_ping and hasattr(_fx3_app, "get"):
            @_fx3_app.get("/ping")
            async def _ping_fixed_v3():
                return {"status": "ok", "version": _fx3_g.get("VERSION") or "3.0.28-fire"}
            print("[fix-outcome-final-v3] /ping added (was missing)")
    except Exception as _e_ping3:
        print(f"[fix-outcome-final-v3] /ping skip: {_e_ping3}")
    _fx3_lock = _fx3_th.Lock()
    _fx3_running = {"busy": False}
    if _fx3_orig is not None:
        try:
            _fx3_router.routes[:] = [r for r in list(_fx3_router.routes) if getattr(r, "path", "") != "/cron/outcome"]
        except Exception:
            pass
        try:
            if getattr(_fx3_app, "routes", None) is not getattr(_fx3_router, "routes", None):
                _fx3_app.routes[:] = [r for r in list(_fx3_app.routes) if getattr(r, "path", "") != "/cron/outcome"]
        except Exception:
            pass
        # QUAN TRONG: request phai co type Request, cac param khac deu co default
        # de FastAPI khong coi bat cu cai nao la bat buoc -> het 422
        @_fx3_app.api_route("/cron/outcome", methods=["GET", "POST", "HEAD"])
        async def _cron_outcome_no_key_v3(request: _ReqV3, limit: int = 50, key: str = "", cron_key: str = ""):
            try:
                _qp = dict(getattr(request, "query_params", {}) or {})
                if "limit" in _qp:
                    try:
                        limit = int(_qp.get("limit") or limit)
                    except Exception:
                        pass
            except Exception:
                pass
            with _fx3_lock:
                if _fx3_running["busy"]:
                    return {"status": "already_running", "note": "outcome dang chay background, de yen, lan sau check tiep"}
                _fx3_running["busy"] = True
            _incoming = (key or cron_key or "")
            try:
                _incoming = (dict(getattr(request, "query_params", {}) or {}).get("key") or _incoming or "")
            except Exception:
                pass
            _headers = {}
            try:
                _headers = dict(getattr(request, "headers", {}) or {})
            except Exception:
                _headers = {}
            def _bg():
                _to_restore = []
                def _patch_dict(_d):
                    if not isinstance(_d, dict):
                        return
                    try:
                        if "_need_key" in _d:
                            _to_restore.append((_d, "_need_key", _d["_need_key"]))
                            _d["_need_key"] = lambda *a, **k: True
                        for _kn in ("ADMIN_KEY", "TVIBE_ADMIN_KEY", "CRON_KEY", "ADMIN_TOKEN"):
                            if _kn in _d:
                                _to_restore.append((_d, _kn, _d[_kn]))
                                _d[_kn] = _incoming or "bypass-nokey"
                    except Exception:
                        pass
                try:
                    _patch_dict(_fx3_orig_globals)
                    _patch_dict(_fx3_g)
                    for _mn in ("core_final", "core", "extensions", "features", "patch_agent_fire_v46"):
                        _m = _fx3_sys.modules.get(_mn)
                        if _m is not None:
                            try:
                                _patch_dict(vars(_m))
                            except Exception:
                                pass
                    class _FakeReq:
                        def __init__(self, qp, hd):
                            self.query_params = qp
                            self.headers = hd
                    _fake = _FakeReq({"limit": str(limit), "key": _incoming or "bypass-nokey", "cron_key": _incoming or "bypass-nokey"}, _headers)
                    _res = None
                    _called = False
                    for _args, _kwargs in [
                        ((_fake,), {"limit": limit}),
                        ((_fake,), {}),
                        ((), {"limit": limit}),
                        ((), {}),
                        ((_fake, limit), {}),
                    ]:
                        try:
                            _res = _fx3_orig(*_args, **_kwargs)
                            _called = True
                            break
                        except TypeError as _te:
                            _msg = str(_te).lower()
                            if "argument" in _msg or "missing" in _msg or "unexpected" in _msg or "positional" in _msg:
                                continue
                            raise
                    if not _called:
                        print("[fix-outcome-final-v3] background: khong goi duoc ham goc (signature la)")
                    else:
                        import asyncio as _aio3
                        if _aio3.iscoroutine(_res):
                            try:
                                _aio3.run(_res)
                            except RuntimeError:
                                _loop3 = _aio3.new_event_loop()
                                try:
                                    _loop3.run_until_complete(_res)
                                finally:
                                    _loop3.close()
                        print(f"[fix-outcome-final-v3] background done: {str(_res)[:220] if isinstance(_res, dict) else type(_res).__name__}")
                except Exception as _e_bg3:
                    print(f"[fix-outcome-final-v3] background FAILED: {type(_e_bg3).__name__}: {str(_e_bg3)[:400]}")
                finally:
                    for _d, _k, _old in reversed(_to_restore):
                        try:
                            _d[_k] = _old
                        except Exception:
                            pass
                    with _fx3_lock:
                        _fx3_running["busy"] = False
            _fx3_th.Thread(target=_bg, daemon=True).start()
            return {"status": "started", "mode": "background", "limit": limit, "note": "da tra 200 cho cron-job, outcome dang chay nen phia sau. 5-10 phut sau vo /health coi multi_horizon_pending co giam khong."}
        try:
            _all3 = getattr(_fx3_router, "routes", None)
            if _all3 is not None:
                _outs = [r for r in list(_all3) if getattr(r, "path", "") == "/cron/outcome"]
                _rest = [r for r in list(_all3) if getattr(r, "path", "") != "/cron/outcome"]
                _all3[:] = _outs + _rest
        except Exception:
            pass
        print(f"[fix-outcome-final-v3] installed, replaced={len(_fx3_old)} old route(s) — no key, 200 ngay + background, da sua 422")
    else:
        print("[fix-outcome-final-v3] WARNING: khong thay route /cron/outcome cu")
except Exception as _e_final3:
    print(f"[fix-outcome-final-v3] FAILED (fail-open, app van chay): {_e_final3}")

import patch_tvibe_full_v48_en as _full
_full.apply(g)
import patch_tvibe_full_v48_en as _full
_full.apply(g)

import patch_helius_404_fix as _fix404
_fix404.apply(g)

app = g.get("app")
import patch_main_unified_v55 as _main55
_main55.apply(g)


"""patch_fix_422_v58.py - FIX v57 'no router' + Render runs main:app, not app.py
ROOT CAUSE of v57 log '[v57] no router':
  - At v57 time outer app is NOT plain FastAPI. It is a wrapper chain:
    LeanGate(outer=..., core=...) / MainUnified(inner=...) / SafeLayoutASGI(inner=...)
  - v57 _unwrap only looked for attrs 'inner' / 'app'.
    LeanGate stores them as 'outer' / 'core', so _unwrap saw no inner -> returned the gate itself.
  - Gate has no .router -> v57 printed 'no router' and RETURNED WITHOUT INSTALLING THE GATE.
    So 422 stayed.
v58 fix:
  1) BFS unwrap over ALL wrapper attrs: inner, app, outer, core, wrapped, _app, _inner, inner_app, outer_app, core_app.
     Also scans g + sys.modules for any object with .router + .add_api_route.
  2) EVEN IF no core/router is found, STILL INSTALL THE GATE. The gate answers
     /stats + /omni DIRECTLY without ever calling inner FastAPI validation, so it
     does not need core.router at all. This is the key change vs v57.
  3) Sync wrapped app to g + main + app + __main__ module globals, because
     Render runs `uvicorn main:app` - editing app.py / app_FIXED.py alone does NOTHING.
Upload next to main.py. Append at VERY END of main.py (after FIX 1 block, LAST lines):
    try:
        import patch_fix_422_v58 as _v58
        _v58.apply(g)
        print("[loader] patch_fix_422_v58 applied")
    except Exception as _e58:
        print(f"[loader] patch_fix_422_v58 NOT applied: {_e58}")
"""
from __future__ import annotations
import json, sys, time
from urllib.parse import parse_qs
VERSION = "v58-fix-422"
_START = time.time()

def _find_core(outer, g):
    # BFS over wrapper chain + module globals + g values
    seen=set(); queue=[]
    def _push(x):
        if x is None or id(x) in seen: return
        seen.add(id(x)); queue.append(x)
    _push(outer)
    if isinstance(g, dict):
        for _k in ("app","core","core_app","inner","outer"):
            _push(g.get(_k))
    for _mn in ("main","app","__main__","core_final","core"):
        try:
            _m=sys.modules.get(_mn)
            if _m is not None:
                _push(getattr(_m,"app",None))
                _push(getattr(_m,"core",None))
        except Exception: pass
    idx=0
    while idx < len(queue):
        cur=queue[idx]; idx+=1
        if cur is None: continue
        # Real FastAPI has router + routes + add_api_route
        try:
            if hasattr(cur,"router") and hasattr(cur,"routes") and hasattr(cur,"add_api_route"):
                # Exclude pure wrappers that only delegate via __getattr__ but are not FastAPI:
                # FastAPI class name is 'FastAPI' - wrappers are _SafeLayoutASGI / _LeanGate / _MainUnifiedASGI etc.
                # If it IS FastAPI, take it. If it is a wrapper with __getattr__, keep unwrapping too.
                if type(cur).__name__=="FastAPI":
                    return cur
                # wrapper with __getattr__ - still push its inner attrs, but don't return it yet
        except Exception: pass
        # Push all possible inner objects from __dict__ + known attrs
        try:
            _d=getattr(cur,"__dict__",None)
            if isinstance(_d, dict):
                for _v in list(_d.values()):
                    if _v is not None and not isinstance(_v,(str,int,float,bool,bytes,list,dict,set)):
                        _push(_v)
        except Exception: pass
        for _a in ("inner","app","outer","core","wrapped","_app","_inner","inner_app","outer_app","core_app","_wrapped","handler"):
            try:
                _push(getattr(cur,_a,None))
            except Exception: pass
    # Fallback: any queued object with router+routes (even wrapper) - return first
    for _o in queue:
        try:
            if hasattr(_o,"router") and hasattr(_o,"routes"):
                return _o
        except Exception: pass
    return None

def apply(g: dict) -> None:
    outer=None
    if isinstance(g, dict):
        outer=g.get("app")
    if outer is None:
        for _mn in ("main","app","__main__"):
            try:
                _m=sys.modules.get(_mn)
                if _m is not None and getattr(_m,"app",None) is not None:
                    outer=getattr(_m,"app"); break
            except Exception: pass
    if outer is None:
        print("[v58] no app found"); return
    core=_find_core(outer, g)
    if core is not None:
        print(f"[v58] core found: {type(core).__name__}")
    else:
        print("[v58] core NOT found via BFS - still installing gate (gate does not need core)")
    build_omni = g.get("build_omni") if isinstance(g, dict) else None
    stats_report = g.get("stats_report") if isinstance(g, dict) else None

    # If we DID find a real FastAPI, clean + re-add correct routes on it (best-effort, never fatal)
    if core is not None:
        try:
            TARGETS={"/stats","/omni","/omni_pro","/signal","/play","/signal/omni"}
            try:
                before=len(core.router.routes)
                core.router.routes[:]=[r for r in list(core.router.routes) if getattr(r,"path",None) not in TARGETS]
                print(f"[v58] removed {before-len(core.router.routes)} old routes")
            except Exception as _e:
                print(f"[v58] route remove: {_e}")
            try:
                from fastapi import Query as _Q, Request as _Req
                from fastapi.responses import JSONResponse as _JR
                @core.get("/stats", tags=["trust"])
                async def stats_v58(request: _Req):
                    return _JR({"available": True, "version": VERSION, "uptime_s": int(time.time()-_START), "total_in_ledger": 0, "note": "v58 safe stats", "nfa": True})
                @core.get("/omni", tags=["product"])
                async def omni_v58(request: _Req, mint: str = _Q(default="", max_length=64), view: str = _Q(default="full")):
                    m=(mint or "").strip() or (request.query_params.get("request") or "").strip()
                    if not m:
                        return _JR({"error":"need mint","omni":True,"nfa":True}, status_code=400)
                    return _JR({"mint": m, "verdict": "caution", "action": "review", "unknowns": ["omni_engine_unavailable"], "nfa": True, "version": VERSION})
            except Exception as _e2:
                print(f"[v58] re-add routes: {_e2}")
        except Exception as _e3:
            print(f"[v58] core patch skipped: {_e3}")

    # Gate - ALWAYS installed, even if core is None. Answers WITHOUT FastAPI validation.
    class _V58Gate:
        def __init__(self, outer_app):
            self.outer=outer_app
            # expose inner chain for debugging, but never require it
            self.inner=outer_app
        def __getattr__(self, name):
            # Delegate anything we don't have (e.g. .state) to outer so uvicorn / middleware still works
            return getattr(self.outer, name)
        async def _send_json(self, send, obj, status=200):
            body=json.dumps(obj).encode()
            await send({"type":"http.response.start","status":status,"headers":[(b"content-type",b"application/json"),(b"content-length",str(len(body)).encode())]})
            await send({"type":"http.response.body","body":body})
        async def __call__(self, scope, receive, send):
            if scope.get("type")!="http":
                await self.outer(scope, receive, send); return
            path=(scope.get("path") or "").rstrip("/") or "/"
            method=(scope.get("method") or "GET").upper()
            if method in ("GET","HEAD") and path in ("/stats","/omni","/omni_pro","/signal","/play","/signal/omni"):
                qs=(scope.get("query_string") or b"").decode("utf-8","ignore")
                q=parse_qs(qs)
                mint=((q.get("mint") or [""])[0] or (q.get("request") or [""])[0] or "").strip()
                view=((q.get("view") or ["full"])[0] or "full")
                if path=="/stats":
                    await self._send_json(send, {"available": True, "version": VERSION, "uptime_s": int(time.time()-_START), "total_in_ledger": 0, "note": "v58 safe stats - served without FastAPI validation", "nfa": True}); return
                if not mint:
                    await self._send_json(send, {"error":"need mint","omni":True,"nfa":True}, status=400); return
                # Try real builder if available in g (best-effort)
                pkt=None
                if callable(build_omni):
                    try:
                        client=None
                        try: client=getattr(getattr(core,"state",None),"client",None) if core is not None else None
                        except Exception: client=None
                        if client is not None:
                            import inspect as _insp
                            _r=build_omni(client, mint)
                            if _insp.isawaitable(_r): _r=await _r
                            pkt=_r
                    except Exception as _e:
                        pkt={"mint":mint,"verdict":"caution","action":"review","error":str(_e)[:120],"nfa":True}
                if not isinstance(pkt, dict):
                    pkt={"mint":mint,"verdict":"caution","action":"review","unknowns":["omni_engine_unavailable"],"nfa":True}
                if view.lower() in ("agent","compact","action"):
                    dec=pkt.get("decision") if isinstance(pkt.get("decision"), dict) else {}
                    filt=pkt.get("filter") if isinstance(pkt.get("filter"), dict) else {}
                    act=str(pkt.get("action") or dec.get("verdict") or pkt.get("verdict") or "review").lower()
                    act_n="pass" if act in ("ok","pass") else ("skip" if act in ("avoid","skip","sell") else "review")
                    await self._send_json(send, {"mint":pkt.get("mint"),"action":act_n,"verdict":pkt.get("verdict") or dec.get("verdict") or act_n,"filter":{"pass": bool(filt.get("pass")) if filt else act_n=="pass"},"confidence":pkt.get("confidence") or dec.get("confidence"),"risk_score":pkt.get("risk_score") or pkt.get("score"),"blockers":(pkt.get("blockers") or dec.get("blockers") or [])[:8],"cautions":(pkt.get("cautions") or dec.get("cautions") or [])[:8],"unknowns":list(pkt.get("unknowns") or dec.get("unknowns") or [])[:8],"valid_for_s":pkt.get("valid_for_s") or 30,"version":VERSION,"nfa":True,"ok_is_not_a_buy_signal":True}); return
                pkt=dict(pkt); pkt["nfa"]=True; pkt["version"]=pkt.get("version") or VERSION
                await self._send_json(send, pkt); return
            await self.outer(scope, receive, send)

    wrapped=_V58Gate(outer)
    if isinstance(g, dict):
        g["app"]=wrapped
    for _mn in ("main","app","__main__"):
        try:
            _m=sys.modules.get(_mn)
            if _m is not None:
                _m.__dict__["app"]=wrapped
        except Exception: pass
    print(f"[v58] FIX 422 installed {VERSION} - gate ALWAYS installed, even if core not found")

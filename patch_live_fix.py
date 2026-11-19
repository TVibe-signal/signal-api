"""patch_live_fix v30-mini — compact, same fixes as v30."""
import json, re
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
LIVE_JS = r"""
async function check(){
 const m=(document.getElementById('mint').value||'').trim();
 const out=document.getElementById('out');
 const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
 if(!m){out.innerHTML='<b>Paste a mint first.</b>';return;}
 if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(m)){out.innerHTML='<b>Not a Solana mint (32-44 base58 chars).</b>';return;}
 const q=encodeURIComponent(m);
 out.innerHTML='<b>Checking live...</b>';
 try{
  const r=await fetch('/omni?mint='+q,{cache:'no-store'});
  const d=await r.json().catch(()=>({}));
  if(!r.ok){out.innerHTML='<b style="color:#FF4D8D">Error '+r.status+'</b><br>'+esc(d.detail||d.error||'No pair / upstream down');return;}
  const dec=d.decision||{};
  if(d.error&&!dec.verdict&&!d.verdict){out.innerHTML='<b>Could not score</b><br>'+esc(d.error);return;}
  const raw=String(dec.verdict||d.verdict||d.action||'').toLowerCase();
  let label=raw==='ok'||raw==='pass'?'PASS':raw==='avoid'||raw==='skip'?'SKIP':raw==='caution'||raw==='review'?'REVIEW':(raw||'—').toUpperCase();
  const c=label==='PASS'?'#00FF9D':label==='REVIEW'?'#FFD166':label==='SKIP'?'#FF4D8D':'#00F0FF';
  out.innerHTML='<span style="display:inline-block;padding:6px 12px;font-weight:800;background:'+c+';color:#000">'+esc(label)+'</span> <b>Risk '+esc(dec.risk_score??d.risk_score??'—')+' | Liq $'+esc(d.liquidity_usd??'—')+'</b><br><a href="/omni?mint='+q+'" target="_blank">Open /omni JSON</a>';
 }catch(e){out.innerHTML='<b style="color:#FF4D8D">Network error — try again.</b>';}
}
"""
CSS = """<style id="tv-mini">#mint{font-size:22px!important;padding:18px 20px!important;min-height:64px!important;width:100%!important;box-sizing:border-box!important;border:2px solid #00F0FF!important;border-radius:14px!important;background:#0B0B14!important;color:#fff!important}</style>"""
JS = """<script id="tv-mini-js">(function(){function h(){try{
 var a=document.querySelectorAll('div,section,article,li');
 for(var i=0;i<a.length;i++){var t=(a[i].innerText||'').replace(/\\s+/g,' ');if(!t)continue;
  if((t.includes('SOL')&&t.includes('Risk 0/100'))||(t.includes('SOL')&&t.includes('Mint revoked'))){var n=a[i];for(var d=0;d<4&&n.parentElement;d++){var p=n.parentElement;if(p.innerText.length>t.length*2)break;n=p;}n.style.display='none';break;}}
 var b=document.querySelectorAll('button,a');
 for(var j=0;j<b.length;j++){var x=(b[j].innerText||'').trim().toUpperCase();if((x.includes('SOL')&&x.includes('PASS'))||x.includes('PEACEFROG')||x==='COA'||x.startsWith('COA '))b[j].style.display='none';}
 var inp=document.getElementById('mint');if(inp&&(inp.value||'').trim().startsWith('So111')){inp.value='';inp.setAttribute('value','');inp.placeholder='Paste a token mint...';}
}catch(e){}}if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',h);else h();var k=0;var iv=setInterval(function(){h();if(++k>6)clearInterval(iv);},500);})();</script>"""
def _html(t):
 if not t or "tv-mini" in t: return t
 o=t
 if "</head>" in o: o=o.replace("</head>",CSS+"</head>",1)
 if "</body>" in o: o=o.replace("</body>",JS+"</body>",1)
 else: o+=CSS+JS
 if "tvibe-live-check" not in o:
  tag='<script id="tvibe-live-check">\n'+LIVE_JS+'\n</script>'
  o=o.replace("</body>",tag+"</body>",1) if "</body>" in o else o+tag
 return o
def _build(g,client,mint):
 b=g.get("build_omni");s=g.get("build_signal")
 if callable(b): return b(client,mint)
 if callable(s):
  r=s(client,mint,security=True)
  if isinstance(r,tuple) and r: r=r[0]
  return r if isinstance(r,dict) else {"mint":mint,"error":"empty"}
 return {"mint":mint,"error":"no_builder","action":"skip","nfa":True}
def _agent_pkt(g,pkt):
 v=g.get("_tvibe_agent_view")
 if callable(v):
  try: return v(pkt)
  except Exception: pass
 dec=pkt.get("decision") if isinstance(pkt.get("decision"),dict) else {}
 f=pkt.get("filter") if isinstance(pkt.get("filter"),dict) else {}
 verdict=str(dec.get("verdict") or pkt.get("verdict") or "caution").lower()
 blockers=list(dec.get("blockers") or pkt.get("blockers") or [])
 action="pass" if f.get("pass") is True and not blockers and verdict not in ("avoid","skip") else "skip" if verdict in ("avoid","skip") or blockers else "review"
 return {"mint":pkt.get("mint"),"action":action,"verdict":verdict,"filter":{"pass":bool(f.get("pass")) if f.get("pass") is not None else False},"risk_score":dec.get("risk_score") if dec.get("risk_score") is not None else pkt.get("risk_score"),"liquidity_usd":pkt.get("liquidity_usd"),"unknowns":list(dec.get("unknowns") or pkt.get("unknowns") or [])[:6],"blockers":blockers[:6],"valid_for_s":30,"nfa":True}
def _omni(g):
 app=g.get("app")
 if app is None: return
 try: app.router.routes[:]=[r for r in app.router.routes if getattr(r,"path",None)!="/omni"]
 except Exception: pass
 from fastapi import Query,Request,HTTPException
 @app.get("/omni",tags=["product"])
 async def omni(request:Request,mint:str|None=Query(default=None),view:str=Query("full")):
  m=(mint or request.query_params.get("mint") or request.query_params.get("request") or "").strip()
  if not m: return {"mint":None,"error":"mint is required: /omni?mint=<MINT>","nfa":True}
  if not MINT_RE.match(m): return {"mint":m,"error":"Invalid Solana token mint address","nfa":True}
  rl=g.get("rate_limited");ip=g.get("client_ip") or (lambda r:"unknown")
  try:
   if callable(rl):
    w=rl(ip(request),cost=4)
    if w: raise HTTPException(status_code=429,detail=f"rate limited, retry after {w}s")
  except HTTPException: raise
  except Exception: pass
  c=getattr(request.app.state,"client",None)
  if c is None:
   import httpx
   async with httpx.AsyncClient(timeout=25.0) as c: pkt=await _build(g,c,m)
  else: pkt=await _build(g,c,m)
  if not isinstance(pkt,dict): pkt={"mint":m,"error":"bad_packet","nfa":True}
  if (view or "").lower() in ("agent","compact","action"): return _agent_pkt(g,pkt)
  return pkt
 print("[patch_live_fix] /omni replaced (v30-mini)")
def _play(g):
 app=g.get("app")
 if app is None: return
 try: app.router.routes[:]=[r for r in app.router.routes if getattr(r,"path",None)!="/play"]
 except Exception: pass
 from fastapi import Query,Request
 @app.get("/play",tags=["product"])
 async def play(request:Request,mint:str|None=Query(default=None),request_param:str|None=Query(default=None,alias="request"),view:str=Query("full")):
  m=((mint or request_param) or "").strip() or (request.query_params.get("mint") or request.query_params.get("request") or "").strip()
  if not m: return {"mint":None,"error":"mint is required: /play?mint=<MINT>","nfa":True}
  if not MINT_RE.match(m): return {"mint":m,"error":"Invalid Solana token mint address","nfa":True}
  c=getattr(request.app.state,"client",None)
  if c is None:
   import httpx
   async with httpx.AsyncClient(timeout=25.0) as c: pkt=await _build(g,c,m)
  else: pkt=await _build(g,c,m)
  if not isinstance(pkt,dict): pkt={"mint":m,"error":"bad_packet","nfa":True}
  if (view or "").lower() in ("agent","compact","action"): return _agent_pkt(g,pkt)
  return pkt
 print("[patch_live_fix] /play replaced (v30-mini)")
def _agent(g):
 app=g.get("app")
 if app is None: return
 try: app.router.routes[:]=[r for r in app.router.routes if getattr(r,"path",None) not in ("/agent.json","/agent","/__main_status")]
 except Exception: pass
 @app.get("/agent.json",tags=["product"])
 async def aj(): return {"name":"TVibe Signal","version":"v30-mini","endpoints":{"check":"GET /omni?mint=<MINT>","compact":"GET /omni?mint=<MINT>&view=agent","play":"GET /play?mint=<MINT>","health":"GET /health","status":"GET /__main_status"},"verdicts":["PASS","REVIEW","CAUTION","AVOID","SKIP"],"rules":["Always call /omni. Never guess.","Error + no verdict = could-not-score, never PASS.","Never PASS on fallback / no_builder.","Mint = 32-44 base58. SOL mint has no pair."],"nfa":True}
 from fastapi.responses import PlainTextResponse
 @app.get("/agent",tags=["product"],response_class=PlainTextResponse)
 async def ag(): return "# TVibe Signal\nCheck: GET /omni?mint=<MINT>\nCompact: GET /omni?mint=<MINT>&view=agent\nVerdicts: PASS / REVIEW / CAUTION / AVOID / SKIP\nNever guess. Error + no verdict = could-not-score, never PASS.\nNot financial advice.\n"
 @app.get("/__main_status",tags=["product"])
 async def st(): return {"main_py":"loader","patch_live_fix":"v30-mini","engine":"deep-via-patch_builder-if-loaded"}
 print("[patch_live_fix] /agent + /agent.json + /__main_status (v30-mini)")
class _SafeLayoutASGI:
 def __init__(self,inner,g=None): self.inner=inner;self.g=g or {}
 def __getattr__(self,n): return getattr(self.inner,n)
 async def _json(self,send,status,obj):
  b=json.dumps(obj).encode()
  await send({"type":"http.response.start","status":status,"headers":[(b"content-type",b"application/json"),(b"cache-control",b"no-store"),(b"content-length",str(len(b)).encode())]})
  await send({"type":"http.response.body","body":b})
 async def __call__(self,scope,receive,send):
  if scope.get("type")=="http" and scope.get("method")=="GET" and scope.get("path") in ("/play","/omni"):
   try:
    from urllib.parse import parse_qsl
    d=dict(parse_qsl(scope.get("query_string",b"").decode("latin-1"),keep_blank_values=True))
    m=(d.get("mint") or d.get("request") or "").strip()
    if not m: await self._json(send,200,{"mint":None,"error":"mint is required","nfa":True});return
    if not MINT_RE.match(m): await self._json(send,200,{"mint":m,"error":"Invalid Solana token mint address","nfa":True});return
    pkt=None
    if callable(self.g.get("build_omni")) or callable(self.g.get("build_signal")):
     import httpx
     async with httpx.AsyncClient(timeout=25.0) as c: pkt=await _build(self.g,c,m)
    if not isinstance(pkt,dict): pkt={"mint":m,"error":"no_builder","action":"skip","nfa":True}
    if (d.get("view") or "").lower() in ("agent","compact","action"): pkt=_agent_pkt(self.g,pkt)
    await self._json(send,200,pkt);return
   except Exception as e: print(f"[patch_live_fix] ASGI intercept fail (fall-through): {e}")
  if scope.get("type")!="http" or scope.get("method")!="GET" or scope.get("path")!="/":
   return await self.inner(scope,receive,send)
  start=None;chunks=[]
  async def cap(msg):
   nonlocal start
   if msg["type"]=="http.response.start": start=msg
   elif msg["type"]=="http.response.body": chunks.append(msg.get("body",b""))
  try: await self.inner(scope,receive,cap)
  except Exception: raise
  if start is None: return
  status=start["status"];headers=list(start["headers"]);body=b"".join(chunks)
  try:
   hd={k.lower():v for k,v in headers};ct=hd.get(b"content-type",b"").decode("latin-1").lower()
   if status==200 and "text/html" in ct and b"content-encoding" not in hd:
    t=body.decode("utf-8","ignore");p=_html(t)
    if p!=t: body=p.encode("utf-8")
  except Exception: pass
  keep=[(k,v) for k,v in headers if k.lower()!=b"content-length"]
  await send({"type":"http.response.start","status":status,"headers":keep+[(b"content-length",str(len(body)).encode())]})
  await send({"type":"http.response.body","body":body})
def apply(g):
 if not isinstance(g,dict): raise TypeError("apply expects dict")
 _omni(g);_play(g);_agent(g)
 h=g.get("HOME_HTML")
 if isinstance(h,str) and h: g["HOME_HTML"]=_html(h)
 g["_SafeLayoutASGI"]=_SafeLayoutASGI
 app=g.get("app")
 if app is not None and not isinstance(app,_SafeLayoutASGI):
  try: g["app"]=_SafeLayoutASGI(app,g)
  except Exception as e: print(f"[patch_live_fix] wrapper fail (non-fatal): {e}")
 print("[patch_live_fix] applied v30-mini")

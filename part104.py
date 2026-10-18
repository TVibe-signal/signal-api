# ---------- v2.84: TVibe home - X link, inline mint check (no raw JSON), color-coded result ----------
VERSION = "2.84.0"
app.version = VERSION
app.openapi_schema = None

from fastapi.responses import HTMLResponse, PlainTextResponse

BRAND = "TVibe Signal"
DONATE_SOL = "3iAVBvE4aU4A5DTKCqzu6jg79UfW6aEnqUD1pjfew18n"
BASE = "https://signal-api-24q4.onrender.com"
GITHUB_URL = "https://github.com/TVibex402/signal-api"
X_URL = "https://x.com/realTVibe"
DONATE_NOTE = (
    f"{BRAND} is free and open source. If the public instance helps your agents, "
    "you can tip SOL to cover hosting & RPC. Never required."
)
FAIR_USE = f"""{BRAND} public instance - FREE, fair use
- About 30 requests/minute without a key (429 if exceeded)
- /signals batch: max 10 mints per call
- Cache the same mint 15-30s on the client
- Prefer GET /omni once over polling many small routes
- Heavy use: self-host from GitHub (your track-record starts empty)
- Not financial advice. Heuristics only.

Optional SOL tip (never required):
  {DONATE_SOL}
"""

# Plain (non f-string) blocks: no need to double the braces here.
CHECK_CSS = r"""
nav .pill{display:inline-flex;align-items:center;gap:.4rem;border:1px solid var(--line);background:rgba(15,22,34,.7);color:var(--text);padding:.3rem .7rem;border-radius:.65rem;margin-left:.6rem}
nav .pill:hover{border-color:var(--a)}
.ic{width:15px;height:15px;fill:currentColor;flex:none}
.logo{display:flex;align-items:center;gap:.5rem}
.logo img{width:26px;height:26px;border-radius:7px}
footer a.fx{display:inline-flex;align-items:center;gap:.3rem}
.hint button{background:none;border:0;color:var(--a);cursor:pointer;font:inherit;padding:0}
.check form button:disabled{opacity:.6;cursor:wait}
#out{margin-top:1rem;text-align:left}
.r-load{display:flex;align-items:center;gap:.6rem;color:var(--muted);font-size:.88rem;padding:.6rem .2rem}
.r-spin{width:18px;height:18px;border:2px solid var(--line);border-top-color:var(--a);border-radius:50%;animation:rsp .8s linear infinite;flex:none}
@keyframes rsp{to{transform:rotate(360deg)}}
.r-err{border:1px solid #6e2523;background:rgba(46,17,18,.8);color:#ffb4b0;border-radius:.75rem;padding:.7rem .9rem;font-size:.88rem}
.res{animation:rin .35s ease both}
@keyframes rin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.r-hero{display:flex;gap:1rem;align-items:center;border-radius:.9rem;padding:1rem;border:1px solid var(--line);background:rgba(17,27,43,.9)}
.r-hero.ok{border-color:rgba(20,241,149,.45);background:linear-gradient(135deg,rgba(20,241,149,.13),rgba(15,22,34,.9))}
.r-hero.warn{border-color:rgba(245,183,59,.5);background:linear-gradient(135deg,rgba(245,183,59,.14),rgba(15,22,34,.9))}
.r-hero.bad{border-color:rgba(242,86,79,.55);background:linear-gradient(135deg,rgba(242,86,79,.15),rgba(15,22,34,.9))}
.r-ring{position:relative;width:84px;height:84px;flex:none}
.r-ring svg{width:84px;height:84px;transform:rotate(-90deg)}
.r-ring circle{fill:none;stroke-width:8;stroke-linecap:round}
.r-ring .bg{stroke:rgba(255,255,255,.09)}
.r-ring .fg{transition:stroke-dashoffset .9s cubic-bezier(.2,.8,.2,1)}
.r-ring.ok .fg{stroke:#14f195}.r-ring.warn .fg{stroke:#f5b73b}.r-ring.bad .fg{stroke:#f2564f}
.r-ring span{position:absolute;inset:0;display:grid;place-items:center;font-weight:800;font-size:1.35rem;align-content:center}
.r-ring small{display:block;font-size:.62rem;color:var(--muted);font-weight:500;text-align:center;margin-top:-2px}
.r-vtxt{min-width:0}
.r-big{font-size:1.6rem;font-weight:800;letter-spacing:-.02em;display:flex;align-items:center;gap:.55rem;flex-wrap:wrap}
.r-tok{font-size:.88rem;color:var(--muted);font-weight:500}
.r-vtxt p{margin:.3rem 0 0;color:#c9d4e6;font-size:.88rem}
.r-dot{width:12px;height:12px;border-radius:50%;display:inline-block}
.ok .r-dot{background:#14f195;box-shadow:0 0 12px #14f195}
.warn .r-dot{background:#f5b73b;box-shadow:0 0 12px #f5b73b}
.bad .r-dot{background:#f2564f;box-shadow:0 0 12px #f2564f}
.r-mint{margin:.6rem .1rem 0;font-size:.75rem;color:var(--muted);word-break:break-all;font-family:ui-monospace,monospace}
.r-chips{display:flex;flex-wrap:wrap;gap:.45rem;margin:.75rem 0 .2rem}
.r-chip{display:inline-flex;align-items:center;gap:.35rem;border-radius:999px;padding:.2rem .65rem;font-size:.78rem;border:1px solid var(--line);background:rgba(10,18,32,.8);color:var(--muted)}
.r-chip.ok{color:#14f195;border-color:rgba(20,241,149,.4);background:rgba(11,32,22,.8)}
.r-chip.warn{color:#f5b73b;border-color:rgba(245,183,59,.45);background:rgba(34,26,9,.8)}
.r-chip.bad{color:#f2564f;border-color:rgba(242,86,79,.5);background:rgba(36,14,15,.8)}
.r-grid{display:grid;grid-template-columns:1fr 1fr;gap:.6rem;margin-top:.6rem}
@media(max-width:640px){.r-grid{grid-template-columns:1fr}.r-hero{flex-direction:column;align-items:flex-start}}
.r-grp,.r-box{background:rgba(17,27,43,.9);border:1px solid var(--line);border-radius:.8rem;padding:.7rem .85rem}
.r-grp h4,.r-box h3{margin:0 0 .5rem;font-size:.88rem;display:flex;align-items:center;gap:.5rem}
.r-grp h4 b{margin-left:auto;font-size:.75rem;color:var(--muted);font-weight:600}
.r-sym{width:20px;height:20px;border-radius:6px;display:grid;place-items:center;font-size:.75rem;font-weight:800}
.r-grp ul{list-style:none;margin:0;padding:0}
.r-grp li{font-size:.83rem;padding:.3rem 0 .3rem .7rem;border-left:2px solid var(--line);margin-bottom:.25rem;color:#d3ddee}
.r-grp.ok{border-color:rgba(20,241,149,.35)}.r-grp.ok .r-sym{background:rgba(20,241,149,.15);color:#14f195}.r-grp.ok li{border-left-color:#14f195}
.r-grp.warn{border-color:rgba(245,183,59,.4)}.r-grp.warn .r-sym{background:rgba(245,183,59,.15);color:#f5b73b}.r-grp.warn li{border-left-color:#f5b73b}
.r-grp.bad{border-color:rgba(242,86,79,.45)}.r-grp.bad .r-sym{background:rgba(242,86,79,.18);color:#f2564f}.r-grp.bad li{border-left-color:#f2564f}
.r-grp.mut .r-sym{background:rgba(139,155,180,.15);color:var(--muted)}.r-grp.mut li{border-left-color:#33415c;color:var(--muted)}
.r-full{grid-column:1/-1}
.r-vbar{display:flex;height:10px;border-radius:99px;overflow:hidden;background:#0a1220;margin:.2rem 0 .4rem}
.r-vbar i{display:block;height:100%}
.r-vbar i.ok{background:#14f195}.r-vbar i.warn{background:#f5b73b}.r-vbar i.bad{background:#f2564f}
.r-prow{display:flex;gap:.6rem;padding:.5rem 0;border-top:1px solid var(--line)}
.r-prow .r-chip{align-self:flex-start;min-width:72px;justify-content:center}
.r-prow p{margin:.15rem 0 0;font-size:.8rem;color:var(--muted)}
.r-prow small{color:var(--muted)}
.r-tools{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.8rem}
.r-tools .btn{padding:.45rem .85rem;font-size:.82rem}
details.r-raw{margin-top:.6rem;background:#08101c;border:1px solid var(--line);border-radius:.65rem;padding:.5rem .75rem}
details.r-raw summary{cursor:pointer;color:var(--muted);font-size:.82rem}
details.r-raw pre{margin:.5rem 0 0;max-height:300px;overflow:auto;font-size:.75rem}
@media(prefers-reduced-motion:reduce){.res,.r-spin,.r-ring .fg{animation:none!important;transition:none!important}}
"""

CHECK_JS = r'''
(function(){
var $=function(s){return document.querySelector(s)};
var out=$('#out'),inp=$('#mint'),btn=$('#go'),lastJSON='';
var B58=/^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
var SOL='So11111111111111111111111111111111111111112';
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function vc(v){return {ok:'ok',caution:'warn',avoid:'bad'}[String(v||'').toLowerCase()]||'mut'}
function pct(x){return Math.round((Number(x)||0)*100)}
function chip(t,c){return '<span class="r-chip '+(c||'')+'">'+esc(t)+'</span>'}
function copy(text,el){
  function done(){if(el){var o=el.textContent;el.textContent='Copied';setTimeout(function(){el.textContent=o},1200)}}
  function fb(){var t=document.createElement('textarea');t.value=text;document.body.appendChild(t);t.select();try{document.execCommand('copy')}catch(e){}t.remove();done()}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(done,fb)}else fb();
}
function group(title,sym,c,arr){
  if(!Array.isArray(arr)||!arr.length)return '';
  var li=arr.map(function(x){return '<li>'+esc(typeof x==='string'?x:(x.label||x.id||JSON.stringify(x)))+'</li>'}).join('');
  return '<div class="r-grp '+c+'"><h4><span class="r-sym">'+sym+'</span>'+title+'<b>'+arr.length+'</b></h4><ul>'+li+'</ul></div>';
}
function debate(db){
  if(!db)return '';
  var vt=db.votes_weighted||db.votes||{};
  var tot=(vt.ok||0)+(vt.caution||0)+(vt.avoid||0)||1;
  var bar=['ok','caution','avoid'].map(function(k){return '<i class="'+vc(k)+'" style="width:'+((vt[k]||0)/tot*100)+'%"></i>'}).join('');
  var rows=(db.personas||[]).map(function(p){
    return '<div class="r-prow">'+chip(p.verdict,vc(p.verdict))+'<div><b>'+esc(p.persona)+'</b> <small>'+pct(p.confidence)+'%</small><p>'+esc(p.reason)+'</p></div></div>';
  }).join('');
  var ag=db.agreement_weighted!=null?db.agreement_weighted:db.agreement;
  return '<section class="r-box r-full" style="margin:0"><h3>Agent debate '+chip(db.meta_verdict,vc(db.meta_verdict))+'<span style="margin-left:auto;font-weight:500;font-size:.75rem;color:var(--muted)">agreement '+pct(ag)+'%</span></h3><div class="r-vbar">'+bar+'</div>'+rows+'</section>';
}
function render(d){
  var dc=d.decision||{},v=String(dc.verdict||'unknown').toLowerCase(),c=vc(v);
  var risk=Number(dc.risk_score),hasRisk=isFinite(risk)&&dc.risk_score!=null;
  var rc=!hasRisk?'mut':(risk<35?'ok':(risk<65?'warn':'bad'));
  var C=2*Math.PI*34,off=hasRisk?C*(1-Math.min(100,Math.max(0,risk))/100):C;
  var label={ok:'OK',caution:'Caution',avoid:'Avoid'}[v]||v;
  var h='<div class="res">';
  h+='<div class="r-hero '+c+'"><div class="r-ring '+rc+'"><svg viewBox="0 0 84 84"><circle class="bg" cx="42" cy="42" r="34"/><circle class="fg" id="fg" cx="42" cy="42" r="34" stroke-dasharray="'+C.toFixed(1)+'" stroke-dashoffset="'+C.toFixed(1)+'" data-off="'+off.toFixed(1)+'"/></svg><span><div>'+(hasRisk?risk:'?')+'<small>risk</small></div></span></div>';
  h+='<div class="r-vtxt"><div class="r-big"><i class="r-dot"></i>'+esc(label)+'<span class="r-tok">'+esc(d.token||'')+'</span></div><p>'+esc(d.summary||'')+'</p></div></div>';
  h+='<div class="r-mint">'+esc(d.mint||'')+'</div>';
  var chips='';
  if(d.regime&&d.regime.name)chips+=chip('Regime: '+d.regime.name+' ('+pct(d.regime.confidence)+'%)',/risk_off/.test(d.regime.name)?'warn':(/risk_on/.test(d.regime.name)?'ok':''));
  if(d.attention_trap)chips+=chip('Attention trap','warn');
  var t=d.time_to_death;
  if(t&&t.band)chips+=chip('Stress clock: '+t.band+(t.eta_hours?' (~'+t.eta_hours+'h)':''),{slow:'ok',medium:'warn',fast:'bad'}[String(t.band).toLowerCase()]||'');
  var cf=d.counterfactual;
  if(cf&&cf.available&&cf.expected_bad_rate!=null){var r=cf.expected_bad_rate;chips+=chip('Similar cases bad: '+pct(r)+'% (n='+cf.cohort_n+')',r<.25?'ok':(r<.5?'warn':'bad'))}
  var at=d.community&&d.community.attention;
  if(at&&at['24h']!=null)chips+=chip('Attention 24h: '+at['24h'],'');
  if(chips)h+='<div class="r-chips">'+chips+'</div>';
  h+='<div class="r-grid">';
  h+=group('Blockers','\u2716','bad',dc.blockers);
  h+=group('Cautions','\u26A0','warn',dc.cautions);
  h+=group('Positives','\u2714','ok',dc.positives);
  h+=group('Unknowns','?','mut',dc.unknowns);
  h+=group('Pre-rug patterns','\u26A0','warn',d.pre_rug);
  h+=group('What would change this','\u21BB','mut',d.would_change_my_mind);
  h+=debate(d.debate);
  h+='</div>';
  h+='<div class="r-tools"><button type="button" class="btn btn-o" id="cj">Copy JSON</button><button type="button" class="btn btn-o" id="cl">Copy link</button><a class="btn btn-o" href="/omni?mint='+encodeURIComponent(d.mint||'')+'" target="_blank" rel="noopener">Open JSON</a></div>';
  h+='<details class="r-raw"><summary>Raw JSON</summary><pre>'+esc(lastJSON)+'</pre></details>';
  h+='<p class="muted" style="margin-top:.6rem;font-size:.78rem">v'+esc(d.version||'')+' · Heuristics only, not financial advice.</p></div>';
  out.innerHTML=h;
  requestAnimationFrame(function(){requestAnimationFrame(function(){var f=$('#fg');if(f)f.style.strokeDashoffset=f.getAttribute('data-off')})});
  $('#cj').onclick=function(){copy(lastJSON,this)};
  $('#cl').onclick=function(){copy(location.origin+location.pathname+'?mint='+encodeURIComponent(d.mint||''),this)};
}
function showErr(m){out.innerHTML='<div class="r-err">'+esc(m)+'</div>'}
async function run(m){
  m=(m||'').trim();
  if(!B58.test(m)){showErr('That does not look like a Solana mint address. Paste the full CA (32-44 characters).');return}
  btn.disabled=true;btn.textContent='Checking...';
  out.innerHTML='<div class="r-load"><div class="r-spin"></div><span>Checking '+esc(m.slice(0,4))+'...'+esc(m.slice(-4))+' - the first request can take up to 30s if the server is waking up.</span></div>';
  var ctl=new AbortController(),to=setTimeout(function(){ctl.abort()},60000);
  try{
    var r=await fetch('/omni?mint='+encodeURIComponent(m),{signal:ctl.signal,headers:{'Accept':'application/json'}});
    var txt=await r.text();var d=null;try{d=JSON.parse(txt)}catch(e){}
    if(r.status===429){showErr('Too many requests. Wait a few seconds and press Check again.')}
    else if(!r.ok||!d){var det=d&&(d.detail||d.error);showErr('Request failed ('+r.status+'). '+(det?(typeof det==='string'?det:JSON.stringify(det)):'Try again in a moment.'))}
    else{lastJSON=JSON.stringify(d,null,2);render(d);try{history.replaceState(null,'','?mint='+encodeURIComponent(m))}catch(e){}}
  }catch(e){showErr(e&&e.name==='AbortError'?'Timed out after 60s. Press Check again.':'Network error. Check your connection and try again.')}
  finally{clearTimeout(to);btn.disabled=false;btn.textContent='Check'}
}
$('#f').addEventListener('submit',function(e){e.preventDefault();run(inp.value)});
inp.addEventListener('paste',function(){setTimeout(function(){var v=inp.value.trim();inp.value=v;if(B58.test(v))run(v)},0)});
$('#demo').addEventListener('click',function(){inp.value=SOL;run(SOL)});
var q=new URLSearchParams(location.search).get('mint');
if(q){inp.value=q;run(q)}
})();
'''

HOME_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#070b12">
<meta name="color-scheme" content="dark">
<title>{BRAND} — Solana signals for AI agents</title>
<meta name="description" content="Free Solana token signals for AI agents. Paste a mint, get verdict and reasons. Measured on /stats. Not financial advice.">
<meta property="og:title" content="{BRAND} — Solana signals for AI agents">
<meta property="og:description" content="Free, open source. One call for verdict + reasons. Accuracy public on /stats.">
<meta property="og:image" content="{BASE}/og.svg">
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>
:root {{
  --bg:#070b12; --card:rgba(15,22,34,.92); --line:rgba(40,56,78,.9);
  --text:#e8eef6; --muted:#8b9bb4; --a:#14f195; --b:#9945ff; --c:#6366f1;
}}
* {{ box-sizing:border-box; margin:0; padding:0 }}
body {{
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.55; min-height: 100vh;
}}
.bg {{ position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }}
.bg span {{
  position: absolute; width: 55vmax; height: 55vmax; border-radius: 50%;
  filter: blur(10px); opacity: .42;
}}
.bg span:nth-child(1) {{
  left: -20vmax; top: -25vmax;
  background: radial-gradient(circle, rgba(153,69,255,.55), transparent 65%);
}}
.bg span:nth-child(2) {{
  right: -25vmax; top: 18vh;
  background: radial-gradient(circle, rgba(20,241,149,.28), transparent 65%);
}}
.bg span:nth-child(3) {{
  left: 18vw; bottom: -35vmax;
  background: radial-gradient(circle, rgba(99,102,241,.38), transparent 65%);
}}
.wrap {{ position: relative; z-index: 1; max-width: 960px; margin: 0 auto; padding: 0 1.25rem 4rem }}
nav {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 1.1rem 0; border-bottom: 1px solid var(--line); flex-wrap: wrap; gap: .6rem;
}}
.logo {{ font-weight: 800; letter-spacing: -.03em; font-size: 1.2rem }}
.logo em {{
  font-style: normal;
  background: linear-gradient(120deg, var(--b), var(--a));
  -webkit-background-clip: text; background-clip: text; color: transparent;
}}
nav a {{ color: var(--muted); text-decoration: none; margin-left: 1rem; font-size: .92rem }}
nav a:hover {{ color: var(--text) }}
.hero {{ text-align: center; padding: 2.8rem 0 1.5rem }}
.badge {{
  display: inline-block; font-size: .72rem; letter-spacing: .07em; text-transform: uppercase;
  color: var(--a); border: 1px solid rgba(20,241,149,.35); padding: .35rem .75rem;
  border-radius: 999px; margin-bottom: 1rem;
}}
h1 {{
  font-size: clamp(2rem, 5.5vw, 3.1rem); font-weight: 800; letter-spacing: -.04em;
  line-height: 1.12; margin-bottom: 1rem;
}}
h1 span {{
  background: linear-gradient(135deg, #a78bfa, #14f195);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}}
.sub {{ color: var(--muted); font-size: 1.05rem; max-width: 560px; margin: 0 auto 1.4rem }}
.sub a {{ color: var(--a) }}
.cta {{ display: flex; flex-wrap: wrap; gap: .7rem; justify-content: center; margin-bottom: 1.25rem }}
.btn {{
  display: inline-block; padding: .75rem 1.35rem; border-radius: .75rem;
  font-weight: 600; text-decoration: none; font-size: .95rem; border: none; cursor: pointer;
}}
.btn-p {{ background: linear-gradient(135deg, var(--b), var(--c)); color: #fff }}
.btn-g {{ background: rgba(20,241,149,.12); color: var(--a); border: 1px solid rgba(20,241,149,.35) }}
.btn-o {{ border: 1px solid var(--line); color: var(--text); background: transparent }}
.check {{
  max-width: 560px; margin: 0 auto 1.5rem; text-align: left;
  background: var(--card); border: 1px solid var(--line); border-radius: 1rem;
  padding: 1.15rem 1.2rem;
}}
.check h3 {{ font-size: .95rem; margin-bottom: .35rem }}
.check form {{ display: flex; flex-wrap: wrap; gap: .5rem; margin-top: .65rem }}
.check input {{
  flex: 1; min-width: 200px; padding: .7rem .9rem; border-radius: .65rem;
  border: 1px solid var(--line); background: #0c121c; color: var(--text);
  font-family: ui-monospace, monospace; font-size: .85rem;
}}
.grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem; margin: 1.5rem 0;
}}
.card {{
  background: var(--card); border: 1px solid var(--line); border-radius: 1rem;
  padding: 1.15rem 1.2rem;
}}
.card h3 {{ font-size: .95rem; margin-bottom: .4rem }}
.card p {{ color: var(--muted); font-size: .88rem }}
.card code {{ color: var(--a); font-size: .8rem }}
pre {{
  background: #0c121c; border: 1px solid var(--line); border-radius: .85rem;
  padding: 1rem 1.1rem; overflow-x: auto; font-size: .82rem; color: #c7d2fe; margin-top: 1rem;
}}
section {{ margin: 2rem 0 }}
section h2 {{ font-size: 1.15rem; margin-bottom: .75rem }}
.muted {{ color: var(--muted); font-size: .9rem }}
.donate-box {{
  background: linear-gradient(145deg, rgba(153,69,255,.14), rgba(20,241,149,.08));
  border: 1px solid rgba(20,241,149,.32); border-radius: 1rem; padding: 1.25rem 1.3rem;
}}
.sol {{
  word-break: break-all; color: var(--a);
  font-family: ui-monospace, monospace; font-size: .85rem; margin-top: .65rem; user-select: all;
}}
.copy-row {{ margin-top: .75rem; display: flex; flex-wrap: wrap; gap: .5rem; align-items: center }}
.copy-btn {{
  cursor: pointer; border: 1px solid rgba(20,241,149,.4); background: rgba(20,241,149,.1);
  color: var(--a); border-radius: .5rem; padding: .4rem .85rem; font-size: .85rem; font-weight: 600;
}}
footer {{
  margin-top: 3rem; padding-top: 1.25rem; border-top: 1px solid var(--line);
  color: var(--muted); font-size: .85rem; text-align: center;
}}
footer a {{ color: var(--a) }}
{CHECK_CSS}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" ar
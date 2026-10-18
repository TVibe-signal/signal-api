# ---------- v2.84: TVibe home - X link, inline mint check (no raw JSON), color-coded result ----------
VERSION = "2.87.0"
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
body{background-image:linear-gradient(rgba(255,255,255,.022) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.022) 1px,transparent 1px);background-size:46px 46px;background-position:center top}
nav{position:sticky;top:0;z-index:30;background:rgba(7,11,18,.72);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px)}
nav a{margin-left:0;padding:.38rem .65rem;border-radius:.6rem}
nav a:hover{background:rgba(255,255,255,.05)}
.navlinks{display:flex;gap:.2rem;align-items:center;flex-wrap:wrap}
nav .pill{display:inline-flex;align-items:center;gap:.4rem;border:1px solid var(--line);background:rgba(15,22,34,.75);color:var(--text);margin-left:.25rem}
nav .pill:hover{border-color:var(--a);background:rgba(20,241,149,.07)}
.ic{width:15px;height:15px;fill:currentColor;flex:none}
@media(max-width:600px){nav{flex-direction:column;align-items:flex-start}.navlinks{width:100%;flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none;padding-bottom:.15rem}.navlinks::-webkit-scrollbar{display:none}.navlinks a{white-space:nowrap}}
footer a.fx{display:inline-flex;align-items:center;gap:.3rem}
.hero h1{letter-spacing:-.045em}
.check{max-width:720px;background:linear-gradient(var(--card),var(--card)) padding-box,linear-gradient(135deg,rgba(153,69,255,.7),rgba(20,241,149,.55)) border-box;border:1px solid transparent;box-shadow:0 24px 60px -24px rgba(99,102,241,.45)}
.check h3{font-size:1.05rem}
.check form{flex-wrap:nowrap}
.check form .btn{padding:.7rem 1.05rem;white-space:nowrap}
.check input:focus{outline:none;border-color:var(--a);box-shadow:0 0 0 3px rgba(20,241,149,.12)}
.check form button:disabled{opacity:.6;cursor:wait}
.tryrow{display:flex;flex-wrap:wrap;gap:.4rem;align-items:center;margin-top:.7rem;font-size:.8rem;color:var(--muted)}
.r-try{cursor:pointer;border:1px solid var(--line);background:rgba(10,18,32,.8);color:var(--text);border-radius:999px;padding:.25rem .7rem;font-size:.78rem}
.r-try:hover{border-color:var(--a);color:var(--a)}
.strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.6rem;margin:1.2rem 0}
.strip div{border:1px solid var(--line);background:rgba(15,22,34,.6);border-radius:.8rem;padding:.65rem .85rem}
.strip b{display:block;font-size:.92rem}
.strip span{font-size:.78rem;color:var(--muted)}
.card{transition:border-color .2s}
.card:hover{border-color:rgba(20,241,149,.4)}
#out{margin-top:1rem;text-align:left}
.r-load{display:flex;align-items:center;gap:.6rem;color:var(--muted);font-size:.88rem;padding:.6rem .2rem}
.r-spin{width:18px;height:18px;border:2px solid var(--line);border-top-color:var(--a);border-radius:50%;animation:rsp .8s linear infinite;flex:none}
@keyframes rsp{to{transform:rotate(360deg)}}
.r-err{border:1px solid #6e2523;background:rgba(46,17,18,.8);color:#ffb4b0;border-radius:.75rem;padding:.7rem .9rem;font-size:.88rem}
.res{animation:rin .35s ease both}
@keyframes rin{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.r-hero{display:flex;gap:1.1rem;align-items:center;border-radius:1rem;padding:1.1rem;border:1px solid var(--line);background:rgba(17,27,43,.9)}
.r-hero.ok{border-color:rgba(20,241,149,.45);background:linear-gradient(135deg,rgba(20,241,149,.14),rgba(15,22,34,.9))}
.r-hero.warn{border-color:rgba(245,183,59,.5);background:linear-gradient(135deg,rgba(245,183,59,.14),rgba(15,22,34,.9))}
.r-hero.bad{border-color:rgba(242,86,79,.55);background:linear-gradient(135deg,rgba(242,86,79,.15),rgba(15,22,34,.9))}
.r-ring{position:relative;width:88px;height:88px;flex:none}
.r-ring svg{width:88px;height:88px;transform:rotate(-90deg)}
.r-ring circle{fill:none;stroke-width:8;stroke-linecap:round}
.r-ring .bg{stroke:rgba(255,255,255,.09)}
.r-ring .fg{transition:stroke-dashoffset .9s cubic-bezier(.2,.8,.2,1)}
.r-ring.ok .fg{stroke:#14f195}.r-ring.warn .fg{stroke:#f5b73b}.r-ring.bad .fg{stroke:#f2564f}.r-ring.mut .fg{stroke:#8b9bb4}
.r-ring .n{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;font-weight:800;font-size:1.45rem;line-height:1}
.r-ring .n small{font-size:.62rem;color:var(--muted);font-weight:500;margin-top:.2rem}
.r-vtxt{min-width:0}
.r-big{font-size:1.65rem;font-weight:800;letter-spacing:-.025em;display:flex;align-items:center;gap:.55rem;flex-wrap:wrap}
.r-tok{font-size:.9rem;color:var(--muted);font-weight:600;border:1px solid var(--line);border-radius:.5rem;padding:.05rem .5rem}
.r-vtxt p{margin:.35rem 0 0;color:#c9d4e6;font-size:.88rem}
.r-dot{width:12px;height:12px;border-radius:50%;display:inline-block}
.ok .r-dot{background:#14f195;box-shadow:0 0 12px #14f195}
.warn .r-dot{background:#f5b73b;box-shadow:0 0 12px #f5b73b}
.bad .r-dot{background:#f2564f;box-shadow:0 0 12px #f2564f}
.r-mint{margin:.7rem .1rem 0;font-size:.74rem;color:var(--muted);word-break:break-all;font-family:ui-monospace,monospace}
.r-links{display:flex;flex-wrap:wrap;gap:.4rem;margin-top:.5rem}
.r-links .btn,.r-tools .btn{padding:.4rem .8rem;font-size:.8rem;border-radius:.6rem}
.r-chips{display:flex;flex-wrap:wrap;gap:.45rem;margin:.8rem 0 .2rem}
.r-chip{display:inline-flex;align-items:center;gap:.35rem;border-radius:999px;padding:.2rem .65rem;font-size:.78rem;border:1px solid var(--line);background:rgba(10,18,32,.8);color:var(--muted)}
.r-chip.ok{color:#14f195;border-color:rgba(20,241,149,.4);background:rgba(11,32,22,.8)}
.r-chip.warn{color:#f5b73b;border-color:rgba(245,183,59,.45);background:rgba(34,26,9,.8)}
.r-chip.bad{color:#f2564f;border-color:rgba(242,86,79,.5);background:rgba(36,14,15,.8)}
.r-h{margin:1.1rem 0 .5rem;font-size:.95rem;font-weight:700;display:flex;align-items:center;gap:.5rem}
.r-h small{font-weight:500;color:var(--muted);font-size:.75rem}
.r-tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:.55rem;margin-top:.8rem}
.r-tile{background:rgba(17,27,43,.9);border:1px solid var(--line);border-top:2px solid var(--line);border-radius:.75rem;padding:.6rem .75rem}
.r-tile small{display:block;font-size:.72rem;color:var(--muted)}
.r-tile b{font-size:1.12rem;letter-spacing:-.01em}
.r-tile.ok{border-top-color:#14f195}.r-tile.warn{border-top-color:#f5b73b}.r-tile.bad{border-top-color:#f2564f}
.r-grid{display:grid;grid-template-columns:1fr 1fr;gap:.6rem;align-items:start}
@media(max-width:640px){.r-grid{grid-template-columns:1fr}.r-hero{flex-direction:column;align-items:flex-start}.check form{flex-wrap:wrap}}
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
.r-sell{display:grid;grid-template-columns:auto 1fr auto;gap:.5rem .75rem;align-items:center;margin-top:.6rem;font-size:.85rem}
.r-bar{height:8px;border-radius:99px;background:#0a1220;overflow:hidden}
.r-bar i{display:block;height:100%;border-radius:99px}
.r-bar i.ok{background:#14f195}.r-bar i.warn{background:#f5b73b}.r-bar i.bad{background:#f2564f}
.r-sell .ok{color:#14f195}.r-sell .warn{color:#f5b73b}.r-sell .bad{color:#f2564f}
.r-note{font-size:.78rem;color:var(--muted);margin:.5rem 0 0}
.r-next{margin:0;padding-left:1.1rem;font-size:.85rem;color:#c9d4e6}
.r-next li{margin:.25rem 0}
.r-tools{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:1rem}
details.r-raw{margin-top:.6rem;background:#08101c;border:1px solid var(--line);border-radius:.65rem;padding:.5rem .75rem}
details.r-raw summary{cursor:pointer;color:var(--muted);font-size:.82rem}
details.r-raw pre{margin:.5rem 0 0;max-height:300px;overflow:auto;font-size:.75rem}

:root{--muted:#9db0ca;--sans:"Inter",ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--disp:"Space Grotesk","Inter",ui-sans-serif,system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
body{font-family:var(--sans);font-size:16px;line-height:1.6}
h1,.logo,.r-big,.r-h,.card h3,section h2,.check h3,.strip b{font-family:var(--disp)}
code,pre,.r-mint,.sol,.check input{font-family:var(--mono)}
.sub{font-size:1.08rem;color:#aab9d0}
.check input{font-size:.9rem}
.r-hero.ok .r-big{color:#3df5ad}.r-hero.warn .r-big{color:#ffc94d}.r-hero.bad .r-big{color:#ff6b64}
.r-big{font-size:2.05rem;font-weight:700;line-height:1.1}
.r-tok{font-size:.95rem;font-family:var(--disp);color:#c4d0e4;background:rgba(255,255,255,.06)}
.r-vtxt p{font-size:.96rem;line-height:1.55;color:#dbe5f5}
.r-ring .n{font-family:var(--disp);font-size:1.85rem;font-weight:700}
.r-ring .n small{font-family:var(--sans);font-size:.66rem;color:#aab9d0}
.r-h{font-size:1.2rem;font-weight:700;margin:1.5rem 0 .65rem;letter-spacing:-.01em}
.r-h::before{content:"";width:4px;height:1.1em;border-radius:3px;background:linear-gradient(var(--b),var(--a))}
.r-h small{font-family:var(--sans)}
.r-tile{padding:.7rem .85rem}
.r-tile small{font-size:.8rem;color:#a9b9d0;margin-bottom:.1rem}
.r-tile b{font-family:var(--disp);font-size:1.5rem;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.r-chip{font-size:.84rem;font-weight:600;padding:.28rem .75rem}
.r-grp,.r-box{padding:.85rem 1rem}
.r-grp h4,.r-box h3{font-size:1.05rem;font-family:var(--disp);margin-bottom:.65rem}
.r-grp.ok h4{color:#3df5ad}.r-grp.warn h4{color:#ffc94d}.r-grp.bad h4{color:#ff6b64}.r-grp.mut h4{color:#bdcae0}
.r-grp li{font-size:.97rem;line-height:1.55;padding:.4rem 0 .4rem .85rem;margin-bottom:.35rem;color:#e8eefa}
.r-grp.mut li{color:#b0bfd5}
.num{font-family:var(--mono);font-weight:700;font-size:.9em;padding:.02em .35em;border-radius:.35em;background:rgba(255,255,255,.08);white-space:nowrap;color:#fff}
.r-grp.ok .num{color:#3df5ad;background:rgba(20,241,149,.12)}
.r-grp.warn .num{color:#ffc94d;background:rgba(245,183,59,.14)}
.r-grp.bad .num{color:#ff6b64;background:rgba(242,86,79,.15)}
.r-vtxt .num{background:rgba(255,255,255,.1)}
.r-prow b{font-size:.98rem}
.r-prow p{font-size:.88rem;color:#aab9d0}
.r-sell{font-size:.95rem}
.r-sell b{font-family:var(--mono);font-size:.9rem}
.r-note{font-size:.84rem}
.r-next{font-size:.95rem;line-height:1.6}
.r-mint{font-size:.78rem}
.btn{font-family:var(--sans)}
.r-tile em{display:block;font-style:normal;font-size:.82rem;font-weight:600;margin-top:.1rem;color:var(--muted)}
.r-tile em.ok{color:#3df5ad}.r-tile em.bad{color:#ff6b64}
.r-box .r-sell{margin-top:0}
@media(max-width:600px){nav{position:static}.r-big{font-size:1.8rem}}
@media(prefers-reduced-motion:reduce){.res,.r-spin,.r-ring .fg{animation:none!important;transition:none!important}}
"""

CHECK_JS = r'''
(function(){
var $=function(s){return document.querySelector(s)};
var out=$('#out'),inp=$('#mint'),btn=$('#go');
var B58=/^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
var st=null,token=0;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function vc(v){return {ok:'ok',caution:'warn',avoid:'bad'}[String(v||'').toLowerCase()]||'mut'}
function pct(x){return Math.round((Number(x)||0)*100)}
function chip(t,c){return '<span class="r-chip '+(c||'')+'">'+esc(t)+'</span>'}
function isNum(v){return typeof v==='number'&&isFinite(v)}
function isNumLike(v){return isNum(v)||(typeof v==='string'&&v.trim()!==''&&isFinite(Number(v)))}
function compact(n){n=Number(n);var a=Math.abs(n);if(a>=1e9)return '$'+(n/1e9).toFixed(2)+'B';if(a>=1e6)return '$'+(n/1e6).toFixed(2)+'M';if(a>=1e3)return '$'+(n/1e3).toFixed(1)+'K';return '$'+n.toFixed(0)}
function nice(f){f=String(f||'').replace(/_/g,' ').trim();return f.charAt(0).toUpperCase()+f.slice(1)}
function flagCls(f){f=String(f).toLowerCase();return /dump|sell|rug|drain|honeypot|bundle|sniper/.test(f)?'bad':(/buy|accum/.test(f)?'':'warn')}
function fmtAge(d){if(d<1/24)return Math.max(1,Math.round(d*1440))+' min';if(d<1)return Math.round(d*24)+' h';if(d>=730)return (d/365).toFixed(1)+' yr';return (d<30?Math.round(d*10)/10:Math.round(d))+' d'}
function hl(t){return t.replace(/(\$\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$\d+(?:\.\d+)?|\d+(?:\.\d+)?%\+?|\b\d+\+? ?(?:days?|hours?|h)\b)/g,'<span class="num">$1</span>')}
function tidy(s){return String(s==null?'':s).replace(/\s*\([^()]*\u03b1=\{[^}]*\}\)/,'')}
function copy(text,el){
  function done(){if(el){var o=el.textContent;el.textContent='Copied';setTimeout(function(){el.textContent=o},1200)}}
  function fb(){var t=document.createElement('textarea');t.value=text;document.body.appendChild(t);t.select();try{document.execCommand('copy')}catch(e){}t.remove();done()}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(done,fb)}else fb();
}
function find(o,re,pred,d){
  d=d||0;if(!o||typeof o!=='object'||d>4)return undefined;var k,v;
  for(k in o){if(re.test(k)){v=o[k];if(pred(v))return v}}
  for(k in o){v=o[k];if(v&&typeof v==='object'){var r=find(v,re,pred,d+1);if(r!==undefined)return r}}
  return undefined;
}
function findSizes(o,d){
  d=d||0;if(!o||typeof o!=='object'||d>4)return null;
  if(Array.isArray(o)&&o.length&&o[0]&&typeof o[0]==='object'){
    var ks=Object.keys(o[0]);
    var a=ks.filter(function(k){return /usd|size|amount|notional/i.test(k)&&isNum(o[0][k])})[0];
    var b=ks.filter(function(k){return /loss|impact|slip|cost/i.test(k)&&isNum(o[0][k])})[0];
    if(a&&b)return o.map(function(it){return {size:it[a],loss:it[b],lk:b}});
  }
  for(var k in o){var r=findSizes(o[k],d+1);if(r)return r}
  return null;
}
function lossPct(v,k){v=Number(v);if(/bps/i.test(k))return v/100;if(/pct|percent/i.test(k))return v;return Math.abs(v)<=1?v*100:v}
function fmtUsd(n){return '$'+Number(n).toLocaleString('en-US',{maximumFractionDigits:0})}
function fmtPrice(n){n=Number(n);return '$'+(n>=1?n.toLocaleString('en-US',{maximumFractionDigits:2}):n.toPrecision(4))}
function group(title,sym,c,arr){
  if(!Array.isArray(arr)||!arr.length)return '';
  var li=arr.map(function(x){return '<li>'+hl(esc(tidy(typeof x==='string'?x:(x.label||x.id||JSON.stringify(x)))))+'</li>'}).join('');
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
function tile(label,val,c,sub,sc){return '<div class="r-tile '+(c||'')+'"><small>'+esc(label)+'</small><b>'+esc(val)+'</b>'+(sub?'<em class="'+(sc||'')+'">'+esc(sub)+'</em>':'')+'</div>'}

function render(first){
  var d=st.d,s=st.s,x=st.x,dc=d.decision||{};
  var v=String(dc.verdict||'unknown').toLowerCase(),c=vc(v);
  var risk=Number(dc.risk_score),hasRisk=dc.risk_score!=null&&isFinite(risk);
  var rc=!hasRisk?'mut':(risk<35?'ok':(risk<65?'warn':'bad'));
  var C=2*Math.PI*34,off=hasRisk?C*(1-Math.min(100,Math.max(0,risk))/100):C;
  var label={ok:'Looks OK',caution:'Use caution',avoid:'High risk'}[v]||v;
  var all=[].concat(dc.positives||[],dc.cautions||[],dc.blockers||[]).join(' | ');
  var src=[s,d];
  function pick(re,pred){for(var i=0;i<src.length;i++){var r=find(src[i],re,pred);if(r!==undefined)return r}}

  var liq=pick(/^(liquidity(_usd)?|liq_usd)$/i,isNum);
  if(liq===undefined){var m1=/Liquidity \$([\d,]+)/.exec(d.summary||'');if(m1)liq=Number(m1[1].replace(/,/g,''))}
  var price=pick(/^(price(_usd)?|priceusd)$/i,isNumLike);
  var age=pick(/^(pair_age_days|age_days|pair_age_d|pair_age)$/i,isNum);
  var ageMin=pick(/^pair_age_minutes$/i,isNum);
  if(age===undefined&&ageMin!==undefined)age=ageMin/1440;
  var pc=s&&s.price_change_pct&&typeof s.price_change_pct==='object'?s.price_change_pct['24h']:undefined;
  var mcap=pick(/^market_cap_usd$/i,isNumLike),vol1=pick(/^volume_1h$/i,isNumLike);
  var buys=s?s.buys_5m:undefined,sells=s?s.sells_5m:undefined;
  var hq=pick(/^holder_quality(_score)?$/i,function(q){return isNum(q)||(q&&isNum(q.score))});
  if(hq&&typeof hq==='object')hq=hq.score;
  var t10=/Top 10 holders own (?:only )?(\d+(?:\.\d+)?)%/i.exec(all);
  var lp=/(\d+(?:\.\d+)?)% of liquidity locked/i.exec(all);

  var tiles='';
  if(liq!==undefined)tiles+=tile('Liquidity',fmtUsd(liq),liq>=100000?'ok':(liq>=20000?'warn':'bad'));
  if(price!==undefined)tiles+=tile('Price',fmtPrice(price),'',isNum(pc)?'24h '+(pc>=0?'+':'')+pc+'%':'',isNum(pc)?(pc>=0?'ok':'bad'):'');
  if(age!==undefined)tiles+=tile('Pair age',fmtAge(age),age<1?'bad':(age<7?'warn':'ok'));
  if(hq!==undefined)tiles+=tile('Holder quality',Math.round(hq)+' / 100',hq>=60?'ok':(hq>=40?'warn':'bad'));
  if(t10)tiles+=tile('Top 10 holders',t10[1]+'%',Number(t10[1])<25?'ok':(Number(t10[1])<50?'warn':'bad'));
  if(lp)tiles+=tile('LP locked or burned',lp[1]+'%',Number(lp[1])>=80?'ok':(Number(lp[1])>=50?'warn':'bad'));
  if(mcap!==undefined)tiles+=tile('Market cap',compact(mcap));
  if(vol1!==undefined)tiles+=tile('Volume 1h',compact(vol1));
  if(isNum(buys)&&isNum(sells))tiles+=tile('Buys / sells 5m',buys+' / '+sells,sells>buys*2?'warn':(buys>sells*2?'ok':''));
  var ow=/One wallet holds (\d+(?:\.\d+)?)%\+? of supply/i.exec(all);
  if(ow)tiles+=tile('Largest wallet',ow[1]+'%+',Number(ow[1])>=30?'bad':'warn');
  if(age===undefined){
    var ao=/Pair older than (\d+) days/i.exec(all),ay=/Pair (?:younger|newer) than (\d+) (days|hours)/i.exec(all);
    if(ao)tiles+=tile('Pair age',ao[1]+'+ d','ok');
    else if(ay)tiles+=tile('Pair age','< '+ay[1]+(ay[2]==='hours'?' h':' d'),'bad');
  }

  var flags=s?find(s,/^flags$/i,Array.isArray):undefined;
  var flagHtml='';
  if(flags&&flags.length)flagHtml='<div class="r-h">Flags</div><div class="r-chips" style="margin-top:0">'+flags.map(function(f){var t=typeof f==='string'?f:(f.label||f.id||f.name||'');return chip(nice(t),flagCls(t))}).join('')+'</div>';

  var sellHtml='';
  if(x){
    var sizes=findSizes(x);
    var grade=find(x,/^(exit_)?grade$/i,function(q){return typeof q==='string'});
    var overall=find(x,/^(overall|overall_verdict|verdict)$/i,function(q){return typeof q==='string'});
    if(sizes&&sizes.length||grade){
      sellHtml='<div class="r-h">Cost to sell <small>Jupiter quote</small></div>';
      var gc=/good|ok|low/i.test(grade||'')?'ok':(/fair|medium|mid|warn|caution/i.test(grade||'')?'warn':(grade?'bad':''));
      var oc=overall?vc(overall):'';
      sellHtml+='<div class="r-chips" style="margin-top:0">'+(grade?chip('Exit grade: '+grade,gc):'')+(overall?chip('Overall: '+overall,oc==='mut'?'':oc):'')+'</div>';
      if(sizes&&sizes.length){
        sellHtml+='<div class="r-sell">'+sizes.slice(0,6).map(function(z){
          var l=lossPct(z.loss,z.lk),lc=l<3?'ok':(l<8?'warn':'bad');
          return '<span>Sell '+fmtUsd(z.size)+'</span><div class="r-bar"><i class="'+lc+'" style="width:'+Math.min(100,Math.max(3,l*4))+'%"></i></div><b class="'+lc+'">'+(Math.round(l*10)/10)+'% lost</b>';
        }).join('')+'</div>';
      }
      sellHtml+='<p class="r-note">A quote does not prove a real sell will succeed.</p>';
    }
  }

  var h='<div class="res">';
  h+='<div class="r-hero '+c+'"><div class="r-ring '+rc+'"><svg viewBox="0 0 88 88" width="88" height="88"><circle class="bg" cx="44" cy="44" r="34"/><circle class="fg" id="fg" cx="44" cy="44" r="34" stroke-dasharray="'+C.toFixed(1)+'" stroke-dashoffset="'+(first?C.toFixed(1):off.toFixed(1))+'" data-off="'+off.toFixed(1)+'"/></svg><div class="n">'+(hasRisk?risk:'?')+'<small>risk / 100</small></div></div>';
  h+='<div class="r-vtxt"><div class="r-big"><i class="r-dot"></i>'+esc(label)+'<span class="r-tok">'+esc(d.token||'')+'</span></div><p>'+hl(esc(tidy(d.summary||'')))+'</p></div></div>';
  h+='<div class="r-mint">'+esc(d.mint||st.mint)+'</div>';
  h+='<div class="r-links"><button type="button" class="btn btn-o" id="ca">Copy address</button><a class="btn btn-o" href="https://dexscreener.com/solana/'+encodeURIComponent(d.mint||st.mint)+'" target="_blank" rel="noopener noreferrer">DexScreener</a><a class="btn btn-o" href="https://solscan.io/token/'+encodeURIComponent(d.mint||st.mint)+'" target="_blank" rel="noopener noreferrer">Solscan</a></div>';

  var chips='';
  if(d.regime&&d.regime.name)chips+=chip('Regime: '+d.regime.name+' ('+pct(d.regime.confidence)+'%)',/risk_off/.test(d.regime.name)?'warn':(/risk_on/.test(d.regime.name)?'ok':''));
  if(d.attention_trap)chips+=chip('Attention trap','warn');
  var t=d.time_to_death;
  if(t&&t.band)chips+=chip('Stress clock: '+t.band+(t.eta_hours?' (~'+t.eta_hours+'h)':''),{slow:'ok',medium:'warn',fast:'bad'}[String(t.band).toLowerCase()]||'');
  var cf=d.counterfactual;
  if(cf&&cf.available&&cf.expected_bad_rate!=null){var r=cf.expected_bad_rate;chips+=chip('Similar cases bad: '+pct(r)+'% (n='+cf.cohort_n+')',r<.25?'ok':(r<.5?'warn':'bad'))}
  var at=d.community&&d.community.attention;
  if(at&&at['24h']!=null)chips+=chip('Attention 24h: '+at['24h'],'');
  var dcf=s&&s.decision_confidence&&s.decision_confidence.level;
  if(dcf)chips+=chip('Data confidence: '+dcf,{high:'ok',medium:'warn',low:'warn'}[String(dcf).toLowerCase()]||'');
  if(chips)h+='<div class="r-chips">'+chips+'</div>';
  if(s&&s.source_note)h+='<p class="r-note">\u24D8 '+esc(s.source_note)+'</p>';
  var at2=d.attestation;
  if(at2&&at2.sig)h+='<p class="r-note"><span class="num">\u2714 Signed #'+esc(at2.chain_n)+'</span> hash '+esc(String(at2.hash).slice(0,12))+'\u2026 \u00B7 <a href="/attest" target="_blank" rel="noopener">verify</a></p>';

  if(tiles)h+='<div class="r-tiles">'+tiles+'</div>';
  if(st.pending>0)h+='<p class="r-note">Loading market data and sell cost...</p>';
  var tr=s&&s.track_record_context;
  if(tr&&isNum(tr.bad_outcome_rate)){
    var br=tr.bad_outcome_rate*100,bc=br<25?'ok':(br<50?'warn':'bad');
    h+='<div class="r-h">Track record <small>similar past verdicts</small></div><div class="r-box"><div class="r-sell"><span>Ended badly'+(tr.horizon_hours?' ('+tr.horizon_hours+'h)':'')+'</span><div class="r-bar"><i class="'+bc+'" style="width:'+Math.min(100,Math.max(3,br))+'%"></i></div><b class="'+bc+'">'+(Math.round(br*10)/10)+'%</b></div><p class="r-note">'+(tr.n?'Based on '+tr.n+' judged tokens'+(tr.basis?' ('+esc(String(tr.basis).replace(/^judged tokens with /i,''))+')':'')+'. ':'')+(tr.ci95&&tr.ci95.length===2?'95% range '+tr.ci95[0]+' to '+tr.ci95[1]+'%. ':'')+esc(tr.meaning||'')+'</p></div>';
  }

  var unk=(dc.unknowns||[]).filter(function(u){return !(sellHtml&&/Exit cost not checked/i.test(String(u)))});
  h+='<div class="r-h">Signals</div><div class="r-grid">';
  h+=group('Blockers','\u2716','bad',dc.blockers);
  h+=group('Cautions','\u26A0','warn',dc.cautions);
  h+=group('Positives','\u2714','ok',dc.positives);
  h+=group('Unknowns','?','mut',unk);
  h+=group('Pre-rug patterns','\u26A0','warn',d.pre_rug);
  h+=group('What would change this','\u21BB','mut',d.would_change_my_mind);
  h+='</div>';
  h+=flagHtml+sellHtml;
  if(d.debate)h+='<div class="r-h">Agent debate</div><div class="r-grid">'+debate(d.debate)+'</div>';

  var steps=[];
  if((dc.blockers||[]).length)steps.push('Blockers were found. Understand each one before sizing any trade.');
  var sn=(s&&Array.isArray(s.suggested_next))?s.suggested_next:(Array.isArray(dc.next_checks)?dc.next_checks:[]);
  sn.forEach(function(z){if(typeof z==='string'&&!(sellHtml&&/exit check/i.test(z)))steps.push(z.charAt(0).toUpperCase()+z.slice(1).replace(/\.$/,'')+'.')});
  if(!sellHtml&&st.pending<=0&&!sn.length)steps.push('Run the exit check (GET /exit or MCP check_exit) before sizing a trade.');
  steps.push('Verify on-chain (DexScreener, Solscan) before acting.');
  h+='<div class="r-h">Next steps</div><ul class="r-next">'+steps.map(function(z){return '<li>'+esc(z)+'</li>'}).join('')+'</ul>';

  var raw=JSON.stringify({omni:st.d,signal:st.s,exit:st.x},null,2);
  var wasOpen=$('details.r-raw')&&$('details.r-raw').open;
  h+='<div class="r-tools"><button type="button" class="btn btn-o" id="cj">Copy JSON</button><button type="button" class="btn btn-o" id="cl">Copy link</button><a class="btn btn-o" href="/omni?mint='+encodeURIComponent(d.mint||st.mint)+'" target="_blank" rel="noopener">Open JSON</a></div>';
  h+='<details class="r-raw"'+(wasOpen?' open':'')+'><summary>Raw JSON</summary><pre>'+esc(raw)+'</pre></details>';
  h+='<p class="r-note">v'+esc(d.version||'')+' \u00B7 Heuristics only, not financial advice. Data can be late or wrong.</p></div>';
  out.innerHTML=h;
  if(first)requestAnimationFrame(function(){requestAnimationFrame(function(){var f=$('#fg');if(f)f.style.strokeDashoffset=f.getAttribute('data-off')})});
  $('#cj').onclick=function(){copy(raw,this)};
  $('#cl').onclick=function(){copy(location.origin+location.pathname+'?mint='+encodeURIComponent(st.mint),this)};
  $('#ca').onclick=function(){copy(d.mint||st.mint,this)};
}
function showErr(m){out.innerHTML='<div class="r-err">'+esc(m)+'</div>'}
function extra(url,key,my){
  fetch(url,{headers:{'Accept':'application/json'}}).then(function(r){return r.ok?r.json():null}).catch(function(){return null}).then(function(j){
    if(my!==token||!st)return;st[key]=j;st.pending--;render(false);
  });
}
async function run(m){
  m=(m||'').trim();
  if(!B58.test(m)){showErr('That does not look like a Solana mint address. Paste the full CA (32-44 characters).');return}
  var my=++token;st=null;
  btn.disabled=true;btn.textContent='Checking...';
  out.innerHTML='<div class="r-load"><div class="r-spin"></div><span>Checking '+esc(m.slice(0,4))+'...'+esc(m.slice(-4))+' - the first request can take up to 30s if the server is waking up.</span></div>';
  var ctl=new AbortController(),to=setTimeout(function(){ctl.abort()},60000);
  try{
    var r=await fetch('/omni?mint='+encodeURIComponent(m),{signal:ctl.signal,headers:{'Accept':'application/json'}});
    var txt=await r.text();var d=null;try{d=JSON.parse(txt)}catch(e){}
    if(my!==token)return;
    if(r.status===429){showErr('Too many requests. Wait a few seconds and press Check again.')}
    else if(!r.ok||!d){var det=d&&(d.detail||d.error);showErr('Request failed ('+r.status+'). '+(det?(typeof det==='string'?det:JSON.stringify(det)):'Try again in a moment.'))}
    else{
      st={d:d,s:null,x:null,mint:m,pending:2};render(true);
      try{history.replaceState(null,'','?mint='+encodeURIComponent(m))}catch(e){}
      extra('/signal?mint='+encodeURIComponent(m),'s',my);
      extra('/exit?mint='+encodeURIComponent(m),'x',my);
    }
  }catch(e){showErr(e&&e.name==='AbortError'?'Timed out after 60s. Press Check again.':'Network error. Check your connection and try again.')}
  finally{clearTimeout(to);btn.disabled=false;btn.textContent='Check'}
}
$('#f').addEventListener('submit',function(e){e.preventDefault();run(inp.value)});
inp.addEventListener('paste',function(){setTimeout(function(){var v=inp.value.trim();inp.value=v;if(B58.test(v))run(v)},0)});
$('#paste').addEventListener('click',function(){
  if(navigator.clipboard&&navigator.clipboard.readText){navigator.clipboard.readText().then(function(t){inp.value=(t||'').trim();run(inp.value)}).catch(function(){inp.focus()})}else inp.focus();
});
$('#check').addEventListener('click',function(e){var b=e.target.closest('.r-try');if(b){inp.value=b.getAttribute('data-mint');run(inp.value)}});
var q=new URLSearchParams(location.search).get('mint');
if(q){inp.value=q;run(q)}
})();
'''

PROOF_CSS = r"""
#proof h2 small{font-family:var(--sans);font-size:.8rem;color:var(--muted);font-weight:500;margin-left:.5rem}
.pf-tabs{display:flex;gap:.4rem;margin-bottom:.8rem}
.pf-tabs button{cursor:pointer;border:1px solid var(--line);background:rgba(10,18,32,.8);color:var(--muted);border-radius:999px;padding:.3rem .85rem;font-size:.82rem;font-family:var(--sans)}
.pf-tabs button.on{border-color:var(--a);color:var(--a)}
.pf-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:.6rem}
.pf-card{background:var(--card);border:1px solid var(--line);border-radius:.9rem;padding:.8rem 1rem}
.pf-card small{display:block;color:var(--muted);font-size:.8rem}
.pf-card b{display:block;font-family:var(--disp);font-size:1.9rem;letter-spacing:-.02em;line-height:1.15}
.pf-card.hl{border-color:rgba(20,241,149,.45);background:linear-gradient(135deg,rgba(20,241,149,.1),var(--card))}
.pf-lead{margin:.9rem 0 .4rem;color:#cfdaec;font-size:.97rem;line-height:1.6}
.pf-box{background:var(--card);border:1px solid var(--line);border-radius:.9rem;padding:.8rem 1rem;margin-top:.7rem}
.pf-box h3{font-family:var(--disp);font-size:1rem;margin:0 0 .5rem}
.pf-box h3 small{font-family:var(--sans);color:var(--muted);font-weight:500;font-size:.78rem;margin-left:.4rem}
.pf-row{display:grid;grid-template-columns:92px 1fr 58px;gap:.15rem .6rem;align-items:center;margin:.5rem 0;font-size:.9rem}
.pf-row small{grid-column:2/4;color:var(--muted);font-size:.75rem}
.pf-row b{font-family:var(--mono);text-align:right;font-size:.88rem}
.pf-bar{position:relative;height:10px;border-radius:99px;background:#0a1220}
.pf-bar i{display:block;height:100%;border-radius:99px}
.pf-bar i.ok{background:#14f195}.pf-bar i.warn{background:#f5b73b}.pf-bar i.bad{background:#f2564f}.pf-bar i.acc{background:linear-gradient(90deg,#9945ff,#14f195)}
.pf-bar u{position:absolute;top:-3px;bottom:-3px;width:2px;background:#fff;opacity:.55}
.pf-rules{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:.6rem;margin-top:.7rem}
.pf-rule{background:var(--card);border:1px solid var(--line);border-radius:.9rem;padding:.8rem 1rem}
.pf-rule.hi{border-color:rgba(153,69,255,.65)}
.pf-rule h4{margin:0;font-family:var(--disp);font-size:1rem}
.pf-rule p{margin:.15rem 0 .4rem;color:var(--muted);font-size:.78rem}
.pf-m{display:grid;grid-template-columns:1fr 52px;gap:.2rem .5rem;margin:.55rem 0;font-size:.82rem;align-items:center}
.pf-m span{grid-column:1/3;color:#c4d0e4}
.pf-m b{font-family:var(--mono);text-align:right;font-size:.85rem}
.pf-m small{grid-column:1/3;color:var(--muted);font-size:.72rem}
#proof details{margin-top:.7rem;color:var(--muted);font-size:.84rem}
#proof details summary{cursor:pointer}
#proof details li{margin:.3rem 0}
"""

PROOF_JS = r'''
(function(){
var sec=document.getElementById('proof');if(!sec)return;
var body=document.getElementById('pf-body'),tabs=document.getElementById('pf-tabs');
var DATA=null,cur='all_tracked';
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function num(x){return typeof x==='number'&&isFinite(x)}
function r1(x){return Math.round(x*10)/10}
function load(u){return fetch(u,{headers:{'Accept':'application/json'}}).then(function(r){return r.ok?r.json():null}).catch(function(){return null})}
function cls(v){return v<40?'ok':(v<70?'warn':'bad')}
function bar(v,c,base){return '<div class="pf-bar"><i class="'+c+'" style="width:'+Math.max(2,Math.min(100,v))+'%"></i>'+(num(base)?'<u style="left:'+Math.min(99,base)+'%" title="base rate"></u>':'')+'</div>'}
function ci(a){return (a&&a.length===2)?'95% range '+a[0]+' to '+a[1]+'%':''}
function metric(label,v,c,sub){if(!num(v))return '';return '<div class="pf-m"><span>'+esc(label)+'</span>'+bar(v,c)+'<b>'+r1(v)+'%</b>'+(sub?'<small>'+esc(sub)+'</small>':'')+'</div>'}
function rule(title,note,o,hi){
  if(!o||!num(o.precision_pct))return '';
  return '<div class="pf-rule'+(hi?' hi':'')+'"><h4>'+esc(title)+'</h4><p>'+esc(note)+' \u00B7 flagged '+esc(o.flagged)+' tokens</p>'
   +metric('Right when it flags',o.precision_pct,'acc',ci(o.precision_ci95_pct))
   +metric('Bad outcomes it catches',o.recall_pct,'acc')
   +metric('Good tokens wrongly flagged',o.false_positive_rate_pct,'warn')+'</div>';
}
function draw(){
  var P=DATA.performance||{},p=P[cur];if(!p){body.innerHTML='';return}
  var base=p.judged?p.bad_outcomes/p.judged*100:null,oa=p.ours_avoid||{},ba=p.baseline_avoid||{},oc=p.ours_avoid_or_caution||{};
  var h='';
  if(num(oa.precision_pct)&&num(base)){
    h+='<div class="pf-cards"><div class="pf-card hl"><small>Avoid is right</small><b>'+r1(oa.precision_pct)+'%</b><small>'+esc(ci(oa.precision_ci95_pct))+'</small></div>'
     +'<div class="pf-card"><small>Base rate, all tracked tokens</small><b>'+r1(base)+'%</b><small>ended badly within '+esc(DATA.horizon_hours||24)+'h</small></div>'
     +'<div class="pf-card"><small>Avoid beats the base rate by</small><b>+'+r1(oa.precision_pct-base)+' pts</b><small>'+esc(p.judged)+' verdicts judged</small></div></div>';
    h+='<p class="pf-lead">Most tokens in this sample fail, so a good verdict must beat <b>'+r1(base)+'%</b>. Avoid reaches <b>'+r1(oa.precision_pct)+'%</b> but catches only <b>'+r1(oa.recall_pct)+'%</b> of bad outcomes.'
     +(num(ba.precision_pct)?' A simple baseline rule catches '+r1(ba.recall_pct)+'% but is right '+r1(ba.precision_pct)+'% of the time and wrongly flags '+r1(ba.false_positive_rate_pct)+'% of good tokens.':'')+'</p>';
  }
  var V=p.verdicts||{},vr='';
  [['ok','OK','ok'],['caution','Caution','warn'],['avoid','Avoid','bad']].forEach(function(x){
    var v=V[x[0]];if(v&&num(v.bad_outcome_rate_pct))vr+='<div class="pf-row"><span>'+x[1]+'</span>'+bar(v.bad_outcome_rate_pct,x[2],base)+'<b>'+r1(v.bad_outcome_rate_pct)+'%</b><small>n='+esc(v.n)+(v.ci95_pct?' \u00B7 '+esc(ci(v.ci95_pct)):'')+'</small></div>';
  });
  if(vr)h+='<div class="pf-box"><h3>Bad outcome rate by verdict <small>white line = base rate</small></h3>'+vr+'</div>';
  var rr=rule('Our avoid','Verdict "avoid"',oa,true)+rule('Baseline rule','Simple liquidity and age rule',ba,false)+rule('Our avoid + caution','Anything not OK',oc,false);
  if(rr)h+='<div class="pf-rules">'+rr+'</div>';
  var B=DATA.by_risk_bucket||[],br='';
  B.forEach(function(b){if(num(b.bad_outcome_rate_pct))br+='<div class="pf-row"><span>Risk '+esc(b.risk_score_range)+'</span>'+bar(b.bad_outcome_rate_pct,cls(b.bad_outcome_rate_pct),base)+'<b>'+r1(b.bad_outcome_rate_pct)+'%</b><small>n='+esc(b.n)+'</small></div>'});
  if(br)h+='<div class="pf-box"><h3>Does a higher risk score mean more failures? <small>all tracked</small></h3>'+br+'</div>';
  var cv=(DATA.caveats||[]).slice(0,2).map(function(c){return '<li>'+esc(c)+'</li>'}).join('');
  h+='<details><summary>How to read this</summary><ul>'+(DATA.bad_outcome_definition?'<li>Bad outcome: '+esc(DATA.bad_outcome_definition)+'.</li>':'')+cv+'<li>'+esc(DATA.resolved||0)+' verdicts judged, '+esc(DATA.pending||0)+' still waiting for their 24h result.</li></ul></details>';
  body.innerHTML=h;
}
function tabsDraw(){
  var P=DATA.performance||{},t='';
  [['all_tracked','All time'],['last_7d','Last 7 days']].forEach(function(x){if(P[x[0]])t+='<button type="button" data-k="'+x[0]+'" class="'+(cur===x[0]?'on':'')+'">'+x[1]+(P[x[0]].days_covered?' ('+P[x[0]].days_covered+'d)':'')+'</button>'});
  tabs.innerHTML=t;
}
tabs.addEventListener('click',function(e){var b=e.target.closest('button');if(!b||!DATA)return;cur=b.getAttribute('data-k');tabsDraw();draw()});
load('/stats').then(function(j){return (j&&j.performance)?j:load('/accuracy')}).then(function(j){
  if(!j||!j.performance){sec.style.display='none';return}
  DATA=j;tabsDraw();draw();
});
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&amp;family=JetBrains+Mono:wght@500;700&amp;family=Space+Grotesk:wght@600;700&amp;display=swap">
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
{PROOF_CSS}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<symbol id="i-x" viewBox="0 0 24 24"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></symbol>
<symbol id="i-gh" viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></symbol>
</svg>
<div class="bg" aria-hidden="true"><span></span><span></span><span></span></div>
<div class="wrap">
  <nav>
    <div class="logo">TVibe<em> Signal</em></div>
    <div class="navlinks">
      <a href="/agents">Agents</a>
      <a href="/stats">Stats</a>
      <a href="/docs">API</a>
      <a href="#donate">Donate</a>
      <a class="pill" href="{GITHUB_URL}" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-gh"/></svg>GitHub</a>
      <a class="pill" href="{X_URL}" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-x"/></svg>X</a>
    </div>
  </nav>

  <header class="hero">
    <div class="badge">Free · Open source · Measured in public</div>
    <h1>Solana token signals<br>for <span>AI agents</span></h1>
    <p class="sub">
      One request → verdict, reasons, and context.
      Track record is public on <a href="/stats">/stats</a>.
      Heuristics only — not financial advice.
    </p>
    <div class="cta">
      <a class="btn btn-g" href="/stats">Live accuracy</a>
      <a class="btn btn-o" href="/mcp">MCP</a>
      <a class="btn btn-o" href="/agents">For agents</a>
    </div>
  </header>

  <div class="check" id="check">
    <h3>Check a token</h3>
    <p class="muted" style="font-size:.88rem">Paste a Solana mint address (CA)</p>
    <form id="f" action="/omni" method="get">
      <input id="mint" name="mint" type="text" required spellcheck="false" autocomplete="off"
        autocapitalize="off" autocorrect="off"
        placeholder="So1111… or any token mint" aria-label="Token mint address" />
      <button id="paste" type="button" class="btn btn-o">Paste</button>
      <button id="go" type="submit" class="btn btn-p">Check</button>
    </form>
    <div class="tryrow">Try
      <button type="button" class="r-try" data-mint="So11111111111111111111111111111111111111112">SOL</button>
      <button type="button" class="r-try" data-mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v">USDC</button>
      <button type="button" class="r-try" data-mint="33jENUQnjoitkMFpvNJcSHyLAHFWJuHwT6E3E8CNpump">Dope</button>
      <button type="button" class="r-try" data-mint="CbcyNo7m1amFWqEQm2m4PLv1UNvpcL3C1Ujm6AkzpKoU">e/acc</button>
    </div>
    <div id="out" aria-live="polite"></div>
  </div>

  <div class="strip">
    <div><b>Free</b><span>no key needed</span></div>
    <div><b>Open source</b><span>self-host anytime</span></div>
    <div><b>Public record</b><span>accuracy on /stats</span></div>
    <div><b>MCP ready</b><span>Claude, Cursor, agents</span></div>
  </div>

  <section id="proof">
    <h2>Live accuracy <small>measured on real verdicts, not a backtest</small></h2>
    <div class="pf-tabs" id="pf-tabs"></div>
    <div id="pf-body"><p class="muted">Loading live accuracy...</p></div>
    <p class="muted" style="margin-top:.7rem;font-size:.85rem"><a href="/stats" style="color:var(--a)">Full numbers</a> · <a href="/attest" style="color:var(--a)">Verify signed verdicts</a></p>
  </section>

  <div class="grid">
    <div class="card">
      <h3>Primary call</h3>
      <p><code>GET /omni?mint=…</code></p>
      <p>Verdict + decision block agents should trust first.</p>
    </div>
    <div class="card">
      <h3>Prove it</h3>
      <p><code>GET /stats</code></p>
      <p>Precision / recall on judged outcomes — not marketing claims.</p>
    </div>
    <div class="card">
      <h3>MCP</h3>
      <p><code>omni(mint)</code></p>
      <p>Wire into Cursor, Claude, or your agent runtime.</p>
    </div>
    <div class="card">
      <h3>Self-host</h3>
      <p><code>github.com/TVibex402/signal-api</code></p>
      <p>Same code. Your Redis starts its own track record.</p>
    </div>
  </div>

  <section>
    <h2>Quick start</h2>
    <pre>curl -s "{BASE}/omni?mint=So11111111111111111111111111111111111111112" | jq .decision</pre>
    <p class="muted" style="margin-top:.75rem">
      Batch: <code>/signals?mints=a,b,c&amp;view=compact</code> (max 10). Cache the same mint 15–30s.
    </p>
  </section>

  <section>
    <h2>Fair use</h2>
    <div class="card">
      <p class="muted">
        Public host is <strong style="color:var(--text)">free</strong>.
        ~30 req/min without a key · batch max 10 · please cache.
        Heavy traffic → self-host or slow down on HTTP 429.
        <a href="/support" style="color:var(--a)">/support</a>
      </p>
    </div>
  </section>

  <section id="donate">
    <h2>Optional tip (never required)</h2>
    <div class="donate-box">
      <p class="muted">{DONATE_NOTE}</p>
      <p class="sol">{DONATE_SOL}</p>
      <div class="copy-row">
        <button type="button" class="copy-btn"
          onclick="navigator.clipboard.writeText('{DONATE_SOL}').then(()=>{{this.textContent='Copied'}}).catch(()=>{{}})">
          Copy address
        </button>
        <a class="btn btn-o" style="padding:.4rem .85rem;font-size:.85rem" href="/donate">/donate JSON</a>
      </div>
    </div>
  </section>

  <footer>
    <p>Not financial advice. Heuristics for agents and research.</p>
    <p style="margin-top:.4rem">
      <a href="/support">/support</a> ·
      <a href="/agents">/agents</a> ·
      <a href="/llms.txt">llms.txt</a> ·
      <a href="/attest">/attest</a> ·
      <a href="{GITHUB_URL}" target="_blank" rel="noopener noreferrer">source</a> ·
      <a class="fx" href="{X_URL}" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-x"/></svg>@realTVibe</a>
    </p>
  </footer>
</div>
<script>{CHECK_JS}</script>
<script>{PROOF_JS}</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home_v287():
    return HOME_HTML


@app.get("/donate", tags=["product"])
async def donate_json():
    return {
        "brand": BRAND,
        "free": True,
        "required": False,
        "asset": "SOL",
        "address": DONATE_SOL,
        "note": DONATE_NOTE,
        "fair_use": "/support",
        "self_host": GITHUB_URL,
        "x": X_URL,
        "disclaimer": "Not financial advice. Donations are voluntary tips for hosting/RPC only.",
        "version": VERSION,
    }


@app.get("/support", response_class=PlainTextResponse, tags=["product"])
async def support_fair_use():
    return FAIR_USE.strip() + "\n"


print(f"[part104] v{VERSION} {BRAND} home + market data from /signal + track record + typography + market tiles + sell cost + X link -> GET /")

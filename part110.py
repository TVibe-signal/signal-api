# part110.py - Home page v2: inline result (no raw JSON), colored verdicts, X link next to GitHub
# Loader entry (before part7):  ("part110.py", 0, "SKIP"),
from fastapi.responses import HTMLResponse

HOME_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="theme-color" content="#070b12">
<title>TVibe Signal — Solana signals for AI agents</title>
<meta name="description" content="Free Solana token signals for AI agents. Paste a mint, get verdict and reasons. Measured on /stats. Not financial advice.">
<meta property="og:title" content="TVibe Signal — Solana signals for AI agents">
<meta property="og:description" content="Free, open source. One call for verdict + reasons. Accuracy public on /stats.">
<meta property="og:image" content="https://signal-api-24q4.onrender.com/og.svg">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='14' fill='%23fff'/%3E%3Cpath d='M16 18h32v8H36v22h-8V26H16z' fill='%23000'/%3E%3C/svg%3E">
<style>
:root{--bg:#070b12;--card:#0d1420;--card2:#111b2b;--line:#1b2840;--txt:#e7eefb;--mut:#8b9ab1;--ok:#2fd27a;--warn:#f5b73b;--bad:#f2564f;--acc:#7da2ff}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;background:radial-gradient(900px 420px at 50% -120px,#13233f 0%,transparent 70%),var(--bg);color:var(--txt);font:16px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
a{color:var(--acc);text-decoration:none}
a:hover{text-decoration:underline}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.wrap{max-width:880px;margin:0 auto;padding:0 18px}
.ic{width:16px;height:16px;fill:currentColor;flex:none}
:focus-visible{outline:2px solid var(--acc);outline-offset:2px}

/* donate bar */
.bar{display:flex;gap:10px;align-items:center;justify-content:center;flex-wrap:wrap;padding:8px 14px;background:#0a1220;border-bottom:1px solid var(--line);font-size:13px;color:var(--mut)}
.bar b{color:var(--txt);font-weight:600}
.bar button.x{background:none;border:0;color:var(--mut);font-size:18px;cursor:pointer;padding:0 4px}

/* header */
header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:18px 0}
.brand{display:flex;align-items:center;gap:10px;font-weight:700;font-size:18px;color:var(--txt)}
.brand i{width:30px;height:30px;border-radius:9px;background:#fff;display:grid;place-items:center;box-shadow:0 0 0 2px #2a3a55}
.brand i svg{width:18px;height:18px}
.brand em{font-style:normal;color:var(--acc)}
nav{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
nav a{color:var(--mut);padding:6px 10px;border-radius:8px;font-size:14px}
nav a:hover{color:var(--txt);background:var(--card);text-decoration:none}
nav a.pill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:var(--card);color:var(--txt)}
nav a.pill:hover{border-color:var(--acc)}

/* hero */
.hero{padding:34px 0 8px}
.hero h1{font-size:clamp(30px,6vw,46px);line-height:1.08;margin:0 0 12px;letter-spacing:-.02em}
.hero p{margin:0;color:var(--mut);max-width:560px}
.hero .links{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}
.btn{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);background:var(--card);color:var(--txt);padding:8px 13px;border-radius:10px;font-size:14px;cursor:pointer}
.btn:hover{border-color:var(--acc);text-decoration:none}

/* checker */
.check{margin-top:26px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:18px}
.check h2{margin:0 0 12px;font-size:18px}
.row{display:flex;gap:8px}
.row input{flex:1;min-width:0;background:#08101c;border:1px solid var(--line);color:var(--txt);border-radius:10px;padding:12px 13px;font:14px ui-monospace,Menlo,Consolas,monospace}
.row input:focus{border-color:var(--acc);outline:none}
.row button{background:var(--acc);color:#06101f;border:0;border-radius:10px;padding:0 20px;font-weight:700;font-size:15px;cursor:pointer;min-width:88px}
.row button:disabled{opacity:.6;cursor:wait}
.hint{margin:9px 0 0;font-size:13px;color:var(--mut)}
.hint button{background:none;border:0;color:var(--acc);cursor:pointer;padding:0;font:inherit}
#out{margin-top:16px}
.loading{display:flex;align-items:center;gap:10px;color:var(--mut);font-size:14px;padding:14px 4px}
.spin{width:18px;height:18px;border:2px solid var(--line);border-top-color:var(--acc);border-radius:50%;animation:sp .8s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.err{border:1px solid #5a2326;background:#1d0f12;color:#ffb4b0;border-radius:12px;padding:12px 14px;font-size:14px}

/* result */
.res{animation:in .35s ease both}
@keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.vhero{display:flex;gap:16px;align-items:center;border-radius:14px;padding:16px;border:1px solid var(--line);background:var(--card2)}
.vhero.ok{border-color:#1d5a3a;background:linear-gradient(135deg,#0d2a1e,#0f1a26)}
.vhero.warn{border-color:#6b5018;background:linear-gradient(135deg,#2b210c,#0f1a26)}
.vhero.bad{border-color:#6e2523;background:linear-gradient(135deg,#2e1112,#0f1a26)}
.ring{position:relative;width:84px;height:84px;flex:none}
.ring svg{width:84px;height:84px;transform:rotate(-90deg)}
.ring circle{fill:none;stroke-width:8;stroke-linecap:round}
.ring .bg{stroke:#ffffff14}
.ring .fg{transition:stroke-dashoffset .9s cubic-bezier(.2,.8,.2,1)}
.ring.ok .fg{stroke:var(--ok)}.ring.warn .fg{stroke:var(--warn)}.ring.bad .fg{stroke:var(--bad)}
.ring span{position:absolute;inset:0;display:grid;place-items:center;font-weight:800;font-size:22px}
.ring span small{display:block;font-size:10px;color:var(--mut);font-weight:500;margin-top:-4px}
.vtxt{min-width:0}
.vtxt .big{font-size:26px;font-weight:800;letter-spacing:-.01em;display:flex;align-items:center;gap:9px;flex-wrap:wrap}
.vtxt .tok{font-size:14px;color:var(--mut);font-weight:500}
.vtxt p{margin:4px 0 0;color:#c7d3e6;font-size:14px}
.dot{width:12px;height:12px;border-radius:50%;display:inline-block}
.ok .dot,.dot.ok{background:var(--ok);box-shadow:0 0 12px var(--ok)}
.warn .dot,.dot.warn{background:var(--warn);box-shadow:0 0 12px var(--warn)}
.bad .dot,.dot.bad{background:var(--bad);box-shadow:0 0 12px var(--bad)}
.mintline{margin:10px 2px 0;font-size:12px;color:var(--mut);word-break:break-all}

.chips{display:flex;flex-wrap:wrap;gap:7px;margin:12px 0 4px}
.chip{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 10px;font-size:12.5px;border:1px solid var(--line);background:#0a1220;color:var(--mut)}
.chip.ok{color:var(--ok);border-color:#1d5a3a;background:#0b2016}
.chip.warn{color:var(--warn);border-color:#6b5018;background:#221a09}
.chip.bad{color:var(--bad);border-color:#6e2523;background:#240e0f}

.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
@media(max-width:640px){.grid{grid-template-columns:1fr}.vhero{flex-direction:column;align-items:flex-start}}
.grp,.box{background:var(--card2);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.grp h4,.box h3{margin:0 0 8px;font-size:14px;display:flex;align-items:center;gap:8px}
.grp h4 b{margin-left:auto;font-size:12px;color:var(--mut);font-weight:600}
.grp .sym{width:20px;height:20px;border-radius:6px;display:grid;place-items:center;font-size:12px;font-weight:800}
.grp ul{list-style:none;margin:0;padding:0}
.grp li{font-size:13.5px;padding:5px 0 5px 12px;border-left:2px solid var(--line);margin-bottom:4px;color:#d3ddee}
.grp.ok{border-color:#1d5a3a}.grp.ok .sym{background:#123a27;color:var(--ok)}.grp.ok li{border-left-color:var(--ok)}
.grp.warn{border-color:#6b5018}.grp.warn .sym{background:#3a2c0d;color:var(--warn)}.grp.warn li{border-left-color:var(--warn)}
.grp.bad{border-color:#6e2523}.grp.bad .sym{background:#431818;color:var(--bad)}.grp.bad li{border-left-color:var(--bad)}
.grp.mut .sym{background:#1a2538;color:var(--mut)}.grp.mut li{border-left-color:#33415c;color:var(--mut)}
.full{grid-column:1/-1}
.vbar{display:flex;height:10px;border-radius:99px;overflow:hidden;background:#0a1220;margin:4px 0 6px}
.vbar i{display:block;height:100%}
.vbar i.ok{background:var(--ok)}.vbar i.warn{background:var(--warn)}.vbar i.bad{background:var(--bad)}
.prow{display:flex;gap:10px;padding:8px 0;border-top:1px solid var(--line)}
.prow .chip{align-self:flex-start;min-width:74px;justify-content:center}
.prow p{margin:2px 0 0;font-size:13px;color:var(--mut)}
.prow small{color:var(--mut)}
.mut{color:var(--mut)}
.tools{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
details.raw{margin-top:10px;background:#08101c;border:1px solid var(--line);border-radius:10px;padding:8px 12px}
details.raw summary{cursor:pointer;color:var(--mut);font-size:13px}
details.raw pre{margin:8px 0 0;max-height:300px;overflow:auto;font-size:12px;color:#b8c6de}

/* sections */
section.s{margin-top:34px}
section.s h2{font-size:20px;margin:0 0 10px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.card h3{margin:0 0 6px;font-size:14px;color:var(--mut);font-weight:600}
.card code{display:block;color:var(--acc);font-size:13px;margin-bottom:6px;word-break:break-all}
.card p{margin:0;font-size:13.5px;color:#c3cfe2}
pre.code{background:#08101c;border:1px solid var(--line);border-radius:12px;padding:12px 14px;overflow:auto;font-size:13px;color:#c9d6ec}
.tip{display:flex;gap:8px;align-items:center;flex-wrap:wrap;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.tip code{font-size:13px;word-break:break-all;flex:1;min-width:200px}
footer{margin:44px 0 30px;padding-top:18px;border-top:1px solid var(--line);color:var(--mut);font-size:13px;display:flex;flex-wrap:wrap;gap:6px 14px;align-items:center}
footer a{display:inline-flex;align-items:center;gap:5px}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
<symbol id="i-x" viewBox="0 0 24 24"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></symbol>
<symbol id="i-gh" viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></symbol>
</svg>

<div class="bar" id="bar">
  <span>Free &amp; open source. Optional SOL tip: <b class="mono">3iAV…w18n</b></span>
  <button class="btn" data-copy="3iAVBvE4aU4A5DTKCqzu6jg79UfW6aEnqUD1pjfew18n" style="padding:3px 10px">Copy</button>
  <a href="/donate.html">Details</a>
  <button class="x" aria-label="Close" onclick="document.getElementById('bar').remove()">×</button>
</div>

<div class="wrap">
<header>
  <a class="brand" href="/" style="text-decoration:none"><i><svg viewBox="0 0 64 64"><path d="M12 12h40v12H38v30H26V24H12z" fill="#000"/></svg></i>TVibe <em>Signal</em></a>
  <nav>
    <a href="/agents">Agents</a>
    <a href="/stats">Stats</a>
    <a href="/docs">API</a>
    <a href="#donate">Donate</a>
    <a class="pill" href="https://github.com/TVibex402/signal-api" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-gh"/></svg>GitHub</a>
    <a class="pill" href="https://x.com/realTVibe" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-x"/></svg>X</a>
  </nav>
</header>

<div class="hero">
  <h1>Solana token signals for AI agents</h1>
  <p>One request gives a verdict, reasons and context. The track record is public on <a href="/stats">/stats</a>. Heuristics only, not financial advice.</p>
  <div class="links">
    <a class="btn" href="/stats">Live accuracy</a>
    <a class="btn" href="/mcp">MCP</a>
    <a class="btn" href="/agents">For agents</a>
  </div>
</div>

<div class="check" id="check">
  <h2>Check a token</h2>
  <form class="row" id="f" autocomplete="off">
    <input id="mint" type="text" inputmode="text" spellcheck="false" autocapitalize="off" autocorrect="off" placeholder="Paste a Solana mint address (CA)" aria-label="Solana mint address">
    <button id="go" type="submit">Check</button>
  </form>
  <p class="hint">Result appears here. Try <button type="button" id="demo">SOL</button> · Not financial advice.</p>
  <div id="out" aria-live="polite"></div>
</div>

<section class="s">
  <div class="cards">
    <div class="card"><h3>Primary call</h3><code>GET /omni?mint=…</code><p>Verdict and decision block agents should trust first.</p></div>
    <div class="card"><h3>Prove it</h3><code>GET /stats</code><p>Precision and recall on judged outcomes, not marketing claims.</p></div>
    <div class="card"><h3>MCP</h3><code>omni(mint)</code><p>Wire into Cursor, Claude, or your agent runtime.</p></div>
    <div class="card"><h3>Self-host</h3><code>github.com/TVibex402/signal-api</code><p>Same code. Your Redis starts its own track record.</p></div>
  </div>
</section>

<section class="s">
  <h2>Quick start</h2>
  <pre class="code">curl -s "https://signal-api-24q4.onrender.com/omni?mint=So11111111111111111111111111111111111111112" | jq .decision</pre>
  <p class="mut" style="font-size:14px">Batch: <code>/signals?mints=a,b,c&amp;view=compact</code> (max 10). Cache the same mint for 15–30s.</p>
</section>

<section class="s">
  <h2>Fair use</h2>
  <p class="mut" style="font-size:14px;margin:0">The public host is <b style="color:var(--txt)">free</b>. About 30 requests per minute without a key, batch max 10, please cache. For heavy traffic, self-host or slow down on HTTP 429. <a href="/support">/support</a></p>
</section>

<section class="s" id="donate">
  <h2>Optional tip</h2>
  <p class="mut" style="font-size:14px;margin:0 0 10px">TVibe Signal is free and open source. If the public instance helps your agents, you can tip SOL to cover hosting and RPC. Never required.</p>
  <div class="tip">
    <code>3iAVBvE4aU4A5DTKCqzu6jg79UfW6aEnqUD1pjfew18n</code>
    <button class="btn" data-copy="3iAVBvE4aU4A5DTKCqzu6jg79UfW6aEnqUD1pjfew18n">Copy address</button>
    <a href="/donate">/donate JSON</a>
  </div>
</section>

<footer>
  <span>Not financial advice. Heuristics for agents and research.</span>
  <a href="/support">/support</a>
  <a href="/agents">/agents</a>
  <a href="/llms.txt">llms.txt</a>
  <a href="https://github.com/TVibex402/signal-api" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-gh"/></svg>source</a>
  <a href="https://x.com/realTVibe" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-x"/></svg>@realTVibe</a>
</footer>
</div>

<script>
(function(){
var $=function(s){return document.querySelector(s)};
var out=$('#out'),inp=$('#mint'),btn=$('#go'),lastJSON='';
var B58=/^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
var SOL='So11111111111111111111111111111111111111112';

function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function vc(v){return {ok:'ok',caution:'warn',avoid:'bad'}[String(v||'').toLowerCase()]||'mut'}
function pct(x){return Math.round((Number(x)||0)*100)}
function chip(t,c){return '<span class="chip '+(c||'')+'">'+esc(t)+'</span>'}

function copy(text,el){
  function done(){if(el){var o=el.textContent;el.textContent='Copied';setTimeout(function(){el.textContent=o},1200)}}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(text).then(done,fb)}else fb();
  function fb(){var t=document.createElement('textarea');t.value=text;document.body.appendChild(t);t.select();try{document.execCommand('copy')}catch(e){}t.remove();done()}
}
document.addEventListener('click',function(e){var b=e.target.closest('[data-copy]');if(b)copy(b.getAttribute('data-copy'),b)});

function group(title,sym,c,arr){
  if(!Array.isArray(arr)||!arr.length)return '';
  var li=arr.map(function(x){return '<li>'+esc(typeof x==='string'?x:(x.label||x.id||JSON.stringify(x)))+'</li>'}).join('');
  return '<div class="grp '+c+'"><h4><span class="sym">'+sym+'</span>'+title+'<b>'+arr.length+'</b></h4><ul>'+li+'</ul></div>';
}

function debate(db){
  if(!db)return '';
  var vt=db.votes_weighted||db.votes||{};
  var tot=(vt.ok||0)+(vt.caution||0)+(vt.avoid||0)||1;
  var bar=['ok','caution','avoid'].map(function(k){return '<i class="'+vc(k)+'" style="width:'+((vt[k]||0)/tot*100)+'%"></i>'}).join('');
  var rows=(db.personas||[]).map(function(p){
    return '<div class="prow">'+chip(p.verdict,vc(p.verdict))+'<div><b>'+esc(p.persona)+'</b> <small>'+pct(p.confidence)+'%</small><p>'+esc(p.reason)+'</p></div></div>';
  }).join('');
  var ag=db.agreement_weighted!=null?db.agreement_weighted:db.agreement;
  return '<section class="box full"><h3>Agent debate '+chip(db.meta_verdict,vc(db.meta_verdict))+'<span class="mut" style="margin-left:auto;font-weight:500;font-size:12px">agreement '+pct(ag)+'%</span></h3><div class="vbar">'+bar+'</div>'+rows+'</section>';
}

function render(d){
  var dc=d.decision||{},v=String(dc.verdict||'unknown').toLowerCase(),c=vc(v);
  var risk=Number(dc.risk_score);var hasRisk=isFinite(risk);
  var rc=!hasRisk?'mut':(risk<35?'ok':(risk<65?'warn':'bad'));
  var C=2*Math.PI*34,off=hasRisk?C*(1-Math.min(100,Math.max(0,risk))/100):C;
  var label={ok:'OK',caution:'Caution',avoid:'Avoid'}[v]||v;
  var h='<div class="res">';
  h+='<div class="vhero '+c+'"><div class="ring '+rc+'"><svg viewBox="0 0 84 84"><circle class="bg" cx="42" cy="42" r="34"/><circle class="fg" id="fg" cx="42" cy="42" r="34" stroke-dasharray="'+C.toFixed(1)+'" stroke-dashoffset="'+C.toFixed(1)+'" data-off="'+off.toFixed(1)+'"/></svg><span>'+(hasRisk?risk:'?')+'<small>risk</small></span></div>';
  h+='<div class="vtxt"><div class="big"><i class="dot"></i>'+esc(label)+'<span class="tok">'+esc(d.token||'')+'</span></div><p>'+esc(d.summary||'')+'</p></div></div>';
  h+='<div class="mintline mono">'+esc(d.mint||'')+'</div>';

  var chips='';
  if(d.regime&&d.regime.name)chips+=chip('Regime: '+d.regime.name+' ('+pct(d.regime.confidence)+'%)',/risk_off/.test(d.regime.name)?'warn':(/risk_on/.test(d.regime.name)?'ok':''));
  if(d.attention_trap)chips+=chip('Attention trap','warn');
  var t=d.time_to_death;
  if(t&&t.band)chips+=chip('Stress clock: '+t.band+(t.eta_hours?' (~'+t.eta_hours+'h)':''),{slow:'ok',medium:'warn',fast:'bad'}[String(t.band).toLowerCase()]||'');
  var cf=d.counterfactual;
  if(cf&&cf.available&&cf.expected_bad_rate!=null){var r=cf.expected_bad_rate;chips+=chip('Similar cases bad: '+pct(r)+'% (n='+cf.cohort_n+')',r<.25?'ok':(r<.5?'warn':'bad'))}
  var at=d.community&&d.community.attention;
  if(at&&at['24h']!=null)chips+=chip('Attention 24h: '+at['24h'],'');
  if(chips)h+='<div class="chips">'+chips+'</div>';

  h+='<div class="grid">';
  h+=group('Blockers','✖','bad',dc.blockers);
  h+=group('Cautions','⚠','warn',dc.cautions);
  h+=group('Positives','✔','ok',dc.positives);
  h+=group('Unknowns','?','mut',dc.unknowns);
  h+=group('Pre-rug patterns','⚠','warn',d.pre_rug);
  h+=group('What would change this','↻','mut',d.would_change_my_mind);
  h+=debate(d.debate);
  h+='</div>';

  h+='<div class="tools"><button class="btn" id="cj">Copy JSON</button><button class="btn" id="cl">Copy link</button><a class="btn" href="/omni?mint='+encodeURIComponent(d.mint||'')+'" target
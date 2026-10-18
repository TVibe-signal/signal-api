# part107.py - /verify page + "results by source" box (v2.89.0)
# 1) GET /verify: anyone can paste a signed /omni response and check it in the browser.
# 2) Adds a "results by source" box to the Live accuracy section of the home page
#    (answers the "only tokens people query" criticism with the same stats you already publish).
# Works on top of your current part104/part105; nothing in them needs to change.
# Loader line (after part105/part106, before part7):  ("part107.py", 0, "SKIP"),
from fastapi.responses import HTMLResponse

VERSION = "2.89.0"
app.version = VERSION
app.openapi_schema = None

VERIFY_HTML = r'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark"><meta name="theme-color" content="#070b12">
<title>Verify a TVibe verdict</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#070b12;color:#e8eef6;font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;padding:1.2rem}
.wrap{max-width:720px;margin:0 auto}
a{color:#14f195}
h1{font-size:1.7rem;letter-spacing:-.03em;margin:.8rem 0 .3rem}
p.sub{color:#9db0ca;margin-bottom:1rem}
.card{background:rgba(15,22,34,.92);border:1px solid rgba(40,56,78,.9);border-radius:1rem;padding:1rem;margin-top:.8rem}
label{display:block;font-size:.85rem;color:#9db0ca;margin-bottom:.35rem}
input,textarea{width:100%;background:#0c121c;color:#e8eef6;border:1px solid rgba(40,56,78,.9);border-radius:.65rem;padding:.65rem .8rem;font:.85rem ui-monospace,Menlo,Consolas,monospace}
textarea{min-height:170px;resize:vertical}
.row{display:flex;gap:.5rem}
button{cursor:pointer;border:0;border-radius:.65rem;padding:.65rem 1.1rem;font-weight:700;font-size:.95rem}
.p{background:linear-gradient(135deg,#9945ff,#6366f1);color:#fff}
.o{background:transparent;border:1px solid rgba(40,56,78,.9);color:#e8eef6}
.res{font-size:1.3rem;font-weight:800;margin:.2rem 0 .6rem}
.res.ok{color:#3df5ad}.res.warn{color:#ffc94d}.res.bad{color:#ff6b64}
ul{list-style:none}
li{display:flex;gap:.6rem;padding:.4rem 0;border-top:1px solid rgba(40,56,78,.6);font-size:.92rem;word-break:break-word}
li b{width:1.3rem;flex:none;text-align:center}
li.ok b{color:#3df5ad}li.bad b{color:#ff6b64}li.warn b{color:#ffc94d}li.info b{color:#9db0ca}
.note{color:#9db0ca;font-size:.85rem;margin-top:.6rem}
</style></head><body><div class="wrap">
<p><a href="/">&larr; TVibe Signal</a></p>
<h1>Verify a verdict</h1>
<p class="sub">Every /omni verdict is signed. Check it here without trusting the server: all checks run in your browser.</p>
<div class="card">
<label for="mint">Option 1: fetch a live verdict by mint address and verify it</label>
<div class="row"><input id="mint" placeholder="Solana mint address" spellcheck="false" autocomplete="off" autocapitalize="off"><button id="fetch" class="p">Fetch</button></div>
</div>
<div class="card">
<label for="raw">Option 2: paste a saved /omni response (or just its "attestation" object)</label>
<textarea id="raw" spellcheck="false" placeholder='{"mint": "...", "decision": {...}, "attestation": {...}}'></textarea>
<div class="row" style="margin-top:.6rem"><button id="go" class="p">Verify</button></div>
</div>
<div class="card" id="out"><p class="note">The result appears here.</p></div>
<p class="note">A valid signature shows that this verdict was produced by the holder of the signing key, unchanged. It does not say the verdict is correct. Accuracy is on the home page.</p>
</div>
<script>
(function(){
var $=function(s){return document.getElementById(s)};
var B='123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function b58d(s){var n=BigInt(0),i;for(i=0;i<s.length;i++){var k=B.indexOf(s[i]);if(k<0)throw new Error('bad base58');n=n*BigInt(58)+BigInt(k)}var hex=n.toString(16);if(hex.length%2)hex='0'+hex;var by=[];for(i=0;i<hex.length;i+=2)by.push(parseInt(hex.substr(i,2),16));var z=0;while(z<s.length&&s[z]==='1')z++;if(n===BigInt(0))by=[];return new Uint8Array(new Array(z).fill(0).concat(by))}
function hexBytes(h){if(!/^[0-9a-f]*$/i.test(h)||h.length%2)throw new Error('bad hex');var o=new Uint8Array(h.length/2);for(var i=0;i<o.length;i++)o[i]=parseInt(h.substr(i*2,2),16);return o}
async function sha(t){var d=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(t));return Array.from(new Uint8Array(d)).map(function(x){return ('0'+x.toString(16)).slice(-2)}).join('')}
async function check(raw,livePub){
  var steps=[],ok=true,unk=false,j;
  function add(t,m){steps.push({t:t,m:m})}
  try{j=JSON.parse(raw)}catch(e){return {steps:[{t:'bad',m:'That is not valid JSON.'}],ok:false}}
  var a=(j&&j.attestation)?j.attestation:j;
  var miss=['canon','prev','hash','sig','pubkey'].filter(function(k){return !a||typeof a[k]!=='string'});
  if(miss.length)return {steps:[{t:'bad',m:'Missing fields: '+miss.join(', ')+'. Paste a full /omni response or its "attestation" object.'}],ok:false};
  var rec;try{rec=JSON.parse(a.canon)}catch(e){return {steps:[{t:'bad',m:'The signed record is not valid JSON.'}],ok:false}}
  add('ok','Record: '+rec.verdict+' for '+rec.mint+' (risk '+rec.risk+') signed at '+new Date(rec.ts*1000).toISOString()+'.');
  if(j.attestation&&j.decision&&j.mint){
    if(rec.mint===j.mint&&rec.verdict===j.decision.verdict)add('ok','The signed verdict matches the verdict shown in the response.');
    else{add('bad','The signed record does not match the verdict shown in the response.');ok=false}
  }
  try{
    var hex=await sha(a.prev+a.canon);
    if(hex===a.hash)add('ok','Hash matches: sha256(prev + record).');else{add('bad','Hash does not match the record.');ok=false}
  }catch(e){add('warn','This browser cannot compute SHA-256 here.');unk=true}
  try{
    var key=await crypto.subtle.importKey('raw',b58d(a.pubkey),{name:'Ed25519'},false,['verify']);
    var v=await crypto.subtle.verify({name:'Ed25519'},key,hexBytes(a.sig),hexBytes(a.hash));
    if(v)add('ok','Ed25519 signature is valid for '+a.pubkey+'.');else{add('bad','The signature is invalid.');ok=false}
  }catch(e){add('warn','This browser cannot check Ed25519 signatures (try a recent Chrome or Safari).');unk=true}
  if(livePub){
    if(livePub===a.pubkey)add('ok','The public key is the one this server publishes at /attest.');
    else{add('bad','The public key differs from the key this server publishes. This may be forged.');ok=false}
  }else add('warn','Could not read /attest to compare the public key.');
  add('info','Not checked here: the link to the previous verdict, and the daily Solana anchor (look for a memo from this address on Solscan).');
  return {steps:steps,ok:ok,unk:unk,rec:rec,pub:a.pubkey};
}
function show(r){
  var icon={ok:'\u2714',bad:'\u2716',warn:'!',info:'i'};
  var head=r.ok&&!r.unk?'<div class="res ok">Verified</div>':(r.ok?'<div class="res warn">Could not fully verify</div>':'<div class="res bad">Not valid</div>');
  $('out').innerHTML=head+'<ul>'+r.steps.map(function(s){return '<li class="'+s.t+'"><b>'+icon[s.t]+'</b><span>'+esc(s.m)+'</span></li>'}).join('')+'</ul>'
   +(r.pub?'<p class="note"><a href="https://solscan.io/account/'+encodeURIComponent(r.pub)+'" target="_blank" rel="noopener noreferrer">View signer address on Solscan</a></p>':'');
}
async function livePub(){try{var r=await fetch('/attest',{headers:{Accept:'application/json'}});var j=await r.json();return j&&j.pubkey?j.pubkey:null}catch(e){return null}}
$('go').addEventListener('click',async function(){show(await check($('raw').value.trim(),await livePub()))});
$('fetch').addEventListener('click',async function(){
  var m=$('mint').value.trim();if(!m)return;
  $('out').innerHTML='<p class="note">Fetching a live verdict...</p>';
  try{var r=await fetch('/omni?mint='+encodeURIComponent(m),{headers:{Accept:'application/json'}});var t=await r.text();
    try{$('raw').value=JSON.stringify(JSON.parse(t),null,2)}catch(e){$('raw').value=t}
    show(await check(t,await livePub()))}
  catch(e){$('out').innerHTML='<div class="res bad">Could not fetch the verdict.</div>'}
});
window.__tvCheck=check;
})();
</script></body></html>
'''

SOURCE_ADDON = r'''<!--source-breakdown-addon-->
<script>
(function(){
var body=document.getElementById('pf-body');if(!body)return;
var D=null,timer=null;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function num(x){return typeof x==='number'&&isFinite(x)}
function r1(x){return Math.round(x*10)/10}
function jget(u){return fetch(u,{headers:{'Accept':'application/json'}}).then(function(r){return r.ok?r.json():null}).catch(function(){return null})}
function bar(v){return '<div class="pf-bar"><i class="acc" style="width:'+Math.max(2,Math.min(100,v))+'%"></i></div>'}
function box(){
  var S=D&&D.by_source;if(!S)return '';
  var u=S.user,h='<div class="pf-box" id="pf-src"><h3>Is it only the easy cases? <small>results by where the token came from</small></h3>';
  var av=u&&u.verdicts&&u.verdicts.avoid;
  if(u&&num(u.bad_outcome_rate_pct)&&av&&num(av.bad_outcome_rate_pct))
    h+='<p class="pf-lead" style="margin:.2rem 0 .6rem">On the <b>'+esc(u.n)+'</b> tokens people really asked about, avoid was right <b>'+r1(av.bad_outcome_rate_pct)+'%</b> against a <b>'+r1(u.bad_outcome_rate_pct)+'%</b> base rate (+'+r1(av.bad_outcome_rate_pct-u.bad_outcome_rate_pct)+' points).</p>';
  var names=[['user','Asked by users'],['seed_new','New pairs'],['seed_trending','Trending'],['seed_boost','Boosted'],['seed_profile','Profiles'],['untagged','Older']];
  names.forEach(function(x){
    var s=S[x[0]];if(!s)return;var has=num(s.bad_outcome_rate_pct);
    h+='<div class="pf-row"><span style="font-size:.82rem">'+x[1]+'</span>'+(has?bar(s.bad_outcome_rate_pct):'<div class="pf-bar"></div>')+'<b>'+(has?r1(s.bad_outcome_rate_pct)+'%':'n&lt;20')+'</b><small>n='+esc(s.n)+(s.ci95_pct&&s.ci95_pct.length===2?' \u00B7 95% range '+esc(s.ci95_pct[0])+' to '+esc(s.ci95_pct[1])+'%':'')+'</small></div>';
  });
  return h+'<p class="pf-lead" style="font-size:.82rem;color:#9db0ca;margin:.4rem 0 0">Share of tokens that ended badly within 24h. Rates stay hidden under 20 samples. Auto-sampled tokens are not chosen by users, so they are shown separately and not mixed into the headline.</p></div>';
}
function inject(){
  if(!D||!body.firstChild||body.querySelector('#pf-src'))return;
  var t=document.createElement('div');t.innerHTML=box();var node=t.firstChild;if(!node)return;
  var det=body.querySelector('details');
  if(det&&det.parentNode)det.parentNode.insertBefore(node,det);else body.appendChild(node);
}
function schedule(){if(timer)return;timer=setTimeout(function(){timer=null;try{inject()}catch(e){}},60)}
if(window.MutationObserver)new MutationObserver(schedule).observe(body,{childList:true});
jget('/stats').then(function(j){return (j&&j.by_source)?j:jget('/accuracy')}).then(function(j){if(j&&j.by_source){D=j;schedule()}});
})();
</script>
'''


@app.get("/verify", response_class=HTMLResponse, include_in_schema=False)
async def verify_page():
    return VERIFY_HTML


try:
    _h = HOME_HTML
    if "<!--source-breakdown-addon-->" not in _h:
        _h = _h.replace("</body>", SOURCE_ADDON + "</body>", 1)
    if 'href="/verify"' not in _h and '<a href="/attest">/attest</a>' in _h:
        _h = _h.replace('<a href="/attest">/attest</a>', '<a href="/attest">/attest</a> \u00b7\n      <a href="/verify">/verify</a>', 1)
    HOME_HTML = _h
    print("[part107] v%s /verify page + results-by-source box" % VERSION)
except NameError:
    print("[part107] v%s /verify page only (HOME_HTML not found)" % VERSION)

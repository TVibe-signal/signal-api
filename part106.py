# part106.py - "Cost to sell" block as a standalone add-on (v2.88.2)
# Works on top of any part104 that serves the home page from the global HOME_HTML.
# It injects its own style + script; it does not need part104 to be changed.
# Loader line (after part104/part105, before part7):  ("part106.py", 0, "SKIP"),

EXIT_ADDON = r'''<!--cost-to-sell-addon-->
<style>
#csell{margin-top:1.2rem}
#csell h4{font-size:1.15rem;font-weight:700;margin:0 0 .55rem;display:flex;align-items:center;gap:.5rem;letter-spacing:-.01em}
#csell h4::before{content:"";width:4px;height:1.1em;border-radius:3px;background:linear-gradient(#9945ff,#14f195)}
#csell h4 small{font-weight:500;font-size:.75rem;color:#9db0ca}
.cs-chips{display:flex;flex-wrap:wrap;gap:.45rem;margin-bottom:.5rem}
.cs-chip{border:1px solid rgba(40,56,78,.9);border-radius:999px;padding:.25rem .75rem;font-size:.84rem;font-weight:600;color:#9db0ca;background:rgba(10,18,32,.8)}
.cs-chip.ok{color:#14f195;border-color:rgba(20,241,149,.4);background:rgba(11,32,22,.8)}
.cs-chip.warn{color:#f5b73b;border-color:rgba(245,183,59,.45);background:rgba(34,26,9,.8)}
.cs-chip.bad{color:#f2564f;border-color:rgba(242,86,79,.5);background:rgba(36,14,15,.8)}
.cs-grid{display:grid;grid-template-columns:auto 1fr auto;gap:.55rem .8rem;align-items:center;font-size:.95rem}
.cs-bar{height:8px;border-radius:99px;background:#0a1220;overflow:hidden}
.cs-bar i{display:block;height:100%;border-radius:99px}
.cs-bar i.ok{background:#14f195}.cs-bar i.warn{background:#f5b73b}.cs-bar i.bad{background:#f2564f}
.cs-grid b{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9rem}
.cs-grid b.ok{color:#14f195}.cs-grid b.warn{color:#f5b73b}.cs-grid b.bad{color:#f2564f}
.cs-na{grid-column:2/4;color:#9db0ca}
.cs-note{font-size:.84rem;color:#9db0ca;margin:.55rem 0 0;line-height:1.5}
.cs-btn{cursor:pointer;border:1px solid rgba(40,56,78,.9);background:rgba(10,18,32,.8);color:#e8eef6;border-radius:999px;padding:.25rem .75rem;font-size:.8rem}
.cs-btn:hover{border-color:#14f195}
.cs-warn{background:rgba(17,27,43,.9);border:1px solid rgba(245,183,59,.4);border-radius:.8rem;padding:.6rem .85rem;margin-top:.6rem;font-size:.9rem}
.cs-warn b{color:#ffc94d}
.cs-warn li{margin:.25rem 0}
</style>
<script>
(function(){
var out=document.getElementById('out');if(!out)return;
var cache={},busy={},timer=null;
function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
function isNum(v){return typeof v==='number'&&isFinite(v)}
function find(o,re,pred,d){d=d||0;if(!o||typeof o!=='object'||d>4)return undefined;var k,v;for(k in o){if(re.test(k)){v=o[k];if(pred(v))return v}}for(k in o){v=o[k];if(v&&typeof v==='object'){var r=find(v,re,pred,d+1);if(r!==undefined)return r}}return undefined}
function usd(n){return '$'+Number(n).toLocaleString('en-US',{maximumFractionDigits:0})}
function lossPct(v,k){v=Number(v);if(/bps/i.test(k))return v/100;if(/pct|percent/i.test(k))return v;return Math.abs(v)<=1?v*100:v}
function levels(lv){
  if(!Array.isArray(lv))return [];
  return lv.filter(function(it){return it&&typeof it==='object'}).map(function(it){
    var ks=Object.keys(it);
    var sk=ks.filter(function(k){return /usd|size|amount|notional/i.test(k)&&isNum(it[k])})[0];
    var lk=ks.filter(function(k){return /loss/i.test(k)&&isNum(it[k])})[0]||ks.filter(function(k){return /impact|slip|cost/i.test(k)&&isNum(it[k])})[0];
    var rk=ks.filter(function(k){return /receive|returns|out_usd/i.test(k)&&isNum(it[k])})[0];
    return {size:sk?it[sk]:null,loss:lk?it[lk]:null,lk:lk,status:it.status,recv:rk?it[rk]:null};
  });
}
function vcls(v){v=String(v||'').toLowerCase();return v==='ok'?'ok':(v==='caution'?'warn':(v==='avoid'?'bad':''))}
function retryBtn(){return ' <button type="button" class="cs-btn" data-cs="retry">Retry</button>'}
function build(x){
  var head='<h4>Cost to sell <small>Jupiter quote</small></h4>';
  if(!x||typeof x!=='object'||x.__error)return head+'<p class="cs-note" style="margin-top:0">Sell cost could not be loaded.'+retryBtn()+'</p>';
  var ex=x.exit&&typeof x.exit==='object'?x.exit:null;
  var lv=levels(ex?ex.levels:null),any=lv.some(function(z){return isNum(z.loss)});
  var grade=find(x,/^(exit_)?grade$/i,function(q){return typeof q==='string'});
  var overall=find(x,/^(overall|overall_verdict|combined_verdict|verdict)$/i,function(q){return typeof q==='string'});
  var h=head;
  if(ex&&ex.available===false&&!any){
    return h+'<p class="cs-note" style="margin-top:0">Sell cost is unavailable right now'+(ex.reason?': '+esc(ex.reason):'')+'.'+retryBtn()+'</p>';
  }
  if(!any&&!grade)return h+'<p class="cs-note" style="margin-top:0">No sell cost data for this token.'+retryBtn()+'</p>';
  var gc=/good|ok|low/i.test(grade||'')?'ok':(/fair|medium|mid|warn|caution/i.test(grade||'')?'warn':(grade?'bad':''));
  h+='<div class="cs-chips">'+(grade?'<span class="cs-chip '+gc+'">Exit grade: '+esc(grade)+'</span>':'')+(overall?'<span class="cs-chip '+vcls(overall)+'">Overall: '+esc(overall)+'</span>':'')+'</div>';
  if(lv.length){
    h+='<div class="cs-grid">'+lv.slice(0,6).map(function(z){
      var lab='<span>Sell '+(z.size!=null?usd(z.size):'')+(isNum(z.recv)?' <small style="color:#9db0ca">\u2192 '+usd(z.recv)+'</small>':'')+'</span>';
      if(!isNum(z.loss))return lab+'<span class="cs-na">n/a'+(z.status?' ('+esc(z.status)+')':'')+'</span>';
      var l=lossPct(z.loss,z.lk),c=l<3?'ok':(l<8?'warn':'bad');
      return lab+'<div class="cs-bar"><i class="'+c+'" style="width:'+Math.min(100,Math.max(3,l*4))+'%"></i></div><b class="'+c+'">'+(Math.round(l*10)/10)+'% lost</b>';
    }).join('')+'</div>';
  }
  h+='<p class="cs-note">A quote does not prove a real sell will succeed. Loss includes fees, price impact and price differences.</p>';
  if(Array.isArray(x.reasons)&&x.reasons.length)h+='<div class="cs-warn"><b>Exit check</b><ul>'+x.reasons.map(function(r){return '<li>'+esc(r)+'</li>'}).join('')+'</ul></div>';
  return h;
}
function mintOf(res){var m=res.querySelector('.r-mint');var t=m?String(m.textContent||'').trim():'';if(t)return t;try{return new URLSearchParams(location.search).get('mint')}catch(e){return null}}
function hasOwn(res){var hs=res.querySelectorAll('.r-h');for(var i=0;i<hs.length;i++){if(/^Cost to sell/i.test(String(hs[i].textContent||'').trim()))return true}return false}
function place(res,html){
  var wrap=document.createElement('div');wrap.id='csell';wrap.innerHTML=html;
  var old=res.querySelector('#csell');
  if(old){old.parentNode.replaceChild(wrap,old);return}
  var anchor=null,hs=res.querySelectorAll('.r-h');
  for(var i=0;i<hs.length;i++){if(/^(Agent debate|Next steps)/i.test(String(hs[i].textContent||'').trim())){anchor=hs[i];break}}
  if(!anchor)anchor=res.querySelector('.r-tools');
  if(anchor&&anchor.parentNode)anchor.parentNode.insertBefore(wrap,anchor);else res.appendChild(wrap);
}
function load(mint){
  busy[mint]=1;
  fetch('/exit?mint='+encodeURIComponent(mint),{headers:{'Accept':'application/json'}})
   .then(function(r){return r.ok?r.json():{__error:1}}).catch(function(){return {__error:1}})
   .then(function(j){cache[mint]=j;busy[mint]=0;schedule()});
}
function inject(){
  var res=out.querySelector('.res');if(!res||hasOwn(res)&&!res.querySelector('#csell'))return;
  var mint=mintOf(res);if(!mint)return;
  if(cache[mint]!==undefined){
    var cur=res.querySelector('#csell');
    var html=build(cache[mint]);
    if(!cur||cur.getAttribute('data-m')!==mint+':'+(cache[mint].__error?'e':'d')){place(res,html);var n=res.querySelector('#csell');if(n)n.setAttribute('data-m',mint+':'+(cache[mint].__error?'e':'d'))}
    return;
  }
  if(!res.querySelector('#csell'))place(res,'<h4>Cost to sell <small>Jupiter quote</small></h4><p class="cs-note" style="margin-top:0">Checking sell cost...</p>');
  if(!busy[mint])load(mint);
}
function schedule(){if(timer)return;timer=setTimeout(function(){timer=null;try{inject()}catch(e){}},60)}
out.addEventListener('click',function(e){
  var b=e.target&&e.target.closest?e.target.closest('[data-cs="retry"]'):null;if(!b)return;
  var res=out.querySelector('.res');if(!res)return;var mint=mintOf(res);if(!mint)return;
  delete cache[mint];place(res,'<h4>Cost to sell <small>Jupiter quote</small></h4><p class="cs-note" style="margin-top:0">Checking sell cost...</p>');load(mint);
});
if(window.MutationObserver)new MutationObserver(schedule).observe(out,{childList:true,subtree:true});
schedule();
})();
</script>
'''

try:
    if "<!--cost-to-sell-addon-->" not in HOME_HTML:
        HOME_HTML = HOME_HTML.replace("</body>", EXIT_ADDON + "</body>", 1)
        print("[part106] cost-to-sell add-on injected into the home page")
    else:
        print("[part106] add-on already present")
except NameError:
    print("[part106] HOME_HTML not found - part104 must load before part106")

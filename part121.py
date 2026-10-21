# part121.py - "Data notice" on the Live accuracy section when the measurement pipeline is degraded (v2.96.0)
# Shows an amber note when /stats says the verdict queue is unreadable (resolved=0 and pending=0 with empty verdict
# tables), the scoring fell back to "static", or the 1h/6h results are missing. Hides itself when data is back.
# Loader line (after part120, before part7):  ("part121.py", 0, "SKIP"),

NOTICE_ADDON = r'''<!--data-notice-addon-->
<script>
(function(){
var body=document.getElementById('pf-body');if(!body)return;
var D=null,timer=null;
function jget(u){return fetch(u,{headers:{'Accept':'application/json'}}).then(function(r){return r.ok?r.json():null}).catch(function(){return null})}
function gaps(d){
  var out=[];
  var bv=d.by_verdict||{},sum=0;
  ['ok','caution','avoid'].forEach(function(k){var f=bv[k]&&bv[k].full;if(f&&typeof f.n==='number')sum+=f.n});
  if(d.resolved===0&&d.pending===0&&sum===0)out.push('the queue of verdicts waiting for their 24h result is not readable');
  if(d.scoring==='static')out.push('the tuned risk weights are not loaded (scoring is "static")');
  var e=d.early_horizons&&d.early_horizons['1h'];
  if(e&&e.n===0&&sum===0)out.push('the 1h and 6h results are missing');
  return out;
}
function inject(){
  if(!D||!body.firstChild||body.querySelector('#pf-notice'))return;
  var g=gaps(D);if(!g.length)return;
  var n=document.createElement('div');n.id='pf-notice';n.className='pf-box';
  n.style.borderColor='rgba(245,183,59,.5)';
  n.innerHTML='<h3 style="color:#ffc94d">Data notice</h3><p class="pf-lead" style="margin:0;font-size:.9rem">Part of the measurement pipeline is temporarily unavailable ('+g.join('; ').replace(/[<>&]/g,'')+'). The numbers below come from verdicts judged before that, and recent verdicts may not be counted yet.</p>';
  body.insertBefore(n,body.firstChild);
}
function schedule(){if(timer)return;timer=setTimeout(function(){timer=null;try{inject()}catch(e){}},60)}
if(window.MutationObserver)new MutationObserver(schedule).observe(body,{childList:true});
jget('/stats').then(function(j){return (j&&j.performance)?j:jget('/accuracy')}).then(function(j){if(j&&j.performance){D=j;schedule()}});
})();
</script>
'''

try:
    if "<!--data-notice-addon-->" not in HOME_HTML:
        HOME_HTML = HOME_HTML.replace("</body>", NOTICE_ADDON + "</body>", 1)
    print("[part121] data notice add-on injected into the home page")
except NameError:
    print("[part121] HOME_HTML not found - part104 must load before part121")

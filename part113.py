# part113.py - display fixes on the home page (v2.89.3), works on top of your current part104
# 1) If the summary says "Verdict capped from X to Y", the headline now shows Y (the more cautious verdict)
#    instead of the old "Looks OK" in green.
# 2) Removes the duplicated "Agent debate" heading.
# 3) Keeps the survival chart from stretching into a huge empty box on phones.
# Loader line (after part107, before part7):  ("part113.py", 0, "SKIP"),

FIX_ADDON = r'''<!--display-fixes-addon-->
<style>
.r-box>svg{display:block;max-width:440px;margin:0 auto}
</style>
<script>
(function(){
var out=document.getElementById('out');if(!out)return;
var LABEL={ok:'Looks OK',caution:'Use caution',avoid:'High risk'},CLS={ok:'ok',caution:'warn',avoid:'bad'},timer=null;
function fix(){
  var res=out.querySelector('.res');if(!res)return;
  var hero=res.querySelector('.r-hero');
  if(hero&&!hero.getAttribute('data-cap')){
    hero.setAttribute('data-cap','1');
    var p=hero.querySelector('.r-vtxt p');
    var m=/Verdict capped from (ok|caution|avoid) to (ok|caution|avoid)/i.exec(p?String(p.textContent||''):'');
    if(m){
      var from=m[1].toLowerCase(),to=m[2].toLowerCase();
      hero.classList.remove('ok');hero.classList.remove('warn');hero.classList.remove('bad');hero.classList.add(CLS[to]);
      var big=hero.querySelector('.r-big');
      if(big){for(var i=0;i<big.childNodes.length;i++){var n=big.childNodes[i];if(n.nodeType===3&&String(n.nodeValue).trim()){n.nodeValue=LABEL[to];break}}}
      var chip=document.createElement('span');chip.className='r-chip warn';chip.style.marginTop='.5rem';chip.textContent='Verdict lowered from '+from+' to '+to;
      if(p&&p.parentNode)p.parentNode.appendChild(chip);
    }
  }
  var hs=res.querySelectorAll('.r-h');
  for(var j=0;j<hs.length;j++){
    if(/^Agent debate\s*$/i.test(String(hs[j].textContent||'').trim())){
      var nx=hs[j].nextElementSibling;
      if(nx&&nx.querySelector&&nx.querySelector('.r-box')&&hs[j].parentNode)hs[j].parentNode.removeChild(hs[j]);
    }
  }
}
function schedule(){if(timer)return;timer=setTimeout(function(){timer=null;try{fix()}catch(e){}},40)}
if(window.MutationObserver)new MutationObserver(schedule).observe(out,{childList:true,subtree:true});
schedule();
})();
</script>
'''

try:
    if "<!--display-fixes-addon-->" not in HOME_HTML:
        HOME_HTML = HOME_HTML.replace("</body>", FIX_ADDON + "</body>", 1)
    print("[part113] display fixes injected into the home page")
except NameError:
    print("[part113] HOME_HTML not found - part104 must load before part113")

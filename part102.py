# ---------- v2.80: Brand + motion (logo avatar, animated site) ----------
# Serves /logo.png /favicon.ico /favicon.png /apple-touch-icon.png /og.png from the brand files
# (folder brand/ or next to main.py; if a file is missing a built-in SVG logo is used).
# A middleware adds favicon/share tags, a header logo, soft animated background, scroll
# reveal, number count-up and hover polish to HTML pages. Any failure returns the original page.
# Env: P102_ON=0 turns it off, P102_SKIP="/docs,/redoc" lists pages left untouched, BRAND_DIR=path
VERSION = "2.80.0"
app.version = VERSION
app.openapi_schema = None

import os
import re

from fastapi.responses import Response

_P102_ON = os.environ.get("P102_ON", "1").lower() not in ("0", "false", "off")
_P102_SKIP = {p.strip() for p in os.environ.get("P102_SKIP", "/docs,/redoc").split(",") if p.strip()}
_P102_HERE = os.path.dirname(os.path.abspath(globals().get("__file__") or "."))
_P102_DIRS = [d for d in (os.environ.get("BRAND_DIR"), os.path.join(_P102_HERE, "brand"), _P102_HERE) if d]

_P102_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><defs>'
    '<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#e5e7eb"/>'
    '<stop offset=".45" stop-color="#8b9bd6"/><stop offset=".7" stop-color="#6ee7c8"/>'
    '<stop offset="1" stop-color="#9ca3af"/></linearGradient></defs>'
    '<rect x="8" y="8" width="84" height="84" rx="18" fill="url(#g)"/>'
    '<rect x="14" y="14" width="72" height="72" rx="13" fill="#f6f6f6"/>'
    '<rect x="31" y="27" width="38" height="10" fill="#000"/><rect x="45" y="27" width="10" height="36" fill="#000"/>'
    '<path d="M24 67Q37 55 50 66T76 66" fill="none" stroke="#000" stroke-width="5" stroke-linecap="round"/></svg>'
)
_P102_FILES = {}


def _p102_load(name):
    if name in _P102_FILES:
        return _P102_FILES[name]
    for d in _P102_DIRS:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            try:
                with open(p, "rb") as fh:
                    _P102_FILES[name] = fh.read()
                return _P102_FILES[name]
            except Exception:
                pass
    return None


_P102_ROUTES = {"/logo.png": ("logo.png",), "/favicon.ico": ("icon-192.png", "logo.png"),
                "/favicon.png": ("icon-192.png", "logo.png"), "/apple-touch-icon.png": ("icon-192.png", "logo.png"),
                "/og.png": ("og.png",)}
if callable(globals().get("_drop_routes")):
    _drop_routes(set(_P102_ROUTES))


def _p102_route(path, names):
    async def handler():
        for n in names:
            data = _p102_load(n)
            if data:
                return Response(content=data, media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})
        if path == "/og.png":
            return Response(status_code=404)
        return Response(content=_P102_SVG, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=3600"})
    app.get(path, include_in_schema=False)(handler)


for _p, _n in _P102_ROUTES.items():
    _p102_route(_p, _n)

_P102_CSS = """
html{scroll-behavior:smooth}
.p102-bg{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden;opacity:.55}
.p102-bg i{position:absolute;width:60vmax;height:60vmax;border-radius:50%;will-change:transform}
.p102-bg i:nth-child(1){left:-22vmax;top:-26vmax;background:radial-gradient(circle,rgba(99,102,241,.45),transparent 62%);animation:p102a 26s ease-in-out infinite alternate}
.p102-bg i:nth-child(2){right:-28vmax;top:8vh;background:radial-gradient(circle,rgba(168,85,247,.38),transparent 62%);animation:p102b 32s ease-in-out infinite alternate}
.p102-bg i:nth-child(3){left:12vw;bottom:-38vmax;background:radial-gradient(circle,rgba(20,241,149,.2),transparent 62%);animation:p102a 38s ease-in-out infinite alternate-reverse}
.p102-bg b{position:absolute;inset:0;background:radial-gradient(420px circle at var(--mx,50%) var(--my,28%),rgba(129,140,248,.16),transparent 60%)}
@keyframes p102a{to{transform:translate(16vmax,12vmax) scale(1.18)}}
@keyframes p102b{to{transform:translate(-14vmax,18vmax) scale(.9)}}
.p102-bar{position:fixed;left:0;top:0;height:3px;width:100%;transform-origin:0 50%;transform:scaleX(0);z-index:2147483000;background:linear-gradient(90deg,#6366f1,#a855f7,#14f195);pointer-events:none}
.p102-logo{width:36px;height:36px;border-radius:10px;flex:none;filter:drop-shadow(0 0 8px rgba(129,140,248,.6));animation:p102g 4.5s ease-in-out infinite;transition:transform .3s}
.p102-logo:hover{transform:rotate(-6deg) scale(1.1)}
@keyframes p102g{50%{filter:drop-shadow(0 0 16px rgba(168,85,247,.85))}}
.p102-r{opacity:0;transform:translateY(16px);transition:opacity .6s ease,transform .6s ease}
.p102-r.p102-in{opacity:1;transform:none}
.p102-shine{background-size:220% 100%!important;animation:p102s 8s ease-in-out infinite alternate}
@keyframes p102s{from{background-position:0 0}to{background-position:100% 0}}
a,button,input{transition:transform .18s,box-shadow .18s,border-color .18s,background-color .18s,color .18s}
button:hover,.btn:hover,a[class*="btn"]:hover,a[class*="button"]:hover{transform:translateY(-2px);box-shadow:0 10px 26px rgba(99,102,241,.38)}
button:active,.btn:active,a[class*="btn"]:active{transform:translateY(0)}
input:focus,textarea:focus{outline:none;border-color:#818cf8!important;box-shadow:0 0 0 3px rgba(99,102,241,.35)}
::selection{background:rgba(99,102,241,.45)}
@media (prefers-reduced-motion:reduce){html{scroll-behavior:auto}.p102-bg i,.p102-logo,.p102-shine{animation:none!important}.p102-r{opacity:1!important;transform:none!important;transition:none!important}.p102-bar{display:none}}
"""

_P102_JS = r"""
(function(){try{
var d=document,de=d.documentElement,B=d.body;
var reduce=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
function safe(f){try{f()}catch(e){}}
safe(function(){
 var w=d.createTreeWalker(B,NodeFilter.SHOW_TEXT),n,i=0,host=null;
 while((n=w.nextNode())&&i++<600){var p=n.parentElement;
  if(p&&/^\s*TVibe/.test(n.nodeValue)&&!p.closest('script,style,h1,h2,h3,p,li,pre,code,.p101d')){host=p;break}}
 if(!host)return;
 var a=host.closest('a')||host;
 if(a.querySelector('.p102-logo'))return;
 var im=d.createElement('img');im.src='/logo.png';im.alt='TVibex402 logo';im.className='p102-logo';im.width=36;im.height=36;
 a.insertBefore(im,a.firstChild);a.style.display='inline-flex';a.style.alignItems='center';a.style.gap='10px';
});
var bg=d.createElement('div');bg.className='p102-bg';bg.setAttribute('aria-hidden','true');bg.innerHTML='<i></i><i></i><i></i><b></b>';
B.insertBefore(bg,B.firstChild);
var bar=d.createElement('div');bar.className='p102-bar';B.appendChild(bar);
var tk=0;function onS(){if(tk)return;tk=requestAnimationFrame(function(){tk=0;var h=de.scrollHeight-innerHeight;bar.style.transform='scaleX('+(h>0?Math.min(1,scrollY/h):0)+')'})}
addEventListener('scroll',onS,{passive:true});onS();
if(!reduce&&matchMedia('(hover:hover) and (pointer:fine)').matches){var px=0;
 addEventListener('pointermove',function(e){if(px)return;px=requestAnimationFrame(function(){px=0;bg.style.setProperty('--mx',e.clientX+'px');bg.style.setProperty('--my',e.clientY+'px')})},{passive:true})}
safe(function(){d.querySelectorAll('h1,h1 *').forEach(function(e){var c=getComputedStyle(e),k=c.webkitBackgroundClip||c.backgroundClip;if(k==='text')e.classList.add('p102-shine')})});
if(reduce||!('IntersectionObserver' in window)){de.classList.add('p102-on');return}
safe(function(){
 var sel='main>*,section,article,form,[class*="card"],[class*="panel"],[class*="hero"]>*,h1,h2,h3,table,pre';
 var all=[].slice.call(d.querySelectorAll(sel)).filter(function(e){return !e.closest('header,nav,footer,.p101d,.p102-bg,script,style')});
 var ok=all.filter(function(e){return all.filter(function(o){return o!==e&&e.contains(o)}).length<3});
 var els=ok.filter(function(e){return !ok.some(function(o){return o!==e&&o.contains(e)})}).slice(0,60);
 var io=new IntersectionObserver(function(es){es.forEach(function(x){if(!x.isIntersecting)return;var t=x.target;t.classList.add('p102-in');io.unobserve(t);
  setTimeout(function(){t.classList.remove('p102-r','p102-in');t.style.transitionDelay=''},1100)})},{threshold:.08});
 els.forEach(function(e,i){e.classList.add('p102-r');e.style.transitionDelay=Math.min(i,6)*70+'ms';io.observe(e)});
 setTimeout(function(){els.forEach(function(e){e.classList.add('p102-in')})},3500);
});
function fmt(v,dec,c){var s=dec?v.toFixed(dec):String(Math.round(v));return c?Number(s).toLocaleString('en-US',{minimumFractionDigits:dec,maximumFractionDigits:dec}):s}
function wrap(tn,re){var m=re.exec(tn.nodeValue);if(!m)return null;var num=m[2],val=parseFloat(num.replace(/,/g,''));
 if(!(val>=10||m[3]))return null;
 var sp=d.createElement('span');sp.className='p102-n';sp.textContent=num;sp.dataset.v=val;sp.dataset.dec=(num.split('.')[1]||'').length;sp.dataset.c=(num.indexOf(',')>-1||val>=1000)?'1':'0';
 var p=tn.parentNode;p.insertBefore(d.createTextNode(m[1]),tn);p.insertBefore(sp,tn);tn.nodeValue=tn.nodeValue.slice(m[0].length);return sp}
safe(function(){
 var cio=new IntersectionObserver(function(es){es.forEach(function(x){if(!x.isIntersecting)return;cio.unobserve(x.target);var s=x.target,v=+s.dataset.v,dec=+s.dataset.dec,c=s.dataset.c==='1',t0=performance.now();
  (function f(t){var k=Math.min(1,(t-t0)/1100),e=1-Math.pow(1-k,3);s.textContent=fmt(k<1?v*e:v,dec,c);if(k<1)requestAnimationFrame(f)})(t0)})},{threshold:.4});
 var re1=/^(\s*)(\d[\d,]*(?:\.\d+)?)(?=(%)|\s|$)/,re2=/^(\s*)(\d+(?:\.\d+)?)(?=(%))/,left=14;
 d.querySelectorAll('strong,b,[class*="stat"],[class*="metric"],[class*="count"]').forEach(function(e){
  if(left<=0||e.closest('pre,code,table,textarea,script,style,.p101d')||!e.firstChild||e.firstChild.nodeType!==3)return;
  var s=wrap(e.firstChild,re1);if(!s)return;left--;cio.observe(s);s.textContent=fmt(0,+s.dataset.dec,s.dataset.c==='1');
  var nx=e.nextSibling;if(nx&&nx.nodeType===3){var s2=wrap(nx,re2);if(s2){cio.observe(s2);s2.textContent=fmt(0,+s2.dataset.dec,s2.dataset.c==='1')}}});
});
de.classList.add('p102-on');
}catch(e){}})();
"""


def _p102_strip_icons(html):
    def fn(m):
        tag = m.group(0)
        return "" if re.search(r"\brel\s*=\s*[\"']?(?:shortcut\s+icon|icon|apple-touch-icon)\b", tag, re.I) else tag
    return re.sub(r"<link\b(?:\"[^\"]*\"|'[^']*'|[^>\"'])*>", fn, html, flags=re.I)


def _p102_head_tags(html, base):
    png = _p102_load("icon-192.png") or _p102_load("logo.png")
    tags = [f'<link rel="icon" type="{"image/png" if png else "image/svg+xml"}" href="/favicon.png">',
            '<link rel="apple-touch-icon" href="/apple-touch-icon.png">']
    if 'name="theme-color"' not in html:
        tags.append('<meta name="theme-color" content="#07070f">')
    if "og:image" not in html and _p102_load("og.png"):
        u = base + "/og.png"
        tags += [f'<meta property="og:image" content="{u}">', '<meta property="og:image:width" content="1200">',
                 '<meta property="og:image:height" content="630">',
                 '<meta name="twitter:card" content="summary_large_image">', f'<meta name="twitter:image" content="{u}">']
    return "".join(tags)


def _p102_inject(html, base):
    html = _p102_strip_icons(html)
    head = _p102_head_tags(html, base) + '<style id="p102-css">' + _P102_CSS + "</style>"
    m = re.search(r"</head>", html, re.I)
    if m:
        html = html[:m.start()] + head + html[m.start():]
    else:
        m = re.search(r"<body[^>]*>", html, re.I)
        if not m:
            return html
        html = html[:m.end()] + head + html[m.end():]
    js = '<script id="p102-js">' + _P102_JS + "</script>"
    i = html.lower().rfind("</body>")
    return html[:i] + js + html[i:] if i != -1 else html + js


if _P102_ON:
    try:
        @app.middleware("http")
        async def _p102_mw(request, call_next):
            resp = await call_next(request)
            if (request.method != "GET" or resp.status_code != 200 or request.url.path in _P102_SKIP
                    or "text/html" not in resp.headers.get("content-type", "")):
                return resp
            body = b""
            async for chunk in resp.body_iterator:
                body += chunk
            keep = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
            out = body
            try:
                html = body.decode("utf-8")
                if "p102-css" not in html and "swagger-ui" not in html:
                    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
                    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
                    new = _p102_inject(html, f"{proto}://{host}").encode("utf-8")
                    if new != body:
                        out = new
                        keep = {k: v for k, v in keep.items() if k.lower() != "content-encoding"}
            except Exception as e:
                print(f"[part102] skipped: {str(e)[:80]}")
            return Response(content=out, status_code=200, headers=keep)
    except Exception as e:
        print(f"[part102] middleware not added: {e}")

print(f"[part102] v{VERSION} brand+motion (on={_P102_ON}) logo files: "
      f"{'found' if _p102_load('logo.png') else 'missing -> SVG fallback'}")

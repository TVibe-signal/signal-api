# part130.py — Show filter.pass on the home token card (Phase B UI)
# Patches HOME_HTML from part104: one chip next to the other status chips.
VERSION = "3.0.2"
app.version = VERSION
app.openapi_schema = None

_INJECT_FROM = "if(chips)h+='<div class=\"r-chips\">'+chips+'</div>';"
_INJECT_TO = (
    "var fl=d.filter;if(fl&&typeof fl==='object'&&fl.pass!=null){"
    "chips=(chips||'')+chip(fl.pass?'Filter: PASS':'Filter: BLOCK',fl.pass?'ok':'bad');"
    "if(fl.policy)chips+=chip('policy '+String(fl.policy),'');"
    "if(!fl.pass&&fl.reasons&&fl.reasons.length)chips+=chip(String(fl.reasons[0]).slice(0,48),'warn');"
    "}"
    "if(chips)h+='<div class=\"r-chips\">'+chips+'</div>';"
)

_CSS_EXTRA = """
<style id="tvibe-filter-chip">
.r-chips .r-chip.ok{border-color:rgba(46,204,113,.45)}
.r-chips .r-chip.bad{border-color:rgba(255,107,100,.5);color:#ffb4b0}
</style>
"""

def _patch_home_html():
    html = globals().get("HOME_HTML")
    if not isinstance(html, str):
        print("[part130] HOME_HTML not found — skip UI patch")
        return False
    if "Filter: PASS" in html or "tvibe-filter-chip" in html:
        print("[part130] already patched")
        return True
    if _INJECT_FROM not in html:
        # alternate quote style
        alt = _INJECT_FROM.replace("\"", "'")
        if alt in html:
            html = html.replace(alt, _INJECT_TO.replace("\"", "'"), 1)
        else:
            print("[part130] chips anchor not found — check part104 render()")
            return False
    else:
        html = html.replace(_INJECT_FROM, _INJECT_TO, 1)
    if "</head>" in html:
        html = html.replace("</head>", _CSS_EXTRA + "</head>", 1)
    elif "</body>" in html:
        html = html.replace("</body>", _CSS_EXTRA + "</body>", 1)
    globals()["HOME_HTML"] = html
    # re-bind / if home closed over old string
    for route in list(app.routes):
        if getattr(route, "path", None) == "/" and getattr(route, "methods", None):
            endpoint = getattr(route, "endpoint", None)
            if callable(endpoint):
                async def _home():
                    return HTMLResponse(globals()["HOME_HTML"])
                try:
                    from fastapi.responses import HTMLResponse
                    route.endpoint = _home
                    if hasattr(route, "dependant") and route.dependant is not None:
                        route.dependant.call = _home
                except Exception as e:
                    print("[part130] route rebind:", e)
    print("[part130] HOME_HTML patched — filter.pass chip on card")
    return True


try:
    from fastapi.responses import HTMLResponse  # noqa: F401
except Exception:
    pass

_ok = _patch_home_html()
print("[part130] v%s filter.pass on web UI (%s)" % (VERSION, "ok" if _ok else "miss"))
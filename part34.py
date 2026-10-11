# ---------- part34: v2.21.0 - UI polish layer: one shared top bar, mobile touch targets, focus rings, theme colour ----------
# Loads last before part7 (it needs every page to be registered). Changes no behaviour: it only patches the HTML of the pages we own
# (/play, /status, /start, and the landing page) when their handlers run. A link appears only if that page exists on this server.
VERSION = "2.21.0"
app.version = VERSION
app.openapi_schema = None

_UI_MARK = "ui-polish"
_UI_CSS = """/* ui-polish */
.topnav{display:flex;align-items:center;justify-content:space-between;gap:.5rem;flex-wrap:wrap;max-width:1040px;margin:0 auto;padding:.7rem 1rem;border-bottom:1px solid #1e2638}
.topnav .brand{font-weight:800;letter-spacing:-.03em;color:#f1f5f9;text-decoration:none;font-size:1.05rem}
.topnav .brand span{color:#6366f1}
.topnav nav{display:flex;gap:.15rem;flex-wrap:wrap}
.topnav nav a{color:#94a3b8;text-decoration:none;font-size:.88rem;padding:.4rem .65rem;border-radius:.5rem;min-height:36px;display:inline-flex;align-items:center}
.topnav nav a:hover{color:#f1f5f9;background:#111827}
.topnav nav a[aria-current="page"]{color:#fff;background:#1e2638}
a:focus-visible,button:focus-visible,input:focus-visible,summary:focus-visible{outline:2px solid #818cf8;outline-offset:2px}
@media (max-width:640px){button,.btn{min-height:44px}.topnav{padding:.6rem .75rem}}
"""
_UI_HEAD = '<meta name="theme-color" content="#05080f"><meta name="color-scheme" content="dark">'
_NAV_ITEMS = [("/play", "Playground"), ("/accuracy", "Accuracy"), ("/status", "Status"), ("/docs", "API docs"), ("/pricing", "Pricing"), ("/start", "Get started")]


def _ui_nav(active: str) -> str:
    links = "".join(
        '<a href="' + p + '"' + (' aria-current="page"' if p == active else "") + ">" + label + "</a>"
        for p, label in _NAV_ITEMS if any(getattr(r, "path", None) == p for r in app.routes))
    return '<header class="topnav"><a class="brand" href="/">TVibe<span>x402</span></a><nav aria-label="Main">' + links + "</nav></header>"


def _ui_patch(html: str, active: str, with_nav: bool = True) -> str:
    """Idempotent: a page that already carries the layer is returned unchanged; a page without the expected anchors is left alone."""
    if not isinstance(html, str) or _UI_MARK in html:
        return html
    if "</style>" in html:
        html = html.replace("</style>", _UI_CSS + "</style>", 1)
    if '<meta charset="utf-8">' in html:
        html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + _UI_HEAD, 1)
    if with_nav and "<body>" in html:
        html = html.replace("<body>", "<body>" + _ui_nav(active), 1)
    return html


# the pages hold their HTML in module variables or build it per request; the handlers read these names when a request arrives
for _name, _path in (("STATUS_HTML", "/status"), ("PLAY_HTML", "/play")):
    if _name in globals():
        globals()[_name] = _ui_patch(globals()[_name], _path)
if "HOME_HTML" in globals():
    HOME_HTML = _ui_patch(HOME_HTML, "/", with_nav=False)  # the landing page already has its own header
if "render_start" in globals():
    _render_start_v30 = render_start

    def render_start(base: str) -> str:
        return _ui_patch(_render_start_v30(base), "/start")


print(f"[part34] v{VERSION} UI polish layer ready (shared top bar on /play, /status, /start)")

# ---------- v2.79: Donate banner on top of the homepage ----------
# A slim bar right under <body> on GET / (add pages with DONATE_BANNER_PATHS="/,/docs").
# Works without touching the page code: a middleware injects it into the HTML.
# If anything fails the original page is returned unchanged. DONATE_BANNER=0 turns it off.
# Needs part100 (DONATE_SOL).
VERSION = "2.79.0"
app.version = VERSION
app.openapi_schema = None

import os
import re

from fastapi.responses import Response

_P101_ON = os.environ.get("DONATE_BANNER", "1").lower() not in ("0", "false", "off")
_P101_PATHS = {p.strip() for p in os.environ.get("DONATE_BANNER_PATHS", "/").split(",") if p.strip()}
_P101_ADDR = globals().get("DONATE_SOL") or ""
_P101_SHORT = (_P101_ADDR[:4] + "…" + _P101_ADDR[-4:]) if len(_P101_ADDR) > 12 else _P101_ADDR

_P101_BANNER = (
    '<style>'
    '.p101d{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center;justify-content:center;'
    'padding:8px 36px 8px 12px;position:relative;font:13px/1.4 system-ui,sans-serif;color:#c7d2fe;'
    'background:rgba(99,102,241,.14);border-bottom:1px solid rgba(99,102,241,.4);text-align:center}'
    '.p101d code{color:#a5f3c4;font-family:ui-monospace,monospace}'
    '.p101d a{color:#c7d2fe;text-decoration:underline}'
    '.p101d button{font:inherit;color:#fff;background:#6366f1;border:0;border-radius:8px;padding:3px 10px;cursor:pointer}'
    '.p101d .x{position:absolute;right:6px;top:3px;background:none;color:#c7d2fe;font-size:18px;padding:2px 8px}'
    '</style>'
    '<div class="p101d" id="p101-donate">'
    '<span>Free &amp; open source. Optional SOL tip:</span>'
    '<code>' + _P101_SHORT + '</code>'
    '<button type="button" data-a="' + _P101_ADDR + '" onclick="var b=this;navigator.clipboard.writeText(b.dataset.a)'
    '.then(function(){b.textContent=\'Copied ✓\';setTimeout(function(){b.textContent=\'Copy\'},1500)})'
    '.catch(function(){prompt(\'Copy address\',b.dataset.a)})">Copy</button>'
    '<a href="/donate.html">Details</a>'
    '<button type="button" class="x" aria-label="Close" onclick="this.parentNode.remove()">×</button>'
    '</div>'
)


def _p101_inject(html: str) -> str:
    if "p101-donate" in html:
        return html
    m = re.search(r"<body[^>]*>", html, re.I)
    return html if not m else html[:m.end()] + _P101_BANNER + html[m.end():]


if _P101_ON and _P101_ADDR:
    try:
        @app.middleware("http")
        async def _p101_banner_mw(request, call_next):
            resp = await call_next(request)
            if (request.method != "GET" or request.url.path not in _P101_PATHS or resp.status_code != 200
                    or "text/html" not in resp.headers.get("content-type", "")):
                return resp
            body = b""
            async for chunk in resp.body_iterator:
                body += chunk
            keep = {k: v for k, v in resp.headers.items() if k.lower() != "content-length"}
            out = body
            try:
                new = _p101_inject(body.decode("utf-8")).encode("utf-8")
                if new != body:
                    out = new
                    keep = {k: v for k, v in keep.items() if k.lower() != "content-encoding"}
            except Exception as e:
                print(f"[part101] banner skipped: {str(e)[:80]}")
            return Response(content=out, status_code=200, headers=keep)
    except Exception as e:
        print(f"[part101] middleware not added: {e}")

print(f"[part101] v{VERSION} donate banner on {sorted(_P101_PATHS)} (on={_P101_ON and bool(_P101_ADDR)})")

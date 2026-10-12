# ---------- part38: v2.25.0 - contact block on public pages ----------
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as _Resp

VERSION = "2.25.0"
app.version = VERSION
app.openapi_schema = None

CONTACT_URL = (os.getenv("CONTACT_URL") or "").strip()
CONTACT_LABEL = (os.getenv("CONTACT_LABEL") or "Contact").strip()
_CONTACT_PATHS = ("/", "/pricing", "/start")


class _ContactMW(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        if not CONTACT_URL or request.url.path not in _CONTACT_PATHS:
            return resp
        if "text/html" not in (resp.headers.get("content-type") or ""):
            return resp
        if resp.headers.get("content-encoding"):
            return resp
        body = b""
        async for chunk in resp.body_iterator:
            body += chunk
        html = body.decode("utf-8", "ignore")
        block = ('<p style="text-align:center;margin:24px 0;font-size:14px">'
                 f'<a href="{CONTACT_URL}" style="color:#7dd3fc">{CONTACT_LABEL}</a>'
                 ' - API keys, feedback, partnerships</p>')
        if "</body>" in html:
            html = html.replace("</body>", block + "</body>", 1)
        else:
            html += block
        skip = ("content-length", "content-type", "content-encoding")
        headers = {k: v for k, v in resp.headers.items() if k.lower() not in skip}
        return _Resp(content=html.encode("utf-8"), status_code=resp.status_code,
                     headers=headers, media_type="text/html")


try:
    app.add_middleware(_ContactMW)
except Exception as e:
    print(f"[part38] contact block not added: {e}")

print(f"[part38] v{VERSION} contact block {'on' if CONTACT_URL else 'off (set CONTACT_URL)'}")
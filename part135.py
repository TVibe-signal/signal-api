# part135.py — brand cleanup: TVibex402 → TVibe-signal (web HTML only)
# Does not touch Telegram bot state, verdicts, or live rules.
# Loader (after part133, before part7):  ("part135.py", 0, "SKIP"),

import os

VERSION = "3.0.6"
app.version = VERSION
app.openapi_schema = None

_BRAND_NEW_GH = os.environ.get(
    "GITHUB_URL", "https://github.com/TVibe-signal/signal-api"
).rstrip("/")
_BRAND_OLD_GH = "https://github.com/TVibex402/signal-api"
_BRAND_OLD_HOST = "github.com/TVibex402/signal-api"
_BRAND_NEW_HOST = _BRAND_NEW_GH.replace("https://", "").replace("http://", "")
_BRAND_OLD_ORG = "TVibex402"
_BRAND_NEW_ORG = "TVibe-signal"


def _brand_patch_html(text: str) -> str:
    if not text or _BRAND_OLD_ORG not in text and _BRAND_OLD_HOST not in text:
        return text
    text = text.replace(_BRAND_OLD_GH, _BRAND_NEW_GH)
    text = text.replace(_BRAND_OLD_HOST, _BRAND_NEW_HOST)
    # Visible org mentions in prose (avoid changing unrelated long hashes)
    text = text.replace(_BRAND_OLD_ORG + "/signal-api", _BRAND_NEW_ORG + "/signal-api")
    text = text.replace(_BRAND_OLD_ORG, _BRAND_NEW_ORG)
    return text


_home = globals().get("HOME_HTML")
if isinstance(_home, str) and _BRAND_OLD_ORG in _home:
    HOME_HTML = _brand_patch_html(_home)
    globals()["HOME_HTML"] = HOME_HTML


class _BrandCleanupMW:
    """Patch remaining TVibex402 on HTML responses (/, /agents, /pricing, /docs, …)."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "GET":
            return await self.app(scope, receive, send)
        path = scope.get("path") or ""
        # Skip API JSON paths
        if path.startswith(("/omni", "/signal", "/stats", "/mcp", "/health", "/ping", "/api")):
            return await self.app(scope, receive, send)

        held, chunks = {}, []

        async def cap(msg):
            if msg["type"] == "http.response.start":
                held["start"] = msg
                return
            if msg["type"] != "http.response.body" or "start" not in held:
                return await send(msg)
            chunks.append(msg.get("body", b""))
            if msg.get("more_body"):
                return
            body, start = b"".join(chunks), held["start"]
            try:
                hs = {k.lower(): v for k, v in (start.get("headers") or [])}
                ctype = hs.get(b"content-type", b"")
                if (
                    start.get("status") == 200
                    and b"text/html" in ctype
                    and b"content-encoding" not in hs
                ):
                    text = body.decode("utf-8", "ignore")
                    patched = _brand_patch_html(text)
                    if patched != text:
                        body = patched.encode("utf-8")
            except Exception:
                pass
            hdrs = [
                (k, v) for k, v in start["headers"] if k.lower() != b"content-length"
            ] + [(b"content-length", str(len(body)).encode())]
            await send({**start, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, cap)


try:
    app.add_middleware(_BrandCleanupMW)
except Exception as e:
    print("[part135] mw:", str(e)[:100])

print(
    "[part135] v%s brand cleanup %s → %s"
    % (VERSION, _BRAND_OLD_ORG, _BRAND_NEW_ORG)
)
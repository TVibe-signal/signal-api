# part133.py - nav: Telegram bot + GitHub org link (v3.0.5, reviewed)
# Review fixes vs v3.0.4:
#   - it assigned _TG and _html. All parts share ONE namespace: _TG is part114's Telegram state object (updates,
#     replies, rate limits, bot username) and _html is part128's html module. After this part loaded, every Telegram
#     webhook raised "'str' object has no attribute 'updates'" and the /pricing page failed. Names are unique now.
#   - removed a condition that was always true.
# Set the GitHub link with the env var GITHUB_URL if the repo moves again.
import os

VERSION = "3.0.5"
app.version = VERSION
app.openapi_schema = None

_TG_LINK = "https://t.me/Gotvibesolbot"
_GITHUB_LINK = os.environ.get("GITHUB_URL", "https://github.com/TVibe-signal/signal-api").rstrip("/")
_X_LINK = "https://x.com/realTVibe"
_OLD_GITHUB = "https://github.com/TVibex402/signal-api"
_X_PILL = ('<a class="pill" href="%s" target="_blank" rel="noopener noreferrer">'
           '<svg class="ic"><use href="#i-x"/></svg>X</a>' % _X_LINK)
_TG_PILL = '<a class="pill" href="%s" target="_blank" rel="noopener noreferrer">Telegram</a>' % _TG_LINK
_HERO_OLD = 'Track record is public on <a href="/stats">/stats</a>.'
_HERO_NEW = (_HERO_OLD + ' Check a mint on the web, <a href="/mcp">MCP</a> or the '
             '<a href="%s" target="_blank" rel="noopener noreferrer">Telegram bot</a>: same verdict as <code>/omni</code>.' % _TG_LINK)


def _patch_page(text: str) -> str:
    text = text.replace(_OLD_GITHUB, _GITHUB_LINK).replace("github.com/TVibex402/signal-api", _GITHUB_LINK.replace("https://", ""))
    if "Gotvibesolbot" not in text:
        if _X_PILL in text:
            text = text.replace(_X_PILL, _X_PILL + "\n      " + _TG_PILL, 1)
        elif "GitHub</a>" in text:
            text = text.replace("GitHub</a>", "GitHub</a>\n      " + _TG_PILL, 1)
        if "Telegram bot" not in text and _HERO_OLD in text:
            text = text.replace(_HERO_OLD, _HERO_NEW, 1)
    return text


_home_page = globals().get("HOME_HTML")
if isinstance(_home_page, str):
    HOME_HTML = _patch_page(_home_page)


class _TgLinkMW:
    """Same fix for pages that are not built from HOME_HTML (/agents, /index.html). Fail-safe."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "GET" or (scope.get("path") or "") not in ("/", "/agents", "/index.html"):
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
                hs = {k.lower(): v for k, v in start.get("headers") or []}
                if start.get("status") == 200 and b"text/html" in hs.get(b"content-type", b"") and b"content-encoding" not in hs:
                    text = body.decode("utf-8", "ignore")
                    patched = _patch_page(text)
                    if patched != text:
                        body = patched.encode("utf-8")
            except Exception:
                pass
            hdrs = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"] + [(b"content-length", str(len(body)).encode())]
            await send({**start, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, cap)


try:
    app.add_middleware(_TgLinkMW)
except Exception as _e:
    print("[part133] mw:", str(_e)[:100])

print("[part133] v%s Telegram %s on the home nav, GitHub link %s" % (VERSION, _TG_LINK, _GITHUB_LINK))

# part133.py — nav: Telegram bot + fix GitHub org link (free forever)
VERSION = "3.0.4"
app.version = VERSION
app.openapi_schema = None

_TG = "https://t.me/Gotvibesolbot"
_GH = "https://github.com/TVibe-signal/signal-api"
_X = "https://x.com/realTVibe"

# Prefer replacing known HOME_HTML if present
_html = globals().get("HOME_HTML")
if isinstance(_html, str) and "Gotvibesolbot" not in _html:
    # Fix old repo slug if still present
    _html = _html.replace("https://github.com/TVibex402/signal-api", _GH)
    _html = _html.replace("github.com/TVibex402/signal-api", "github.com/TVibe-signal/signal-api")

    _pill_tg = (
        f'<a class="pill" href="{_TG}" target="_blank" rel="noopener noreferrer">'
        f'Telegram</a>'
    )
    # Insert Telegram after X pill (or after GitHub if no X)
    if f'href="{_X}"' in _html or "href=\"https://x.com/realTVibe\"" in _html:
        _html = _html.replace(
            f'<a class="pill" href="{_X}" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-x"/></svg>X</a>',
            f'<a class="pill" href="{_X}" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-x"/></svg>X</a>\n      {_pill_tg}',
            1,
        )
        if "Gotvibesolbot" not in _html:
            _html = _html.replace(
                'href="https://x.com/realTVibe" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-x"/></svg>X</a>',
                'href="https://x.com/realTVibe" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-x"/></svg>X</a>\n      ' + _pill_tg,
                1,
            )
    elif "GitHub</a>" in _html:
        _html = _html.replace("GitHub</a>", "GitHub</a>\n      " + _pill_tg, 1)

    # One-line agent hint under hero sub if missing
    _hint = (
        ' Check a mint on web, <a href="/mcp">MCP</a>, or '
        f'<a href="{_TG}" target="_blank" rel="noopener noreferrer">Telegram bot</a>'
        " — same verdict as <code>/omni</code>."
    )
    if "Gotvibesolbot" in _html and "Telegram bot" not in _html.split("hero")[0] if False else True:
        if "Telegram bot" not in _html and '<p class="sub">' in _html:
            # append once into first sub paragraph close
            _html = _html.replace(
                "Track record is public on <a href=\"/stats\">/stats</a>.",
                "Track record is public on <a href=\"/stats\">/stats</a>." + _hint,
                1,
            )

    HOME_HTML = _html
    globals()["HOME_HTML"] = _html

# Footer / agents page soft mentions via tiny middleware (optional, fail-safe)
class _TgLinkMW:
    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "GET":
            return await self.app(scope, receive, send)
        path = scope.get("path") or ""
        if path not in ("/", "/agents", "/index.html"):
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
                if start.get("status") == 200 and b"text/html" in hs.get(b"content-type", b""):
                    text = body.decode("utf-8", "ignore")
                    if "Gotvibesolbot" not in text and "realTVibe" in text:
                        pill = (
                            f'<a class="pill" href="{_TG}" target="_blank" '
                            f'rel="noopener noreferrer">Telegram</a>'
                        )
                        text2 = text.replace(
                            'href="https://x.com/realTVibe" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-x"/></svg>X</a>',
                            'href="https://x.com/realTVibe" target="_blank" rel="noopener noreferrer"><svg class="ic"><use href="#i-x"/></svg>X</a>\n      ' + pill,
                            1,
                        )
                        text2 = text2.replace(
                            "https://github.com/TVibex402/signal-api",
                            _GH,
                        )
                        if text2 != text:
                            body = text2.encode("utf-8")
            except Exception:
                pass
            hdrs = [(k, v) for k, v in start["headers"] if k.lower() != b"content-length"]
            hdrs.append((b"content-length", str(len(body)).encode()))
            await send({**start, "headers": hdrs})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, cap)


try:
    app.add_middleware(_TgLinkMW)
except Exception as e:
    print("[part133] mw:", str(e)[:100])

print("[part133] v%s Telegram %s on home nav (+ GitHub org fix)" % (VERSION, _TG))
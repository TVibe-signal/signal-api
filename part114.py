# part114.py - Telegram bot for TVibe Signal (webhook) - v2.92.0
# People send a Solana mint address to the bot (or use /check <mint>) and it replies with the verdict,
# the main reasons and links. It calls your own /omni in-process, so the answer is the same as on the website
# (including the signed attestation).
#
# Privacy: the bot only looks at messages that contain a Solana address or a command. It stores nothing about
# the chat, usernames or user ids (only in-memory counters at /telegram/status).
#
# Setup (details in the chat): env vars on Render
#   TELEGRAM_BOT_TOKEN       token from BotFather (never commit it, never paste it anywhere public)
#   TELEGRAM_WEBHOOK_SECRET  any long random string (letters, digits, _ or -); required
#   TELEGRAM_GROUP_AUTO=1    optional: also react to any mint address in group chats (needs BotFather /setprivacy -> Disable)
#   PUBLIC_BASE_URL          optional, default https://signal-api-24q4.onrender.com
# Loader line (after part112, before part7):  ("part114.py", 0, "SKIP"),
import asyncio
import html
import os
import re
import time
import types

from fastapi import Request
from fastapi.responses import JSONResponse

VERSION = "2.92.0"
app.version = VERSION
app.openapi_schema = None

_TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
_TG_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
_TG_GROUP_AUTO = os.environ.get("TELEGRAM_GROUP_AUTO", "0") == "1"
_TG_BASE = os.environ.get("PUBLIC_BASE_URL", "https://signal-api-24q4.onrender.com").rstrip("/")
_TG_MINT_RE = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
_TG_MIN_GAP_S = 3.0
_TG_CHAT_PER_MIN = 20
_TG_MAX_MINTS = 2

_TG = types.SimpleNamespace(username="", updates=0, replies=0, errors=0, rate_limited=0,
                            started=int(time.time()), last_user={}, chat_hits={})
_TG_TASKS = set()


def _tg_clean(e):
    return re.sub(r"bot\d+:[\w-]+", "bot<token>", str(e))[:160]


async def _tg_call(method, payload=None):
    import httpx
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://api.telegram.org/bot%s/%s" % (_TG_TOKEN, method), json=payload or {})
        return r.json()


async def _tg_omni(mint):
    """Call our own /omni in-process (same answer, same signing, same cache as the website)."""
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal",
                                 timeout=60) as c:
        r = await c.get("/omni", params={"mint": mint}, headers={"accept": "application/json"})
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, None


def _clip(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "\u2026"


def _tg_format(d, mint):
    dec = d.get("decision") or {}
    v = dec.get("verdict")
    label = {"ok": "Looks OK", "caution": "Use caution", "avoid": "High risk"}.get(v, str(v))
    icon = {"ok": "\U0001F7E2", "caution": "\U0001F7E1", "avoid": "\U0001F534"}.get(v, "\u26AA")
    head = "%s <b>%s</b> \u2014 %s" % (icon, html.escape(_clip(d.get("token") or "token", 40)), html.escape(label))
    if dec.get("risk_score") is not None:
        head += " \u00B7 risk %s/100" % html.escape(str(dec["risk_score"]))
    lines = [head]
    if d.get("summary"):
        lines.append(html.escape(_clip(d["summary"], 300)))
    for title, key, sym, n in (("Blockers", "blockers", "\u2716", 3), ("Cautions", "cautions", "\u26A0", 3),
                               ("Positives", "positives", "\u2714", 3), ("Unknowns", "unknowns", "?", 2)):
        arr = dec.get(key) or []
        if arr:
            lines.append("")
            lines.append("<b>%s</b>" % title)
            for x in arr[:n]:
                lines.append("%s %s" % (sym, html.escape(_clip(x if isinstance(x, str) else x.get("detail", x), 110))))
    att = d.get("attestation") or {}
    if att.get("sig"):
        lines.append("")
        lines.append("\u2714 Signed verdict #%s \u2014 check it at %s/verify" % (html.escape(str(att.get("chain_n"))), _TG_BASE))
    lines.append("")
    lines.append("<i>Heuristic, not financial advice. Data can be late or wrong.</i>")
    text = "\n".join(lines)
    return text if len(text) <= 3900 else text[:3890] + "\u2026"


def _tg_buttons(mint):
    return {"inline_keyboard": [[
        {"text": "Full report", "url": "%s/?mint=%s" % (_TG_BASE, mint)},
        {"text": "DexScreener", "url": "https://dexscreener.com/solana/%s" % mint},
    ]]}


HELP_TEXT = ("<b>TVibe Signal</b>\nSend me a Solana token address (or use <code>/check ADDRESS</code>) "
             "and I reply with a verdict and the reasons behind it.\n\n"
             "I only read messages that contain a Solana address or a command, and I do not store chats.\n"
             "<i>Heuristic, not financial advice.</i>")


def _tg_allowed(chat_id, user_id):
    now = time.time()
    key = (chat_id, user_id)
    if now - _TG.last_user.get(key, 0) < _TG_MIN_GAP_S:
        return False
    hits = [t for t in _TG.chat_hits.get(chat_id, []) if now - t < 60]
    if len(hits) >= _TG_CHAT_PER_MIN:
        _TG.chat_hits[chat_id] = hits
        return False
    hits.append(now)
    _TG.chat_hits[chat_id] = hits
    _TG.last_user[key] = now
    if len(_TG.last_user) > 5000:
        _TG.last_user.clear()
    if len(_TG.chat_hits) > 2000:
        _TG.chat_hits.clear()
    return True


async def _tg_send(chat_id, text, thread, reply_to, buttons=None):
    p = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if thread:
        p["message_thread_id"] = thread
    if reply_to:
        p["reply_to_message_id"] = reply_to
        p["allow_sending_without_reply"] = True
    if buttons:
        p["reply_markup"] = buttons
    res = await _tg_call("sendMessage", p)
    _TG.replies += 1
    return res


async def _tg_username():
    if not _TG.username:
        try:
            r = await _tg_call("getMe")
            _TG.username = ((r or {}).get("result") or {}).get("username", "") or ""
        except Exception as e:
            print("[part114] getMe:", _tg_clean(e))
    return _TG.username


async def _tg_handle(upd):
    msg = upd.get("message")
    if not isinstance(msg, dict):
        return
    text = msg.get("text") or msg.get("caption") or ""
    sender = msg.get("from") or {}
    chat = msg.get("chat") or {}
    chat_id, ctype = chat.get("id"), chat.get("type")
    if not text or sender.get("is_bot") or chat_id is None:
        return
    thread = msg.get("message_thread_id") if msg.get("is_topic_message") else None
    reply_to = msg.get("message_id")
    is_private = ctype == "private"
    uname = (await _tg_username()).lower()

    cmd, rest = "", text
    if text.startswith("/"):
        first, _, rest = text.partition(" ")
        cmd = first.split("@")[0].lower()
        if "@" in first and uname and first.split("@", 1)[1].lower() != uname:
            return  # command meant for another bot
    if cmd in ("/start", "/help"):
        await _tg_send(chat_id, HELP_TEXT, thread, reply_to)
        return

    mentioned = bool(uname) and ("@" + uname) in text.lower()
    replied_to_us = bool(uname) and (((msg.get("reply_to_message") or {}).get("from") or {}).get("username", "")
                                     .lower() == uname)
    wants = bool(cmd in ("/check", "/c", "/signal")) or is_private or mentioned or replied_to_us or _TG_GROUP_AUTO
    if not wants:
        return
    mints = _TG_MINT_RE.findall(rest if cmd else text)
    if not mints:
        if cmd in ("/check", "/c", "/signal"):
            await _tg_send(chat_id, "Send a Solana token address after the command, for example <code>/check ADDRESS</code>.",
                           thread, reply_to)
        return
    if not _tg_allowed(chat_id, sender.get("id")):
        _TG.rate_limited += 1
        return
    seen = []
    for m in mints:
        if m not in seen:
            seen.append(m)
    for mint in seen[:_TG_MAX_MINTS]:
        try:
            await _tg_call("sendChatAction", {"chat_id": chat_id, "action": "typing",
                                              **({"message_thread_id": thread} if thread else {})})
            status, d = await _tg_omni(mint)
            if status == 429:
                await _tg_send(chat_id, "I am busy right now. Please try again in a minute.", thread, reply_to)
            elif status != 200 or not isinstance(d, dict) or not (d.get("decision") or {}).get("verdict"):
                await _tg_send(chat_id, "I could not read <code>%s\u2026</code> as a token. Check the address." % html.escape(mint[:6]),
                               thread, reply_to)
            else:
                await _tg_send(chat_id, _tg_format(d, mint), thread, reply_to, _tg_buttons(mint))
        except Exception as e:
            _TG.errors += 1
            print("[part114] reply failed:", _tg_clean(e))


@app.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request):
    if not _TG_TOKEN or not _TG_SECRET:
        return JSONResponse({"ok": False, "error": "not configured"}, status_code=503)
    if request.headers.get("x-telegram-bot-api-secret-token", "") != _TG_SECRET:
        return JSONResponse({"ok": False}, status_code=403)
    try:
        upd = await request.json()
    except Exception:
        return {"ok": True}
    _TG.updates += 1
    t = asyncio.create_task(_tg_handle(upd))  # answer Telegram at once; the reply is sent when ready
    _TG_TASKS.add(t)
    t.add_done_callback(_TG_TASKS.discard)
    return {"ok": True}


@app.get("/telegram/status", include_in_schema=False)
async def telegram_status():
    return {
        "bot_token_set": bool(_TG_TOKEN), "webhook_secret_set": bool(_TG_SECRET),
        "ready": bool(_TG_TOKEN and _TG_SECRET), "group_auto_detect": _TG_GROUP_AUTO,
        "webhook_url_to_register": _TG_BASE + "/telegram/webhook",
        "updates_received": _TG.updates, "replies_sent": _TG.replies, "rate_limited": _TG.rate_limited,
        "errors": _TG.errors, "since": _TG.started, "version": VERSION,
    }


print("[part114] v%s Telegram bot webhook (%s)" % (VERSION, "ready" if (_TG_TOKEN and _TG_SECRET) else "set TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET"))

# part115.py - Telegram UX polish (after part114) (v2.92.3, reviewed)
# Adds /status and a clearer /help, and turns "API busy" statuses into a friendly message.
# Review fixes vs v2.92.2:
#   - "\~30s" was an invalid escape (SyntaxWarning)
#   - the old wrapper swapped the global _tg_omni during every message; with several messages at once it could
#     restore the wrong function. The wrapper is now installed once.
#   - /status, /help and /start also answered commands meant for OTHER bots ("/start@otherbot") and were not
#     rate-limited. Both fixed. /status no longer shows internal counters to everyone.
#   - removed unused code
VERSION = "2.92.3"
app.version = VERSION
app.openapi_schema = None

import html

_HELP_115 = (
    "<b>TVibe Signal</b>\n"
    "\u2022 <code>/check ADDRESS</code> \u2014 verdict and risk for a Solana token\n"
    "\u2022 In a private chat you can also paste the address\n"
    "\u2022 <code>/status</code> \u2014 is the bot ready\n"
    "\u2022 <code>/help</code> \u2014 this message\n\n"
    "I only read messages that contain a Solana address or a command, and I do not store chats.\n"
    "<i>Heuristic only, not financial advice.</i>"
)

_prev_handle_115 = globals().get("_tg_handle")
_prev_omni_115 = globals().get("_tg_omni")
_prev_send_115 = globals().get("_tg_send")

if callable(_prev_handle_115) and callable(_prev_omni_115) and callable(_prev_send_115):

    async def _tg_omni(mint):
        status, d = await _prev_omni_115(mint)
        if status in (502, 503, 504):
            return 429, None  # part114 then says "I am busy right now, try again in a minute"
        return status, d

    async def _tg_send(chat_id, text, thread, reply_to, buttons=None):
        t = str(text or "")
        low = t.lower()
        if "could not read" in low and "as a token" in low:
            t = ("No verdict for that address right now. The data may be incomplete or the service busy. "
                 "Try again in a minute; the address may still be valid.")
        if buttons is not None:
            return await _prev_send_115(chat_id, t, thread, reply_to, buttons)
        return await _prev_send_115(chat_id, t, thread, reply_to)

    async def _tg_handle(upd):
        try:
            msg = upd.get("message") if isinstance(upd, dict) else None
            if isinstance(msg, dict) and not (msg.get("from") or {}).get("is_bot"):
                text = str(msg.get("text") or "").strip()
                chat = msg.get("chat") or {}
                chat_id = chat.get("id")
                first = text.split(" ", 1)[0].lower() if text.startswith("/") else ""
                cmd, _, target = first.partition("@")
                if chat_id is not None and cmd in ("/status", "/help", "/start"):
                    uname = (await _tg_username()).lower() if "_tg_username" in globals() else ""
                    if target and uname and target != uname:
                        return  # meant for another bot
                    allowed = globals().get("_tg_allowed")
                    if callable(allowed) and not allowed(chat_id, (msg.get("from") or {}).get("id")):
                        return
                    thread = msg.get("message_thread_id") if msg.get("is_topic_message") else None
                    if cmd == "/status":
                        ready = bool(globals().get("_TG_TOKEN") and globals().get("_TG_SECRET"))
                        body = "<b>Bot status</b>\nready: %s\nversion: %s" % (ready, html.escape(VERSION))
                    else:
                        body = _HELP_115
                    await _prev_send_115(chat_id, body, thread, msg.get("message_id"))
                    return
        except Exception as e:
            print("[part115] pre-handler:", str(e)[:100])
        await _prev_handle_115(upd)

    globals()["_tg_omni"] = _tg_omni
    globals()["_tg_send"] = _tg_send
    globals()["_tg_handle"] = _tg_handle
    print("[part115] Telegram UX: /status /help + friendlier busy and no-verdict messages")
else:
    print("[part115] part114 handlers not found - skipped (load part114 before part115)")

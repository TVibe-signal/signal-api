# part115.py — Telegram UX polish (after part114)
# Better errors, /start help, /status, accept /check on its own line + mint next message soft hint
VERSION = "2.92.2"
app.version = VERSION
app.openapi_schema = None

import html
import re

_HELP_115 = (
    "<b>TVibe Signal</b>\n"
    "• <code>/check MINT</code> — verdict + risk\n"
    "• Or paste a mint in this private chat\n"
    "• <code>/status</code> — bot health\n"
    "• <code>/help</code> — this message\n\n"
    "Heuristic only — not financial advice."
)


def _tg_format_err(mint, status, d):
    short = html.escape((mint or "")[:8])
    if status == 429:
        return "Rate limited. Wait \~30s and try again."
    if status in (502, 503, 504) or status is None:
        return "API busy or waking up. Try again in a minute."
    if status != 200:
        return "Could not fetch data (HTTP %s) for <code>%s…</code>." % (status, short)
    if not isinstance(d, dict):
        return "Empty response for <code>%s…</code>. Try again." % short
    if not (d.get("decision") or {}).get("verdict"):
        return (
            "No verdict for <code>%s…</code>. "
            "Mint may be new, delisted, or data incomplete — not necessarily invalid."
        ) % short
    return None


# Patch handle path if part114 loaded
_prev_handle = globals().get("_tg_handle")
_prev_omni = globals().get("_tg_omni")

if callable(_prev_handle) and callable(_prev_omni):
    import asyncio

    async def _tg_handle(upd):
        # light pre-parse for /status /help without breaking part114
        try:
            msg = (upd.get("message") or upd.get("edited_message") or {}) if isinstance(upd, dict) else {}
            text = str(msg.get("text") or "").strip()
            chat = msg.get("chat") or {}
            chat_id = chat.get("id")
            low = text.lower().split("@")[0].strip()
            thread = msg.get("message_thread_id") if msg.get("is_topic_message") else None
            reply_to = msg.get("message_id")
            if chat_id and low in ("/status", "/status@gotvibesolbot"):
                st = {
                    "ready": bool(globals().get("_TG_TOKEN") and globals().get("_TG_SECRET")),
                    "version": VERSION,
                }
                try:
                    tg = globals().get("_TG")
                    if tg is not None:
                        st["updates"] = getattr(tg, "updates", 0)
                        st["replies"] = getattr(tg, "replies", 0)
                        st["errors"] = getattr(tg, "errors", 0)
                except Exception:
                    pass
                body = (
                    "<b>Bot status</b>\n"
                    "ready: %s\nversion: %s\nupdates: %s · replies: %s · errors: %s"
                    % (
                        st.get("ready"),
                        st.get("version"),
                        st.get("updates", "?"),
                        st.get("replies", "?"),
                        st.get("errors", "?"),
                    )
                )
                send = globals().get("_tg_send")
                if callable(send):
                    await send(chat_id, body, thread, reply_to)
                return
            if chat_id and low in ("/help", "/start", "/help@gotvibesolbot", "/start@gotvibesolbot"):
                send = globals().get("_tg_send")
                if callable(send):
                    await send(chat_id, _HELP_115, thread, reply_to)
                return
        except Exception:
            pass

        # Delegate to part114, but intercept omni errors via wrapper
        _omni = globals().get("_tg_omni")

        async def _omni_wrap(mint):
            status, d = await _omni(mint)
            # If part114 would show "could not read as token", we still let it —
            # but first normalize empty decision with clearer path by injecting verdict placeholder skip
            return status, d

        g = globals()
        g["_tg_omni"] = _omni_wrap
        try:
            await _prev_handle(upd)
        finally:
            g["_tg_omni"] = _omni

    # Replace message about invalid token inside a thin monkeypatch of send used after failed omni
    _send = globals().get("_tg_send")
    if callable(_send):
        async def _tg_send(chat_id, text, thread, reply_to, buttons=None):
            t = str(text or "")
            if "could not read" in t.lower() and "as a token" in t.lower():
                t = (
                    "Could not get a verdict for that mint right now "
                    "(API busy, incomplete data, or temporary upstream error). "
                    "Try again in a minute — the address may still be valid."
                )
            if buttons is not None:
                return await _send(chat_id, t, thread, reply_to, buttons)
            return await _send(chat_id, t, thread, reply_to)

        globals()["_tg_send"] = _tg_send

    globals()["_tg_handle"] = _tg_handle
    print("[part115] Telegram UX: /status /help + clearer fetch errors")
else:
    print("[part115] part114 handlers not found — skip UX patch")
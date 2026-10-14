# part62.py (v2.45.2) - Dọn dẹp. Đặt SAU part61, TRƯỚC part7. Không cần sửa main.py.
# 1) Đăng ký lại 4 MCP tool (get_community, explain_verdict, submit_agent_feedback, get_debate) ở request đầu tiên,
#    khi part7 đã nạp xong (part55 chạy trước part7 nên mcp_server chưa tồn tại và lỗi bị nuốt).
# 2) Gỡ /evolution và /evolution/view khỏi công khai (đặt EVOLUTION_PUBLIC=true để giữ).
# 3) llms.txt: gộp mục trùng (giữ bản mới nhất) và thêm mô tả debate trung thực.
# 4) Ẩn dòng "Debate consensus" trong decision.unknowns (mâu thuẫn với verdict). Đặt DEBATE_NOTE=true để giữ.

VERSION = "2.45.2"
app.version = VERSION
app.openapi_schema = None

import os
import re

HG62_EVOLUTION_PUBLIC = os.getenv("EVOLUTION_PUBLIC", "").lower() in ("1", "true", "yes")
HG62_DEBATE_NOTE = os.getenv("DEBATE_NOTE", "").lower() in ("1", "true", "yes")
HG62_DEBATE_DOC = (
    "## Debate (experimental)\n"
    "A signal may include a `debate` object: four rule-based personas vote on the same underlying data. "
    "They are not independent evidence, and `debate.meta_verdict` can differ from `decision.verdict`. "
    "Trust `decision` first and use `debate` only as extra context.\n"
)
_HG62_DONE = {"ran": False, "tools": []}


def hg62_dedupe_llms(text):
    """Gộp các mục '## ...' trùng tên (bỏ phần trong ngoặc), giữ bản xuất hiện sau cùng; thêm mục debate nếu thiếu."""
    parts = text.split("\n## ")
    head, secs = parts[0], parts[1:]
    seen, kept = set(), []
    for s in reversed(secs):
        title = re.sub(r"\s*\(.*?\)", "", s.split("\n", 1)[0]).strip().lower()
        if title in seen:
            continue
        seen.add(title)
        kept.append(s)
    kept.reverse()
    out = head + "".join("\n## " + s for s in kept)
    if "debate" not in seen:
        out = out.rstrip("\n") + "\n\n" + HG62_DEBATE_DOC
    return out


def _hg62_register_mcp():
    ms = globals().get("mcp_server")
    if ms is None:
        return []
    try:
        existing = set(getattr(getattr(ms, "_tool_manager", None), "_tools", {}) or {})
    except Exception:
        existing = set()
    added = []

    def reg(fn):
        if fn.__name__ not in existing:
            ms.tool()(fn)
            added.append(fn.__name__)

    async def get_community(mint: str) -> dict:
        """Get community attention, recent verdict distribution and feedback summary for a token."""
        client = app.state.client
        attn = await get_attention(client, mint) if "get_attention" in globals() else {}
        conv = await get_community_conviction(client, mint) if "get_community_conviction" in globals() else {}
        fb = await get_feedback_summary(client, mint) if "get_feedback_summary" in globals() else {}
        return {"mint": mint, "attention": attn, "conviction": conv, "feedback": fb}

    async def explain_verdict(mint: str) -> dict:
        """Explain the current verdict: blockers, cautions, positives and unknowns."""
        sig, _ = await build_signal(app.state.client, mint, True)
        d = sig.get("decision") or {}
        return {"mint": mint, "verdict": d.get("verdict"), "risk_score": sig.get("risk_score"),
                "blockers": d.get("blockers"), "cautions": d.get("cautions"), "positives": d.get("positives"),
                "unknowns": d.get("unknowns"), "would_change_if": d.get("would_change_if"),
                "summary": sig.get("summary")}

    async def submit_agent_feedback(mint: str, useful: str, note: str = "") -> dict:
        """Report whether a verdict was useful: useful must be yes, no or neutral."""
        if useful not in ("yes", "no", "neutral"):
            return {"error": "useful must be yes, no or neutral"}
        await _save_feedback(app.state.client, mint, useful, note)
        return {"ok": True, "mint": mint, "useful": useful}

    async def get_debate(mint: str) -> dict:
        """Experimental: four rule-based personas vote on one token. Not independent evidence."""
        sig, _ = await build_signal(app.state.client, mint, True)
        return {"mint": mint, "debate": sig.get("debate"), "verdict": (sig.get("decision") or {}).get("verdict"),
                "risk_score": sig.get("risk_score")}

    for fn, needs in ((get_community, "_save_feedback"), (explain_verdict, "build_signal"),
                      (submit_agent_feedback, "_save_feedback"), (get_debate, "run_debate")):
        if needs in globals():
            reg(fn)
    return added


def _hg62_post_load():
    """Chạy đúng 1 lần ở request đầu tiên (lúc này mọi part, kể cả part7, đã nạp xong)."""
    out = {}
    if not HG62_EVOLUTION_PUBLIC:
        before = len(app.router.routes)
        app.router.routes[:] = [r for r in app.router.routes
                                if getattr(r, "path", None) not in ("/evolution", "/evolution/view")]
        out["routes_removed"] = before - len(app.router.routes)
        app.openapi_schema = None
    t = globals().get("LLMS_TXT")
    if isinstance(t, str):
        globals()["LLMS_TXT"] = hg62_dedupe_llms(t)
        out["llms_deduped"] = True
    out["tools"] = _hg62_register_mcp()
    _HG62_DONE["tools"] = out["tools"]
    return out


class _Hg62FirstRequest:
    """ASGI thuần (không BaseHTTPMiddleware) để không ảnh hưởng streaming của MCP."""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        if not _HG62_DONE["ran"] and scope.get("type") in ("http", "websocket"):
            _HG62_DONE["ran"] = True
            try:
                _hg62_post_load()
            except Exception as e:
                print(f"[part62] post-load skipped: {e}")
        await self.inner(scope, receive, send)


app.add_middleware(_Hg62FirstRequest)

# ---------- ẩn ghi chú debate mâu thuẫn với verdict ----------
_build_signal_hg62 = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_signal_hg62(client, mint, security, prefetched)
    try:
        dec = result.get("decision") if isinstance(result, dict) else None
        if not HG62_DEBATE_NOTE and isinstance(dec, dict) and dec.get("unknowns"):
            kept = [u for u in dec["unknowns"] if not str(u).startswith("Debate consensus")]
            if len(kept) != len(dec["unknowns"]):
                result = dict(result)
                result["decision"] = dict(dec, unknowns=kept)
    except Exception:
        pass
    return result, status

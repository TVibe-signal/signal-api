# ---------- v2.54.1: Autonomic Loop + Journal Publish + MCP Omni ----------
VERSION = "2.54.1"
app.version = VERSION
app.openapi_schema = None

import asyncio
import json
import time
from typing import Optional

AUTO_LOOP = os.getenv("SI_AUTO_LOOP", "true").lower() in ("1", "true", "yes")
AUTO_EVERY = int(os.getenv("SI_AUTO_EVERY_S", "900"))  # 15 min opportunistic
_last_auto = 0

async def autonomic_cycle(client) -> dict:
    """
    P1: seed-ish focus → light signal pulls → entity refresh → report.
    Does not replace resolver; amplifies learning surface.
    """
    summary = {"ok": False, "focus_pulled": 0, "errors": 0}
    if not PRED_ENABLED or not client:
        return summary
    try:
        # 1) Focus list from entity
        focus = []
        try:
            raw = await redis_get(client, "si:entity:focus")
            if raw:
                focus = json.loads(raw) or []
        except Exception:
            pass
        if not focus and "refresh_entity" in globals():
            ent = await refresh_entity(client)
            focus = (ent or {}).get("focus") or []

        # 2) Pull a few focus mints through signal pipeline (generates events + learning hooks)
        for item in focus[:4]:
            m = item.get("mint") if isinstance(item, dict) else None
            if not m or not MINT_RE.match(m):
                continue
            try:
                await build_signal(client, m, True)
                summary["focus_pulled"] += 1
                await asyncio.sleep(0.35)
            except Exception:
                summary["errors"] += 1

        # 3) Entity + report
        if "refresh_entity" in globals():
            await refresh_entity(client)
        if "maybe_write_report" in globals():
            await maybe_write_report(client)

        # 4) Event marker
        if "si_emit" in globals():
            await si_emit(client, "autonomic_cycle", None, {
                "focus_pulled": summary["focus_pulled"],
                "errors": summary["errors"],
            })

        summary["ok"] = True
    except Exception as e:
        summary["error"] = str(e)[:160]
    return summary

@app.post("/si/autonomic/run", tags=["entity"], include_in_schema=False)
async def run_autonomic(request: Request):
    """Manual trigger for autonomic cycle."""
    client = request.app.state.client
    return await autonomic_cycle(client)

# Opportunistic auto loop on traffic
_build_prev_auto = build_signal

async def build_signal(client, mint, security, prefetched=None):
    global _last_auto
    result, status = await _build_prev_auto(client, mint, security, prefetched)
    try:
        if AUTO_LOOP and time.time() - _last_auto > AUTO_EVERY:
            _last_auto = time.time()
            # fire and forget style: short cycle only
            await autonomic_cycle(client)
    except Exception:
        pass
    return result, status

# -------------------- Journal publish (public narrative) --------------------

@app.get("/si/journal/public", tags=["product"])
async def journal_public(request: Request, limit: int = 7):
    """Public-facing identity journal (safe subset)."""
    client = request.app.state.client
    limit = max(1, min(limit, 20))
    entries = []
    try:
        if "si_journal" in globals():
            # call underlying storage
            pass
        if PRED_ENABLED:
            res = await redis_pipe(client, [["LRANGE", "si:entity:journal", 0, limit - 1]])
            for raw in (res or [[]])[0] or []:
                try:
                    e = json.loads(raw)
                    entries.append({
                        "day": e.get("day"),
                        "line": e.get("line"),
                        "ts": e.get("ts"),
                    })
                except Exception:
                    continue
    except Exception:
        pass
    return {
        "title": "What I learned recently",
        "entries": entries,
        "note": "Self-reflection log of the SI entity — heuristic, not advice",
    }

# -------------------- MCP: omni + core --------------------

def _register_omni_mcp():
    try:
        ms = globals().get("mcp_server")
        if ms is None:
            return
        existing = set()
        try:
            existing = set(getattr(getattr(ms, "_tool_manager", None), "_tools", {}) or {})
        except Exception:
            pass

        async def omni(mint: str) -> dict:
            """One-call full SI signal: decision, debate, causal, CF, time-to-death, pre-rug."""
            return await build_omni(app.state.client, mint)

        async def si_core_tool() -> dict:
            """Return the SI entity core state (mood, beliefs, integrity, focus)."""
            if "refresh_entity" in globals():
                return await refresh_entity(app.state.client)
            raw = await redis_get(app.state.client, "si:entity:core")
            return json.loads(raw) if raw else {}

        for fn in (omni, si_core_tool):
            if fn.__name__ not in existing:
                try:
                    ms.tool()(fn)
                except Exception:
                    pass
    except Exception as e:
        print(f"[part75] MCP register skip: {e}")

try:
    import asyncio as _aio
    loop = _aio.get_event_loop()
    loop.call_later(4, _register_omni_mcp)
except Exception:
    _register_omni_mcp()

# llms.txt hint
if "LLMS_TXT" in globals():
    LLMS_TXT += """

## Omni (recommended for agents)
GET /omni?mint=ADDRESS
One call returns decision, debate, community, causal, DNA, counterfactual, time_to_death, pre_rug patterns, and would_change_my_mind.
Prefer /omni over multiple separate calls when you need full SI context.

MCP tools: omni(mint), si_core_tool()
Public journal: GET /si/journal/public
"""

print(f"[part75] v{VERSION} Autonomic loop + journal public + MCP omni loaded")
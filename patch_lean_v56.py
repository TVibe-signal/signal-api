"""patch_lean_v56.py — lean restore after v55 HTML hijack.

Upload next to app.py. Append at VERY END of app.py (after v55):

    try:
        import patch_lean_v56
        patch_lean_v56.apply(g if "g" in dir() and isinstance(g, dict) else globals())
        print("[loader] patch_lean_v56 applied")
    except Exception as _e56:
        print(f"[loader] patch_lean_v56 NOT applied: {_e56}")

What it does (small surface):
1) GET /omni?view=agent or Accept: application/json → real JSON gate (bypass v55 HTML)
2) /stats, /skill.json, /llms.txt, /mcp/tools, agent-card → core app (not 404 under wrap)
3) Soft /stats if missing
4) Does NOT remove web HTML /pro for humans
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs

VERSION = "3.0.31-lean-fix-omni-422"
BASE = (os.environ.get("PUBLIC_BASE_URL") or "https://signal-api-24q4.onrender.com").rstrip("/")


def _unwrap(app):
    seen = set()
    cur = app
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        inner = getattr(cur, "inner", None) or getattr(cur, "app", None)
        if inner is None or inner is cur:
            break
        # Starlette/FastAPI have .router — stop there
        if hasattr(cur, "router") and hasattr(cur, "routes"):
            return cur
        cur = inner
    if hasattr(app, "router"):
        return app
    return cur or app


def apply(G: dict) -> None:
    outer = G.get("app")
    if outer is None:
        print("[lean-v56] no app"); return

    try:
        from fastapi import Query, Request
        from fastapi.responses import JSONResponse, PlainTextResponse
    except Exception as e:
        print("[lean-v56] fastapi missing", e); return

    core = _unwrap(outer)
    # Prefer object with router.routes
    if not hasattr(core, "router"):
        # walk modules
        for name in ("app", "__main__", "main"):
            mod = sys.modules.get(name)
            a = getattr(mod, "app", None) if mod else None
            if a is not None and hasattr(_unwrap(a), "router"):
                core = _unwrap(a)
                break

    build_omni = G.get("build_omni")
    stats_report = G.get("stats_report")
    MINT_RE = G.get("MINT_RE")

    def _agent_view(pkt: dict) -> dict:
        if not isinstance(pkt, dict):
            pkt = {}
        dec = pkt.get("decision") if isinstance(pkt.get("decision"), dict) else {}
        filt = pkt.get("filter") if isinstance(pkt.get("filter"), dict) else {}
        action = str(pkt.get("action") or dec.get("verdict") or pkt.get("verdict") or "review").lower()
        if action in ("ok", "pass"):
            action_n = "pass"
        elif action in ("avoid", "skip", "sell"):
            action_n = "skip"
        else:
            action_n = "review"
        unknowns = list(pkt.get("unknowns") or dec.get("unknowns") or [])[:8]
        tips = []
        if unknowns:
            tips.append("Clear unknowns before sizing.")
        if filt.get("pass") is False or action_n != "pass":
            tips.append("filter.pass false — no size until gate clears.")
        tips.append("Re-fetch when valid_for_s expires. NFA.")
        return {
            "mint": pkt.get("mint"),
            "action": action_n,
            "verdict": pkt.get("verdict") or dec.get("verdict") or action_n,
            "filter": {"pass": bool(filt.get("pass")) if filt else action_n == "pass"},
            "confidence": pkt.get("confidence") or dec.get("confidence"),
            "risk_score": pkt.get("risk_score") or pkt.get("score"),
            "blockers": (pkt.get("blockers") or dec.get("blockers") or [])[:8],
            "cautions": (pkt.get("cautions") or dec.get("cautions") or [])[:8],
            "unknowns": unknowns,
            "what_would_change": tips[:3],
            "valid_for_s": pkt.get("valid_for_s") or 30,
            "rules_version": pkt.get("rules_version") or G.get("RULES_VERSION"),
            "version": VERSION,
            "nfa": True,
            "ok_is_not_a_buy_signal": True,
        }

    # --- register lean routes on core FastAPI ---
    try:
        routes = list(getattr(core.router, "routes", []) or [])
        # drop lean duplicates
        core.router.routes[:] = [
            r for r in routes
            if getattr(r, "path", None) not in {
                "/omni", "/stats", "/llms.txt", "/skill.json",
                "/.well-known/agent-card.json", "/mcp/tools", "/agent/batch",
            }
            or getattr(r, "endpoint", None) and getattr(r.endpoint, "_lean56", False)
        ]
    except Exception as e:
        print("[lean-v56] route drop", e)

    @core.get("/omni", tags=["product"])
    async def omni_lean(
        request: Request,
        mint: str = Query(default="", max_length=64),
        view: str = Query("full"),
    ):
        mint = (mint or "").strip()
        if not mint:
            return JSONResponse({"error": "need mint", "omni": True, "nfa": True}, status_code=400)
        client = getattr(request.app.state, "client", None)
        # if core was unwrapped, state may be on outer — try request.app
        if client is None:
            client = getattr(getattr(request, "app", None), "state", None)
            client = getattr(client, "client", None) if client else None
        pkt = None
        if callable(build_omni) and client is not None:
            try:
                pkt = await build_omni(client, mint)
            except Exception as e:
                pkt = {"mint": mint, "verdict": "caution", "action": "review", "error": str(e)[:120], "nfa": True}
        if not isinstance(pkt, dict):
            pkt = {"mint": mint, "verdict": "caution", "action": "review", "unknowns": ["omni_engine_unavailable"], "nfa": True}
        if (view or "").lower() in ("agent", "compact", "action"):
            return JSONResponse(_agent_view(pkt))
        # Prefer JSON always for Accept
        accept = (request.headers.get("accept") or "").lower()
        if "text/html" in accept and "application/json" not in accept and (view or "full") == "full":
            # let humans use /pro for HTML; still return JSON for API clients default
            pass
        pkt = dict(pkt)
        pkt.setdefault("what_would_change", _agent_view(pkt).get("what_would_change"))
        pkt["nfa"] = True
        pkt["version"] = pkt.get("version") or VERSION
        return JSONResponse(pkt)

    omni_lean._lean56 = True

    @core.get("/stats", tags=["trust"])
    async def stats_lean(request: Request):
        import inspect
        out = {"available": False, "nfa": True, "version": VERSION}
        state = getattr(request.app, "state", None)
        httpx_client = getattr(state, "client", None) if state else None
        fns = []
        if callable(stats_report):
            fns.append(("stats_report", stats_report))
        for n in ("stats_with_bias", "compute_stats", "build_stats"):
            fn = G.get(n)
            if callable(fn):
                fns.append((n, fn))
        last = None
        for name, fn in fns:
            for call in (
                (lambda f=fn: f(httpx_client)) if httpx_client else None,
                (lambda f=fn: f(request)),
                (lambda f=fn: f(request=request)),
                (lambda f=fn: f(client=httpx_client)) if httpx_client else None,
                (lambda f=fn: f()),
            ):
                if call is None:
                    continue
                try:
                    res = call()
                    if inspect.isawaitable(res):
                        res = await res
                    if isinstance(res, dict) and (res.get("by_verdict") or res.get("resolved") is not None or res.get("available")):
                        res = dict(res)
                        res["available"] = True
                        res["stats_source"] = name
                        res["nfa"] = True
                        return JSONResponse(res)
                except Exception as e:
                    last = f"{name}: {e}"
                    continue
        out["error"] = "stats_partial"
        out["detail"] = last
        out["hint"] = "Seed via /seed or cron; compare within rules_version"
        return JSONResponse(out)

    stats_lean._lean56 = True

    _LLMS = f"""# TVibe Signal
> Free Solana mint risk gate for agents. NFA.

## Primary
- GET {BASE}/omni?mint=<MINT>&view=agent
- GET {BASE}/pro_json?mint=<MINT>
- GET {BASE}/stats
- MCP: {BASE}/mcp
- Skill: {BASE}/skill.json

## Claude
{{"mcpServers":{{"tvibe":{{"url":"{BASE}/mcp"}}}}}}

## Rules
1. action: pass | review | skip
2. unknowns non-empty → do not size
3. pass is NOT a buy order
"""

    @core.get("/llms.txt", include_in_schema=False)
    async def llms_lean():
        return PlainTextResponse(_LLMS)
    llms_lean._lean56 = True

    _SKILL = {
        "name": "tvibe-signal",
        "title": "TVibe Signal",
        "version": VERSION,
        "pricing": "free",
        "service_url": BASE,
        "endpoints": [
            {"method": "GET", "path": "/omni", "query": "mint,view=agent"},
            {"method": "GET", "path": "/pro_json", "query": "mint"},
            {"method": "GET", "path": "/stats"},
        ],
        "mcp": {"url": f"{BASE}/mcp"},
        "nfa": True,
    }

    @core.get("/skill.json", include_in_schema=False)
    async def skill_lean():
        return JSONResponse(_SKILL)
    skill_lean._lean56 = True

    @core.get("/.well-known/agent-card.json", include_in_schema=False)
    async def card_lean():
        return JSONResponse({
            "name": "TVibe Signal",
            "version": VERSION,
            "url": BASE,
            "skills": [
                {"id": "omni", "endpoint": f"{BASE}/omni?view=agent"},
                {"id": "pro_json", "endpoint": f"{BASE}/pro_json"},
                {"id": "stats", "endpoint": f"{BASE}/stats"},
            ],
            "pricing": "free",
            "nfa": True,
        })
    card_lean._lean56 = True

    @core.get("/mcp/tools", tags=["mcp"])
    async def tools_lean():
        return {
            "tools": [
                {"name": "omni", "url": f"{BASE}/omni?mint=<MINT>&view=agent"},
                {"name": "pro_json", "url": f"{BASE}/pro_json?mint=<MINT>"},
                {"name": "stats", "url": f"{BASE}/stats"},
            ],
            "version": VERSION,
            "nfa": True,
        }
    tools_lean._lean56 = True

    # --- ASGI gate: agent JSON bypasses v55 HTML for /omni ---
    class _LeanGate:
        def __init__(self, outer_app, core_app):
            self.outer = outer_app
            self.core = core_app

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http":
                path = scope.get("path") or ""
                qs = (scope.get("query_string") or b"").decode("utf-8", "ignore")
                headers = {
                    (k.decode() if isinstance(k, bytes) else k).lower():
                    (v.decode() if isinstance(v, bytes) else v)
                    for k, v in (scope.get("headers") or [])
                }
                accept = headers.get("accept", "")
                q = parse_qs(qs)
                view = (q.get("view") or [""])[0].lower()
                want_json = (
                    view in ("agent", "compact", "action")
                    or "application/json" in accept
                    or headers.get("x-tvibe-client") == "agent"
                )
                api_paths = {
                    "/omni", "/stats", "/llms.txt", "/skill.json",
                    "/.well-known/agent-card.json", "/mcp/tools", "/agent/batch",
                    "/health", "/ping",
                }
                # /omni HTML only when explicitly browser-ish and not agent
                if path.rstrip("/") == "/omni" and want_json:
                    await self.core(scope, receive, send)
                    return
                if path.rstrip("/") in api_paths or path in api_paths:
                    await self.core(scope, receive, send)
                    return
            await self.outer(scope, receive, send)

    gated = _LeanGate(outer, core)
    G["app"] = gated
    for mod_name in ("app", "__main__", "main"):
        mod = sys.modules.get(mod_name)
        if mod is not None and hasattr(mod, "app"):
            try:
                setattr(mod, "app", gated)
            except Exception:
                pass

    try:
        G["VERSION"] = VERSION
        if hasattr(core, "version"):
            core.version = VERSION
        if hasattr(core, "openapi_schema"):
            core.openapi_schema = None
    except Exception:
        pass

    print(f"[lean-v56] ready {VERSION} — omni JSON for agents, stats/skill/llms restored")


if __name__ == "__main__":
    print("apply(G) from app.py end only")

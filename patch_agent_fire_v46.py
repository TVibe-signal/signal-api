"""patch_agent_fire_v46.py — P0/P1 agent pack for TVibe.

Apply AFTER loader + PRO + rescue:
    import patch_agent_fire_v46
    patch_agent_fire_v46.apply(g)   # g = shared namespace dict
  or at end of app.py:
    import patch_agent_fire_v46 as _p46
    _p46.apply(globals())

Does:
  1) Fix /stats (request arg bug → full track-record when possible)
  2) GET /llms.txt agent-first (3 lines Claude/Cursor + omni)
  3) GET /skill.json + /.well-known/agent-card.json
  4) Enrich /omni?view=agent: what_would_change, stable action contract
  5) MCP tool aliases documented; GET /mcp/tools JSON list for discovery
  6) GET /agent/batch?mints=a,b,c (up to 5) — omni-style actions
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional


VERSION = "3.0.28-fire"
BASE = (os.environ.get("PUBLIC_BASE_URL") or "https://signal-api-24q4.onrender.com").rstrip("/")


def apply(G: dict) -> None:
    app = G.get("app")
    if app is None:
        print("[fire-v46] no app — skip")
        return

    try:
        from fastapi import Query, Request
        from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
    except Exception as e:
        print("[fire-v46] fastapi import failed:", e)
        return

    # ---------- helpers ----------
    def _drop_paths(paths):
        try:
            app.router.routes[:] = [
                r for r in list(app.router.routes)
                if getattr(r, "path", None) not in paths
            ]
        except Exception as e:
            print("[fire-v46] drop:", e)

    def _front(*paths_order):
        """Move listed paths to front (before catch-all)."""
        try:
            routes = list(app.router.routes)
            for p in reversed(paths_order):
                idxs = [i for i, r in enumerate(routes) if getattr(r, "path", None) == p]
                if idxs:
                    r = routes.pop(idxs[-1])
                    routes.insert(0, r)
            app.router.routes[:] = routes
        except Exception as e:
            print("[fire-v46] front:", e)

    MINT_RE = G.get("MINT_RE")
    build_omni = G.get("build_omni")
    build_signal = G.get("build_signal")
    stats_report = G.get("stats_report")
    rate_limited = G.get("rate_limited")
    client_ip = G.get("client_ip")
    too_many = G.get("too_many")

    # ---------- 1) /stats full / soft-correct ----------
    _drop_paths({"/stats"})

    @app.get("/stats", tags=["trust"], summary="Measured accuracy of past verdicts")
    async def stats_fire(request: Request):
        """Prefer real stats_report; never 500; never wrong signature."""
        out: Dict[str, Any] = {
            "available": False,
            "app_version": G.get("VERSION") or VERSION,
            "rules_version": G.get("RULES_VERSION"),
            "nfa": True,
        }
        # Try several call shapes used across parts
        client = getattr(getattr(request, "app", None), "state", None)
        httpx_client = getattr(client, "client", None) if client else None

        candidates = []
        if callable(stats_report):
            candidates.append(("stats_report", stats_report))
        for name in (
            "stats_with_bias",
            "compute_stats",
            "build_stats",
            "stats_payload",
        ):
            fn = G.get(name)
            if callable(fn):
                candidates.append((name, fn))

        last_err = None
        for name, fn in candidates:
            for kwargs in (
                {"request": request},
                {"client": httpx_client},
                {"client": httpx_client, "request": request},
                {},
            ):
                try:
                    import inspect
                    sig = None
                    try:
                        sig = inspect.signature(fn)
                    except Exception:
                        sig = None
                    # filter kwargs to accepted params
                    if sig is not None:
                        allowed = set(sig.parameters.keys())
                        if any(
                            p.kind == inspect.Parameter.VAR_KEYWORD
                            for p in sig.parameters.values()
                        ):
                            call_kw = kwargs
                        else:
                            call_kw = {k: v for k, v in kwargs.items() if k in allowed}
                            # positional-only client style
                            if not call_kw and "client" in allowed and httpx_client is not None:
                                call_kw = {}
                                if len(sig.parameters) >= 1:
                                    res = fn(httpx_client)
                                    if inspect.isawaitable(res):
                                        res = await res
                                    if isinstance(res, dict) and res:
                                        out = res
                                        out.setdefault("available", True)
                                        out["stats_source"] = name
                                        return JSONResponse(out)
                    else:
                        call_kw = kwargs

                    res = fn(**call_kw) if call_kw else fn()
                    if inspect.isawaitable(res):
                        res = await res
                    if isinstance(res, dict) and (
                        res.get("resolved") is not None
                        or res.get("by_verdict")
                        or res.get("available") is True
                    ):
                        res = dict(res)
                        res.setdefault("available", True)
                        res["stats_source"] = name
                        res["nfa"] = True
                        return JSONResponse(res)
                    if isinstance(res, dict):
                        out.update(res)
                        out["stats_source"] = name
                except TypeError as e:
                    last_err = f"{name}: {e}"
                    continue
                except Exception as e:
                    last_err = f"{name}: {e}"
                    continue

        # Redis / track-record light fallback
        try:
            store = G.get("track_record_store") or G.get("TR") or G.get("get_track_record")
            if callable(store):
                tr = store()
                if inspect.isawaitable(tr):
                    tr = await tr
                if isinstance(tr, dict):
                    out["track_record_meta"] = {k: tr.get(k) for k in list(tr)[:12]}
        except Exception:
            pass

        out["available"] = bool(out.get("resolved") or out.get("by_verdict"))
        out["error"] = None if out["available"] else "stats_partial"
        out["detail"] = last_err
        out["hint"] = "Seed more mints via /seed or cron; compare within same rules_version"
        out["public_verify"] = {
            "ledger": "GET /ledger",
            "methodology": "GET /methodology",
            "history_ui": "GET /history",
        }
        return JSONResponse(out, status_code=200)

    print("[fire-v46] /stats replaced (request-safe)")

    # ---------- 2) llms.txt ----------
    _drop_paths({"/llms.txt"})
    _LLMS = f"""# TVibe Signal
> Free Solana mint **risk gate** for AI agents. Heuristics + public track record. NFA.

## Primary (use this first)
- HTTP: GET {BASE}/omni?mint=<MINT>&view=agent
- PRO depth: GET {BASE}/pro_json?mint=<MINT>
- Batch: GET {BASE}/agent/batch?mints=mint1,mint2,mint3
- Stats: GET {BASE}/stats
- MCP: {BASE}/mcp
- Skill: {BASE}/skill.json
- Agent card: {BASE}/.well-known/agent-card.json

## Claude Desktop (mcpServers)
{{"mcpServers":{{"tvibe":{{"url":"{BASE}/mcp"}}}}}}

## Cursor
{{"mcp":{{"tvibe":{{"url":"{BASE}/mcp"}}}}}}

## How to read view=agent
1. action: pass | review | skip
2. filter.pass — only size when true AND unknowns empty
3. unknowns non-empty → do not size
4. what_would_change — what would flip the gate
5. valid_for_s / rules_version — re-fetch when stale; compare stats in-version
6. Never treat pass as a buy order (NFA)

## Fair use
Public free instance — self-host for high volume. GET /ops/fair-use if present.
"""

    @app.get("/llms.txt", include_in_schema=False)
    async def llms_txt_fire():
        return PlainTextResponse(_LLMS)

    print("[fire-v46] /llms.txt agent-first")

    # ---------- 3) skill.json + agent-card ----------
    _drop_paths({"/skill.json", "/.well-known/agent-card.json"})

    _SKILL = {
        "name": "tvibe-signal",
        "title": "TVibe Signal",
        "description": "Free Solana mint risk gate for agents. Heuristic pass/review/skip with optional PRO holder/LP/dev. Public track record. NFA.",
        "category": "security",
        "version": VERSION,
        "pricing": "free",
        "service_url": BASE,
        "endpoints": [
            {"method": "GET", "path": "/omni", "query": "mint,view=agent", "role": "primary risk gate"},
            {"method": "GET", "path": "/pro_json", "query": "mint", "role": "holder/LP/dev grade"},
            {"method": "GET", "path": "/agent/batch", "query": "mints", "role": "batch up to 5"},
            {"method": "GET", "path": "/stats", "role": "measured outcomes"},
            {"method": "GET", "path": "/mcp", "role": "MCP transport"},
        ],
        "mcp": {"url": f"{BASE}/mcp"},
        "nfa": True,
    }

    _CARD = {
        "name": "TVibe Signal",
        "description": "Free Solana token risk gate for autonomous agents.",
        "url": BASE,
        "version": VERSION,
        "skills": [
            {
                "id": "omni",
                "name": "omni",
                "description": "Risk gate for one mint. Prefer view=agent.",
                "input": {"mint": "string", "view": "agent|full"},
                "endpoint": f"{BASE}/omni",
            },
            {
                "id": "pro_json",
                "name": "pro_json",
                "description": "PRO grade A-F + holders/LP/dev breakdown.",
                "input": {"mint": "string"},
                "endpoint": f"{BASE}/pro_json",
            },
            {
                "id": "batch",
                "name": "agent_batch",
                "description": "Check up to 5 mints; returns action list.",
                "input": {"mints": "comma-separated"},
                "endpoint": f"{BASE}/agent/batch",
            },
            {
                "id": "stats",
                "name": "stats",
                "description": "Measured track record of past verdicts.",
                "endpoint": f"{BASE}/stats",
            },
        ],
        "authentication": "none",
        "pricing": "free",
        "nfa": True,
    }

    @app.get("/skill.json", include_in_schema=False)
    async def skill_json_fire():
        return JSONResponse(_SKILL)

    @app.get("/.well-known/agent-card.json", include_in_schema=False)
    async def agent_card_fire():
        return JSONResponse(_CARD)

    print("[fire-v46] /skill.json + agent-card")

    # ---------- 4) what_would_change on agent view ----------
    def _what_would_change(pkt: dict) -> List[str]:
        tips: List[str] = []
        if not isinstance(pkt, dict):
            return ["Re-fetch when valid_for_s expires."]
        unknowns = pkt.get("unknowns") or (pkt.get("decision") or {}).get("unknowns") or []
        blockers = pkt.get("blockers") or (pkt.get("decision") or {}).get("blockers") or []
        filt = pkt.get("filter") if isinstance(pkt.get("filter"), dict) else {}
        action = (pkt.get("action") or (pkt.get("decision") or {}).get("verdict") or "").lower()
        if unknowns:
            tips.append("Clear unknowns (more on-chain data) before sizing.")
        if blockers:
            tips.append("Blockers present — only reconsider if liquidity/holders/authorities improve on-chain.")
        if filt.get("pass") is False:
            tips.append("filter.pass is false — treat as no-trade until gate clears.")
        if action in ("skip", "avoid"):
            tips.append("Avoid/skip: need lower concentration, locked LP, and no active mint/freeze.")
        if action in ("review", "caution"):
            tips.append("Review: smaller size only if unknowns empty and liquidity deepens.")
        if action in ("pass", "ok") and not unknowns:
            tips.append("Gate clear is not a buy signal — re-check after valid_for_s.")
        if not tips:
            tips.append("Re-fetch when valid_for_s expires; compare /stats within same rules_version.")
        return tips[:3]

    def _agent_view(pkt: dict) -> dict:
        if not isinstance(pkt, dict):
            pkt = {}
        dec = pkt.get("decision") if isinstance(pkt.get("decision"), dict) else {}
        filt = pkt.get("filter") if isinstance(pkt.get("filter"), dict) else {}
        action = pkt.get("action") or dec.get("verdict") or pkt.get("verdict") or "review"
        action = str(action).lower()
        # normalize to pass|review|skip
        if action in ("ok", "pass"):
            action_n = "pass"
        elif action in ("avoid", "skip", "sell"):
            action_n = "skip"
        else:
            action_n = "review"
        out = {
            "mint": pkt.get("mint"),
            "action": action_n,
            "verdict": pkt.get("verdict") or dec.get("verdict") or action_n,
            "filter": {"pass": bool(filt.get("pass")) if filt else action_n == "pass"},
            "confidence": pkt.get("confidence") or dec.get("confidence"),
            "risk_score": pkt.get("risk_score") or pkt.get("score"),
            "blockers": (pkt.get("blockers") or dec.get("blockers") or [])[:8],
            "cautions": (pkt.get("cautions") or dec.get("cautions") or [])[:8],
            "unknowns": (pkt.get("unknowns") or dec.get("unknowns") or [])[:8],
            "what_would_change": _what_would_change(pkt),
            "valid_for_s": pkt.get("valid_for_s") or pkt.get("ttl_s") or 30,
            "rules_version": pkt.get("rules_version") or G.get("RULES_VERSION"),
            "version": pkt.get("version") or G.get("VERSION") or VERSION,
            "nfa": True,
            "ok_is_not_a_buy_signal": True,
        }
        return out

    # Wrap existing GET /omni endpoints
    wrapped = 0
    for route in list(getattr(app, "routes", []) or []):
        if getattr(route, "path", None) != "/omni":
            continue
        endpoint = getattr(route, "endpoint", None)
        if not callable(endpoint) or getattr(endpoint, "_fire_v46", False):
            continue

        import functools
        import inspect

        if inspect.iscoroutinefunction(endpoint):
            @functools.wraps(endpoint)
            async def _omni_wrap(*args, __ep=endpoint, **kwargs):
                res = await __ep(*args, **kwargs)
                view = kwargs.get("view") or "full"
                # try extract view from request
                for a in args:
                    try:
                        from fastapi import Request as _R
                        if isinstance(a, _R):
                            view = a.query_params.get("view") or view
                    except Exception:
                        pass
                if str(view).lower() in ("agent", "compact", "action"):
                    data = res
                    if hasattr(res, "body"):
                        try:
                            data = json.loads(res.body.decode())
                        except Exception:
                            return res
                    if isinstance(data, dict):
                        return JSONResponse(_agent_view(data))
                # always attach what_would_change on dict JSONResponse
                if isinstance(res, dict):
                    res = dict(res)
                    res.setdefault("what_would_change", _what_would_change(res))
                    res["nfa"] = True
                    return res
                return res
            _omni_wrap._fire_v46 = True
            route.endpoint = _omni_wrap
            dep = getattr(route, "dependant", None)
            if dep is not None:
                try:
                    dep.call = _omni_wrap
                except Exception:
                    pass
            wrapped += 1
    print(f"[fire-v46] /omni agent enrich wrapped={wrapped}")

    # ---------- 5) MCP tools discovery list ----------
    _drop_paths({"/mcp/tools"})

    @app.get("/mcp/tools", tags=["mcp"], summary="List agent tools (discovery)")
    async def mcp_tools_list():
        return {
            "tools": [
                {
                    "name": "omni",
                    "description": "Solana mint risk gate. Returns action pass|review|skip.",
                    "url": f"{BASE}/omni?mint=<MINT>&view=agent",
                    "method": "GET",
                },
                {
                    "name": "pro_json",
                    "description": "PRO grade + holders/LP/dev breakdown.",
                    "url": f"{BASE}/pro_json?mint=<MINT>",
                    "method": "GET",
                },
                {
                    "name": "agent_batch",
                    "description": "Batch up to 5 mints.",
                    "url": f"{BASE}/agent/batch?mints=m1,m2,m3",
                    "method": "GET",
                },
                {
                    "name": "stats",
                    "description": "Measured track record.",
                    "url": f"{BASE}/stats",
                    "method": "GET",
                },
            ],
            "mcp_transport": f"{BASE}/mcp",
            "nfa": True,
            "version": VERSION,
        }

    print("[fire-v46] GET /mcp/tools")

    # ---------- 6) agent batch ----------
    _drop_paths({"/agent/batch"})

    @app.get("/agent/batch", tags=["product"], summary="Batch risk gate (max 5)")
    async def agent_batch(
        request: Request,
        mints: str = Query(..., description="Comma-separated mints, max 5"),
    ):
        parts = [p.strip() for p in (mints or "").split(",") if p.strip()][:5]
        if not parts:
            return JSONResponse({"error": "need mints"}, status_code=400)
        if callable(rate_limited) and callable(client_ip):
            try:
                wait = rate_limited(client_ip(request), cost=min(4 * len(parts), 12))
                if wait and callable(too_many):
                    raise too_many(wait)
            except Exception:
                pass

        client = getattr(request.app.state, "client", None)
        results = []
        for m in parts:
            item = {"mint": m}
            try:
                if callable(build_omni) and client is not None:
                    pkt = await build_omni(client, m)
                    if isinstance(pkt, dict):
                        item.update(_agent_view(pkt))
                    else:
                        item["action"] = "review"
                        item["error"] = "bad_payload"
                else:
                    # fallback: internal pro path not required
                    item["action"] = "review"
                    item["error"] = "build_omni_unavailable"
                    item["nfa"] = True
            except Exception as e:
                item["action"] = "review"
                item["error"] = str(e)[:120]
                item["nfa"] = True
            results.append(item)

        return {
            "count": len(results),
            "results": results,
            "nfa": True,
            "version": VERSION,
        }

    print("[fire-v46] GET /agent/batch")

    # Route order: keep critical paths in front
    _front(
        "/omni",
        "/signal",
        "/stats",
        "/agent/batch",
        "/mcp/tools",
        "/llms.txt",
        "/skill.json",
        "/health",
        "/pro",
        "/pro_json",
        "/mcp",
        "/",
    )

    try:
        G["VERSION"] = VERSION
        app.version = VERSION
        app.openapi_schema = None
    except Exception:
        pass

    print(f"[fire-v46] ready version={VERSION}")


if __name__ == "__main__":
    print("Import apply(G) from loader — not a standalone server.")

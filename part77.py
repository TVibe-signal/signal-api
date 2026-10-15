# ---------- v2.56: Autonomic Breath (reliable seed + focus loop) ----------
VERSION = "2.56.0"
app.version = VERSION
app.openapi_schema = None

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional

# ---- knobs (env) ----
BREATH_ENABLED = os.getenv("SI_BREATH", "true").lower() in ("1", "true", "yes")
BREATH_EVERY_S = int(os.getenv("SI_BREATH_EVERY_S", "900"))       # 15 min
BREATH_FOCUS_N = int(os.getenv("SI_BREATH_FOCUS_N", "3"))
BREATH_SEED_N = int(os.getenv("SI_BREATH_SEED_N", "2"))
BREATH_DAILY_CAP = int(os.getenv("SI_BREATH_DAILY_CAP", "80"))    # hard cap pulls/day
BREATH_PAUSE_IF_RPC_DOWN = os.getenv("SI_BREATH_PAUSE_RPC", "true").lower() in ("1", "true", "yes")

BREATH_META = "si:breath:meta"
BREATH_DAY = "si:breath:day:{}"          # YYYYMMDD -> count
_last_breath = 0.0

def _day_key() -> str:
    return time.strftime("%Y%m%d", time.gmtime())

async def _breath_count_today(client) -> int:
    if not PRED_ENABLED or not client:
        return 0
    try:
        raw = await redis_get(client, BREATH_DAY.format(_day_key()))
        return int(raw or 0)
    except Exception:
        return 0

async def _breath_incr(client, n: int = 1) -> int:
    if not PRED_ENABLED or not client:
        return 0
    try:
        k = BREATH_DAY.format(_day_key())
        res = await redis_pipe(client, [
            ["INCRBY", k, n],
            ["EXPIRE", k, 3 * 86400],
            ["HINCRBY", BREATH_META, "total_pulls", n],
            ["HSET", BREATH_META, "last_ts", str(int(time.time()))],
            ["EXPIRE", BREATH_META, 30 * 86400],
        ])
        return int((res or [0])[0] or 0)
    except Exception:
        return 0

def _rpc_seems_down() -> bool:
    """Best-effort: if health-style source stats exist and rpc is down, pause."""
    try:
        src = globals().get("_source_stats") or globals().get("SOURCE_STATS")
        if isinstance(src, dict):
            rpc = src.get("solana_rpc") or {}
            if str(rpc.get("status", "")).lower() in ("down", "error", "fail"):
                return True
    except Exception:
        pass
    return False

async def _focus_mints(client) -> List[str]:
    out: List[str] = []
    try:
        raw = await redis_get(client, "si:entity:focus")
        if raw:
            for item in json.loads(raw) or []:
                m = item.get("mint") if isinstance(item, dict) else None
                if m and MINT_RE.match(m):
                    out.append(m)
    except Exception:
        pass
    try:
        res = await redis_pipe(client, [["ZREVRANGE", "predattn:top", 0, 9]])
        for m in (res or [[]])[0] or []:
            if m and MINT_RE.match(m) and m not in out:
                out.append(m)
    except Exception:
        pass
    return out

async def _seed_mints(client) -> List[str]:
    """Reuse project seed helpers when present; otherwise empty."""
    candidates: List[str] = []
    for name in ("_seed_candidate_mints", "seed_candidate_mints", "_get_seed_mints"):
        fn = globals().get(name)
        if callable(fn):
            try:
                got = await fn(client)
                if isinstance(got, list):
                    candidates.extend([m for m in got if isinstance(m, str)])
            except Exception:
                pass
    try:
        res = await redis_pipe(client, [["LRANGE", "seed:recent", 0, 19]])
        for m in (res or [[]])[0] or []:
            if isinstance(m, str):
                candidates.append(m)
    except Exception:
        pass

    seen = set()
    out = []
    for m in candidates:
        if m and MINT_RE.match(m) and m not in seen:
            seen.add(m)
            out.append(m)
    return out

async def breath_once(client) -> Dict[str, Any]:
    """One autonomic breath: focus pulls + limited seed pulls."""
    summary: Dict[str, Any] = {
        "ok": False,
        "pulled": 0,
        "focus": 0,
        "seed": 0,
        "errors": 0,
        "skipped": None,
        "day_count": 0,
        "ts": int(time.time()),
        "version": VERSION,
    }
    if not BREATH_ENABLED:
        summary["skipped"] = "disabled"
        return summary
    if not PRED_ENABLED or not client:
        summary["skipped"] = "no_redis"
        return summary
    if BREATH_PAUSE_IF_RPC_DOWN and _rpc_seems_down():
        summary["skipped"] = "rpc_down"
        return summary

    day_n = await _breath_count_today(client)
    summary["day_count"] = day_n
    remain = max(0, BREATH_DAILY_CAP - day_n)
    if remain <= 0:
        summary["skipped"] = "daily_cap"
        return summary

    focus = await _focus_mints(client)
    seed = await _seed_mints(client)

    plan: List[tuple] = []
    for m in focus[:BREATH_FOCUS_N]:
        plan.append(("focus", m))
    for m in seed[:BREATH_SEED_N]:
        if m not in focus:
            plan.append(("seed", m))
    plan = plan[:remain]

    for kind, mint in plan:
        try:
            await build_signal(client, mint, True)
            summary["pulled"] += 1
            if kind == "focus":
                summary["focus"] += 1
            else:
                summary["seed"] += 1
            await _breath_incr(client, 1)
            await asyncio.sleep(0.45)
        except Exception:
            summary["errors"] += 1
            await asyncio.sleep(0.2)

    try:
        if "refresh_entity" in globals() and summary["pulled"] > 0:
            await refresh_entity(client)
    except Exception:
        pass
    try:
        if "si_emit" in globals():
            await si_emit(client, "autonomic_breath", None, {
                "pulled": summary["pulled"],
                "focus": summary["focus"],
                "seed": summary["seed"],
                "errors": summary["errors"],
            })
    except Exception:
        pass

    summary["ok"] = True
    summary["day_count"] = await _breath_count_today(client)
    return summary

@app.post("/si/breath", tags=["entity"], include_in_schema=False)
async def si_breath_run(request: Request):
    """Manual breath trigger (operator / cron POST)."""
    return await breath_once(request.app.state.client)

@app.get("/si/breath", tags=["entity"], include_in_schema=False)
async def si_breath_get(request: Request):
    """Cron-friendly alias: free monitors often only support GET."""
    try:
        summary = await breath_once(request.app.state.client)
        return {"ok": True, "via": "GET", "summary": summary}
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}

@app.get("/si/breath/status", tags=["entity"])
async def si_breath_status(request: Request):
    client = request.app.state.client
    meta = {}
    try:
        if PRED_ENABLED:
            raw = await redis_pipe(client, [["HGETALL", BREATH_META]])
            meta = to_dict((raw or [{}])[0] or {})
    except Exception:
        pass
    return {
        "enabled": BREATH_ENABLED,
        "every_s": BREATH_EVERY_S,
        "daily_cap": BREATH_DAILY_CAP,
        "day_count": await _breath_count_today(client),
        "focus_n": BREATH_FOCUS_N,
        "seed_n": BREATH_SEED_N,
        "meta": meta,
        "version": VERSION,
    }

# Opportunistic breath on traffic (rate-limited)
_build_prev_breath = build_signal

async def build_signal(client, mint, security, prefetched=None):
    global _last_breath
    result, status = await _build_prev_breath(client, mint, security, prefetched)
    try:
        now = time.time()
        if BREATH_ENABLED and now - _last_breath >= BREATH_EVERY_S:
            _last_breath = now
            await breath_once(client)
    except Exception:
        pass
    return result, status

print(f"[part77] v{VERSION} Autonomic Breath loaded → POST+GET /si/breath · GET /si/breath/status")
# ---------- v2.62: Fixes from live test ----------
VERSION = "2.62.0"
app.version = VERSION
app.openapi_schema = None

import asyncio
import hmac
import math
import os
import time
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


def _drop_route(path: str, method: str) -> None:
    app.router.routes[:] = [
        r for r in app.router.routes
        if not (getattr(r, "path", None) == path and method in (getattr(r, "methods", None) or ()))
    ]


# ===== 1. Missing data must be None, never 0 (live: MOON showed "top 10 own only 0%") =====
_NUM = (int, float)


def _fix_missing(r: Any) -> Any:
    if not isinstance(r, dict):
        return r
    r = dict(r)
    added = []
    t = r.get("top10_holders_pct")
    if isinstance(t, _NUM) and not isinstance(t, bool) and t <= 0:
        r["top10_holders_pct"] = None
        added.append("top10_holders_pct")
    if r.get("asset_class") == "major" and r.get("lp_locked_pct") == 0:
        r["lp_locked_pct"] = None  # LP lock is not meaningful for SOL/USDC/USDT
    pos = r.get("positives")
    if added and isinstance(pos, list):
        r["positives"] = [p for p in pos if "top 10 holders" not in str(p).lower()]
    if added:
        dq = dict(r.get("data_quality") or {})
        dq["missing"] = sorted(set(list(dq.get("missing") or []) + added))
        dq["completeness"] = "partial"
        try:
            dq["data_confidence"] = min(float(dq.get("data_confidence", 1.0)), 0.7)
        except Exception:
            dq["data_confidence"] = 0.7
        r["data_quality"] = dq
        dec = r.get("decision")
        if isinstance(dec, dict):
            dec = dict(dec)
            unk = list(dec.get("unknowns") or [])
            unk.append("Top-10 holder share was not available (reported as unknown, not 0%)")
            dec["unknowns"] = unk
            r["decision"] = dec
    return r


_build_prev_83 = build_signal


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_83(client, mint, security, *args, **kwargs)
    try:
        if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], dict):
            return _fix_missing(res[0]), res[1]
        if isinstance(res, dict):
            return _fix_missing(res)
    except Exception:
        pass
    return res


# ===== 2. Flag classifier: use the real flag names seen in /track_record =====
_OBS_FLAGS = {
    "brand_new_pair", "very_new_pair", "new_pair", "no_recent_trades", "dead_pool",
    "very_low_liquidity", "low_liquidity", "volume_spike", "extreme_volume_spike",
    "high_turnover", "extreme_turnover", "heavy_selling", "one_sided_flow",
    "lp_not_locked", "lp_partially_locked", "mint_authority_active", "freeze_authority_active",
    "dominant_holder", "high_holder_concentration", "extreme_holder_concentration",
    "transfer_fee_set", "transfer_fee_high", "transfer_fee_extreme", "transfer_hook_active",
    "permanent_delegate_active", "default_account_frozen", "risky_token_extension",
    "no_sell_route", "high_exit_cost",
}
_INF_FLAGS = {
    "dump_risk", "late_entry_risk", "holders_churning", "whale_dumping",
    "weak_absorption", "dip_absorbed", "holders_stable", "whale_accumulating",
}
_INF_TOK = {"risk", "likely", "pattern", "suspect", "predict", "cluster", "dumper", "rug"}
_OBS_TOK = {"authority", "liquidity", "age", "pair", "trades", "turnover", "volume", "holder", "lp"}


def _flag_kind(fid: str) -> str:
    x = fid.lower()
    if "unverified" in x or "unknown" in x:
        return "unknown"
    if x in _OBS_FLAGS:
        return "observation"
    if x in _INF_FLAGS:
        return "inference"
    toks = set(x.split("_"))
    if toks & _INF_TOK:
        return "inference"
    if toks & _OBS_TOK:
        return "observation"
    return "inference"


# ===== 3. Daily journal: yesterday's summary, atomic, off the hot path =====
_journal_day_done: Optional[str] = None
_bg_tasks: set = set()


async def _write_journal(client, force: bool = False) -> Optional[dict]:
    day = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 86400))
    marker = f"si:journal:day:{day}"
    if force:
        await redis_pipe(client, [["DEL", marker]])
    res = await redis_pipe(client, [["SET", marker, "1", "NX", "EX", 3 * 86400]])
    first = (res or [None])[0]
    if isinstance(first, dict):
        first = first.get("result")
    if not first:
        return None  # someone already wrote it
    breath: Any = "n/a"
    try:
        v = await redis_get(client, f"si:breath:day:{day.replace('-', '')}")
        if v is not None:
            breath = int(v)
    except Exception:
        pass
    mood, regime = "observing", "unknown"
    try:
        raw = await redis_get(client, "si:entity:core")
        if raw:
            ent = json.loads(raw)
            mood = ent.get("mood") or mood
            regime = ((ent.get("stats") or {}).get("regime")) or regime
    except Exception:
        pass
    bench = await prerug_bench_v3(client)
    pats = (bench.get("patterns") or {}).values()
    ready = sum(1 for p in pats if p.get("ready"))
    line = (f"Day log {day} (UTC): breath_pulls={breath}; latest mood={mood}, regime={regime}; "
            f"prerug_patterns_ready={ready}.")
    entry = {"ts": int(time.time()), "day": day, "line": line, "meta": {"source": "daily_auto"}}
    await redis_pipe(client, [
        ["LPUSH", JOURNAL_KEY, json.dumps(entry, separators=(",", ":"))],
        ["LTRIM", JOURNAL_KEY, 0, 89],
        ["EXPIRE", JOURNAL_KEY, 180 * 86400],
    ])
    return entry


async def _journal_task(client) -> None:
    global _journal_day_done
    try:
        await _write_journal(client)
    except Exception:
        _journal_day_done = None  # retry on a later call


async def maybe_daily_journal(client) -> Optional[dict]:
    """Cheap RAM check; the Redis work runs in the background. Old wrappers keep calling this name."""
    global _journal_day_done
    if not PRED_ENABLED or not client:
        return None
    today = time.strftime("%Y-%m-%d", time.gmtime())
    if _journal_day_done == today:
        return None
    _journal_day_done = today
    t = asyncio.create_task(_journal_task(client))
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return None


def _operator_ok(key: Optional[str]) -> bool:
    want = os.getenv("OPERATOR_KEY", "")  # swap for the part48 helper if it uses another name
    return bool(want) and bool(key) and hmac.compare_digest(key, want)


_drop_route("/si/daily-journal", "POST")


@app.post("/si/daily-journal", tags=["entity"], include_in_schema=False)
async def daily_journal_operator(request: Request, force: int = 0):
    if not _operator_ok(request.headers.get("x-operator-key")):
        raise HTTPException(status_code=403, detail="Forbidden")
    entry = await _write_journal(request.app.state.client, force=bool(force))
    return {"ok": True, "entry": entry, "note": "entry is null if yesterday was already written"}


# ===== 4. Benchmark: Wilson CI, no fake 0.0 rates, rate limit + cache. Must beat the old route =====
def _wilson(k: int, n: int, z: float = 1.96):
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - m) / d, 3), round((c + m) / d, 3)]


_bench_prev_83 = prerug_bench_public


async def prerug_bench_v3(client) -> Dict[str, Any]:
    out = await _bench_prev_83(client)
    for p in (out.get("patterns") or {}).values():
        if p.get("basis") != "outcome_labeled":
            p["bad_rate"] = None  # fire counts without outcome labels say nothing about bad rate
        p["ci95"] = _wilson(p.get("labeled_bad", 0), p.get("labeled_n", 0)) if p.get("labeled_n", 0) >= 5 else None
    out["version"] = VERSION
    return out


_drop_route("/benchmark/prerug", "GET")


@app.get("/benchmark/prerug", tags=["product"])
async def benchmark_prerug_v3(request: Request):
    wait = rate_limited(client_ip(request), cost=1)
    if wait:
        raise too_many(wait)
    out = await prerug_bench_v3(request.app.state.client)
    return JSONResponse(content=out, headers={"Cache-Control": "public, max-age=30"})


# ===== 5. /diff: do not leak internal Redis key names =====
_compute_diff_prev = compute_diff


async def compute_diff(*a, **k):
    try:
        return await _compute_diff_prev(*a, **k)
    except HTTPException as e:
        if isinstance(e.detail, dict) and not os.getenv("DEBUG_DIFF"):
            e.detail = {kk: vv for kk, vv in e.detail.items() if kk != "debug"}
        raise


print(f"[part83] v{VERSION} live-test fixes loaded")

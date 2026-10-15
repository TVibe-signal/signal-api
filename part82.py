# ---------- v2.61: Daily journal + prerug bench public (labeled) ----------
VERSION = "2.61.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Any, Dict, Optional

BENCH_KEY = "prerug:bench"
BENCH_TTL = 120 * 86400
JOURNAL_KEY = "si:entity:journal"

async def prerug_bench_public(client) -> Dict[str, Any]:
    if not PRED_ENABLED or not client:
        return {"available": False, "patterns": {}}
    try:
        raw = await redis_pipe(client, [["HGETALL", BENCH_KEY]])
        h = to_dict((raw or [{}])[0] or {})
        patterns = {}
        ids = {k.split(":")[0] for k in h if ":" in k}
        for pid in sorted(ids):
            n = int(float(h.get(f"{pid}:n", 0) or 0))
            labeled_n = int(float(h.get(f"{pid}:labeled_n", 0) or 0))
            labeled_bad = int(float(h.get(f"{pid}:labeled_bad", 0) or 0))
            bad = int(float(h.get(f"{pid}:bad", 0) or 0))
            if labeled_n >= 5:
                rate = round(labeled_bad / labeled_n, 3)
                basis = "outcome_labeled"
                sample = labeled_n
            elif n >= 5:
                rate = round(bad / n, 3) if n else None
                basis = "fire_count_only"
                sample = n
            else:
                rate, basis, sample = None, "insufficient", max(n, labeled_n)
            patterns[pid] = {
                "fires": n,
                "labeled_n": labeled_n,
                "labeled_bad": labeled_bad,
                "bad_rate": rate,
                "basis": basis,
                "sample": sample,
                "ready": labeled_n >= 20,
            }
        return {
            "available": True,
            "patterns": patterns,
            "note": "bad_rate uses outcome labels when labeled_n>=5; ready=true at labeled_n>=20",
            "version": VERSION,
        }
    except Exception as e:
        return {"available": False, "error": str(e)[:120], "patterns": {}}

@app.get("/benchmark/prerug", tags=["product"])
async def benchmark_prerug_v2(request: Request):
    return await prerug_bench_public(request.app.state.client)

async def maybe_daily_journal(client) -> Optional[dict]:
    if not PRED_ENABLED or not client:
        return None
    day = time.strftime("%Y-%m-%d", time.gmtime())
    marker = f"si:journal:day:{day}"
    try:
        if await redis_get(client, marker):
            return None
        breath_n = 0
        try:
            breath_n = int(await redis_get(client, f"si:breath:day:{time.strftime('%Y%m%d', time.gmtime())}") or 0)
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
        bench = await prerug_bench_public(client)
        ready = sum(1 for p in (bench.get("patterns") or {}).values() if p.get("ready"))
        line = (
            f"Day log {day}: breath_pulls={breath_n}, mood={mood}, regime={regime}, "
            f"prerug_patterns_ready={ready}."
        )
        entry = {"ts": int(time.time()), "day": day, "line": line, "meta": {"source": "daily_auto"}}
        await redis_pipe(client, [
            ["SET", marker, "1", "EX", 3 * 86400],
            ["LPUSH", JOURNAL_KEY, json.dumps(entry, separators=(",", ":"))],
            ["LTRIM", JOURNAL_KEY, 0, 89],
            ["EXPIRE", JOURNAL_KEY, 180 * 86400],
        ])
        return entry
    except Exception:
        return None

_prev_breath = globals().get("breath_once")
if callable(_prev_breath):
    async def breath_once(client):
        summary = await _prev_breath(client)
        try:
            await maybe_daily_journal(client)
        except Exception:
            pass
        return summary

@app.post("/si/daily-journal", tags=["entity"], include_in_schema=False)
async def force_daily_journal(request: Request):
    entry = await maybe_daily_journal(request.app.state.client)
    return {"ok": True, "entry": entry, "note": "None if already written today"}

_build_prev_82 = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_82(client, mint, security, prefetched)
    try:
        await maybe_daily_journal(client)
    except Exception:
        pass
    return result, status

print(f"[part82] v{VERSION} daily journal + prerug bench public loaded")
# ---------- v2.55: Autonomic Loop + Pre-rug Benchmark + Omni Packaging ----------
VERSION = "2.55.0"
app.version = VERSION
app.openapi_schema = None

import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional

# =========================
# Config
# =========================
AUTO_LOOP = os.getenv("SI_AUTO_LOOP", "true").lower() in ("1", "true", "yes")
AUTO_EVERY_S = int(os.getenv("SI_AUTO_EVERY_S", "1200"))      # 20 min
AUTO_FOCUS_PULL = int(os.getenv("SI_AUTO_FOCUS_PULL", "4"))
AUTO_SEED_PULL = int(os.getenv("SI_AUTO_SEED_PULL", "2"))
BENCH_KEY = "prerug:bench"
BENCH_TTL = 120 * 86400
_last_auto = 0.0

# =========================
# 1) Autonomic full cycle
# =========================
async def _auto_pull_mints(client) -> List[str]:
    """Focus first, then optional seed candidates."""
    mints: List[str] = []
    # Focus from entity
    try:
        raw = await redis_get(client, "si:entity:focus")
        if raw:
            for item in json.loads(raw) or []:
                m = item.get("mint") if isinstance(item, dict) else None
                if m and MINT_RE.match(m):
                    mints.append(m)
    except Exception:
        pass

    # Seed candidates if available
    try:
        if " _seed_candidate_mints" in globals() or "_seed_candidate_mints" in globals():
            extra = await _seed_candidate_mints(client)
            for m in extra or []:
                if m and MINT_RE.match(m) and m not in mints:
                    mints.append(m)
    except Exception:
        pass

    # Dedupe preserve order
    seen = set()
    out = []
    for m in mints:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out

async def autonomic_full_cycle(client) -> Dict[str, Any]:
    """
    seed/focus → signal (events + SI hooks) → entity refresh → report.
    Resolver/judge still owns labels; this keeps the organism breathing.
    """
    summary: Dict[str, Any] = {
        "ok": False,
        "pulled": 0,
        "errors": 0,
        "focus_used": 0,
        "ts": int(time.time()),
    }
    if not PRED_ENABLED or not client:
        summary["reason"] = "redis_unavailable"
        return summary

    try:
        mints = await _auto_pull_mints(client)
        # Prefer focus slots then seed slots
        focus_n = min(AUTO_FOCUS_PULL, len(mints))
        pull = mints[: focus_n + AUTO_SEED_PULL]
        summary["focus_used"] = focus_n

        for m in pull:
            try:
                await build_signal(client, m, True)
                summary["pulled"] += 1
                await asyncio.sleep(0.4)
            except Exception:
                summary["errors"] += 1

        if "refresh_entity" in globals():
            try:
                await refresh_entity(client)
            except Exception:
                pass
        if "maybe_write_report" in globals():
            try:
                await maybe_write_report(client)
            except Exception:
                pass
        if "si_emit" in globals():
            try:
                await si_emit(client, "autonomic_cycle", None, {
                    "pulled": summary["pulled"],
                    "errors": summary["errors"],
                })
            except Exception:
                pass

        summary["ok"] = True
    except Exception as e:
        summary["error"] = str(e)[:180]
    return summary

@app.post("/si/autonomic/run", tags=["entity"], include_in_schema=False)
async def si_autonomic_run(request: Request):
    return await autonomic_full_cycle(request.app.state.client)

# Opportunistic trigger
_build_prev_auto2 = build_signal

async def build_signal(client, mint, security, prefetched=None):
    global _last_auto
    result, status = await _build_prev_auto2(client, mint, security, prefetched)
    try:
        if AUTO_LOOP and time.time() - _last_auto >= AUTO_EVERY_S:
            _last_auto = time.time()
            await autonomic_full_cycle(client)
    except Exception:
        pass
    return result, status

# =========================
# 2) Pre-rug / pattern benchmark (public)
# =========================
async def bench_touch(client, pattern_ids: List[str], bad: Optional[bool]):
    if not PRED_ENABLED or not client or not pattern_ids:
        return
    try:
        cmds = []
        for pid in pattern_ids:
            cmds.append(["HINCRBY", BENCH_KEY, f"{pid}:n", 1])
            if bad is True:
                cmds.append(["HINCRBY", BENCH_KEY, f"{pid}:bad", 1])
            elif bad is False:
                cmds.append(["HINCRBY", BENCH_KEY, f"{pid}:good", 1])
        cmds.append(["EXPIRE", BENCH_KEY, BENCH_TTL])
        await redis_pipe(client, cmds)
    except Exception:
        pass

async def bench_snapshot(client) -> Dict[str, Any]:
    if not PRED_ENABLED or not client:
        return {"patterns": {}, "available": False}
    try:
        raw = await redis_pipe(client, [["HGETALL", BENCH_KEY]])
        h = to_dict((raw or [{}])[0] or {})
        patterns = {}
        ids = {k.split(":")[0] for k in h if ":" in k}
        for pid in sorted(ids):
            n = int(float(h.get(f"{pid}:n", 0) or 0))
            bad = int(float(h.get(f"{pid}:bad", 0) or 0))
            good = int(float(h.get(f"{pid}:good", 0) or 0))
            patterns[pid] = {
                "n": n,
                "bad": bad,
                "good": good,
                "bad_rate": round(bad / n, 3) if n else None,
                "precision_proxy": round(bad / n, 3) if n else None,
            }
        return {
            "available": True,
            "patterns": patterns,
            "note": "bad_rate among cases where pattern fired and later received an outcome label",
        }
    except Exception:
        return {"patterns": {}, "available": False}

@app.get("/benchmark/prerug", tags=["product"])
async def benchmark_prerug(request: Request):
    """Public benchmark for pre-rug / SI patterns."""
    return await bench_snapshot(request.app.state.client)

# When signal matches pre_rug, mark pending for later outcome
_build_prev_bench = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_bench(client, mint, security, prefetched)
    try:
        if isinstance(result, dict) and PRED_ENABLED:
            hits = result.get("pre_rug") or []
            ids = [h.get("id") for h in hits if isinstance(h, dict) and h.get("id")]
            if ids:
                await redis_pipe(client, [
                    ["SET", f"prerug:pending:{mint}", json.dumps(ids), "EX", 40 * 3600],
                ])
                # also count fires
                await bench_touch(client, ids, bad=None)
    except Exception:
        pass
    return result, status

# Close loop on outcome
_prev_on_outcome3 = globals().get("on_outcome_for_si")

async def on_outcome_for_si(client, mint: str, bad_outcome: bool):
    if _prev_on_outcome3:
        try:
            await _prev_on_outcome3(client, mint, bad_outcome)
        except Exception:
            pass
    try:
        raw = await redis_get(client, f"prerug:pending:{mint}")
        if raw:
            ids = json.loads(raw)
            # outcome-labeled update (separate from fire count)
            if PRED_ENABLED and ids:
                cmds = []
                for pid in ids:
                    cmds.append(["HINCRBY", BENCH_KEY, f"{pid}:labeled_n", 1])
                    if bad_outcome:
                        cmds.append(["HINCRBY", BENCH_KEY, f"{pid}:labeled_bad", 1])
                cmds.append(["DEL", f"prerug:pending:{mint}"])
                cmds.append(["EXPIRE", BENCH_KEY, BENCH_TTL])
                await redis_pipe(client, cmds)
    except Exception:
        pass

# =========================
# 3) Omni packaging (single story)
# =========================
OMNI_STORY = (
    "TVibex402 omni: one call for verdict, debate, community, regime, DNA, "
    "counterfactual, time-to-death and pre-rug patterns. Measured in public."
)

@app.get("/product", tags=["product"])
async def product_story():
    return {
        "name": "TVibex402",
        "one_liner": OMNI_STORY,
        "primary_call": "GET /omni?mint=ADDRESS",
        "mcp": "omni(mint)",
        "prove_it": [
            "GET /stats",
            "GET /benchmark/prerug",
            "GET /si/journal/public",
            "GET /accuracy/story",
        ],
        "entity": [
            "GET /si/core",
            "GET /si/focus",
            "GET /si/journal",
        ],
        "disclaimer": "Heuristics, not financial advice.",
    }

# Prefer omni in llms.txt
if "LLMS_TXT" in globals():
    LLMS_TXT += f"""

## Primary agent interface
{OMNI_STORY}

Use GET /omni?mint=ADDRESS (or MCP tool omni) as the default.
Use /signal only when you need the classic compact payload.

Public proof:
- /stats — track record
- /benchmark/prerug — pattern hit rates after outcomes
- /si/journal/public — what the SI entity learned
"""

# MCP re-assert omni as primary
def _register_product_mcp():
    try:
        ms = globals().get("mcp_server")
        if ms is None:
            return
        async def omni(mint: str) -> dict:
            """Primary tool: full SI packet for one mint."""
            if "build_omni" in globals():
                return await build_omni(app.state.client, mint)
            sig, _ = await build_signal(app.state.client, mint, True)
            return sig
        try:
            ms.tool()(omni)
        except Exception:
            pass
    except Exception as e:
        print(f"[part76] mcp skip: {e}")

try:
    import asyncio as _aio
    _aio.get_event_loop().call_later(5, _register_product_mcp)
except Exception:
    _register_product_mcp()

print(f"[part76] v{VERSION} autonomic + prerug benchmark + omni packaging loaded")
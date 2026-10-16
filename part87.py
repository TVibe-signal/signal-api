# ---------- v2.65: Pre-rug pattern labeled outcomes ----------
VERSION = "2.65.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Any, Dict, List, Optional

PRERUG_FIRE_KEY = "prerug:fire:{}"      # mint → json list of pattern ids at fire time
PRERUG_FIRE_TTL = 10 * 86400
BENCH_KEY = globals().get("BENCH_KEY") or "prerug:bench"


async def prerug_record_fire(client, mint: str, patterns: List[dict]) -> None:
    """Call when pre_rug patterns fire on a signal."""
    if not PRED_ENABLED or not client or not patterns:
        return
    try:
        ids = []
        for p in patterns:
            if isinstance(p, dict) and p.get("id"):
                ids.append(str(p["id"]))
            elif isinstance(p, str):
                ids.append(p)
        if not ids:
            return
        cmds = [
            ["SET", PRERUG_FIRE_KEY.format(mint), json.dumps({"ts": int(time.time()), "ids": ids}), "EX", PRERUG_FIRE_TTL],
        ]
        for pid in ids:
            cmds += [
                ["HINCRBY", BENCH_KEY, f"{pid}:n", 1],
            ]
        cmds += [["EXPIRE", BENCH_KEY, 120 * 86400]]
        await redis_pipe(client, cmds)
    except Exception as e:
        print(f"[part87] fire: {e}")


async def prerug_on_outcome(client, mint: str, bad: bool, meta: Optional[dict] = None) -> None:
    """Label previously fired patterns for this mint."""
    if not PRED_ENABLED or not client:
        return
    try:
        raw = await redis_get(client, PRERUG_FIRE_KEY.format(mint))
        if not raw:
            return
        data = json.loads(raw)
        ids = data.get("ids") or []
        cmds = []
        for pid in ids:
            cmds += [
                ["HINCRBY", BENCH_KEY, f"{pid}:labeled_n", 1],
            ]
            if bad:
                cmds += [
                    ["HINCRBY", BENCH_KEY, f"{pid}:labeled_bad", 1],
                    ["HINCRBY", BENCH_KEY, f"{pid}:bad", 1],
                ]
        cmds += [
            ["EXPIRE", BENCH_KEY, 120 * 86400],
            ["DEL", PRERUG_FIRE_KEY.format(mint)],
        ]
        if cmds:
            await redis_pipe(client, cmds)
        if "si_emit" in globals():
            await si_emit(client, "prerug_labeled", mint, {"ids": ids, "bad": bad})
    except Exception as e:
        print(f"[part87] label: {e}")


# Record fires from signal pre_rug field
_build_prev_prerug = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_prerug(client, mint, security, prefetched)
    try:
        if isinstance(result, dict):
            pr = result.get("pre_rug") or []
            if pr:
                await prerug_record_fire(client, mint, pr if isinstance(pr, list) else [pr])
    except Exception:
        pass
    return result, status


# Chain outcome hook
_prev_outcome_pr = globals().get("on_outcome_for_si")


async def on_outcome_for_si(client, mint: str, bad: bool, meta: Optional[dict] = None, **kwargs):
    if callable(_prev_outcome_pr):
        try:
            await _prev_outcome_pr(client, mint, bad, meta, **kwargs)
        except TypeError:
            try:
                await _prev_outcome_pr(client, mint, bad, meta)
            except Exception:
                pass
        except Exception:
            pass
    await prerug_on_outcome(client, mint, bad, meta)


@app.get("/benchmark/prerug/status", tags=["product"])
async def prerug_label_status(request: Request):
    """Quick view: how many fires still waiting for labels."""
    client = request.app.state.client
    bench = {}
    if "prerug_bench_public" in globals():
        try:
            bench = await prerug_bench_public(client)
        except Exception:
            pass
    return {
        "version": VERSION,
        "bench": bench,
        "note": "labeled_n increases when resolver judges a mint that previously fired a pre_rug pattern.",
    }


print(f"[part87] v{VERSION} Pre-rug labeled outcomes → fire on signal + label on_outcome_for_si")
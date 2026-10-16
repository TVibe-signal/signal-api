# ---------- v2.64: Residual outcome learning (did AttnRes beat base?) ----------
VERSION = "2.64.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Any, Dict, Optional

RES_LEARN_KEY = "si:res:learn"          # hash: right_base, right_res, n, ...
RES_PENDING = "si:res:pending:{}"       # pending residual snapshot per mint
RES_TTL = 8 * 86400


async def _res_learn_record_pending(client, mint: str, result: dict) -> None:
    """Store base vs residual verdict at emit time for later judge."""
    if not PRED_ENABLED or not client or not isinstance(result, dict):
        return
    ar = result.get("attention_residuals") or {}
    if not ar:
        return
    try:
        payload = {
            "ts": int(time.time()),
            "base": ar.get("base_verdict") or result.get("verdict"),
            "residual": ar.get("residual_verdict"),
            "alpha": ar.get("alpha"),
            "blended_stress": ar.get("blended_stress"),
            "risk_score": result.get("risk_score"),
        }
        await redis_pipe(client, [
            ["SET", RES_PENDING.format(mint), json.dumps(payload), "EX", RES_TTL],
        ])
    except Exception:
        pass


async def residual_on_outcome(client, mint: str, bad: bool, meta: Optional[dict] = None) -> None:
    """
    When outcome is judged: if residual_verdict was more conservative on bad cases
    (or less wrong on good cases), count a win for residual.
    """
    if not PRED_ENABLED or not client:
        return
    try:
        raw = await redis_get(client, RES_PENDING.format(mint))
        if not raw:
            return
        snap = json.loads(raw)
        base = (snap.get("base") or "").lower()
        res = (snap.get("residual") or "").lower()

        # Scoring: on bad outcome, "avoid" > "caution" > "ok"
        order = {"ok": 0, "caution": 1, "avoid": 2}
        b = order.get(base, 1)
        r = order.get(res, 1)

        base_ok = (b >= 1 and bad) or (b == 0 and not bad)  # rough
        # Better metric: residual closer to truth
        # truth stress = 1 if bad else 0
        truth = 1.0 if bad else 0.0
        err_base = abs(b / 2.0 - truth)
        err_res = abs(r / 2.0 - truth)
        residual_better = err_res < err_base - 1e-9
        residual_worse = err_res > err_base + 1e-9

        cmds = [
            ["HINCRBY", RES_LEARN_KEY, "n", 1],
            ["HINCRBY", RES_LEARN_KEY, "base_closer", 1 if (not residual_better and not residual_worse) or err_base <= err_res else 0],
            ["HINCRBY", RES_LEARN_KEY, "res_closer", 1 if residual_better else 0],
            ["HINCRBY", RES_LEARN_KEY, "res_worse", 1 if residual_worse else 0],
            ["HINCRBY", RES_LEARN_KEY, "disagree", 1 if base != res else 0],
            ["HSET", RES_LEARN_KEY, "last_ts", str(int(time.time()))],
            ["EXPIRE", RES_LEARN_KEY, 120 * 86400],
            ["DEL", RES_PENDING.format(mint)],
        ]
        # Fix base_closer logic cleanly in second pass
        await redis_pipe(client, cmds)

        # Rewrite base_closer accurately
        if residual_better:
            pass
        elif residual_worse:
            await redis_pipe(client, [["HINCRBY", RES_LEARN_KEY, "base_closer", 1]])
        else:
            await redis_pipe(client, [["HINCRBY", RES_LEARN_KEY, "tie", 1]])

        if "si_emit" in globals():
            await si_emit(client, "residual_judged", mint, {
                "bad": bad,
                "base": base,
                "residual": res,
                "residual_better": residual_better,
            })
    except Exception as e:
        print(f"[part86] residual_on_outcome: {e}")


@app.get("/residuals/stats", tags=["experimental"])
async def residuals_stats(request: Request):
    client = request.app.state.client
    if not PRED_ENABLED:
        return {"enabled": False}
    try:
        raw = await redis_pipe(client, [["HGETALL", RES_LEARN_KEY]])
        h = to_dict((raw or [{}])[0] or {})
        n = int(float(h.get("n", 0) or 0))
        res_c = int(float(h.get("res_closer", 0) or 0))
        return {
            "enabled": True,
            "n": n,
            "residual_closer": res_c,
            "base_closer": int(float(h.get("base_closer", 0) or 0)),
            "tie": int(float(h.get("tie", 0) or 0)),
            "res_worse": int(float(h.get("res_worse", 0) or 0)),
            "disagree": int(float(h.get("disagree", 0) or 0)),
            "residual_win_rate": round(res_c / n, 3) if n >= 5 else None,
            "ready": n >= 30,
            "last_ts": h.get("last_ts"),
            "version": VERSION,
            "note": "Compares residual_verdict vs base_verdict error to bad/good outcome. Not advice.",
        }
    except Exception as e:
        return {"enabled": True, "error": str(e)[:120]}


# Pending snapshot on every signal that has residuals
_build_prev_reslearn = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_reslearn(client, mint, security, prefetched)
    try:
        if isinstance(result, dict) and result.get("attention_residuals"):
            await _res_learn_record_pending(client, mint, result)
    except Exception:
        pass
    return result, status


# Hook outcome path
_prev_outcome_res = globals().get("on_outcome_for_si")


async def on_outcome_for_si(client, mint: str, bad: bool, meta: Optional[dict] = None, **kwargs):
    if callable(_prev_outcome_res):
        try:
            await _prev_outcome_res(client, mint, bad, meta, **kwargs)
        except TypeError:
            try:
                await _prev_outcome_res(client, mint, bad, meta)
            except Exception:
                pass
        except Exception:
            pass
    await residual_on_outcome(client, mint, bad, meta)


print(f"[part86] v{VERSION} Residual outcome learning → /residuals/stats + on_outcome_for_si")
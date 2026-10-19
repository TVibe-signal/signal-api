# ---------- v2.91: Deployer reputation SHADOW (from our outcomes only) ----------
# When a judged outcome is bad/ok, if we know creator/deployer, bump shadow counters.
# Never changes live verdict. GET /stats/deployer-shadow for research.
VERSION = "2.91.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Any, Dict, Optional

DEP_KEY = "si:shadow:deployer"
DEP_TTL = 120 * 86400


def _dep_field(meta: Optional[dict], result: Optional[dict] = None) -> Optional[str]:
    for src in (meta or {}, result or {}):
        if not isinstance(src, dict):
            continue
        for k in ("creator", "deployer", "deployer_wallet", "creator_wallet", "authority"):
            v = src.get(k)
            if isinstance(v, str) and 32 <= len(v) <= 54:
                return v
        cr = src.get("rugcheck") or src.get("security") or {}
        if isinstance(cr, dict):
            for k in ("creator", "deployer", "mintAuthority"):
                v = cr.get(k)
                if isinstance(v, str) and 32 <= len(v) <= 54 and v not in ("", "11111111111111111111111111111111"):
                    return v
    return None


async def deployer_shadow_on_outcome(
    client, mint: str, bad: bool, meta: Optional[dict] = None
) -> None:
    if not globals().get("PRED_ENABLED") or not client:
        return
    dep = _dep_field(meta)
    if not dep:
        return
    try:
        field_n = f"{dep}:n"
        field_bad = f"{dep}:bad"
        cmds = [
            ["HINCRBY", DEP_KEY, field_n, 1],
            ["HINCRBY", DEP_KEY, field_bad, 1 if bad else 0],
            ["EXPIRE", DEP_KEY, DEP_TTL],
        ]
        await redis_pipe(client, cmds)
    except Exception as e:
        print(f"[part110] deployer shadow: {e}")


_prev_out_110 = globals().get("on_outcome_for_si")


async def on_outcome_for_si(client, mint: str, bad: bool, meta: Optional[dict] = None, **kwargs):
    if callable(_prev_out_110):
        try:
            await _prev_out_110(client, mint, bad, meta, **kwargs)
        except TypeError:
            try:
                await _prev_out_110(client, mint, bad)
            except Exception:
                pass
        except Exception:
            pass
    await deployer_shadow_on_outcome(client, mint, bad, meta)


@app.get("/stats/deployer-shadow", tags=["accuracy"])
async def stats_deployer_shadow(request: Request, min_n: int = 3, limit: int = 30):
    """Shadow only — not used in live verdict."""
    client = request.app.state.client
    rows = []
    try:
        if PRED_ENABLED and client:
            raw = await redis_pipe(client, [["HGETALL", DEP_KEY]])
            h = to_dict((raw or [{}])[0] or {})
            agg: Dict[str, Dict[str, int]] = {}
            for k, v in h.items():
                if not isinstance(k, str) or ":" not in k:
                    continue
                dep, kind = k.rsplit(":", 1)
                if kind not in ("n", "bad"):
                    continue
                agg.setdefault(dep, {"n": 0, "bad": 0})
                agg[dep][kind] = int(float(v or 0))
            for dep, c in agg.items():
                n = c["n"]
                if n < max(1, min_n):
                    continue
                bad = c["bad"]
                rows.append({
                    "deployer": dep,
                    "n": n,
                    "bad": bad,
                    "bad_rate_pct": round(100.0 * bad / n, 1) if n else None,
                })
            rows.sort(key=lambda r: (-(r["bad_rate_pct"] or 0), -r["n"]))
            rows = rows[: max(1, min(limit, 100))]
    except Exception as e:
        return {"version": VERSION, "error": str(e)[:120], "rows": []}
    return {
        "version": VERSION,
        "shadow": True,
        "live_verdict_unchanged": True,
        "min_n": min_n,
        "rows": rows,
        "note": "Built only from our judged outcomes when creator/deployer was known. Not financial advice.",
    }


print(f"[part110] v{VERSION} deployer shadow → GET /stats/deployer-shadow")
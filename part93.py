# ---------- v2.71: Shadow avoid-recall rules (measure first, never override live) ----------
VERSION = "2.71.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Any, Dict, List, Optional

SHADOW_AVOID_KEY = "si:shadow:avoid_rules"
SHADOW_AVOID_PENDING = "si:shadow:avoid_pending:{}"
SHADOW_AVOID_TTL = 10 * 86400


def shadow_avoid_verdict(result: dict) -> Dict[str, Any]:
    """
    Stricter shadow policies aimed at higher recall than live avoid.
    Does NOT change decision.verdict.
    """
    risk = float(result.get("risk_score") or 0)
    flags = set(result.get("flags") or [])
    live = ((result.get("decision") or {}).get("verdict") or result.get("verdict") or "").lower()

    rules_hit: List[str] = []

    # R1: medium-high risk + newness/turnover (catch more rugs early)
    if risk >= 40 and flags.intersection({"brand_new_pair", "very_new_pair", "extreme_turnover", "extreme_volume_spike"}):
        rules_hit.append("risk40_new_or_spike")

    # R2: classic dump / concentration cluster
    if flags.intersection({"dump_risk", "extreme_holder_concentration", "dominant_holder"}) and risk >= 30:
        rules_hit.append("dump_or_concentration")

    # R3: dead / collapsed micro liq
    if flags.intersection({"dead_pool", "price_collapse_24h", "no_recent_trades"}) and risk >= 25:
        rules_hit.append("dead_or_collapse")

    # R4: residual suggests avoid while live is softer (if present)
    ar = result.get("attention_residuals") or {}
    if (ar.get("residual_verdict") or "").lower() == "avoid" and live in ("ok", "caution"):
        rules_hit.append("residual_avoid")

    shadow_verdict = "avoid" if rules_hit else live
    return {
        "live_verdict": live,
        "shadow_verdict": shadow_verdict,
        "rules_hit": rules_hit,
        "would_flag_avoid": bool(rules_hit),
        "note": "Shadow only — live decision unchanged. Tracked for recall experiments.",
        "version": VERSION,
    }


async def _shadow_avoid_pending(client, mint: str, payload: dict) -> None:
    if not PRED_ENABLED or not client:
        return
    try:
        await redis_pipe(client, [
            ["SET", SHADOW_AVOID_PENDING.format(mint), json.dumps(payload), "EX", SHADOW_AVOID_TTL],
            ["HINCRBY", SHADOW_AVOID_KEY, "emitted", 1],
            ["HINCRBY", SHADOW_AVOID_KEY, "flagged_avoid", 1 if payload.get("would_flag_avoid") else 0],
            ["EXPIRE", SHADOW_AVOID_KEY, 120 * 86400],
        ])
    except Exception:
        pass


async def shadow_avoid_on_outcome(client, mint: str, bad: bool, meta: Optional[dict] = None) -> None:
    if not PRED_ENABLED or not client:
        return
    try:
        raw = await redis_get(client, SHADOW_AVOID_PENDING.format(mint))
        if not raw:
            return
        snap = json.loads(raw)
        flagged = bool(snap.get("would_flag_avoid"))
        live = (snap.get("live_verdict") or "").lower()
        cmds = [
            ["HINCRBY", SHADOW_AVOID_KEY, "judged", 1],
            ["HINCRBY", SHADOW_AVOID_KEY, "bad", 1 if bad else 0],
            ["DEL", SHADOW_AVOID_PENDING.format(mint)],
            ["EXPIRE", SHADOW_AVOID_KEY, 120 * 86400],
        ]
        if flagged and bad:
            cmds.append(["HINCRBY", SHADOW_AVOID_KEY, "tp", 1])
        if flagged and not bad:
            cmds.append(["HINCRBY", SHADOW_AVOID_KEY, "fp", 1])
        if (not flagged) and bad and live != "avoid":
            cmds.append(["HINCRBY", SHADOW_AVOID_KEY, "fn_vs_live_miss", 1])
        if live == "avoid" and bad:
            cmds.append(["HINCRBY", SHADOW_AVOID_KEY, "live_tp", 1])
        await redis_pipe(client, cmds)
    except Exception as e:
        print(f"[part93] outcome: {e}")


_build_prev_sa = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_sa(client, mint, security, prefetched)
    try:
        if isinstance(result, dict):
            sa = shadow_avoid_verdict(result)
            result["shadow_avoid"] = sa
            await _shadow_avoid_pending(client, mint, sa)
    except Exception:
        pass
    return result, status


_prev_out_sa = globals().get("on_outcome_for_si")


async def on_outcome_for_si(client, mint: str, bad: bool, meta: Optional[dict] = None, **kwargs):
    if callable(_prev_out_sa):
        try:
            await _prev_out_sa(client, mint, bad, meta, **kwargs)
        except TypeError:
            try:
                await _prev_out_sa(client, mint, bad, meta)
            except Exception:
                pass
        except Exception:
            pass
    await shadow_avoid_on_outcome(client, mint, bad, meta)


@app.get("/stats/shadow-avoid", tags=["accuracy"])
async def stats_shadow_avoid(request: Request):
    client = request.app.state.client
    h = {}
    try:
        if PRED_ENABLED and client:
            raw = await redis_pipe(client, [["HGETALL", SHADOW_AVOID_KEY]])
            h = to_dict((raw or [{}])[0] or {})
    except Exception:
        pass
    judged = int(float(h.get("judged", 0) or 0))
    tp = int(float(h.get("tp", 0) or 0))
    fp = int(float(h.get("fp", 0) or 0))
    flagged = tp + fp
    return {
        "version": VERSION,
        "emitted": int(float(h.get("emitted", 0) or 0)),
        "flagged_avoid": int(float(h.get("flagged_avoid", 0) or 0)),
        "judged": judged,
        "true_positive": tp,
        "false_positive": fp,
        "fn_vs_live_miss": int(float(h.get("fn_vs_live_miss", 0) or 0)),
        "precision_pct": round(100.0 * tp / flagged, 1) if flagged >= 5 else None,
        "ready": judged >= 30,
        "note": "Shadow avoid rules only. Live verdict unchanged until a rule wins on precision+recall.",
    }


print(f"[part93] v{VERSION} shadow avoid-recall → signal.shadow_avoid + GET /stats/shadow-avoid")
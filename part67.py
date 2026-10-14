# ---------- v2.48.1: Debate vs Outcome Learning ----------
VERSION = "2.48.1"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Dict, Any

DEBATE_SCORE_KEY = "debate:persona"     # hash: persona -> n / correct
DEBATE_PENDING = "debate:pending:{}"    # mint -> {personas, meta, ts}

async def _record_debate_pending(client, mint: str, debate: dict):
    if not PRED_ENABLED or not client or not debate:
        return
    try:
        payload = {
            "meta": debate.get("meta_verdict"),
            "agreement": debate.get("agreement"),
            "personas": {
                p.get("persona"): p.get("verdict")
                for p in (debate.get("personas") or [])
                if p.get("persona")
            },
            "ts": int(time.time()),
        }
        await redis_pipe(client, [
            ["SET", DEBATE_PENDING.format(mint), json.dumps(payload), "EX", 36 * 3600],
        ])
    except Exception:
        pass

async def score_debate_against_outcome(client, mint: str, bad_outcome: bool, actual_verdict_hint: str = None):
    """
    Called when an outcome is known.
    bad_outcome=True means the token failed hard.
    A persona is 'correct' if:
      - it said avoid and bad_outcome is True
      - it said ok and bad_outcome is False
      - caution counts as partial (0.5)
    """
    if not PRED_ENABLED or not client:
        return
    try:
        raw = await redis_get(client, DEBATE_PENDING.format(mint))
        if not raw:
            return
        data = json.loads(raw)
        personas = data.get("personas") or {}
        cmds = []
        for name, verdict in personas.items():
            cmds.append(["HINCRBY", DEBATE_SCORE_KEY, f"{name}:n", 1])
            correct = 0.0
            if verdict == "avoid" and bad_outcome:
                correct = 1.0
            elif verdict == "ok" and not bad_outcome:
                correct = 1.0
            elif verdict == "caution":
                correct = 0.5
            cmds.append(["HINCRBYFLOAT", DEBATE_SCORE_KEY, f"{name}:correct", correct])
        # Meta verdict
        meta = data.get("meta")
        if meta:
            cmds.append(["HINCRBY", DEBATE_SCORE_KEY, "meta:n", 1])
            mc = 1.0 if ((meta == "avoid" and bad_outcome) or (meta == "ok" and not bad_outcome)) else (0.5 if meta == "caution" else 0.0)
            cmds.append(["HINCRBYFLOAT", DEBATE_SCORE_KEY, "meta:correct", mc])
        cmds.append(["DEL", DEBATE_PENDING.format(mint)])
        if cmds:
            await redis_pipe(client, cmds)
    except Exception:
        pass

async def get_debate_leaderboard(client) -> Dict[str, Any]:
    if not PRED_ENABLED or not client:
        return {}
    try:
        raw = await redis_pipe(client, [["HGETALL", DEBATE_SCORE_KEY]])
        h = to_dict((raw or [{}])[0] or {})
        stats = {}
        names = set()
        for k in h:
            if ":" in k:
                names.add(k.split(":")[0])
        for name in names:
            n = float(h.get(f"{name}:n", 0) or 0)
            c = float(h.get(f"{name}:correct", 0) or 0)
            stats[name] = {
                "n": int(n),
                "accuracy": round(c / n, 3) if n else None,
            }
        return stats
    except Exception:
        return {}

@app.get("/debate/scores", tags=["experimental"])
async def debate_scores(request: Request):
    client = request.app.state.client
    return {
        "persona_accuracy": await get_debate_leaderboard(client),
        "note": "Accuracy is measured only on tokens that later received an outcome label.",
    }

# Hook: store debate pending on each signal
_build_prev_debate_learn = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_debate_learn(client, mint, security, prefetched)
    try:
        deb = result.get("debate")
        if deb:
            await _record_debate_pending(client, mint, deb)
    except Exception:
        pass
    return result, status

# Optional: expose a helper so resolver / multi-horizon can call it later
async def on_outcome_for_si(client, mint: str, bad_outcome: bool):
    """Call this from outcome enrichment when a label is known."""
    await score_debate_against_outcome(client, mint, bad_outcome)
    # Also feed hypothesis counters if pending
    try:
        raw = await redis_get(client, f"hypo:pending:{mint}")
        if raw:
            matched = json.loads(raw)
            for hid in matched:
                await _touch_hypothesis(client, hid, bad=bad_outcome)
            await redis_pipe(client, [["DEL", f"hypo:pending:{mint}"]])
    except Exception:
        pass

print(f"[part67] v{VERSION} Debate vs Outcome Learning loaded")
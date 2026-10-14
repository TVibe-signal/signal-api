# ---------- v2.47: Causal Memory Graph (SI layer) ----------
VERSION = "2.47.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Dict, Any, List, Optional

CAUSAL_KEY = "causal:{}"           # causal:{mint} → list of events
CAUSAL_GLOBAL = "causal:global"    # recent global transitions
CAUSAL_MAX = 30
CAUSAL_TTL = 14 * 24 * 3600

def _event(kind: str, detail: dict) -> dict:
    return {
        "ts": int(time.time()),
        "kind": kind,
        "detail": detail,
    }

async def _append_causal(client, mint: str, event: dict):
    if not PRED_ENABLED or not client:
        return
    try:
        raw = json.dumps(event, separators=(",", ":"))
        await redis_pipe(client, [
            ["LPUSH", CAUSAL_KEY.format(mint), raw],
            ["LTRIM", CAUSAL_KEY.format(mint), 0, CAUSAL_MAX - 1],
            ["EXPIRE", CAUSAL_KEY.format(mint), CAUSAL_TTL],
            ["LPUSH", CAUSAL_GLOBAL, json.dumps({"mint": mint, **event}, separators=(",", ":"))],
            ["LTRIM", CAUSAL_GLOBAL, 0, 99],
            ["EXPIRE", CAUSAL_GLOBAL, CAUSAL_TTL],
        ])
    except Exception:
        pass

async def get_causal_chain(client, mint: str) -> List[dict]:
    if not PRED_ENABLED or not client:
        return []
    try:
        res = await redis_pipe(client, [["LRANGE", CAUSAL_KEY.format(mint), 0, CAUSAL_MAX - 1]])
        out = []
        for raw in (res or [[]])[0] or []:
            try:
                out.append(json.loads(raw))
            except Exception:
                continue
        return out
    except Exception:
        return []

def _detect_transitions(prev: dict, curr: dict) -> List[dict]:
    """Detect meaningful state changes between two signal snapshots."""
    events = []
    try:
        # Attention spike
        pa = (prev.get("community") or {}).get("attention") or {}
        ca = (curr.get("community") or {}).get("attention") or {}
        if ca.get("1h", 0) >= 8 and ca.get("1h", 0) >= (pa.get("1h", 0) + 5):
            events.append(_event("attention_spike", {
                "from": pa.get("1h", 0),
                "to": ca.get("1h", 0),
            }))

        # Community shift
        pc = (prev.get("community") or {}).get("conviction") or {}
        cc = (curr.get("community") or {}).get("conviction") or {}
        if pc.get("dominant") and cc.get("dominant") and pc["dominant"] != cc["dominant"]:
            events.append(_event("community_shift", {
                "from": pc["dominant"],
                "to": cc["dominant"],
                "n": cc.get("n"),
            }))

        # Verdict change
        pv = (prev.get("decision") or {}).get("verdict") or prev.get("verdict")
        cv = (curr.get("decision") or {}).get("verdict") or curr.get("verdict")
        if pv and cv and pv != cv:
            events.append(_event("verdict_change", {"from": pv, "to": cv}))

        # Debate disagreement
        deb = curr.get("debate") or {}
        if deb.get("agreement") is not None and deb["agreement"] < 0.55:
            events.append(_event("debate_split", {
                "meta": deb.get("meta_verdict"),
                "agreement": deb.get("agreement"),
            }))

        # Risk jump
        pr = float(prev.get("risk_score") or 0)
        cr = float(curr.get("risk_score") or 0)
        if cr - pr >= 15:
            events.append(_event("risk_jump", {"from": pr, "to": cr}))

        # HG signals
        hg = curr.get("_hg") or {}
        if hg.get("known_dumper_present"):
            events.append(_event("known_dumper", {"n": len(hg.get("dumpers") or [])}))
        if hg.get("cluster_high_risk"):
            events.append(_event("cluster_high_risk", hg.get("cluster") or {}))

    except Exception:
        pass
    return events

# Keep a tiny in-memory previous snapshot (per process)
_PREV_SNAP: Dict[str, dict] = {}

_build_prev_causal = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_causal(client, mint, security, prefetched)

    try:
        prev = _PREV_SNAP.get(mint)
        if prev and isinstance(result, dict):
            transitions = _detect_transitions(prev, result)
            for ev in transitions:
                await _append_causal(client, mint, ev)

            # Attach short causal summary when interesting
            if transitions:
                chain = await get_causal_chain(client, mint)
                recent_kinds = [e.get("kind") for e in chain[:6]]
                result["causal"] = {
                    "recent": recent_kinds,
                    "last_events": transitions[:3],
                }

        # Store compact previous state
        if isinstance(result, dict):
            _PREV_SNAP[mint] = {
                "risk_score": result.get("risk_score"),
                "verdict": (result.get("decision") or {}).get("verdict") or result.get("verdict"),
                "community": result.get("community"),
                "debate": result.get("debate"),
                "_hg": result.get("_hg"),
            }
            # Limit memory
            if len(_PREV_SNAP) > 500:
                _PREV_SNAP.clear()
    except Exception:
        pass

    return result, status

@app.get("/causal/{mint}", tags=["experimental"])
async def causal_chain(mint: str, request: Request):
    """Return the recent causal event chain for a mint."""
    if not MINT_RE.match(mint):
        raise HTTPException(400, "Invalid mint")
    client = request.app.state.client
    chain = await get_causal_chain(client, mint)
    return {
        "mint": mint,
        "events": chain,
        "n": len(chain),
    }

print(f"[part65] v{VERSION} Causal Memory Graph loaded")
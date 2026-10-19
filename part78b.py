# part78b.py - keep decision.verdict in step with the capped verdict (v2.57.1)
# part78 caps the top-level "verdict" from ok to caution when there are unresolved unknowns,
# but left decision.verdict at "ok". This wraps build_signal once more and syncs it.
# Only ever downgrades; never upgrades.
# Loader line: put it right AFTER part78 and before part79:  ("part78b.py", 0, "SKIP"),

_RANK_78B = {"ok": 0, "caution": 1, "avoid": 2}


def _sync_decision_verdict(r):
    dec = r.get("decision") if isinstance(r, dict) else None
    top = r.get("verdict") if isinstance(r, dict) else None
    cur = dec.get("verdict") if isinstance(dec, dict) else None
    if (isinstance(dec, dict) and r.get("verdict_capped_by")
            and top in _RANK_78B and cur in _RANK_78B and _RANK_78B[top] > _RANK_78B[cur]):
        dec["verdict_raw"] = cur
        dec["verdict"] = top
        dec["capped_by"] = r["verdict_capped_by"]
    return r


_build_prev_78b = build_signal


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_78b(client, mint, security, *args, **kwargs)
    try:
        if isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], dict):
            return _sync_decision_verdict(res[0]), res[1]
        if isinstance(res, dict):
            return _sync_decision_verdict(res)
    except Exception:
        pass  # never break the response
    return res


print("[part78b] decision.verdict now follows the capped verdict")

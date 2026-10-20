# part116.py — System circuit breaker (source health → soft degrade)
# Does NOT block the API forever. Opens when upstream is sick; agents see system_stress.
VERSION = "2.93.0"
app.version = VERSION
app.openapi_schema = None

import time
from typing import Any, Dict, Optional

_CB = {
    "state": "closed",          # closed | open | half
    "opened_at": 0.0,
    "reason": "",
    "open_for_s": 90,           # stay open at least this long
    "dex_fail_streak": 0,
    "rpc_fail_streak": 0,
}

_CB_OPEN_S = 90
_CB_STREAK = 3


def circuit_status() -> Dict[str, Any]:
    now = time.time()
    st = dict(_CB)
    if st["state"] == "open" and now - st["opened_at"] >= st.get("open_for_s", _CB_OPEN_S):
        st["state"] = "half"
    st["now"] = now
    return st


def circuit_record_source(name: str, ok: bool) -> None:
    key = "dex_fail_streak" if name in ("dexscreener", "dex") else (
        "rpc_fail_streak" if name in ("solana_rpc", "rpc") else None
    )
    if not key:
        return
    if ok:
        _CB[key] = 0
    else:
        _CB[key] = int(_CB.get(key) or 0) + 1
    if _CB["dex_fail_streak"] >= _CB_STREAK and _CB["rpc_fail_streak"] >= _CB_STREAK:
        if _CB["state"] != "open":
            _CB["state"] = "open"
            _CB["opened_at"] = time.time()
            _CB["reason"] = "dex_and_rpc_failing"
            print("[part116] circuit OPEN:", _CB["reason"])
    elif _CB["state"] == "half" and ok and name in ("dexscreener", "dex", "solana_rpc", "rpc"):
        _CB["state"] = "closed"
        _CB["reason"] = ""
        print("[part116] circuit CLOSED")


def circuit_apply_to_result(r: dict) -> dict:
    if not isinstance(r, dict):
        return r
    st = circuit_status()
    r["system_stress"] = {
        "state": st["state"],
        "reason": st.get("reason") or None,
        "note": "When open/half, prefer smaller size or wait; data may be stale or partial.",
    }
    if st["state"] in ("open", "half"):
        dec = r.get("decision") if isinstance(r.get("decision"), dict) else None
        if dec is not None:
            # never upgrade; only soft-warn
            cautions = list(dec.get("cautions") or [])
            msg = "System stress: upstream degraded (circuit %s)" % st["state"]
            if msg not in cautions:
                cautions.append(msg)
            dec["cautions"] = cautions
            top = r.get("verdict")
            if top == "ok":
                r["verdict"] = "caution"
                r["verdict_capped_by"] = r.get("verdict_capped_by") or "circuit_breaker"
            if dec.get("verdict") == "ok":
                dec["verdict_raw"] = dec.get("verdict_raw") or "ok"
                dec["verdict"] = "caution"
    return r


_build_prev_116 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_116(client, mint, security, *args, **kwargs)
    try:
        # light health sample from sources block if present
        body = res[0] if isinstance(res, tuple) else res
        if isinstance(body, dict):
            src = body.get("sources") or {}
            if isinstance(src, dict):
                for k, v in src.items():
                    if isinstance(v, dict) and "status" in v:
                        circuit_record_source(k, v.get("status") == "ok")
                    elif isinstance(v, str):
                        circuit_record_source(k, v == "ok")
            circuit_apply_to_result(body)
        return res
    except Exception as e:
        print("[part116] apply:", e)
        return res


@app.get("/system/circuit", tags=["ops"], include_in_schema=False)
async def system_circuit():
    return {"version": VERSION, **circuit_status()}


print(f"[part116] v{VERSION} circuit breaker → GET /system/circuit")
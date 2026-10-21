# part116.py - System circuit breaker (source health -> soft degrade) (v2.93.1, reviewed)
# Opens when BOTH DexScreener and Solana RPC fail 3 times in a row; agents then see system_stress.
# Review fixes vs v2.93.0:
#   - it could never close again (the "half" state was only computed in a copy), so after ONE outage every
#     verdict stayed capped to caution forever. It now closes after the hold time as soon as a source answers ok.
#   - verdict_capped_by stays a list (part78 uses a list); major assets (SOL, USDC...) are not capped.
VERSION = "2.93.1"
app.version = VERSION
app.openapi_schema = None

import time
from typing import Any, Dict

_CB = {"state": "closed", "opened_at": 0.0, "reason": "", "open_for_s": 90,
       "dex_fail_streak": 0, "rpc_fail_streak": 0}
_CB_STREAK = 3


def circuit_status() -> Dict[str, Any]:
    now = time.time()
    st = dict(_CB)
    if st["state"] == "open" and now - st["opened_at"] >= st["open_for_s"]:
        st["state"] = "half"
    st["now"] = now
    return st


def circuit_record_source(name: str, ok: bool) -> None:
    key = "dex_fail_streak" if name in ("dexscreener", "dex") else (
        "rpc_fail_streak" if name in ("solana_rpc", "rpc") else None)
    if not key:
        return
    _CB[key] = 0 if ok else int(_CB.get(key) or 0) + 1
    now = time.time()
    both_failing = _CB["dex_fail_streak"] >= _CB_STREAK and _CB["rpc_fail_streak"] >= _CB_STREAK
    if both_failing:
        if _CB["state"] == "closed":
            _CB["state"], _CB["opened_at"], _CB["reason"] = "open", now, "dex_and_rpc_failing"
            print("[part116] circuit OPEN:", _CB["reason"])
        elif now - _CB["opened_at"] >= _CB["open_for_s"]:
            _CB["opened_at"] = now  # still failing after the hold time: stay open another round
    elif _CB["state"] == "open" and ok and now - _CB["opened_at"] >= _CB["open_for_s"]:
        _CB["state"], _CB["reason"] = "closed", ""
        print("[part116] circuit CLOSED")


def _add_cap(r: dict, tag: str) -> None:
    cur = r.get("verdict_capped_by")
    lst = list(cur) if isinstance(cur, list) else ([str(cur)] if cur else [])
    if tag not in lst:
        lst.append(tag)
    r["verdict_capped_by"] = lst


def circuit_apply_to_result(r: dict) -> dict:
    if not isinstance(r, dict):
        return r
    st = circuit_status()
    r["system_stress"] = {
        "state": st["state"],
        "reason": st.get("reason") or None,
        "note": "When open/half, prefer smaller size or wait; data may be stale or partial.",
    }
    if st["state"] in ("open", "half") and r.get("asset_class") != "major":
        dec = r.get("decision") if isinstance(r.get("decision"), dict) else None
        if dec is not None:
            cautions = list(dec.get("cautions") or [])
            msg = "System stress: upstream degraded (circuit %s)" % st["state"]
            if msg not in cautions:
                cautions.append(msg)
            dec["cautions"] = cautions
            if r.get("verdict") == "ok":
                r["verdict"] = "caution"
                _add_cap(r, "circuit_breaker")
            if dec.get("verdict") == "ok":
                dec["verdict_raw"] = dec.get("verdict_raw") or "ok"
                dec["verdict"] = "caution"
    return r


_build_prev_116 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_116(client, mint, security, *args, **kwargs)
    try:
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


print(f"[part116] v{VERSION} circuit breaker (auto-closes) -> GET /system/circuit")

"""TVibe client gate — fail-closed + fib retry + reject stale payloads.

Env: API_BASE, MAX_RISK, MAX_LOSS_PCT, MIN_LIQ, REQUIRE_PASS, CHECK_EXIT,
     HTTP_RETRIES, MAX_STALE_S (default 120 — hard ceiling beyond expires_at)

NFA.
"""
from __future__ import annotations

import os
import time
from typing import Any, List, Tuple

import httpx

try:
    from retry_fib import with_fib_retry, fib_sleep
except ImportError:
    try:
        from examples.retry_fib import with_fib_retry, fib_sleep  # type: ignore
    except ImportError:
        def fib_sleep(i: int) -> float:
            return (1.0, 2.0, 3.0, 5.0, 8.0, 13.0)[min(max(i, 0), 5)]

        def with_fib_retry(fn, retries=4, retry_on=(429, 503, 502)):
            last = None
            for a in range(retries + 1):
                try:
                    return fn()
                except httpx.HTTPStatusError as e:
                    last = e
                    code = e.response.status_code if e.response is not None else None
                    if code not in retry_on or a >= retries:
                        raise
                    time.sleep(fib_sleep(a))
                except httpx.TransportError as e:
                    last = e
                    if a >= retries:
                        raise
                    time.sleep(fib_sleep(a))
            raise last  # type: ignore

API = os.getenv("API_BASE", "https://signal-api-24q4.onrender.com").rstrip("/")
MAX_RISK = float(os.getenv("MAX_RISK", "30"))
MAX_LOSS = float(os.getenv("MAX_LOSS_PCT", "5"))
MIN_LIQ = float(os.getenv("MIN_LIQ", "50000"))
REQUIRE_PASS = os.getenv("REQUIRE_PASS", "1").lower() in ("1", "true", "yes")
CHECK_EXIT_DEFAULT = os.getenv("CHECK_EXIT", "1").lower() in ("1", "true", "yes")
HTTP_RETRIES = max(0, int(os.getenv("HTTP_RETRIES", "4")))
MAX_STALE_S = max(15, int(os.getenv("MAX_STALE_S", "120")))


def _find_floats(obj: Any, key: str) -> List[float]:
    out: List[float] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, (int, float)):
                out.append(float(v))
            else:
                out.extend(_find_floats(v, key))
    elif isinstance(obj, list):
        for x in obj:
            out.extend(_find_floats(x, key))
    return out


def _get_agent(mint: str) -> dict:
    url = f"{API}/omni"
    params = {"mint": mint, "view": "agent"}

    def _once() -> dict:
        with httpx.Client(timeout=55.0) as client:
            r = client.get(url, params=params)
            if r.status_code in (429, 503, 502):
                r.raise_for_status()
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise RuntimeError("bad_json")
            return data

    return with_fib_retry(_once, retries=HTTP_RETRIES)


def _stale_reason(d: dict) -> str | None:
    now = time.time()
    exp = d.get("expires_at")
    if exp is not None:
        try:
            if now > float(exp):
                return "expired_past_expires_at"
        except (TypeError, ValueError):
            pass
    as_of = d.get("as_of")
    vfs = d.get("valid_for_s")
    if as_of is not None:
        try:
            age = now - float(as_of)
            limit = float(vfs) if vfs is not None else float(MAX_STALE_S)
            limit = min(limit, float(MAX_STALE_S))
            if age > limit:
                return f"stale_age>{limit}s"
        except (TypeError, ValueError):
            pass
    return None


def safe_to_buy(mint: str, *, check_exit: bool | None = None) -> Tuple[bool, str]:
    check_exit = CHECK_EXIT_DEFAULT if check_exit is None else check_exit
    mint = (mint or "").strip()
    if not mint or len(mint) < 32:
        return False, "invalid_mint"
    try:
        d = _get_agent(mint)
    except Exception as e:
        return False, f"fetch_error:{type(e).__name__}"

    if d.get("error"):
        return False, f"api_error:{d.get('error')}"

    stale = _stale_reason(d)
    if stale:
        return False, stale

    action = str(d.get("action") or "").lower()
    if action == "skip":
        return False, "action_skip"
    if action == "review":
        return False, "action_review"

    filt = d.get("filter") if isinstance(d.get("filter"), dict) else {}
    if REQUIRE_PASS and filt.get("pass") is not True:
        return False, "filter_not_pass"

    if d.get("unknowns"):
        return False, "unknowns_present"

    try:
        risk = d.get("risk_score")
        if risk is not None and float(risk) > MAX_RISK:
            return False, f"risk_score>{MAX_RISK}"
    except (TypeError, ValueError):
        return False, "risk_score_invalid"

    liq = d.get("liquidity_usd")
    if liq is None:
        fl = _find_floats(d, "liquidity_usd")
        liq = fl[0] if fl else None
    try:
        if liq is not None and float(liq) < MIN_LIQ:
            return False, f"liquidity<{MIN_LIQ}"
    except (TypeError, ValueError):
        pass

    if check_exit:
        losses = _find_floats(d, "loss_vs_market_pct")
        if losses and max(losses) > MAX_LOSS:
            return False, f"exit_loss>{MAX_LOSS}"

    if action == "pass" or filt.get("pass") is True:
        return True, "ok_pass"
    return False, "no_clear_pass"


if __name__ == "__main__":
    import sys

    m = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not m:
        print("usage: python gate.py <MINT>")
        raise SystemExit(2)
    ok, reason = safe_to_buy(m)
    print({"ok": ok, "reason": reason, "nfa": True})

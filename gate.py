"""TVibe buy-gate helper for external bots (client-side, not part of the API server).

Usage:
    from gate import safe_to_buy
    ok, reason = safe_to_buy(mint)

Env:
    API_BASE       default https://signal-api-24q4.onrender.com
    MAX_RISK       default 30
    MAX_LOSS_PCT   default 5
    MIN_LIQ        default 50000
    REQUIRE_PASS   default 1
    CHECK_EXIT     default 1
    HTTP_RETRIES   default 4 (fib backoff on 429/503)

Fail-closed. NFA.
"""
from __future__ import annotations

import os
from typing import Any, List, Tuple

import httpx

try:
    from retry_fib import with_fib_retry
except ImportError:
    from examples.retry_fib import with_fib_retry  # type: ignore

API = os.getenv("API_BASE", "https://signal-api-24q4.onrender.com").rstrip("/")
MAX_RISK = float(os.getenv("MAX_RISK", "30"))
MAX_LOSS = float(os.getenv("MAX_LOSS_PCT", "5"))
MIN_LIQ = float(os.getenv("MIN_LIQ", "50000"))
REQUIRE_PASS = os.getenv("REQUIRE_PASS", "1").lower() in ("1", "true", "yes")
CHECK_EXIT_DEFAULT = os.getenv("CHECK_EXIT", "1").lower() in ("1", "true", "yes")
HTTP_RETRIES = max(0, int(os.getenv("HTTP_RETRIES", "4")))


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


def safe_to_buy(mint: str, *, check_exit: bool | None = None) -> Tuple[bool, str]:
    """Return (ok, reason). Fail-closed on errors."""
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

    action = str(d.get("action") or "").lower()
    if action == "skip":
        return False, "action_skip"
    if action == "review":
        return False, "action_review"

    filt = d.get("filter") if isinstance(d.get("filter"), dict) else {}
    if REQUIRE_PASS and filt.get("pass") is not True:
        return False, "filter_not_pass"

    unknowns = d.get("unknowns") or []
    if unknowns:
        return False, "unknowns_present"

    risk = d.get("risk_score")
    try:
        if risk is not None and float(risk) > MAX_RISK:
            return False, f"risk_score>{MAX_RISK}"
    except (TypeError, ValueError):
        return False, "risk_score_invalid"

    # liquidity if present
    liq = d.get("liquidity_usd")
    if liq is None:
        floats = _find_floats(d, "liquidity_usd")
        liq = floats[0] if floats else None
    try:
        if liq is not None and float(liq) < MIN_LIQ:
            return False, f"liquidity<{MIN_LIQ}"
    except (TypeError, ValueError):
        pass

    if check_exit:
        losses = _find_floats(d, "loss_vs_market_pct")
        if losses and max(losses) > MAX_LOSS:
            return False, f"exit_loss>{MAX_LOSS}"

    if action and action != "pass":
        return False, f"action_{action}"

    # require explicit pass action when present
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

"""TVibe buy-gate helper for external bots (client-side, not part of the API server).

Usage:
    from gate import safe_to_buy
    ok, reason = safe_to_buy(mint)

Env:
    API_BASE       default https://signal-api-24q4.onrender.com
    MAX_RISK       default 30 (heuristic risk_score 0-100; higher = worse)
    MAX_LOSS_PCT   default 5  (max exit loss_vs_market_pct)
    MIN_LIQ        default 50000 (USD)
    REQUIRE_PASS   default 1  (require filter.pass == true)
    CHECK_EXIT     default 1

Fail-closed: network errors or missing fields => do not buy.

NFA: This is a policy helper around TVibe heuristics, not financial advice.
"""
from __future__ import annotations

import os
from typing import Any, List, Tuple

import httpx

API = os.getenv("API_BASE", "https://signal-api-24q4.onrender.com").rstrip("/")
MAX_RISK = float(os.getenv("MAX_RISK", "30"))
MAX_LOSS = float(os.getenv("MAX_LOSS_PCT", "5"))
MIN_LIQ = float(os.getenv("MIN_LIQ", "50000"))
REQUIRE_PASS = os.getenv("REQUIRE_PASS", "1").lower() in ("1", "true", "yes")
CHECK_EXIT_DEFAULT = os.getenv("CHECK_EXIT", "1").lower() in ("1", "true", "yes")


def _find_floats(obj: Any, key: str) -> List[float]:
    out: List[float] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, (int, float)):
                out.append(float(v))
            else:
                out.extend(_find_floats(v, key))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_find_floats(v, key))
    return out


def _verdict(payload: dict) -> str | None:
    dec = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    v = dec.get("verdict") or payload.get("verdict")
    return str(v).lower() if v is not None else None


def _risk(payload: dict) -> float | None:
    dec = payload.get("decision") if isinstance(payload.get("decision"), dict) else {}
    r = dec.get("risk_score")
    if r is None:
        r = payload.get("risk_score")
    try:
        return float(r) if r is not None else None
    except (TypeError, ValueError):
        return None


def _filter_pass(payload: dict) -> bool | None:
    f = payload.get("filter")
    if isinstance(f, dict) and "pass" in f:
        return bool(f.get("pass"))
    return None


def safe_to_buy(mint: str, check_exit: bool | None = None) -> Tuple[bool, str]:
    """Return (allowed, reason). Fail-closed on errors or incomplete data."""
    mint = (mint or "").strip()
    if not mint or len(mint) < 32:
        return False, "invalid_mint"
    do_exit = CHECK_EXIT_DEFAULT if check_exit is None else bool(check_exit)

    try:
        with httpx.Client(timeout=30.0) as client:
            # Agent-oriented omni view when available; falls back to full omni fields.
            r = client.get(f"{API}/omni", params={"mint": mint, "view": "agent"})
            if r.status_code == 429:
                retry = None
                try:
                    retry = r.json().get("error", {}).get("retry_after_s") or r.json().get("retry_after_s")
                except Exception:
                    pass
                return False, f"rate_limited retry_after_s={retry}"
            if r.status_code >= 500:
                return False, f"upstream_http_{r.status_code}"
            data = r.json()
            if not isinstance(data, dict):
                return False, "bad_payload"

            if data.get("ok") is False and data.get("error"):
                err = data["error"] if isinstance(data["error"], dict) else {}
                return False, f"api_error:{err.get('code') or data.get('error')}"

            verdict = _verdict(data)
            if verdict in (None, "avoid"):
                return False, f"verdict={verdict}"

            fp = _filter_pass(data)
            if REQUIRE_PASS and fp is False:
                return False, "filter.pass=false"
            if REQUIRE_PASS and fp is None and verdict != "ok":
                # Agent view always has filter; if missing, be strict when not ok
                return False, "filter.pass_missing"

            risk = _risk(data)
            if risk is None or risk > MAX_RISK:
                return False, f"risk={risk} max={MAX_RISK}"

            liq = data.get("liquidity_usd")
            try:
                liq_f = float(liq) if liq is not None else 0.0
            except (TypeError, ValueError):
                liq_f = 0.0
            if liq_f < MIN_LIQ:
                return False, f"liq={liq_f:.0f} < {MIN_LIQ:.0f}"

            action = (data.get("action") or "").lower()
            if action == "skip":
                return False, "action=skip"

            if do_exit:
                er = client.get(f"{API}/exit", params={"mint": mint})
                if er.status_code >= 400:
                    return False, f"exit_http_{er.status_code}"
                exit_data = er.json()
                losses = _find_floats(exit_data, "loss_vs_market_pct")
                if not losses:
                    return False, "exit_cost_missing"
                worst = max(losses)
                if worst > MAX_LOSS:
                    return False, f"sell_cost={worst:.1f}% > {MAX_LOSS}%"

            return True, (
                f"ok verdict={verdict} risk={risk} liq={liq_f:.0f} "
                f"rules={data.get('rules_version')}"
            )
    except Exception as ex:
        return False, f"error:{ex.__class__.__name__}"


if __name__ == "__main__":
    import sys

    m = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    if not m:
        print("usage: python gate.py <MINT>")
        raise SystemExit(2)
    ok, why = safe_to_buy(m)
    print(("ALLOW" if ok else "DENY"), why)

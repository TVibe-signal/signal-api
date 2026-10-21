# part119.py - Phase 1: light sell simulation via /exit (Jupiter quote) (v2.94.1, reviewed)
# Not a full VM sandbox. A quote does NOT prove every honeypot is detectable.
# Review fixes vs v2.94.0:
#   - when Jupiter was unavailable / rate-limited, the old code treated "no route" as honeypot risk and capped
#     the verdict to caution. An unavailable quote is now UNKNOWN: no warning, no cap.
#   - /exit itself builds a market verdict, so calling /exit from build_signal could call build_signal again
#     (endless nesting). A context flag now blocks that.
#   - a slow quote no longer holds every /omni for ~13s: we wait at most ~6s; the quote keeps loading in the
#     background and the next call uses the cached result. One in-flight request per mint.
#   - no `sizes` parameter (it created a second cache entry next to the home page's /exit call).
#   - major assets are skipped; cache is bounded; verdict_capped_by stays a list.
# Switch off any time with the env var SELL_SIM=0 (each new token costs one Jupiter quote while it is on).
VERSION = "2.94.1"
app.version = VERSION
app.openapi_schema = None

import asyncio
import contextvars
import os
import time
from typing import Any, Dict, Optional

_SIM_TTL_S = 120
_SIM_FAIL_TTL_S = 20
_SIM_WAIT_S = 6.0
_SIM_FETCH_TIMEOUT_S = 15.0
_SIM_SIZE_USD = 100.0
_SIM_MAX = 500
_SIM_CACHE: Dict[str, tuple] = {}      # mint -> (stored_at, ttl, sim)
_SIM_INFLIGHT: Dict[str, Any] = {}
_IN_SIM = contextvars.ContextVar("tv_in_sim", default=False)
_BAD_GRADES = ("bad", "poor", "fail")


def _band(loss: Optional[float]) -> str:
    if loss is None:
        return "unknown"
    return "tight" if loss < 1 else "moderate" if loss < 3 else "wide" if loss < 8 else "extreme"


def _sim_from_exit(body: dict) -> dict:
    ex = body.get("exit") if isinstance(body, dict) else None
    if not isinstance(ex, dict):
        ex = body if isinstance(body, dict) else {}
    base = {"kind": "jupiter_quote_sim", "size_usd": _SIM_SIZE_USD, "mev_protection": False}
    if ex.get("available") is not True:
        return {**base, "status": "unavailable", "sell_ok": None, "honeypot_risk_heuristic": None,
                "note": "Sell quote unavailable right now (%s). Not proof of safety or danger."
                        % (str(ex.get("reason") or "no quote")[:90])}
    route = ex.get("exit_route_found")
    grade = ex.get("grade") or ex.get("exit_verdict") or "unknown"
    loss = receives = None
    levels = ex.get("levels") or []
    if levels and isinstance(levels[0], dict):
        try:
            loss = float(levels[0].get("loss_vs_market_pct"))
        except (TypeError, ValueError):
            loss = None
        try:
            receives = float(levels[0].get("sell_receives_usd"))
        except (TypeError, ValueError):
            receives = None
    risk = (route is False) or (loss is not None and loss >= 25) or (str(grade).lower() in _BAD_GRADES)
    if route is False or (loss is not None and loss >= 50):
        sell_ok = False
    elif route is True:
        sell_ok = True
    else:
        sell_ok = None
    return {**base, "status": "ok", "sell_ok": sell_ok, "route_found": route, "grade": grade,
            "loss_vs_market_pct": loss, "sell_receives_usd": receives, "slippage_band": _band(loss),
            "honeypot_risk_heuristic": bool(risk),
            "note": "Based on a Jupiter sell quote vs market - not a full contract sandbox. "
                    "Cannot detect every sell-block. Not financial advice."}


async def _exit_call(mint: str):
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal",
                                 timeout=_SIM_FETCH_TIMEOUT_S) as c:
        r = await c.get("/exit", params={"mint": mint}, headers={"accept": "application/json"})
        return r.status_code, (r.json() if r.status_code == 200 else None)


def _cache_put(mint: str, ttl: float, sim: Optional[dict]) -> None:
    now = time.time()
    if len(_SIM_CACHE) >= _SIM_MAX:
        for k in [k for k, v in _SIM_CACHE.items() if now - v[0] >= v[1]]:
            _SIM_CACHE.pop(k, None)
        while len(_SIM_CACHE) >= _SIM_MAX:
            _SIM_CACHE.pop(min(_SIM_CACHE, key=lambda k: _SIM_CACHE[k][0]), None)
    _SIM_CACHE[mint] = (now, ttl, sim)


async def _fetch_sim(mint: str) -> Optional[dict]:
    tok = _IN_SIM.set(True)  # anything /exit calls inside must not start another sim
    try:
        status, data = await _exit_call(mint)
        if status != 200 or not isinstance(data, dict):
            _cache_put(mint, _SIM_FAIL_TTL_S, None)
            return None
        sim = _sim_from_exit(data)
        _cache_put(mint, _SIM_TTL_S if sim.get("status") == "ok" else _SIM_FAIL_TTL_S, sim)
        return sim
    except Exception as e:
        print("[part119] sim fetch:", str(e)[:120])
        _cache_put(mint, _SIM_FAIL_TTL_S, None)
        return None
    finally:
        _IN_SIM.reset(tok)


async def _get_sim(mint: str) -> Optional[dict]:
    hit = _SIM_CACHE.get(mint)
    if hit and time.time() - hit[0] < hit[1]:
        return hit[2]
    task = _SIM_INFLIGHT.get(mint)
    if task is None:
        task = asyncio.ensure_future(_fetch_sim(mint))
        _SIM_INFLIGHT[mint] = task
        task.add_done_callback(lambda t, m=mint: _SIM_INFLIGHT.pop(m, None))
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout=_SIM_WAIT_S)
    except Exception:
        return None  # the task keeps running; the next call finds the cached result


def _add_cap(body: dict, tag: str) -> None:
    cur = body.get("verdict_capped_by")
    lst = list(cur) if isinstance(cur, list) else ([str(cur)] if cur else [])
    if tag not in lst:
        lst.append(tag)
    body["verdict_capped_by"] = lst


def _apply_sim_to_signal(body: dict, sim: dict) -> dict:
    body["sim"] = sim
    dec = body.get("decision") if isinstance(body.get("decision"), dict) else None
    if dec is None or sim.get("status") != "ok":
        return body
    cautions = list(dec.get("cautions") or [])
    if sim.get("honeypot_risk_heuristic"):
        msg = "Sell quote weak or missing (possible sell friction)"
        if msg not in cautions:
            cautions.append(msg)
        if body.get("verdict") == "ok":
            body["verdict"] = "caution"
            _add_cap(body, "sell_sim")
        if dec.get("verdict") == "ok":
            dec["verdict_raw"] = dec.get("verdict_raw") or "ok"
            dec["verdict"] = "caution"
            dec["capped_by"] = dec.get("capped_by") or ["sell_sim"]
    elif sim.get("sell_ok") and sim.get("slippage_band") in ("wide", "extreme"):
        msg = "Sell quote slippage is %s (about %s%% below market)" % (sim.get("slippage_band"), sim.get("loss_vs_market_pct"))
        if msg not in cautions:
            cautions.append(msg)
    dec["cautions"] = cautions
    dec["unknowns"] = [u for u in (dec.get("unknowns") or [])
                       if "Exit cost not checked" not in str(u) and "Slippage/exit:" not in str(u)]
    return body


_build_prev_119 = globals().get("build_signal")


async def build_signal(client, mint, security, *args, **kwargs):
    res = await _build_prev_119(client, mint, security, *args, **kwargs)
    if _IN_SIM.get() or os.environ.get("SELL_SIM", "1") == "0":
        return res  # inside our own /exit call, or switched off with SELL_SIM=0
    try:
        body = res[0] if isinstance(res, tuple) else res
        if not isinstance(body, dict):
            return res
        if body.get("asset_class") == "major" or (body.get("decision") or {}).get("asset_class") == "major":
            return res
        st = globals().get("circuit_status")
        if callable(st):
            try:
                if (st() or {}).get("state") == "open":
                    body["sim"] = {"kind": "skipped", "note": "Upstream stressed - sell quote skipped"}
                    return res
            except Exception:
                pass
        sim = await _get_sim(str(mint))
        if sim is None:
            body["sim"] = {"kind": "jupiter_quote_sim", "status": "pending", "sell_ok": None,
                           "note": "Sell quote not ready yet. Not proof of safety or danger."}
        else:
            _apply_sim_to_signal(body, sim)
        return res
    except Exception as e:
        print("[part119] wrap:", str(e)[:120])
        return res


print(f"[part119] v{VERSION} sell-sim via /exit (unavailable = unknown, no recursion) -> sim.* on signal/omni")

"""part90 - Shadow signals (v2.68.0).
Adds NO field to API responses and changes NO verdict. It only records
extra signals to Redis so the track record can measure them first.
Switches (env, default on): SHADOW_ENABLED, SHADOW_PRICE, SHADOW_PUMP, SHADOW_HOLDER
"""
VERSION = "2.68.0"
app.version = VERSION
app.openapi_schema = None

import asyncio
import json
import os
import time

SHADOW_BUF = "si:shadow:buf"
SHADOW_MAX = 2000
SHADOW_TTL = 14 * 86400
_PUMP_API = "https://frontend-api-v3.pump.fun"
_GRAPH_FLAGS = ("known_dumper_present", "smart_money_absorbing", "cluster_high_risk")

_SH_COOL = {}
_SH_CACHE = {}
_SH_SEEN = {}
_SH_TASKS = set()
_SH_STATS = {"runs": 0, "errors": 0, "flags": {}}


def _sh_on(name):
    return os.environ.get(name, "1").lower() not in ("0", "false", "off")


def _sh_num(v):
    try:
        x = float(v)
        return x if x > 0 else None
    except Exception:
        return None


def _sh_get(key):
    hit = _SH_CACHE.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def _sh_put(key, val, ttl):
    if len(_SH_CACHE) > 3000:
        _SH_CACHE.clear()
    _SH_CACHE[key] = (time.time() + ttl, val)


async def _sh_http(client, src, url, params=None):
    """Short timeout; any block or error puts the source on cooldown."""
    if _SH_COOL.get(src, 0) > time.time():
        return None
    try:
        r = await client.get(url, params=params, timeout=2.5)
    except Exception:
        _SH_COOL[src] = time.time() + 60
        return None
    if r.status_code in (403, 429) or r.status_code >= 500:
        _SH_COOL[src] = time.time() + 120
        return None
    if r.status_code != 200:
        return None
    try:
        return r.json()
    except Exception:
        return None


# 1) price cross-check: our price vs Jupiter price
async def _sh_price(client, mint, result):
    if not _sh_on("SHADOW_PRICE"):
        return None
    ours = _sh_num(result.get("price_usd"))
    if not ours:
        return None
    jp = _sh_get("jup:" + mint)
    if jp is None:
        j = await _sh_http(client, "jup", "https://lite-api.jup.ag/price/v3", {"ids": mint})
        jp = _sh_num(((j or {}).get(mint) or {}).get("usdPrice")) or 0.0
        if j is not None:
            _sh_put("jup:" + mint, jp, 15)
    if not jp:
        return {"jup_price": None}
    div = abs(ours - jp) / jp
    return {
        "jup_price": jp,
        "our_price": ours,
        "divergence_pct": round(div * 100, 1),
        "flag": "price_divergence" if div > 0.15 else None,
    }


# 2) pump.fun: migrate status + deployer history
async def _sh_pump(client, mint):
    if not _sh_on("SHADOW_PUMP") or not mint.endswith("pump"):
        return None
    coin = _sh_get("pc:" + mint)
    if coin is None:
        coin = await _sh_http(client, "pump", f"{_PUMP_API}/coins/{mint}")
        if not isinstance(coin, dict):
            return None
        _sh_put("pc:" + mint, coin, 60)
    creator = coin.get("creator")
    out = {
        "migrated": bool(coin.get("complete")),
        "mcap_usd": coin.get("usd_market_cap"),
        "creator": creator,
        "flags": [],
    }
    if not creator:
        return out
    hist = _sh_get("pd:" + creator)
    if hist is None:
        j = await _sh_http(
            client, "pump",
            f"{_PUMP_API}/coins/user-created-coins/{creator}",
            {"offset": 0, "limit": 50, "includeNsfw": "true"},
        )
        coins = j.get("coins") if isinstance(j, dict) else j
        if not isinstance(coins, list):
            return out
        others = [c for c in coins if isinstance(c, dict) and c.get("mint") != mint]
        hist = {"n": len(others), "migrated": sum(1 for c in others if c.get("complete"))}
        _sh_put("pd:" + creator, hist, 600)
    out["deployer_prev"] = hist["n"]
    out["deployer_migrated"] = hist["migrated"]
    if hist["n"] >= 8 and hist["migrated"] / hist["n"] < 0.1:
        out["flags"].append("serial_deployer")
    return out


# 3) holder behavior: copy flags the graph/cluster parts already produced
def _sh_holder(result):
    if not _sh_on("SHADOW_HOLDER"):
        return None
    fl = result.get("flags") or []
    hit = [f for f in _GRAPH_FLAGS if f in fl]
    return {"flags": hit} if hit else None


async def _shadow_run(client, mint, result):
    try:
        res = await asyncio.wait_for(
            asyncio.gather(
                _sh_price(client, mint, result),
                _sh_pump(client, mint),
                return_exceptions=True,
            ),
            5,
        )
    except Exception:
        _SH_STATS["errors"] += 1
        return
    price, pump = [None if isinstance(x, Exception) else x for x in res]
    holder = _sh_holder(result)
    flags = []
    if price and price.get("flag"):
        flags.append(price["flag"])
    if pump:
        flags += pump.get("flags") or []
    if holder:
        flags += holder["flags"]
    for f in flags:
        _SH_STATS["flags"][f] = _SH_STATS["flags"].get(f, 0) + 1
    _SH_STATS["runs"] += 1
    row = {
        "ts": int(time.time()),
        "mint": mint,
        "verdict": result.get("verdict"),
        "risk_score": result.get("risk_score"),
        "price": price,
        "pump": pump,
        "holder": holder,
        "flags": flags,
    }
    try:
        if PRED_ENABLED:
            await redis_pipe(client, [
                ["LPUSH", SHADOW_BUF, json.dumps(row, separators=(",", ":"), default=str)],
                ["LTRIM", SHADOW_BUF, 0, SHADOW_MAX - 1],
                ["EXPIRE", SHADOW_BUF, SHADOW_TTL],
            ])
    except Exception:
        _SH_STATS["errors"] += 1


_build_prev_shadow = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_shadow(client, mint, security, prefetched)
    try:
        if (client and isinstance(result, dict) and _sh_on("SHADOW_ENABLED")
                and time.time() - _SH_SEEN.get(mint, 0) > 30):
            _SH_SEEN[mint] = time.time()
            if len(_SH_SEEN) > 3000:
                _SH_SEEN.clear()
            t = asyncio.create_task(_shadow_run(client, mint, result))
            _SH_TASKS.add(t)
            t.add_done_callback(_SH_TASKS.discard)
    except Exception:
        pass
    return result, status


@app.get("/shadow/status", tags=["operator"], include_in_schema=False)
async def shadow_status(request: Request, limit: int = 50):
    gate = globals().get("require_operator") or globals().get("soft_gate_operator")
    if callable(gate):
        try:
            await gate(request)
        except Exception:
            pass
    rows = []
    client = request.app.state.client
    if PRED_ENABLED and client:
        try:
            res = await redis_pipe(client, [["LRANGE", SHADOW_BUF, 0, max(1, min(int(limit), 200)) - 1]])
            for raw in (res or [[]])[0] or []:
                try:
                    rows.append(json.loads(raw))
                except Exception:
                    continue
        except Exception:
            pass
    return {"ok": True, "version": VERSION, "stats": _SH_STATS,
            "cooldowns": {k: int(v - time.time()) for k, v in _SH_COOL.items() if v > time.time()},
            "rows": rows}


print(f"[part90] v{VERSION} shadow signals (price cross-check, pump.fun, holder) -> GET /shadow/status")

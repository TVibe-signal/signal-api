# ---------- v2.34: Multi-horizon Outcome Enrichment ----------
# Mở rộng resolver_loop: enrich snapshot sau 1h / 6h / 24h / 7d.
# Giữ nguyên hệ thống track-record 24h cũ.

VERSION = "2.34.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Optional, Dict, Any

# Các horizon mới (giây)
MULTI_HORIZONS = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 24 * 3600,
}

# Key cho multi-outcome
SNAP_OUTCOME_KEY = "sout:{}:{}"          # sout:{mint}:{ts} → outcomes dict
PENDING_MULTI = "pending_multi"          # ZSET score = due_ts, member = mint:ts:horizon

async def _fetch_current_price_liq(client: httpx.AsyncClient, mint: str) -> tuple[Optional[float], Optional[float]]:
    """Lấy price + liq hiện tại từ DexScreener."""
    try:
        resp = await client.get(DEX_URL.format(mint=mint), timeout=4.0)
        resp.raise_for_status()
        pair = pick_best_pair(resp.json().get("pairs") or [], mint)
        if not pair:
            return None, None
        price = float(pair.get("priceUsd") or 0) or None
        liq = float((pair.get("liquidity") or {}).get("usd") or 0) or None
        return price, liq
    except Exception:
        return None, None

async def schedule_multi_outcomes(client, mint: str, ts: int, price0: float, liq0: float):
    """Đăng ký các horizon cho 1 snapshot."""
    if not PRED_ENABLED or not client or price0 <= 0:
        return
    try:
        pipe = []
        for name, delta in MULTI_HORIZONS.items():
            due = ts + delta
            member = f"{mint}:{ts}:{name}"
            pipe.append(["ZADD", PENDING_MULTI, due, member])
        if pipe:
            await redis_pipe(client, pipe)
    except Exception:
        pass

async def resolve_multi_due(client: httpx.AsyncClient) -> int:
    """Xử lý các multi-horizon đã đến hạn."""
    if not PRED_ENABLED:
        return 0
    now = int(time.time())
    got = await redis_pipe(client, [
        ["ZRANGEBYSCORE", PENDING_MULTI, "-inf", now, "LIMIT", 0, 40]
    ])
    members = (got or [[]])[0] or []
    if not members:
        return 0

    # nhóm theo mint để giảm số lần gọi Dex
    by_mint: Dict[str, list] = {}
    for m in members:
        try:
            mint, ts_s, horizon = m.split(":")
            by_mint.setdefault(mint, []).append((int(ts_s), horizon, m))
        except Exception:
            continue

    cmds = []
    processed = 0
    for mint, items in by_mint.items():
        price1, liq1 = await _fetch_current_price_liq(client, mint)
        for ts, horizon, member in items:
            cmds.append(["ZREM", PENDING_MULTI, member])
            processed += 1

            # load snapshot gốc
            snap_raw = await redis_get(client, SNAPSHOT_KEY.format(mint, ts)) if "SNAPSHOT_KEY" in globals() else None
            if not snap_raw:
                continue
            try:
                snap = json.loads(snap_raw)
            except Exception:
                continue

            p0 = float((snap.get("market") or {}).get("price") or 0)
            l0 = float((snap.get("market") or {}).get("liq") or 0)
            if p0 <= 0:
                continue

            ret = ((price1 / p0) - 1) * 100 if price1 and p0 > 0 else -100.0
            liq_ratio = (liq1 / l0) if (liq1 and l0 > 0) else 0.0
            bad = ret <= BAD_RETURN_PCT or liq_ratio <= BAD_LIQ_RATIO or price1 is None

            # cập nhật outcomes vào snapshot
            outcomes = snap.get("outcomes") or {}
            outcomes[horizon] = {
                "ts": now,
                "price": price1,
                "liq": liq1,
                "return_pct": round(ret, 2),
                "liq_ratio": round(liq_ratio, 3) if liq_ratio else None,
                "bad": bad,
            }
            snap["outcomes"] = outcomes

            # lưu lại
            await redis_set(client, SNAPSHOT_KEY.format(mint, ts), json.dumps(snap), SNAPSHOT_TTL)
            # cũng lưu riêng cho dễ query
            await redis_set(client, SNAP_OUTCOME_KEY.format(mint, ts), json.dumps(outcomes), SNAPSHOT_TTL)

    if cmds:
        await redis_pipe(client, cmds)
    return processed

# ---------- mở rộng resolver_loop ----------
_old_resolver_loop = resolver_loop

async def resolver_loop(app: FastAPI):
    last_tune = 0.0
    await asyncio.sleep(25)
    while True:
        busy = False
        try:
            # giữ nguyên logic cũ
            n_old = await resolve_due(app.state.client)
            # thêm multi-horizon
            n_multi = await resolve_multi_due(app.state.client)
            busy = (n_old + n_multi) >= 20

            if AUTO_TUNE and time.time() - last_tune > 1800:
                await refresh_weights(app.state.client)
                last_tune = time.time()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(8 if busy else 180)

# Gắn schedule_multi vào pipeline snapshot (part43)
_build_signal_v33 = build_signal

async def build_signal(client: httpx.AsyncClient, mint: str, security: bool, prefetched: Optional[dict] = None):
    result, status = await _build_signal_v33(client, mint, security, prefetched)
    try:
        ts = result.get("_snap_ts")
        price = float(result.get("price_usd") or result.get("price") or 0)
        liq = float(result.get("liquidity_usd") or result.get("liquidity") or 0)
        if ts and price > 0:
            await schedule_multi_outcomes(client, mint, ts, price, liq)
    except Exception:
        pass
    return result, status
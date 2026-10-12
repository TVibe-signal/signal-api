# ---------- v2.34: Multi-horizon Outcome Enrichment ----------
# Mở rộng resolver_loop hiện có: enrich outcome sau 1h / 6h / 24h / 7d.
# Giữ nguyên logic 24h cũ, chỉ bổ sung.

VERSION = "2.34.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Optional, Dict, Any, List

# Horizon mới (giây)
MULTI_HORIZONS = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 24 * 3600,
}

PENDING_MULTI = "pending_multi"          # ZSET: score = due_ts, member = mint:ts:horizon
SNAP_OUTCOME_KEY = "sout:{}:{}"          # sout:{mint}:{ts} → outcomes

async def _get_price_liq(client: httpx.AsyncClient, mint: str) -> tuple[Optional[float], Optional[float]]:
    """Lấy giá + thanh khoản hiện tại. Trả về (None, None) nếu pair biến mất."""
    try:
        resp = await client.get(DEX_URL.format(mint=mint), timeout=4.0)
        resp.raise_for_status()
        pairs = resp.json().get("pairs") or []
        pair = pick_best_pair(pairs, mint)
        if not pair:
            return None, None
        price = float(pair.get("priceUsd") or 0) or None
        liq = float((pair.get("liquidity") or {}).get("usd") or 0) or None
        return price, liq
    except Exception:
        return None, None

async def schedule_multi(client, mint: str, ts: int, price0: float):
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
    """Xử lý các multi-horizon đã đến hạn. Trả về số lượng đã xử lý."""
    if not PRED_ENABLED:
        return 0

    now = int(time.time())
    got = await redis_pipe(client, [
        ["ZRANGEBYSCORE", PENDING_MULTI, "-inf", now, "LIMIT", 0, 50]
    ])
    members = (got or [[]])[0] or []
    if not members:
        return 0

    # Nhóm theo mint để giảm số lần gọi DexScreener
    by_mint: Dict[str, List[tuple]] = {}
    for member in members:
        try:
            mint, ts_s, horizon = member.split(":")
            by_mint.setdefault(mint, []).append((int(ts_s), horizon, member))
        except Exception:
            continue

    cmds = []
    processed = 0

    for mint, items in by_mint.items():
        price1, liq1 = await _get_price_liq(client, mint)

        for ts, horizon, member in items:
            cmds.append(["ZREM", PENDING_MULTI, member])
            processed += 1

            # Load snapshot gốc (từ part43)
            snap_key = f"snap:{mint}:{ts}"
            raw = await redis_get(client, snap_key)
            if not raw:
                continue

            try:
                snap = json.loads(raw)
            except Exception:
                continue

            market = snap.get("market") or {}
            p0 = float(market.get("price") or 0)
            l0 = float(market.get("liq") or 0)
            if p0 <= 0:
                continue

            # Tính outcome
            if price1 is None:
                ret = -100.0
                liq_ratio = 0.0
                disappeared = True
            else:
                ret = (price1 / p0 - 1) * 100
                liq_ratio = (liq1 / l0) if (liq1 and l0 > 0) else 0.0
                disappeared = False

            bad = ret <= BAD_RETURN_PCT or liq_ratio <= BAD_LIQ_RATIO or disappeared

            # Ghi vào snapshot
            outcomes = snap.get("outcomes") or {}
            outcomes[horizon] = {
                "ts": now,
                "price": price1,
                "liq": liq1,
                "return_pct": round(ret, 2),
                "liq_ratio": round(liq_ratio, 3) if liq_ratio else None,
                "bad": bad,
                "disappeared": disappeared,
            }
            snap["outcomes"] = outcomes

            # Lưu lại
            await redis_set(client, snap_key, json.dumps(snap), SNAPSHOT_TTL if "SNAPSHOT_TTL" in globals() else 90*24*3600)
            await redis_set(client, SNAP_OUTCOME_KEY.format(mint, ts), json.dumps(outcomes), 90*24*3600)

    if cmds:
        await redis_pipe(client, cmds)

    return processed

# ---------- Ghi đè resolver_loop ----------
_old_resolver = resolver_loop

async def resolver_loop(app: FastAPI):
    last_tune = 0.0
    await asyncio.sleep(30)          # đợi app khởi động xong

    while True:
        busy = False
        try:
            # Giữ nguyên logic cũ
            n_old = await resolve_due(app.state.client)
            # Thêm multi-horizon
            n_multi = await resolve_multi_due(app.state.client)

            busy = (n_old + n_multi) >= 25

            if AUTO_TUNE and time.time() - last_tune > 1800:
                await refresh_weights(app.state.client)
                last_tune = time.time()

        except asyncio.CancelledError:
            raise
        except Exception:
            pass

        await asyncio.sleep(10 if busy else 180)

# ---------- Gắn vào pipeline build_signal (sau khi đã có snapshot) ----------
_build_prev = build_signal

async def build_signal(client: httpx.AsyncClient, mint: str, security: bool, prefetched: Optional[dict] = None):
    result, status = await _build_prev(client, mint, security, prefetched)

    try:
        ts = result.get("_snap_ts")
        price = float(result.get("price_usd") or 0)
        if ts and price > 0:
            await schedule_multi(client, mint, ts, price)
    except Exception:
        pass

    return result, status
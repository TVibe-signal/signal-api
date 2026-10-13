# part51.py (v2.38.0) - Vá Multi-horizon Outcome (part47). Ghi đè resolve_multi_due.
# Đặt SAU part50, TRƯỚC part7. Cần: PENDING_MULTI, MULTI_HORIZONS, SNAP_OUTCOME_KEY, DEX_URL,
# pick_best_pair, BAD_RETURN_PCT, BAD_LIQ_RATIO, redis_get/redis_set/redis_pipe (đều có sẵn).

VERSION = "2.38.0"
app.version = VERSION
app.openapi_schema = None

import json
import time

HGX_RETRY_S = 600         # lỗi mạng / 429: thử lại sau 10 phút
HGX_GONE_RETRY_S = 900    # "biến mất": phải thấy 2 lần cách nhau >= 15 phút mới chốt
HGX_GIVEUP_S = 6 * 3600   # lỗi kéo dài quá 6h sau hạn: bỏ, KHÔNG gán nhãn
HGX_OUT_TTL = 90 * 86400
HGX_STATS = {"final": 0, "gone": 0, "retry": 0, "giveup": 0, "no_snap": 0, "no_price": 0, "bad_member": 0}


async def _hgx_price_liq(client, mint):
    """(state, price, liq). ok = có pair; gone = DexScreener trả 200 nhưng không có pair;
    error = lỗi mạng / 429 / timeout / dữ liệu lạ (KHÔNG được coi là rug)."""
    try:
        resp = await client.get(DEX_URL.format(mint=mint), timeout=4.0)
        if resp.status_code != 200:
            return "error", None, None
        body = resp.json()
        if not isinstance(body, dict) or "pairs" not in body:      # schema lạ = lỗi, không phải rug
            return "error", None, None
        pairs = body.get("pairs") or []
        pair = pick_best_pair(pairs, mint) if pairs else None
        if not pair:
            return "gone", None, None
        price = float(pair.get("priceUsd") or 0)
        if price <= 0:
            return "error", None, None
        lq = (pair.get("liquidity") or {}).get("usd")
        return "ok", price, (float(lq) if lq is not None else None)
    except Exception:
        return "error", None, None


async def _hgx_defer(client, items, secs, now):
    cmds = []
    for ts, hz, m, due in items:
        if now - due > HGX_GIVEUP_S:
            HGX_STATS["giveup"] += 1
            cmds.append(["ZREM", PENDING_MULTI, m])
        else:
            HGX_STATS["retry"] += 1
            cmds.append(["ZADD", PENDING_MULTI, now + secs, m])
    await redis_pipe(client, cmds)


async def _hgx_finalize(client, mint, ts, hz, state, price1, liq1, now):
    snap_key = f"snap:{mint}:{ts}"
    raw = await redis_get(client, snap_key)
    if not raw:
        HGX_STATS["no_snap"] += 1
        return
    snap = json.loads(raw)
    mk = snap.get("market") or {}
    p0, l0 = float(mk.get("price") or 0), float(mk.get("liq") or 0)
    if p0 <= 0:
        HGX_STATS["no_price"] += 1
        return
    if state == "gone":
        ret, ratio, gone = -100.0, 0.0, True
    else:
        ret, gone = (price1 / p0 - 1) * 100, False
        # thiếu thanh khoản lúc chụp (l0 = 0) hoặc API không trả liq -> không biết, KHÔNG tính là xấu
        ratio = (liq1 / l0) if (liq1 is not None and l0 > 0) else None
    bad = gone or ret <= BAD_RETURN_PCT or (ratio is not None and ratio <= BAD_LIQ_RATIO)
    outs = snap.get("outcomes") or {}
    outs[hz] = {"ts": now, "price": price1, "liq": liq1, "return_pct": round(ret, 2),
                "liq_ratio": None if ratio is None else round(ratio, 3), "bad": bad, "disappeared": gone}
    snap["outcomes"] = outs
    ttl = SNAPSHOT_TTL if "SNAPSHOT_TTL" in globals() else HGX_OUT_TTL
    await redis_set(client, snap_key, json.dumps(snap), ttl)
    await redis_set(client, SNAP_OUTCOME_KEY.format(mint, ts), json.dumps(outs), HGX_OUT_TTL)
    HGX_STATS["final"] += 1
    if hz == "24h" and "hgx_note_outcome" in globals():       # cập nhật tỉ lệ xấu của cluster (part50)
        await hgx_note_outcome(client, mint, bad)


async def resolve_multi_due(client):
    """Ghi đè part47. Khác bản cũ: lỗi mạng/429 không còn bị chấm là 'biến mất'; 'biến mất' phải
    xác nhận 2 lần; thiếu liq lúc chụp không còn thành nhãn xấu; 1 mục lỗi không kẹt cả hàng đợi."""
    if not PRED_ENABLED:
        return 0
    now = int(time.time())
    got = await redis_pipe(client, [["ZRANGEBYSCORE", PENDING_MULTI, "-inf", now, "LIMIT", 0, 50]])
    members = (got or [[]])[0] or []
    by_mint, done = {}, 0
    for m in members:
        try:
            mint, ts_s, hz = m.split(":")
            by_mint.setdefault(mint, []).append((int(ts_s), hz, m, int(ts_s) + MULTI_HORIZONS[hz]))
        except Exception:
            HGX_STATS["bad_member"] += 1
            await redis_pipe(client, [["ZREM", PENDING_MULTI, m]])
    for mint, items in by_mint.items():
        state, price1, liq1 = await _hgx_price_liq(client, mint)
        if state == "error":
            await _hgx_defer(client, items, HGX_RETRY_S, now)
            continue
        if state == "gone":
            HGX_STATS["gone"] += 1
            r = await redis_pipe(client, [["INCR", f"mgone:{mint}"], ["EXPIRE", f"mgone:{mint}", 3600]])
            if int((r or [0])[0] or 0) < 2:
                await _hgx_defer(client, items, HGX_GONE_RETRY_S, now)
                continue
        for ts, hz, m, due in items:
            await redis_pipe(client, [["ZREM", PENDING_MULTI, m]])     # nhận việc trước để khỏi kẹt đầu hàng
            done += 1
            try:
                await _hgx_finalize(client, mint, ts, hz, state, price1, liq1, now)
            except Exception:
                pass
    return done

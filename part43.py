# ---------- v2.30: Proprietary Snapshot Store + Multi-horizon Outcomes ----------
# Lưu full snapshot mỗi lần /signal, enrich outcome sau 1h / 6h / 24h / 7d.
# Chỉ chạy khi PRED_ENABLED (Redis).

VERSION = "2.30.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Optional, Dict, Any, List

SNAPSHOT_TTL = 90 * 24 * 3600          # 90 ngày
SNAPSHOT_KEY = "snap:{}:{}"            # snap:{mint}:{ts}
SNAPSHOTS_ZSET = "snaps:{}"            # sorted set theo ts
OUTCOME_HORIZONS = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
    "7d": 7 * 24 * 3600,
}

def _make_snapshot(mint: str, result: dict, status: str) -> dict:
    """Tạo snapshot gọn, chỉ lấy field quan trọng."""
    market = {
        "price": result.get("price"),
        "fdv": result.get("fdv"),
        "mcap": result.get("market_cap"),
        "liq": result.get("liquidity"),
        "pair_age_h": result.get("pair_age_hours"),
        "pc_5m": (result.get("price_change_pct") or {}).get("5m"),
        "pc_1h": (result.get("price_change_pct") or {}).get("1h"),
        "pc_6h": (result.get("price_change_pct") or {}).get("6h"),
        "pc_24h": (result.get("price_change_pct") or {}).get("24h"),
        "vol_5m": result.get("volume_5m"),
        "buys_5m": result.get("buys_5m"),
        "sells_5m": result.get("sells_5m"),
        "buy_pressure_5m": result.get("buy_pressure_5m"),
    }
    sec = result.get("security") or {}
    hq = result.get("holder_quality") or {}
    return {
        "mint": mint,
        "ts": int(time.time()),
        "verdict": (result.get("decision") or {}).get("verdict"),
        "risk_score": result.get("risk_score"),
        "flags": result.get("flags") or [],
        "status": status,
        "market": market,
        "security": {
            "mint_auth": sec.get("mint_authority_active"),
            "freeze_auth": sec.get("freeze_authority_active"),
            "top10_pct": sec.get("top10_holders_pct"),
            "lp_locked_pct": sec.get("lp_locked_pct"),
            "top_owners": hq.get("top_owners") or [],
        },
        "holder_quality": {
            "score": hq.get("score"),
            "stability": hq.get("stability"),
            "absorption": hq.get("absorption"),
            "flags": hq.get("flags") or [],
        },
        "exit_grade": result.get("exit_grade"),
        "sources": result.get("sources") or {},
    }

async def _save_snapshot(client, mint: str, snap: dict):
    if not PRED_ENABLED or not client:
        return
    try:
        key = SNAPSHOT_KEY.format(mint, snap["ts"])
        zkey = SNAPSHOTS_ZSET.format(mint)
        await redis_set(client, key, json.dumps(snap), SNAPSHOT_TTL)
        # ZADD snaps:{mint} ts ts
        await redis_pipe(client, [
            ["ZADD", zkey, snap["ts"], str(snap["ts"])],
            ["EXPIRE", zkey, SNAPSHOT_TTL],
        ])
    except Exception:
        pass

async def _load_snapshot(client, mint: str, ts: int) -> Optional[dict]:
    if not PRED_ENABLED or not client:
        return None
    try:
        raw = await redis_get(client, SNAPSHOT_KEY.format(mint, ts))
        return json.loads(raw) if raw else None
    except Exception:
        return None

# ---------- gắn vào pipeline ----------
_build_signal_v29 = build_signal

async def build_signal(client: httpx.AsyncClient, mint: str, security: bool, prefetched: Optional[dict] = None):
    result, status = await _build_signal_v29(client, mint, security, prefetched)
    try:
        snap = _make_snapshot(mint, result, status)
        await _save_snapshot(client, mint, snap)
        # gắn id snapshot để các part sau dùng
        result["_snap_ts"] = snap["ts"]
    except Exception:
        pass
    return result, status
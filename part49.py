# ---------- v2.36: Network Effects – Attention + Community Conviction ----------
# Contribution loop nhẹ + community context.

VERSION = "2.36.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Optional, Dict, Any
from collections import Counter

# Redis keys
ATTENTION_KEY = "attn:{}:{}"          # attn:{mint}:{window} → count
ATTENTION_WINDOWS = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
}
COMMUNITY_KEY = "comm:{}"             # comm:{mint} → list of recent verdicts
COMMUNITY_MAX = 40                    # giữ tối đa 40 verdict gần nhất
COMMUNITY_TTL = 7 * 24 * 3600

async def _record_attention(client, mint: str):
    """Ghi nhận 1 lượt query (ẩn danh)."""
    if not PRED_ENABLED or not client:
        return
    try:
        now = int(time.time())
        pipe = []
        for window, ttl in ATTENTION_WINDOWS.items():
            key = ATTENTION_KEY.format(mint, window)
            # Dùng HyperLogLog hoặc đơn giản INCR + EXPIRE
            pipe.append(["INCR", key])
            pipe.append(["EXPIRE", key, ttl])
        await redis_pipe(client, pipe)
    except Exception:
        pass

async def _record_community_verdict(client, mint: str, verdict: str, risk_score: float):
    """Ghi verdict vào community pool của token."""
    if not PRED_ENABLED or not client or not verdict:
        return
    try:
        key = COMMUNITY_KEY.format(mint)
        entry = json.dumps({
            "v": verdict,
            "s": round(risk_score, 1),
            "ts": int(time.time()),
        })
        await redis_pipe(client, [
            ["LPUSH", key, entry],
            ["LTRIM", key, 0, COMMUNITY_MAX - 1],
            ["EXPIRE", key, COMMUNITY_TTL],
        ])
    except Exception:
        pass

async def get_attention(client, mint: str) -> Dict[str, int]:
    """Lấy số lượt query gần đây."""
    if not PRED_ENABLED or not client:
        return {}
    try:
        keys = [ATTENTION_KEY.format(mint, w) for w in ATTENTION_WINDOWS]
        res = await redis_pipe(client, [["GET", k] for k in keys])
        out = {}
        for w, val in zip(ATTENTION_WINDOWS.keys(), res or []):
            out[w] = int(val or 0)
        return out
    except Exception:
        return {}

async def get_community_conviction(client, mint: str) -> Dict[str, Any]:
    """Tính community conviction từ các verdict gần đây."""
    if not PRED_ENABLED or not client:
        return {}
    try:
        res = await redis_pipe(client, [["LRANGE", COMMUNITY_KEY.format(mint), 0, COMMUNITY_MAX - 1]])
        raw_list = (res or [[]])[0] or []
        if not raw_list:
            return {"n": 0}

        verdicts = []
        scores = []
        for item in raw_list:
            try:
                d = json.loads(item)
                verdicts.append(d.get("v"))
                scores.append(float(d.get("s") or 0))
            except Exception:
                continue

        if not verdicts:
            return {"n": 0}

        cnt = Counter(verdicts)
        total = len(verdicts)
        avg_score = round(sum(scores) / total, 1)

        return {
            "n": total,
            "ok_pct": round(cnt.get("ok", 0) / total * 100, 1),
            "caution_pct": round(cnt.get("caution", 0) / total * 100, 1),
            "avoid_pct": round(cnt.get("avoid", 0) / total * 100, 1),
            "avg_risk_score": avg_score,
            "dominant": cnt.most_common(1)[0][0] if cnt else None,
        }
    except Exception:
        return {"n": 0}

# ---------- Gắn vào pipeline ----------
_build_prev_net = build_signal

async def build_signal(client: httpx.AsyncClient, mint: str, security: bool, prefetched: Optional[dict] = None):
    result, status = await _build_prev_net(client, mint, security, prefetched)

    try:
        # 1. Ghi nhận contribution (mỗi lần gọi đều góp data)
        await _record_attention(client, mint)

        verdict = (result.get("decision") or {}).get("verdict") or result.get("verdict")
        risk = float(result.get("risk_score") or 0)
        if verdict:
            await _record_community_verdict(client, mint, verdict, risk)

        # 2. Lấy community context (chỉ gắn khi có dữ liệu)
        attention = await get_attention(client, mint)
        conviction = await get_community_conviction(client, mint)

        if attention or (conviction and conviction.get("n", 0) >= 3):
            result["community"] = {
                "attention": attention,               # số lần được query gần đây
                "conviction": conviction,             # phân bố verdict cộng đồng
            }
    except Exception:
        pass

    return result, status
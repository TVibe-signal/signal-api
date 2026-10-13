# ---------- v2.39: Network Effects – Attention + Community Conviction (hoàn thiện) ----------
# Mỗi lần /signal đều góp data → hiện community context rõ ràng hơn.

VERSION = "2.39.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Optional, Dict, Any
from collections import Counter

ATTENTION_KEY = "attn:{}:{}"
ATTENTION_WINDOWS = {
    "1h": 3600,
    "6h": 6 * 3600,
    "24h": 24 * 3600,
}
COMMUNITY_KEY = "comm:{}"
COMMUNITY_MAX = 50
COMMUNITY_TTL = 7 * 24 * 3600

async def _record_attention(client, mint: str):
    if not PRED_ENABLED or not client:
        return
    try:
        pipe = []
        for window, ttl in ATTENTION_WINDOWS.items():
            key = ATTENTION_KEY.format(mint, window)
            pipe.append(["INCR", key])
            pipe.append(["EXPIRE", key, ttl])
        await redis_pipe(client, pipe)
    except Exception:
        pass

async def _record_community_verdict(client, mint: str, verdict: str, risk_score: float):
    if not PRED_ENABLED or not client or not verdict:
        return
    try:
        entry = json.dumps({
            "v": verdict,
            "s": round(float(risk_score or 0), 1),
            "ts": int(time.time()),
        })
        await redis_pipe(client, [
            ["LPUSH", COMMUNITY_KEY.format(mint), entry],
            ["LTRIM", COMMUNITY_KEY.format(mint), 0, COMMUNITY_MAX - 1],
            ["EXPIRE", COMMUNITY_KEY.format(mint), COMMUNITY_TTL],
        ])
    except Exception:
        pass

async def get_attention(client, mint: str) -> Dict[str, int]:
    if not PRED_ENABLED or not client:
        return {}
    try:
        keys = [ATTENTION_KEY.format(mint, w) for w in ATTENTION_WINDOWS]
        res = await redis_pipe(client, [["GET", k] for k in keys])
        return {w: int(v or 0) for w, v in zip(ATTENTION_WINDOWS.keys(), res or [])}
    except Exception:
        return {}

async def get_community_conviction(client, mint: str) -> Dict[str, Any]:
    if not PRED_ENABLED or not client:
        return {"n": 0}
    try:
        res = await redis_pipe(client, [["LRANGE", COMMUNITY_KEY.format(mint), 0, COMMUNITY_MAX - 1]])
        raw_list = (res or [[]])[0] or []
        if not raw_list:
            return {"n": 0}

        verdicts, scores = [], []
        for item in raw_list:
            try:
                d = json.loads(item)
                if d.get("v"):
                    verdicts.append(d["v"])
                    scores.append(float(d.get("s") or 0))
            except Exception:
                continue

        if not verdicts:
            return {"n": 0}

        cnt = Counter(verdicts)
        n = len(verdicts)
        avg = round(sum(scores) / n, 1)

        return {
            "n": n,
            "ok_pct": round(cnt.get("ok", 0) / n * 100, 1),
            "caution_pct": round(cnt.get("caution", 0) / n * 100, 1),
            "avoid_pct": round(cnt.get("avoid", 0) / n * 100, 1),
            "avg_risk_score": avg,
            "dominant": cnt.most_common(1)[0][0],
        }
    except Exception:
        return {"n": 0}

def _community_summary(attn: dict, conv: dict) -> str:
    """Tạo câu tóm tắt dễ đọc cho agent."""
    parts = []
    a24 = attn.get("24h", 0)
    if a24 >= 10:
        parts.append(f"được quan tâm khá nhiều ({a24} lượt/24h)")
    elif a24 >= 3:
        parts.append(f"có vài lượt quan tâm ({a24}/24h)")

    n = conv.get("n", 0)
    if n >= 5:
        dom = conv.get("dominant")
        avoid = conv.get("avoid_pct", 0)
        if dom == "avoid" and avoid >= 50:
            parts.append(f"cộng đồng nghiêng về avoid ({avoid}%)")
        elif dom == "ok":
            parts.append(f"cộng đồng chủ yếu ok ({conv.get('ok_pct')}%)")
        else:
            parts.append(f"cộng đồng phân tán (n={n})")

    return "; ".join(parts) if parts else ""

# ---------- Gắn vào pipeline ----------
_build_prev_net = build_signal

async def build_signal(client: httpx.AsyncClient, mint: str, security: bool, prefetched: Optional[dict] = None):
    result, status = await _build_prev_net(client, mint, security, prefetched)

    try:
        await _record_attention(client, mint)

        verdict = (result.get("decision") or {}).get("verdict") or result.get("verdict")
        risk = float(result.get("risk_score") or 0)
        if verdict:
            await _record_community_verdict(client, mint, verdict, risk)

        attention = await get_attention(client, mint)
        conviction = await get_community_conviction(client, mint)

        # Hiện sớm hơn (n >= 2 thay vì 3)
        if attention or (conviction and conviction.get("n", 0) >= 2):
            summary = _community_summary(attention, conviction)
            result["community"] = {
                "attention": attention,
                "conviction": conviction,
                "summary": summary or None,
            }

            # Gắn ghi chú nhẹ vào decision nếu có
            if summary and result.get("decision"):
                d = dict(result["decision"])
                unknowns = list(d.get("unknowns") or [])
                note = f"Community: {summary}"
                if note not in unknowns:
                    unknowns.append(note)
                d["unknowns"] = unknowns
                result["decision"] = d
    except Exception:
        pass

    return result, status
# ---------- v2.33: Private Feature Vector + Model Adjustment ----------
# Chuẩn bị feature vector + chỗ load model offline.
# Model thật train bên ngoài, chỉ load adjustment vào đây.

VERSION = "2.33.0"
app.version = VERSION
app.openapi_schema = None

import json
from typing import Dict, Any

# Feature list cố định (để train offline khớp)
PRIVATE_FEATURES = [
    "risk_score", "liq", "pair_age_h",
    "pc_1h", "pc_6h", "buy_pressure_5m",
    "top10_pct", "hq_score", "hq_stability", "hq_absorption",
    "n_flags", "has_whale_dumping", "has_holders_churning",
    "cluster_size",
]

def _extract_features(result: dict) -> Dict[str, float]:
    m = result.get("market") or {}
    hq = result.get("holder_quality") or {}
    sec = result.get("security") or {}
    flags = set(result.get("flags") or [])
    cl = result.get("_cluster") or {}

    return {
        "risk_score": float(result.get("risk_score") or 0),
        "liq": float(m.get("liq") or result.get("liquidity") or 0),
        "pair_age_h": float(m.get("pair_age_h") or result.get("pair_age_hours") or 0),
        "pc_1h": float(m.get("pc_1h") or 0),
        "pc_6h": float(m.get("pc_6h") or 0),
        "buy_pressure_5m": float(m.get("buy_pressure_5m") or result.get("buy_pressure_5m") or 0.5),
        "top10_pct": float(sec.get("top10_pct") or 50),
        "hq_score": float(hq.get("score") or 50),
        "hq_stability": float(hq.get("stability") or 50),
        "hq_absorption": float(hq.get("absorption") or 50),
        "n_flags": float(len(flags)),
        "has_whale_dumping": 1.0 if "whale_dumping" in flags else 0.0,
        "has_holders_churning": 1.0 if "holders_churning" in flags else 0.0,
        "cluster_size": float(cl.get("size") or 1),
    }

# Placeholder model (thay bằng model thật sau khi train)
# Ví dụ: dict weight đơn giản hoặc load joblib
_PRIVATE_WEIGHTS = {
    "risk_score": 0.35,
    "liq": -0.00002,
    "pair_age_h": -0.8,
    "pc_1h": -0.15,
    "buy_pressure_5m": -12.0,
    "hq_stability": -0.25,
    "has_whale_dumping": 18.0,
    "cluster_size": 0.4,
}

def _private_risk_adjustment(feats: dict) -> float:
    """Trả về điểm điều chỉnh (-30 → +30)."""
    score = 0.0
    for k, w in _PRIVATE_WEIGHTS.items():
        score += w * feats.get(k, 0)
    return max(-30.0, min(30.0, score))

# ---------- gắn vào pipeline ----------
_build_signal_v32 = build_signal

async def build_signal(client: httpx.AsyncClient, mint: str, security: bool, prefetched: Optional[dict] = None):
    result, status = await _build_signal_v32(client, mint, security, prefetched)
    try:
        feats = _extract_features(result)
        adj = _private_risk_adjustment(feats)
        # chỉ gắn internal
        result["_private"] = {
            "features": feats,
            "risk_adj": round(adj, 1),
            "adjusted_risk": max(0, min(100, (result.get("risk_score") or 0) + adj)),
        }
        # Có thể dùng adjusted_risk để xếp hạng trong /signals sau này
    except Exception:
        pass
    return result, status
# ---------- v2.41: Seed boost + smart ranking + health extras ----------
VERSION = "2.41.0"
app.version = VERSION
app.openapi_schema = None

import os
import time
from typing import Optional, List, Dict, Any

# ---------- 1. Seed boost ----------
SEED_MAX_PER_DAY = int(os.getenv("SEED_MAX_PER_DAY", "120"))
SEED_FORCE = os.getenv("SEED_FORCE", "").lower() in ("1", "true", "yes")

try:
    if "_seed_state" in globals():
        _seed_state["max"] = SEED_MAX_PER_DAY
except Exception:
    pass

# ---------- 2. Ranking thông minh cho /signals ----------
def _rank_score(r: dict) -> float:
    """Điểm càng thấp càng tốt (dùng khi sort safest)."""
    base = float(r.get("risk_score") or 50)

    # Community conviction
    conv = (r.get("community") or {}).get("conviction") or {}
    n = conv.get("n", 0)
    if n >= 5:
        avoid = conv.get("avoid_pct", 0)
        ok = conv.get("ok_pct", 0)
        if avoid >= 55:
            base += 18
        elif ok >= 60:
            base -= 8

    # Private adjusted risk
    priv = r.get("_private") or {}
    adj = priv.get("adjusted_risk")
    if adj is not None:
        base = 0.65 * base + 0.35 * float(adj)

    # Attention
    attn = (r.get("community") or {}).get("attention") or {}
    if attn.get("24h", 0) >= 30:
        base -= 3

    return base

_old_build_batch = build_batch if "build_batch" in globals() else None

async def build_batch(client, raw_mints, security, *, sort="input", only=None, max_risk=None, top=None, view="full", charge=None):
    if _old_build_batch is None:
        raise RuntimeError("build_batch not found")
    out = await _old_build_batch(
        client, raw_mints, security,
        sort=sort, only=only, max_risk=max_risk,
        top=top, view=view, charge=charge
    )

    try:
        results = out.get("results") or []
        if sort in ("safest", "riskiest") and results:
            reverse = sort == "riskiest"
            results.sort(key=_rank_score, reverse=reverse)
            out["results"] = results
            out["rank_note"] = "ranked with community + private risk"
    except Exception:
        pass
    return out

# ---------- 3. Health extras (cách an toàn, không đụng app.routes) ----------
@app.get("/health", tags=["ops"], include_in_schema=False)
async def health_with_extras(request: Request):
    data = {
        "status": "ok",
        "version": VERSION,
    }

    # Cố gắng lấy dữ liệu health gốc nếu có
    try:
        # Gọi các hàm health cũ nếu tồn tại
        if "health" in globals() and callable(health):
            original = await health(request)
            if isinstance(original, dict):
                data.update(original)
    except Exception:
        pass

    try:
        # Seed info
        data["seed"] = data.get("seed") or {}
        data["seed"]["force"] = SEED_FORCE
        data["seed"]["max_per_day"] = SEED_MAX_PER_DAY

        # Multi-horizon pending
        if PRED_ENABLED:
            client = request.app.state.client
            res = await redis_pipe(client, [["ZCARD", "pending_multi"]])
            data["multi_horizon_pending"] = int((res or [0])[0] or 0)

        # RPC rotator
        if "_rpc_stats" in globals():
            data["rpc_rotator"] = {
                "endpoints": len(_rpc_stats),
                "mode": "private" if globals().get("PRIVATE_RPC") else "rotator",
            }
    except Exception:
        pass

    return data

print(f"[part53] v{VERSION} seed boost + smart ranking + health extras loaded")
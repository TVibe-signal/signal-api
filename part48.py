# ---------- v2.35: Internal Operator Endpoints (Secure) ----------
# Chỉ hoạt động khi ENABLE_INTERNAL=true và header X-Operator-Secret đúng.
# An toàn khi repo mã nguồn mở.

VERSION = "2.35.0"
app.version = VERSION
app.openapi_schema = None

import os
import json
from typing import Optional
from fastapi import Header, Query, Request, HTTPException

# Bật/tắt toàn bộ internal
ENABLE_INTERNAL = os.getenv("ENABLE_INTERNAL", "").lower() in ("1", "true", "yes")
OPERATOR_SECRET = os.getenv("OPERATOR_SECRET", "")  # bắt buộc set nếu bật

def _require_operator(x_operator_secret: Optional[str] = Header(None, alias="X-Operator-Secret")):
    """Chặn cứng nếu chưa bật hoặc secret sai. Trả 404 để che sự tồn tại."""
    if not ENABLE_INTERNAL:
        raise HTTPException(status_code=404, detail="Not found")
    if not OPERATOR_SECRET or not x_operator_secret or x_operator_secret != OPERATOR_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")
    return True

# ------------------------------------------------------------------
# 1. Xem snapshot + outcome của 1 mint
# ------------------------------------------------------------------
@app.get("/internal/snap/{mint}", tags=["internal"], include_in_schema=False)
async def internal_snapshots(
    mint: str,
    limit: int = Query(8, ge=1, le=30),
    request: Request,
    x_operator_secret: Optional[str] = Header(None, alias="X-Operator-Secret"),
):
    _require_operator(x_operator_secret)

    if not PRED_ENABLED:
        return {"error": "Redis / track-record not enabled"}

    client = request.app.state.client

    try:
        res = await redis_pipe(client, [
            ["ZREVRANGE", f"snaps:{mint}", 0, limit - 1]
        ])
        tss = (res or [[]])[0] or []

        snapshots = []
        for ts in tss:
            raw = await redis_get(client, f"snap:{mint}:{ts}")
            if not raw:
                continue
            try:
                snap = json.loads(raw)
                snapshots.append({
                    "ts": snap.get("ts"),
                    "verdict": snap.get("verdict"),
                    "risk_score": snap.get("risk_score"),
                    "flags": snap.get("flags"),
                    "market": snap.get("market"),
                    "holder_quality": snap.get("holder_quality"),
                    "outcomes": snap.get("outcomes"),      # quan trọng nhất
                    "cluster": snap.get("_cluster"),
                })
            except Exception:
                continue

        return {
            "mint": mint,
            "count": len(snapshots),
            "snapshots": snapshots,
        }
    except Exception as e:
        return {"error": str(e)}

# ------------------------------------------------------------------
# 2. Wallet behavior profile
# ------------------------------------------------------------------
@app.get("/internal/wallet/{wallet}", tags=["internal"], include_in_schema=False)
async def internal_wallet(
    wallet: str,
    request: Request,
    x_operator_secret: Optional[str] = Header(None, alias="X-Operator-Secret"),
):
    _require_operator(x_operator_secret)

    if "get_wallet_profile" not in globals():
        return {"error": "Holder graph (part44) not loaded"}

    client = request.app.state.client
    profile = await get_wallet_profile(client, wallet)

    return {
        "wallet": wallet,
        "profile": profile,
    }

# ------------------------------------------------------------------
# 3. Cluster info theo fingerprint
# ------------------------------------------------------------------
@app.get("/internal/cluster/{fingerprint}", tags=["internal"], include_in_schema=False)
async def internal_cluster(
    fingerprint: str,
    request: Request,
    x_operator_secret: Optional[str] = Header(None, alias="X-Operator-Secret"),
):
    _require_operator(x_operator_secret)

    if "get_cluster_info" not in globals():
        return {"error": "Cluster detection (part45) not loaded"}

    client = request.app.state.client
    info = await get_cluster_info(client, fingerprint)

    return {
        "fingerprint": fingerprint,
        "cluster": info,
    }

# ------------------------------------------------------------------
# 4. Health check nội bộ (tiện kiểm tra)
# ------------------------------------------------------------------
@app.get("/internal/health", tags=["internal"], include_in_schema=False)
async def internal_health(
    x_operator_secret: Optional[str] = Header(None, alias="X-Operator-Secret"),
):
    _require_operator(x_operator_secret)
    return {
        "status": "ok",
        "internal_enabled": True,
        "pred_enabled": PRED_ENABLED,
        "multi_horizon": list(MULTI_HORIZONS.keys()) if "MULTI_HORIZONS" in globals() else [],
        "version": VERSION,
    }
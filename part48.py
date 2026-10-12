# ---------- v2.35: Internal endpoints – Wallet Profile & Cluster ----------

VERSION = "2.35.0"
app.version = VERSION
app.openapi_schema = None

from fastapi import Header, HTTPException

def _require_operator(x_api_key: Optional[str] = Header(None)):
    """Chỉ cho phép API key đã đăng ký (hoặc bạn tự thêm whitelist)."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key required for internal endpoints")
    # Nếu bạn có dict API_KEYS thì kiểm tra ở đây
    # Tạm thời cho phép mọi key hợp lệ (bạn siết sau)
    return True

@app.get("/internal/wallet/{wallet}", tags=["internal"], summary="Wallet behavior profile")
async def internal_wallet_profile(
    wallet: str,
    request: Request,
    x_api_key: Optional[str] = Header(None),
):
    _require_operator(x_api_key)
    client = request.app.state.client
    profile = await get_wallet_profile(client, wallet) if "get_wallet_profile" in globals() else {}
    return {
        "wallet": wallet,
        "profile": profile,
        "note": "Internal only. dump_rate cao = hay bán mạnh.",
    }

@app.get("/internal/cluster/{fingerprint}", tags=["internal"], summary="Cluster info by fingerprint")
async def internal_cluster(
    fingerprint: str,
    request: Request,
    x_api_key: Optional[str] = Header(None),
):
    _require_operator(x_api_key)
    client = request.app.state.client
    info = await get_cluster_info(client, fingerprint) if "get_cluster_info" in globals() else {}
    return {
        "fingerprint": fingerprint,
        "cluster": info,
        "note": "Internal only.",
    }

@app.get("/internal/snap/{mint}", tags=["internal"], summary="Latest snapshots + outcomes of a mint")
async def internal_snapshots(
    mint: str,
    limit: int = Query(5, ge=1, le=20),
    request: Request,
    x_api_key: Optional[str] = Header(None),
):
    _require_operator(x_api_key)
    if not PRED_ENABLED:
        return {"error": "Redis not enabled"}
    client = request.app.state.client
    try:
        # lấy ts mới nhất
        res = await redis_pipe(client, [
            ["ZREVRANGE", SNAPSHOTS_ZSET.format(mint), 0, limit - 1]
        ])
        tss = (res or [[]])[0] or []
        snaps = []
        for ts in tss:
            raw = await redis_get(client, SNAPSHOT_KEY.format(mint, ts))
            if raw:
                snaps.append(json.loads(raw))
        return {"mint": mint, "snapshots": snaps}
    except Exception as e:
        return {"error": str(e)}
# ---------- part41: v2.28.0 - labelled dataset: public info + private export ----------
import hmac as _hmac
import json as _j
from starlette.responses import Response as _Resp

VERSION = "2.28.0"
app.version = VERSION
app.openapi_schema = None

ADMIN_TOKEN = (os.getenv("ADMIN_TOKEN") or "").strip()
DS_KEY = "ds:rows"
DS_PAGE_MAX = 500


def _admin_ok(request: Request) -> bool:
    if not ADMIN_TOKEN:
        return False
    got = request.headers.get("x-admin-token") or request.query_params.get("token") or ""
    return _hmac.compare_digest(got.encode(), ADMIN_TOKEN.encode())


def _row_ts(s):
    try:
        return int(_j.loads(s).get("ts") or 0) or None
    except Exception:
        return None


@app.get("/dataset/info", tags=["data"], summary="Size of the labelled outcome dataset")
async def dataset_info(request: Request):
    wait = rate_limited("dsi:" + client_ip(request), limit=20)
    if wait:
        raise HTTPException(status_code=429, detail="rate limited", headers={"Retry-After": str(wait)})
    res = await redis_pipe(request.app.state.client,
                           [["LLEN", DS_KEY], ["LINDEX", DS_KEY, 0], ["LINDEX", DS_KEY, -1]])
    if res is None:
        raise HTTPException(status_code=503, detail="storage unavailable, retry later")
    return JSONResponse({
        "rows": int(res[0] or 0), "capacity": DATASET_MAX,
        "newest_ts": _row_ts(res[1]), "oldest_ts": _row_ts(res[2]),
        "labels": ["ret_h1", "ret_h6", "ret_24h", "liq_ratio", "bad"],
        "includes": "features at verdict time, flags, shadow-rule verdicts",
        "excludes": "mint addresses and token names",
        "access": "private export for now",
    }, headers={"Cache-Control": "no-store"})


@app.get("/dataset", include_in_schema=False)
async def dataset_export(request: Request, offset: int = 0, limit: int = 200):
    wait = rate_limited("ds:" + client_ip(request), limit=20)
    if wait:
        raise HTTPException(status_code=429, detail="rate limited", headers={"Retry-After": str(wait)})
    if not _admin_ok(request):
        raise HTTPException(status_code=403, detail="admin token required")
    offset = max(0, offset)
    limit = max(1, min(limit, DS_PAGE_MAX))
    res = await redis_pipe(request.app.state.client, [["LRANGE", DS_KEY, offset, offset + limit - 1]])
    if res is None:
        raise HTTPException(status_code=503, detail="storage unavailable, retry later")
    rows = res[0] or []
    body = "\n".join(rows) + ("\n" if rows else "")
    return _Resp(content=body, media_type="application/x-ndjson",
                 headers={"Cache-Control": "no-store", "X-Next-Offset": str(offset + len(rows))})


print(f"[part41] v{VERSION} dataset export {'ready' if ADMIN_TOKEN else 'off (set ADMIN_TOKEN)'}")
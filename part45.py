# ---------- v2.32: Risk Cluster Detection ----------
# Fingerprint top holders + gán cluster_id + survival rate.

VERSION = "2.32.0"
app.version = VERSION
app.openapi_schema = None

import hashlib
import json

CLUSTER_KEY = "cluster:{}"              # cluster:{fingerprint} → meta
CLUSTER_MEMBERS = "clmem:{}"            # set of mints
CLUSTER_TTL = 45 * 24 * 3600

def _holder_fingerprint(top_owners: list) -> str:
    """Hash ổn định của top 5 owners (bỏ % để nhóm gần nhau)."""
    if not top_owners:
        return ""
    owners = sorted([o for o, _ in top_owners[:5]])
    raw = "|".join(owners)
    return hashlib.sha256(raw.encode()).hexdigest()[:12]

async def _update_cluster(client, mint: str, fp: str, ts: int):
    if not PRED_ENABLED or not client or not fp:
        return None
    try:
        meta_key = CLUSTER_KEY.format(fp)
        mem_key = CLUSTER_MEMBERS.format(fp)
        # lấy meta hiện tại
        raw = await redis_get(client, meta_key)
        meta = json.loads(raw) if raw else {
            "id": f"cl_{fp}",
            "first_seen": ts,
            "last_seen": ts,
            "size": 0,
            "n_rugs": 0,
        }
        meta["last_seen"] = ts
        meta["size"] = meta.get("size", 0) + 1

        pipe = [
            ["SADD", mem_key, mint],
            ["EXPIRE", mem_key, CLUSTER_TTL],
            ["SET", meta_key, json.dumps(meta), "EX", CLUSTER_TTL],
        ]
        await redis_pipe(client, pipe)
        return meta
    except Exception:
        return None

async def get_cluster_info(client, fp: str) -> dict:
    if not PRED_ENABLED or not client or not fp:
        return {}
    try:
        raw = await redis_get(client, CLUSTER_KEY.format(fp))
        return json.loads(raw) if raw else {}
    except Exception:
        return {}

# ---------- gắn vào pipeline ----------
_build_signal_v31 = build_signal

async def build_signal(client: httpx.AsyncClient, mint: str, security: bool, prefetched: Optional[dict] = None):
    result, status = await _build_signal_v31(client, mint, security, prefetched)
    try:
        hq = result.get("holder_quality") or {}
        tops = hq.get("top_owners") or []
        fp = _holder_fingerprint(tops)
        if fp:
            meta = await _update_cluster(client, mint, fp, result.get("_snap_ts") or int(time.time()))
            if meta:
                # chỉ gắn internal, không public hết
                result["_cluster"] = {
                    "id": meta.get("id"),
                    "fingerprint": fp,
                    "size": meta.get("size"),
                    "first_seen": meta.get("first_seen"),
                }
    except Exception:
        pass
    return result, status
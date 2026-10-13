# ---------- v2.40: Smart RPC Rotator + Private Ready ----------
# Xoay vòng nhiều endpoint free, tự tránh rate-limit, sẵn sàng chuyển sang private/self-host.

VERSION = "2.40.0"
app.version = VERSION
app.openapi_schema = None

import os
import time
import random
from typing import List, Optional, Dict, Any

# ----- Cấu hình -----
# Ưu tiên private nếu có
PRIVATE_RPC_URL = (os.getenv("SOLANA_RPC_URL") or "").strip()
PRIVATE_RPC = os.getenv("PRIVATE_RPC", "").lower() in ("1", "true", "yes") and bool(PRIVATE_RPC_URL)

# Danh sách free endpoint (có thể thêm bớt)
FREE_RPCS = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-mainnet.g.alchemy.com/v2/demo",           # Alchemy demo
    "https://rpc.ankr.com/solana",
    "https://solana-api.projectserum.com",
    # Thêm Helius free key của bạn vào đây nếu có:
    # "https://mainnet.helius-rpc.com/?api-key=YOUR_FREE_KEY",
]

# Fallback từ env (ngăn cách bằng dấu phẩy)
_extra = (os.getenv("SOLANA_RPC_FALLBACKS") or "").strip()
if _extra:
    FREE_RPCS.extend([u.strip() for u in _extra.split(",") if u.strip()])

# Theo dõi sức khỏe từng endpoint
_rpc_stats: Dict[str, Dict[str, Any]] = {}
RPC_FAIL_COOLDOWN = 45          # giây tạm nghỉ khi fail
RPC_SLOW_THRESHOLD_MS = 1800    # coi là chậm

def _record_rpc(url: str, ok: bool, ms: float):
    st = _rpc_stats.setdefault(url, {"ok": 0, "fail": 0, "last_fail": 0, "avg_ms": 0, "samples": 0})
    st["samples"] += 1
    if ok:
        st["ok"] += 1
        # moving average đơn giản
        st["avg_ms"] = round((st["avg_ms"] * 0.7) + (ms * 0.3), 1)
    else:
        st["fail"] += 1
        st["last_fail"] = time.time()

def _pick_rpc() -> List[str]:
    """Trả về danh sách endpoint theo thứ tự ưu tiên."""
    now = time.time()
    candidates = []

    # 1. Private trước (nếu bật)
    if PRIVATE_RPC:
        candidates.append(PRIVATE_RPC_URL)

    # 2. Free endpoints còn khỏe
    healthy = []
    for url in FREE_RPCS:
        st = _rpc_stats.get(url, {})
        last_fail = st.get("last_fail", 0)
        if now - last_fail < RPC_FAIL_COOLDOWN:
            continue
        healthy.append(url)

    # Sắp xếp: ít fail + nhanh hơn lên trước
    def score(u):
        st = _rpc_stats.get(u, {})
        fail_rate = st.get("fail", 0) / max(1, st.get("samples", 1))
        avg = st.get("avg_ms", 999)
        return (fail_rate, avg)

    healthy.sort(key=score)
    candidates.extend(healthy)

    # Nếu không còn gì thì dùng lại list gốc
    if not candidates:
        candidates = list(FREE_RPCS)

    return candidates

# ----- Ghi đè hàm rpc -----
async def rpc(client: httpx.AsyncClient, method: str, params: list):
    """Thử lần lượt các endpoint, tự tránh cái đang chết/chậm."""
    urls = _pick_rpc()
    last_err = None

    for url in urls:
        t0 = time.time()
        try:
            resp = await client.post(
                url,
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                timeout=5.5,
            )
            ms = (time.time() - t0) * 1000
            resp.raise_for_status()
            body = resp.json()
            if body.get("error"):
                raise RuntimeError(str(body["error"])[:180])

            _record_rpc(url, True, ms)
            return body.get("result")
        except Exception as e:
            ms = (time.time() - t0) * 1000
            _record_rpc(url, False, ms)
            last_err = e
            continue

    raise last_err or RuntimeError("All RPC endpoints failed")

# ----- Gắn thông tin nguồn vào signal -----
_build_prev_rpc = build_signal

async def build_signal(client: httpx.AsyncClient, mint: str, security: bool, prefetched: Optional[dict] = None):
    result, status = await _build_prev_rpc(client, mint, security, prefetched)

    try:
        if security and result.get("security"):
            result["security"]["rpc_mode"] = "private" if PRIVATE_RPC else "rotator"
            # Thêm stats nhẹ (chỉ khi debug)
            if os.getenv("RPC_DEBUG", "").lower() in ("1", "true"):
                result["security"]["rpc_stats"] = {
                    u.split("/")[2][:20]: {
                        "ok": st.get("ok", 0),
                        "fail": st.get("fail", 0),
                        "avg_ms": st.get("avg_ms", 0),
                    }
                    for u, st in list(_rpc_stats.items())[:6]
                }
    except Exception:
        pass

    return result, status
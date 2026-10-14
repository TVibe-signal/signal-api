# part61.py (v2.45.1) - Vá RPC rotator của part52. Đặt SAU part52 (khuyến nghị: ngay sau part60).
# 1) Có SOLANA_RPC_URL thì luôn dùng nó đầu tiên (tắt bằng PRIVATE_RPC=false), không cần đặt PRIVATE_RPC=true.
# 2) Bỏ endpoint đã ngừng hoạt động (projectserum).
# 3) Lỗi JSON-RPC theo từng request (mint sai: -32602...) KHÔNG làm endpoint bị phạt và không thử lại các endpoint khác.
# 4) Cooldown tăng dần khi lỗi liên tiếp (45s -> 90s -> ... tối đa 10 phút); private có cooldown ngắn hơn.
# 5) Timeout mỗi endpoint 3s khi còn endpoint dự phòng, tổng thời gian tối đa 8s cho 1 lệnh gọi.

VERSION = "2.45.1"
app.version = VERSION
app.openapi_schema = None

import os
import time

PRIVATE_RPC = bool(PRIVATE_RPC_URL) and os.getenv("PRIVATE_RPC", "true").lower() not in ("0", "false", "no")
FREE_RPCS[:] = [u for u in FREE_RPCS if "projectserum" not in u]

HG61_REQUEST_ERRORS = {-32600, -32601, -32602}     # lỗi do yêu cầu, không phải do endpoint


class _Hg61RequestError(RuntimeError):
    """Yêu cầu sai (mint sai...). Là RuntimeError nên code gọi cũ vẫn bắt được."""

HG61_TIMEOUT_MULTI = 3.0
HG61_TIMEOUT_LAST = 5.5
HG61_TOTAL_S = 8.0
HG61_PRIVATE_COOLDOWN = 15
HG61_MAX_COOLDOWN = 600


def _record_rpc(url, ok, ms):
    st = _rpc_stats.setdefault(url, {"ok": 0, "fail": 0, "last_fail": 0, "avg_ms": 0, "samples": 0, "consec": 0})
    st["samples"] += 1
    if ok:
        st["ok"] += 1
        st["consec"] = 0
        st["avg_ms"] = round(ms if not st["avg_ms"] else st["avg_ms"] * 0.7 + ms * 0.3, 1)
    else:
        st["fail"] += 1
        st["consec"] = st.get("consec", 0) + 1
        st["last_fail"] = time.time()


def _hg61_cooling(url, base):
    st = _rpc_stats.get(url) or {}
    c = st.get("consec", 0)
    if not c:
        return False
    return time.time() - st.get("last_fail", 0) < min(HG61_MAX_COOLDOWN, base * 2 ** (c - 1))


def _pick_rpc():
    out = []
    if PRIVATE_RPC and not _hg61_cooling(PRIVATE_RPC_URL, HG61_PRIVATE_COOLDOWN):
        out.append(PRIVATE_RPC_URL)
    healthy = [u for u in FREE_RPCS if not _hg61_cooling(u, RPC_FAIL_COOLDOWN)]

    def score(u):
        st = _rpc_stats.get(u) or {}
        return (st.get("fail", 0) / max(1, st.get("samples", 0)), st.get("avg_ms") or 999)

    healthy.sort(key=score)
    out += healthy
    if not out:                                   # tất cả đang nghỉ: thử lại toàn bộ thay vì bỏ cuộc
        out = ([PRIVATE_RPC_URL] if PRIVATE_RPC else []) + list(FREE_RPCS)
    return out


async def rpc(client, method, params):
    urls = _pick_rpc()
    last_err = None
    deadline = time.time() + HG61_TOTAL_S
    for i, url in enumerate(urls):
        if i and time.time() >= deadline:
            break
        t0 = time.time()
        try:
            resp = await client.post(
                url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                timeout=HG61_TIMEOUT_MULTI if i < len(urls) - 1 else HG61_TIMEOUT_LAST)
            ms = (time.time() - t0) * 1000
            resp.raise_for_status()
            body = resp.json()
            err = body.get("error") if isinstance(body, dict) else None
            if err:
                code = err.get("code") if isinstance(err, dict) else None
                if code in HG61_REQUEST_ERRORS:           # endpoint khoẻ, yêu cầu sai
                    _record_rpc(url, True, ms)
                    raise _Hg61RequestError(str(err)[:180])
                raise RuntimeError(str(err)[:180])
            _record_rpc(url, True, ms)
            return body.get("result")
        except _Hg61RequestError:
            raise
        except Exception as e:
            _record_rpc(url, False, (time.time() - t0) * 1000)
            last_err = e
    raise last_err or RuntimeError("All RPC endpoints failed")

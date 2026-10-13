# ---------- v2.43: Self-Improving Signal Loop (Experimental) ----------
VERSION = "2.43.0"
app.version = VERSION
app.openapi_schema = None

import os
import json
import time
from typing import Dict, Any, List

# Bật/tắt toàn bộ tính năng
SELF_IMPROVE = os.getenv("SELF_IMPROVE", "true").lower() in ("1", "true", "yes")
# Có cho phép tự động áp dụng thay đổi không? (mặc định chỉ đề xuất)
SELF_APPLY = os.getenv("SELF_APPLY", "false").lower() in ("1", "true", "yes")

# Ngưỡng an toàn
MIN_SAMPLES_FLAG = 40          # flag phải có ít nhất 40 mẫu mới xét
MIN_TOTAL_JUDGED = 200         # tổng judged tối thiểu
MAX_WEIGHT_CHANGE = 6          # mỗi lần chỉ được thay đổi tối đa ±6
WEIGHT_FLOOR = 0               # weight không được âm
WEIGHT_CEILING = 45            # weight không được quá cao

EVOL_LOG_KEY = "evol:log"      # danh sách các lần tiến hóa
EVOL_STATE_KEY = "evol:state"  # trạng thái hiện tại của self-improve

async def _get_flag_performance(client) -> Dict[str, Dict]:
    """Lấy hiệu quả hiện tại của từng flag từ track-record."""
    if not PRED_ENABLED:
        return {}
    try:
        # Lấy tất cả key liên quan đến flag
        raw = await redis_pipe(client, [["HGETALL", "st"]])
        st = to_dict((raw or [{}])[0] or {})
        perf = {}
        for k, v in st.items():
            if k.startswith("f:") and k.endswith(":n"):
                flag = k[2:-2]
                n = int(v or 0)
                bad = int(st.get(f"f:{flag}:bad", 0))
                if n >= 5:
                    perf[flag] = {
                        "n": n,
                        "bad": bad,
                        "bad_rate": round(bad / n, 3) if n else 0,
                    }
        return perf
    except Exception:
        return {}

async def _propose_adjustments(client) -> List[Dict]:
    """Đề xuất điều chỉnh weight dựa trên performance."""
    if not SELF_IMPROVE:
        return []

    perf = await _get_flag_performance(client)
    if not perf:
        return []

    proposals = []
    current_weights = dict(RISK_WEIGHTS) if "RISK_WEIGHTS" in globals() else {}

    for flag, data in perf.items():
        if data["n"] < MIN_SAMPLES_FLAG:
            continue

        rate = data["bad_rate"]
        old_w = current_weights.get(flag, 0)

        # Logic đơn giản:
        # - bad_rate rất cao → tăng weight
        # - bad_rate thấp → giảm weight
        new_w = old_w
        reason = ""

        if rate >= 0.75 and old_w < WEIGHT_CEILING:
            delta = min(MAX_WEIGHT_CHANGE, 4)
            new_w = min(WEIGHT_CEILING, old_w + delta)
            reason = f"high bad_rate {rate:.2f} → increase"
        elif rate <= 0.35 and old_w > WEIGHT_FLOOR:
            delta = min(MAX_WEIGHT_CHANGE, 3)
            new_w = max(WEIGHT_FLOOR, old_w - delta)
            reason = f"low bad_rate {rate:.2f} → decrease"

        if new_w != old_w:
            proposals.append({
                "flag": flag,
                "old_weight": old_w,
                "new_weight": new_w,
                "n": data["n"],
                "bad_rate": rate,
                "reason": reason,
            })

    return proposals

async def _apply_proposals(client, proposals: List[Dict]):
    """Áp dụng đề xuất (chỉ khi SELF_APPLY=true)."""
    if not SELF_APPLY or not proposals:
        return False

    try:
        # Ghi log trước khi thay đổi
        entry = {
            "ts": int(time.time()),
            "applied": True,
            "changes": proposals,
        }
        await redis_pipe(client, [
            ["LPUSH", EVOL_LOG_KEY, json.dumps(entry)],
            ["LTRIM", EVOL_LOG_KEY, 0, 49],
        ])

        # Áp dụng vào RISK_WEIGHTS (runtime)
        for p in proposals:
            if p["flag"] in RISK_WEIGHTS:
                RISK_WEIGHTS[p["flag"]] = p["new_weight"]

        return True
    except Exception:
        return False

async def run_self_improve(client) -> Dict[str, Any]:
    """Chạy một vòng self-improve."""
    if not SELF_IMPROVE:
        return {"status": "disabled"}

    proposals = await _propose_adjustments(client)
    applied = False
    if proposals and SELF_APPLY:
        applied = await _apply_proposals(client, proposals)
    elif proposals:
        # Chỉ ghi log đề xuất, chưa apply
        entry = {
            "ts": int(time.time()),
            "applied": False,
            "changes": proposals,
        }
        await redis_pipe(client, [
            ["LPUSH", EVOL_LOG_KEY, json.dumps(entry)],
            ["LTRIM", EVOL_LOG_KEY, 0, 49],
        ])

    return {
        "status": "ok",
        "proposals": len(proposals),
        "applied": applied,
        "details": proposals[:8],
    }

# ---------- Endpoint xem quá trình tiến hóa ----------
@app.get("/evolution", tags=["experimental"])
async def evolution_log(request: Request, limit: int = 10):
    if not PRED_ENABLED:
        return {"enabled": False}
    client = request.app.state.client
    res = await redis_pipe(client, [["LRANGE", EVOL_LOG_KEY, 0, max(1, min(limit, 30)) - 1]])
    logs = []
    for raw in (res or [[]])[0] or []:
        try:
            logs.append(json.loads(raw))
        except Exception:
            continue
    return {
        "self_improve": SELF_IMPROVE,
        "self_apply": SELF_APPLY,
        "logs": logs,
    }

# ---------- Tự chạy định kỳ (nhẹ) ----------
_last_evol = 0
EVOL_INTERVAL = 6 * 3600   # 6 giờ một lần

_build_prev_evol = build_signal

async def build_signal(client, mint, security, prefetched=None):
    global _last_evol
    result, status = await _build_prev_evol(client, mint, security, prefetched)

    # Chạy self-improve thưa thôi, không ảnh hưởng latency
    try:
        now = time.time()
        if SELF_IMPROVE and now - _last_evol > EVOL_INTERVAL:
            _last_evol = now
            await run_self_improve(client)
    except Exception:
        pass

    return result, status

print(f"[part57] v{VERSION} Self-Improving Loop loaded (apply={SELF_APPLY})")
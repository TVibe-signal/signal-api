# ---------- v2.31: Holder Behavior Graph ----------
# Theo dõi action của top holders qua thời gian + co-hold.

VERSION = "2.31.0"
app.version = VERSION
app.openapi_schema = None

import json
from collections import defaultdict

WALLET_ACTIONS_KEY = "wact:{}"          # list of actions
WALLET_TOKENS_KEY = "wtok:{}"           # set of mints
COHOLD_KEY = "cohold:{}:{}"             # counter
WALLET_PROFILE_TTL = 60 * 24 * 3600     # 60 ngày
ACTION_TTL = 90 * 24 * 3600

def _record_actions(prev_tops: list, curr_tops: list, mint: str, ts: int) -> list:
    """So sánh prev vs curr → sinh list action."""
    actions = []
    prev_map = {o: p for o, p in (prev_tops or [])}
    curr_map = {o: p for o, p in (curr_tops or [])}

    for owner, pct in curr_tops or []:
        old = prev_map.get(owner, 0.0)
        delta = pct - old
        if abs(delta) < 1.5:          # bỏ nhiễu nhỏ
            continue
        action = "accumulate" if delta > 0 else "dump"
        actions.append({
            "wallet": owner,
            "mint": mint,
            "action": action,
            "delta_pct": round(delta, 2),
            "ts": ts,
        })
    return actions

async def _save_wallet_actions(client, actions: list):
    if not PRED_ENABLED or not client or not actions:
        return
    try:
        pipe = []
        for a in actions:
            w = a["wallet"]
            pipe.append(["LPUSH", WALLET_ACTIONS_KEY.format(w), json.dumps(a)])
            pipe.append(["LTRIM", WALLET_ACTIONS_KEY.format(w), 0, 199])  # giữ 200 action gần nhất
            pipe.append(["EXPIRE", WALLET_ACTIONS_KEY.format(w), ACTION_TTL])
            pipe.append(["SADD", WALLET_TOKENS_KEY.format(w), a["mint"]])
            pipe.append(["EXPIRE", WALLET_TOKENS_KEY.format(w), WALLET_PROFILE_TTL])
        # co-hold
        wallets = list({a["wallet"] for a in actions})
        for i in range(len(wallets)):
            for j in range(i + 1, len(wallets)):
                a, b = sorted([wallets[i], wallets[j]])
                pipe.append(["INCR", COHOLD_KEY.format(a, b)])
                pipe.append(["EXPIRE", COHOLD_KEY.format(a, b), WALLET_PROFILE_TTL])
        if pipe:
            await redis_pipe(client, pipe)
    except Exception:
        pass

async def get_wallet_profile(client, wallet: str) -> dict:
    """Trả về profile đơn giản của 1 wallet (dùng nội bộ)."""
    if not PRED_ENABLED or not client:
        return {}
    try:
        raw_acts = await redis_get(client, WALLET_ACTIONS_KEY.format(wallet))  # sẽ là list, cần LRANGE
        # vì redis_get hiện tại là GET, ta dùng pipe
        res = await redis_pipe(client, [
            ["LRANGE", WALLET_ACTIONS_KEY.format(wallet), 0, 49],
            ["SCARD", WALLET_TOKENS_KEY.format(wallet)],
        ])
        acts_raw, n_tokens = res[0] or [], res[1] or 0
        acts = [json.loads(x) for x in acts_raw if x]
        dumps = sum(1 for a in acts if a.get("action") == "dump")
        accums = sum(1 for a in acts if a.get("action") == "accumulate")
        total = dumps + accums or 1
        return {
            "wallet": wallet,
            "n_tokens": int(n_tokens),
            "n_actions": len(acts),
            "dump_rate": round(dumps / total, 3),
            "accum_rate": round(accums / total, 3),
            "recent_actions": acts[:10],
        }
    except Exception:
        return {}

# ---------- gắn vào pipeline (sau holder_quality) ----------
_build_signal_v30 = build_signal

async def build_signal(client: httpx.AsyncClient, mint: str, security: bool, prefetched: Optional[dict] = None):
    result, status = await _build_signal_v30(client, mint, security, prefetched)
    try:
        hq = result.get("holder_quality") or {}
        curr_tops = hq.get("top_owners") or []
        # lấy prev từ cache cũ (đã có trong part18)
        prev = await _load_prev_tops(client, mint) if "_load_prev_tops" in globals() else None
        actions = _record_actions(prev, curr_tops, mint, result.get("_snap_ts") or int(time.time()))
        await _save_wallet_actions(client, actions)
    except Exception:
        pass
    return result, status
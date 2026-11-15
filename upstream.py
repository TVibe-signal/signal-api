import asyncio

UPSTREAM_CHECK_EVERY_S = 60
MAX_DIFF_PCT = 3
_upstream = {"status": "unknown", "checked_s_ago": None, "price_diff_pct": None}

def upstream_status():
    return _upstream

async def check_upstream_loop(get_dex_canary, get_gecko_canary, is_valid_shape):
    global _upstream
    while True:
        try:
            dex = await get_dex_canary()
            gecko = await get_gecko_canary()
            dex_ok = is_valid_shape(dex)
            gecko_ok = is_valid_shape(gecko)
            if dex_ok and gecko_ok:
                diff = abs(dex - gecko) / dex * 100 if dex else None
                status = "ok" if diff <= MAX_DIFF_PCT else "diverged"
            elif dex_ok or gecko_ok:
                status = "partial"
                diff = None
            else:
                status = "both_down"
                diff = None
            _upstream = {"status": status, "checked_s_ago": 0, "price_diff_pct": diff, "dexscreener": {"ok": dex_ok}, "geckoterminal": {"ok": gecko_ok}}
        except Exception as e:
            _upstream = {"status": "both_down", "checked_s_ago": 0, "price_diff_pct": None, "error": str(e)}
        await asyncio.sleep(UPSTREAM_CHECK_EVERY_S)
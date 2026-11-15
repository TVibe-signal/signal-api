import asyncio

MAX_PER_DAY = 40
INTERVAL_S = 900

async def seed_job(upstream_status_fn, make_verdict, random_mint, save, log, save_error):
    if upstream_status_fn() == "both_down":
        log("seed paused: upstream down")
        return
    try:
        v = await make_verdict(random_mint())
        save(v)
    except Exception as e:
        if type(e).__name__ == "RateLimitError":
            await asyncio.sleep(300)
            return
        log(f"seed error: {type(e).__name__}: {e}")
        save_error({"type": type(e).__name__, "msg": str(e)})
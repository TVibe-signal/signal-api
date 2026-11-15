MIN_SAMPLES_FOR_RATE = 10

def success_rate(samples):
    # samples: [{ok:bool, ms:int, ts:float}]
    if len(samples) < MIN_SAMPLES_FOR_RATE:
        import time
        last = None
        ok = [s for s in samples if s.get("ok")]
        if ok:
            last = int(time.time() - max(s["ts"] for s in ok))
        return {"status": "warming_up", "success_rate_pct": None, "samples": len(samples), "last_success_s_ago": last, "note": "insufficient_samples"}
    rate = sum(1 for s in samples if s.get("ok")) / len(samples) * 100
    avg = sum(s.get("ms", 0) for s in samples) / len(samples) if samples else 0
    return {"status": "ok" if rate > 80 else "degraded" if rate > 30 else "down", "success_rate_pct": round(rate, 1), "samples": len(samples), "avg_ms": round(avg, 1)}
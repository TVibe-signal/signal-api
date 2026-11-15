# patch_p0.py - P0 fix, load SAU khi core/features/extensions load xong.
# Không sửa file dài, chỉ ghi đè ở runtime.
import time

def apply(G):
    # 1. Ép version - thắng hết mấy cái 2.72 / 3.0.27 trong extensions.py
    for k in ("VERSION", "APP_VERSION", "__version__", "API_VERSION"):
        G[k] = "3.0.28"
    try:
        G["app"].version = "3.0.28"
    except Exception:
        pass

    # 2. Ép config P0
    for k, v in (("STALE_MAX", 600), ("STALE_MAX_S", 600),
                 ("CACHE_MAX", 1000), ("CACHE_SIZE", 1000),
                 ("UPSTREAM_EVERY_S", 60)):
        G[k] = v

    # 3. Wrap build_signal: stale / confidence low -> pass = False
    orig = G.get("build_signal")
    if not callable(orig):
        print("[patch_p0] no build_signal to wrap")
        return

    async def wrapped(client, mint, security, prefetched=None):
        result, status = await orig(client, mint, security, prefetched)
        try:
            if not isinstance(result, dict):
                return result, status
            decision = result.get("decision") or {}
            filt = result.get("filter") or {}

            # Sync unknowns: ngoài và trong decision phải giống nhau
            unknowns = decision.get("unknowns") or result.get("unknowns") or []
            result["unknowns"] = unknowns
            decision["unknowns"] = unknowns

            # Tính stale: timestamp cũ quá 600s hoặc cờ stale/partial
            age = None
            ts = result.get("timestamp")
            if isinstance(ts, (int, float)):
                age = time.time() - ts
            is_stale = bool(result.get("stale") or result.get("partial"))
            if age is not None and age > 600:
                is_stale = True

            # Confidence low?
            conf = result.get("decision_confidence") or {}
            conf_low = (conf.get("level") == "low") if isinstance(conf, dict) else False

            # pass_strict = pass gốc nhưng phải KHÔNG stale + KHÔNG low
            strict = bool(filt.get("pass")) and (not is_stale) and (not conf_low)
            filt["pass_strict"] = strict
            # P0: stale / low thì pass phải là False
            if is_stale or conf_low:
                filt["pass"] = False
            result["filter"] = filt
            result["decision"] = decision
            result["filter_pass_strict"] = strict
        except Exception as e:
            print(f"[patch_p0] wrap skip: {e}")
        return result, status

    G["build_signal"] = wrapped
    print("[patch_p0] applied v3.0.28")
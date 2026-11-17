"""patch_usdc_pair_v2.py - Fix mint -> no result for USDC-quoted / PumpSwap pairs (e.g. CBUCKS).

Root cause (found in repo):
- Render runs `uvicorn main:app`. Old main.py loaded old core.py which has NO /omni route,
  so /omni returned FastAPI {"detail":"Not Found"}. That is fixed by the new main.py
  (loads core_final), not by this file alone.
- Even with core_final, pick_best_pair() only matched baseToken == mint.
  For CBUCKS/USDC on PumpSwap, DexScreener can return the pair with USDC as base
  and CBUCKS as quote, so the mint was missed -> 404 / empty result.
- When mint is quote, priceUsd in DexScreener is the BASE token price (USDC ~ $1),
  not the mint price. Must invert via priceNative.

This file is loaded by main.py AFTER extensions, BEFORE home_live.
apply(g) patches BOTH:
  - g (shared namespace used by features/extensions exec)
  - core_final module globals (used by _build_signal_core defined in core_final)
  - fetch_dex: if /tokens/{mint} returns 0 pairs, fallback to /search?q={mint}
"""
import copy

DEX_SEARCH_URL = "https://api.dexscreener.com/latest/dex/search?q={mint}"

def _liq(p):
    try:
        return float((p.get("liquidity") or {}).get("usd") or 0)
    except Exception:
        return 0

def _invert_for_quote(pair, mint):
    """If mint is quoteToken, return a copy with price corrected to mint price."""
    base = (pair.get("baseToken") or {}).get("address")
    quote = (pair.get("quoteToken") or {}).get("address")
    if quote != mint or base == mint:
        return pair
    # mint is quote only -> invert
    try:
        price_usd = float(pair.get("priceUsd") or 0)
        price_native = float(pair.get("priceNative") or 0)
    except Exception:
        return pair
    if not price_usd or not price_native:
        return pair
    out = copy.deepcopy(pair)
    # price of quote in USD = price of base in USD / (quote per 1 base)
    # priceNative = price of base in quote units
    out["priceUsd"] = str(price_usd / price_native)
    out["priceNative"] = str(1.0 / price_native) if price_native else out.get("priceNative")
    # priceChange of base is opposite sign for quote (approx, avoids showing USDC ~0% as CBUCKS change)
    pc = out.get("priceChange") or {}
    if isinstance(pc, dict):
        out["priceChange"] = {k: (-float(v) if isinstance(v, (int, float)) else v) for k, v in pc.items()}
    # swap base/quote labels so downstream compute_signals reads the mint as base
    out["baseToken"], out["quoteToken"] = out.get("quoteToken"), out.get("baseToken")
    out["_tvibe_quote_inverted"] = True
    return out

def pick_best_pair_fixed(pairs, mint):
    if not pairs:
        return None
    sol = [p for p in pairs if p.get("chainId") == "solana"]
    if not sol:
        return None
    matched = [p for p in sol if (p.get("baseToken") or {}).get("address") == mint
               or (p.get("quoteToken") or {}).get("address") == mint]
    pool = matched or sol
    best = max(pool, key=_liq)
    return _invert_for_quote(best, mint)

def apply(g):
    # 1) patch shared namespace g
    g["pick_best_pair"] = pick_best_pair_fixed
    # 2) patch core_final module (where _build_signal_core lives)
    try:
        import core_final as _cf
        _cf.pick_best_pair = pick_best_pair_fixed
        print("[patch_usdc_pair_v2] core_final.pick_best_pair patched")
    except Exception as e:
        print(f"[patch_usdc_pair_v2] core_final patch skipped: {e}")
    # 3) patch core module too if present (old code path)
    try:
        import core as _c
        _c.pick_best_pair = pick_best_pair_fixed
    except Exception:
        pass

    # 4) fetch_dex fallback: empty pairs -> search API
    orig_fetch = g.get("fetch_dex")
    if callable(orig_fetch):
        async def fetch_dex_fixed(client, mint, *a, **kw):
            data = await orig_fetch(client, mint, *a, **kw)
            pairs = (data or {}).get("pairs") or [] if isinstance(data, dict) else []
            if pairs:
                return data
            # Fallback: DexScreener search often finds PumpSwap USDC pairs that /tokens misses
            try:
                resp = await client.get(DEX_SEARCH_URL.format(mint=mint))
                resp.raise_for_status()
                spairs = (resp.json() or {}).get("pairs") or []
                # keep only Solana pairs containing this mint on either side
                spairs = [p for p in spairs if p.get("chainId") == "solana" and mint in (
                    (p.get("baseToken") or {}).get("address"), (p.get("quoteToken") or {}).get("address"))]
                if spairs:
                    print(f"[patch_usdc_pair_v2] search fallback found {len(spairs)} pairs for {mint[:8]}")
                    return {"pairs": spairs}
            except Exception as e:
                print(f"[patch_usdc_pair_v2] search fallback failed: {e}")
            return data
        g["fetch_dex"] = fetch_dex_fixed
        try:
            import core_final as _cf2
            _cf2.fetch_dex = fetch_dex_fixed
        except Exception:
            pass
        print("[patch_usdc_pair_v2] fetch_dex search fallback patched")
    print("[patch_usdc_pair_v2] applied: base OR quote + price inversion + search fallback")

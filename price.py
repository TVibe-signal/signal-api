from circuit_breaker import breakers, CircuitOpenError

async def get_price_with_fallback(mint, fetch_price):
    for source in ["dexscreener", "geckoterminal", "jupiter"]:
        try:
            return await breakers[source].call(lambda s=source: fetch_price(s, mint))
        except CircuitOpenError:
            continue
        except Exception:
            continue
    return {"price": None, "source": None, "all_down": True}

# Jupiter thêm: check route + slippage
# if jupiter_route is None -> liquidity chết -> skip
# if slippage_1sol > 10% -> caution liquidity mỏng
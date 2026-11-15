import os

RPC_PROVIDERS = [
    f"https://mainnet.helius-rpc.com/?api-key={os.getenv('HELIUS_API_KEY','')}",
    os.getenv("QUICKNODE_RPC_URL",""),
    "https://api.mainnet-beta.solana.com",
]

async def call_rpc(http_post, method, params):
    last = None
    for url in RPC_PROVIDERS:
        if not url:
            continue
        try:
            r = await http_post(url, {"method": method, "params": params}, timeout=3)
            if getattr(r, "status_code", 200) == 200:
                return r.json() if hasattr(r, "json") else r
        except Exception as e:
            last = e
            continue
    raise last or RuntimeError("all RPC providers failed")
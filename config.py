import os
from dataclasses import dataclass

@dataclass
class Settings:
    dexscreener_api_key: str = os.getenv("DEXSCREENER_API_KEY", "")
    geckoterminal_api_key: str = os.getenv("GECKOTERMINAL_API_KEY", "")
    helius_api_key: str = os.getenv("HELIUS_API_KEY", "")
    quicknode_rpc_url: str = os.getenv("QUICKNODE_RPC_URL", "")
    jupiter_api_key: str = os.getenv("JUPITER_API_KEY", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    cache_size: int = int(os.getenv("CACHE_SIZE", "1000"))
    cache_ttl_s: int = int(os.getenv("CACHE_TTL_S", "360"))
    stale_max_s: int = int(os.getenv("STALE_MAX_S", "600"))
    upstream_check_every_s: int = int(os.getenv("UPSTREAM_CHECK_EVERY_S", "60"))
    max_diff_pct: float = float(os.getenv("MAX_DIFF_PCT", "3"))
    min_samples_for_rate: int = int(os.getenv("MIN_SAMPLES_FOR_RATE", "10"))
    community_min_n: int = int(os.getenv("COMMUNITY_MIN_N", "20"))

    @property
    def api_keys_configured(self) -> int:
        return sum([
            bool(self.dexscreener_api_key),
            bool(self.geckoterminal_api_key),
            bool(self.helius_api_key),
            bool(self.jupiter_api_key),
        ])

settings = Settings()
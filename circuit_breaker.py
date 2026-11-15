import time

class CircuitOpenError(Exception):
    def __init__(self, retry_after_s=60):
        self.retry_after_s = retry_after_s
        super().__init__(f"circuit open, retry_after_s={retry_after_s}")

class CircuitBreaker:
    def __init__(self, fail_threshold=3, base_cooldown_s=60):
        self.fail_count = 0
        self.open_until = 0
        self.fail_threshold = fail_threshold
        self.base_cooldown_s = base_cooldown_s

    async def call(self, fn):
        now = time.time()
        if now < self.open_until:
            raise CircuitOpenError(retry_after_s=int(self.open_until - now))
        try:
            r = await fn()
            self.fail_count = 0
            return r
        except Exception as e:
            self.fail_count += 1
            if self.fail_count >= self.fail_threshold:
                backoff = self.base_cooldown_s * (2 ** (self.fail_count - self.fail_threshold))
                self.open_until = now + backoff
            raise e

    def status(self):
        return {
            "open": time.time() < self.open_until,
            "retry_after_s": max(0, int(self.open_until - time.time())),
            "failed_checks_in_a_row": self.fail_count,
        }

breakers = {k: CircuitBreaker() for k in ["dexscreener","geckoterminal","solana_rpc","jupiter","rugcheck"]}
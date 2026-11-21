"""Offline tests for pro_engine (no network, no FastAPI needed).

Run:  python -m pytest -q tests/test_pro_engine.py     or     python tests/test_pro_engine.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SOLANA_RPC_URL"] = "http://fake-rpc.invalid/?api-key=SECRET"

import pro_engine as pe  # noqa: E402

MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
POOL = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"        # used as pair address / pool owner
CREATOR = "So11111111111111111111111111111111111111112"      # any valid pubkey
WHALE = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
OTHER = "11111111111111111111111111111111"                   # burn owner
LPMINT = "Vote111111111111111111111111111111111111111"
ACCT = ["Stake11111111111111111111111111111111111111", "SysvarC1ock11111111111111111111111111111111",
        "SysvarRent111111111111111111111111111111111", "ComputeBudget111111111111111111111111111111"]


class Fake:
    """Programmable fake of DexScreener + RPC + Raydium."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.dex_status = 200
        self.pairs = [self.pair()]
        self.rpc_up = True
        self.sigs_pages = [[{"signature": "SIGOLD"}]]          # newest page first
        self.creator = CREATOR
        self.owners = {ACCT[0]: POOL, ACCT[1]: WHALE, ACCT[2]: "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",
                       ACCT[3]: "SysvarS1otHashes111111111111111111111111111"}
        self.balances = {ACCT[0]: 600, ACCT[1]: 20, ACCT[2]: 100, ACCT[3]: 5}
        self.supply = 1000
        self.mint_auth = None
        self.freeze_auth = None
        self.calls = []
        self.lp_owner_burn = True

    @staticmethod
    def pair(dex="raydium", liq=80000, vol=120000, age_h=500, change=3.0):
        return {"chainId": "solana", "dexId": dex, "pairAddress": POOL,
                "baseToken": {"address": MINT, "symbol": "TST", "name": "Test"},
                "priceUsd": "0.01", "liquidity": {"usd": liq}, "volume": {"h24": vol},
                "priceChange": {"h24": change}, "pairCreatedAt": int((time.time() - age_h * 3600) * 1000)}

    def get(self, url, timeout=6.0, headers=None):
        self.calls.append(("GET", url.split("?")[0]))
        if "dexscreener" in url:
            if self.dex_status != 200:
                return self.dex_status, None
            return 200, {"pairs": self.pairs}
        if "geckoterminal" in url:
            return 404, None
        if "raydium" in url:
            return 200, {"data": [{"lpMint": {"address": LPMINT}, "burnPercent": 100.0}]}
        return 404, None

    def post(self, url, payload, timeout=6.0):
        m, p = payload["method"], payload["params"]
        self.calls.append(("RPC", m))
        if not self.rpc_up:
            return 503, None
        ok = lambda r: (200, {"result": r})
        if m == "getAccountInfo":
            return ok({"value": {"owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                                 "data": {"parsed": {"type": "mint", "info": {
                                     "mintAuthority": self.mint_auth, "freezeAuthority": self.freeze_auth,
                                     "decimals": 6}}}}})
        if m == "getTokenSupply":
            return ok({"value": {"amount": str(self.supply if p[0] == MINT else 1000)}})
        if m == "getTokenLargestAccounts":
            if p[0] == MINT:
                return ok({"value": [{"address": a, "amount": str(b)} for a, b in self.balances.items()]})
            return ok({"value": [{"address": ACCT[0], "amount": "1000"}]})   # LP mint: one account
        if m == "getMultipleAccounts":
            vals = []
            for a in p[0]:
                owner = OTHER if (a == ACCT[0] and self.lp_owner_burn and p[0] == [ACCT[0]]) else self.owners.get(a)
                vals.append({"data": {"parsed": {"info": {"owner": owner}}}})
            return ok({"value": vals})
        if m == "getSignaturesForAddress":
            if p[0] == MINT:
                before = p[1].get("before")
                if before is None:
                    return ok(self.sigs_pages[0])
                idx = next(i for i, pg in enumerate(self.sigs_pages) if pg and pg[-1]["signature"] == before)
                return ok(self.sigs_pages[idx + 1])
            return ok([{"signature": "x"}] * 37)                     # creator history
        if m == "getTransaction":
            return ok({"transaction": {"message": {"accountKeys": [self.creator, "other"]}}})
        return 200, {"error": {"message": "nope"}}


fake = Fake()
pe._http_get = fake.get
pe._http_post = fake.post


def fresh():
    fake.reset()
    pe._CACHE._d.clear()
    pe.LIMITER._h.clear()
    pe.GLOBAL_LIMITER._h.clear()


def test_valid_mint():
    assert pe.valid_mint(MINT)
    assert pe.valid_mint(POOL)
    assert not pe.valid_mint("")
    assert not pe.valid_mint("abc")
    assert not pe.valid_mint(MINT + "0")                       # 0 is not base58
    assert not pe.valid_mint("98vd3CovpBmHJGN2z9rSiZRxM8QBvcc9Gnvq1RdJnpump")  # 45 chars (old site example)
    assert not pe.valid_mint("../../etc/passwd" + "1" * 30)
    assert not pe.valid_mint("1" * 33)                         # right charset, wrong byte length
    assert not pe.valid_mint(None)


def test_invalid_never_touches_network():
    fresh()
    r = pe.analyze("not-a-mint&x=1")
    assert r["status"] == "invalid" and r["action"] == "review"
    assert fake.calls == []


def test_healthy_token_passes_and_pool_is_excluded():
    fresh()
    r = pe.analyze(MINT)
    assert r["status"] == "ok", r
    h = r["holders"]
    assert h["pool_pct"] == 70.0                      # POOL 60% + Raydium authority 10%
    assert h["top1_pct"] == 2.0                       # whale holds 2% of supply, not 60%
    assert r["lp_lock"]["status"] == "burned"
    assert r["dev"]["creator"] == CREATOR
    assert r["dev"]["tx_count"] == 37
    assert r["verdict"] == "ok" and r["action"] == "pass" and r["confidence"] == "high"
    assert "whale_50pct" not in r["flags"]


def test_dev_holds_resolves_via_owner_wallet():
    fresh()
    fake.owners[ACCT[1]] = CREATOR                    # the "whale" account is actually owned by the dev
    fake.balances[ACCT[1]] = 150                      # 15%
    r = pe.analyze(MINT)
    assert r["dev"]["dev_holds_pct"] == 15.0
    assert "dev_holds_medium" in r["flags"]


def test_creator_is_oldest_not_newest():
    fresh()
    page1 = [{"signature": "S%04d" % i} for i in range(1000)]
    page2 = [{"signature": "T%04d" % i} for i in range(300)]
    fake.sigs_pages = [page1, page2]
    fake.creator = CREATOR
    r = pe.analyze(MINT)
    assert r["dev"]["trace"] == "oldest_tx"
    txcalls = [c for c in fake.calls if c == ("RPC", "getTransaction")]
    assert len(txcalls) == 1


def test_busy_token_creator_unknown_not_guessed():
    fresh()
    fake.sigs_pages = [[{"signature": "A%d_%04d" % (p, i)} for i in range(1000)] for p in range(6)]
    r = pe.analyze(MINT)
    assert r["dev"]["available"] is False and r["dev"]["trace"] == "too_busy"
    assert "dev_unknown" in r["flags"]


def test_rpc_down_is_unverified_not_a_fake_score():
    fresh()
    fake.rpc_up = False
    r = pe.analyze(MINT)
    assert r["verdict"] == "unverified" and r["label"] == "UNVERIFIED" and r["grade"] == "?"
    assert r["action"] == "review"
    assert set(r["data_quality"]["missing"]) >= {"holders", "authority"}


def test_no_rpc_configured():
    fresh()
    old = os.environ.pop("SOLANA_RPC_URL")
    try:
        r = pe.analyze(MINT)
        assert r["verdict"] == "unverified" and r["data_quality"]["rpc_configured"] is False
    finally:
        os.environ["SOLANA_RPC_URL"] = old


def test_dexscreener_429_is_source_error_not_not_found():
    fresh()
    fake.dex_status = 429
    r = pe.analyze(MINT)
    assert r["status"] == "source_error" and r["verdict"] == "unverified"


def test_stale_served_when_upstream_fails():
    fresh()
    good = pe.analyze(MINT)
    assert good["status"] == "ok"
    # age the cache entry past FRESH but inside STALE
    ts, ttl, val = pe._CACHE._d[MINT]
    pe._CACHE._d[MINT] = (ts - 200, ttl, val)
    fake.dex_status = 503
    r = pe.analyze(MINT)
    assert r.get("stale") is True and r["verdict"] == "ok"


def test_not_found():
    fresh()
    fake.pairs = []
    r = pe.analyze(MINT)
    assert r["status"] == "not_found" and r["action"] == "skip"


def test_cache_hit_makes_no_new_calls():
    fresh()
    pe.analyze(MINT)
    n = len(fake.calls)
    r = pe.analyze(MINT)
    assert r["cached"] is True and len(fake.calls) == n


def test_unknown_age_is_penalised():
    fresh()
    fake.pairs[0]["pairCreatedAt"] = None
    r = pe.analyze(MINT)
    assert "age_unknown" in r["flags"] and r["age_h"] is None
    assert r["risks"]["sniper"] == "unknown"


def test_lp_single_wallet_is_not_called_locked():
    fresh()
    fake.lp_owner_burn = False
    fake.owners[ACCT[0]] = CREATOR                    # one wallet holds the LP
    import pro_engine as m
    orig = m._raydium_lp_mint
    m._raydium_lp_mint = lambda pa, mint: (LPMINT, 0.0)   # Raydium says nothing burned
    try:
        r = pe.analyze(MINT)
    finally:
        m._raydium_lp_mint = orig
    assert r["lp_lock"]["status"] == "single_wallet"
    assert "lp_single_wallet" in r["flags"] and r["verdict"] != "ok"


def test_pumpfun_bonding_curve_has_no_lp_risk():
    fresh()
    fake.pairs = [Fake.pair(dex="pumpfun", liq=30000, age_h=2)]
    r = pe.analyze(MINT)
    assert r["lp_lock"]["status"] == "bonding_curve"
    assert "lp_unknown" not in r["flags"] and "lp_not_locked" not in r["flags"]


def test_unsupported_dex_is_marked_unverified():
    fresh()
    fake.pairs = [Fake.pair(dex="meteora")]
    r = pe.analyze(MINT)
    assert r["lp_lock"]["status"] == "unverified" and "lp_unverified_dex" in r["flags"]


def test_low_liquidity_forces_avoid():
    fresh()
    fake.pairs = [Fake.pair(liq=500)]
    r = pe.analyze(MINT)
    assert r["verdict"] == "avoid" and r["action"] == "skip"


def test_freeze_and_mint_active_cannot_pass():
    fresh()
    fake.mint_auth = CREATOR
    fake.freeze_auth = CREATOR
    r = pe.analyze(MINT)
    assert r["verdict"] != "ok"


def test_batch_parallel_and_dedupe():
    fresh()
    out = pe.analyze_many([MINT, "bad", MINT])
    assert [o["status"] for o in out] == ["ok", "invalid", "ok"]


def test_rate_limiter():
    rl = pe.RateLimiter(5)
    assert all(rl.allow("a")[0] for _ in range(5))
    ok, retry = rl.allow("a")
    assert not ok and 1 <= retry <= 61
    assert rl.allow("b")[0]
    ok, _ = rl.allow("c", cost=6)
    assert not ok


def test_cache_is_bounded():
    c = pe.TTLCache(10)
    for i in range(100):
        c.put(i, i, 60)
    assert len(c) == 10 and c.get(99) is not None and c.get(0) is None


def test_rpc_url_never_logged(caplog=None):
    import logging
    records = []

    class H(logging.Handler):
        def emit(self, r):
            records.append(r.getMessage())
    h = H()
    pe.log.addHandler(h)
    pe.log.setLevel(logging.DEBUG)
    fresh()
    fake.rpc_up = False
    pe.analyze(MINT)
    pe.log.removeHandler(h)
    assert not any("SECRET" in m or "fake-rpc" in m for m in records)


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    bad = 0
    for n, f in tests:
        try:
            f()
            print("PASS", n)
        except Exception as e:  # noqa: BLE001
            bad += 1
            import traceback
            print("FAIL", n, "->", repr(e))
            traceback.print_exc()
    print("\n%d/%d passed" % (len(tests) - bad, len(tests)))
    sys.exit(1 if bad else 0)

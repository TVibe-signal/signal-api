"""pro_engine.py - TVibe PRO v45 scoring engine.

Framework-free (no FastAPI import) so it can be unit-tested offline.
Replaces the inline PRO V43 engine in app.py. Fixes:

  * mint validation (base58 + 32 bytes) before anything touches a URL / RPC
  * token ACCOUNT -> OWNER wallet resolution (getMultipleAccounts), so
    dev_holds_pct and LP-burn checks actually work and pool vaults / bonding
    curves are excluded from "top holder" numbers
  * creator = fee payer of the OLDEST signature (paged), not the newest one
  * LP: only a real burn counts as safe; one wallet holding the LP is NOT "locked"
  * unknown age / unknown data adds risk; no data at all -> "unverified"
  * parallel RPC chains, bounded thread pools, LRU+TTL cache with single-flight,
    stale-on-error, per-IP + global rate limit
  * no bare `except:`; failures are logged (never the RPC url / key)
"""
from __future__ import annotations

import copy
import logging
import os
import random
import re
import threading
import time
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor

import requests

VERSION = "v45"
log = logging.getLogger("tvibe.pro")

# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


FRESH_S = _env_int("PRO_CACHE_FRESH_S", 90)          # serve from cache without re-fetching
STALE_S = _env_int("PRO_CACHE_STALE_S", 900)         # serve stale only if upstream fails
CACHE_MAX = _env_int("PRO_CACHE_MAX", 1500)
RATE_PER_MIN = _env_int("PRO_RATE_PER_MIN", 30)      # per IP (batch costs 1 per mint)
GLOBAL_PER_MIN = _env_int("PRO_GLOBAL_PER_MIN", 300)  # all callers together
RPC_CONCURRENCY = _env_int("PRO_RPC_CONCURRENCY", 6)
CREATOR_MAX_PAGES = _env_int("PRO_CREATOR_MAX_PAGES", 4)  # x1000 signatures

_RPC_ENV_NAMES = (
    "SOLANA_RPC_URL", "HELIUS_URL", "HELIUS_RPC_URL",
    "PRIVATE_RPC", "PRIVATE_RPC_URL", "RPC_URL",
)
_rpc_resolver = None  # optional callable() -> str, set by the loader


def set_rpc_resolver(fn) -> None:
    """Loader may pass a callable that returns an RPC url (e.g. from core globals)."""
    global _rpc_resolver
    _rpc_resolver = fn


def rpc_url() -> str:
    for n in _RPC_ENV_NAMES:
        v = (os.getenv(n) or "").strip()
        if v.startswith("http"):
            return v
    if _rpc_resolver is not None:
        try:
            v = (_rpc_resolver() or "").strip()
            if v.startswith("http"):
                return v
        except Exception as e:  # resolver is third-party code
            log.warning("rpc resolver failed: %s", type(e).__name__)
    return ""


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_B58_IDX = {c: i for i, c in enumerate(_B58)}
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def _b58_len(s: str) -> int:
    n = 0
    for ch in s:
        n = n * 58 + _B58_IDX[ch]
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return pad + len(body)


def valid_mint(m) -> bool:
    """True only for a syntactically valid 32-byte Solana public key."""
    if not isinstance(m, str) or not MINT_RE.match(m):
        return False
    try:
        return _b58_len(m) == 32
    except KeyError:
        return False


# --------------------------------------------------------------------------
# cache (LRU + TTL) with single-flight, and rate limiter
# --------------------------------------------------------------------------
class TTLCache:
    def __init__(self, max_items: int = 1500):
        self._d: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self.max = max_items

    def put(self, key, val, ttl: float):
        with self._lock:
            self._d[key] = (time.time(), ttl, val)
            self._d.move_to_end(key)
            while len(self._d) > self.max:
                self._d.popitem(last=False)

    def get(self, key, allow_stale_s: float = 0.0):
        """-> (val, age_s, is_fresh) or None."""
        now = time.time()
        with self._lock:
            it = self._d.get(key)
            if not it:
                return None
            ts, ttl, val = it
            age = now - ts
            if age <= ttl:
                self._d.move_to_end(key)
                return val, age, True
            if age <= ttl + allow_stale_s:
                return val, age, False
            return None

    def __len__(self):
        with self._lock:
            return len(self._d)


class RateLimiter:
    def __init__(self, per_min: int, window: float = 60.0, max_keys: int = 20000):
        self.per = per_min
        self.win = window
        self.max_keys = max_keys
        self._h: dict = {}
        self._lock = threading.Lock()
        self._gc_at = 0.0

    def allow(self, key: str, cost: int = 1):
        """-> (allowed, retry_after_s)."""
        now = time.time()
        with self._lock:
            dq = self._h.get(key)
            if dq is None:
                dq = self._h[key] = deque()
            while dq and now - dq[0][0] > self.win:
                dq.popleft()
            used = sum(c for _, c in dq)
            if used + cost > self.per:
                retry = int(self.win - (now - dq[0][0])) + 1 if dq else 1
                return False, max(1, retry)
            dq.append((now, cost))
            if now - self._gc_at > 120 or len(self._h) > self.max_keys:
                self._gc_at = now
                for k in [k for k, v in self._h.items() if not v or now - v[-1][0] > self.win]:
                    self._h.pop(k, None)
        return True, 0


LIMITER = RateLimiter(RATE_PER_MIN)
GLOBAL_LIMITER = RateLimiter(GLOBAL_PER_MIN)


def allow_request(ip: str, cost: int = 1):
    """Per-IP then global limit. -> (allowed, retry_after_s, scope)."""
    ok, retry = LIMITER.allow("ip:" + (ip or "?"), cost)
    if not ok:
        return False, retry, "ip"
    ok, retry = GLOBAL_LIMITER.allow("*", cost)
    if not ok:
        return False, retry, "global"
    return True, 0, ""


def client_ip(request) -> str:
    """Best-effort client IP behind Render / Cloudflare."""
    try:
        h = request.headers
        for name in ("cf-connecting-ip", "true-client-ip"):
            v = (h.get(name) or "").strip()
            if v:
                return v[:64]
        xff = (h.get("x-forwarded-for") or "").strip()
        if xff:
            return xff.split(",")[-1].strip()[:64]
        return (request.client.host if request.client else "?")[:64]
    except Exception:
        return "?"


_CACHE = TTLCache(CACHE_MAX)
_inflight: dict = {}
_inflight_lock = threading.Lock()
_IO = ThreadPoolExecutor(max_workers=12, thread_name_prefix="pro-io")
_JOBS = ThreadPoolExecutor(max_workers=6, thread_name_prefix="pro-job")
_RPC_SEM = threading.BoundedSemaphore(RPC_CONCURRENCY)
_tls = threading.local()
_FAIL = object()


# --------------------------------------------------------------------------
# HTTP / RPC helpers
# --------------------------------------------------------------------------
def _sess() -> requests.Session:
    s = getattr(_tls, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": "TVibe-PRO/" + VERSION, "Accept": "application/json"})
        _tls.s = s
    return s


def _http_get(url: str, timeout: float = 6.0, headers=None):
    """GET json with one retry on 429/5xx/timeouts. -> (status, json|None)."""
    last = 0
    for attempt in (0, 1):
        try:
            r = _sess().get(url, timeout=timeout, headers=headers)
            last = r.status_code
            if r.status_code == 200:
                try:
                    return 200, r.json()
                except ValueError:
                    return 200, None
            if r.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(0.35 + random.random() * 0.35)
                continue
            return r.status_code, None
        except requests.RequestException as e:
            log.info("http get failed: %s", type(e).__name__)
            last = 0
            if attempt == 0:
                time.sleep(0.2)
    return last, None


def _http_post(url: str, payload: dict, timeout: float = 6.0):
    """POST json, same retry policy. -> (status, json|None)."""
    last = 0
    for attempt in (0, 1):
        try:
            with _RPC_SEM:
                r = _sess().post(url, json=payload, timeout=timeout)
            last = r.status_code
            if r.status_code == 200:
                try:
                    return 200, r.json()
                except ValueError:
                    return 200, None
            if r.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                time.sleep(0.3 + random.random() * 0.3)
                continue
            return r.status_code, None
        except requests.RequestException as e:
            log.info("rpc post failed: %s", type(e).__name__)  # never log the url (api key)
            last = 0
            if attempt == 0:
                time.sleep(0.2)
    return last, None


def _rpc(method: str, params: list, timeout: float = 6.0):
    """JSON-RPC call. Returns result, or _FAIL when unavailable / errored."""
    url = rpc_url()
    if not url:
        return _FAIL
    st, j = _http_post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout)
    if st != 200 or not isinstance(j, dict) or j.get("error"):
        return _FAIL
    return j.get("result")


# --------------------------------------------------------------------------
# market data (DexScreener, GeckoTerminal fallback)
# --------------------------------------------------------------------------
SOL_MINT = "So11111111111111111111111111111111111111112"


def _f(x, default=0.0) -> float:
    try:
        v = float(x)
        return v if v == v and v not in (float("inf"), float("-inf")) else default
    except (TypeError, ValueError):
        return default


def _pick_pair(pairs: list, mint: str):
    sol = [p for p in pairs if isinstance(p, dict) and p.get("chainId") == "solana"]
    base = [p for p in sol if ((p.get("baseToken") or {}).get("address") == mint)]
    pool = base or sol
    if not pool:
        return None, 0, False
    best = max(pool, key=lambda p: _f((p.get("liquidity") or {}).get("usd")))
    return best, len(pool), not base  # mint_is_quote


def fetch_market(mint: str):
    """-> (pair|None, info). info = {status, source, pairs_count, mint_is_quote}."""
    st, j = _http_get("https://api.dexscreener.com/latest/dex/tokens/" + mint, timeout=6.0)
    if st == 200 and isinstance(j, dict):
        pairs = j.get("pairs") or []
        pair, n, quote = _pick_pair(pairs, mint)
        if pair is not None:
            return pair, {"status": "ok", "source": "dexscreener", "pairs_count": n, "mint_is_quote": quote}
        # DexScreener answered but knows nothing -> maybe GeckoTerminal does
    # fallback
    gst, gj = _http_get(
        "https://api.geckoterminal.com/api/v2/networks/solana/tokens/" + mint,
        timeout=6.0, headers={"Accept": "application/json;version=20230302"},
    )
    if gst == 200 and isinstance(gj, dict):
        try:
            attr = (gj.get("data") or {}).get("attributes") or {}
            liq = _f(attr.get("total_reserve_in_usd"))
            if attr and (attr.get("price_usd") or liq):
                pool_id = ""
                try:
                    pool_id = (((gj["data"]["relationships"]["top_pools"]["data"]) or [{}])[0].get("id") or "")
                except (KeyError, IndexError, TypeError):
                    pool_id = ""
                pool_addr = pool_id.split("_", 1)[1] if pool_id.startswith("solana_") else None
                pair = {
                    "chainId": "solana", "dexId": None, "pairAddress": pool_addr,
                    "baseToken": {"address": mint, "symbol": attr.get("symbol"), "name": attr.get("name")},
                    "priceUsd": attr.get("price_usd"),
                    "liquidity": {"usd": liq},
                    "volume": {"h24": _f((attr.get("volume_usd") or {}).get("h24"))},
                    "priceChange": {}, "pairCreatedAt": None,
                }
                return pair, {"status": "ok", "source": "geckoterminal", "pairs_count": 1, "mint_is_quote": False}
        except (KeyError, TypeError, ValueError) as e:
            log.info("geckoterminal parse failed: %s", type(e).__name__)
    if st == 200:
        return None, {"status": "not_found", "source": "dexscreener", "pairs_count": 0, "mint_is_quote": False}
    return None, {"status": "source_error", "source": "dexscreener", "pairs_count": 0, "mint_is_quote": False,
                  "http": st}


# --------------------------------------------------------------------------
# on-chain data
# --------------------------------------------------------------------------
BURN_OWNERS = {
    "1nc1nerator11111111111111111111111111111111",
    "11111111111111111111111111111111",
    "deaddeaddeaddeaddeaddeaddeaddeaddeaddeaddead",
}
# Raydium pool-authority PDAs that own the vault token accounts
KNOWN_POOL_OWNERS = {
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",  # Raydium AMM v4 authority
    "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL",  # Raydium CPMM authority
}
RISKY_EXT = {
    "permanentDelegate": ("permanent_delegate", 14),
    "transferHook": ("transfer_hook", 6),
    "transferFeeConfig": ("transfer_fee", 4),
    "defaultAccountState": ("default_account_state", 6),
    "nonTransferable": ("non_transferable", 14),
}


def _owners_of(token_accounts: list):
    """token account addresses -> list of owner wallet|None, or _FAIL."""
    if not token_accounts:
        return []
    res = _rpc("getMultipleAccounts", [token_accounts, {"encoding": "jsonParsed", "commitment": "confirmed"}])
    if res is _FAIL or not isinstance(res, dict):
        return _FAIL
    vals = res.get("value")
    if not isinstance(vals, list) or len(vals) != len(token_accounts):
        return _FAIL
    out = []
    for v in vals:
        try:
            out.append(v["data"]["parsed"]["info"]["owner"])
        except (KeyError, TypeError):
            out.append(None)
    return out


def _holder_table(mint: str, extra_pool_owners=()):
    """Return (rows, supply_raw) with rows=[{owner, raw}] aggregated by OWNER, or _FAIL."""
    sr = _rpc("getTokenSupply", [mint])
    lr = _rpc("getTokenLargestAccounts", [mint, {"commitment": "confirmed"}])
    if sr is _FAIL or lr is _FAIL or not isinstance(sr, dict) or not isinstance(lr, dict):
        return _FAIL, 0
    try:
        supply = int((sr.get("value") or {}).get("amount") or 0)
    except (TypeError, ValueError):
        return _FAIL, 0
    vals = lr.get("value") or []
    if supply <= 0 or not isinstance(vals, list) or not vals:
        return _FAIL, 0
    accts = [v.get("address") for v in vals[:20] if isinstance(v, dict) and v.get("address")]
    owners = _owners_of(accts)
    if owners is _FAIL:
        return _FAIL, 0
    agg: dict = {}
    for v, owner in zip(vals[:20], owners):
        try:
            raw = int(v.get("amount") or 0)
        except (TypeError, ValueError):
            continue
        key = owner or ("acct:" + str(v.get("address")))
        agg[key] = agg.get(key, 0) + raw
    rows = sorted(({"owner": k, "raw": r} for k, r in agg.items()), key=lambda x: -x["raw"])
    return rows, supply


def task_holders(mint: str, pair_address):
    out = {"available": False, "top1_pct": None, "top10_pct": None, "top_holders": [],
           "concentration": "unknown", "pool_pct": None, "burned_pct": None,
           "note": "Holder data unavailable."}
    rows, supply = _holder_table(mint)
    if rows is _FAIL:
        return out, {}
    pool_owners = set(KNOWN_POOL_OWNERS)
    if pair_address:
        pool_owners.add(pair_address)
    pool = burn = 0.0
    real = []
    wallet_pct = {}
    for r in rows:
        pct = r["raw"] / supply * 100.0
        if r["owner"] in BURN_OWNERS:
            burn += pct
        elif r["owner"] in pool_owners:
            pool += pct
        else:
            real.append({"address": r["owner"], "pct": round(pct, 2)})
        wallet_pct[r["owner"]] = pct
    real = real[:10]
    t1 = real[0]["pct"] if real else 0.0
    t10 = round(sum(h["pct"] for h in real), 2)
    conc = ("very_high" if t1 > 50 else "high" if (t1 > 30 or t10 > 70)
            else "medium" if t10 > 50 else "low")
    out.update({
        "available": True, "top1_pct": round(t1, 2), "top10_pct": t10, "top_holders": real,
        "concentration": conc, "pool_pct": round(pool, 2), "burned_pct": round(burn, 2),
        "supply_raw": str(supply),
        "note": "Top wallet %.1f%%, top 10 wallets %.1f%% (pool/curve %.1f%% and burned %.1f%% excluded)."
                % (t1, t10, pool, burn),
    })
    return out, wallet_pct


def task_authority(mint: str):
    out = {"available": False, "exists": None, "mint_authority": None, "freeze_authority": None,
           "renounced": None, "token_program": None, "extensions": []}
    res = _rpc("getAccountInfo", [mint, {"encoding": "jsonParsed", "commitment": "confirmed"}])
    if res is _FAIL or not isinstance(res, dict):
        return out
    val = res.get("value")
    if val is None:
        out.update({"available": True, "exists": False})
        return out
    try:
        parsed = val["data"]["parsed"]
        info = parsed["info"]
        if parsed.get("type") != "mint":
            out.update({"available": True, "exists": False})
            return out
    except (KeyError, TypeError):
        return out
    prog = "token-2022" if (val.get("owner") or "").startswith("TokenzQd") else "spl-token"
    exts = []
    for e in (info.get("extensions") or []):
        name = e.get("extension") if isinstance(e, dict) else None
        if name:
            exts.append(name)
    out.update({
        "available": True, "exists": True,
        "mint_authority": info.get("mintAuthority"), "freeze_authority": info.get("freezeAuthority"),
        "renounced": info.get("mintAuthority") is None and info.get("freezeAuthority") is None,
        "token_program": prog, "extensions": exts, "decimals": info.get("decimals"),
    })
    return out


def task_creator(mint: str):
    """Creator = fee payer of the OLDEST transaction touching the mint."""
    out = {"available": False, "creator": None, "creator_short": None, "tx_count": None,
           "dev_holds_pct": None, "trace": "rpc_failed"}
    before = None
    oldest = None
    for _ in range(CREATOR_MAX_PAGES):
        opts = {"limit": 1000, "commitment": "confirmed"}
        if before:
            opts["before"] = before
        page = _rpc("getSignaturesForAddress", [mint, opts], timeout=8.0)
        if page is _FAIL or not isinstance(page, list):
            return out
        if not page:
            break
        if len(page) < 1000:
            oldest = page[-1]
            break
        before = page[-1].get("signature")
    else:
        out["trace"] = "too_busy"   # >CREATOR_MAX_PAGES*1000 signatures: not traceable cheaply
        return out
    sig = (oldest or {}).get("signature") if isinstance(oldest, dict) else None
    if not sig:
        out["trace"] = "no_history"
        return out
    tx = _rpc("getTransaction", [sig, {"encoding": "json", "maxSupportedTransactionVersion": 0,
                                       "commitment": "confirmed"}], timeout=8.0)
    if tx is _FAIL or not isinstance(tx, dict):
        return out
    creator = None
    try:
        keys = tx["transaction"]["message"]["accountKeys"]
        k0 = keys[0]
        creator = k0.get("pubkey") if isinstance(k0, dict) else k0
    except (KeyError, IndexError, TypeError):
        creator = None
    if not (isinstance(creator, str) and valid_mint(creator)):
        return out
    hist = _rpc("getSignaturesForAddress", [creator, {"limit": 50}], timeout=6.0)
    txc = len(hist) if isinstance(hist, list) else None
    out.update({"available": True, "creator": creator,
                "creator_short": creator[:6] + "..." + creator[-4:], "tx_count": txc, "trace": "oldest_tx"})
    return out


def _raydium_lp_mint(pair_address, mint):
    """-> (lp_mint|None, burn_percent|None). Handles lpMint as str or {address}."""
    urls = []
    if pair_address and valid_mint(pair_address):
        urls.append("https://api-v3.raydium.io/pools/info/ids?ids=" + pair_address)
    urls.append("https://api-v3.raydium.io/pools/info/mint?mint1=" + mint + "&mint2=" + SOL_MINT +
                "&poolType=all&poolSortField=default&sortType=desc&pageSize=1&page=1")
    for u in urls:
        st, j = _http_get(u, timeout=5.0)
        if st != 200 or not isinstance(j, dict):
            continue
        data = j.get("data")
        pools = data.get("data") if isinstance(data, dict) else data
        if not isinstance(pools, list) or not pools or not isinstance(pools[0], dict):
            continue
        p = pools[0]
        lm = p.get("lpMint")
        addr = lm.get("address") if isinstance(lm, dict) else lm
        if isinstance(addr, str) and valid_mint(addr):
            bp = p.get("burnPercent")
            return addr, (_f(bp, None) if bp is not None else None)
    return None, None


def task_lp(pair: dict, mint: str):
    dex = (pair.get("dexId") or "").lower() or None
    out = {"available": False, "status": "unknown", "pct_locked": None, "lp_mint": None, "dex": dex,
           "note": "LP lock not verified. Assume LP can be pulled."}
    if dex == "pumpfun":
        out.update({"available": True, "status": "bonding_curve",
                    "note": "Still on the pump.fun bonding curve: there is no LP to pull."})
        return out
    if dex != "raydium":
        out.update({"status": "unverified",
                    "note": "LP lock check not supported for %s yet. Assume LP can be pulled." % (dex or "this DEX")})
        return out
    lp_mint, burn_pct = _raydium_lp_mint(pair.get("pairAddress"), mint)
    if not lp_mint:
        return out
    out["lp_mint"] = lp_mint
    lp_burn = burn_pct
    top_other = None
    rows, supply = _holder_table(lp_mint)
    if rows is not _FAIL:
        burn = sum(r["raw"] for r in rows if r["owner"] in BURN_OWNERS) / supply * 100.0
        others = [r for r in rows if r["owner"] not in BURN_OWNERS]
        top_other = (others[0]["raw"] / supply * 100.0) if others else 0.0
        lp_burn = max(burn, lp_burn or 0.0)
    if lp_burn is None and top_other is None:
        return out
    out["available"] = True
    out["pct_locked"] = round(lp_burn or 0.0, 1)  # kept key name; only BURNED LP is counted
    if (lp_burn or 0) >= 90:
        out.update({"status": "burned", "note": "LP burned %.1f%%. Liquidity cannot be pulled." % lp_burn})
    elif (lp_burn or 0) >= 50:
        out.update({"status": "partial", "note": "LP only %.1f%% burned. The rest can still be pulled." % lp_burn})
    elif top_other is not None and top_other >= 50:
        out.update({"status": "single_wallet",
                    "note": "One wallet holds %.1f%% of the LP. Not burned - it can pull unless a locker holds it "
                            "(locker contracts are not verified)." % top_other})
    else:
        out.update({"status": "unlocked", "note": "LP is not burned and is spread over wallets. Can be pulled."})
    return out


# --------------------------------------------------------------------------
# scoring (pure function)
# --------------------------------------------------------------------------
def score(pair: dict, h: dict, a: dict, d: dict, lp: dict, now: float | None = None) -> dict:
    now = now or time.time()
    liq = _f((pair.get("liquidity") or {}).get("usd"))
    vol = _f((pair.get("volume") or {}).get("h24"))
    ch = _f((pair.get("priceChange") or {}).get("h24"))
    age_h = None
    pc = pair.get("pairCreatedAt")
    if pc:
        ms = _f(pc, None)
        if ms and ms > 0:
            age_h = max(0.0, (now - ms / 1000.0) / 3600.0)

    # ---- market (cap 32)
    mkt, mf = 0, []
    if liq < 1000: mkt += 25; mf.append("low_liquidity")
    elif liq < 5000: mkt += 18; mf.append("thin_liquidity")
    elif liq < 15000: mkt += 10; mf.append("thin_liquidity")
    elif liq < 30000: mkt += 5; mf.append("low_liq_vs_vol")
    elif liq < 50000: mkt += 2
    if ch <= -50: mkt += 20; mf.append("dump_50pct")
    elif ch <= -30: mkt += 12; mf.append("dump_30pct")
    elif ch <= -15: mkt += 7; mf.append("dump_15pct")
    if age_h is None: mkt += 8; mf.append("age_unknown")
    elif age_h < 1: mkt += 15; mf.append("very_new")
    elif age_h < 6: mkt += 12; mf.append("very_new")
    elif age_h < 24: mkt += 8; mf.append("new_token")
    elif age_h < 72: mkt += 5; mf.append("new_token")
    elif age_h < 168: mkt += 2
    ratio = (vol / liq) if liq > 0 else 0
    if ratio > 30: mkt += 6; mf.append("vol_liq_wash")
    elif ratio > 15: mkt += 5; mf.append("vol_liq_high")
    elif ratio > 8: mkt += 4; mf.append("vol_liq_high")
    elif ratio > 4: mkt += 2
    mkt = min(mkt, 32)

    # ---- holders (cap 28) - pool/curve/burn already excluded
    hold, hf = 0, []
    t1 = t10 = 0.0
    if h.get("available"):
        t1 = h.get("top1_pct") or 0.0
        t10 = h.get("top10_pct") or 0.0
        if t1 > 50: hold += 25; hf.append("whale_50pct")
        elif t1 > 30: hold += 18; hf.append("high_concentration")
        elif t1 > 20: hold += 12; hf.append("high_concentration")
        elif t1 > 15: hold += 6; hf.append("top1_15pct")
        elif t1 > 10: hold += 3
        if t10 > 70: hold += 15; hf.append("top10_70pct")
        elif t10 > 60: hold += 12; hf.append("top10_60pct")
        elif t10 > 50: hold += 8; hf.append("top10_50pct")
        elif t10 > 40: hold += 5; hf.append("top10_40pct")
        elif t10 > 35: hold += 3
    else:
        hold += 8; hf.append("holders_unknown")
    hold = min(hold, 28)

    # ---- LP (cap 25)
    lps, lf = 0, []
    st = lp.get("status")
    if st in ("burned", "bonding_curve"): lf.append("lp_locked" if st == "burned" else "bonding_curve")
    elif st == "partial": lps += 12; lf.append("lp_partial")
    elif st == "single_wallet": lps += 20; lf.append("lp_single_wallet")
    elif st == "unlocked": lps += 25; lf.append("lp_not_locked")
    elif st == "unverified": lps += 18; lf.append("lp_unverified_dex")
    else: lps += 18; lf.append("lp_unknown")

    # ---- dev (cap 23)
    dev, df = 0, []
    if d.get("available"):
        dh = d.get("dev_holds_pct")
        if dh is None: dev += 8; df.append("dev_holds_unknown")
        elif dh > 20: dev += 15; df.append("dev_holds_large")
        elif dh > 10: dev += 8; df.append("dev_holds_medium")
        elif dh > 5: dev += 4; df.append("dev_holds_small")
        txc = d.get("tx_count")
        if txc is not None:
            if txc < 5: dev += 8; df.append("new_dev")
            elif txc < 20: dev += 3; df.append("new_dev")
    else:
        dev += 12; df.append("dev_unknown")
    dev = min(dev, 23)

    # ---- authority / token-2022 extensions (cap 26)
    auth, af = 0, []
    if a.get("available") and a.get("exists") is not False:
        if a.get("mint_authority") is not None: auth += 8; af.append("mint_active")
        if a.get("freeze_authority") is not None: auth += 10; af.append("freeze_active")
        if a.get("renounced"): af.append("authorities_renounced")
        for ext in a.get("extensions") or []:
            if ext in RISKY_EXT:
                flag, pts = RISKY_EXT[ext]
                auth += pts; af.append(flag)
    else:
        auth += 8; af.append("authority_unknown")
    auth = min(auth, 26)

    total = max(0, min(100, mkt + hold + lps + dev + auth))
    flags = mf + hf + lf + df + af

    # ---- grade
    if total <= 15: grade, verdict, label = "A", "ok", "PASS"
    elif total <= 30: grade, verdict, label = "B", "ok", "PASS"
    elif total <= 50: grade, verdict, label = "C", "caution", "HOLD-BUY"
    elif total <= 70: grade, verdict, label = "D", "avoid", "SELL"
    else: grade, verdict, label = "F", "avoid", "SELL"

    # ---- data quality & caps
    missing = []
    if not h.get("available"): missing.append("holders")
    if not (a.get("available") and a.get("exists") is not False): missing.append("authority")
    if not d.get("available"): missing.append("creator")
    if not lp.get("available") and lp.get("status") != "unverified": missing.append("lp")
    capped_by = None
    if "holders" in missing and "authority" in missing:
        grade, verdict, label = "?", "unverified", "UNVERIFIED"
        capped_by = "onchain_data_unavailable"
    else:
        if verdict == "ok" and ("holders" in missing or "authority" in missing):
            grade, verdict, label = "C", "caution", "HOLD-BUY"; capped_by = "missing_core_data"
        if liq < 1000 and verdict != "avoid":
            grade, verdict, label = "D", "avoid", "SELL"; capped_by = "liquidity_under_1k"
        if "permanent_delegate" in flags and verdict != "avoid":
            grade, verdict, label = "D", "avoid", "SELL"; capped_by = "permanent_delegate"
        if "mint_active" in flags and "freeze_active" in flags and verdict == "ok":
            grade, verdict, label = "C", "caution", "HOLD-BUY"; capped_by = "mint_and_freeze_active"
        if lp.get("status") in ("unknown", "unverified") and verdict == "ok":
            grade, verdict, label = "C", "caution", "HOLD-BUY"; capped_by = "lp_unverified"
        if "whale_50pct" in flags and verdict == "ok":
            grade, verdict, label = "C", "caution", "HOLD-BUY"; capped_by = "whale_50pct"
    if capped_by:
        flags.append("verdict_capped:" + capped_by)

    # ---- advanced risks
    dhv = d.get("dev_holds_pct") or 0
    bundle = "high" if (t1 > 30 and t10 > 60) else "medium" if (t10 > 40 or t1 > 15) else "low"
    if a.get("freeze_authority") is not None and lp.get("status") in ("unlocked", "single_wallet"): honey = "high"
    elif a.get("freeze_authority") is not None: honey = "medium"
    elif "lp_unknown" in lf and "authority_unknown" in af: honey = "medium"
    else: honey = "low"
    if age_h is None: sniper = "unknown"
    elif age_h < 6 and t1 > 15: sniper = "high"
    elif age_h < 24 and t1 > 15: sniper = "medium"
    elif age_h < 72 and t1 > 20: sniper = "medium"
    else: sniper = "low"
    _ = dhv

    # ---- plain-English reason
    if verdict == "unverified":
        why = "Could not verify on-chain data (holders / authorities). Treat as unknown - do not size."
    elif grade == "F":
        why = "Do not buy. Multiple risks + too many unknowns."
    elif capped_by == "permanent_delegate":
        why = "Do not buy. A permanent delegate can take tokens from any wallet."
    elif "whale_50pct" in hf:
        why = "Do not buy. One wallet holds 50%+."
    elif "lp_not_locked" in lf or "lp_single_wallet" in lf:
        why = "Do not buy. LP is not burned - it can be pulled."
    elif "lp_unknown" in lf and "dev_unknown" in df:
        why = "Do not buy. LP + Dev unknown, token very new."
    elif "vol_liq_wash" in mf:
        why = "Volume looks washed vs liquidity. Small size only."
    elif capped_by == "lp_unverified":
        why = "Not a clear yes: LP lock could not be verified, so liquidity might be pulled. Small size only."
    elif verdict == "caution":
        why = "Mixed. Small size only."
    elif verdict == "avoid":
        why = "Too risky on these checks."
    else:
        why = "Looks OK on these checks. PASS does not mean safe."

    n_missing = len(missing)
    confidence = "high" if n_missing == 0 else ("medium" if n_missing == 1 else "low")
    return {
        "age_h": None if age_h is None else round(age_h, 1),
        "risk_score": total, "grade": grade, "verdict": verdict, "label": label, "why": why,
        "action": {"ok": "pass", "caution": "review", "avoid": "skip"}.get(verdict, "review"),
        "breakdown": {"market": mkt, "holder": hold, "lp": lps, "dev": dev, "authority": auth},
        "flags": flags,
        "risks": {"bundle": bundle, "honeypot": honey, "sniper": sniper},
        "confidence": confidence, "missing": missing, "verdict_capped_by": capped_by,
        "liq": liq, "vol": vol, "ch": ch,
    }


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------
def _fail(mint, status, why, http=None):
    r = {"mint": mint, "status": status, "verdict": "avoid" if status == "not_found" else "unverified",
         "label": "SELL" if status == "not_found" else "UNVERIFIED",
         "grade": "F" if status == "not_found" else "?", "risk_score": 100 if status == "not_found" else None,
         "action": "skip" if status == "not_found" else "review", "why": why, "version": VERSION,
         "disclaimer": "PASS does not mean safe. Always check yourself."}
    if http is not None:
        r["upstream_http"] = http
    return r


def _compute(mint: str) -> dict:
    pair, info = fetch_market(mint)
    if pair is None:
        if info["status"] == "not_found":
            return _fail(mint, "not_found", "No trading pair found. Brand-new token, wrong mint, or no liquidity.")
        return _fail(mint, "source_error", "Market data source is busy right now. Try again in a minute.",
                     info.get("http"))
    pair_addr = pair.get("pairAddress")
    rpc_ok = bool(rpc_url())

    f_auth = _IO.submit(task_authority, mint)
    f_hold = _IO.submit(task_holders, mint, pair_addr)
    f_creator = _IO.submit(task_creator, mint)
    f_lp = _IO.submit(task_lp, pair, mint)

    def _res(fut, default, label):
        try:
            return fut.result(timeout=30)
        except Exception as e:  # task bug / timeout must not kill the whole report
            log.warning("task %s failed: %s", label, type(e).__name__)
            return default

    a = _res(f_auth, {"available": False}, "authority")
    hres = _res(f_hold, ({"available": False, "note": "Holder data unavailable."}, {}), "holders")
    h, wallet_pct = hres if isinstance(hres, tuple) else (hres, {})
    d = _res(f_creator, {"available": False, "trace": "rpc_failed"}, "creator")
    lp = _res(f_lp, {"available": False, "status": "unknown", "note": "LP lock not verified."}, "lp")

    if a.get("exists") is False:
        return _fail(mint, "not_found", "This address is not a token mint.")

    if d.get("available") and h.get("available"):
        d["dev_holds_pct"] = round(wallet_pct.get(d["creator"], 0.0), 2)

    sc = score(pair, h, a, d, lp)
    base = pair.get("baseToken") or {}
    status = "ok" if not sc["missing"] else ("unverified" if sc["verdict"] == "unverified" else "partial")
    return {
        "mint": mint, "status": status, "version": VERSION,
        "symbol": base.get("symbol") or "?", "name": base.get("name") or "",
        "price_usd": _f(pair.get("priceUsd")), "liquidity_usd": sc["liq"], "volume_24h": sc["vol"],
        "change_24h_pct": sc["ch"], "age_h": sc["age_h"], "pairAddress": pair_addr,
        "risk_score": sc["risk_score"], "grade": sc["grade"], "verdict": sc["verdict"], "label": sc["label"],
        "action": sc["action"], "why": sc["why"], "breakdown": sc["breakdown"], "flags": sc["flags"],
        "holders": h, "lp_lock": lp, "dev": d, "onchain": a, "risks": sc["risks"],
        "confidence": sc["confidence"], "verdict_capped_by": sc["verdict_capped_by"],
        "data_quality": {"missing": sc["missing"], "rpc_configured": rpc_ok, "market_source": info["source"],
                         "pairs_count": info["pairs_count"], "mint_is_quote": info["mint_is_quote"],
                         "creator_trace": d.get("trace")},
        "valid_for_s": 60,
        "disclaimer": "PASS does not mean safe. Always check yourself.",
    }


def _tag(res: dict, age: float, fresh: bool) -> dict:
    r = copy.deepcopy(res)
    r["cached"] = True
    r["cache_age_s"] = int(age)
    if not fresh:
        r["stale"] = True
    return r


def analyze(mint: str) -> dict:
    mint = (mint or "").strip()
    if not valid_mint(mint):
        return {"mint": mint[:60], "status": "invalid", "verdict": "unverified", "label": "UNVERIFIED",
                "grade": "?", "risk_score": None, "action": "review", "version": VERSION,
                "why": "Not a valid Solana token mint (expected a base58 address, 32-44 characters)."}
    hit = _CACHE.get(mint)
    if hit and hit[2]:
        return _tag(hit[0], hit[1], True)
    with _inflight_lock:
        ev = _inflight.get(mint)
        leader = ev is None
        if leader:
            ev = _inflight[mint] = threading.Event()
    if not leader:
        ev.wait(timeout=30)
        hit = _CACHE.get(mint)
        if hit and hit[2]:
            return _tag(hit[0], hit[1], True)
    try:
        res = _compute(mint)
    except Exception as e:  # last line of defence: never 500 the public endpoint
        log.exception("analyze crashed: %s", type(e).__name__)
        res = _fail(mint, "source_error", "Internal error while scoring. Try again.")
    finally:
        if leader:
            with _inflight_lock:
                _inflight.pop(mint, None)
            ev.set()
    st = res.get("status")
    if st in ("ok", "partial"):
        _CACHE.put(mint, res, FRESH_S)
    elif st == "not_found":
        _CACHE.put(mint, res, 30)
    elif st == "source_error":
        stale = _CACHE.get(mint, allow_stale_s=STALE_S)
        if stale:
            return _tag(stale[0], stale[1], False)
    return copy.deepcopy(res)


def analyze_many(mints: list) -> list:
    """Parallel analysis (order preserved). Duplicates are analysed once."""
    uniq = list(dict.fromkeys(m.strip() for m in mints))
    futs = {m: _JOBS.submit(analyze, m) for m in uniq}
    out = {}
    for m, f in futs.items():
        try:
            out[m] = f.result(timeout=60)
        except Exception as e:
            log.warning("batch item failed: %s", type(e).__name__)
            out[m] = _fail(m, "source_error", "Timed out. Try again.")
    return [copy.deepcopy(out[m.strip()]) for m in mints]


def agent_view(o: dict) -> dict:
    """Compact JSON for bots (/check)."""
    return {
        "mint": o.get("mint"), "action": o.get("action"), "verdict": o.get("verdict"),
        "label": o.get("label"), "grade": o.get("grade"), "risk_score": o.get("risk_score"),
        "symbol": o.get("symbol"), "price_usd": o.get("price_usd"), "liquidity_usd": o.get("liquidity_usd"),
        "flags": o.get("flags") or [], "confidence": o.get("confidence"), "why": o.get("why"),
        "status": o.get("status"), "valid_for_s": 60, "version": VERSION, "nfa": True,
    }


def status() -> dict:
    return {"pro_engine": VERSION, "rpc_configured": bool(rpc_url()), "cache_entries": len(_CACHE),
            "rate_per_ip_per_min": RATE_PER_MIN, "rate_global_per_min": GLOBAL_PER_MIN}

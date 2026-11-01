"""
TVibe Signal API — core.py
Core: app setup, basic signal pipeline, security, early heuristics
Loaded by main.py into shared namespace (same behavior as original multi-part).
Source: https://github.com/TVibe-signal/signal-api
"""

# --- part1 ---
import asyncio
import json
import math
import os
import re
import time
import threading
from collections import Counter, OrderedDict, deque
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

VERSION = "2.0.0"
DEX_URL = "https://api.dexscreener.com/latest/dex/tokens/{mint}"
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")  # base58

CACHE_TTL = 30
CACHE_MAX = 500
SEC_CACHE_TTL = 120  # authorities/holders change slowly

# Solana RPC. The public endpoint is heavily rate-limited: set SOLANA_RPC_URL
# (e.g. a free Helius URL) in Render > Environment for reliable results.
RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
RUGCHECK_URL = "https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary"  # public, no key
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
RISKY_EXTENSIONS = {"permanentDelegate", "transferHook", "transferFeeConfig", "defaultAccountState"}
# Holders that are not "real" holders: burn address + common AMM pool authorities (best effort)
KNOWN_NON_HOLDERS = {
    "1nc1nerator11111111111111111111111111111111",  # burn
    "5Q544fKrFoe6tsEbD7S8EmxGTJYAKtTVhAW5Q5pge4j1",  # Raydium AMM v4 authority
    "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL",  # Raydium CPMM authority
}
RATE_LIMIT = 30      # requests
RATE_WINDOW = 60     # seconds, per IP
GLOBAL_LIMIT = 250   # upstream fetches/minute across ALL clients (protects DexScreener quota)
MAX_BATCH = 10
SECONDARY_TIMEOUT = 2.5  # max wait for RPC / RugCheck before answering with partial data
PARTIAL_TTL = 8          # partial results are cached only briefly
STALE_MAX = 600          # serve cached data up to 10 min old if upstream is down
# How many trusted proxies sit in front of the app (Render = 1). The client IP is read
# from the RIGHT side of X-Forwarded-For, so a client cannot spoof it by sending its own header.
TRUSTED_HOPS = max(1, int(os.getenv("TRUSTED_PROXY_HOPS", "1")))


# ---------- operations: metrics + response headers ----------
_m: Dict[str, Any] = {"started": time.time(), "routes": Counter(), "status": Counter(),
                      "lat": {}, "cache": Counter(), "partial": 0}
_KNOWN_ROUTES = {"/signal", "/signals", "/exit", "/stats", "/health", "/metrics", "/mcp", "/llms.txt", "/docs", "/openapi.json"}
_TIMED_ROUTES = {"/signal", "/signals", "/exit", "/mcp"}


def route_label(path: str) -> str:
    if path in ("", "/"):
        return "/"
    return path.rstrip("/") if path.rstrip("/") in _KNOWN_ROUTES else "other"


def pctl(vals, p: float) -> Optional[float]:
    v = sorted(vals)
    return round(v[min(len(v) - 1, int(len(v) * p))], 1) if v else None


class MetricsMiddleware:
    """Pure ASGI (safe with the mounted MCP app): adds X-API-Version / X-Response-Time and counts requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        t0 = time.time()
        label = route_label(scope.get("path", ""))
        box = {"code": 500}

        async def send_wrap(message):
            if message["type"] == "http.response.start":
                box["code"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-api-version", VERSION.encode()))
                headers.append((b"x-response-time", f"{(time.time() - t0) * 1000:.0f}ms".encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrap)
        finally:
            ms = (time.time() - t0) * 1000
            _m["routes"][label] += 1
            _m["status"][str(box["code"])] += 1
            if label in _TIMED_ROUTES:
                _m["lat"].setdefault(label, deque(maxlen=300)).append(ms)


def metrics_report() -> dict:
    c = _m["cache"]
    total = sum(c.values())
    pct = lambda x: round(x / total * 100, 1) if total else None  # noqa: E731
    return {
        "version": VERSION,
        "uptime_s": int(time.time() - _m["started"]),
        "note": "Counters live in memory and reset when the server restarts or sleeps.",
        "requests": sum(_m["routes"].values()),
        "by_route": dict(_m["routes"]),
        "by_status": dict(_m["status"]),
        "latency_ms": {r: {"n": len(d), "p50": pctl(d, 0.5), "p95": pctl(d, 0.95)} for r, d in _m["lat"].items() if d},
        "signals": {"total": total, "cache_hit_rate_pct": pct(c["HIT"]), "stale_rate_pct": pct(c["STALE"]),
                    "partial_rate_pct": pct(_m["partial"])},
        "sources": src_status(),
    }


mcp_server = None  # set at the bottom of this file when the `mcp` package is installed


@asynccontextmanager
async def lifespan(app: FastAPI):
    # One shared client = connection reuse, much faster than a new client per request
    app.state.client = httpx.AsyncClient(
        timeout=httpx.Timeout(6.0, connect=3.0),
        headers={"User-Agent": f"TVibex402/{VERSION}"},
    )
    resolver = asyncio.create_task(resolver_loop(app)) if PRED_ENABLED else None
    try:
        if mcp_server is not None:
            # the MCP Streamable HTTP session manager must run for the app's whole lifetime
            async with mcp_server.session_manager.run():
                yield
        else:
            yield
    finally:
        if resolver:
            resolver.cancel()
        await app.state.client.aclose()


app = FastAPI(
    title="TVibex402",
    version=VERSION,
    description="Free Solana token data API for AI agents & bots. Not financial advice.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Cache", "X-Response-Time", "X-API-Version", "Retry-After"],
)
app.add_middleware(MetricsMiddleware)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    """Same {"detail": ...} shape as before. For 502/503 we add source health + a retry hint, so an agent
    can tell 'wait a few seconds' from 'give up' when one or more data sources are down."""
    body: Dict[str, Any] = {"detail": exc.detail}
    if exc.status_code in (502, 503):
        retry = int((exc.headers or {}).get("Retry-After", 10))
        body.update(retry_after_s=retry, sources=src_status())
    return JSONResponse(content=body, status_code=exc.status_code, headers=exc.headers)

# ---------- cache ----------
_cache: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()
_cache_lock = threading.Lock()


def cache_peek(key: str):
    """Return (age_seconds, data) or None. Entries are NOT dropped when expired,
    so they can still be served as stale if upstream fails (LRU keeps the size bounded)."""
    with _cache_lock:
        item = _cache.get(key)
        if not item:
            return None
        ts, data = item
        _cache.move_to_end(key)
        return time.time() - ts, data


def cache_get(key: str, ttl: int = CACHE_TTL) -> Optional[dict]:
    hit = cache_peek(key)
    return hit[1] if hit and hit[0] <= ttl else None


def cache_set(key: str, data: dict):
    with _cache_lock:
        _cache[key] = (time.time(), data)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)


# ---------- rate limit (per IP, in-memory sliding window) ----------
_hits: Dict[str, deque] = {}
_rl_lock = threading.Lock()


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        parts = [x.strip() for x in xff.split(",") if x.strip()]
        if len(parts) >= TRUSTED_HOPS:
            return parts[-TRUSTED_HOPS]
        if parts:
            return parts[0]
    return request.client.host if request.client else "unknown"


def rate_limited(key: str, limit: int = RATE_LIMIT, cost: int = 1) -> int:
    """Return 0 if allowed (and record `cost` hits), else seconds to wait."""
    now = time.time()
    with _rl_lock:
        dq = _hits.setdefault(key, deque())
        while dq and now - dq[0] > RATE_WINDOW:
            dq.popleft()
        if len(dq) + cost > limit:
            return int(RATE_WINDOW - (now - dq[0])) + 1 if dq else RATE_WINDOW
        dq.extend([now] * cost)
        if len(_hits) > 5000:  # cleanup stale IPs
            for k in [k for k, v in _hits.items() if not v or now - v[-1] > RATE_WINDOW]:
                _hits.pop(k, None)
    return 0

# --- part2 ---
# ---------- signal logic ----------
def pick_best_pair(pairs: list, mint: str) -> Optional[dict]:
    sol = [p for p in pairs if p.get("chainId") == "solana"]
    if not sol:
        return None
    # Prefer pairs where the requested mint is the BASE token (otherwise data is for the other token)
    base_match = [p for p in sol if (p.get("baseToken") or {}).get("address") == mint]
    pool = base_match or sol
    return max(pool, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)


RISK_WEIGHTS = {
    "very_low_liquidity": 30,
    "low_liquidity": 15,
    "brand_new_pair": 20,
    "very_new_pair": 10,
    "new_pair": 5,
    "extreme_turnover": 15,
    "high_turnover": 5,
    "dump_risk": 25,
    "heavy_selling": 10,
    "extreme_volume_spike": 10,
    "mint_authority_active": 25,
    "freeze_authority_active": 20,
    "risky_token_extension": 20,
    "extreme_holder_concentration": 30,
    "high_holder_concentration": 15,
    "dominant_holder": 10,
    "lp_not_locked": 25,
    "lp_partially_locked": 10,
}


def compute_signals(pair: dict) -> Dict[str, Any]:
    base = pair.get("baseToken") or {}
    volume = pair.get("volume") or {}
    txns = pair.get("txns") or {}
    price_change = pair.get("priceChange") or {}
    liquidity_usd = float((pair.get("liquidity") or {}).get("usd") or 0)

    m5 = txns.get("m5") or {}
    buys_5m = int(m5.get("buys") or 0)
    sells_5m = int(m5.get("sells") or 0)
    total_5m = buys_5m + sells_5m
    buy_pressure = round(buys_5m / total_5m, 3) if total_5m > 0 else None

    vol_5m = float(volume.get("m5") or 0)
    vol_1h = float(volume.get("h1") or 0)
    vol_6h = float(volume.get("h6") or 0)
    avg_5m = vol_1h / 12 if vol_1h > 0 else 0
    volume_spike = round(vol_5m / avg_5m, 2) if avg_5m > 0 else None
    turnover = round(vol_1h / liquidity_usd, 3) if liquidity_usd > 0 else None

    flags = []
    if volume_spike is not None:
        if volume_spike >= 5.0:
            flags.append("extreme_volume_spike")
        elif volume_spike >= 3.0:
            flags.append("volume_spike")
    if buy_pressure is not None:
        if buy_pressure >= 0.75:
            flags.append("heavy_buying")
        elif buy_pressure <= 0.25:
            flags.append("heavy_selling")
    if liquidity_usd < 20000:
        flags.append("very_low_liquidity")
    elif liquidity_usd < 50000:
        flags.append("low_liquidity")
    if turnover is not None:
        if turnover >= 3.0:
            flags.append("extreme_turnover")
        elif turnover >= 1.5:
            flags.append("high_turnover")

    created = pair.get("pairCreatedAt")
    age_minutes = None
    if created:
        age_minutes = max(0, int((time.time() * 1000 - created) / 60000))
        if age_minutes < 60:
            flags.append("brand_new_pair")
        elif age_minutes < 360:
            flags.append("very_new_pair")
        elif age_minutes < 1440:
            flags.append("new_pair")

    pc = price_change
    if (pc.get("m5") or 0) > 10 and (pc.get("h1") or 0) > 20:
        flags.append("strong_momentum")
    if (pc.get("m5") or 0) < -15 and (pc.get("h1") or 0) < -25:
        flags.append("dump_risk")
    if total_5m >= 300:
        flags.append("high_activity")

    return {
        "token": base.get("symbol") or "UNKNOWN",
        "name": base.get("name"),
        "mint": base.get("address"),
        "price_usd": pair.get("priceUsd"),
        "price_change_pct": {
            "5m": price_change.get("m5"),
            "1h": price_change.get("h1"),
            "6h": price_change.get("h6"),
            "24h": price_change.get("h24"),
        },
        "liquidity_usd": round(liquidity_usd, 2),
        "fdv_usd": pair.get("fdv"),
        "market_cap_usd": pair.get("marketCap"),
        "volume_5m": round(vol_5m, 2),
        "volume_1h": round(vol_1h, 2),
        "volume_6h": round(vol_6h, 2) if vol_6h else None,
        "buys_5m": buys_5m,
        "sells_5m": sells_5m,
        "buy_pressure_5m": buy_pressure,
        "volume_spike_ratio_5m": volume_spike,
        "turnover_1h": turnover,
        "pair_age_minutes": age_minutes,
        "dex": pair.get("dexId"),
        "pair_address": pair.get("pairAddress"),
        "flags": flags,
        "timestamp": int(time.time()),
        "source": "dexscreener",
        "version": VERSION,
    }


# ---------- on-chain security (Solana RPC) ----------
async def rpc(client: httpx.AsyncClient, method: str, params: list):
    resp = await client.post(
        RPC_URL, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("error"):
        raise RuntimeError(str(body["error"])[:200])
    return body.get("result")


async def fetch_security(client: httpx.AsyncClient, mint: str) -> Optional[dict]:
    """Raw on-chain data. Never raises; returns None if nothing could be read."""
    t_rpc = time.time()
    info_r, big_r = await asyncio.gather(
        rpc(client, "getAccountInfo", [mint, {"encoding": "jsonParsed"}]),
        rpc(client, "getTokenLargestAccounts", [mint, {"commitment": "confirmed"}]),
        return_exceptions=True,
    )
    src_log("solana_rpc", not isinstance(info_r, Exception) and not isinstance(big_r, Exception), t_rpc)
    raw: Dict[str, Any] = {"info_ok": False, "holders": None, "supply": None}

    try:
        val = (info_r or {}).get("value") if not isinstance(info_r, Exception) else None
        data = (val or {}).get("data")
        parsed = data.get("parsed") if isinstance(data, dict) else None
        if parsed and parsed.get("type") == "mint":
            info = parsed.get("info") or {}
            raw.update(
                info_ok=True,
                mint_authority=info.get("mintAuthority"),
                freeze_authority=info.get("freezeAuthority"),
                decimals=info.get("decimals"),
                supply=int(info.get("supply") or 0) or None,
                program="token-2022" if val.get("owner") == TOKEN_2022 else "spl-token",
                extensions=[e.get("extension") for e in (info.get("extensions") or []) if isinstance(e, dict)],
            )
    except Exception:
        pass

    try:
        if not isinstance(big_r, Exception) and big_r:
            accts = big_r.get("value") or []
            addrs = [a["address"] for a in accts]
            owners: Dict[str, str] = {}
            if addrs:
                try:
                    multi = await rpc(client, "getMultipleAccounts", [addrs, {"encoding": "jsonParsed"}])
                    for addr, acc in zip(addrs, (multi or {}).get("value") or []):
                        try:
                            owners[addr] = acc["data"]["parsed"]["info"]["owner"]
                        except (TypeError, KeyError):
                            pass
                except Exception:
                    pass
            raw["holders"] = [
                {"account": a["address"], "owner": owners.get(a["address"]), "amount": int(a.get("amount") or 0)}
                for a in accts
            ]
    except Exception:
        pass

    if not raw["info_ok"] and raw["holders"] is None:
        return None
    return raw


async def get_security(client: httpx.AsyncClient, mint: str) -> Optional[dict]:
    key = "sec:" + mint
    cached = cache_get(key, SEC_CACHE_TTL)
    if cached:
        return cached
    try:
        raw = await fetch_security(client, mint)
    except Exception:
        return None
    if raw:
        cache_set(key, raw)
    return raw


def build_security(raw: Optional[dict], pool_ids: set):
    """Turn raw on-chain data into a public `security` block + extra flags."""
    if not raw:
        return {"available": False}, []
    flags = []
    out: Dict[str, Any] = {"available": True, "partial": False}

    if raw.get("info_ok"):
        ma, fa = raw.get("mint_authority"), raw.get("freeze_authority")
        out.update(
            mint_authority_revoked=ma is None,
            freeze_authority_revoked=fa is None,
            token_program=raw.get("program"),
            decimals=raw.get("decimals"),
        )
        risky = sorted(set(raw.get("extensions") or []) & RISKY_EXTENSIONS)
        out["risky_extensions"] = risky
        if ma is not None:
            flags.append("mint_authority_active")
        if fa is not None:
            flags.append("freeze_authority_active")
        if risky:
            flags.append("risky_token_extension")
    else:
        out["partial"] = True

    holders, supply = raw.get("holders"), raw.get("supply")
    if holders and supply:
        excluded_ids = pool_ids | KNOWN_NON_HOLDERS
        real, pool_pct = [], 0.0
        for h in holders:
            pct = h["amount"] / supply * 100
            if h["owner"] in excluded_ids or h["account"] in excluded_ids:
                pool_pct += pct
            else:
                real.append({"owner": h["owner"] or h["account"], "pct": round(pct, 2)})
        top1 = real[0]["pct"] if real else 0.0
        top10 = round(sum(h["pct"] for h in real[:10]), 2)
        out.update(
            top1_holder_pct=top1,
            top10_holders_pct=top10,
            liquidity_pool_pct=round(pool_pct, 2),
            top_holders=real[:5],
        )
        if top10 >= 80:
            flags.append("extreme_holder_concentration")
        elif top10 >= 50:
            flags.append("high_holder_concentration")
        if top1 >= 20:
            flags.append("dominant_holder")
    else:
        out["partial"] = True
    return out, flags


def finalize_risk(result: dict, onchain: bool):
    """Heuristic 0-100 score from market flags (+ on-chain flags when available).
    It is a quick filter, NOT a guarantee."""
    score = min(100, sum(ACTIVE_WEIGHTS.get(f, 0) for f in result["flags"]))
    result["scoring"] = "tuned" if _tune["on"] else "static"
    result["risk_score"] = score
    result["risk_level"] = "low" if score < 25 else "medium" if score < 50 else "high"
    result["risk_basis"] = "market+onchain" if onchain else "market"


async def get_lp_lock(client: httpx.AsyncClient, mint: str) -> Optional[dict]:
    """LP lock/burn % + RugCheck score from RugCheck's public summary. Never raises."""
    key = "lp:" + mint
    cached = cache_get(key, SEC_CACHE_TTL)
    if cached:
        return cached
    t0 = time.time()
    try:
        resp = await client.get(RUGCHECK_URL.format(mint=mint))
        resp.raise_for_status()
        j = resp.json()
        pct = j.get("lpLockedPct")
        out = {
            "lp_locked_pct": round(float(pct), 2) if pct is not None else None,
            "rugcheck_score": j.get("score_normalised"),  # 0-100, higher = riskier
            "rugcheck_risks": [
                {"name": r.get("name"), "level": r.get("level")}
                for r in (j.get("risks") or [])[:6]
                if isinstance(r, dict)
            ],
        }
        src_log("rugcheck", True, t0)
    except Exception:
        src_log("rugcheck", False, t0)
        return None
    cache_set(key, out)
    return out


async def fetch_dex(client: httpx.AsyncClient, mint: str) -> dict:
    t0 = time.time()
    try:
        resp = await client.get(DEX_URL.format(mint=mint))
        resp.raise_for_status()
        data = resp.json()
        src_log("dexscreener", True, t0)
        return data
    except (httpx.HTTPError, ValueError):
        src_log("dexscreener", False, t0)
        raise HTTPException(status_code=503, detail="Market data source (DexScreener) is unavailable, retry in a few seconds",
                            headers={"Retry-After": "10"})

# --- part3 ---
# ---------- verdict ----------
REASONS = {
    "mint_authority_active": "Mint authority still active: supply can be inflated",
    "freeze_authority_active": "Freeze authority active: wallets can be frozen",
    "risky_token_extension": "Token-2022 extension that can restrict or tax transfers",
    "lp_not_locked": "Liquidity is not locked or burned",
    "dump_risk": "Price is dumping fast",
    "extreme_holder_concentration": "Top 10 holders own 80%+ of supply",
    "very_low_liquidity": "Liquidity under $20k",
    "low_liquidity": "Liquidity under $50k",
    "high_holder_concentration": "Top 10 holders own 50%+ of supply",
    "dominant_holder": "One wallet holds 20%+ of supply",
    "lp_partially_locked": "Liquidity only partly locked or burned",
    "brand_new_pair": "Pair is under 1 hour old",
    "extreme_turnover": "Volume is extreme vs liquidity (wash-trading risk)",
}
AVOID_FLAGS = ["mint_authority_active", "freeze_authority_active", "risky_token_extension",
               "lp_not_locked", "dump_risk", "extreme_holder_concentration"]
CAUTION_FLAGS = ["very_low_liquidity", "low_liquidity", "high_holder_concentration", "dominant_holder",
                 "lp_partially_locked", "brand_new_pair", "extreme_turnover"]
AUTHORITY_FLAGS = {"mint_authority_active", "freeze_authority_active"}


def add_verdict(result: dict):
    """One-line decision for agents: ok | caution | avoid (heuristic, not advice)."""
    flags = set(result["flags"])
    # Established tokens (e.g. regulated stablecoins) legitimately keep authorities
    established = result["liquidity_usd"] >= 1_000_000 and (result.get("pair_age_minutes") or 0) >= 43200
    avoid = [f for f in AVOID_FLAGS if f in flags and not (established and f in AUTHORITY_FLAGS)]
    caution = [f for f in CAUTION_FLAGS if f in flags]
    if established:
        caution = [f for f in AUTHORITY_FLAGS if f in flags] + caution
    score = result["risk_score"]
    result["verdict"] = "avoid" if avoid or score >= 50 else "caution" if caution or score >= 25 else "ok"
    result["verdict_reasons"] = [REASONS[f] for f in avoid + caution]
    # "full" only when BOTH on-chain sources answered in time
    result["verdict_confidence"] = "full" if result.get("security") and not result.get("partial") else "market_only"
    top = "; ".join(result["verdict_reasons"][:3]) or "no major red flags found"
    result["summary"] = (
        f"{result.get('token') or '?'}: {result['verdict'].upper()} ({result['verdict_confidence']} data). "
        f"{top}. Liquidity ${result['liquidity_usd']:,.0f}, risk {result['risk_score']}/100."
    )
    nxt = []
    if result.get("partial"):
        miss = [k for k, v in (result.get("sources") or {}).items() if v != "ok"]
        nxt.append("retry in a few seconds for full on-chain data" + (f" (missing: {', '.join(miss)})" if miss else ""))
    if result["verdict"] != "avoid":
        nxt.append("run the exit check (GET /exit or MCP check_exit) before sizing a trade")
    result["suggested_next"] = nxt


# ---------- pipeline ----------
_bg: set = set()


async def soft(coro, timeout: float):
    """Wait up to `timeout`, then give up for THIS request but let the work finish
    in the background so it lands in the cache for the next request."""
    task = asyncio.ensure_future(coro)
    _bg.add(task)
    task.add_done_callback(_bg.discard)
    try:
        return await asyncio.wait_for(asyncio.shield(task), timeout)
    except Exception:
        return None


async def _dex_or_prefetched(client: httpx.AsyncClient, mint: str, prefetched: Optional[dict]) -> dict:
    return prefetched if prefetched is not None else await fetch_dex(client, mint)


async def fetch_dex_many(client: httpx.AsyncClient, mints: List[str]) -> Optional[Dict[str, dict]]:
    """ONE DexScreener request for up to 30 mints. Returns {mint: {"pairs": [...]}} or None if the call failed."""
    out: Dict[str, dict] = {m: {"pairs": []} for m in mints}
    t0 = time.time()
    try:
        resp = await client.get(DEX_URL.format(mint=",".join(mints)))
        resp.raise_for_status()
        pairs = resp.json().get("pairs") or []
        src_log("dexscreener", True, t0)
    except (httpx.HTTPError, ValueError):
        src_log("dexscreener", False, t0)
        return None
    for p in pairs:
        for m in {(p.get("baseToken") or {}).get("address"), (p.get("quoteToken") or {}).get("address")}:
            if m in out:
                out[m]["pairs"].append(p)
    return out


async def _build_signal_core(client: httpx.AsyncClient, mint: str, security: bool, prefetched: Optional[dict] = None):
    """Return (result, cache_status). Raises HTTPException on failure."""
    cache_key = mint if security else mint + ":nosec"
    hit = cache_peek(cache_key)
    stale = None
    if hit:
        age, cached = hit
        if age <= (PARTIAL_TTL if cached.get("partial") else CACHE_TTL):
            return cached, "HIT"
        if age <= STALE_MAX:
            stale = (age, cached)

    def serve_stale(err: HTTPException):
        if stale:
            return dict(stale[1], stale=True, stale_age_s=int(stale[0])), "STALE"
        raise err

    # global budget for upstream calls, independent of client IP
    if prefetched is None and rate_limited("__global__", GLOBAL_LIMIT):  # batches pay once, in build_batch
        return serve_stale(HTTPException(status_code=503, detail="Service busy, retry shortly", headers={"Retry-After": "5"}))

    try:
        if security:
            data, raw_sec, lp_raw = await asyncio.gather(
                _dex_or_prefetched(client, mint, prefetched),
                soft(get_security(client, mint), SECONDARY_TIMEOUT),
                soft(get_lp_lock(client, mint), SECONDARY_TIMEOUT),
            )
        else:
            data, raw_sec, lp_raw = await _dex_or_prefetched(client, mint, prefetched), None, None
    except HTTPException as e:
        return serve_stale(e)

    pair = pick_best_pair(data.get("pairs") or [], mint)
    if not pair:
        raise HTTPException(status_code=404, detail="No Solana pair found for this token")

    result = compute_signals(pair)
    result["partial"] = bool(security and (raw_sec is None or lp_raw is None))
    if security:
        result["sources"] = {"dexscreener": "ok", "solana_rpc": "ok" if raw_sec else "missing",
                             "rugcheck": "ok" if lp_raw else "missing"}
    onchain = False
    if security:
        pool_ids = {x for x in (pair.get("pairAddress"),) if x}
        sec, sec_flags = build_security(raw_sec, pool_ids)
        result["flags"].extend(sec_flags)
        if lp_raw:
            pct = lp_raw.get("lp_locked_pct")
            sec.update(lp_locked_pct=pct, rugcheck_score=lp_raw.get("rugcheck_score"),
                       rugcheck_risks=lp_raw.get("rugcheck_risks"), lp_source="rugcheck")
            # bonding-curve tokens have no LP yet, so skip the LP flags there
            if pct is not None and pair.get("dexId") != "pumpfun":
                if pct < 10:
                    result["flags"].append("lp_not_locked")
                elif pct < 80:
                    result["flags"].append("lp_partially_locked")
        result["security"] = sec
        onchain = bool(sec.get("available")) or bool(lp_raw)
    finalize_risk(result, onchain)
    add_verdict(result)
    cache_set(cache_key, result)
    if security and PRED_ENABLED:
        schedule(record_prediction(client, result))  # fire and forget: adds no latency
    return result, "MISS"


# ---------- data quality (what is missing, how fresh, how complete) ----------
def with_quality(result: dict, status: str, security: bool) -> dict:
    """Return a COPY with a data_quality block (the cached dict is never mutated).
    data_confidence (0-1) = how complete and fresh the data is. It is NOT the probability that the
    verdict is correct: that is what /stats measures."""
    now = time.time()
    age = max(0, int(now - (result.get("timestamp") or now)))
    freshness = "stale" if status == "STALE" else "fresh" if age <= 5 else "cached"
    missing = [k for k, v in (result.get("sources") or {}).items() if v != "ok"]
    completeness = "market_only" if not security else "partial" if missing else "full"
    conf = 1.0 - sum({"solana_rpc": 0.25, "rugcheck": 0.2}.get(m, 0.15) for m in missing)
    if not security:
        conf = min(conf, 0.6)
    if status == "STALE":
        conf -= 0.2 + min(0.3, age / 600 * 0.3)
    return dict(result, data_quality={"freshness": freshness, "age_s": age, "completeness": completeness,
                                      "missing": missing, "data_confidence": max(0.05, round(conf, 2))})


async def build_signal(client: httpx.AsyncClient, mint: str, security: bool, prefetched: Optional[dict] = None):
    result, status = await _build_signal_core(client, mint, security, prefetched)
    _m["cache"][status] += 1
    if result.get("partial"):
        _m["partial"] += 1
    return with_quality(result, status, security), status


# ---------- smart batch ----------
BATCH_DEADLINE_S = 9.0
_COMPACT_KEYS = ("token", "name", "mint", "price_usd", "liquidity_usd", "pair_age_minutes", "verdict",
                 "verdict_confidence", "verdict_reasons", "risk_score", "risk_level", "flags", "summary", "safety_rank",
                 "partial", "stale", "data_quality")


def compact_signal(r: dict) -> dict:
    out = {k: r.get(k) for k in _COMPACT_KEYS if k in r}
    sec = r.get("security") or {}
    for k in ("mint_authority_revoked", "freeze_authority_revoked", "top10_holders_pct", "lp_locked_pct"):
        if k in sec:
            out[k] = sec[k]
    return out


async def build_batch(client: httpx.AsyncClient, raw_mints: List[str], security: bool, *, sort: str = "input",
                      only: Optional[str] = None, max_risk: Optional[int] = None, top: Optional[int] = None,
                      view: str = "full", charge=None) -> dict:
    """Smart batch: ONE shared DexScreener request for everything not cached, cost = only what needs fetching,
    an overall deadline (slow tokens are reported, not waited for), ranking, filters and a one-line summary."""
    ids = list(dict.fromkeys(m.strip() for m in raw_mints if m and m.strip()))
    if not ids:
        raise HTTPException(status_code=400, detail="Provide at least one mint")
    if len(ids) > MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"Max {MAX_BATCH} mints per request")
    if sort not in ("input", "safest", "riskiest"):
        raise HTTPException(status_code=400, detail="sort must be input, safest or riskiest")
    if view not in ("full", "compact"):
        raise HTTPException(status_code=400, detail="view must be full or compact")
    only_set = None
    if only:
        only_set = {x.strip().lower() for x in only.split(",") if x.strip()}
        if not only_set or not only_set <= {"ok", "caution", "avoid"}:
            raise HTTPException(status_code=400, detail="only must be a comma list of: ok, caution, avoid")

    errors: List[dict] = []
    valid: List[str] = []
    for m in ids:
        if MINT_RE.match(m):
            valid.append(m)
        else:
            errors.append({"mint": m, "status": 400, "detail": "Invalid Solana token address"})

    # what actually needs upstream work? (fresh cache hits are free)
    todo = []
    for m in valid:
        hit = cache_peek(m if security else m + ":nosec")
        if not (hit and hit[0] <= (PARTIAL_TTL if hit[1].get("partial") else CACHE_TTL)):
            todo.append(m)
    wait = charge(max(1, len(todo))) if charge else 0
    if wait:
        raise too_many(wait)

    prefetched: Dict[str, dict] = {}
    for i in range(0, len(todo), 30):
        if rate_limited("__global__", GLOBAL_LIMIT):
            break  # over budget: each token falls back to stale cache or a clear 503
        got = await fetch_dex_many(client, todo[i:i + 30])
        if got:
            prefetched.update(got)

    sem = asyncio.Semaphore(4)

    async def one(m: str) -> dict:
        async with sem:
            res, _ = await build_signal(client, m, security, prefetched.get(m))
            return res

    tasks: Dict[str, Any] = {}
    for m in valid:
        t = asyncio.ensure_future(one(m))
        t.add_done_callback(lambda f: f.cancelled() or f.exception())  # never log 'exception never retrieved'
        _bg.add(t)
        t.add_done_callback(_bg.discard)
        tasks[m] = t
    if tasks:
        await asyncio.wait(list(tasks.values()), timeout=BATCH_DEADLINE_S)

    results: List[dict] = []
    for m in valid:
        t = tasks[m]
        if not t.done():  # keeps running in the background and lands in the cache
            errors.append({"mint": m, "status": 504, "detail": "Still computing, retry in a few seconds", "retry_after_s": 5})
            continue
        exc = t.exception()
        if exc is None:
            results.append(t.result())
        elif isinstance(exc, HTTPException):
            e = {"mint": m, "status": exc.status_code, "detail": exc.detail}
            if exc.headers and "Retry-After" in exc.headers:
                e["retry_after_s"] = int(exc.headers["Retry-After"])
            errors.append(e)
        else:
            errors.append({"mint": m, "status": 500, "detail": "Internal error"})

    order = sorted(range(len(results)), key=lambda i: (results[i]["risk_score"], -(results[i].get("liquidity_usd") or 0)))
    for rank, i in enumerate(order, 1):
        results[i] = dict(results[i], safety_rank=rank)
    everything = list(results)

    if only_set:
        results = [r for r in results if r["verdict"] in only_set]
    if max_risk is not None:
        results = [r for r in results if r["risk_score"] <= max_risk]
    if sort == "safest":
        results.sort(key=lambda r: r["safety_rank"])
    elif sort == "riskiest":
        results.sort(key=lambda r: -r["safety_rank"])
    if top:
        results = results[:top]
    if view == "compact":
        results = [compact_signal(r) for r in results]

    cnt = Counter(r["verdict"] for r in everything)
    best = min(everything, key=lambda r: r["safety_rank"]) if everything else None
    worst = max(everything, key=lambda r: r["safety_rank"]) if everything else None
    brief = lambda r: {"mint": r["mint"], "token": r.get("token"), "risk_score": r["risk_score"], "verdict": r["verdict"]}  # noqa: E731
    headline = (f"{len(ids)} requested: {cnt['ok']} ok, {cnt['caution']} caution, {cnt['avoid']} avoid"
                + (f", {len(errors)} failed" if errors else "")
                + (f". Lowest risk: {best.get('token')} ({best['risk_score']}/100)" if best else "") + ".")
    return {
        "count": len(results),
        "summary": {"checked": len(ids), "ok": cnt["ok"], "caution": cnt["caution"], "avoid": cnt["avoid"],
                    "failed": len(errors), "headline": headline,
                    "safest": brief(best) if best else None, "riskiest": brief(worst) if worst else None,
                    "min_data_confidence": min((r["data_quality"]["data_confidence"] for r in everything), default=None)},
        "results": results, "errors": errors, "filtered_out": len(everything) - len(results),
        "sort": sort, "view": view,
    }

# --- part4 ---
# ---------- self-calibration: track record, prediction error, source health ----------
# Every verdict is a prediction. About 24h later we measure what happened; the gap between
# prediction and outcome ("prediction error") feeds public stats and, optionally, the risk weights.
REDIS_URL = (os.getenv("UPSTASH_REDIS_REST_URL") or "").rstrip("/")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN") or ""
PRED_ENABLED = bool(REDIS_URL and REDIS_TOKEN)
PRED_HORIZON_S = int(float(os.getenv("PRED_HORIZON_HOURS", "24")) * 3600)
MAX_PRED_PER_DAY = int(os.getenv("MAX_PRED_PER_DAY", "300"))  # keeps Upstash usage well inside the free tier
AUTO_TUNE = os.getenv("AUTO_TUNE", "").lower() in ("1", "true", "yes")  # OFF by default
BAD_RETURN_PCT = -50.0   # "bad outcome": price down 50%+ ...
BAD_LIQ_RATIO = 0.3      # ... or liquidity down 70%+ (or the pair vanished)
MIN_N_SHOW = 20          # never show rates from fewer than 20 samples
STATS_TTL = 600
SOL_MINT = "So11111111111111111111111111111111111111112"
RESOLVE_BATCH = 25       # predictions judged per cycle (+1 slot for the SOL baseline price)
MIN_DAY_N = 5            # a day needs this many resolved predictions to count as a market-background cohort

ACTIVE_WEIGHTS: Dict[str, int] = dict(RISK_WEIGHTS)
_tune: Dict[str, Any] = {"on": False, "n": 0}
_pred_day: Dict[str, Any] = {"day": "", "count": 0}
_stats_cache: Dict[str, Any] = {"ts": 0.0, "data": None}

# ----- source health (in memory) -----
_src: Dict[str, deque] = {}
SRC_WINDOW_S = 600


def src_log(name: str, ok: bool, t0: float):
    _src.setdefault(name, deque(maxlen=40)).append((time.time(), bool(ok), (time.time() - t0) * 1000))


def src_status() -> dict:
    now, out = time.time(), {}
    for name in ("dexscreener", "solana_rpc", "rugcheck", "jupiter"):
        recent = [x for x in _src.get(name, ()) if now - x[0] <= SRC_WINDOW_S]
        if not recent:
            out[name] = {"status": "unknown"}
            continue
        okr = sum(1 for x in recent if x[1]) / len(recent)
        out[name] = {"status": "ok" if okr >= 0.8 else "degraded" if okr >= 0.4 else "down",
                     "success_rate_pct": round(okr * 100), "avg_ms": round(sum(x[2] for x in recent) / len(recent)),
                     "samples": len(recent)}
    return out


# ----- Upstash Redis over REST (no extra dependency) -----
async def redis_pipe(client: httpx.AsyncClient, cmds: list) -> Optional[list]:
    if not PRED_ENABLED:
        return None
    try:
        resp = await client.post(
            REDIS_URL + "/pipeline",
            json=[[str(x) for x in c] for c in cmds],
            headers={"Authorization": f"Bearer {REDIS_TOKEN}"},
            timeout=5.0,
        )
        resp.raise_for_status()
        return [(x.get("result") if isinstance(x, dict) else None) for x in resp.json()]
    except Exception:
        return None


def to_dict(v) -> dict:
    if isinstance(v, dict):
        return v
    if isinstance(v, list):
        return dict(zip(v[0::2], v[1::2]))
    return {}


def schedule(coro):
    t = asyncio.ensure_future(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


_sol: Dict[str, Any] = {"ts": 0.0, "price": None}


async def sol_price(client: httpx.AsyncClient) -> Optional[float]:
    """SOL/USD, cached 60s. This is the 'background expansion' every token rides on."""
    if _sol["price"] and time.time() - _sol["ts"] < 60:
        return _sol["price"]
    price = None
    try:
        resp = await client.get(DEX_URL.format(mint=SOL_MINT))
        resp.raise_for_status()
        pair = pick_best_pair([p for p in (resp.json().get("pairs") or [])
                               if (p.get("baseToken") or {}).get("address") == SOL_MINT], SOL_MINT)
        price = float(pair.get("priceUsd")) if pair else None
    except (httpx.HTTPError, ValueError, TypeError):
        price = None
    if price and price > 0:
        _sol.update(ts=time.time(), price=price)
        return price
    return None


async def record_prediction(client: httpx.AsyncClient, r: dict):
    """Store one verdict to be judged later. At most one per mint per 6h and MAX_PRED_PER_DAY per day."""
    try:
        price = float(r.get("price_usd") or 0)
        mint = r.get("mint")
        if price <= 0 or not mint:
            return
        today = time.strftime("%Y%m%d", time.gmtime())
        if _pred_day["day"] != today:
            _pred_day.update(day=today, count=0)
        if _pred_day["count"] >= MAX_PRED_PER_DAY:
            return
        lock = await redis_pipe(client, [["SET", f"plock:{mint}", "1", "EX", 21600, "NX"]])
        if not lock or lock[0] != "OK":
            return
        _pred_day["count"] += 1
        now = int(time.time())
        pid = f"{mint}:{now}"
        sol = await sol_price(client)
        await redis_pipe(client, [
            ["HSET", f"pred:{pid}", "mint", mint, "token", r.get("token") or "", "ts", now, "price", price,
             "liq", r.get("liquidity_usd") or 0, "verdict", r["verdict"], "conf", r["verdict_confidence"],
             "score", r["risk_score"], "flags", ",".join(r.get("flags") or []), "sol", sol or ""],
            ["EXPIRE", f"pred:{pid}", PRED_HORIZON_S * 4],
            ["ZADD", "due", now + PRED_HORIZON_S, pid],
        ])
    except Exception:
        pass


async def resolve_due(client: httpx.AsyncClient) -> int:
    """Judge predictions whose time has come. Returns how many were processed."""
    now = int(time.time())
    got = await redis_pipe(client, [["ZRANGEBYSCORE", "due", "-inf", now, "LIMIT", 0, RESOLVE_BATCH]])
    ids = (got or [[]])[0] or []
    if not ids:
        return 0
    hashes = await redis_pipe(client, [["HGETALL", f"pred:{i}"] for i in ids])
    if hashes is None:
        return 0
    cmds: list = []
    preds: Dict[str, dict] = {}
    for pid, h in zip(ids, hashes):
        d = to_dict(h)
        if d.get("mint"):
            preds[pid] = d
        else:
            cmds.append(["ZREM", "due", pid])  # hash expired: drop the orphan
    best: Dict[str, Optional[dict]] = {}
    sol1: Optional[float] = None
    if preds:
        mints = sorted({d["mint"] for d in preds.values()})
        ask = mints if SOL_MINT in mints else mints + [SOL_MINT]
        t0 = time.time()
        try:
            resp = await client.get(DEX_URL.format(mint=",".join(ask)))
            resp.raise_for_status()
            pairs = resp.json().get("pairs") or []
            src_log("dexscreener", True, t0)
        except (httpx.HTTPError, ValueError):
            src_log("dexscreener", False, t0)
            if cmds:
                await redis_pipe(client, cmds)
            return 0  # try again next cycle, nothing is lost
        for m in mints:
            best[m] = pick_best_pair([p for p in pairs if (p.get("baseToken") or {}).get("address") == m], m)
        sp = pick_best_pair([p for p in pairs if (p.get("baseToken") or {}).get("address") == SOL_MINT], SOL_MINT)
        try:
            sol1 = float(sp.get("priceUsd")) if sp else None
        except (TypeError, ValueError):
            sol1 = None

    recent = []
    for pid, d in preds.items():
        cmds += [["ZREM", "due", pid], ["DEL", f"pred:{pid}"]]
        age = now - int(d.get("ts") or 0)
        if age > PRED_HORIZON_S * 3:
            continue  # judged far too late (server was asleep): would distort the stats
        p0, l0 = float(d.get("price") or 0), float(d.get("liq") or 0)
        pair = best.get(d["mint"])
        if pair is None:
            ret, liq_ratio = -100.0, 0.0
        else:
            p1 = float(pair.get("priceUsd") or 0)
            l1 = float((pair.get("liquidity") or {}).get("usd") or 0)
            ret = (p1 / p0 - 1) * 100 if p0 > 0 else 0.0
            liq_ratio = l1 / l0 if l0 > 0 else 1.0
        bad = ret <= BAD_RETURN_PCT or liq_ratio <= BAD_LIQ_RATIO
        # market background: how much did SOL itself move over the same window?
        sol0 = float(d.get("sol") or 0)
        sol_ret = (sol1 / sol0 - 1) * 100 if (sol1 and sol0 > 0) else None
        xret = ret - sol_ret if sol_ret is not None else None
        v, c = d.get("verdict", "?"), d.get("conf", "?")
        bucket = min(9, int(float(d.get("score") or 0)) // 10)
        day = time.strftime("%Y%m%d", time.gmtime(int(d.get("ts") or 0)))
        flags_t = [f for f in (d.get("flags") or "").split(",") if f in RISK_WEIGHTS]
        groups = ["all", f"v:{v}:{c}", f"rb:{bucket}", f"d:{day}"]
        groups += [f"f:{f}" for f in flags_t] + [f"fd:{f}:{day}" for f in flags_t]
        for g in groups:
            cmds.append(["HINCRBY", "st", f"{g}:n", 1])
            if bad:
                cmds.append(["HINCRBY", "st", f"{g}:bad", 1])
        cmds.append(["HINCRBYFLOAT", "st", f"v:{v}:{c}:ret", round(ret, 2)])
        if xret is not None:
            cmds += [["HINCRBYFLOAT", "st", f"v:{v}:{c}:xret", round(xret, 2)], ["HINCRBY", "st", f"v:{v}:{c}:xn", 1]]
        recent.append(json.dumps({"token": d.get("token"), "mint": d["mint"], "verdict": v, "risk_score": float(d.get("score") or 0),
                                  "return_pct": round(ret, 1), "sol_return_pct": round(sol_ret, 1) if sol_ret is not None else None,
                                  "excess_return_pct": round(xret, 1) if xret is not None else None,
                                  "bad_outcome": bad, "age_h": round(age / 3600, 1)}))
    for item in recent:
        cmds.append(["LPUSH", "recent", item])
    if recent:
        cmds.append(["LTRIM", "recent", 0, 49])
    if cmds:
        await redis_pipe(client, cmds)
    return len(ids)

# --- part5 ---
def rate(n: int, bad: int) -> Optional[float]:
    return round(bad / n * 100, 1) if n >= MIN_N_SHOW else None


def flag_stats(st: dict):
    """Per-flag outcome stats. The lift is ADJUSTED for the market background: each flagged token is compared
    with the bad-outcome rate of its own day (observed / expected), so a flag that merely shows up on crash
    days is not blamed for the crash. Falls back to the raw lift until 2+ days of cohort data exist."""
    n_all, bad_all = int(st.get("all:n", 0)), int(st.get("all:bad", 0))
    day_rate: Dict[str, float] = {}
    for k, v in st.items():
        if k.startswith("d:") and k.endswith(":n") and int(v) >= MIN_DAY_N:
            day = k[2:-2]
            day_rate[day] = int(st.get(f"d:{day}:bad", 0)) / int(v)
    fd: Dict[str, Dict[str, List[int]]] = {}  # flag -> day -> [n, bad]
    for k, v in st.items():
        if k.startswith("fd:") and (k.endswith(":n") or k.endswith(":bad")):
            parts = k.split(":")
            if len(parts) == 4:
                e = fd.setdefault(parts[1], {}).setdefault(parts[2], [0, 0])
                e[0 if parts[3] == "n" else 1] = int(v)
    base = bad_all / n_all if n_all else 0.0
    adjusted_ok = len(day_rate) >= 2
    rows = []
    for f, prior in RISK_WEIGHTS.items():
        n, bad = int(st.get(f"f:{f}:n", 0)), int(st.get(f"f:{f}:bad", 0))
        row: Dict[str, Any] = {"flag": f, "n": n, "bad_rate_pct": rate(n, bad), "lift_raw": None, "lift": None,
                               "market_adjusted": False, "prior_weight": prior, "suggested_weight": None, "blended_weight": prior}
        if n_all >= 100 and bad_all > 0 and n >= 30:
            raw = ((bad + base * 10) / (n + 10)) / base  # smoothed toward the base rate
            lift = raw
            if adjusted_ok:
                obs = exp = 0.0
                for day, (nf, bf) in fd.get(f, {}).items():
                    obs += bf
                    exp += nf * day_rate.get(day, base)
                lift = (obs + base * 10) / (exp + base * 10)
                row["market_adjusted"] = True
            sugg = max(0, min(40, round(25 * math.log(lift)))) if lift > 1 else 0
            alpha = min(0.5, n / 400)  # trust data more as n grows, never more than 50%
            row.update(lift_raw=round(raw, 2), lift=round(lift, 2), suggested_weight=sugg,
                       blended_weight=round((1 - alpha) * prior + alpha * sugg))
        rows.append(row)
    return rows, n_all


async def refresh_weights(client: httpx.AsyncClient):
    res = await redis_pipe(client, [["HGETALL", "st"]])
    if not res:
        return
    rows, n_all = flag_stats(to_dict(res[0]))
    new = dict(RISK_WEIGHTS)
    changed = False
    for r in rows:
        if r["suggested_weight"] is not None:
            new[r["flag"]] = r["blended_weight"]
            changed = True
    ACTIVE_WEIGHTS.clear()
    ACTIVE_WEIGHTS.update(new)
    _tune.update(on=changed, n=n_all)


async def stats_report(client: httpx.AsyncClient) -> dict:
    if not PRED_ENABLED:
        return {"enabled": False, "detail": "Track record store is not configured on this server."}
    if _stats_cache["data"] and time.time() - _stats_cache["ts"] < STATS_TTL:
        return _stats_cache["data"]
    res = await redis_pipe(client, [["HGETALL", "st"], ["ZCARD", "due"], ["LRANGE", "recent", 0, 19]])
    if res is None:
        return {"enabled": True, "available": False, "detail": "Stats store unavailable, retry shortly"}
    st = to_dict(res[0])

    def grp(prefix: str) -> dict:
        n, bad = int(st.get(f"{prefix}:n", 0)), int(st.get(f"{prefix}:bad", 0))
        ret = float(st.get(f"{prefix}:ret", 0))
        xn, xr = int(st.get(f"{prefix}:xn", 0)), float(st.get(f"{prefix}:xret", 0))
        return {"n": n, "bad_outcome_rate_pct": rate(n, bad),
                "avg_return_pct": round(ret / n, 1) if n >= MIN_N_SHOW else None,
                "avg_excess_return_pct": round(xr / xn, 1) if xn >= MIN_N_SHOW else None}

    rows, n_all = flag_stats(st)
    by_verdict = {v: {c: grp(f"v:{v}:{c}") for c in ("full", "market_only")} for v in ("ok", "caution", "avoid")}
    ok_r, av_r = by_verdict["ok"]["full"]["bad_outcome_rate_pct"], by_verdict["avoid"]["full"]["bad_outcome_rate_pct"]
    recent = []
    for x in res[2] or []:
        try:
            recent.append(json.loads(x))
        except Exception:
            pass
    hours = round(PRED_HORIZON_S / 3600, 1)
    cohorts = []
    for k in sorted((k for k in st if k.startswith("d:") and k.endswith(":n")), reverse=True)[:14]:
        day, n = k[2:-2], int(st[k])
        cohorts.append({"day": day, "n": n,
                        "bad_outcome_rate_pct": round(int(st.get(f"d:{day}:bad", 0)) / n * 100, 1) if n >= MIN_DAY_N else None})
    data = {
        "enabled": True, "available": True, "horizon_hours": hours, "resolved": n_all, "pending": int(res[1] or 0),
        "bad_outcome_definition": f"price down {abs(BAD_RETURN_PCT):.0f}%+ or liquidity down {round((1 - BAD_LIQ_RATIO) * 100)}%+ "
                                  f"or pair gone, measured about {hours}h after the verdict",
        "by_verdict": by_verdict,
        "avoid_vs_ok_gap_pts": round(av_r - ok_r, 1) if ok_r is not None and av_r is not None else None,
        "by_risk_bucket": [{"risk_score_range": f"{b * 10}-{b * 10 + 9}", **grp(f"rb:{b}")} for b in range(10)],
        "flags": rows,
        "market_adjustment": {
            "method": "flag lift = observed bad outcomes / bad outcomes expected from each day's overall rate; "
                      "avg_excess_return_pct = token return minus SOL return over the same window",
            "active": any(r["market_adjusted"] for r in rows),
            "days_with_cohort_data": len([c for c in cohorts if c["bad_outcome_rate_pct"] is not None]),
        },
        "daily_background": cohorts,
        "scoring": "tuned" if _tune["on"] else "static",
        "recent_outcomes": recent,
        "caveats": [
            "Only tokens that people query are measured: this is not a random sample of all tokens.",
            "Bad outcomes can come from ordinary market moves, not only rugs. Flags overlap, so per-flag numbers are not causal.",
            f"Rates are hidden until there are at least {MIN_N_SHOW} samples.",
            "Flag lifts are corrected for each day's overall bad-outcome rate once 2+ days of data exist; before that they are raw.",
            "Heuristic risk scoring, not financial advice.",
        ],
    }
    _stats_cache.update(ts=time.time(), data=data)
    return data


async def resolver_loop(app: FastAPI):
    last_tune = 0.0
    await asyncio.sleep(20)
    while True:
        busy = False
        try:
            busy = (await resolve_due(app.state.client)) >= RESOLVE_BATCH
            if AUTO_TUNE and time.time() - last_tune > 1800:
                await refresh_weights(app.state.client)
                last_tune = time.time()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(5 if busy else 300)


# ---------- exit check (can you sell, and at what cost?) ----------
JUP_URL = "https://api.jup.ag/swap/v1/quote"
JUP_KEY = os.getenv("JUPITER_API_KEY")  # optional free key from portal.jup.ag (higher rate limit)
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
JUP_LIMIT = 50 if JUP_KEY else 25  # quotes per minute, shared by everyone (keyless tier is ~0.5 req/s)
EXIT_CACHE_TTL = 60
MAX_EXIT_USD = 50_000
DEFAULT_EXIT_SIZES = [100.0, 1000.0]
VERDICT_RANK = {"ok": 0, "caution": 1, "avoid": 2}
EXIT_NOTE = (
    "Based on a Jupiter quote vs the DexScreener market price, so the loss includes fees, price impact and "
    "price differences. A quote does NOT prove a real sell will succeed: it cannot detect every sell-blocking "
    "mechanism. Treat it as one signal, not a guarantee."
)


def clean_sizes(vals) -> List[float]:
    if not vals:
        return list(DEFAULT_EXIT_SIZES)
    out: List[float] = []
    for v in vals:
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="sizes must be numbers in USD, e.g. 100,1000")
        if not (1 <= f <= MAX_EXIT_USD):
            raise HTTPException(status_code=400, detail=f"each size must be between 1 and {MAX_EXIT_USD} USD")
        out.append(f)
    if len(out) > 3:
        raise HTTPException(status_code=400, detail="Use at most 3 sizes")
    return out


def parse_sizes(text: Optional[str]) -> List[float]:
    return clean_sizes([x for x in (text or "").split(",") if x.strip()])


async def _jup_quote_raw(client: httpx.AsyncClient, mint: str, raw_amount: int) -> dict:
    """status: ok | no_route | unavailable. Never raises."""
    headers = {"x-api-key": JUP_KEY} if JUP_KEY else {}
    params = {"inputMint": mint, "outputMint": USDC_MINT, "amount": str(raw_amount),
              "slippageBps": "100", "restrictIntermediateTokens": "true"}
    try:
        resp = await client.get(JUP_URL, params=params, headers=headers)
    except httpx.HTTPError:
        return {"status": "unavailable"}
    if resp.status_code == 200:
        try:
            j = resp.json()
            out = int(j["outAmount"])
        except (ValueError, KeyError, TypeError):
            return {"status": "unavailable"}
        if out <= 0:
            return {"status": "no_route"}
        labels = []
        for step in j.get("routePlan") or []:
            lab = (step.get("swapInfo") or {}).get("label")
            if lab and lab not in labels:
                labels.append(lab)
        return {"status": "ok", "out_usd": out / 1e6, "impact_raw": j.get("priceImpactPct"), "routes": labels[:3]}
    if resp.status_code in (400, 404):
        txt = resp.text.lower()
        if "route" in txt or "tradable" in txt or "tradeable" in txt:
            return {"status": "no_route"}
    return {"status": "unavailable", "http_status": resp.status_code}


async def jup_quote(client: httpx.AsyncClient, mint: str, raw_amount: int) -> dict:
    t0 = time.time()
    q = await _jup_quote_raw(client, mint, raw_amount)
    src_log("jupiter", q["status"] != "unavailable", t0)
    return q


async def exit_check(client: httpx.AsyncClient, mint: str, sizes: List[float], sig: dict) -> dict:
    key = f"exit:{mint}:{','.join(str(x) for x in sizes)}"
    cached = cache_get(key, EXIT_CACHE_TTL)
    if cached:
        return cached
    price = float(sig.get("price_usd") or 0)
    dec = (sig.get("security") or {}).get("decimals")
    if dec is None:
        raw = await soft(get_security(client, mint), SECONDARY_TIMEOUT)
        dec = (raw or {}).get("decimals")
    if price <= 0 or dec is None:
        return {"available": False, "reason": "price or token decimals unavailable, retry shortly", "note": EXIT_NOTE}

    levels = []
    for usd in sizes:
        if rate_limited("__jup__", JUP_LIMIT):
            levels.append({"size_usd": usd, "status": "rate_limited"})
            continue
        q = await jup_quote(client, mint, int(usd / price * 10 ** int(dec)))
        lvl: Dict[str, Any] = {"size_usd": usd, "status": q["status"]}
        if q["status"] == "ok":
            loss = max(0.0, (1 - q["out_usd"] / usd) * 100)
            lvl.update(sell_receives_usd=round(q["out_usd"], 2), loss_vs_market_pct=round(loss, 2),
                       jupiter_price_impact_raw=q.get("impact_raw"), routes=q.get("routes"))
        levels.append(lvl)

    ok = [l for l in levels if l["status"] == "ok"]
    no_route = any(l["status"] == "no_route" for l in levels)
    if not ok and not no_route:
        return {"available": False, "levels": levels, "note": EXIT_NOTE,
                "reason": "Jupiter quote unavailable or rate limited, retry in a minute"}

    reasons: List[str] = []
    if no_route:
        grade, verdict = "no_route", "avoid"
        reasons.append("No sell route found on Jupiter")
    else:
        worst = max(l["loss_vs_market_pct"] for l in ok)
        grade = "good" if worst < 3 else "fair" if worst < 10 else "poor" if worst < 25 else "very_poor"
        verdict = {"good": "ok", "fair": "ok", "poor": "caution", "very_poor": "avoid"}[grade]
        if grade in ("poor", "very_poor"):
            reasons.append(f"Selling would lose about {worst:.0f}% vs market price (fees + price impact)")
    result = {"available": True, "exit_route_found": not no_route, "grade": grade, "exit_verdict": verdict,
              "levels": levels, "reasons": reasons, "note": EXIT_NOTE}
    cache_set(key, result)
    return result


async def build_exit_report(client: httpx.AsyncClient, mint: str, sizes: List[float]) -> dict:
    sig, _ = await build_signal(client, mint, True)
    ex = await exit_check(client, mint, sizes, sig)
    base = sig["verdict"]
    combined = base
    if ex.get("available") and VERDICT_RANK[ex["exit_verdict"]] > VERDICT_RANK[base]:
        combined = ex["exit_verdict"]
    reasons = list(sig.get("verdict_reasons") or []) + list(ex.get("reasons") or [])
    if ex.get("available"):
        ok = [l for l in ex["levels"] if l["status"] == "ok"]
        big = max(ok, key=lambda l: l["size_usd"]) if ok else None
        sell = (f"Selling ${big['size_usd']:,.0f} returns about ${big['sell_receives_usd']:,.2f} "
                f"({big['loss_vs_market_pct']}% below market)." if big else "No sell route found.")
    else:
        sell = "Exit check unavailable right now."
    mkt_reasons = "; ".join((sig.get("verdict_reasons") or [])[:2])
    mkt = f" ({mkt_reasons})" if mkt_reasons else ""
    return {
        "mint": mint, "token": sig.get("token"), "combined_verdict": combined, "market_verdict": base,
        "verdict_confidence": sig.get("verdict_confidence"), "reasons": reasons, "exit": ex,
        "summary": f"{sig.get('token') or '?'}: {combined.upper()}. {sell} Market verdict: {base}{mkt}.",
        "timestamp": int(time.time()),
    }

# --- part6 ---
# ---------- pages ----------
HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVibex402 - Solana token data API for AI agents</title>
<meta name="description" content="Free Solana token data API for AI agents and bots. No API key, instant JSON.">
<style>
:root{--bg:#070b12;--card:rgba(18,25,35,.8);--line:rgba(34,48,66,.8);--text:#e8eef6;--muted:#8b9bb4;--a:#14f195;--b:#9945ff;--danger:#ff4d6d;--warn:#ffb020}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:system-ui,sans-serif;line-height:1.55;min-height:100vh;background-image:radial-gradient(ellipse 80% 50% at 20% -10%,rgba(153,69,255,.18),transparent),radial-gradient(ellipse 60% 40% at 90% 10%,rgba(20,241,149,.12),transparent)}
.wrap{max-width:720px;margin:0 auto;padding:36px 18px 80px}
.brand{font-size:2.5rem;font-weight:800;background:linear-gradient(120deg,var(--b),var(--a));-webkit-background-clip:text;background-clip:text;color:transparent}
.tag{color:var(--muted);margin:6px 0 28px;font-size:1.05rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:22px;margin-bottom:20px}
h2{font-size:1.15rem;margin:28px 0 12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.grid .item{background:rgba(13,17,23,.6);border:1px solid var(--line);border-radius:12px;padding:14px 12px;font-size:.9rem;color:var(--muted)}
input[type=text]{width:100%;padding:14px 16px;border-radius:12px;border:1px solid var(--line);background:rgba(13,17,23,.8);color:var(--text);font-size:.95rem;outline:none}
input:focus{border-color:var(--b)}
button{background:linear-gradient(90deg,var(--b),var(--a));color:#06110b;border:0;padding:13px 22px;border-radius:12px;font-weight:700;cursor:pointer;font-size:.95rem}
button:disabled{opacity:.6}
.muted{color:var(--muted);font-size:.88rem}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;font-size:.75rem;font-weight:600;margin:3px 4px 3px 0}
.badge.green{background:rgba(20,241,149,.15);color:var(--a)}
.badge.purple{background:rgba(153,69,255,.2);color:#c084fc}
.badge.red{background:rgba(255,77,109,.15);color:var(--danger)}
.badge.yellow{background:rgba(255,176,32,.15);color:var(--warn)}
.result-box{display:none;margin-top:18px}
.result-box.show{display:block}
.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:14px 0}
.stat{background:rgba(13,17,23,.7);border-radius:12px;padding:12px;border:1px solid var(--line)}
.stat .label{font-size:.75rem;color:var(--muted)}
.stat .value{font-size:1.1rem;font-weight:700;margin-top:2px}
.loading{display:none;text-align:center;padding:20px;color:var(--muted)}
.loading.show{display:block}
.spinner{width:28px;height:28px;border:3px solid var(--line);border-top-color:var(--a);border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 10px}
@keyframes spin{to{transform:rotate(360deg)}}
a{color:var(--a);text-decoration:none}
pre{margin:0;background:#0d1117;padding:14px;border-radius:12px;overflow:auto;font-size:.82rem}
footer{margin-top:40px;text-align:center;color:var(--muted);font-size:.85rem}
</style>
</head>
<body>
<div class="wrap">
<h1 class="brand">TVibex402</h1>
<p class="tag">Free Solana token data API for AI agents &amp; bots</p>
<div class="card">
<p style="font-weight:600;margin-bottom:12px">Try it live</p>
<input type="text" id="mint" placeholder="Paste Solana token mint address" autocomplete="off" spellcheck="false">
<div style="margin-top:12px"><button id="btn" onclick="getSignal()">Get Signal</button></div>
<p class="muted" style="margin-top:12px">No API key &bull; No signup &bull; Instant JSON</p>
<div class="loading" id="loading"><div class="spinner"></div>Fetching live data...</div>
<div class="result-box" id="result"></div>
</div>
<h2>What you get</h2>
<div class="grid">
<div class="item">Price, FDV, Market Cap</div>
<div class="item">Price change 5m / 1h / 6h / 24h</div>
<div class="item">Liquidity + Pair age</div>
<div class="item">Volume 5m / 1h / 6h</div>
<div class="item">Buy / Sell + Buy pressure</div>
<div class="item">Volume spike + Flags + Risk score</div>
<div class="item">Mint/Freeze authority + Holder concentration</div>
<div class="item">LP locked/burned % (via RugCheck)</div>
<div class="item">Exit check: sell cost per size (via Jupiter)</div>
<div class="item">Verdict + plain-English summary</div>
</div>
<h2>Endpoint for Agents</h2>
<div class="card" style="padding:16px">
<pre>GET /signal?mint=TOKEN_MINT_ADDRESS
GET /exit?mint=TOKEN_MINT_ADDRESS&amp;sizes=100,1000</pre>
<p class="muted" style="margin-top:10px">Example: <a href="/signal?mint=So11111111111111111111111111111111111111112">/signal?mint=So111...112</a></p>
<p class="muted" style="margin-top:6px">Docs: <a href="/docs">/docs</a> &bull; <a href="/llms.txt">/llms.txt</a> &bull; <a href="/stats">/stats</a> &bull; <a href="/metrics">/metrics</a> &bull; Limit: 30 req/min per IP</p>
<p class="muted" style="margin-top:6px">MCP for Claude &amp; agents: add this site's URL + <b>/mcp</b> as a remote MCP server</p>
</div>
<footer>TVibex402 &bull; Built for AI Agents<br>Data from DexScreener. Not financial advice. Risk score is a heuristic (market + on-chain), not a security audit. LP lock % is sourced from RugCheck.</footer>
</div>
<script>
const esc=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function getSignal(){
const mint=document.getElementById('mint').value.trim();
if(!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(mint)){alert('Please paste a valid Solana mint address');return}
const btn=document.getElementById('btn'),loading=document.getElementById('loading'),result=document.getElementById('result');
btn.disabled=true;loading.classList.add('show');result.classList.remove('show');result.innerHTML='';
try{
const res=await fetch('/signal?mint='+encodeURIComponent(mint));
const data=await res.json();
if(!res.ok){result.innerHTML='<div style="color:#ff4d6d">Error: '+esc(data.detail||'Failed')+'</div>'}
else{
const flags=(data.flags||[]).map(f=>{
let cls='purple';
if(f.includes('buying')||f.includes('momentum'))cls='green';
if(f.includes('selling')||f.includes('dump')||f.includes('low')||f.includes('active')||f.includes('not_locked')||f.includes('concentration')||f.includes('dominant')||f.includes('risky'))cls='red';
if(f.includes('new')||f.includes('spike')||f.includes('partially'))cls='yellow';
return '<span class="badge '+cls+'">'+esc(f)+'</span>';
}).join('');
const s=data.security||{};
const yn=v=>v===true?'Revoked':v===false?'ACTIVE':'?';
const secTxt=esc(yn(s.mint_authority_revoked))+' / '+esc(yn(s.freeze_authority_revoked));
const top10=s.top10_holders_pct!=null?esc(s.top10_holders_pct)+'%':'-';
const vcol=data.verdict==='avoid'?'var(--danger)':data.verdict==='caution'?'var(--warn)':'var(--a)';
const lp=s.lp_locked_pct!=null?esc(s.lp_locked_pct)+'%':'-';
const top1=s.top1_holder_pct!=null?esc(s.top1_holder_pct)+'%':'-';
const riskColor=data.risk_level==='high'?'var(--danger)':data.risk_level==='medium'?'var(--warn)':'var(--a)';
result.innerHTML=`<div style="margin-top:8px">
<div style="display:flex;justify-content:space-between;align-items:center">
<div><div style="font-size:1.4rem;font-weight:700">${esc(data.token)}</div>
<div class="muted" style="font-size:.85rem">${esc(data.name)}</div></div>
<div style="text-align:right"><div style="font-size:1.3rem;font-weight:700">$${esc(data.price_usd||'-')}</div>
<div class="muted" style="font-size:.8rem">${esc(data.dex)}</div></div></div>
<div class="stat-grid">
<div class="stat"><div class="label">Liquidity</div><div class="value">$${esc((data.liquidity_usd||0).toLocaleString())}</div></div>
<div class="stat"><div class="label">Buy Pressure 5m</div><div class="value">${data.buy_pressure_5m!=null?(data.buy_pressure_5m*100).toFixed(1)+'%':'-'}</div></div>
<div class="stat"><div class="label">Volume 5m</div><div class="value">$${esc((data.volume_5m||0).toLocaleString())}</div></div>
<div class="stat"><div class="label">Volume Spike</div><div class="value">${data.volume_spike_ratio_5m!=null?esc(data.volume_spike_ratio_5m)+'x':'-'}</div></div>
<div class="stat"><div class="label">Verdict</div><div class="value" style="color:${vcol}">${esc((data.verdict||'-').toUpperCase())}</div></div>
<div class="stat"><div class="label">Risk Score</div><div class="value" style="color:${riskColor}">${esc(data.risk_score)} (${esc(data.risk_level)})</div></div>
<div class="stat"><div class="label">Mint / Freeze authority</div><div class="value" style="font-size:.95rem">${secTxt}</div></div>
<div class="stat"><div class="label">Top 10 Holders</div><div class="value">${top10}</div></div>
<div class="stat"><div class="label">Top Holder</div><div class="value">${top1}</div></div>
<div class="stat"><div class="label">LP Locked/Burned</div><div class="value">${lp}</div></div>
</div>
<div style="margin:12px 0 6px;font-size:.85rem;color:var(--muted)">Flags</div>
<div>${flags||'<span class="muted">None</span>'}</div>
<div class="muted" style="margin-top:8px">${esc((data.verdict_reasons||[]).join(' • '))}</div>
${data.partial?'<p class="muted" style="margin-top:8px">Some on-chain data was slow, so it is missing here.</p>':''}${data.stale?'<p class="muted" style="margin-top:8px">Showing cached data (source temporarily down).</p>':''}</div>`;
}
result.classList.add('show');
}catch(e){result.innerHTML='<p style="color:#ff4d6d">Network error</p>';result.classList.add('show')}
loading.classList.remove('show');btn.disabled=false;
}
document.getElementById('mint').addEventListener('keypress',e=>{if(e.key==='Enter')getSignal()});
</script>
</body>
</html>"""

LLMS_TXT = """# TVibex402
> Free Solana token data API for AI agents and bots. No API key. Data from DexScreener. Not financial advice.

## Endpoint
GET /signal?mint=<SOLANA_TOKEN_MINT>
Returns JSON: price, FDV, market cap, price change (5m/1h/6h/24h), liquidity, volume, buy/sell counts,
buy pressure, volume spike ratio, pair age, flags, risk_score (0-100 heuristic), risk_level, and a `security` object:
mint_authority_revoked, freeze_authority_revoked, token_program, risky_extensions, top1_holder_pct,
top10_holders_pct (excluding liquidity pools/burn), liquidity_pool_pct, top_holders.
Add &security=false to skip on-chain checks (faster).
verdict: "ok" | "caution" | "avoid" plus verdict_reasons (heuristic, not advice). verdict_confidence is "full" or "market_only".
Established tokens (liquidity >= $1M, pair > 30 days) are not marked "avoid" only for active authorities (e.g. stablecoins).
partial=true: a slow on-chain source timed out, market data is still valid. stale=true: upstream was down, a cached copy (stale_age_s old) is returned.
lp_locked_pct, rugcheck_score and rugcheck_risks come from RugCheck's public API (LP locked or burned %).
risk_score is a heuristic, not a guarantee.

## Batch
GET /signals?mints=A,B,C  (max 10) -> {count, summary, results:[...], errors:[...], filtered_out}
Smart batch: one shared market-data request, ranked (safety_rank 1 = lowest risk), summary.headline is one sentence.
Options: sort=input|safest|riskiest, only=ok,caution, max_risk=40, top=3, view=full|compact, security=false.
Rate-limit cost = tokens that needed fetching (cached ones are free). Slow tokens appear in errors with status 504.

## Data quality
Every signal has data_quality: freshness (fresh|cached|stale), age_s, completeness (full|partial|market_only),
missing (e.g. ["solana_rpc"]) and data_confidence 0-1. data_confidence says how complete and fresh the data is.
It is NOT the probability that the verdict is right (see /stats for measured accuracy).
When data sources are down you get HTTP 503 with Retry-After, retry_after_s and per-source status.
Every response carries X-API-Version and X-Response-Time. GET /metrics shows request counts, cache hit rate,
partial rate and latency (p50/p95).

## Track record
GET /stats -> how often verdicts were right: every verdict is judged ~24h later (bad outcome = price -50% or liquidity -70%
or pair gone). Shows rates per verdict, per risk bucket and per flag, recent outcomes and caveats. Rates are null until n >= 20. Flag lifts are adjusted for each day's market background (daily_background),
and avg_excess_return_pct is relative to SOL over the same window.

## Exit check
GET /exit?mint=<MINT>&sizes=100,1000  (1-3 sizes in USD, default 100,1000)
Returns combined_verdict (worst of market verdict and exit verdict), exit.levels[] with loss_vs_market_pct,
exit.grade (good|fair|poor|very_poor|no_route) and a summary. A quote is not proof a sell will succeed.

## Reference
verdict: ok | caution | avoid. Every signal also has `summary` (one sentence) and `suggested_next`.
Risk flags: mint_authority_active, freeze_authority_active, risky_token_extension, lp_not_locked, lp_partially_locked,
dump_risk, extreme_holder_concentration, high_holder_concentration, dominant_holder, very_low_liquidity, low_liquidity,
brand_new_pair, very_new_pair, new_pair, extreme_turnover, high_turnover, heavy_selling, extreme_volume_spike.
Info flags: volume_spike, heavy_buying, strong_momentum, high_activity.
`sources` shows which data sources answered (ok|missing). `scoring` is static, or tuned if the server learned weights from outcomes.

## MCP
Remote MCP server (Streamable HTTP, stateless, no auth): POST /mcp
Tools: get_token_signal (full data), check_token_risk (compact verdict), check_tokens_batch (max 10, ranked safest first, filters sort/only/max_risk/top),
check_exit (can you sell? price impact per size via Jupiter),
get_track_record (measured accuracy of past verdicts).

## Other
GET /health  - service status
GET /docs    - OpenAPI docs
Rate limit: 30 requests/minute per IP (HTTP 429 with Retry-After).
Cache: results cached up to 30 seconds (X-Cache: HIT/MISS/STALE).
"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home():
    return HOME_HTML


@app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
async def llms():
    return LLMS_TXT


@app.get("/demo")
async def demo():
    return {"token": "SOL", "price_usd": "119.54", "sample": True, "note": "Static sample"}


def too_many(wait: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=f"Rate limit exceeded. Retry in {wait}s",
        headers={"Retry-After": str(wait)},
    )


@app.get("/signal", tags=["signals"], summary="Market + on-chain data and a verdict for one token")
async def signal(
    request: Request,
    mint: str = Query(..., min_length=1, max_length=64),
    security: bool = Query(True, description="Include on-chain checks: authorities, holders, LP lock"),
):
    mint = mint.strip()
    if not MINT_RE.match(mint):
        raise HTTPException(status_code=400, detail="Invalid Solana token address")
    wait = rate_limited(client_ip(request))
    if wait:
        raise too_many(wait)
    result, status = await build_signal(request.app.state.client, mint, security)
    return JSONResponse(content=result, headers={"X-Cache": status, "Cache-Control": "public, max-age=10"})


@app.get("/signals", tags=["signals"], summary="Smart batch: up to 10 tokens, ranked and filtered",
         description="One shared market-data request for everything not cached; the rate-limit cost is the number of tokens "
                     "that needed fetching. Slow tokens are listed in `errors` (status 504) instead of delaying the batch. "
                     "Each result has `safety_rank` (1 = lowest risk).")
async def signals(
    request: Request,
    mints: str = Query(..., max_length=600, description=f"Comma-separated mints, max {MAX_BATCH}"),
    security: bool = Query(True, description="Include on-chain checks"),
    sort: str = Query("input", description="input | safest | riskiest"),
    only: Optional[str] = Query(None, description="Keep only these verdicts, e.g. ok,caution"),
    max_risk: Optional[int] = Query(None, ge=0, le=100, description="Keep only risk_score <= this"),
    top: Optional[int] = Query(None, ge=1, le=MAX_BATCH, description="Keep only the first N after sorting"),
    view: str = Query("full", description="full | compact (decision fields only)"),
):
    data = await build_batch(request.app.state.client, mints.split(","), security, sort=sort, only=only,
                             max_risk=max_risk, top=top, view=view,
                             charge=lambda cost: rate_limited(client_ip(request), cost=cost))
    return JSONResponse(content=data, headers={"Cache-Control": "public, max-age=10"})


@app.get("/exit", tags=["decision"], summary="Can you sell, and at what cost? (Jupiter quote, not proof)")
async def exit_route(
    request: Request,
    mint: str = Query(..., min_length=1, max_length=64),
    sizes: Optional[str] = Query(None, description="Sell sizes in USD, comma separated, max 3. Default 100,1000"),
):
    mint = mint.strip()
    if not MINT_RE.match(mint):
        raise HTTPException(status_code=400, detail="Invalid Solana token address")
    size_list = parse_sizes(sizes)
    wait = rate_limited(client_ip(request), cost=2)
    if wait:
        raise too_many(wait)
    report = await build_exit_report(request.app.state.client, mint, size_list)
    return JSONResponse(content=report, headers={"Cache-Control": "public, max-age=10"})


@app.get("/stats", tags=["trust"], summary="Measured accuracy of past verdicts")
async def stats_route(request: Request):
    wait = rate_limited(client_ip(request))
    if wait:
        raise too_many(wait)
    report = await stats_report(request.app.state.client)
    return JSONResponse(content=report, headers={"Cache-Control": "public, max-age=60"})


@app.get("/metrics", tags=["trust"], summary="Request counts, cache hit rate, latency, source health")
async def metrics_route():
    return JSONResponse(content=metrics_report(), headers={"Cache-Control": "no-store"})


@app.get("/health")
async def health():
    return {"status": "ok", "version": VERSION, "cache_size": len(_cache), "rpc": "custom" if os.getenv("SOLANA_RPC_URL") else "public", "mcp": mcp_server is not None, "mcp_error": mcp_error, "jupiter_key": bool(JUP_KEY),
            "uptime_s": int(time.time() - _m["started"]), "track_record": PRED_ENABLED, "auto_tune": AUTO_TUNE, "sources": src_status()}

# --- part8 ---
# ---------- v2.1: honest verdicts, decision object, smarter ranking ----------
# This file only ADDS or REPLACES functions defined in part1-part6 (same shared namespace).
VERSION = "2.1.0"
app.version = VERSION
app.openapi_schema = None  # force /docs to rebuild with the new version

# Assets where "rug" checks make no sense (deep, regulated or native markets). Matched by exact mint address.
MAJOR_ASSETS = {
    "So11111111111111111111111111111111111111112": "SOL (wrapped)",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
}
# Flags about authorities, holders and LP lock: right for memecoins, noise for majors/established tokens
RUG_STYLE_FLAGS = {"mint_authority_active", "freeze_authority_active", "extreme_holder_concentration",
                   "high_holder_concentration", "dominant_holder", "lp_not_locked", "lp_partially_locked"}


def asset_class(r: dict) -> str:
    """major | established | standard"""
    if r.get("mint") in MAJOR_ASSETS:
        return "major"
    if (r.get("liquidity_usd") or 0) >= 1_000_000 and (r.get("pair_age_minutes") or 0) >= 43200:
        return "established"
    return "standard"


def rank_key(r: dict):
    """Lower = safer. Unknown data is not rewarded: missing sources add up to 20 points."""
    conf = (r.get("data_quality") or {}).get("data_confidence")
    penalty = round((1 - (conf if conf is not None else 1.0)) * 20)
    return (r["risk_score"] + penalty, -(r.get("liquidity_usd") or 0))


def finalize_risk(result: dict, onchain: bool):
    """Heuristic 0-100 score. Rug-style flags are not scored for majors and established tokens."""
    cls = asset_class(result)
    result["asset_class"] = cls
    skip = RUG_STYLE_FLAGS if cls in ("major", "established") else set()
    score = min(100, sum(ACTIVE_WEIGHTS.get(f, 0) for f in result["flags"] if f not in skip))
    result["scoring"] = "tuned" if _tune["on"] else "static"
    result["risk_score"] = score
    result["risk_level"] = "low" if score < 25 else "medium" if score < 50 else "high"
    result["risk_basis"] = "market+onchain" if onchain else "market"
    shown = sorted(skip & set(result["flags"]))
    if shown:
        result["flags_not_scored"] = shown


def _positives(r: dict) -> list:
    out, sec = [], r.get("security") or {}
    if sec.get("mint_authority_revoked") is True:
        out.append("Mint authority revoked")
    if sec.get("freeze_authority_revoked") is True:
        out.append("Freeze authority revoked")
    lp = sec.get("lp_locked_pct")
    if lp is not None and lp >= 80:
        out.append(f"{lp:.0f}% of liquidity locked or burned")
    t10 = sec.get("top10_holders_pct")
    if t10 is not None and t10 < 30:
        out.append(f"Top 10 holders own only {t10:.0f}%")
    if (r.get("liquidity_usd") or 0) >= 250_000:
        out.append(f"Liquidity ${r['liquidity_usd']:,.0f}")
    if (r.get("pair_age_minutes") or 0) >= 10080:
        out.append("Pair older than 7 days")
    return out


def add_verdict(result: dict):
    """ok | caution | avoid plus a decision object. Heuristic, not advice."""
    flags = set(result["flags"])
    cls = result.get("asset_class") or asset_class(result)
    ignore = RUG_STYLE_FLAGS if cls == "major" else (RUG_STYLE_FLAGS - AUTHORITY_FLAGS) if cls == "established" else set()
    avoid = [f for f in AVOID_FLAGS if f in flags and f not in ignore and not (cls == "established" and f in AUTHORITY_FLAGS)]
    caution = [f for f in CAUTION_FLAGS if f in flags and f not in ignore]
    if cls == "established":
        caution = [f for f in sorted(AUTHORITY_FLAGS) if f in flags] + caution
    score = result["risk_score"]
    verdict = "avoid" if avoid or score >= 50 else "caution" if caution or score >= 25 else "ok"
    result["verdict"] = verdict
    result["verdict_reasons"] = [REASONS[f] for f in avoid + caution]
    result["verdict_confidence"] = "full" if result.get("security") and not result.get("partial") else "market_only"
    top = "; ".join(result["verdict_reasons"][:3]) or ("major asset, rug-style checks do not apply" if cls == "major" else "no major red flags found")
    result["summary"] = (
        f"{result.get('token') or '?'}: {verdict.upper()} ({result['verdict_confidence']} data). "
        f"{top}. Liquidity ${result['liquidity_usd']:,.0f}, risk {score}/100."
    )
    nxt = []
    if result.get("partial"):
        miss = [k for k, v in (result.get("sources") or {}).items() if v != "ok"]
        nxt.append("retry in a few seconds for full on-chain data" + (f" (missing: {', '.join(miss)})" if miss else ""))
    if verdict != "avoid":
        nxt.append("run the exit check (GET /exit or MCP check_exit) before sizing a trade")
    result["suggested_next"] = nxt
    blockers = [REASONS[f] for f in avoid]
    if not avoid and score >= 50:
        blockers.append(f"Risk score {score}/100 is at or above the avoid threshold (50)")
    note = ("Major asset: rug-style checks (authorities, holders, LP lock) do not apply." if cls == "major" else
            "Established token: holder and LP flags are shown but not scored." if cls == "established" else None)
    decision = {
        "verdict": verdict,
        "blockers": blockers,
        "cautions": [REASONS[f] for f in caution] + ([f"Risk score {score}/100"] if verdict == "caution" and not caution else []),
        "positives": _positives(result),
        "unknowns": [],          # filled in with_quality, which knows about missing data
        "next_checks": nxt,
        "valid_for_s": 30,
        "asset_class": cls,
        "disclaimer": "Heuristic output, not financial advice.",
    }
    if note:
        decision["note"] = note
    result["decision"] = decision


_with_quality_v20 = with_quality


def with_quality(result: dict, status: str, security: bool) -> dict:
    out = _with_quality_v20(result, status, security)
    dq, d = out["data_quality"], dict(out.get("decision") or {})
    if d:
        unknown = [f"{m} did not answer" for m in dq["missing"]]
        if not security:
            unknown.append("On-chain checks were skipped (security=false)")
        if status == "STALE":
            unknown.append(f"Data is {dq['age_s']}s old because the live source was down")
        if d.get("verdict") != "avoid":
            unknown.append("Exit cost not checked yet (use check_exit)")
        d.update(unknowns=unknown, confidence=dq["data_confidence"], freshness=dq["freshness"])
        out["decision"] = d
    return out


_compact_v20 = compact_signal


def compact_signal(r: dict) -> dict:
    out = _compact_v20(r)
    if "asset_class" in r:
        out["asset_class"] = r["asset_class"]
    d = r.get("decision")
    if d:
        out["decision"] = {k: d[k] for k in ("blockers", "unknowns", "confidence", "valid_for_s") if k in d}
    return out


async def build_batch(client: httpx.AsyncClient, raw_mints: List[str], security: bool, *, sort: str = "input",
                      only: Optional[str] = None, max_risk: Optional[int] = None, top: Optional[int] = None,
                      view: str = "full", charge=None) -> dict:
    """Smart batch: ONE shared DexScreener request for everything not cached, cost = only what needs fetching,
    an overall deadline (slow tokens are reported, not waited for), ranking, filters and a one-line summary."""
    ids = list(dict.fromkeys(m.strip() for m in raw_mints if m and m.strip()))
    if not ids:
        raise HTTPException(status_code=400, detail="Provide at least one mint")
    if len(ids) > MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"Max {MAX_BATCH} mints per request")
    if sort not in ("input", "safest", "riskiest"):
        raise HTTPException(status_code=400, detail="sort must be input, safest or riskiest")
    if view not in ("full", "compact"):
        raise HTTPException(status_code=400, detail="view must be full or compact")
    only_set = None
    if only:
        only_set = {x.strip().lower() for x in only.split(",") if x.strip()}
        if not only_set or not only_set <= {"ok", "caution", "avoid"}:
            raise HTTPException(status_code=400, detail="only must be a comma list of: ok, caution, avoid")

    errors: List[dict] = []
    valid: List[str] = []
    for m in ids:
        if MINT_RE.match(m):
            valid.append(m)
        else:
            errors.append({"mint": m, "status": 400, "detail": "Invalid Solana token address"})

    # what actually needs upstream work? (fresh cache hits are free)
    todo = []
    for m in valid:
        hit = cache_peek(m if security else m + ":nosec")
        if not (hit and hit[0] <= (PARTIAL_TTL if hit[1].get("partial") else CACHE_TTL)):
            todo.append(m)
    wait = charge(max(1, len(todo))) if charge else 0
    if wait:
        raise too_many(wait)

    prefetched: Dict[str, dict] = {}
    for i in range(0, len(todo), 30):
        if rate_limited("__global__", GLOBAL_LIMIT):
            break  # over budget: each token falls back to stale cache or a clear 503
        got = await fetch_dex_many(client, todo[i:i + 30])
        if got:
            prefetched.update(got)

    sem = asyncio.Semaphore(4)

    async def one(m: str) -> dict:
        async with sem:
            res, _ = await build_signal(client, m, security, prefetched.get(m))
            return res

    tasks: Dict[str, Any] = {}
    for m in valid:
        t = asyncio.ensure_future(one(m))
        t.add_done_callback(lambda f: f.cancelled() or f.exception())  # never log 'exception never retrieved'
        _bg.add(t)
        t.add_done_callback(_bg.discard)
        tasks[m] = t
    if tasks:
        await asyncio.wait(list(tasks.values()), timeout=BATCH_DEADLINE_S)

    results: List[dict] = []
    for m in valid:
        t = tasks[m]
        if not t.done():  # keeps running in the background and lands in the cache
            errors.append({"mint": m, "status": 504, "detail": "Still computing, retry in a few seconds", "retry_after_s": 5})
            continue
        exc = t.exception()
        if exc is None:
            results.append(t.result())
        elif isinstance(exc, HTTPException):
            e = {"mint": m, "status": exc.status_code, "detail": exc.detail}
            if exc.headers and "Retry-After" in exc.headers:
                e["retry_after_s"] = int(exc.headers["Retry-After"])
            errors.append(e)
        else:
            errors.append({"mint": m, "status": 500, "detail": "Internal error"})

    order = sorted(range(len(results)), key=lambda i: rank_key(results[i]))
    for rank, i in enumerate(order, 1):
        results[i] = dict(results[i], safety_rank=rank)
    everything = list(results)

    if only_set:
        results = [r for r in results if r["verdict"] in only_set]
    if max_risk is not None:
        results = [r for r in results if r["risk_score"] <= max_risk]
    if sort == "safest":
        results.sort(key=lambda r: r["safety_rank"])
    elif sort == "riskiest":
        results.sort(key=lambda r: -r["safety_rank"])
    if top:
        results = results[:top]
    if view == "compact":
        results = [compact_signal(r) for r in results]

    cnt = Counter(r["verdict"] for r in everything)
    best = min(everything, key=lambda r: r["safety_rank"]) if everything else None
    worst = max(everything, key=lambda r: r["safety_rank"]) if everything else None
    brief = lambda r: {"mint": r["mint"], "token": r.get("token"), "risk_score": r["risk_score"], "verdict": r["verdict"]}  # noqa: E731
    headline = (f"{len(ids)} requested: {cnt['ok']} ok, {cnt['caution']} caution, {cnt['avoid']} avoid"
                + (f", {len(errors)} failed" if errors else "")
                + (f". Lowest risk: {best.get('token')} ({best['risk_score']}/100)" if best else "") + ".")
    return {
        "count": len(results),
        "summary": {"checked": len(ids), "ok": cnt["ok"], "caution": cnt["caution"], "avoid": cnt["avoid"],
                    "failed": len(errors), "headline": headline,
                    "safest": brief(best) if best else None, "riskiest": brief(worst) if worst else None,
                    "min_data_confidence": min((r["data_quality"]["data_confidence"] for r in everything), default=None)},
        "results": results, "errors": errors, "filtered_out": len(everything) - len(results),
        "sort": sort, "view": view,
        "rank_basis": "risk_score + data-quality penalty (up to 20 points), ties broken by liquidity",
    }

# --- part9 ---
# ---------- v2.1: resilience, API keys, tamper-evident ledger ----------
import hashlib
import hmac

# --- Solana RPC: fallbacks, one retry, circuit breaker ---
RPC_FALLBACKS = [u.strip() for u in (os.getenv("SOLANA_RPC_FALLBACKS") or "").split(",") if u.strip()]
_rpc_state: Dict[str, Any] = {"fails": 0, "open_until": 0.0}


async def rpc(client: httpx.AsyncClient, method: str, params: list):
    """Try the primary RPC, then each fallback, then the primary once more. After 5 failed calls in a row the
    breaker opens for 20s so a dead RPC cannot pile up requests (signals just come back marked partial)."""
    if time.time() < _rpc_state["open_until"]:
        raise RuntimeError("RPC circuit open: skipped for a few seconds")
    urls = [RPC_URL] + RPC_FALLBACKS + [RPC_URL]
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    last = "no attempt"
    for i, url in enumerate(urls):
        try:
            resp = await client.post(url, json=payload, timeout=4.0)
            resp.raise_for_status()
            body = resp.json()
            if body.get("error"):
                raise RuntimeError(str(body["error"])[:200])
            _rpc_state["fails"] = 0
            return body.get("result")
        except Exception as e:  # noqa: BLE001
            last = f"{type(e).__name__}: {str(e)[:120]}"
            if i < len(urls) - 1:
                await asyncio.sleep(0.2)
    _rpc_state["fails"] += 1
    if _rpc_state["fails"] >= 5:
        _rpc_state.update(fails=0, open_until=time.time() + 20)
    raise RuntimeError(last)


# --- optional API keys: a key gets its own, higher rate limit (no more sharing an IP with strangers) ---
def _load_keys() -> Dict[str, str]:
    keys: Dict[str, str] = {}
    for item in (os.getenv("API_KEYS") or "").split(","):  # API_KEYS="secret1:partnerA,secret2:partnerB"
        key, _, label = item.strip().partition(":")
        if key:
            keys[key] = label or key[:4] + "..."
    return keys


API_KEYS = _load_keys()
KEY_RATE_LIMIT = int(os.getenv("KEY_RATE_LIMIT", "300"))
_client_ip_v20 = client_ip
_rate_limited_v20 = rate_limited


def client_ip(request: Request) -> str:
    given = request.headers.get("x-api-key")
    if given and API_KEYS:
        for key, label in API_KEYS.items():
            if hmac.compare_digest(given.encode(), key.encode()):
                return "key:" + label
    return _client_ip_v20(request)


def rate_limited(key: str, limit: Optional[int] = None, cost: int = 1) -> int:
    if limit is None:
        limit = KEY_RATE_LIMIT if str(key).startswith("key:") else RATE_LIMIT
    return _rate_limited_v20(key, limit, cost)


# --- ledger: every recorded verdict is chained to the previous one with SHA-256 ---
# Publishing the head hash now and then proves the history was not rewritten or back-filled.
LEDGER_KEEP = 20000
_ledger_lock: Optional[asyncio.Lock] = None


def canon(d: dict) -> str:
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


def verify_chain(entries_oldest_first: list) -> bool:
    prev = None
    for e in entries_oldest_first:
        body = {k: v for k, v in e.items() if k != "hash"}
        if hashlib.sha256(canon(body).encode()).hexdigest() != e.get("hash"):
            return False
        if prev is not None and e.get("prev") != prev:
            return False
        prev = e["hash"]
    return True


async def ledger_append(client: httpx.AsyncClient, entry: dict):
    global _ledger_lock
    if not PRED_ENABLED:
        return
    if _ledger_lock is None:
        _ledger_lock = asyncio.Lock()
    async with _ledger_lock:
        got = await redis_pipe(client, [["GET", "ledger_head"]])
        if got is None:
            return  # store unavailable: skip, never block the API
        body = dict(entry, prev=got[0] or "GENESIS")
        h = hashlib.sha256(canon(body).encode()).hexdigest()
        await redis_pipe(client, [["LPUSH", "ledger", canon(dict(body, hash=h))],
                                  ["LTRIM", "ledger", 0, LEDGER_KEEP - 1], ["SET", "ledger_head", h]])


async def record_prediction(client: httpx.AsyncClient, r: dict):
    """Store one verdict to be judged later. At most one per mint per 6h and MAX_PRED_PER_DAY per day."""
    try:
        price = float(r.get("price_usd") or 0)
        mint = r.get("mint")
        if price <= 0 or not mint:
            return
        today = time.strftime("%Y%m%d", time.gmtime())
        if _pred_day["day"] != today:
            _pred_day.update(day=today, count=0)
        if _pred_day["count"] >= MAX_PRED_PER_DAY:
            return
        lock = await redis_pipe(client, [["SET", f"plock:{mint}", "1", "EX", 21600, "NX"]])
        if not lock or lock[0] != "OK":
            return
        _pred_day["count"] += 1
        now = int(time.time())
        pid = f"{mint}:{now}"
        sol = await sol_price(client)
        await redis_pipe(client, [
            ["HSET", f"pred:{pid}", "mint", mint, "token", r.get("token") or "", "ts", now, "price", price,
             "liq", r.get("liquidity_usd") or 0, "verdict", r["verdict"], "conf", r["verdict_confidence"],
             "score", r["risk_score"], "flags", ",".join(r.get("flags") or []), "sol", sol or ""],
            ["EXPIRE", f"pred:{pid}", PRED_HORIZON_S * 4],
            ["ZADD", "due", now + PRED_HORIZON_S, pid],
        ])
        await ledger_append(client, {
            "id": pid, "ts": now, "mint": mint, "token": r.get("token") or "", "verdict": r["verdict"],
            "risk_score": r["risk_score"], "price_usd": price, "liquidity_usd": r.get("liquidity_usd") or 0,
            "flags": sorted(r.get("flags") or []), "version": VERSION,
        })
    except Exception:
        pass


@app.get("/ledger", tags=["trust"], summary="Tamper-evident list of every recorded verdict (hash chain)")
async def ledger_route(request: Request, limit: int = Query(50, ge=1, le=500, description="Newest entries to return")):
    wait = rate_limited(client_ip(request))
    if wait:
        raise too_many(wait)
    if not PRED_ENABLED:
        return JSONResponse(content={"enabled": False, "detail": "The ledger is not switched on on this server yet."})
    res = await redis_pipe(request.app.state.client, [["LRANGE", "ledger", 0, limit - 1], ["GET", "ledger_head"], ["LLEN", "ledger"]])
    if res is None:
        return JSONResponse(content={"enabled": True, "available": False, "detail": "Ledger store unavailable, retry shortly"},
                            status_code=503, headers={"Retry-After": "10"})
    entries = []
    for x in res[0] or []:
        try:
            entries.append(json.loads(x))
        except ValueError:
            pass
    return JSONResponse(content={
        "enabled": True, "head": res[1], "total_kept": int(res[2] or 0), "returned": len(entries), "newest_first": True,
        "how_to_verify": "Go from oldest to newest. For each entry drop the 'hash' field, serialize with sorted keys and compact "
                         "separators (',' and ':'), SHA-256 it: it must equal 'hash', and the next entry's 'prev' must equal it. "
                         "The oldest kept entry's 'prev' is GENESIS or the hash of an older entry. Compare 'head' over time.",
        "entries": entries,
    }, headers={"Cache-Control": "public, max-age=30"})

# --- part10 ---
# ---------- v2.1: public accuracy dashboard + docs ----------
import html as _html

_head_cache: Dict[str, Any] = {"ts": 0.0, "head": None}


def _h(x: Any) -> str:
    return _html.escape(str(x if x is not None else "-"), quote=True)


def _num(v: Any, suffix: str = "") -> str:
    return "-" if v is None else f"{v}{suffix}"


def _rate_cell(rate_pct: Optional[float], n: int) -> str:
    if rate_pct is None:
        return f'<td class="muted">hidden (n={n}, needs {MIN_N_SHOW}+)</td>'
    w = max(0.0, min(100.0, float(rate_pct)))
    return f'<td><div class="bar"><span style="width:{w:.0f}%"></span></div> {w:.1f}% <span class="muted">(n={n})</span></td>'


def render_accuracy(rep: dict, head: Optional[str]) -> str:
    body = []
    if not rep.get("enabled"):
        body.append('<div class="card">The track record is not switched on yet on this server. When it is, every verdict is recorded '
                    "and judged about a day later, and the results appear here.</div>")
    elif rep.get("available") is False:
        body.append('<div class="card">The statistics store is temporarily unavailable. Please try again in a minute.</div>')
    else:
        resolved, pending = int(rep.get("resolved") or 0), int(rep.get("pending") or 0)
        if resolved < MIN_N_SHOW:
            body.append(f'<div class="card"><b>Collecting data.</b> {resolved} verdicts judged so far, {pending} waiting for their '
                        f"{_h(rep.get('horizon_hours'))}h mark. Rates appear once a group has {MIN_N_SHOW}+ samples. "
                        "Nothing is hidden or adjusted by hand.</div>")
        rows = "".join(
            f"<tr><td><b>{_h(v)}</b></td>{_rate_cell(g.get('bad_outcome_rate_pct'), g.get('n', 0))}"
            f"<td>{_num(g.get('avg_return_pct'), '%')}</td><td>{_num(g.get('avg_excess_return_pct'), '%')}</td></tr>"
            for v, d in (rep.get("by_verdict") or {}).items() for g in [d.get("full") or {}])
        body.append("<h2>Bad outcomes by verdict</h2><table><tr><th>Verdict</th><th>Share with a bad outcome</th>"
                    f"<th>Avg return</th><th>Avg vs SOL</th></tr>{rows}</table>")
        gap = rep.get("avoid_vs_ok_gap_pts")
        if gap is not None:
            word = "higher" if gap >= 0 else "LOWER (the verdicts are not working here)"
            body.append(f'<p class="note">Tokens marked <b>avoid</b> had a bad-outcome rate {abs(gap)} points {word} than tokens marked <b>ok</b>.</p>')
        brows = "".join(f"<tr><td>{_h(b['risk_score_range'])}</td>{_rate_cell(b.get('bad_outcome_rate_pct'), b.get('n', 0))}</tr>"
                        for b in rep.get("by_risk_bucket") or [] if b.get("n"))
        if brows:
            body.append(f"<h2>Does a higher risk score mean more bad outcomes?</h2><table><tr><th>Risk score</th><th>Share with a bad outcome</th></tr>{brows}</table>")
        drows = "".join(f"<tr><td>{_h(c['day'])}</td><td>{_h(c['n'])}</td><td>{_num(c.get('bad_outcome_rate_pct'), '%')}</td></tr>"
                        for c in rep.get("daily_background") or [])
        if drows:
            body.append("<h2>The market background, day by day</h2><p class=\"muted\">Share of all judged tokens with a bad outcome that day. "
                        f"Flag statistics are corrected for this.</p><table><tr><th>Day</th><th>Judged</th><th>Bad outcomes</th></tr>{drows}</table>")
        frows = "".join(f"<tr><td>{_h(f['flag'])}</td><td>{_h(f['n'])}</td><td>{_num(f.get('bad_rate_pct'), '%')}</td>"
                        f"<td>{_num(f.get('lift'))}{' (adjusted)' if f.get('market_adjusted') else ''}</td></tr>"
                        for f in rep.get("flags") or [] if f.get("n"))
        if frows:
            body.append(f"<h2>Flags</h2><table><tr><th>Flag</th><th>Judged</th><th>Bad rate</th><th>Lift</th></tr>{frows}</table>")
        rrows = "".join(f"<tr><td>{_h(r.get('token'))}</td><td>{_h(r.get('verdict'))}</td><td>{_h(r.get('risk_score'))}</td>"
                        f"<td>{_num(r.get('return_pct'), '%')}</td><td>{'bad' if r.get('bad_outcome') else 'ok'}</td></tr>"
                        for r in (rep.get("recent_outcomes") or [])[:10])
        if rrows:
            body.append(f"<h2>Latest judged verdicts</h2><table><tr><th>Token</th><th>Verdict</th><th>Risk</th><th>Return</th><th>Outcome</th></tr>{rrows}</table>")
    caveats = "".join(f"<li>{_h(c)}</li>" for c in rep.get("caveats") or [])
    ledger = (f'<p>Ledger head: <code>{_h(head)}</code></p>' if head else "")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVibex402 accuracy</title><style>
:root{{--bg:#070b12;--card:rgba(18,25,35,.8);--line:rgba(34,48,66,.8);--text:#e8eef6;--muted:#8b9bb4;--a:#14f195;--b:#9945ff}}
*{{box-sizing:border-box;margin:0;padding:0}}body{{background:var(--bg);color:var(--text);font-family:system-ui,sans-serif;line-height:1.55}}
.wrap{{max-width:760px;margin:0 auto;padding:32px 16px 70px}}h1{{font-size:2rem;background:linear-gradient(120deg,var(--b),var(--a));-webkit-background-clip:text;background-clip:text;color:transparent}}
h2{{font-size:1.1rem;margin:26px 0 10px}}.muted{{color:var(--muted);font-size:.88rem}}.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:16px 0}}
table{{width:100%;border-collapse:collapse;font-size:.9rem;display:block;overflow-x:auto}}th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}}
.bar{{display:inline-block;width:90px;height:8px;background:var(--line);border-radius:6px;vertical-align:middle;overflow:hidden}}.bar span{{display:block;height:100%;background:var(--b)}}
.note{{margin:10px 0;padding:10px 12px;border-left:3px solid var(--a);background:var(--card)}}a{{color:var(--a)}}code{{word-break:break-all;font-size:.78rem}}li{{margin:4px 0 4px 18px}}
</style></head><body><div class="wrap"><h1>Measured accuracy</h1>
<p class="muted">Every verdict this API gives is recorded, then judged about {_h(rep.get('horizon_hours', 24))} hours later. This page shows what actually happened, including when the verdicts are wrong.</p>
{''.join(body)}
<h2>How we measure</h2><p class="muted">{_h(rep.get('bad_outcome_definition', 'A bad outcome means price down 50%+, liquidity down 70%+, or the pair disappeared.'))}</p>
<ul class="muted">{caveats}</ul>{ledger}
<p class="muted" style="margin-top:14px"><a href="/ledger">Tamper-evident ledger</a> &bull; <a href="/stats">Raw JSON</a> &bull; <a href="/">Home</a></p>
<p class="muted" style="margin-top:18px">Heuristic data, not financial advice. Past measurements do not predict future results.</p>
</div></body></html>"""


@app.get("/accuracy", response_class=HTMLResponse, tags=["trust"], summary="Public accuracy dashboard")
async def accuracy_page(request: Request):
    wait = rate_limited(client_ip(request))
    if wait:
        raise too_many(wait)
    client = request.app.state.client
    rep = await stats_report(client)
    if PRED_ENABLED and time.time() - _head_cache["ts"] > 60:
        got = await redis_pipe(client, [["GET", "ledger_head"]])
        _head_cache.update(ts=time.time(), head=got[0] if got else None)
    return render_accuracy(rep, _head_cache["head"] if PRED_ENABLED else None)


# --- docs: links on the home page and in llms.txt ---
if '<a href="/stats">/stats</a>' in HOME_HTML:
    HOME_HTML = HOME_HTML.replace('<a href="/stats">/stats</a>',
                                  '<a href="/accuracy">/accuracy</a> &bull; <a href="/ledger">/ledger</a> &bull; <a href="/stats">/stats</a>')
LLMS_TXT = LLMS_TXT + """
## Decision object
Every signal has `decision`: verdict, blockers (hard reasons to avoid), cautions, positives, unknowns (what is missing or was NOT
checked), next_checks, valid_for_s (how long this stays valid), confidence (0-1: completeness and freshness of the data, NOT the
chance that the verdict is right) and asset_class (major | established | standard).
Majors (wrapped SOL, USDC, USDT) skip rug-style checks. Established tokens (liquidity >= $1M, pair older than 30 days) show
holder and LP flags but do not score them (flags_not_scored); active authorities still give at most a caution.

## Trust
GET /accuracy  human dashboard of measured outcomes.  GET /stats  same data as JSON.
GET /ledger  hash-chained list of every recorded verdict (tamper-evident: each entry contains the hash of the previous one).
Optional header X-API-Key gives a higher rate limit (keys are issued by the operator).
"""

# --- part11 ---
# ---------- v2.1.1: holder accuracy, abuse resistance, hygiene ----------
# Adds or replaces functions from earlier parts (same shared namespace). Loads before part7 (MCP).
VERSION = "2.1.1"
app.version = VERSION
app.openapi_schema = None  # rebuild /docs with the new version
import contextvars
import re as _re
from functools import lru_cache

SYSTEM_PROGRAM = "11111111111111111111111111111111"
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_P = 2 ** 255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P


def b58_to_32(s: str) -> Optional[bytes]:
    n = 0
    for ch in s:
        i = _B58.find(ch)
        if i < 0:
            return None
        n = n * 58 + i
    raw = b"\x00" * (len(s) - len(s.lstrip("1"))) + n.to_bytes((n.bit_length() + 7) // 8, "big")
    return raw if len(raw) == 32 else None


def is_on_curve(b: bytes) -> bool:
    """True if these 32 bytes decode to an ed25519 point, i.e. the address can have a private key (a wallet).
    Program-derived addresses (pool vaults, bonding curves, multisig vaults) are OFF the curve by construction."""
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    if y >= _P:
        return False
    y2 = y * y % _P
    x2 = (y2 - 1) * pow(_D * y2 + 1, _P - 2, _P) % _P
    return x2 == 0 or pow(x2, (_P - 1) // 2, _P) == 1


@lru_cache(maxsize=4096)
def is_pda(addr: str) -> Optional[bool]:
    raw = b58_to_32(addr)
    return None if raw is None else not is_on_curve(raw)


# A holder that is a program-derived address whose own account belongs to a program (an AMM pool, a bonding curve,
# a staking vault...) is not a person. Wallets and multisig vaults (system-owned) still count as holders.
_fetch_security_v20 = fetch_security


async def fetch_security(client: httpx.AsyncClient, mint: str) -> Optional[dict]:
    raw = await _fetch_security_v20(client, mint)
    try:
        holders = (raw or {}).get("holders") or []
        pdas = sorted({h["owner"] for h in holders if h.get("owner") and is_pda(h["owner"])})
        if pdas:
            res = await rpc(client, "getMultipleAccounts", [pdas, {"encoding": "base64", "dataSlice": {"offset": 0, "length": 0}}])
            infos = dict(zip(pdas, (res or {}).get("value") or []))
            for h in holders:
                if h.get("owner") in infos:
                    acc = infos[h["owner"]]
                    program = (acc or {}).get("owner")
                    h["program_owned"] = bool(acc) and program != SYSTEM_PROGRAM
                    if h["program_owned"]:
                        h["program"] = program
    except Exception:  # noqa: BLE001  best effort: without it we simply fall back to the old behaviour
        pass
    return raw


def build_security(raw: Optional[dict], pool_ids: set):
    """Turn raw on-chain data into a public `security` block + extra flags."""
    if not raw:
        return {"available": False}, []
    flags = []
    out: Dict[str, Any] = {"available": True, "partial": False}

    if raw.get("info_ok"):
        ma, fa = raw.get("mint_authority"), raw.get("freeze_authority")
        out.update(
            mint_authority_revoked=ma is None,
            freeze_authority_revoked=fa is None,
            token_program=raw.get("program"),
            decimals=raw.get("decimals"),
        )
        risky = sorted(set(raw.get("extensions") or []) & RISKY_EXTENSIONS)
        out["risky_extensions"] = risky
        if ma is not None:
            flags.append("mint_authority_active")
        if fa is not None:
            flags.append("freeze_authority_active")
        if risky:
            flags.append("risky_token_extension")
    else:
        out["partial"] = True

    holders, supply = raw.get("holders"), raw.get("supply")
    if holders and supply:
        excluded_ids = pool_ids | KNOWN_NON_HOLDERS
        real, pool_pct, prog_pct = [], 0.0, 0.0
        for h in holders:
            pct = h["amount"] / supply * 100
            if h["owner"] in excluded_ids or h["account"] in excluded_ids or h.get("program_owned"):
                pool_pct += pct
                if h.get("program_owned"):
                    prog_pct += pct
            else:
                real.append({"owner": h["owner"] or h["account"], "pct": round(pct, 2)})
        top1 = real[0]["pct"] if real else 0.0
        top10 = round(sum(h["pct"] for h in real[:10]), 2)
        out.update(
            top1_holder_pct=top1,
            top10_holders_pct=top10,
            liquidity_pool_pct=round(pool_pct, 2),
            program_owned_pct=round(prog_pct, 2),
            top_holders=real[:5],
        )
        if top10 >= 80:
            flags.append("extreme_holder_concentration")
        elif top10 >= 50:
            flags.append("high_holder_concentration")
        if top1 >= 20:
            flags.append("dominant_holder")
    else:
        out["partial"] = True
    return out, flags


# --- a reserved lane in the shared upstream budget for keyed clients ---
# Anonymous traffic can no longer use up the whole DexScreener budget and lock out clients who hold an API key.
GLOBAL_KEY_RESERVE = int(os.getenv("GLOBAL_KEY_RESERVE", "50"))
_keyed_ctx: "contextvars.ContextVar[bool]" = contextvars.ContextVar("tvibex_keyed", default=False)
_rate_limited_v21 = rate_limited


def rate_limited(key: str, limit: Optional[int] = None, cost: int = 1) -> int:
    if key == "__global__" and _keyed_ctx.get():
        key, limit = "__global_key__", GLOBAL_KEY_RESERVE
    return _rate_limited_v21(key, limit, cost)


class KeyContextMiddleware:
    """Marks the request context as 'keyed' when a valid X-API-Key header is present."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and API_KEYS:
            given = next((v for k, v in scope.get("headers", []) if k == b"x-api-key"), None)
            if given and any(hmac.compare_digest(given, key.encode()) for key in API_KEYS):
                token = _keyed_ctx.set(True)
                try:
                    return await self.app(scope, receive, send)
                finally:
                    _keyed_ctx.reset(token)
        return await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrap(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                have = {k.lower() for k, _ in headers}
                for k, v in ((b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                             (b"x-frame-options", b"DENY")):
                    if k not in have:
                        headers.append((k, v))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrap)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(KeyContextMiddleware)

# --- never leak an RPC key (Helius puts it in the URL) through an error message ---
_SECRET_RE = _re.compile(r"(?i)(api[-_]?key|apikey|token|key)=[^&\s'\"]+")


def redact(msg: str) -> str:
    for u in [RPC_URL] + RPC_FALLBACKS:
        if u:
            msg = msg.replace(u, "[rpc]")
    return _SECRET_RE.sub(lambda m: m.group(1) + "=[redacted]", msg)


_rpc_v21 = rpc


async def rpc(client: httpx.AsyncClient, method: str, params: list):
    try:
        return await _rpc_v21(client, method, params)
    except RuntimeError as e:
        raise RuntimeError(redact(str(e))) from None


@app.get("/whoami", tags=["ops"], summary="Which client IP this server sees (use it to check TRUSTED_PROXY_HOPS)")
async def whoami(request: Request):
    wait = rate_limited(client_ip(request))
    if wait:
        raise too_many(wait)
    return JSONResponse(content={"seen_ip": client_ip(request), "x_forwarded_for": request.headers.get("x-forwarded-for"),
                                 "trusted_proxy_hops": TRUSTED_HOPS}, headers={"Cache-Control": "no-store"})


LLMS_TXT = LLMS_TXT + """
## Holders
top1_holder_pct and top10_holders_pct count real holders only. Liquidity pools, bonding curves and other accounts owned by
programs are excluded (liquidity_pool_pct, program_owned_pct). Wallets and multisig vaults still count as holders.
"""

# --- part12 ---
# ---------- v2.2: honest PumpSwap LP status + richer home page ----------
# Adds or replaces things from earlier parts (same shared namespace). Loads before part7 (MCP).
VERSION = "2.2.0"
app.version = VERSION
app.openapi_schema = None  # rebuild /docs with the new version

# --- PumpSwap: RugCheck cannot tell a burned-at-graduation pool from a directly created one ---
PUMPSWAP_LP_NOTE = ("PumpSwap pools created by pump.fun graduation burn their LP automatically, but pools created directly "
                    "may not, and RugCheck cannot tell which this is. LP status is unverified, not confirmed bad.")
REASONS["lp_unverified"] = "Liquidity lock/burn could not be verified (PumpSwap pool)"
RISK_WEIGHTS.setdefault("lp_unverified", 10)
ACTIVE_WEIGHTS.setdefault("lp_unverified", 10)
if "lp_unverified" not in CAUTION_FLAGS:
    CAUTION_FLAGS.append("lp_unverified")
RUG_STYLE_FLAGS.add("lp_unverified")
_finalize_risk_v21 = finalize_risk


def finalize_risk(result: dict, onchain: bool):
    if result.get("dex") == "pumpswap" and {"lp_not_locked", "lp_partially_locked"} & set(result["flags"]):
        result["flags"] = [f for f in result["flags"] if f not in ("lp_not_locked", "lp_partially_locked")] + ["lp_unverified"]
        if isinstance(result.get("security"), dict):
            result["security"]["lp_note"] = PUMPSWAP_LP_NOTE
    _finalize_risk_v21(result, onchain)


_with_quality_v21 = with_quality


def with_quality(result: dict, status: str, security: bool) -> dict:
    out = _with_quality_v21(result, status, security)
    d = out.get("decision")
    if d and "lp_unverified" in out.get("flags", []):
        out["decision"] = dict(d, unknowns=list(d.get("unknowns") or []) + ["LP burn/lock is unverified for this PumpSwap pool"])
    return out


# --- home page: decision panels, data quality line, exit button (patched into the existing page) ---
_HOME_CSS = """
.why{border-left:3px solid var(--line);background:rgba(13,17,23,.6);border-radius:10px;padding:8px 12px;margin:10px 0;font-size:.88rem}
.why ul{margin:4px 0 0 18px}.why.bad{border-color:var(--danger)}.why.warn{border-color:var(--warn)}.why.good{border-color:var(--a)}.why.dim{color:var(--muted)}
button.ghost{background:transparent;color:var(--text);border:1px solid var(--line);margin-top:12px;padding:10px 16px}
table.mini{margin-top:6px;font-size:.85rem;border-collapse:collapse}table.mini td{padding:3px 12px 3px 0}
"""

_HOME_JS = """
function wlist(title,items,cls){
if(!items||!items.length)return '';
return '<div class="why '+cls+'"><b>'+esc(title)+'</b><ul>'+items.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul></div>';
}
function renderDecision(d){
if(!d)return '';
return wlist('Why not',d.blockers,'bad')+wlist('Watch out',d.cautions,'warn')+wlist('Good signs',d.positives,'good')+wlist('Not known or not checked',d.unknowns,'dim')+(d.note?'<p class="muted" style="margin-top:6px">'+esc(d.note)+'</p>':'');
}
function renderQuality(q){
if(!q)return '';
const c=q.data_confidence!=null?Math.round(q.data_confidence*100)+'%':'-';
const m=(q.missing&&q.missing.length)?' | missing: '+q.missing.map(esc).join(', '):'';
return '<p class="muted" style="margin-top:10px">Data: '+esc(q.freshness)+' | '+esc(q.age_s)+'s old | '+esc(q.completeness)+' | confidence '+esc(c)+m+'</p>';
}
async function checkExit(mint){
const box=document.getElementById('exitbox'),btn=document.getElementById('exitbtn');
btn.disabled=true;box.innerHTML='<p class="muted">Asking Jupiter...</p>';
try{
const res=await fetch('/exit?mint='+encodeURIComponent(mint));const d=await res.json();
if(!res.ok){box.innerHTML='<p style="color:#ff4d6d">'+esc(d.detail||'Failed')+'</p>';}
else{
const e=d.exit||{};
const rows=(e.levels||[]).map(l=>'<tr><td>$'+esc(l.size_usd)+'</td><td>'+(l.status==='ok'?'receive $'+esc(l.sell_receives_usd)+' ('+esc(l.loss_vs_market_pct)+'% below market)':esc(l.status))+'</td></tr>').join('');
const cls=d.combined_verdict==='avoid'?'bad':d.combined_verdict==='caution'?'warn':'good';
box.innerHTML='<div class="why '+cls+'"><b>Combined: '+esc((d.combined_verdict||'').toUpperCase())+'</b><p style="margin:4px 0">'+esc(d.summary||'')+'</p>'+(rows?'<table class="mini">'+rows+'</table>':'')+'<p class="muted" style="margin-top:6px">A quote is not proof that a real sell will succeed.</p></div>';
}
}catch(err){box.innerHTML='<p style="color:#ff4d6d">Network error</p>'}
btn.disabled=false;
}
"""

_HOME_RESULT_TAIL = """<div class="muted" style="margin-top:12px">${esc(data.summary||'')}</div>
${renderDecision(data.decision)}
<div style="margin:12px 0 6px;font-size:.85rem;color:var(--muted)">Flags</div>
<div>${flags||'<span class="muted">None</span>'}</div>
${data.decision?'':'<div class="muted" style="margin-top:8px">'+esc((data.verdict_reasons||[]).join(' | '))+'</div>'}
${renderQuality(data.data_quality)}
${data.partial?'<p class="muted" style="margin-top:6px">Some on-chain data was slow, so it is missing here.</p>':''}${data.stale?'<p class="muted" style="margin-top:6px">Showing cached data from '+esc(data.stale_age_s||'?')+'s ago because a data source was down.</p>':''}
<button class="ghost" id="exitbtn" data-mint="${esc(data.mint||'')}" onclick="checkExit(this.dataset.mint)">Check exit cost (can I sell?)</button>
<div id="exitbox"></div>
<p class="muted" style="margin-top:12px;font-size:.78rem">Heuristic output, not financial advice.</p></div>`;"""

_flags_marker = '<div style="margin:12px 0 6px;font-size:.85rem;color:var(--muted)">Flags</div>'
_a = HOME_HTML.find(_flags_marker)
_b = HOME_HTML.find("</div>`;", _a) if _a >= 0 else -1
if _a >= 0 and _b >= 0 and "renderDecision" not in HOME_HTML:
    HOME_HTML = HOME_HTML[:_a] + _HOME_RESULT_TAIL + HOME_HTML[_b + len("</div>`;"):]
    HOME_HTML = HOME_HTML.replace("</style>", _HOME_CSS + "</style>", 1)
    HOME_HTML = HOME_HTML.replace("</script>", _HOME_JS + "</script>", 1)
    HOME_HTML = HOME_HTML.replace("const lp=s.lp_locked_pct!=null?esc(s.lp_locked_pct)+'%':'-';",
                                  "const lp=s.lp_note?'unverified':(s.lp_locked_pct!=null?esc(s.lp_locked_pct)+'%':'-');")
    HOME_HTML = HOME_HTML.replace("Verdict + plain-English summary", "Verdict, reasons, watch-outs and what is unknown")

LLMS_TXT = LLMS_TXT + """
## PumpSwap liquidity
For pools on PumpSwap the flag lp_unverified is used instead of lp_not_locked: pump.fun graduations burn their LP automatically,
directly created pools may not, and the data source cannot tell which one it is. It is a caution, not a confirmed problem.
security.lp_note explains it. Check the pool's LP mint holders on a block explorer if it matters.
"""

# --- part13 ---
# ---------- v2.3: Token-2022 details, smarter batch filters ----------
# Adds or replaces things from earlier parts (same shared namespace). Loads before part7 (MCP).
VERSION = "2.3.0"
app.version = VERSION
app.openapi_schema = None  # rebuild /docs with the new version

# --- Token-2022: read what each extension actually does instead of flagging every extension ---
T22_FEE_HIGH_BPS = 500       # 5% on every transfer
T22_FEE_EXTREME_BPS = 2500   # 25%: a sell tax
_ZERO_KEY = "11111111111111111111111111111111"
REASONS.update({
    "permanent_delegate_active": "A permanent delegate can move or burn tokens from any holder",
    "transfer_fee_extreme": "Transfer fee of 25% or more on every transfer (a sell tax)",
    "default_account_frozen": "New token accounts start frozen: holders cannot move tokens until the issuer thaws them",
    "transfer_fee_high": "Transfer fee of 5% or more on every transfer",
    "transfer_hook_active": "A transfer hook program runs on every transfer and can block it",
})
for _flag, _weight in (("permanent_delegate_active", 40), ("transfer_fee_extreme", 40), ("default_account_frozen", 40),
                       ("transfer_fee_high", 20), ("transfer_hook_active", 20), ("transfer_fee_set", 5)):
    RISK_WEIGHTS.setdefault(_flag, _weight)
    ACTIVE_WEIGHTS.setdefault(_flag, _weight)
for _flag in ("permanent_delegate_active", "transfer_fee_extreme", "default_account_frozen"):
    if _flag not in AVOID_FLAGS:
        AVOID_FLAGS.append(_flag)
for _flag in ("transfer_fee_high", "transfer_hook_active"):
    if _flag not in CAUTION_FLAGS:
        CAUTION_FLAGS.append(_flag)


def parse_t22(extensions) -> Optional[dict]:
    """What the Token-2022 extensions of a mint do. None if the data does not look like jsonParsed extensions."""
    if not isinstance(extensions, list):
        return None
    out: Dict[str, Any] = {"transfer_fee_bps": None, "max_transfer_fee": None, "permanent_delegate": None,
                           "default_account_frozen": False, "transfer_hook_program": None,
                           "non_transferable": False, "other": []}
    for e in extensions:
        if not isinstance(e, dict):
            return None
        name, st = e.get("extension"), e.get("state") or {}
        if name == "transferFeeConfig":
            bps = maximum = 0
            for k in ("newerTransferFee", "olderTransferFee"):  # the newer fee applies from its epoch: assume the worse
                fee = st.get(k) or {}
                bps = max(bps, int(fee.get("transferFeeBasisPoints") or 0))
                maximum = max(maximum, int(fee.get("maximumFee") or 0))
            out["transfer_fee_bps"], out["max_transfer_fee"] = bps, maximum
        elif name == "permanentDelegate":
            delegate = st.get("delegate")
            out["permanent_delegate"] = delegate if delegate and delegate != _ZERO_KEY else None
        elif name == "defaultAccountState":
            out["default_account_frozen"] = st.get("accountState") == "frozen"
        elif name == "transferHook":
            program = st.get("programId")
            out["transfer_hook_program"] = program if program and program != _ZERO_KEY else None
        elif name == "nonTransferable":
            out["non_transferable"] = True
        elif name:
            out["other"].append(name)
    return out


_fetch_security_v22 = fetch_security


async def fetch_security(client: httpx.AsyncClient, mint: str) -> Optional[dict]:
    raw = await _fetch_security_v22(client, mint)
    try:
        if raw and raw.get("program") == "token-2022" and raw.get("extensions"):  # one extra call, Token-2022 only
            res = await rpc(client, "getAccountInfo", [mint, {"encoding": "jsonParsed"}])
            data = ((res or {}).get("value") or {}).get("data")
            parsed = data.get("parsed") if isinstance(data, dict) else None
            details = parse_t22(((parsed or {}).get("info") or {}).get("extensions"))
            if details is not None:
                raw["t22"] = details
    except Exception:  # noqa: BLE001  best effort: without it the older, coarser flag stays
        pass
    return raw


_build_security_v22 = build_security


def build_security(raw: Optional[dict], pool_ids: set):
    out, flags = _build_security_v22(raw, pool_ids)
    t = (raw or {}).get("t22")
    if t is not None and "unparseableExtension" not in t["other"]:
        flags = [f for f in flags if f != "risky_token_extension"]  # replaced by the specific flags below
        bps = t["transfer_fee_bps"] or 0
        if t["permanent_delegate"]:
            flags.append("permanent_delegate_active")
        if bps >= T22_FEE_EXTREME_BPS:
            flags.append("transfer_fee_extreme")
        elif bps >= T22_FEE_HIGH_BPS:
            flags.append("transfer_fee_high")
        elif bps > 0:
            flags.append("transfer_fee_set")
        if t["transfer_hook_program"]:
            flags.append("transfer_hook_active")
        if t["default_account_frozen"]:
            flags.append("default_account_frozen")
        out["token2022"] = {
            "transfer_fee_pct": round(bps / 100, 2), "max_transfer_fee_raw": t["max_transfer_fee"],
            "permanent_delegate": t["permanent_delegate"], "transfer_hook_program": t["transfer_hook_program"],
            "default_account_frozen": t["default_account_frozen"], "non_transferable": t["non_transferable"],
            "other_extensions": t["other"],
        }
    return out, flags


# --- batch: cheap filters run BEFORE the expensive per-token work ---
BATCH_SORTS_V23 = ("input", "safest", "riskiest", "liquidity", "volume_1h")


def market_facts(mint: str, security: bool, pre: Optional[dict]):
    """(liquidity_usd, pair_age_minutes, volume_1h) from the shared DexScreener data or a fresh cache entry, else None."""
    if pre is not None:
        pair = pick_best_pair(pre.get("pairs") or [], mint)
        if pair is None:
            return None
        created = pair.get("pairCreatedAt")
        age = max(0, int((time.time() * 1000 - created) / 60000)) if created else None
        return (float((pair.get("liquidity") or {}).get("usd") or 0), age, float((pair.get("volume") or {}).get("h1") or 0))
    hit = cache_peek(mint if security else mint + ":nosec")
    if hit:
        d = hit[1]
        return float(d.get("liquidity_usd") or 0), d.get("pair_age_minutes"), float(d.get("volume_1h") or 0)
    return None


async def build_batch(client: httpx.AsyncClient, raw_mints: List[str], security: bool, *, sort: str = "input",
                      only: Optional[str] = None, max_risk: Optional[int] = None, top: Optional[int] = None,
                      view: str = "full", charge=None, min_liq: Optional[float] = None,
                      max_age_minutes: Optional[int] = None, min_volume_1h: Optional[float] = None) -> dict:
    """Smart batch: ONE shared DexScreener request for everything not cached, cost = only what needs fetching,
    an overall deadline (slow tokens are reported, not waited for), ranking, filters and a one-line summary."""
    ids = list(dict.fromkeys(m.strip() for m in raw_mints if m and m.strip()))
    if not ids:
        raise HTTPException(status_code=400, detail="Provide at least one mint")
    if len(ids) > MAX_BATCH:
        raise HTTPException(status_code=400, detail=f"Max {MAX_BATCH} mints per request")
    if sort not in BATCH_SORTS_V23:
        raise HTTPException(status_code=400, detail="sort must be one of: " + ", ".join(BATCH_SORTS_V23))
    if view not in ("full", "compact"):
        raise HTTPException(status_code=400, detail="view must be full or compact")
    only_set = None
    if only:
        only_set = {x.strip().lower() for x in only.split(",") if x.strip()}
        if not only_set or not only_set <= {"ok", "caution", "avoid"}:
            raise HTTPException(status_code=400, detail="only must be a comma list of: ok, caution, avoid")

    errors: List[dict] = []
    valid: List[str] = []
    for m in ids:
        if MINT_RE.match(m):
            valid.append(m)
        else:
            errors.append({"mint": m, "status": 400, "detail": "Invalid Solana token address"})

    # what actually needs upstream work? (fresh cache hits are free)
    todo = []
    for m in valid:
        hit = cache_peek(m if security else m + ":nosec")
        if not (hit and hit[0] <= (PARTIAL_TTL if hit[1].get("partial") else CACHE_TTL)):
            todo.append(m)
    wait = charge(max(1, len(todo))) if charge else 0
    if wait:
        raise too_many(wait)

    prefetched: Dict[str, dict] = {}
    for i in range(0, len(todo), 30):
        if rate_limited("__global__", GLOBAL_LIMIT):
            break  # over budget: each token falls back to stale cache or a clear 503
        got = await fetch_dex_many(client, todo[i:i + 30])
        if got:
            prefetched.update(got)

    # cheap filters first: drop tokens that fail them BEFORE the expensive RPC / RugCheck work
    skipped: List[dict] = []
    if min_liq is not None or max_age_minutes is not None or min_volume_1h is not None:
        keep = []
        for m in valid:
            facts = market_facts(m, security, prefetched.get(m))
            why = None
            if facts is not None:  # unknown facts: let the full pipeline decide (it reports the real error)
                liq, age, vol = facts
                if min_liq is not None and liq < min_liq:
                    why = f"liquidity ${liq:,.0f} is below min_liq ${min_liq:,.0f}"
                elif max_age_minutes is not None and age is not None and age > max_age_minutes:
                    why = f"pair is {age} minutes old, above max_age_minutes {max_age_minutes}"
                elif min_volume_1h is not None and vol < min_volume_1h:
                    why = f"1h volume ${vol:,.0f} is below min_volume_1h ${min_volume_1h:,.0f}"
            if why:
                skipped.append({"mint": m, "reason": why})
            else:
                keep.append(m)
        valid = keep

    sem = asyncio.Semaphore(4)

    async def one(m: str) -> dict:
        async with sem:
            res, _ = await build_signal(client, m, security, prefetched.get(m))
            return res

    tasks: Dict[str, Any] = {}
    for m in valid:
        t = asyncio.ensure_future(one(m))
        t.add_done_callback(lambda f: f.cancelled() or f.exception())  # never log 'exception never retrieved'
        _bg.add(t)
        t.add_done_callback(_bg.discard)
        tasks[m] = t
    if tasks:
        await asyncio.wait(list(tasks.values()), timeout=BATCH_DEADLINE_S)

    results: List[dict] = []
    for m in valid:
        t = tasks[m]
        if not t.done():  # keeps running in the background and lands in the cache
            errors.append({"mint": m, "status": 504, "detail": "Still computing, retry in a few seconds", "retry_after_s": 5})
            continue
        exc = t.exception()
        if exc is None:
            results.append(t.result())
        elif isinstance(exc, HTTPException):
            e = {"mint": m, "status": exc.status_code, "detail": exc.detail}
            if exc.headers and "Retry-After" in exc.headers:
                e["retry_after_s"] = int(exc.headers["Retry-After"])
            errors.append(e)
        else:
            errors.append({"mint": m, "status": 500, "detail": "Internal error"})

    order = sorted(range(len(results)), key=lambda i: rank_key(results[i]))
    for rank, i in enumerate(order, 1):
        results[i] = dict(results[i], safety_rank=rank)
    everything = list(results)

    if only_set:
        results = [r for r in results if r["verdict"] in only_set]
    if max_risk is not None:
        results = [r for r in results if r["risk_score"] <= max_risk]
    if sort == "safest":
        results.sort(key=lambda r: r["safety_rank"])
    elif sort == "riskiest":
        results.sort(key=lambda r: -r["safety_rank"])
    elif sort == "liquidity":
        results.sort(key=lambda r: -(r.get("liquidity_usd") or 0))
    elif sort == "volume_1h":
        results.sort(key=lambda r: -(r.get("volume_1h") or 0))
    if top:
        results = results[:top]
    if view == "compact":
        results = [compact_signal(r) for r in results]

    cnt = Counter(r["verdict"] for r in everything)
    best = min(everything, key=lambda r: r["safety_rank"]) if everything else None
    worst = max(everything, key=lambda r: r["safety_rank"]) if everything else None
    brief = lambda r: {"mint": r["mint"], "token": r.get("token"), "risk_score": r["risk_score"], "verdict": r["verdict"]}  # noqa: E731
    headline = (f"{len(ids)} requested: {cnt['ok']} ok, {cnt['caution']} caution, {cnt['avoid']} avoid"
                + (f", {len(errors)} failed" if errors else "")
                + (f", {len(skipped)} skipped by filters" if skipped else "")
                + (f". Lowest risk: {best.get('token')} ({best['risk_score']}/100)" if best else "") + ".")
    return {
        "count": len(results),
        "summary": {"checked": len(ids), "ok": cnt["ok"], "caution": cnt["caution"], "avoid": cnt["avoid"],
                    "failed": len(errors), "headline": headline,
                    "safest": brief(best) if best else None, "riskiest": brief(worst) if worst else None,
                    "min_data_confidence": min((r["data_quality"]["data_confidence"] for r in everything), default=None)},
        "results": results, "errors": errors, "filtered_out": len(everything) - len(results),
        "sort": sort, "view": view, "skipped": skipped,
        "filters": {k: v for k, v in (("min_liq", min_liq), ("max_age_minutes", max_age_minutes),
                                      ("min_volume_1h", min_volume_1h), ("only", only), ("max_risk", max_risk),
                                      ("top", top)) if v is not None},
        "rank_basis": "risk_score + data-quality penalty (up to 20 points), ties broken by liquidity",
    }


def _drop_route(path: str) -> int:
    router = getattr(app, "router", None)
    routes = getattr(router, "routes", None)
    if routes is None:
        return 0
    keep = [r for r in routes if getattr(r, "path", None) != path]
    removed = len(routes) - len(keep)
    routes[:] = keep
    return removed


_drop_route("/signals")  # replaced below by a version with the new parameters


@app.get("/signals", tags=["signals"], summary="Smart batch: up to 10 tokens, filtered cheaply, ranked",
         description="One shared market-data request for everything not cached. min_liq, max_age_minutes and min_volume_1h are "
                     "applied right after that request, so tokens that fail them cost no RPC or RugCheck calls and are listed "
                     "in `skipped`. The rate-limit cost is the number of tokens that needed fetching. Slow tokens appear in "
                     "`errors` (status 504). Each result has `safety_rank` (1 = lowest risk).")
async def signals(
    request: Request,
    mints: str = Query(..., max_length=600, description=f"Comma-separated mints, max {MAX_BATCH}"),
    security: bool = Query(True, description="Include on-chain checks"),
    sort: str = Query("input", description="input | safest | riskiest | liquidity | volume_1h"),
    only: Optional[str] = Query(None, description="Keep only these verdicts, e.g. ok,caution"),
    max_risk: Optional[int] = Query(None, ge=0, le=100, description="Keep only risk_score <= this"),
    top: Optional[int] = Query(None, ge=1, le=MAX_BATCH, description="Keep only the first N after sorting"),
    view: str = Query("full", description="full | compact (decision fields only)"),
    min_liq: Optional[float] = Query(None, ge=0, description="Skip tokens with liquidity below this (USD)"),
    max_age_minutes: Optional[int] = Query(None, ge=1, le=525600, description="Skip pairs older than this"),
    min_volume_1h: Optional[float] = Query(None, ge=0, description="Skip tokens with 1h volume below this (USD)"),
):
    data = await build_batch(request.app.state.client, mints.split(","), security, sort=sort, only=only,
                             max_risk=max_risk, top=top, view=view, min_liq=min_liq, max_age_minutes=max_age_minutes,
                             min_volume_1h=min_volume_1h, charge=lambda cost: rate_limited(client_ip(request), cost=cost))
    return JSONResponse(content=data, headers={"Cache-Control": "public, max-age=10"})


LLMS_TXT = LLMS_TXT + """
## Batch filters
GET /signals also takes min_liq (USD), max_age_minutes, min_volume_1h and sort=liquidity|volume_1h. These filters run right after
the shared market-data request, so tokens that fail them cost no RPC or RugCheck calls; they are listed in `skipped`.

## Token-2022 flags
permanent_delegate_active, transfer_fee_extreme (>=25%), transfer_fee_high (>=5%), transfer_fee_set (<5%), transfer_hook_active,
default_account_frozen. security.token2022 shows the details. A fee of 0% is no longer treated as risky.
"""

# --- part14 ---
# ---------- v2.3: live updates for one token (Server-Sent Events) ----------
# One polling loop per watched token, shared by every listener: upstream cost follows the number of
# tokens being watched, not the number of connections. Strict caps keep it from being abused.
from fastapi.responses import StreamingResponse

STREAM_MAX_WATCHED = int(os.getenv("STREAM_MAX_WATCHED", "30"))   # tokens watched at the same time
STREAM_MAX_PER_IP = int(os.getenv("STREAM_MAX_PER_IP", "2"))
STREAM_MAX_PER_KEY = int(os.getenv("STREAM_MAX_PER_KEY", "10"))
STREAM_MAX_SECONDS = int(os.getenv("STREAM_MAX_SECONDS", "600"))  # a connection ends after this; clients reconnect
STREAM_INTERVAL_S = max(10, int(os.getenv("STREAM_INTERVAL_S", "20")))
STREAM_KEEPALIVE_S = 15

_watchers: Dict[str, "_Watcher"] = {}
_stream_open: Counter = Counter()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def _change_key(r: dict):
    d = r.get("decision") or {}
    return (r.get("verdict"), r.get("risk_score"), tuple(sorted(r.get("flags") or [])), tuple(d.get("blockers") or []))


class _Watcher:
    def __init__(self, mint: str):
        self.mint = mint
        self.subs: set = set()
        self.key = None
        self.last: Optional[dict] = None
        self.task = None

    def publish(self, message: str):
        for q in list(self.subs):
            if q.full():  # a slow listener loses its oldest message instead of blocking everyone
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(message)

    async def run(self, client: httpx.AsyncClient):
        try:
            while self.subs:
                try:
                    res, _ = await build_signal(client, self.mint, True)
                    snap = dict(compact_signal(res), checked_at=res.get("timestamp"))
                    key = _change_key(res)
                    self.last = snap
                    if key != self.key:
                        kind = "snapshot" if self.key is None else "change"
                        self.key = key
                        self.publish(_sse(kind, snap))
                    else:
                        self.publish(_sse("tick", {"price_usd": snap.get("price_usd"), "liquidity_usd": snap.get("liquidity_usd"),
                                                   "checked_at": snap.get("checked_at"),
                                                   "freshness": (snap.get("data_quality") or {}).get("freshness")}))
                except HTTPException as e:
                    self.publish(_sse("problem", {"status": e.status_code, "detail": e.detail}))
                await asyncio.sleep(STREAM_INTERVAL_S)
        finally:
            if _watchers.get(self.mint) is self:
                _watchers.pop(self.mint, None)


async def _stream_gen(request: Request, client: httpx.AsyncClient, mint: str, who: str):
    watcher = _watchers.get(mint)
    if watcher is None:
        watcher = _watchers[mint] = _Watcher(mint)
    q: asyncio.Queue = asyncio.Queue(maxsize=20)
    watcher.subs.add(q)
    _stream_open[who] += 1
    if watcher.task is None or watcher.task.done():
        watcher.task = asyncio.ensure_future(watcher.run(client))
        _bg.add(watcher.task)
        watcher.task.add_done_callback(_bg.discard)
    started = time.time()
    try:
        yield "retry: 5000\n\n"
        if watcher.last:
            yield _sse("snapshot", watcher.last)
        while time.time() - started < STREAM_MAX_SECONDS:
            if await request.is_disconnected():
                return
            try:
                message = await asyncio.wait_for(q.get(), timeout=STREAM_KEEPALIVE_S)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            yield message
        yield _sse("end", {"reason": "maximum duration reached, reconnect to continue"})
    finally:
        watcher.subs.discard(q)
        _stream_open[who] -= 1
        if _stream_open[who] <= 0:
            _stream_open.pop(who, None)
        if not watcher.subs and watcher.task is not None and not watcher.task.done():
            watcher.task.cancel()


@app.get("/stream", tags=["signals"], summary="Live updates for one token (Server-Sent Events)",
         description="Events: snapshot (first state), change (verdict, risk score, flags or blockers changed), tick (price and "
                     "liquidity, about every 20s), problem (a data source failed), end (max duration reached: reconnect). "
                     "Listeners of the same token share one polling loop. Limits: 2 open streams per IP (10 per API key), "
                     "30 tokens watched at once, 10 minutes per connection.")
async def stream_route(request: Request, mint: str = Query(..., min_length=1, max_length=64)):
    mint = mint.strip()
    if not MINT_RE.match(mint):
        raise HTTPException(status_code=400, detail="Invalid Solana token address")
    who = client_ip(request)
    wait = rate_limited(who)
    if wait:
        raise too_many(wait)
    cap = STREAM_MAX_PER_KEY if str(who).startswith("key:") else STREAM_MAX_PER_IP
    if _stream_open.get(who, 0) >= cap:
        raise HTTPException(status_code=429, detail=f"Too many open streams for this client (max {cap})", headers={"Retry-After": "10"})
    if mint not in _watchers and len(_watchers) >= STREAM_MAX_WATCHED:
        raise HTTPException(status_code=503, detail="Too many tokens are being watched right now, retry in a minute",
                            headers={"Retry-After": "30"})
    return StreamingResponse(_stream_gen(request, request.app.state.client, mint, who), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


LLMS_TXT = LLMS_TXT + """
## Live updates (Server-Sent Events)
GET /stream?mint=<MINT> keeps the connection open and sends events: snapshot, change (verdict, risk score, flags or blockers
changed), tick (price and liquidity every ~20s), problem, end. Reconnect after `end` (max 10 minutes per connection).
Limits: 2 open streams per IP (10 per API key), 30 tokens watched at once. Listeners of one token share a single polling loop.
"""

# --- part15 ---
# ---------- v2.4: windowed accuracy, baseline comparison, evidence-based context ----------
# Adds or replaces things from earlier parts (same shared namespace). Loads before part7 (MCP).
import calendar

VERSION = "2.4.0"
app.version = VERSION
app.openapi_schema = None  # rebuild /docs with the new version

# The simplest honest baseline: "avoid anything with liquidity under $50k or a pair younger than 6 hours".
BASELINE_FLAGS = {"very_low_liquidity", "low_liquidity", "brand_new_pair", "very_new_pair"}
RAW_ST_TTL = 600
_raw_st: Dict[str, Any] = {"ts": 0.0, "st": {}}


def wilson(k: int, n: int, z: float = 1.96):
    """95% confidence interval for a share k/n (Wilson). Honest about small samples."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


async def resolve_due(client: httpx.AsyncClient) -> int:
    """Judge predictions whose time has come. Returns how many were processed."""
    now = int(time.time())
    got = await redis_pipe(client, [["ZRANGEBYSCORE", "due", "-inf", now, "LIMIT", 0, RESOLVE_BATCH]])
    ids = (got or [[]])[0] or []
    if not ids:
        return 0
    hashes = await redis_pipe(client, [["HGETALL", f"pred:{i}"] for i in ids])
    if hashes is None:
        return 0
    cmds: list = []
    preds: Dict[str, dict] = {}
    for pid, h in zip(ids, hashes):
        d = to_dict(h)
        if d.get("mint"):
            preds[pid] = d
        else:
            cmds.append(["ZREM", "due", pid])  # hash expired: drop the orphan
    best: Dict[str, Optional[dict]] = {}
    sol1: Optional[float] = None
    if preds:
        mints = sorted({d["mint"] for d in preds.values()})
        ask = mints if SOL_MINT in mints else mints + [SOL_MINT]
        t0 = time.time()
        try:
            resp = await client.get(DEX_URL.format(mint=",".join(ask)))
            resp.raise_for_status()
            pairs = resp.json().get("pairs") or []
            src_log("dexscreener", True, t0)
        except (httpx.HTTPError, ValueError):
            src_log("dexscreener", False, t0)
            if cmds:
                await redis_pipe(client, cmds)
            return 0  # try again next cycle, nothing is lost
        for m in mints:
            best[m] = pick_best_pair([p for p in pairs if (p.get("baseToken") or {}).get("address") == m], m)
        sp = pick_best_pair([p for p in pairs if (p.get("baseToken") or {}).get("address") == SOL_MINT], SOL_MINT)
        try:
            sol1 = float(sp.get("priceUsd")) if sp else None
        except (TypeError, ValueError):
            sol1 = None

    recent = []
    for pid, d in preds.items():
        cmds += [["ZREM", "due", pid], ["DEL", f"pred:{pid}"]]
        age = now - int(d.get("ts") or 0)
        if age > PRED_HORIZON_S * 3:
            continue  # judged far too late (server was asleep): would distort the stats
        p0, l0 = float(d.get("price") or 0), float(d.get("liq") or 0)
        pair = best.get(d["mint"])
        if pair is None:
            ret, liq_ratio = -100.0, 0.0
        else:
            p1 = float(pair.get("priceUsd") or 0)
            l1 = float((pair.get("liquidity") or {}).get("usd") or 0)
            ret = (p1 / p0 - 1) * 100 if p0 > 0 else 0.0
            liq_ratio = l1 / l0 if l0 > 0 else 1.0
        bad = ret <= BAD_RETURN_PCT or liq_ratio <= BAD_LIQ_RATIO
        # market background: how much did SOL itself move over the same window?
        sol0 = float(d.get("sol") or 0)
        sol_ret = (sol1 / sol0 - 1) * 100 if (sol1 and sol0 > 0) else None
        xret = ret - sol_ret if sol_ret is not None else None
        v, c = d.get("verdict", "?"), d.get("conf", "?")
        bucket = min(9, int(float(d.get("score") or 0)) // 10)
        day = time.strftime("%Y%m%d", time.gmtime(int(d.get("ts") or 0)))
        flags_t = [f for f in (d.get("flags") or "").split(",") if f in RISK_WEIGHTS]
        groups = ["all", f"v:{v}:{c}", f"rb:{bucket}", f"d:{day}"]
        groups += [f"f:{f}" for f in flags_t] + [f"fd:{f}:{day}" for f in flags_t]
        base_pred = "avoid" if BASELINE_FLAGS & set((d.get("flags") or "").split(",")) else "ok"
        groups += [f"vd:{v}:{c}:{day}", f"bl:{base_pred}", f"bd:{base_pred}:{day}"]  # per-day verdicts + the simple baseline
        for g in groups:
            cmds.append(["HINCRBY", "st", f"{g}:n", 1])
            if bad:
                cmds.append(["HINCRBY", "st", f"{g}:bad", 1])
        cmds.append(["HINCRBYFLOAT", "st", f"v:{v}:{c}:ret", round(ret, 2)])
        if xret is not None:
            cmds += [["HINCRBYFLOAT", "st", f"v:{v}:{c}:xret", round(xret, 2)], ["HINCRBY", "st", f"v:{v}:{c}:xn", 1]]
        recent.append(json.dumps({"token": d.get("token"), "mint": d["mint"], "verdict": v, "risk_score": float(d.get("score") or 0),
                                  "return_pct": round(ret, 1), "sol_return_pct": round(sol_ret, 1) if sol_ret is not None else None,
                                  "excess_return_pct": round(xret, 1) if xret is not None else None,
                                  "bad_outcome": bad, "age_h": round(age / 3600, 1)}))
    for item in recent:
        cmds.append(["LPUSH", "recent", item])
    if recent:
        cmds.append(["LTRIM", "recent", 0, 49])
    if cmds:
        await redis_pipe(client, cmds)
    return len(ids)


async def refresh_raw_stats(client: httpx.AsyncClient, force: bool = True):
    if not PRED_ENABLED:
        return
    if not force and _raw_st["st"] and time.time() - _raw_st["ts"] < RAW_ST_TTL:
        return
    res = await redis_pipe(client, [["HGETALL", "st"]])
    if res:
        _raw_st.update(ts=time.time(), st=to_dict(res[0]))


def _day_in(day: str, span: Optional[int], now: float) -> bool:
    if span is None:
        return True
    try:
        return now - calendar.timegm(time.strptime(day, "%Y%m%d")) <= span * 86400
    except ValueError:
        return False


def _metrics(pos_n: int, pos_bad: int, total: int, total_bad: int) -> dict:
    """What happens if we treat the flagged group as the prediction 'this ends badly'."""
    tp, fp = pos_bad, pos_n - pos_bad
    fn, tn = total_bad - pos_bad, (total - total_bad) - (pos_n - pos_bad)

    def pct(a: int, b: int) -> Optional[float]:
        return round(a / b * 100, 1) if b >= MIN_N_SHOW else None

    ci = wilson(tp, pos_n) if pos_n >= MIN_N_SHOW else None
    return {"flagged": pos_n, "precision_pct": pct(tp, pos_n),
            "precision_ci95_pct": [round(x * 100, 1) for x in ci] if ci else None,
            "recall_pct": pct(tp, total_bad), "false_positive_rate_pct": pct(fp, fp + tn),
            "true_positive": tp, "false_positive": fp, "missed_bad": fn, "true_negative": tn}


def performance_from(st: dict, now: Optional[float] = None) -> dict:
    """Precision / recall / false-positive rate of our verdicts vs a simple baseline, per time window."""
    now = now or time.time()
    out: Dict[str, Any] = {}
    for name, span in (("all_tracked", None), ("last_30d", 30), ("last_7d", 7)):
        ours = {v: [0, 0] for v in ("ok", "caution", "avoid")}
        base = {v: [0, 0] for v in ("ok", "avoid")}
        days = set()
        for k, val in st.items():
            p = k.split(":")
            if len(p) == 5 and p[0] == "vd" and p[4] in ("n", "bad") and p[1] in ours and _day_in(p[3], span, now):
                ours[p[1]][0 if p[4] == "n" else 1] += int(val)
                days.add(p[3])
            elif len(p) == 4 and p[0] == "bd" and p[3] in ("n", "bad") and p[1] in base and _day_in(p[2], span, now):
                base[p[1]][0 if p[3] == "n" else 1] += int(val)
        total, bad = sum(x[0] for x in ours.values()), sum(x[1] for x in ours.values())
        b_total, b_bad = sum(x[0] for x in base.values()), sum(x[1] for x in base.values())
        out[name] = {
            "days_covered": len(days), "judged": total, "bad_outcomes": bad,
            "verdicts": {v: {"n": n, "bad_outcome_rate_pct": round(b / n * 100, 1) if n >= MIN_N_SHOW else None,
                             "ci95_pct": [round(x * 100, 1) for x in wilson(b, n)] if n >= MIN_N_SHOW else None}
                         for v, (n, b) in ours.items()},
            "ours_avoid": _metrics(ours["avoid"][0], ours["avoid"][1], total, bad),
            "ours_avoid_or_caution": _metrics(ours["avoid"][0] + ours["caution"][0], ours["avoid"][1] + ours["caution"][1], total, bad),
            "baseline_avoid": _metrics(base["avoid"][0], base["avoid"][1], b_total, b_bad),
        }
    return out


def calibration_for(r: dict) -> Optional[dict]:
    """What happened to similar past verdicts. NOT the chance that this particular token fails."""
    st = _raw_st["st"]
    if not st:
        return None
    b = min(9, int(r.get("risk_score") or 0) // 10)
    n, bad = int(st.get(f"rb:{b}:n", 0)), int(st.get(f"rb:{b}:bad", 0))
    if n < MIN_N_SHOW:
        return None
    lo, hi = wilson(bad, n)
    return {"basis": f"judged tokens with a risk score of {b * 10}-{b * 10 + 9}", "n": n,
            "bad_outcome_rate": round(bad / n, 3), "ci95": [round(lo, 3), round(hi, 3)],
            "horizon_hours": round(PRED_HORIZON_S / 3600, 1),
            "meaning": "Share of similar past verdicts that ended badly. Not the chance that this token will fail."}


_with_quality_v23 = with_quality


def with_quality(result: dict, status: str, security: bool) -> dict:
    out = _with_quality_v23(result, status, security)
    if PRED_ENABLED:
        if time.time() - _raw_st["ts"] > RAW_ST_TTL:
            _raw_st["ts"] = time.time()  # one refresh per interval, in the background
            schedule(refresh_raw_stats(app.state.client))
        ctx = calibration_for(out)
        if ctx:
            out["track_record_context"] = ctx
    return out


_compact_v23 = compact_signal


def compact_signal(r: dict) -> dict:
    out = _compact_v23(r)
    ctx = r.get("track_record_context")
    if ctx:
        out["track_record_context"] = {k: ctx[k] for k in ("n", "bad_outcome_rate", "ci95")}
    return out


_stats_report_v23 = stats_report


async def stats_report(client: httpx.AsyncClient) -> dict:
    rep = await _stats_report_v23(client)
    if rep.get("enabled") and rep.get("available") is not False:
        await refresh_raw_stats(client, force=False)
        rep = dict(rep, performance=performance_from(_raw_st["st"]))
    return rep

# --- part16 ---
# ---------- v2.4: methodology page and the new accuracy-page sections ----------
# Adds or replaces things from earlier parts (same shared namespace). Loads before part7 (MCP).


def methodology_report() -> dict:
    """Everything that decides a verdict, in the open."""
    return {
        "version": VERSION,
        "verdict_rules": {
            "summary": ("avoid if any avoid-flag is present or the risk score is 50 or more; caution if any caution-flag is present "
                        "or the score is 25 or more; otherwise ok. Majors (wrapped SOL, USDC, USDT) skip rug-style checks; "
                        "established tokens (liquidity $1M+, older than 30 days) show them without scoring them."),
            "avoid_flags": list(AVOID_FLAGS), "caution_flags": list(CAUTION_FLAGS),
            "rug_style_flags": sorted(RUG_STYLE_FLAGS), "avoid_score_threshold": 50, "caution_score_threshold": 25,
        },
        "risk_score": {
            "how": "sum of the weights of the flags present, capped at 100",
            "scoring": "tuned" if _tune["on"] else "static",
            "weights_in_use": dict(sorted(ACTIVE_WEIGHTS.items())),
            "weights_default": dict(sorted(RISK_WEIGHTS.items())),
        },
        "auto_tune": {
            "enabled": AUTO_TUNE, "currently_tuned": bool(_tune["on"]), "judged_samples": _tune["n"],
            "how": ("Each flag's weight is blended (at most 50%) toward a value suggested by how much that flag raised the "
                    "bad-outcome rate versus the same day's overall rate. It only starts once a flag has 30+ judged samples and "
                    "100+ judged tokens exist. Default: off."),
        },
        "outcomes": {
            "horizon_hours": round(PRED_HORIZON_S / 3600, 1),
            "bad_outcome": f"price down {abs(BAD_RETURN_PCT):.0f}%+, or liquidity down {round((1 - BAD_LIQ_RATIO) * 100)}%+, or the pair disappeared",
            "judged": "every verdict is stored, then judged once after the horizon; a tamper-evident hash chain is at /ledger",
            "minimum_samples_to_show_a_rate": MIN_N_SHOW,
        },
        "baseline": {
            "definition": "avoid anything with liquidity under $50k or a pair younger than 6 hours",
            "why": "A signal that cannot beat two simple rules is not worth the complexity. The accuracy page shows both side by side.",
        },
        "data_sources": ["DexScreener (market)", "Solana RPC (authorities, holders)", "RugCheck (LP lock)", "Jupiter (exit quotes)"],
        "limits": [
            "Verdicts are heuristics, not advice and not a security audit.",
            "Only tokens that people query are measured, not a random sample of the market.",
            "A bad outcome can come from ordinary market moves, not only from rugs.",
            "A Jupiter quote does not prove a real sell will succeed.",
        ],
    }


@app.get("/methodology", tags=["trust"], summary="Exactly how verdicts and risk scores are computed")
async def methodology_route(request: Request):
    wait = rate_limited(client_ip(request))
    if wait:
        raise too_many(wait)
    return JSONResponse(content=methodology_report(), headers={"Cache-Control": "public, max-age=300"})


def _pc(v: Any) -> str:
    return "-" if v is None else _h(f"{v}%")


def render_performance(perf: dict) -> str:
    rows = ""
    for key, label in (("all_tracked", "Since tracking started"), ("last_30d", "Last 30 days"), ("last_7d", "Last 7 days")):
        w = perf.get(key) or {}
        a, b = w.get("ours_avoid") or {}, w.get("baseline_avoid") or {}
        rows += ("<tr><td>" + _h(label) + "</td><td>" + _h(w.get("judged", 0)) + "</td><td>" + _h(a.get("flagged", 0)) + "</td>"
                 "<td>" + _pc(a.get("precision_pct")) + "</td><td>" + _pc(a.get("recall_pct")) + "</td><td>" + _pc(a.get("false_positive_rate_pct")) + "</td>"
                 "<td>" + _pc(b.get("precision_pct")) + "</td><td>" + _pc(b.get("recall_pct")) + "</td><td>" + _pc(b.get("false_positive_rate_pct")) + "</td></tr>")
    return ('<h2>Our "avoid" against a simple baseline</h2><p class="muted">Precision: of the tokens flagged, how many ended badly. '
            "Recall: of all bad outcomes, how many we flagged. False positives: of the tokens that did fine, how many we flagged anyway. "
            "Baseline: avoid anything with liquidity under $50k or a pair younger than 6 hours. A number stays hidden until it rests on "
            "20+ samples. If we do not beat the baseline, this table will show it.</p>"
            "<table><tr><th>Window</th><th>Judged</th><th>Flagged</th><th>Precision</th><th>Recall</th><th>False pos.</th>"
            "<th>Base precision</th><th>Base recall</th><th>Base false pos.</th></tr>" + rows + "</table>")


def render_methodology() -> str:
    m = methodology_report()
    weights = sorted(m["risk_score"]["weights_in_use"].items(), key=lambda kv: -kv[1])
    rows = "".join("<tr><td>" + _h(k) + "</td><td>" + _h(v) + "</td></tr>" for k, v in weights if v)
    tune = m["auto_tune"]
    return ('<h2>Methodology</h2><p class="muted">' + _h(m["verdict_rules"]["summary"]) + "</p>"
            '<p class="muted">Weights in use are ' + _h(m["risk_score"]["scoring"]) + ". Auto-tuning is "
            + ("on" if tune["enabled"] else "off") + ". " + _h(tune["how"]) + "</p>"
            "<table><tr><th>Flag</th><th>Points</th></tr>" + rows + "</table>"
            '<p class="muted">Machine-readable version: <a href="/methodology">/methodology</a></p>')


_render_accuracy_v23 = render_accuracy


def render_accuracy(rep: dict, head: Optional[str]) -> str:
    page = _render_accuracy_v23(rep, head)
    extra = (render_performance(rep["performance"]) if rep.get("performance") else "") + render_methodology()
    marker = "<h2>How we measure</h2>"
    return page.replace(marker, extra + marker, 1) if marker in page else page


LLMS_TXT = LLMS_TXT + """
## Methodology and performance
GET /methodology: the exact rules, thresholds, weights in use, auto-tuning rules, baseline and limits.
GET /stats now includes `performance`: precision, recall and false-positive rate of our "avoid" per window (since tracking started,
30 days, 7 days) next to a simple baseline (liquidity under $50k or pair younger than 6 hours). Rates stay null below 20 samples.
Signals can carry `track_record_context`: how similar past verdicts (same risk-score band) ended, with n and a 95% interval.
It is a historical rate, not the chance that this token will fail.
"""

# --- part17 ---
# ---------- v2.5: operator diagnostics, remembered exit checks, hypothesis flags, pricing page ----------
# Adds or replaces things from earlier parts (same shared namespace). Loads before part7 (MCP).
import platform

VERSION = "2.5.0"
app.version = VERSION
app.openapi_schema = None  # rebuild /docs with the new version

# --- /health: tell the operator exactly what is switched on and what is missing (never any secret values) ---
_redis_state: Dict[str, Any] = {"ts": 0.0, "ok": None}


async def redis_status(client: Optional[httpx.AsyncClient]) -> dict:
    missing = [name for name, value in (("UPSTASH_REDIS_REST_URL", REDIS_URL), ("UPSTASH_REDIS_REST_TOKEN", REDIS_TOKEN)) if not value]
    if missing:
        return {"configured": False, "missing_env": missing}
    if client is not None and time.time() - _redis_state["ts"] > 300:
        res = await redis_pipe(client, [["PING"]])
        _redis_state.update(ts=time.time(), ok=bool(res) and res[0] == "PONG")
    return {"configured": True, "reachable": _redis_state["ok"]}


_drop_route("/health")


@app.get("/health", tags=["ops"], summary="Service status and what is switched on")
async def health():
    return {
        "status": "ok", "version": VERSION, "uptime_s": int(time.time() - _m["started"]), "python": platform.python_version(),
        "cache_size": len(_cache), "rpc": "custom" if os.getenv("SOLANA_RPC_URL") else "public", "mcp": mcp_server is not None,
        "mcp_error": mcp_error, "jupiter_key": bool(JUP_KEY), "track_record": PRED_ENABLED,
        "track_record_store": await redis_status(getattr(app.state, "client", None)), "auto_tune": AUTO_TUNE,
        "api_keys_configured": len(API_KEYS), "streams": {"watching": len(_watchers), "open": sum(_stream_open.values())},
        "sources": src_status(),
    }


# --- an exit check you made recently follows the token: no_sell_route / high_exit_cost become real flags ---
EXIT_MEMORY_S = 600
_exit_seen: Dict[str, tuple] = {}
REASONS["no_sell_route"] = "No sell route was found on Jupiter when it was checked a few minutes ago"
REASONS["high_exit_cost"] = "Selling would lose a large part of the value to fees and price impact (checked recently)"
for _flag, _weight in (("no_sell_route", 40), ("high_exit_cost", 20)):
    RISK_WEIGHTS.setdefault(_flag, _weight)
    ACTIVE_WEIGHTS.setdefault(_flag, _weight)
if "no_sell_route" not in AVOID_FLAGS:
    AVOID_FLAGS.append("no_sell_route")
if "high_exit_cost" not in CAUTION_FLAGS:
    CAUTION_FLAGS.append("high_exit_cost")
_exit_check_v24 = exit_check


async def exit_check(client: httpx.AsyncClient, mint: str, sizes: List[float], sig: dict) -> dict:
    result = await _exit_check_v24(client, mint, sizes, sig)
    if result.get("available"):
        _exit_seen[mint] = (time.time(), result.get("grade"))
        if len(_exit_seen) > 2000:
            for old in sorted(_exit_seen, key=lambda m: _exit_seen[m][0])[:1000]:
                _exit_seen.pop(old, None)
    return result


def _fresh_exit(mint: Optional[str]):
    seen = _exit_seen.get(mint) if mint else None
    return seen if seen and time.time() - seen[0] <= EXIT_MEMORY_S else None


# --- hypotheses: flags that are shown and MEASURED, but not scored (weight 0) until the track record supports them ---
HYPOTHESES = {
    "late_entry_risk": "Up 100%+ in the last hour on a pair younger than a day: late entry into a pump",
    "one_sided_flow": "Over 90% of the last 5 minutes of trades were on one side, with high activity",
    "no_recent_trades": "No trades in the last 5 minutes: price and exit quotes are less reliable",
}
for _flag in HYPOTHESES:
    RISK_WEIGHTS.setdefault(_flag, 0)
    ACTIVE_WEIGHTS.setdefault(_flag, 0)


def add_hypothesis_flags(r: dict):
    flags = r["flags"]
    age = r.get("pair_age_minutes")
    if (((r.get("price_change_pct") or {}).get("1h")) or 0) >= 100 and age is not None and age < 1440:
        flags.append("late_entry_risk")
    trades = (r.get("buys_5m") or 0) + (r.get("sells_5m") or 0)
    bp = r.get("buy_pressure_5m")
    if bp is not None and trades >= 50 and (bp >= 0.9 or bp <= 0.1):
        flags.append("one_sided_flow")
    if trades == 0:
        flags.append("no_recent_trades")


_finalize_risk_v24 = finalize_risk


def finalize_risk(result: dict, onchain: bool):
    seen = _fresh_exit(result.get("mint"))
    if seen and seen[1] == "no_route":
        result["flags"].append("no_sell_route")
    elif seen and seen[1] in ("poor", "very_poor"):
        result["flags"].append("high_exit_cost")
    add_hypothesis_flags(result)
    _finalize_risk_v24(result, onchain)


_with_quality_v24 = with_quality


def with_quality(result: dict, status: str, security: bool) -> dict:
    out = _with_quality_v24(result, status, security)
    seen, d = _fresh_exit(out.get("mint")), out.get("decision")
    if d and seen:
        unknowns = [u for u in d.get("unknowns", []) if not u.startswith("Exit cost not checked")]
        out["decision"] = dict(d, unknowns=unknowns, exit_grade=seen[1])
    return out


# --- pricing and limits: always generated from the live settings, so the page cannot drift from the code ---
CONTACT_URL = os.getenv("CONTACT_URL", "")


def render_pricing() -> str:
    link = (f'<a href="{_h(CONTACT_URL)}">{_h(CONTACT_URL)}</a>' if CONTACT_URL.startswith("https://")
            else "the contact link of this project (see the GitHub page)")
    rows = (
        f"<tr><td><b>Free</b><br><span class='muted'>no key</span></td><td>{RATE_LIMIT} requests/min per IP</td><td>up to {MAX_BATCH} tokens</td>"
        f"<td>{STREAM_MAX_PER_IP} open streams</td><td>everything below, including MCP</td><td>$0</td></tr>"
        f"<tr><td><b>API key</b><br><span class='muted'>issued by hand</span></td><td>{KEY_RATE_LIMIT} requests/min</td><td>up to {MAX_BATCH} tokens</td>"
        f"<td>{STREAM_MAX_PER_KEY} open streams</td><td>its own reserved lane of {GLOBAL_KEY_RESERVE} upstream requests/min, "
        "so heavy anonymous traffic cannot lock it out</td><td>free during the beta</td></tr>"
        "<tr><td><b>Pay per call</b></td><td colspan='4'>Under evaluation (the x402 standard). Not available yet.</td><td>-</td></tr>")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVibex402 pricing and limits</title><style>
:root{{--bg:#070b12;--card:rgba(18,25,35,.8);--line:rgba(34,48,66,.8);--text:#e8eef6;--muted:#8b9bb4;--a:#14f195;--b:#9945ff}}
*{{box-sizing:border-box;margin:0;padding:0}}body{{background:var(--bg);color:var(--text);font-family:system-ui,sans-serif;line-height:1.55}}
.wrap{{max-width:820px;margin:0 auto;padding:32px 16px 70px}}h1{{font-size:2rem;background:linear-gradient(120deg,var(--b),var(--a));-webkit-background-clip:text;background-clip:text;color:transparent}}
h2{{font-size:1.1rem;margin:26px 0 10px}}.muted{{color:var(--muted);font-size:.88rem}}table{{width:100%;border-collapse:collapse;font-size:.9rem;display:block;overflow-x:auto}}
th,td{{text-align:left;padding:10px;border-bottom:1px solid var(--line);vertical-align:top}}li{{margin:6px 0 6px 18px}}a{{color:var(--a)}}
</style></head><body><div class="wrap"><h1>Pricing and limits</h1>
<p class="muted">Free first. These numbers are read from the running server, so they are always the real ones.</p>
<table><tr><th>Plan</th><th>Rate</th><th>Batch</th><th>Live streams</th><th>Also</th><th>Price</th></tr>{rows}</table>
<h2>What always stays free</h2><ul>
<li><a href="/accuracy">/accuracy</a>, <a href="/methodology">/methodology</a> and <a href="/ledger">/ledger</a>: measured results and the exact rules, in the open.</li>
<li>The MCP server at <code>/mcp</code> and the docs at <a href="/docs">/docs</a> and <a href="/llms.txt">/llms.txt</a>.</li></ul>
<h2>Getting a key</h2><p class="muted">Keys are issued by hand during the beta. Ask at {link} and say what you are building and how many requests you expect.</p>
<h2>Honest limits</h2><ul class="muted"><li>No uptime guarantee. The free host can sleep; clients should retry after a 503.</li>
<li>Verdicts are heuristics, not advice and not a security audit. A sell quote is not proof a sell will succeed.</li>
<li>Data comes from DexScreener, Solana RPC, RugCheck and Jupiter and can be late or wrong.</li></ul>
<p class="muted" style="margin-top:20px"><a href="/">Home</a></p></div></body></html>"""


@app.get("/pricing", response_class=HTMLResponse, tags=["ops"], summary="Plans, limits and how to get an API key")
async def pricing_page():
    return render_pricing()


if '<a href="/accuracy">/accuracy</a>' in HOME_HTML and "/pricing" not in HOME_HTML:
    HOME_HTML = HOME_HTML.replace('<a href="/accuracy">/accuracy</a>', '<a href="/accuracy">/accuracy</a> &bull; <a href="/pricing">/pricing</a>', 1)

LLMS_TXT = LLMS_TXT + """
## Limits, keys and pricing
GET /pricing lists the plans and the live limits. Free: no key. An X-API-Key header (issued by hand during the beta) gives a higher
rate limit and its own reserved lane in the shared upstream budget. Pay-per-call is not available yet.

## Hypothesis flags (shown, measured, not scored)
late_entry_risk, one_sided_flow, no_recent_trades. They carry weight 0 until /accuracy shows that they predict bad outcomes.
After an exit check, no_sell_route (avoid) and high_exit_cost (caution) also attach to later signals for that token for ten minutes.
"""

# --- part18 ---
# ---------- v2.6: Holder Quality + Dip Absorption ----------
# Không override with_quality nữa để tránh đệ quy với part19.
VERSION = "2.6.0"
app.version = VERSION
app.openapi_schema = None

REASONS["holders_stable"] = "Top holders largely unchanged (conviction)"
REASONS["holders_churning"] = "Significant turnover among top holders"
REASONS["whale_accumulating"] = "Largest holders appear to be adding"
REASONS["whale_dumping"] = "Largest holders appear to be reducing"
REASONS["dip_absorbed"] = "Price drop met with solid buy pressure"
REASONS["weak_absorption"] = "Price drop with weak buy support"

for flag, weight in (
    ("holders_churning", 14),
    ("whale_dumping", 18),
    ("weak_absorption", 11),
    ("holders_stable", 0),
    ("whale_accumulating", 0),
    ("dip_absorbed", 0),
):
    RISK_WEIGHTS.setdefault(flag, weight)
    ACTIVE_WEIGHTS.setdefault(flag, weight)

for flag in ("holders_churning", "whale_dumping", "weak_absorption"):
    if flag not in CAUTION_FLAGS:
        CAUTION_FLAGS.append(flag)

HOLDER_CACHE_TTL = 8 * 3600
HOLDER_CACHE_KEY = "hq:{}"


def _top_owners(sec, n=5):
    holders = sec.get("top_holders") or []
    out = []
    for h in holders:
        owner = h.get("owner") or h.get("address")
        pct = h.get("pct") or h.get("percentage")
        if owner and pct is not None and owner not in KNOWN_NON_HOLDERS:
            try:
                out.append((owner, float(pct)))
            except (TypeError, ValueError):
                continue
        if len(out) >= n:
            break
    return out


def _concentration_score(top10):
    if top10 is None:
        return 50.0
    if top10 >= 80:
        return 12.0
    if top10 >= 60:
        return 35.0
    if top10 >= 45:
        return 55.0
    if top10 >= 30:
        return 75.0
    return 92.0


def _stability_score(curr, prev):
    if not curr or not prev:
        return 50.0
    prev_map = {o: p for o, p in prev}
    shared = 0.0
    for o, p in curr:
        if o in prev_map:
            shared += min(p, prev_map[o])
    return max(0.0, min(100.0, shared * 1.15))


def _absorption_score(result):
    pc = result.get("price_change_pct") or {}
    h1 = pc.get("1h") or 0
    h6 = pc.get("6h") or 0
    bp = result.get("buy_pressure_5m")
    trades = (result.get("buys_5m") or 0) + (result.get("sells_5m") or 0)
    if bp is None or trades < 8:
        return 50.0
    if h1 <= -12 or h6 <= -20:
        if bp >= 0.58:
            return 88.0
        if bp >= 0.45:
            return 68.0
        if bp <= 0.32:
            return 22.0
        return 40.0
    return 55.0


def compute_holder_quality(result, prev_tops=None):
    sec = result.get("security") or {}
    top10 = sec.get("top10_holders_pct")
    curr_tops = _top_owners(sec, 5)
    conc = _concentration_score(top10)
    stab = _stability_score(curr_tops, prev_tops or [])
    abso = _absorption_score(result)
    hq = round(0.40 * conc + 0.35 * stab + 0.25 * abso)

    flags = []
    if stab >= 72:
        flags.append("holders_stable")
    elif stab <= 38 and prev_tops:
        flags.append("holders_churning")

    if prev_tops and curr_tops:
        prev_map = {o: p for o, p in prev_tops}
        gained = sum(max(0.0, p - prev_map.get(o, 0.0)) for o, p in curr_tops)
        lost = sum(max(0.0, prev_map.get(o, 0.0) - p) for o, p in curr_tops)
        if gained >= 8.0 and gained > lost * 1.4:
            flags.append("whale_accumulating")
        elif lost >= 8.0 and lost > gained * 1.4:
            flags.append("whale_dumping")

    if abso >= 78:
        flags.append("dip_absorbed")
    elif abso <= 28:
        flags.append("weak_absorption")

    return {
        "score": hq,
        "flags": flags,
        "concentration": round(conc, 1),
        "stability": round(stab, 1),
        "absorption": round(abso, 1),
        "top_owners": curr_tops,
    }


async def _load_prev_tops(client, mint: str):
    if not PRED_ENABLED or not client:
        return None
    try:
        raw = await redis_get(client, HOLDER_CACHE_KEY.format(mint))
        if raw:
            import json
            return json.loads(raw)
    except Exception:
        pass
    return None


async def _save_curr_tops(client, mint: str, tops):
    if not PRED_ENABLED or not client or not tops:
        return
    try:
        import json
        await redis_set(client, HOLDER_CACHE_KEY.format(mint), json.dumps(tops), HOLDER_CACHE_TTL)
    except Exception:
        pass


async def attach_holder_quality(client, mint: str, result: dict):
    """Gọi sau khi có security data. An toàn, không đệ quy."""
    prev = await _load_prev_tops(client, mint)
    hq = compute_holder_quality(result, prev)
    result["holder_quality"] = {
        "score": hq["score"],
        "flags": hq["flags"],
        "concentration": hq["concentration"],
        "stability": hq["stability"],
        "absorption": hq["absorption"],
    }
    for f in hq["flags"]:
        if f not in result.get("flags", []):
            result.setdefault("flags", []).append(f)
    await _save_curr_tops(client, mint, hq["top_owners"])
    return result
# ---------- gắn holder_quality vào pipeline chính ----------
_build_signal_v26 = build_signal


async def build_signal(client: httpx.AsyncClient, mint: str, security: bool, prefetched: Optional[dict] = None):
    result, status = await _build_signal_v26(client, mint, security, prefetched)
    if security and result.get("security"):
        try:
            result = await attach_holder_quality(client, mint, result)
        except Exception:
            pass  # không làm hỏng signal nếu Redis lỗi
    return result, status

# --- part19 ---
# ---------- part19: v2.7.2 (consolidated: v2.6.0 .. v2.7.1 merged, duplicates removed) ----------
# Soli Deo Gloria - to the glory of God alone.
# Work wholeheartedly, as working for the Lord (Colossians 3:23).
# May this product be honest, useful to the people who rely on it, and never promise what it cannot keep.
#
# Adds or replaces things from earlier parts (same shared namespace). Loads before part7 (MCP).
VERSION = "2.7.2"
app.version = VERSION
app.openapi_schema = None  # rebuild /docs with the new version

# --- cybernetics (negative feedback): when the main market source struggles, answers live longer so we lean on it less ---
BASE_CACHE_TTL = 30
STALE_MAX = max(STALE_MAX, 900)      # stale answers may be served for up to 15 minutes
PARTIAL_TTL = max(PARTIAL_TTL, 15)   # partial answers live a little longer


def homeostat() -> int:
    """When DexScreener is degraded or down, keep answers in cache longer."""
    global CACHE_TTL
    status = (src_status().get("dexscreener") or {}).get("status")
    CACHE_TTL = BASE_CACHE_TTL * {"degraded": 3, "down": 6}.get(status, 1)
    return CACHE_TTL


# --- pre-mortem (mental models): for every reason against a token, what would have to change for it to go away? ---
CHANGE_IF = {
    "mint_authority_active": "the mint authority is revoked",
    "freeze_authority_active": "the freeze authority is revoked",
    "lp_not_locked": "most of the liquidity is locked or burned",
    "lp_partially_locked": "at least 80% of the liquidity is locked or burned",
    "lp_unverified": "the pool's LP tokens are checked on a block explorer and shown to be burned or locked",
    "very_low_liquidity": "liquidity rises above $20k (above $50k to clear the next level)",
    "low_liquidity": "liquidity rises above $50k",
    "extreme_holder_concentration": "the top 10 real holders fall below 80% of supply (below 50% to clear the next level)",
    "high_holder_concentration": "the top 10 real holders fall below 50% of supply",
    "dominant_holder": "no single real holder owns 20% or more",
    "brand_new_pair": "the pair is older than 1 hour",
    "very_new_pair": "the pair is older than 6 hours",
    "dump_risk": "the price stops falling on both the 5 minute and 1 hour view",
    "extreme_turnover": "1h volume falls well below the liquidity",
    "no_sell_route": "a sell route appears on Jupiter",
    "high_exit_cost": "a fresh exit check shows a much smaller loss",
    "transfer_fee_extreme": "the issuer lowers the transfer fee below 25%",
    "transfer_fee_high": "the issuer lowers the transfer fee below 5%",
    "permanent_delegate_active": "the issuer removes the permanent delegate (rarely possible)",
    "default_account_frozen": "the issuer changes the default account state",
    "transfer_hook_active": "the issuer removes the transfer hook",
}


def would_change_if(out: dict, decision: dict) -> list:
    """Conditions, not predictions. Only for reasons that are actually part of this decision."""
    shown = set(decision.get("blockers") or []) | set(decision.get("cautions") or [])
    items = []
    for flag in out.get("flags") or []:
        if flag in CHANGE_IF and REASONS.get(flag) in shown:
            items.append({"flag": flag, "if": CHANGE_IF[flag]})
    return items[:6]


# --- volatility sets how long a reading stays useful (decision under pressure) ---
FAST_FLAGS = {"strong_momentum", "volume_spike", "extreme_volume_spike", "late_entry_risk", "dump_risk", "one_sided_flow"}


def valid_for(out: dict) -> int:
    flags = set(out.get("flags") or [])
    fast = bool(FAST_FLAGS & flags) or (out.get("pair_age_minutes") is not None and out["pair_age_minutes"] < 60)
    if fast:
        return 10
    return 120 if out.get("asset_class") in ("major", "established") else 30


# --- shadow flags: shown and measured, NOT scored (part8 scores with ACTIVE_WEIGHTS.get(flag, 0)) ---
DEAD_POOL_LIQ_USD = 5_000      # below this, with no recent trades, a sell is unlikely to go through
COLLAPSE_24H_PCT = -50.0       # price already lost half of its value in 24h
HYPOTHESES["dead_pool"] = "a pool under $5k liquidity with no recent trades is effectively untradeable (should be avoid)"
HYPOTHESES["price_collapse_24h"] = "a token that already lost 50%+ in 24h keeps losing (momentum of the dump)"

# LP flags are noise for majors like SOL
MAJOR_NOISE_FLAGS = {"lp_not_locked", "lp_partially_locked", "lp_unverified"}


def _tidy_major_flags(out: dict) -> None:
    if out.get("asset_class") != "major":
        return
    if out.get("flags"):
        out["flags"] = [f for f in out["flags"] if f not in MAJOR_NOISE_FLAGS]
    if out.get("flags_not_scored"):
        left = [f for f in out["flags_not_scored"] if f not in MAJOR_NOISE_FLAGS]
        if left:
            out["flags_not_scored"] = left
        else:
            out.pop("flags_not_scored", None)


def _add_shadow_flags(out: dict) -> None:
    flags = out.get("flags")
    if not isinstance(flags, list):
        return
    quiet = "no_recent_trades" in flags or (out.get("volume_1h") or 0) == 0
    if (out.get("liquidity_usd") or 0) < DEAD_POOL_LIQ_USD and quiet and "dead_pool" not in flags:
        flags.append("dead_pool")
    change = (out.get("price_change_pct") or {}).get("24h")
    if change is not None and change <= COLLAPSE_24H_PCT and "price_collapse_24h" not in flags:
        flags.append("price_collapse_24h")


# --- fallback market data: GeckoTerminal, used only when DexScreener refuses ---
_GT_URL = "https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}/pools?include=base_token,quote_token&page=1"
_GT_HEADERS = {"Accept": "application/json;version=20230302"}
_GT_COOLDOWN = {"until": 0.0}
_GT_SEM = asyncio.Semaphore(2)
_FALLBACK_MINTS: Dict[str, float] = {}   # mint -> when its data last came from the fallback
_GT_CONFIDENCE_CAP = 0.7


def _gt_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _gt_ms(iso):
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(iso).replace("Z", "+00:00")).timestamp() * 1000)
    except Exception:  # noqa: BLE001
        return None


def gt_to_dex_pairs(payload: dict, mint: str) -> list:
    """GeckoTerminal pools -> DexScreener-style pairs where `mint` is always the base token."""
    toks = {}
    for inc in payload.get("included") or []:
        a = inc.get("attributes") or {}
        if a.get("address"):
            toks[a["address"]] = {"address": a["address"], "name": a.get("name"), "symbol": a.get("symbol")}
    pairs = []
    for pool in payload.get("data") or []:
        a, rel = pool.get("attributes") or {}, pool.get("relationships") or {}

        def addr(key):
            tid = (((rel.get(key) or {}).get("data")) or {}).get("id") or ""
            return tid.split("_", 1)[-1] or None

        base, quote = addr("base_token"), addr("quote_token")
        if mint == base:
            ours, other, price, idx = base, quote, a.get("base_token_price_usd"), 0
        elif mint == quote:
            ours, other, price, idx = quote, base, a.get("quote_token_price_usd"), 1
        else:
            continue
        names = str(a.get("name") or "").split(" / ")
        base_tok = toks.get(ours) or {"address": ours, "symbol": names[idx] if len(names) == 2 else None}
        tx, vol, chg = a.get("transactions") or {}, a.get("volume_usd") or {}, a.get("price_change_percentage") or {}
        pairs.append({
            "chainId": "solana",
            "dexId": (((rel.get("dex") or {}).get("data")) or {}).get("id"),
            "pairAddress": a.get("address"),
            "baseToken": base_tok,
            "quoteToken": toks.get(other) or {"address": other},
            "priceUsd": price,
            "txns": {k: {"buys": (tx.get(k) or {}).get("buys"), "sells": (tx.get(k) or {}).get("sells")}
                     for k in ("m5", "h1", "h24") if k in tx},
            "volume": {k: _gt_float(vol.get(k)) for k in ("m5", "h1", "h6", "h24") if k in vol},
            "priceChange": {k: _gt_float(chg.get(k)) for k in ("m5", "h1", "h6", "h24") if k in chg},
            "liquidity": {"usd": _gt_float(a.get("reserve_in_usd"))},
            "fdv": _gt_float(a.get("fdv_usd")),
            "marketCap": _gt_float(a.get("market_cap_usd")),
            "pairCreatedAt": _gt_ms(a.get("pool_created_at")),
        })
    pairs.sort(key=lambda p: (p["liquidity"]["usd"] or 0), reverse=True)
    return pairs


def _mark_fallback(out: dict) -> None:
    if out.get("mint") not in _FALLBACK_MINTS:
        return
    out["source"] = "geckoterminal"
    out["source_note"] = ("DexScreener was rate-limiting, so market data comes from GeckoTerminal "
                          "(fewer fields, lower confidence)")
    dq = out.get("data_quality")
    if isinstance(dq, dict):
        dq = dict(dq, fallback_source="geckoterminal")
        dq["data_confidence"] = min(dq.get("data_confidence", 1.0), _GT_CONFIDENCE_CAP)
        out["data_quality"] = dq
    d = out.get("decision")
    if isinstance(d, dict):
        d = dict(d)
        d["confidence"] = min(d.get("confidence", 1.0), _GT_CONFIDENCE_CAP)
        d["unknowns"] = list(d.get("unknowns") or []) + ["Market data came from GeckoTerminal (DexScreener was rate-limiting)"]
        out["decision"] = d


_with_quality_v25 = with_quality


def with_quality(result: dict, status: str, security: bool) -> dict:
    homeostat()
    out = _with_quality_v25(result, status, security)
    d = out.get("decision")
    if d:
        d = dict(d)
        d["valid_for_s"] = 0 if (out.get("data_quality") or {}).get("freshness") == "stale" else valid_for(out)
        if d.get("verdict") != "ok":
            change = would_change_if(out, d)
            if change:
                d["would_change_if"] = change
        out["decision"] = d
    _tidy_major_flags(out)
    _add_shadow_flags(out)
    _mark_fallback(out)
    return out


# --- science vs pseudoscience: the rules for promoting or dropping a hypothesis are fixed BEFORE the data arrives ---
PROMOTE_RULE = "promote when judged >= 100, seen on 7+ days and the market-adjusted lift is >= 1.5"
DROP_RULE = "drop when judged >= 200 and the market-adjusted lift is <= 1.1"


def hypotheses_report(st: dict) -> list:
    rows = {r["flag"]: r for r in flag_stats(st)[0]} if st else {}
    out = []
    for flag, claim in HYPOTHESES.items():
        row = rows.get(flag) or {}
        n, lift = int(row.get("n") or 0), row.get("lift")
        days = len({k.split(":")[2] for k in st if k.startswith(f"fd:{flag}:") and k.endswith(":n")}) if st else 0
        if n >= 200 and lift is not None and lift <= 1.1:
            status = "drop: no real signal"
        elif n >= 100 and days >= 7 and lift is not None and lift >= 1.5:
            status = "promote: measured signal"
        elif n < 100:
            status = "collecting"
        else:
            status = "keep watching"
        out.append({"flag": flag, "claim": claim, "status": status, "judged": n, "days_seen": days, "lift": lift})
    return out


_methodology_v25 = methodology_report


def methodology_report() -> dict:
    m = _methodology_v25()
    m["hypotheses"] = {"rules": [PROMOTE_RULE, DROP_RULE], "under_test": hypotheses_report(_raw_st["st"]),
                       "note": "Shown and measured, not scored. A status only says the numbers are strong enough to decide; weights change only when the operator promotes a flag or turns auto-tuning on."}
    m["adaptive_cache"] = {"base_ttl_s": BASE_CACHE_TTL, "current_ttl_s": CACHE_TTL,
                           "rule": "if the market data source is degraded or down, answers are reused 3x or 6x longer to lean on it less"}
    m["will_not_say"] = ["buy or sell", "price targets", "position sizes", "guarantees of any kind"]
    return m


# --- prediction error: show where the verdicts were wrong, not only where they were right ---
def render_surprises(recent: list) -> str:
    missed = [r for r in recent if r.get("verdict") in ("ok", "caution") and r.get("bad_outcome")][:5]
    false_alarms = [r for r in recent if r.get("verdict") == "avoid" and not r.get("bad_outcome")][:5]
    if not recent:
        return ""

    def rows(items):
        return "".join("<tr><td>" + _h(r.get("token")) + "</td><td>" + _h(r.get("verdict")) + "</td><td>" + _h(r.get("risk_score"))
                       + "</td><td>" + _pc(r.get("return_pct")) + "</td></tr>" for r in items)

    head = "<tr><th>Token</th><th>Verdict</th><th>Risk</th><th>Return</th></tr>"
    body = ('<h2>Biggest surprises</h2><p class="muted">A verdict is a prediction. The gap between it and what happened is what the '
            f"system learns from, so we show the misses too. Among the latest {len(recent)} judged verdicts:</p>")
    body += (f"<p><b>Called ok or caution, ended badly ({len(missed)})</b></p><table>{head}{rows(missed)}</table>" if missed
             else "<p class=\"muted\">No ok or caution verdict ended badly in this sample.</p>")
    body += (f"<p><b>Called avoid, did fine ({len(false_alarms)})</b></p><table>{head}{rows(false_alarms)}</table>" if false_alarms
             else "<p class=\"muted\">No avoid verdict turned out fine in this sample.</p>")
    return body


def render_hypotheses() -> str:
    rep = hypotheses_report(_raw_st["st"])
    rows = "".join("<tr><td>" + _h(h["flag"]) + "</td><td>" + _h(h["claim"]) + "</td><td>" + _h(h["status"]) + "</td><td>" + _h(h["judged"])
                   + "</td><td>" + _h(h["lift"]) + "</td></tr>" for h in rep)
    return ("<h2>Hypotheses under test</h2><p class=\"muted\">Written down before the data: " + _h(PROMOTE_RULE) + "; " + _h(DROP_RULE)
            + ". They are shown but not scored until a rule says promote.</p>"
            "<table><tr><th>Flag</th><th>Claim</th><th>Status</th><th>Judged</th><th>Lift</th></tr>" + rows + "</table>")


_render_accuracy_v25 = render_accuracy


def render_accuracy(rep: dict, head: Optional[str]) -> str:
    page = _render_accuracy_v25(rep, head)
    extra = render_surprises(rep.get("recent_outcomes") or []) + render_hypotheses()
    for marker in ("<h2>Methodology</h2>", "<h2>How we measure</h2>"):
        if marker in page:
            return page.replace(marker, extra + marker, 1)
    return page


LLMS_TXT = LLMS_TXT + """
## Decision object: validity and pre-mortem
decision.valid_for_s says how long the reading stays useful: 10s for fast-moving tokens (momentum, volume spikes, dumps, pairs under an hour),
30s normally, 120s for majors and established tokens, 0 when the data is stale. decision.would_change_if lists, for each reason against the
token, the condition that would make it go away. They are conditions, not predictions.

## Hypotheses
/methodology lists the hypotheses under test with the promotion and drop rules fixed in advance, and their current status.
The accuracy page also shows the biggest surprises: verdicts that were wrong.

## Data source
Market data normally comes from DexScreener. When DexScreener is rate-limiting, "source" is "geckoterminal" and
data_quality.data_confidence is capped at 0.7. Errors that mean "try again later" carry retry_after_s.
"""


# ---------- HTTP layer: shared cooldowns, DexScreener fetchers, fallback ----------
_DEX_COOLDOWN = {"until": 0.0}
_RUGCHECK_COOLDOWN = {"until": 0.0}
_HOST_COOLDOWNS = {"api.dexscreener.com": _DEX_COOLDOWN, "api.rugcheck.xyz": _RUGCHECK_COOLDOWN}


def _retry_after_seconds(resp, default: int = 30) -> int:
    try:
        return max(1, min(int(resp.headers.get("retry-after", default)), 120))
    except (TypeError, ValueError):
        return default


# Every call to these hosts, from any part (part4 and part15 call DexScreener straight through client.get),
# shares one cooldown: after a 429 we stop calling that host for Retry-After seconds. Callers already catch
# httpx.HTTPError, so they simply skip the round.
if not getattr(httpx.AsyncClient.get, "_host_guard", False):
    _client_get_original = httpx.AsyncClient.get

    async def _guarded_get(self, url, *args, **kwargs):
        cooldown = None
        if isinstance(url, str):
            for host, state in _HOST_COOLDOWNS.items():
                if host in url:
                    cooldown = state
                    break
        if cooldown is None:
            return await _client_get_original(self, url, *args, **kwargs)
        if cooldown["until"] > time.time():
            raise httpx.ConnectError("source is cooling down after a 429")
        resp = await _client_get_original(self, url, *args, **kwargs)
        if resp.status_code == 429:
            cooldown["until"] = time.time() + _retry_after_seconds(resp)
        return resp

    _guarded_get._host_guard = True
    httpx.AsyncClient.get = _guarded_get


async def _fetch_dex_direct(client: httpx.AsyncClient, mint: str) -> dict:
    wait = _DEX_COOLDOWN["until"] - time.time()
    if wait > 0:  # still cooling down: do not call upstream at all
        raise HTTPException(
            status_code=503,
            detail="DexScreener rate limit (429). Using longer cache window.",
            headers={"Retry-After": str(int(wait) + 1)},
        )
    t0 = time.time()
    try:
        resp = await client.get(DEX_URL.format(mint=mint))
        if resp.status_code == 429:
            ra = _retry_after_seconds(resp)
            _DEX_COOLDOWN["until"] = time.time() + ra
            src_log("dexscreener", False, t0)
            raise HTTPException(
                status_code=503,
                detail="DexScreener rate limit (429). Using longer cache window.",
                headers={"Retry-After": str(ra)},
            )
        resp.raise_for_status()
        data = resp.json()
        src_log("dexscreener", True, t0)
        return data
    except HTTPException:
        raise
    except (httpx.HTTPError, ValueError):
        src_log("dexscreener", False, t0)
        raise HTTPException(
            status_code=503,
            detail="Market data source (DexScreener) is unavailable, retry in a few seconds",
            headers={"Retry-After": "15"},
        )


async def _gt_fetch(client, mint: str):
    if _GT_COOLDOWN["until"] > time.time():
        return None
    async with _GT_SEM:
        try:
            resp = await client.get(_GT_URL.format(mint=mint), headers=_GT_HEADERS, timeout=8.0)
        except (httpx.HTTPError, asyncio.TimeoutError):
            print(f"[fallback] geckoterminal unreachable for {mint[:6]}")
            return None
        if resp.status_code == 429:
            _GT_COOLDOWN["until"] = time.time() + _retry_after_seconds(resp, 60)
            print("[fallback] geckoterminal is rate-limiting too, pausing it")
            return None
        if resp.status_code != 200:
            print(f"[fallback] geckoterminal answered {resp.status_code} for {mint[:6]}")
            return None
        try:
            return gt_to_dex_pairs(resp.json(), mint) or None
        except Exception:  # noqa: BLE001
            print(f"[fallback] geckoterminal answer for {mint[:6]} could not be read")
            return None


async def fetch_dex(client: httpx.AsyncClient, mint: str) -> dict:
    """DexScreener first; if it refuses (503), GeckoTerminal in DexScreener's shape; else the original error."""
    try:
        data = await _fetch_dex_direct(client, mint)
        _FALLBACK_MINTS.pop(mint, None)  # DexScreener is back for this token
        return data
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        pairs = await _gt_fetch(client, mint)
        if not pairs:
            raise  # fallback failed too: report the original DexScreener problem
        _FALLBACK_MINTS[mint] = time.time()
        print(f"[fallback] geckoterminal served {mint[:6]} ({len(pairs)} pools)")
        return {"pairs": pairs}


async def fetch_dex_many(client: httpx.AsyncClient, mints: List[str]) -> Optional[Dict[str, dict]]:
    """ONE DexScreener request for up to 30 mints. Returns {mint: {"pairs": [...]}} or None if the call failed or
    the source is cooling down (callers then fall back to stale cache, the single fetch_dex, or a clear 503).
    - Majors (SOL, USDC, USDT) stay out: with their huge pair counts they crowd small tokens out of the shared answer.
    - A mint with no pair in the answer is left out, so the caller asks for it alone instead of reporting a false 404.
    """
    rest = [m for m in mints if m not in MAJOR_ASSETS]
    if not rest:
        return {}
    if _DEX_COOLDOWN["until"] > time.time():
        return None
    out: Dict[str, dict] = {m: {"pairs": []} for m in rest}
    t0 = time.time()
    try:
        resp = await client.get(DEX_URL.format(mint=",".join(rest)))
        if resp.status_code == 429:
            _DEX_COOLDOWN["until"] = time.time() + _retry_after_seconds(resp)
            src_log("dexscreener", False, t0)
            return None
        resp.raise_for_status()
        pairs = resp.json().get("pairs") or []
        src_log("dexscreener", True, t0)
    except (httpx.HTTPError, ValueError):
        src_log("dexscreener", False, t0)
        return None
    # A token belongs to a pair as its BASE. Matching the quote side too would push every memecoin/SOL pair into
    # SOL's list, so quote is only a fallback for tokens with no base match.
    for p in pairs:
        base = (p.get("baseToken") or {}).get("address")
        if base in out:
            out[base]["pairs"].append(p)
    no_base = {m for m, v in out.items() if not v["pairs"]}
    for p in pairs:
        quote = (p.get("quoteToken") or {}).get("address")
        if quote in no_base:
            out[quote]["pairs"].append(p)
    return {m: v for m, v in out.items() if v["pairs"]}


# ---------- Homepage: retry button when 429/503 ----------
_old_get = """if(!res.ok){result.innerHTML='<div style="color:#ff4d6d">Error: '+esc(data.detail||'Failed')+'</div>'}"""

_new_get = """if(!res.ok){
  const retry=parseInt(res.headers.get('Retry-After')||'30',10);
  let left=retry;
  result.innerHTML='<div style="color:#ff4d6d;margin-bottom:10px">Error: '+esc(data.detail||'Failed')+'</div>'
    +'<button id="retryBtn" disabled style="margin-top:4px;padding:8px 16px;border-radius:8px;border:none;background:linear-gradient(90deg,#7c5cff,#00d4aa);color:#fff;font-weight:600;cursor:pointer">Retry in '+left+'s</button>';
  const rb=document.getElementById('retryBtn');
  const t=setInterval(()=>{
    left--;
    if(left<=0){clearInterval(t);rb.textContent='Retry now';rb.disabled=false;rb.onclick=()=>getSignal()}
    else{rb.textContent='Retry in '+left+'s';rb.disabled=true}
  },1000);
}"""

if _old_get in HOME_HTML:
    HOME_HTML = HOME_HTML.replace(_old_get, _new_get)
elif "retryBtn" not in HOME_HTML:
    print("[part19] warning: homepage retry button was NOT applied (the original JS line has changed)")


# ---------- favicon (inline SVG, no static file needed) ----------
_FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#9945FF"/>
      <stop offset="100%" stop-color="#14F195"/>
    </linearGradient>
  </defs>
  <rect width="64" height="64" rx="14" fill="#070b12"/>
  <text x="32" y="44" text-anchor="middle" font-family="system-ui,sans-serif"
        font-size="28" font-weight="800" fill="url(#g)">T</text>
</svg>"""

_FAVICON_LINK = '<link rel="icon" href="/favicon.ico" type="image/svg+xml">'
if _FAVICON_LINK not in HOME_HTML and "<title>" in HOME_HTML:
    HOME_HTML = HOME_HTML.replace(
        "<title>",
        _FAVICON_LINK + "\n<title>",
        1,
    )


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    from fastapi.responses import Response
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})

# --- part20 ---
# ---------- part20: v2.8.0 — Phase 2 step 1: anti-429 + anti-sleep ----------
# Loads before part7 (MCP). Same shared namespace as all other parts.
VERSION = "2.8.0"
app.version = VERSION
app.openapi_schema = None

# Longer tolerance when upstream is angry
STALE_MAX = max(STALE_MAX, 1800)        # 30 minutes
PARTIAL_TTL = max(PARTIAL_TTL, 20)
BASE_CACHE_TTL = max(BASE_CACHE_TTL, 30)

_homeostat_prev = homeostat


def homeostat() -> int:
    """Stretch cache harder while DexScreener is in 429 cooldown."""
    global CACHE_TTL, STALE_MAX
    ttl = _homeostat_prev()
    cooling = False
    try:
        cooling = float(_DEX_COOLDOWN.get("until") or 0) > time.time()
    except Exception:
        pass
    if cooling:
        CACHE_TTL = max(CACHE_TTL, BASE_CACHE_TTL * 8)
        STALE_MAX = max(STALE_MAX, 1800)
    return CACHE_TTL


# Last-resort: if build would 503 and we still have any cache entry, serve it
_build_core_prev = _build_signal_core


async def _build_signal_core(client, mint: str, security: bool, prefetched=None):
    homeostat()
    cache_key = mint if security else mint + ":nosec"
    try:
        return await _build_core_prev(client, mint, security, prefetched)
    except HTTPException as exc:
        if getattr(exc, "status_code", None) != 503:
            raise
        hit = cache_peek(cache_key)
        if not hit:
            raise
        age, cached = hit
        out = dict(cached)
        out["stale"] = True
        out["stale_age_s"] = int(age)
        out["source_note"] = "served beyond normal stale window because market source is rate-limited"
        return out, "STALE"


@app.get("/ping", include_in_schema=False)
async def ping():
    """No upstream calls. Point a free cron (cron-job.org / UptimeRobot) here every 10–14 min."""
    cooling = False
    try:
        cooling = float(_DEX_COOLDOWN.get("until") or 0) > time.time()
    except Exception:
        pass
    return {
        "ok": True,
        "version": VERSION,
        "ts": int(time.time()),
        "dex_cooling": cooling,
        "cache_size": len(_cache),
    }


# Replace /health so operators see stability fields
_drop_route("/health")


@app.get("/health", tags=["ops"], summary="Service status and what is switched on")
async def health():
    cooling = False
    try:
        cooling = float(_DEX_COOLDOWN.get("until") or 0) > time.time()
    except Exception:
        pass
    return {
        "status": "ok",
        "version": VERSION,
        "uptime_s": int(time.time() - _m["started"]),
        "python": platform.python_version(),
        "cache_size": len(_cache),
        "rpc": "custom" if os.getenv("SOLANA_RPC_URL") else "public",
        "mcp": mcp_server is not None,
        "mcp_error": mcp_error,
        "jupiter_key": bool(JUP_KEY),
        "track_record": PRED_ENABLED,
        "track_record_store": await redis_status(getattr(app.state, "client", None)),
        "auto_tune": AUTO_TUNE,
        "api_keys_configured": len(API_KEYS),
        "streams": {"watching": len(_watchers), "open": sum(_stream_open.values())},
        "sources": src_status(),
        "stability": {
            "stale_max_s": STALE_MAX,
            "cache_ttl_s": CACHE_TTL,
            "dex_cooling": cooling,
            "keep_alive": "GET /ping every 10-14 min (cron-job.org or UptimeRobot)",
        },
    }


# Agent docs
try:
    if "GET /ping" not in LLMS_TXT:
        LLMS_TXT = LLMS_TXT + """
## Keep-alive
GET /ping — no upstream calls. Hit every 10–14 min from a free cron to reduce free-tier host sleep.
"""
except NameError:
    pass

print(f"[part20] v{VERSION} anti-429/anti-sleep ready (STALE_MAX={STALE_MAX}s)")

# --- part21 ---
# ---------- part21: v2.8.1 — Phase 2 step 2: seed traffic + accuracy growth ----------
# Loads before part7 (MCP). Slow, capped sampling so track-record fills without melting DexScreener.
VERSION = "2.8.1"
app.version = VERSION
app.openapi_schema = None

SEED_ENABLED = (os.getenv("SEED_TRAFFIC") or "true").lower() in ("1", "true", "yes")
SEED_INTERVAL_S = max(180, int(os.getenv("SEED_INTERVAL_S", "900")))  # default 15 min between seeds
SEED_MAX_PER_DAY = max(5, int(os.getenv("SEED_MAX_PER_DAY", "40")))   # hard cap
_SEED_BOOST = "https://api.dexscreener.com/token-boosts/top/v1"
_SEED_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"
_seed_state = {"day": "", "count": 0, "last": 0.0, "last_mint": None, "last_ok": False, "errors": 0}


def _seed_day_ok() -> bool:
    today = time.strftime("%Y%m%d", time.gmtime())
    if _seed_state["day"] != today:
        _seed_state.update(day=today, count=0)
    return _seed_state["count"] < SEED_MAX_PER_DAY


async def _seed_candidate_mints(client: httpx.AsyncClient) -> list:
    """Solana mints from DexScreener boosts + latest profiles (best-effort, no throw)."""
    mints = []
    for url in (_SEED_BOOST, _SEED_PROFILES):
        try:
            resp = await client.get(url, timeout=6.0)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if not isinstance(data, list):
                continue
            for row in data:
                if (row.get("chainId") or "").lower() != "solana":
                    continue
                addr = row.get("tokenAddress") or row.get("token_address")
                if addr and MINT_RE.match(addr) and addr not in MAJOR_ASSETS:
                    mints.append(addr)
        except Exception:
            continue
    # de-dupe, shuffle lightly by time bucket
    seen = set()
    out = []
    for m in mints:
        if m not in seen:
            seen.add(m)
            out.append(m)
    if out:
        # rotate starting point so we don't always hit the same top boosts
        off = int(time.time() // SEED_INTERVAL_S) % len(out)
        out = out[off:] + out[:off]
    return out


async def run_one_seed(client: httpx.AsyncClient) -> dict:
    """Fetch one diverse mint and run full signal path (records prediction automatically)."""
    if not SEED_ENABLED:
        return {"ok": False, "detail": "SEED_TRAFFIC disabled"}
    if not _seed_day_ok():
        return {"ok": False, "detail": f"daily seed cap {SEED_MAX_PER_DAY} reached"}
    now = time.time()
    if now - _seed_state["last"] < SEED_INTERVAL_S:
        wait = int(SEED_INTERVAL_S - (now - _seed_state["last"]))
        return {"ok": False, "detail": "too soon", "retry_after_s": wait}
    try:
        if float(_DEX_COOLDOWN.get("until") or 0) > now:
            return {"ok": False, "detail": "dex cooling, skip seed"}
    except Exception:
        pass

    mints = await _seed_candidate_mints(client)
    if not mints:
        _seed_state["errors"] += 1
        return {"ok": False, "detail": "no solana candidates from boosts/profiles"}

    # pick first not recently locked by prediction lock (best effort: try up to 5)
    last_err = None
    for mint in mints[:5]:
        try:
            result, status = await build_signal(client, mint, True)
            _seed_state.update(last=time.time(), last_mint=mint, last_ok=True, count=_seed_state["count"] + 1)
            return {
                "ok": True,
                "mint": mint,
                "token": result.get("token"),
                "verdict": result.get("verdict"),
                "risk_score": result.get("risk_score"),
                "cache": status,
                "seeded_today": _seed_state["count"],
            }
        except HTTPException as e:
            last_err = getattr(e, "detail", str(e))
            if getattr(e, "status_code", None) == 503:
                break  # don't hammer further
            continue
        except Exception as e:
            last_err = str(e)[:120]
            continue
    _seed_state["errors"] += 1
    _seed_state["last"] = time.time()
    return {"ok": False, "detail": last_err or "all candidates failed"}


@app.get("/seed", tags=["ops"], summary="Slow sample of live tokens to grow accuracy data",
         include_in_schema=False)
async def seed_route(request: Request):
    """Call from cron every 15–20 min. Capped, skips when Dex is cooling. No API key needed."""
    # cheap IP rate limit so random scanners cannot spray
    wait = rate_limited("seed:" + client_ip(request), limit=6)
    if wait:
        raise HTTPException(status_code=429, detail="seed rate limited", headers={"Retry-After": str(wait)})
    client = request.app.state.client
    report = await run_one_seed(client)
    code = 200 if report.get("ok") else 503 if "cooling" in str(report.get("detail")) else 200
    return JSONResponse(content=report, status_code=code,
                        headers={"Cache-Control": "no-store"})


# Auto-seed on /ping occasionally (every 2nd ping after interval), so one cron covers both
_drop_route("/ping")
_ping_prev = ping
_ping_count = {"n": 0}


@app.get("/ping", include_in_schema=False)
async def ping():
    body = await _ping_prev() if asyncio.iscoroutinefunction(_ping_prev) else _ping_prev()
    if not isinstance(body, dict):
        return body
    _ping_count["n"] += 1
    body["seed"] = {
        "enabled": SEED_ENABLED,
        "seeded_today": _seed_state["count"],
        "max_per_day": SEED_MAX_PER_DAY,
        "interval_s": SEED_INTERVAL_S,
        "last_mint": _seed_state.get("last_mint"),
    }
    # every other ping, try a seed if due (fire-and-forget)
    if SEED_ENABLED and _ping_count["n"] % 2 == 0 and _seed_day_ok():
        if time.time() - _seed_state["last"] >= SEED_INTERVAL_S:
            client = getattr(app.state, "client", None)
            if client is not None:
                async def _bg():
                    try:
                        await run_one_seed(client)
                    except Exception:
                        pass
                t = asyncio.create_task(_bg())
                _seed_bg = globals().setdefault("_seed_bg", set())
                _seed_bg.add(t)
                t.add_done_callback(_seed_bg.discard)
    return body


# health: expose seed counters
_drop_route("/health")


@app.get("/health", tags=["ops"], summary="Service status and what is switched on")
async def health():
    cooling = False
    try:
        cooling = float(_DEX_COOLDOWN.get("until") or 0) > time.time()
    except Exception:
        pass
    return {
        "status": "ok",
        "version": VERSION,
        "uptime_s": int(time.time() - _m["started"]),
        "python": platform.python_version(),
        "cache_size": len(_cache),
        "rpc": "custom" if os.getenv("SOLANA_RPC_URL") else "public",
        "mcp": mcp_server is not None,
        "mcp_error": mcp_error,
        "jupiter_key": bool(JUP_KEY),
        "track_record": PRED_ENABLED,
        "track_record_store": await redis_status(getattr(app.state, "client", None)),
        "auto_tune": AUTO_TUNE,
        "api_keys_configured": len(API_KEYS),
        "streams": {"watching": len(_watchers), "open": sum(_stream_open.values())},
        "sources": src_status(),
        "stability": {
            "stale_max_s": STALE_MAX,
            "cache_ttl_s": CACHE_TTL,
            "dex_cooling": cooling,
            "keep_alive": "GET /ping every 10-14 min (cron-job.org or UptimeRobot)",
        },
        "seed": {
            "enabled": SEED_ENABLED,
            "seeded_today": _seed_state["count"],
            "max_per_day": SEED_MAX_PER_DAY,
            "interval_s": SEED_INTERVAL_S,
            "last_mint": _seed_state.get("last_mint"),
            "errors": _seed_state["errors"],
            "hint": "GET /seed or rely on /ping auto-seed; aim for ok/avoid n>=20 on /stats",
        },
    }


try:
    if "GET /seed" not in LLMS_TXT:
        LLMS_TXT = LLMS_TXT + """
## Accuracy growth
GET /seed — slow sample of live Solana tokens (capped) so measured accuracy fills in.
Also runs occasionally when /ping is hit. Targets: enough judged samples for ok/caution/avoid rates.
"""
except NameError:
    pass

print(f"[part21] v{VERSION} seed traffic ready (interval={SEED_INTERVAL_S}s, max/day={SEED_MAX_PER_DAY})")

# --- part22 ---
# ---------- part22: v2.9.0 - cleaner track record: no major assets, one verdict per mint per 24h, source labels ----------
# Loads before part7 (MCP). Replaces record_prediction and resolve_due, widens the seed candidates, adds by_source to /stats.
import contextvars

VERSION = "2.9.0"
app.version = VERSION
app.openapi_schema = None

PRED_LOCK_S = 86400  # at most one recorded verdict per mint per 24h: repeats are not independent samples
SEED_GECKO = (os.getenv("SEED_GECKO") or "true").lower() in ("1", "true", "yes")  # GeckoTerminal pools are not paid promotions
_GECKO_URLS = {
    "trending": "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools",
    "new": "https://api.geckoterminal.com/api/v2/networks/solana/new_pools",
}
_PRED_SRC = contextvars.ContextVar("pred_src", default="user")
_SEED_ORIGIN: Dict[str, str] = {}  # mint -> boost | profile | trending | new (memory only)


def _pred_source(mint: str) -> str:
    if _PRED_SRC.get() == "seed":
        return "seed_" + _SEED_ORIGIN.get(mint, "other")
    return "user"


async def record_prediction(client: httpx.AsyncClient, r: dict):
    """Store one verdict to be judged later. Skips major assets, one per mint per 24h, MAX_PRED_PER_DAY per day."""
    try:
        price = float(r.get("price_usd") or 0)
        mint = r.get("mint")
        if price <= 0 or not mint or mint in MAJOR_ASSETS:
            return
        today = time.strftime("%Y%m%d", time.gmtime())
        if _pred_day["day"] != today:
            _pred_day.update(day=today, count=0)
        if _pred_day["count"] >= MAX_PRED_PER_DAY:
            return
        lock = await redis_pipe(client, [["SET", f"plock24:{mint}", "1", "EX", PRED_LOCK_S, "NX"]])
        if not lock or lock[0] != "OK":
            return
        _pred_day["count"] += 1
        now = int(time.time())
        pid = f"{mint}:{now}"
        sol = await sol_price(client)
        src = _pred_source(mint)
        await redis_pipe(client, [
            ["HSET", f"pred:{pid}", "mint", mint, "token", r.get("token") or "", "ts", now, "price", price,
             "liq", r.get("liquidity_usd") or 0, "verdict", r["verdict"], "conf", r["verdict_confidence"],
             "score", r["risk_score"], "flags", ",".join(r.get("flags") or []), "sol", sol or "", "src", src],
            ["EXPIRE", f"pred:{pid}", PRED_HORIZON_S * 4],
            ["ZADD", "due", now + PRED_HORIZON_S, pid],
        ])
        await ledger_append(client, {
            "id": pid, "ts": now, "mint": mint, "token": r.get("token") or "", "verdict": r["verdict"],
            "risk_score": r["risk_score"], "price_usd": price, "liquidity_usd": r.get("liquidity_usd") or 0,
            "flags": sorted(r.get("flags") or []), "version": VERSION, "src": src,
        })
    except Exception:
        pass


async def resolve_due(client: httpx.AsyncClient) -> int:
    """Judge predictions whose time has come. Returns how many were processed. (v2.9: skips major assets, labels the source)"""
    now = int(time.time())
    got = await redis_pipe(client, [["ZRANGEBYSCORE", "due", "-inf", now, "LIMIT", 0, RESOLVE_BATCH]])
    ids = (got or [[]])[0] or []
    if not ids:
        return 0
    hashes = await redis_pipe(client, [["HGETALL", f"pred:{i}"] for i in ids])
    if hashes is None:
        return 0
    cmds: list = []
    preds: Dict[str, dict] = {}
    for pid, h in zip(ids, hashes):
        d = to_dict(h)
        if d.get("mint"):
            preds[pid] = d
        else:
            cmds.append(["ZREM", "due", pid])  # hash expired: drop the orphan
    best: Dict[str, Optional[dict]] = {}
    sol1: Optional[float] = None
    if preds:
        mints = sorted({d["mint"] for d in preds.values()})
        ask = mints if SOL_MINT in mints else mints + [SOL_MINT]
        t0 = time.time()
        try:
            resp = await client.get(DEX_URL.format(mint=",".join(ask)))
            resp.raise_for_status()
            pairs = resp.json().get("pairs") or []
            src_log("dexscreener", True, t0)
        except (httpx.HTTPError, ValueError):
            src_log("dexscreener", False, t0)
            if cmds:
                await redis_pipe(client, cmds)
            return 0  # try again next cycle, nothing is lost
        for m in mints:
            best[m] = pick_best_pair([p for p in pairs if (p.get("baseToken") or {}).get("address") == m], m)
        sp = pick_best_pair([p for p in pairs if (p.get("baseToken") or {}).get("address") == SOL_MINT], SOL_MINT)
        try:
            sol1 = float(sp.get("priceUsd")) if sp else None
        except (TypeError, ValueError):
            sol1 = None

    recent = []
    for pid, d in preds.items():
        cmds += [["ZREM", "due", pid], ["DEL", f"pred:{pid}"]]
        if d["mint"] in MAJOR_ASSETS:
            continue  # v2.9: SOL and stablecoins are not judged (they would only pad the ok group)
        age = now - int(d.get("ts") or 0)
        if age > PRED_HORIZON_S * 3:
            continue  # judged far too late (server was asleep): would distort the stats
        p0, l0 = float(d.get("price") or 0), float(d.get("liq") or 0)
        pair = best.get(d["mint"])
        if pair is None:
            ret, liq_ratio = -100.0, 0.0
        else:
            p1 = float(pair.get("priceUsd") or 0)
            l1 = float((pair.get("liquidity") or {}).get("usd") or 0)
            ret = (p1 / p0 - 1) * 100 if p0 > 0 else 0.0
            liq_ratio = l1 / l0 if l0 > 0 else 1.0
        bad = ret <= BAD_RETURN_PCT or liq_ratio <= BAD_LIQ_RATIO
        # market background: how much did SOL itself move over the same window?
        sol0 = float(d.get("sol") or 0)
        sol_ret = (sol1 / sol0 - 1) * 100 if (sol1 and sol0 > 0) else None
        xret = ret - sol_ret if sol_ret is not None else None
        v, c = d.get("verdict", "?"), d.get("conf", "?")
        bucket = min(9, int(float(d.get("score") or 0)) // 10)
        day = time.strftime("%Y%m%d", time.gmtime(int(d.get("ts") or 0)))
        flags_t = [f for f in (d.get("flags") or "").split(",") if f in RISK_WEIGHTS]
        src = d.get("src") or "untagged"  # v2.9: where the request came from; older rows have no label
        groups = ["all", f"v:{v}:{c}", f"rb:{bucket}", f"d:{day}", f"src:{src}", f"srcv:{src}:{v}"]
        groups += [f"f:{f}" for f in flags_t] + [f"fd:{f}:{day}" for f in flags_t]
        base_pred = "avoid" if BASELINE_FLAGS & set((d.get("flags") or "").split(",")) else "ok"
        groups += [f"vd:{v}:{c}:{day}", f"bl:{base_pred}", f"bd:{base_pred}:{day}"]  # per-day verdicts + the simple baseline
        for g in groups:
            cmds.append(["HINCRBY", "st", f"{g}:n", 1])
            if bad:
                cmds.append(["HINCRBY", "st", f"{g}:bad", 1])
        cmds.append(["HINCRBYFLOAT", "st", f"v:{v}:{c}:ret", round(ret, 2)])
        if xret is not None:
            cmds += [["HINCRBYFLOAT", "st", f"v:{v}:{c}:xret", round(xret, 2)], ["HINCRBY", "st", f"v:{v}:{c}:xn", 1]]
        recent.append(json.dumps({"token": d.get("token"), "mint": d["mint"], "verdict": v, "risk_score": float(d.get("score") or 0),
                                  "return_pct": round(ret, 1), "sol_return_pct": round(sol_ret, 1) if sol_ret is not None else None,
                                  "excess_return_pct": round(xret, 1) if xret is not None else None,
                                  "bad_outcome": bad, "age_h": round(age / 3600, 1), "src": src}))
    for item in recent:
        cmds.append(["LPUSH", "recent", item])
    if recent:
        cmds.append(["LTRIM", "recent", 0, 49])
    if cmds:
        await redis_pipe(client, cmds)
    return len(ids)


# ---------- seed candidates: boosts + profiles (DexScreener, paid promotion) plus trending + new pools (GeckoTerminal) ----------
def _add_mints(pool: list, addrs) -> None:
    for addr in addrs:
        if addr and MINT_RE.match(addr) and addr not in MAJOR_ASSETS and addr not in pool:
            pool.append(addr)


async def _seed_candidate_mints(client: httpx.AsyncClient) -> list:
    """Solana mints from several sources, mixed so one seed call does not always draw from the same list (best-effort)."""
    pools: Dict[str, list] = {"boost": [], "profile": [], "trending": [], "new": []}
    for origin, url in (("boost", _SEED_BOOST), ("profile", _SEED_PROFILES)):
        try:
            resp = await client.get(url, timeout=6.0)
            if resp.status_code != 200:
                continue
            data = resp.json()
            if not isinstance(data, list):
                continue
            _add_mints(pools[origin], [row.get("tokenAddress") or row.get("token_address") for row in data
                                       if isinstance(row, dict) and (row.get("chainId") or "").lower() == "solana"])
        except Exception:
            continue
    if SEED_GECKO:
        for origin, url in _GECKO_URLS.items():
            try:
                resp = await client.get(url, timeout=6.0, headers={"Accept": "application/json"})
                if resp.status_code != 200:
                    continue
                body = resp.json()
                rows = body.get("data") if isinstance(body, dict) else None
                addrs = []
                for row in rows or []:
                    tid = ((((row.get("relationships") or {}).get("base_token") or {}).get("data") or {}).get("id") or "")
                    addrs.append(tid.split("_", 1)[1] if tid.startswith("solana_") else "")
                _add_mints(pools[origin], addrs)
            except Exception:
                continue
    names = ["trending", "boost", "new", "profile"]
    k = (_seed_state["count"] + _seed_state["errors"]) % len(names)
    names = names[k:] + names[:k]  # the preferred origin changes from one seed call to the next
    bucket = int(time.time() // SEED_INTERVAL_S)
    for n in names:
        if pools[n]:
            o = bucket % len(pools[n])
            pools[n] = pools[n][o:] + pools[n][:o]
    pairs = [(names[0], m) for m in pools[names[0]][:2]]
    for i in range(max(len(p) for p in pools.values())):
        for n in names:
            if i < len(pools[n]):
                pairs.append((n, pools[n][i]))
    out: list = []
    for n, m in pairs:
        if m not in out:
            out.append(m)
            _SEED_ORIGIN[m] = n
    if len(_SEED_ORIGIN) > 400:
        keep = set(out)
        for m in [x for x in _SEED_ORIGIN if x not in keep]:
            _SEED_ORIGIN.pop(m, None)
    head_n = out[:40]
    if head_n:
        chk = await redis_pipe(client, [["EXISTS", f"plock24:{m}"] for m in head_n])
        if chk and len(chk) == len(head_n):
            out = [m for m, x in zip(head_n, chk) if not int(x or 0)] + out[40:]  # skip mints already measured in the last 24h
    return out


_run_one_seed_v21 = run_one_seed


async def run_one_seed(client: httpx.AsyncClient) -> dict:
    tok = _PRED_SRC.set("seed")  # record_prediction runs in a task created inside this context, so it sees the label
    try:
        return await _run_one_seed_v21(client)
    finally:
        _PRED_SRC.reset(tok)


# ---------- /stats and the MCP track record: accuracy split by where the verdict came from ----------
def _by_source(st: dict) -> dict:
    out: Dict[str, Any] = {}
    for key in sorted(st):
        p = key.split(":")
        if len(p) != 3 or p[0] != "src" or p[2] != "n":
            continue
        s = p[1]
        n, bad = int(st.get(f"src:{s}:n", 0)), int(st.get(f"src:{s}:bad", 0))
        verdicts = {}
        for v in ("ok", "caution", "avoid"):
            vn, vb = int(st.get(f"srcv:{s}:{v}:n", 0)), int(st.get(f"srcv:{s}:{v}:bad", 0))
            verdicts[v] = {"n": vn, "bad_outcome_rate_pct": round(vb / vn * 100, 1) if vn >= MIN_N_SHOW else None}
        out[s] = {"n": n, "bad_outcome_rate_pct": round(bad / n * 100, 1) if n >= MIN_N_SHOW else None,
                  "ci95_pct": [round(x * 100, 1) for x in wilson(bad, n)] if n >= MIN_N_SHOW else None,
                  "verdicts": verdicts}
    return out


_stats_report_v21 = stats_report


async def stats_report(client: httpx.AsyncClient) -> dict:
    rep = await _stats_report_v21(client)
    if rep.get("enabled") and rep.get("available") is not False:
        await refresh_raw_stats(client, force=False)
        note = ("From v2.9: major assets (SOL, USDC, USDT) are no longer judged and each mint is recorded at most once "
                "per 24h. Rows judged earlier are labelled 'untagged' and may include repeats. by_source separates "
                "user requests from seeded samples (seed_boost and seed_profile are paid promotions on DexScreener; "
                "seed_trending and seed_new come from GeckoTerminal).")
        rep = dict(rep, by_source=_by_source(_raw_st["st"]), caveats=list(rep.get("caveats") or []) + [note])
    return rep


print(f"[part22] v{VERSION} track record: majors skipped, 1 verdict/mint/{PRED_LOCK_S // 3600}h, sources labelled (gecko={SEED_GECKO})")

# --- part23 ---
# ---------- part23: v2.10.0 - upstream canary: is each market source alive, readable and in agreement? ----------
# Loads before part7 (MCP). part19 already falls back to GeckoTerminal when DexScreener refuses; this part makes that
# visible and checked: a small probe (SOL) every CANARY_EVERY_S compares both sources and the shape of their answers.
VERSION = "2.10.0"
app.version = VERSION
app.openapi_schema = None

CANARY_EVERY_S = max(300, int(os.getenv("CANARY_EVERY_S", "900")))
CANARY_MAX_DIFF_PCT = float(os.getenv("CANARY_MAX_DIFF_PCT", "3"))
# Off by default: when on, a token DexScreener has no pair for is also looked up on GeckoTerminal (lower confidence).
GT_FILL_MISSING = (os.getenv("GT_FILL_MISSING") or "false").lower() in ("1", "true", "yes")

_PAIR_KEYS = ("priceUsd", "liquidity", "baseToken", "pairAddress", "dexId")
_canary: Dict[str, Any] = {"ts": 0.0, "running": False, "status": "unknown", "price_diff_pct": None,
                           "dexscreener": None, "geckoterminal": None,
                           "streak": {"dexscreener": 0, "geckoterminal": 0}}


def _pair_problems(pair: Any) -> list:
    """What is wrong with a pair, judged by the fields the rest of the code needs. Empty list = readable."""
    if not isinstance(pair, dict):
        return ["no pair returned"]
    problems = [f"missing {k}" for k in _PAIR_KEYS if pair.get(k) in (None, "", {})]
    liq = pair.get("liquidity")
    if not isinstance(liq, dict) or not isinstance(liq.get("usd"), (int, float)):
        problems.append("missing liquidity.usd")
    try:
        if float(pair.get("priceUsd")) <= 0:
            problems.append("priceUsd is not positive")
    except (TypeError, ValueError):
        if "missing priceUsd" not in problems:
            problems.append("priceUsd is not a number")
    return problems


def _probe_result(pair: Any, t0: float, why: str = "") -> dict:
    problems = _pair_problems(pair) if not why else [why]
    price = None
    if not problems:
        price = float(pair["priceUsd"])
    return {"ok": not problems, "price": price, "problems": problems, "ms": round((time.time() - t0) * 1000)}


async def _probe_dex(client: httpx.AsyncClient) -> dict:
    t0 = time.time()
    try:
        data = await _fetch_dex_direct(client, SOL_MINT)
    except HTTPException as exc:
        return _probe_result(None, t0, f"unavailable ({exc.status_code})")
    except Exception as exc:  # noqa: BLE001
        return _probe_result(None, t0, f"error: {str(exc)[:80]}")
    pairs = data.get("pairs") if isinstance(data, dict) else None
    return _probe_result(pick_best_pair(pairs or [], SOL_MINT), t0)


async def _probe_gt(client: httpx.AsyncClient) -> dict:
    t0 = time.time()
    try:
        pairs = await _gt_fetch(client, SOL_MINT)
    except Exception as exc:  # noqa: BLE001
        return _probe_result(None, t0, f"error: {str(exc)[:80]}")
    if not pairs:
        return _probe_result(None, t0, "no data (cooling down, unreachable or unreadable)")
    return _probe_result(pick_best_pair(pairs, SOL_MINT), t0)


async def run_canary(client: httpx.AsyncClient) -> None:
    if _canary["running"]:
        return
    _canary["running"] = True
    try:
        dex, gt = await _probe_dex(client), await _probe_gt(client)
        for name, res in (("dexscreener", dex), ("geckoterminal", gt)):
            _canary["streak"][name] = 0 if res["ok"] else _canary["streak"][name] + 1
        diff = abs(dex["price"] - gt["price"]) / dex["price"] * 100 if dex["ok"] and gt["ok"] else None
        if dex["ok"] and gt["ok"]:
            status = "ok" if diff <= CANARY_MAX_DIFF_PCT else "price_mismatch"
        elif dex["ok"]:
            status = "fallback_unavailable"
        elif gt["ok"]:
            status = "primary_down_fallback_ok"
        else:
            status = "both_down"
        _canary.update(ts=time.time(), status=status, dexscreener=dex, geckoterminal=gt,
                       price_diff_pct=round(diff, 2) if diff is not None else None)
    except Exception:  # noqa: BLE001
        pass
    finally:
        _canary["running"] = False


def _canary_view() -> dict:
    ts = _canary["ts"]
    if not ts:
        return {"status": "unknown", "detail": "no check has run yet since this server started"}

    def side(name: str) -> dict:
        r = _canary.get(name) or {}
        return {"ok": r.get("ok"), "problems": r.get("problems") or [], "failed_checks_in_a_row": _canary["streak"][name]}

    return {"status": _canary["status"], "checked_s_ago": int(time.time() - ts), "every_s": CANARY_EVERY_S,
            "price_diff_pct": _canary["price_diff_pct"], "max_diff_pct": CANARY_MAX_DIFF_PCT,
            "basis": "SOL priced by both sources, plus a shape check of each answer",
            "dexscreener": side("dexscreener"), "geckoterminal": side("geckoterminal")}


# GeckoTerminal shows up next to the other sources, judged by the canary (a normal 404 for an unknown token is not a failure)
_src_status_v4 = src_status


def src_status() -> dict:
    out = _src_status_v4()
    age = time.time() - _canary["ts"] if _canary["ts"] else None
    g = _canary.get("geckoterminal")
    if g and age is not None and age < CANARY_EVERY_S * 4:
        out["geckoterminal"] = {"status": "ok" if g["ok"] else "down", "basis": "canary", "checked_s_ago": int(age)}
    else:
        out["geckoterminal"] = {"status": "unknown"}
    return out


# Optional: also use GeckoTerminal for tokens DexScreener does not know (yet).
_fetch_dex_v19 = fetch_dex


async def fetch_dex(client: httpx.AsyncClient, mint: str) -> dict:
    data = await _fetch_dex_v19(client, mint)
    if GT_FILL_MISSING and mint not in MAJOR_ASSETS and not (isinstance(data, dict) and data.get("pairs")):
        pairs = await _gt_fetch(client, mint)
        if pairs:
            _FALLBACK_MINTS[mint] = time.time()  # lowers the confidence and says so, exactly like the 429 fallback
            return {"pairs": pairs}
    return data


# /health: the canary and the fallback state
_drop_route("/health")
_health_v21 = health


@app.get("/health", tags=["ops"], summary="Service status and what is switched on")
async def health():
    body = await _health_v21()
    if isinstance(body, dict):
        now = time.time()
        body = dict(body, upstream=_canary_view(), fallback={
            "geckoterminal_serving_now": sum(1 for t in _FALLBACK_MINTS.values() if now - t < 600),
            "geckoterminal_cooldown_s": max(0, int(_GT_COOLDOWN["until"] - now)),
            "fill_missing_tokens": GT_FILL_MISSING,
        })
    return body


# /ping: start a check in the background when one is due (the cron you already have is enough)
_drop_route("/ping")
_ping_v22 = ping


@app.get("/ping", include_in_schema=False)
async def ping():
    body = await _ping_v22() if asyncio.iscoroutinefunction(_ping_v22) else _ping_v22()
    if isinstance(body, dict):
        if time.time() - _canary["ts"] >= CANARY_EVERY_S and not _canary["running"]:
            client = getattr(app.state, "client", None)
            if client is not None:
                schedule(run_canary(client))
        body["upstream"] = _canary["status"]
    return body


print(f"[part23] v{VERSION} upstream canary ready (every {CANARY_EVERY_S}s, max price gap {CANARY_MAX_DIFF_PCT}%, fill_missing={GT_FILL_MISSING})")

# --- part24 ---
# ---------- part24: v2.11.0 - shadow rules and early checks: learn faster, compare other rules on the same tokens ----------
# Loads before part7 (MCP). Every new verdict also stores what five alternative rules would have said, and is judged
# again after 1h and 6h (same definition of a bad outcome) besides the usual 24h. Live answers are not changed.
VERSION = "2.11.1"
app.version = VERSION
app.openapi_schema = None

DATASET_ENABLED = (os.getenv("DATASET_ENABLED") or "true").lower() in ("1", "true", "yes")
DATASET_MAX = max(100, int(os.getenv("DATASET_MAX") or "2000"))  # labelled rows kept in Redis (about 1 KB each)
SHADOW_ENABLED = (os.getenv("SHADOW_ENABLED") or "true").lower() in ("1", "true", "yes")


def _early_hours() -> list:
    out = []
    for part in (os.getenv("EARLY_HOURS") if os.getenv("EARLY_HOURS") is not None else "1,6").split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= 23 and int(part) not in out:
            out.append(int(part))
    return sorted(out)


_EARLY = [(h, f"due_h{h}") for h in _early_hours()]  # EARLY_HOURS="" switches the early checks off (saves Redis commands)
_VERDICTS = ("ok", "caution", "avoid")


def _rule_baseline(f: set, s: float, liq: float) -> str:
    return "avoid" if BASELINE_FLAGS & f else "ok"


def _rule_graded_liq_age(f: set, s: float, liq: float) -> str:
    if {"very_low_liquidity", "brand_new_pair"} & f:
        return "avoid"
    return "caution" if {"low_liquidity", "very_new_pair"} & f else "ok"


def _rule_score_35(f: set, s: float, liq: float) -> str:
    return "avoid" if s >= 35 else "caution" if s >= 15 else "ok"


def _rule_score_only(f: set, s: float, liq: float) -> str:
    return "avoid" if s >= 50 else "caution" if s >= 25 else "ok"  # the live thresholds without the hard flag overrides


def _rule_liq_5k(f: set, s: float, liq: float) -> str:
    return "avoid" if liq < 5000 else "caution" if liq < 20000 else "ok"


SHADOW_RULES = {"baseline": _rule_baseline, "graded_liq_age": _rule_graded_liq_age, "score_35": _rule_score_35,
                "score_only": _rule_score_only, "liq_5k": _rule_liq_5k}


def _shadow_str(r: dict) -> str:
    """'live=caution,baseline=ok,...' for one verdict. Never raises."""
    if not SHADOW_ENABLED:
        return ""
    try:
        f = set(r.get("flags") or [])
        s, liq = float(r.get("risk_score") or 0), float(r.get("liquidity_usd") or 0)
        pairs = [("live", r.get("verdict") if r.get("verdict") in _VERDICTS else "caution")]
        pairs += [(name, fn(f, s, liq)) for name, fn in SHADOW_RULES.items()]
        return ",".join(f"{a}={b}" for a, b in pairs)
    except Exception:  # noqa: BLE001
        return ""


def _parse_shadow(text: Any) -> list:
    out = []
    for item in (text or "").split(","):
        name, _, verdict = item.partition("=")
        if name and re.fullmatch(r"[a-z0-9_]+", name) and verdict in _VERDICTS:
            out.append((name, verdict))
    return out


def _early_zadds(pid: str, now: int) -> list:
    return [["ZADD", zset, now + hours * 3600, pid] for hours, zset in _EARLY]


_FEAT_SKIP = {"token", "name", "summary", "mint", "decision", "flags", "data_quality", "verdict_reasons", "suggested_next",
              "disclaimer", "note", "verdict", "raw", "price_usd", "risk_score", "liquidity_usd"}
_FEAT_NESTED = ("price_change_pct", "volume", "txns", "security", "holder_quality", "market", "holders", "buys", "sells")


def _feat_scalar(v: Any) -> Any:
    """A number, or a short enum-like word. Anything else (free text, names) is dropped on purpose."""
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return round(float(v), 4) if math.isfinite(float(v)) else None
    if isinstance(v, str):
        try:
            f = float(v)
            return round(f, 6) if math.isfinite(f) else None
        except ValueError:
            return v if re.fullmatch(r"[A-Za-z0-9_.-]{1,16}", v) else None
    return None


def _feat_str(r: dict) -> str:
    """The numbers behind one verdict, as compact JSON, for the labelled dataset. Never raises, never keeps token names or text."""
    if not DATASET_ENABLED:
        return ""
    try:
        out: Dict[str, Any] = {}
        for k, v in r.items():
            if k in _FEAT_SKIP or not re.fullmatch(r"[a-z0-9_]{1,40}", str(k)):
                continue
            if isinstance(v, dict) and k in _FEAT_NESTED:
                for k2, v2 in v.items():
                    if re.fullmatch(r"[A-Za-z0-9_]{1,30}", str(k2)) and (x := _feat_scalar(v2)) is not None:
                        out[f"{k}.{k2}"] = x
            elif (x := _feat_scalar(v)) is not None and not isinstance(v, (dict, list)):
                out[k] = x
        for k in ("price_usd", "risk_score", "liquidity_usd"):  # the three core numbers, always as numbers
            if (x := _feat_scalar(r.get(k))) is not None:
                out[k] = x
        text = json.dumps(out, separators=(",", ":"), sort_keys=True)
        return text if len(text) <= 1800 else ""
    except Exception:  # noqa: BLE001
        return ""


def _num(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _dataset_cmds(d: dict, v: str, src: str, ret: float, liq_ratio: float, bad: bool) -> list:
    """One labelled row per judged verdict: no mint, no token name, only numbers and our own labels."""
    if not DATASET_ENABLED:
        return []
    try:
        row = {"ts": int(d.get("ts") or 0), "src": src, "verdict": v, "risk": float(d.get("score") or 0),
               "flags": [f for f in (d.get("flags") or "").split(",") if f][:30], "shadow": d.get("shadow") or "",
               "feat": json.loads(d.get("feat") or "{}"), "ret_h1": _num(d.get("ret_h1")), "ret_h6": _num(d.get("ret_h6")),
               "ret_24h": round(ret, 2), "liq_ratio": round(liq_ratio, 3), "bad": 1 if bad else 0}
        return [["LPUSH", "ds:rows", json.dumps(row, separators=(",", ":"))], ["LTRIM", "ds:rows", 0, DATASET_MAX - 1]]
    except Exception:  # noqa: BLE001
        return []


async def record_prediction(client: httpx.AsyncClient, r: dict):
    """Store one verdict to be judged later. Skips major assets, one per mint per 24h, MAX_PRED_PER_DAY per day.
    (v2.11: also stores what the shadow rules would have said and schedules the 1h / 6h checks)"""
    try:
        price = float(r.get("price_usd") or 0)
        mint = r.get("mint")
        if price <= 0 or not mint or mint in MAJOR_ASSETS:
            return
        today = time.strftime("%Y%m%d", time.gmtime())
        if _pred_day["day"] != today:
            _pred_day.update(day=today, count=0)
        if _pred_day["count"] >= MAX_PRED_PER_DAY:
            return
        lock = await redis_pipe(client, [["SET", f"plock24:{mint}", "1", "EX", PRED_LOCK_S, "NX"]])
        if not lock or lock[0] != "OK":
            return
        _pred_day["count"] += 1
        now = int(time.time())
        pid = f"{mint}:{now}"
        sol = await sol_price(client)
        src = _pred_source(mint)
        shadow_str = _shadow_str(r)
        feat_str = _feat_str(r)
        await redis_pipe(client, [
            ["HSET", f"pred:{pid}", "mint", mint, "token", r.get("token") or "", "ts", now, "price", price,
             "liq", r.get("liquidity_usd") or 0, "verdict", r["verdict"], "conf", r["verdict_confidence"],
             "score", r["risk_score"], "flags", ",".join(r.get("flags") or []), "sol", sol or "", "src", src, "shadow", shadow_str, "feat", feat_str],
            ["EXPIRE", f"pred:{pid}", PRED_HORIZON_S * 4],
            ["ZADD", "due", now + PRED_HORIZON_S, pid],
        ] + _early_zadds(pid, now))
        await ledger_append(client, {
            "id": pid, "ts": now, "mint": mint, "token": r.get("token") or "", "verdict": r["verdict"],
            "risk_score": r["risk_score"], "price_usd": price, "liquidity_usd": r.get("liquidity_usd") or 0,
            "flags": sorted(r.get("flags") or []), "version": VERSION, "src": src,
        })
    except Exception:
        pass


async def resolve_due(client: httpx.AsyncClient) -> int:
    """Judge predictions whose time has come. Returns how many were processed. (v2.9: skips major assets, labels the source; v2.11: counts the shadow rules)"""
    now = int(time.time())
    got = await redis_pipe(client, [["ZRANGEBYSCORE", "due", "-inf", now, "LIMIT", 0, RESOLVE_BATCH]])
    ids = (got or [[]])[0] or []
    if not ids:
        return 0
    hashes = await redis_pipe(client, [["HGETALL", f"pred:{i}"] for i in ids])
    if hashes is None:
        return 0
    cmds: list = []
    preds: Dict[str, dict] = {}
    for pid, h in zip(ids, hashes):
        d = to_dict(h)
        if d.get("mint"):
            preds[pid] = d
        else:
            cmds.append(["ZREM", "due", pid])  # hash expired: drop the orphan
    best: Dict[str, Optional[dict]] = {}
    sol1: Optional[float] = None
    if preds:
        mints = sorted({d["mint"] for d in preds.values()})
        ask = mints if SOL_MINT in mints else mints + [SOL_MINT]
        t0 = time.time()
        try:
            resp = await client.get(DEX_URL.format(mint=",".join(ask)))
            resp.raise_for_status()
            pairs = resp.json().get("pairs") or []
            src_log("dexscreener", True, t0)
        except (httpx.HTTPError, ValueError):
            src_log("dexscreener", False, t0)
            if cmds:
                await redis_pipe(client, cmds)
            return 0  # try again next cycle, nothing is lost
        for m in mints:
            best[m] = pick_best_pair([p for p in pairs if (p.get("baseToken") or {}).get("address") == m], m)
        sp = pick_best_pair([p for p in pairs if (p.get("baseToken") or {}).get("address") == SOL_MINT], SOL_MINT)
        try:
            sol1 = float(sp.get("priceUsd")) if sp else None
        except (TypeError, ValueError):
            sol1 = None

    recent = []
    for pid, d in preds.items():
        cmds += [["ZREM", "due", pid], ["DEL", f"pred:{pid}"]]
        if d["mint"] in MAJOR_ASSETS:
            continue  # v2.9: SOL and stablecoins are not judged (they would only pad the ok group)
        age = now - int(d.get("ts") or 0)
        if age > PRED_HORIZON_S * 3:
            continue  # judged far too late (server was asleep): would distort the stats
        p0, l0 = float(d.get("price") or 0), float(d.get("liq") or 0)
        pair = best.get(d["mint"])
        if pair is None:
            ret, liq_ratio = -100.0, 0.0
        else:
            p1 = float(pair.get("priceUsd") or 0)
            l1 = float((pair.get("liquidity") or {}).get("usd") or 0)
            ret = (p1 / p0 - 1) * 100 if p0 > 0 else 0.0
            liq_ratio = l1 / l0 if l0 > 0 else 1.0
        bad = ret <= BAD_RETURN_PCT or liq_ratio <= BAD_LIQ_RATIO
        # market background: how much did SOL itself move over the same window?
        sol0 = float(d.get("sol") or 0)
        sol_ret = (sol1 / sol0 - 1) * 100 if (sol1 and sol0 > 0) else None
        xret = ret - sol_ret if sol_ret is not None else None
        v, c = d.get("verdict", "?"), d.get("conf", "?")
        bucket = min(9, int(float(d.get("score") or 0)) // 10)
        day = time.strftime("%Y%m%d", time.gmtime(int(d.get("ts") or 0)))
        flags_t = [f for f in (d.get("flags") or "").split(",") if f in RISK_WEIGHTS]
        src = d.get("src") or "untagged"  # v2.9: where the request came from; older rows have no label
        groups = ["all", f"v:{v}:{c}", f"rb:{bucket}", f"d:{day}", f"src:{src}", f"srcv:{src}:{v}"]
        groups += [f"f:{f}" for f in flags_t] + [f"fd:{f}:{day}" for f in flags_t]
        base_pred = "avoid" if BASELINE_FLAGS & set((d.get("flags") or "").split(",")) else "ok"
        groups += [f"vd:{v}:{c}:{day}", f"bl:{base_pred}", f"bd:{base_pred}:{day}"]  # per-day verdicts + the simple baseline
        groups += [f"sh:{rn}:{sv}" for rn, sv in _parse_shadow(d.get("shadow"))]  # v2.11: what the other rules would have said
        for g in groups:
            cmds.append(["HINCRBY", "st", f"{g}:n", 1])
            if bad:
                cmds.append(["HINCRBY", "st", f"{g}:bad", 1])
        cmds.append(["HINCRBYFLOAT", "st", f"v:{v}:{c}:ret", round(ret, 2)])
        if xret is not None:
            cmds += [["HINCRBYFLOAT", "st", f"v:{v}:{c}:xret", round(xret, 2)], ["HINCRBY", "st", f"v:{v}:{c}:xn", 1]]
        recent.append(json.dumps({"token": d.get("token"), "mint": d["mint"], "verdict": v, "risk_score": float(d.get("score") or 0),
                                  "return_pct": round(ret, 1), "sol_return_pct": round(sol_ret, 1) if sol_ret is not None else None,
                                  "excess_return_pct": round(xret, 1) if xret is not None else None,
                                  "bad_outcome": bad, "age_h": round(age / 3600, 1), "src": src}))
        cmds += _dataset_cmds(d, v, src, ret, liq_ratio, bad)  # v2.11.1: labelled row for later analysis
    for item in recent:
        cmds.append(["LPUSH", "recent", item])
    if recent:
        cmds.append(["LTRIM", "recent", 0, 49])
    if cmds:
        await redis_pipe(client, cmds)
    return len(ids)


_resolve_due_24h = resolve_due


async def _resolve_early_one(client: httpx.AsyncClient, hours: int, zset: str) -> int:
    """Judge predictions that reached the `hours` mark. Same bad-outcome rule as at 24h; the prediction is kept for 24h."""
    now = int(time.time())
    got = await redis_pipe(client, [["ZRANGEBYSCORE", zset, "-inf", now, "LIMIT", 0, RESOLVE_BATCH]])
    ids = (got or [[]])[0] or []
    if not ids:
        return 0
    hashes = await redis_pipe(client, [["HGETALL", f"pred:{i}"] for i in ids])
    if hashes is None:
        return 0
    cmds: list = []
    preds: Dict[str, dict] = {}
    for pid, h in zip(ids, hashes):
        d = to_dict(h)
        if d.get("mint"):
            preds[pid] = d
        else:
            cmds.append(["ZREM", zset, pid])  # hash gone (judged at 24h already, or expired): drop the entry
    best: Dict[str, Optional[dict]] = {}
    if preds:
        mints = sorted({d["mint"] for d in preds.values()})
        t0 = time.time()
        try:
            resp = await client.get(DEX_URL.format(mint=",".join(mints)))
            resp.raise_for_status()
            pairs = resp.json().get("pairs") or []
            src_log("dexscreener", True, t0)
        except (httpx.HTTPError, ValueError):
            src_log("dexscreener", False, t0)
            if cmds:
                await redis_pipe(client, cmds)
            return 0  # try again next cycle
        for m in mints:
            best[m] = pick_best_pair([p for p in pairs if (p.get("baseToken") or {}).get("address") == m], m)
    pre = f"h{hours}"
    for pid, d in preds.items():
        cmds.append(["ZREM", zset, pid])
        if d["mint"] in MAJOR_ASSETS:
            continue
        age = now - int(d.get("ts") or 0)
        if age > hours * 3600 * 3:
            continue  # judged far too late: would distort the numbers
        p0, l0 = float(d.get("price") or 0), float(d.get("liq") or 0)
        pair = best.get(d["mint"])
        if pair is None:
            ret, liq_ratio = -100.0, 0.0
        else:
            p1 = float(pair.get("priceUsd") or 0)
            l1 = float((pair.get("liquidity") or {}).get("usd") or 0)
            ret = (p1 / p0 - 1) * 100 if p0 > 0 else 0.0
            liq_ratio = l1 / l0 if l0 > 0 else 1.0
        bad = ret <= BAD_RETURN_PCT or liq_ratio <= BAD_LIQ_RATIO
        v = d.get("verdict", "?")
        groups = ["all", f"v:{v}", f"src:{d.get('src') or 'untagged'}"]
        groups += [f"sh:{rn}:{sv}" for rn, sv in _parse_shadow(d.get("shadow"))]
        for g in groups:
            cmds.append(["HINCRBY", "sth", f"{pre}:{g}:n", 1])
            if bad:
                cmds.append(["HINCRBY", "sth", f"{pre}:{g}:bad", 1])
        cmds.append(["HINCRBYFLOAT", "sth", f"{pre}:v:{v}:ret", round(ret, 2)])
        if DATASET_ENABLED:
            cmds.append(["HSET", f"pred:{pid}", f"ret_h{hours}", str(round(ret, 2))])  # the hash is still alive: it is kept until 24h
    if cmds:
        await redis_pipe(client, cmds)
    return len(ids)


async def resolve_due(client: httpx.AsyncClient) -> int:
    """24h judgments as before, then the early (1h / 6h) ones. Returns how many predictions were processed."""
    n = await _resolve_due_24h(client)
    for hours, zset in _EARLY:
        try:
            n += await _resolve_early_one(client, hours, zset)
        except Exception:  # noqa: BLE001
            pass  # the early checks must never break the 24h track record
    return n


# ---------- /stats and the MCP track record: shadow rules and early horizons ----------
def _cell(n: int, bad: int) -> dict:
    return {"n": n, "bad_outcome_rate_pct": round(bad / n * 100, 1) if n >= MIN_N_SHOW else None,
            "ci95_pct": [round(x * 100, 1) for x in wilson(bad, n)] if n >= MIN_N_SHOW else None}


def _shadow_table(st: dict, pre: str) -> dict:
    """Per rule: how its avoid / caution / ok groups did, on the same judged tokens. pre is '' (24h) or 'h1:' ..."""
    names = set()
    for key in st:
        if key.startswith(f"{pre}sh:") and key.endswith(":n"):
            names.add(key[len(pre) + 3:-2].rpartition(":")[0])
    rules: Dict[str, Any] = {}
    for name in sorted(names, key=lambda x: (x != "live", x)):
        cells = {v: (int(st.get(f"{pre}sh:{name}:{v}:n", 0)), int(st.get(f"{pre}sh:{name}:{v}:bad", 0))) for v in _VERDICTS}
        judged, bad = sum(c[0] for c in cells.values()), sum(c[1] for c in cells.values())
        an, ab = cells["avoid"]
        rules[name] = {"judged": judged, "bad": bad, **{v: _cell(*cells[v]) for v in _VERDICTS},
                       "avoid_precision_pct": round(ab / an * 100, 1) if an >= MIN_N_SHOW else None,
                       "avoid_recall_pct": round(ab / bad * 100, 1) if judged >= MIN_N_SHOW and bad > 0 else None}
    return rules


_sth_cache: Dict[str, Any] = {"ts": 0.0, "v": {}}


async def _get_sth(client: httpx.AsyncClient) -> dict:
    if time.time() - _sth_cache["ts"] > 120:
        got = await redis_pipe(client, [["HGETALL", "sth"]])
        if got is not None:
            _sth_cache.update(ts=time.time(), v=to_dict(got[0]))
    return _sth_cache["v"]


_stats_report_v22 = stats_report


async def stats_report(client: httpx.AsyncClient) -> dict:
    rep = await _stats_report_v22(client)
    if not (rep.get("enabled") and rep.get("available") is not False):
        return rep
    note = ("Shadow rules (v2.11): each new verdict also records what 5 alternative rules would have said, so every rule is "
            "judged on the same tokens (only verdicts made since v2.11 are included). 'live' is the real verdict. "
            "Early horizons judge the same verdicts after 1h and 6h with the same definition of a bad outcome. "
            "Rates stay hidden under 20 samples per group; do not tune anything from small numbers.")
    extra: Dict[str, Any] = {}
    if SHADOW_ENABLED:
        extra["shadow_rules"] = {"horizon_hours": round(PRED_HORIZON_S / 3600, 1), "rules": _shadow_table(_raw_st["st"], "")}
    if _EARLY:
        sth = await _get_sth(client)
        early: Dict[str, Any] = {}
        for hours, _ in _EARLY:
            pre = f"h{hours}:"
            n, bad = int(sth.get(f"{pre}all:n", 0)), int(sth.get(f"{pre}all:bad", 0))
            early[f"{hours}h"] = {**_cell(n, bad), "by_verdict": {v: _cell(int(sth.get(f"{pre}v:{v}:n", 0)), int(sth.get(f"{pre}v:{v}:bad", 0))) for v in _VERDICTS},
                                  "shadow_rules": _shadow_table(sth, pre) if SHADOW_ENABLED else {}}
        extra["early_horizons"] = early
    return dict(rep, **extra, caveats=list(rep.get("caveats") or []) + [note])


print(f"[part24] v{VERSION} shadow rules ({'on' if SHADOW_ENABLED else 'off'}: {', '.join(SHADOW_RULES)}), early checks at {[h for h, _ in _EARLY] or 'none'}h")

# --- part25 ---
# ---------- part25: v2.12.0 - /status: a small live status page (reads /health in the browser) ----------
# Loads before part7. Adds one route and changes nothing else. Seed speed is set with env vars, not here:
# SEED_MAX_PER_DAY and SEED_INTERVAL_S (keep interval about 86400 / max_per_day so samples spread over the whole day).
VERSION = "2.12.0"
app.version = VERSION
app.openapi_schema = None

STATUS_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVibex402 status</title>
<style>
  :root { --bg:#0f1117; --card:#1a1d27; --green:#22c55e; --yellow:#eab308; --red:#ef4444; --grey:#64748b; --text:#e2e8f0; --muted:#94a3b8; }
  body { font-family: system-ui, sans-serif; background:var(--bg); color:var(--text); margin:0; padding:1rem; }
  .card { background:var(--card); border-radius:12px; padding:1.25rem; margin:0 auto 1rem; max-width:760px; }
  h1 { margin:0 0 .25rem; font-size:1.4rem; }
  .badge { display:inline-block; padding:.15rem .6rem; border-radius:9999px; font-size:.8rem; font-weight:600; }
  .ok { background:var(--green); color:#052e16; }
  .degraded { background:var(--yellow); color:#422006; }
  .down { background:var(--red); color:#450a0a; }
  .unknown { background:var(--grey); color:#f1f5f9; }
  table { width:100%; border-collapse:collapse; margin-top:.75rem; }
  th, td { text-align:left; padding:.45rem .5rem; border-bottom:1px solid #2d3348; font-size:.9rem; }
  th { color:var(--muted); font-weight:500; }
  .muted { color:var(--muted); font-size:.85rem; }
  a { color:#60a5fa; }
</style>
</head>
<body>
<div class="card">
  <h1>TVibex402 status</h1>
  <p class="muted">Live from /health. Refreshes every minute while this tab is open.</p>
  <div id="status">Loading...</div>
  <noscript><p>This page needs JavaScript. The same data is at <a href="/health">/health</a>.</p></noscript>
</div>
<script>
(function () {
  var root = document.getElementById('status');
  function el(tag, text, cls) {
    var n = document.createElement(tag);
    if (text !== undefined && text !== null) { n.textContent = String(text); }
    if (cls) { n.className = cls; }
    return n;
  }
  function badge(s) {
    var known = ['ok', 'degraded', 'down'].indexOf(s) >= 0;
    return el('span', String(s).toUpperCase(), 'badge ' + (known ? s : 'unknown'));
  }
  function cell(content) {
    var td = document.createElement('td');
    if (typeof content === 'object' && content !== null) { td.appendChild(content); } else { td.textContent = String(content); }
    return td;
  }
  function render(d) {
    var src = d.sources || {};
    var names = Object.keys(src);
    var bad = false;
    names.forEach(function (k) { var s = src[k].status; if (s === 'down' || s === 'degraded') { bad = true; } });
    var overall = d.status !== 'ok' ? 'down' : (bad ? 'degraded' : 'ok');
    while (root.firstChild) { root.removeChild(root.firstChild); }
    var top = el('p');
    top.appendChild(badge(overall));
    top.appendChild(el('span', ' Version ' + d.version + ' - up ' + Math.floor((d.uptime_s || 0) / 60) + ' min'));
    root.appendChild(top);
    var table = el('table');
    var head = el('tr');
    ['Source', 'Status', 'Success', 'Avg', 'Samples'].forEach(function (h) { head.appendChild(el('th', h)); });
    table.appendChild(head);
    names.forEach(function (k) {
      var s = src[k] || {};
      var tr = el('tr');
      tr.appendChild(cell(k));
      tr.appendChild(cell(badge(s.status || 'unknown')));
      tr.appendChild(cell(s.success_rate_pct !== undefined ? s.success_rate_pct + '%' : '-'));
      tr.appendChild(cell(s.avg_ms !== undefined ? s.avg_ms + ' ms' : '-'));
      tr.appendChild(cell(s.samples !== undefined ? s.samples : '-'));
      table.appendChild(tr);
    });
    root.appendChild(table);
    var seed = d.seed || {};
    var up = d.upstream || {};
    var store = d.track_record_store || {};
    var lines = [
      'Track record: ' + (d.track_record ? 'on' : 'off') + (d.track_record ? (store.reachable ? ' (store reachable)' : ' (store NOT reachable)') : ''),
      'Price cross-check: ' + (up.status || 'unknown') + (up.price_diff_pct !== undefined && up.price_diff_pct !== null ? ' (gap ' + up.price_diff_pct + '%)' : ''),
      'Seeded today: ' + (seed.seeded_today !== undefined ? seed.seeded_today : 0) + ' of ' + (seed.max_per_day !== undefined ? seed.max_per_day : '?'),
      'MCP: ' + (d.mcp ? 'on' : 'off')
    ];
    lines.forEach(function (t) { var p = el('p', t, 'muted'); p.style.margin = '.25rem 0'; root.appendChild(p); });
    var links = el('p', null, 'muted');
    [['/', 'Home'], ['/accuracy', 'Accuracy'], ['/health', 'Health JSON'], ['/metrics', 'Metrics']].forEach(function (l, i) {
      if (i) { links.appendChild(document.createTextNode(' - ')); }
      var a = el('a', l[1]); a.href = l[0]; links.appendChild(a);
    });
    root.appendChild(links);
  }
  function load() {
    if (typeof document.hidden !== 'undefined' && document.hidden) { return; }
    fetch('/health', { cache: 'no-store' })
      .then(function (r) { if (!r.ok) { throw new Error('HTTP ' + r.status); } return r.json(); })
      .then(render)
      .catch(function () {
        while (root.firstChild) { root.removeChild(root.firstChild); }
        var p = el('p'); p.appendChild(badge('down')); p.appendChild(el('span', ' Could not read /health right now.'));
        root.appendChild(p);
      });
  }
  load();
  setInterval(load, 60000);
  document.addEventListener('visibilitychange', load);
})();
</script>
</body>
</html>"""


@app.get("/status", include_in_schema=False)
async def status_page():
    return HTMLResponse(STATUS_HTML, headers={"Cache-Control": "no-cache"})


print(f"[part25] v{VERSION} /status page ready")

# --- part26 ---
# ---------- part26: v2.13.6 - /play: polished playground for any Solana token ----------
# Loads before part7. One route, no new dependency. Calls public /signal + /exit (rate limits apply).
# All network text is rendered with textContent (never innerHTML) — token names are hostile.
VERSION = "2.13.6"
app.version = VERSION
app.openapi_schema = None

PLAY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#070a10">
<meta name="color-scheme" content="dark">
<title>TVibex402 playground</title>
<style>
@property --p { syntax: "<number>"; inherits: false; initial-value: 0; }
:root {
  --bg: #070a10; --surface: #0f1521; --raised: #151d2d; --line: #222d42; --line2: #34425e;
  --text: #eef2f8; --muted: #8fa0bb; --accent: #7c83ff; --accent-soft: rgba(124,131,255,.16);
  --ok: #2dd4a0; --caution: #f5b83d; --avoid: #ff5d6c; --unknown: #7d8aa3;
  --track: #1b2437; --radius: 16px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  background-image: radial-gradient(ellipse 70% 40% at 50% -10%, rgba(124,131,255,.16), transparent);
  background-repeat: no-repeat;
  color: var(--text); line-height: 1.55; min-height: 100vh; padding: 1.75rem 1rem 4rem;
}
.wrap { max-width: 700px; margin: 0 auto; }
h1 { font-size: 1.7rem; font-weight: 750; letter-spacing: -.03em; }
h1 span { color: var(--accent); }
.sub { color: var(--muted); font-size: .92rem; margin: .2rem 0 1.2rem; }
.disclaimer {
  font-size: .8rem; color: var(--muted); margin-bottom: 1.3rem;
  padding: .55rem .85rem; border-left: 3px solid var(--caution);
  background: rgba(245,184,61,.06); border-radius: 0 10px 10px 0;
}
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.row {
  display: flex; gap: .5rem; padding: .4rem; margin-bottom: .75rem;
  background: var(--surface); border: 1px solid var(--line2); border-radius: 14px;
  transition: border-color .2s, box-shadow .2s;
}
.row:focus-within { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-soft); }
input {
  flex: 1; min-width: 0; background: transparent; border: 0; outline: none; color: var(--text);
  padding: .75rem .85rem; font-size: .95rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
button {
  background: var(--accent); color: #fff; border: 0; border-radius: 10px; padding: 0 1.5rem;
  font-weight: 650; font-size: .95rem; cursor: pointer; min-height: 44px;
  transition: filter .15s, transform .1s;
}
button:hover { filter: brightness(1.12); }
button:active { transform: scale(.97); }
button:disabled { opacity: .5; cursor: not-allowed; }
.chips { display: flex; align-items: center; flex-wrap: wrap; gap: .4rem; margin-bottom: 1.6rem; font-size: .8rem; color: var(--muted); }
.chip {
  background: var(--surface); border: 1px solid var(--line); color: var(--text);
  padding: .3rem .85rem; border-radius: 999px; font-size: .8rem; font-weight: 550; cursor: pointer;
  min-height: 0; transition: border-color .15s, background .15s;
}
.chip:hover { border-color: var(--accent); background: var(--accent-soft); filter: none; }

/* verdict colour system: every card/group sets --vc (main), --vs (tint), --vb (border) */
.v-ok, .g-ok { --vc: var(--ok); --vs: rgba(45,212,160,.14); --vb: rgba(45,212,160,.4); }
.v-caution, .g-caution { --vc: var(--caution); --vs: rgba(245,184,61,.14); --vb: rgba(245,184,61,.4); }
.v-avoid, .g-avoid { --vc: var(--avoid); --vs: rgba(255,93,108,.15); --vb: rgba(255,93,108,.45); }
.v-unknown, .g-unknown { --vc: var(--unknown); --vs: rgba(125,138,163,.14); --vb: rgba(125,138,163,.35); }

.card {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 1.25rem; margin-bottom: 1rem;
}
.card.hero { background: linear-gradient(150deg, var(--vs), transparent 60%), var(--surface); border-color: var(--vb); }
.top { display: flex; align-items: center; gap: 1.1rem; }
.ring {
  --p: 0; flex: none; position: relative; width: 96px; height: 96px; border-radius: 50%;
  display: grid; place-items: center; text-align: center;
  background: conic-gradient(var(--vc) calc(var(--p) * 1%), var(--track) 0);
  transition: --p 1.1s cubic-bezier(.2, .8, .2, 1);
}
.ring::before { content: ""; position: absolute; inset: 9px; border-radius: 50%; background: var(--surface); }
.ring div { position: relative; line-height: 1.1; }
.ring b { display: block; font-size: 1.7rem; font-weight: 750; font-variant-numeric: tabular-nums; }
.ring small { font-size: .68rem; color: var(--muted); }
.vword { display: flex; align-items: center; gap: .55rem; font-size: 2rem; font-weight: 800; letter-spacing: -.03em; color: var(--vc); line-height: 1.1; }
.vicon {
  display: inline-grid; place-items: center; width: 1.7rem; height: 1.7rem; border-radius: 50%;
  background: var(--vc); color: var(--bg); font-size: 1rem; font-weight: 800;
}
.tname { font-weight: 600; margin-top: .25rem; }
.summary { font-size: .95rem; margin: 1rem 0 .3rem; }
.meta { color: var(--muted); font-size: .78rem; word-break: break-all; font-family: ui-monospace, Menlo, monospace; }
.note { color: var(--muted); font-size: .8rem; }

.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(135px, 1fr)); gap: .55rem; margin: 1.1rem 0 .4rem; }
.metric { background: var(--raised); border: 1px solid var(--line); border-radius: 12px; padding: .75rem .9rem; border-top: 3px solid var(--line2); }
.metric .l { color: var(--muted); font-size: .76rem; margin-bottom: .15rem; }
.metric .v { font-size: 1.15rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.metric.t-ok { border-top-color: var(--ok); }
.metric.t-caution { border-top-color: var(--caution); }
.metric.t-avoid { border-top-color: var(--avoid); }

h3 { font-size: .95rem; font-weight: 700; margin: 1.4rem 0 .55rem; letter-spacing: -.01em; }
.groups { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: .6rem; align-items: start; }
.g-unknown { grid-column: 1 / -1; }
.grp { background: var(--vs); border: 1px solid var(--vb); border-left: 4px solid var(--vc); border-radius: 12px; padding: .75rem .9rem; }
.gh { display: flex; align-items: center; gap: .5rem; font-weight: 700; font-size: .9rem; color: var(--vc); margin-bottom: .3rem; }
.gh i {
  font-style: normal; display: inline-grid; place-items: center; width: 1.2rem; height: 1.2rem;
  border-radius: 50%; background: var(--vc); color: var(--bg); font-size: .72rem; font-weight: 800;
}
.gh em { margin-left: auto; font-style: normal; font-size: .75rem; color: var(--muted); font-weight: 600; }
ul { padding-left: 1.05rem; }
li { margin: .25rem 0; font-size: .88rem; color: #d3dbe9; }
.flag { display: inline-block; background: var(--raised); border: 1px solid var(--line2); border-radius: 8px; padding: .3rem .7rem; font-size: .84rem; font-weight: 550; margin: .2rem .3rem .2rem 0; color: #cdd6e8; }
.acts { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .7rem; }
.ghost { background: var(--raised); border: 1px solid var(--line2); color: var(--muted); min-height: 0; padding: .3rem .85rem; font-size: .78rem; font-weight: 600; border-radius: 8px; }
.ghost:hover { color: var(--text); border-color: var(--accent); filter: none; }

.sellhead { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; margin-bottom: .6rem; font-size: .88rem; }
.sell { display: grid; grid-template-columns: 5.5rem 1fr 5rem; align-items: center; gap: .7rem; padding: .3rem 0; font-size: .88rem; }
.bar { height: 8px; border-radius: 99px; background: var(--track); overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 99px; background: var(--vc); }
.sell b { text-align: right; color: var(--vc); font-variant-numeric: tabular-nums; }

.badge { display: inline-block; padding: .18rem .7rem; border-radius: 99px; font-size: .75rem; font-weight: 700; color: var(--vc); background: var(--vs); border: 1px solid var(--vb); }
.err { color: var(--avoid); font-size: .92rem; border-left: 4px solid var(--avoid); padding-left: .8rem; }

pre { background: var(--bg); border: 1px solid var(--line); border-radius: 10px; padding: .85rem; overflow-x: auto; font-size: .72rem; max-height: 260px; margin-top: .5rem; color: #94a3b8; }
details { margin-top: 1.1rem; }
summary { cursor: pointer; color: var(--muted); font-size: .84rem; user-select: none; }
summary:hover { color: var(--text); }
.why { background: var(--raised); border-left: 4px solid var(--accent); border-radius: 0 12px 12px 0; padding: .9rem 1rem; }
.why .head { font-weight: 700; margin-bottom: .45rem; }
.why p { margin: .3rem 0; font-size: .88rem; color: var(--muted); }
.fl { display: flex; gap: .7rem; padding: .5rem 0; border-top: 1px solid var(--line); font-size: .88rem; }
.pts { min-width: 2.6rem; font-weight: 750; color: var(--caution); font-variant-numeric: tabular-nums; }
.role { font-size: .75rem; color: var(--muted); margin-top: .1rem; }
.role.blocker { color: var(--avoid); } .role.caution { color: var(--caution); } .role.positive { color: var(--ok); }
.tabs { display: inline-flex; gap: .2rem; padding: .2rem; margin-bottom: .6rem; background: var(--raised); border: 1px solid var(--line); border-radius: 10px; }
.tab { background: transparent; color: var(--muted); border-radius: 8px; padding: .25rem .8rem; font-size: .8rem; min-height: 0; font-weight: 600; }
.tab.on { background: var(--accent); color: #fff; }
.links { margin-top: 2rem; font-size: .82rem; display: flex; flex-wrap: wrap; gap: .3rem 1.1rem; }
.links a { color: #9aa0ff; text-decoration: none; }
.links a:hover { text-decoration: underline; }

@keyframes shimmer { 0% { background-position: -600px 0; } 100% { background-position: 600px 0; } }
@keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
.sk { background: linear-gradient(90deg, #121826 0%, #1c2438 50%, #121826 100%); background-size: 1200px 100%; animation: shimmer 1.4s linear infinite; border-radius: 10px; }
.sk-ring { width: 96px; height: 96px; border-radius: 50%; flex: none; }
.sk-line { height: .8rem; margin: .55rem 0; } .sk-l60 { width: 60%; } .sk-l90 { width: 90%; }
.sk-metric { height: 3.6rem; border-radius: 12px; }
.enter { animation: rise .4s ease-out both; }
@media (prefers-reduced-motion: reduce) { .sk, .enter { animation: none !important; } .ring { transition: none !important; } }
@media (max-width: 480px) {
  .row { flex-direction: column; } .row button { width: 100%; }
  body { padding: 1.2rem .75rem 3rem; } .vword { font-size: 1.6rem; }
  .sell { grid-template-columns: 4.6rem 1fr 4.2rem; }
}
</style>
</head>
<body>
<div class="wrap">
<h1>TVibex402 <span>playground</span></h1>
<p class="sub">Paste a Solana token address to get a verdict, the reasons behind it, and what it costs to sell.</p>
<div class="disclaimer">Heuristic only. Not a security audit and not financial advice. Data can be late or wrong.</div>
<div class="row">
<input id="mint" type="text" placeholder="Paste Solana mint address…" autocomplete="off" spellcheck="false" aria-label="Solana mint address">
<button id="btn" type="button">Check</button>
</div>
<div class="chips">Try
<button type="button" class="chip" data-mint="So11111111111111111111111111111111111111112">SOL</button>
<button type="button" class="chip" data-mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v">USDC</button>
<span id="recent" style="display:contents"></span>
</div>
<div id="result" aria-live="polite"></div>
<p class="links">
<a href="/">Home</a>
<a href="/status">Status</a>
<a href="/accuracy">Accuracy</a>
<a href="/docs">API docs</a>
<a href="/methodology">Methodology</a>
<a href="/pricing">Pricing</a>
</p>
</div>
<script>
(function () {
  var MINT_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
  var out = document.getElementById('result');
  var input = document.getElementById('mint');
  var btn = document.getElementById('btn');
  var lang = ((navigator.language || 'en').toLowerCase().indexOf('vi') === 0) ? 'vi' : 'en';
  var last = null;
  var VERDICTS = { ok: ['Looks OK', '✓'], caution: ['Caution', '!'], avoid: ['Avoid', '✕'], unknown: ['Unknown', '?'] };

  function el(tag, text, cls) {
    var n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function vkey(v) { return VERDICTS[v] ? v : 'unknown'; }
  function usd(x) {
    var n = Number(x);
    return isFinite(n) ? '$' + n.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—';
  }
  function price(x) {
    var n = Number(x);
    return isFinite(n) && n > 0 ? '$' + n.toPrecision(4) : '—';
  }
  function age(min) {
    var m = Number(min);
    if (!isFinite(m) || m < 0) return '—';
    var h = m / 60;
    return h < 48 ? Math.floor(h) + ' h' : Math.floor(h / 24) + ' d';
  }
  function scoreTone(s) {
    var n = Number(s);
    if (!isFinite(n)) return '';
    return n >= 60 ? 't-ok' : n >= 35 ? 't-caution' : 't-avoid';
  }
  function nice(f) { var t = String(f).replace(/_/g, ' '); return t.charAt(0).toUpperCase() + t.slice(1); }
  function gradeKey(g) {
    g = String(g || '').toLowerCase();
    if (['good', 'great', 'excellent', 'a', 'b'].indexOf(g) >= 0) return 'ok';
    if (['fair', 'ok', 'moderate', 'medium', 'c'].indexOf(g) >= 0) return 'caution';
    if (!g || g === '—') return 'unknown';
    return 'avoid';
  }
  function copyBtn(label, text) {
    var b = el('button', label, 'ghost');
    b.type = 'button';
    b.addEventListener('click', function () {
      var done = function (t) { b.textContent = t; setTimeout(function () { b.textContent = label; }, 1400); };
      try { navigator.clipboard.writeText(text).then(function () { done('Copied ✓'); }, function () { done('Copy failed'); }); }
      catch (e) { done('Copy failed'); }
    });
    return b;
  }
  var RKEY = 'tvx402_recent';
  function loadRecent() {
    try { var a = JSON.parse(localStorage.getItem(RKEY) || '[]'); return Array.isArray(a) ? a : []; } catch (e) { return []; }
  }
  function saveRecent(mint, name) {
    if (!mint || !MINT_RE.test(mint)) return;
    var a = loadRecent().filter(function (x) { return x && x.m !== mint; });
    a.unshift({ m: mint, n: String(name || mint.slice(0, 4)).slice(0, 12) });
    try { localStorage.setItem(RKEY, JSON.stringify(a.slice(0, 5))); } catch (e) {}
    drawRecent();
  }
  function drawRecent() {
    var box = document.getElementById('recent');
    clear(box);
    loadRecent().forEach(function (x) {
      if (!x || !MINT_RE.test(String(x.m))) return;
      var c = el('button', x.n, 'chip');
      c.type = 'button';
      c.addEventListener('click', function () { input.value = x.m; check(); });
      box.appendChild(c);
    });
  }
  function lossKey(p) { return p < 3 ? 'ok' : p < 10 ? 'caution' : 'avoid'; }
  function metric(label, value, tone) {
    var d = el('div', null, 'metric ' + (tone || ''));
    d.appendChild(el('div', label, 'l'));
    d.appendChild(el('div', value, 'v'));
    return d;
  }
  function list(items) {
    var ul = el('ul');
    (Array.isArray(items) ? items : []).slice(0, 10).forEach(function (x) { ul.appendChild(el('li', x)); });
    return ul;
  }
  function sk(cls) { return el('div', null, 'sk ' + cls); }

  function showSkeleton() {
    clear(out);
    out.setAttribute('aria-busy', 'true');
    var card = el('div', null, 'card');
    var top = el('div', null, 'top');
    top.appendChild(sk('sk-ring'));
    var side = el('div');
    side.style.flex = '1';
    side.appendChild(sk('sk-line sk-l60'));
    side.appendChild(sk('sk-line sk-l90'));
    top.appendChild(side);
    card.appendChild(top);
    var grid = el('div', null, 'grid');
    for (var i = 0; i < 4; i++) grid.appendChild(sk('sk-metric'));
    card.appendChild(grid);
    card.appendChild(sk('sk-line sk-l90'));
    out.appendChild(card);
  }

  function whyBox(xp) {
    var box = el('div');
    var e = xp && xp[lang];
    if (!e) return box;
    box.appendChild(el('h3', lang === 'vi' ? 'Vì sao có kết quả này' : 'Why this verdict'));
    var tabs = el('div', null, 'tabs');
    [['en', 'English'], ['vi', 'Tiếng Việt']].forEach(function (t) {
      var b = el('button', t[1], 'tab' + (lang === t[0] ? ' on' : ''));
      b.type = 'button';
      b.addEventListener('click', function () {
        lang = t[0];
        if (last) render(last.d, last.ex, last.xp, true);
      });
      tabs.appendChild(b);
    });
    box.appendChild(tabs);
    var w = el('div', null, 'why');
    w.appendChild(el('div', e.headline, 'head'));
    (e.why || []).forEach(function (x) { w.appendChild(el('p', x)); });
    (e.flags || []).slice(0, 12).forEach(function (f) {
      var row = el('div', null, 'fl');
      row.appendChild(el('div', f.counted ? '+' + f.points : '—', 'pts'));
      var body = el('div');
      body.appendChild(el('div', f.text));
      var rc = ['blocker', 'caution', 'positive'].indexOf(f.role) >= 0 ? f.role : '';
      body.appendChild(el('div', f.flag + ' · ' + f.role + (f.counted ? '' : ' (not scored)'), 'role ' + rc));
      row.appendChild(body);
      w.appendChild(row);
    });
    (e.what_would_change || []).forEach(function (x) { w.appendChild(el('p', x)); });
    if (e.note) w.appendChild(el('p', e.note));
    box.appendChild(w);
    return box;
  }

  function sellBox(ex) {
    var box = el('div');
    if (!(ex && ex.exit && ex.exit.available)) {
      box.appendChild(el('p', 'Sell check is not available for this token right now.', 'note'));
      return box;
    }
    var head = el('div', null, 'sellhead');
    head.appendChild(el('span', 'Exit grade: ' + (ex.exit.grade || '—'), 'badge v-' + gradeKey(ex.exit.grade)));
    head.appendChild(el('span', 'Overall: ' + (ex.combined_verdict || '—'), 'badge v-' + vkey(ex.combined_verdict)));
    box.appendChild(head);
    (ex.exit.levels || []).forEach(function (l) {
      var loss = Number(l.loss_vs_market_pct);
      var ok = isFinite(loss);
      var row = el('div', null, 'sell v-' + (ok ? lossKey(loss) : 'unknown'));
      row.appendChild(el('span', 'Sell ' + usd(l.size_usd)));
      var bar = el('div', null, 'bar');
      var fill = el('i');
      fill.style.width = (ok ? Math.max(3, Math.min(100, loss * 4)) : 0) + '%';
      bar.appendChild(fill);
      row.appendChild(bar);
      row.appendChild(el('b', ok ? loss.toFixed(1) + '% lost' : (l.status || 'no quote')));
      box.appendChild(row);
    });
    box.appendChild(el('p', 'A quote does not prove a real sell will succeed.', 'note'));
    return box;
  }

  function render(d, ex, xp, still) {
    last = { d: d, ex: ex, xp: xp };
    clear(out);
    out.setAttribute('aria-busy', 'false');
    var dec = d.decision || {};
    var hq = d.holder_quality || {};
    var vk = vkey(d.verdict);
    var card = el('div', null, 'card hero v-' + vk + (still ? '' : ' enter'));

    var top = el('div', null, 'top');
    var ring = el('div', null, 'ring');
    var risk = Number(d.risk_score);
    var target = isFinite(risk) ? Math.max(0, Math.min(100, risk)) : 0;
    ring.style.setProperty('--p', still ? target : 0);
    var inner = el('div');
    inner.appendChild(el('b', isFinite(risk) ? risk : '—'));
    inner.appendChild(el('small', 'risk / 100'));
    ring.appendChild(inner);
    top.appendChild(ring);
    var side = el('div');
    var vw = el('div', null, 'vword');
    vw.appendChild(el('span', VERDICTS[vk][1], 'vicon'));
    vw.appendChild(el('span', VERDICTS[vk][0]));
    side.appendChild(vw);
    side.appendChild(el('div', d.token || d.name || 'Unnamed token', 'tname'));
    top.appendChild(side);
    card.appendChild(top);

    card.appendChild(el('p', d.summary || '', 'summary'));
    card.appendChild(el('p', d.mint || '', 'meta'));
    if (d.mint) {
      var acts = el('div', null, 'acts');
      acts.appendChild(copyBtn('Copy address', d.mint));
      acts.appendChild(copyBtn('Copy link', location.origin + '/play?mint=' + encodeURIComponent(d.mint)));
      card.appendChild(acts);
    }

    var grid = el('div', null, 'grid');
    grid.appendChild(metric('Liquidity', usd(d.liquidity_usd)));
    grid.appendChild(metric('Price', price(d.price_usd)));
    grid.appendChild(metric('Pair age', age(d.pair_age_minutes)));
    grid.appendChild(metric('Holder quality', (hq.score !== undefined ? hq.score : '—') + ' / 100', scoreTone(hq.score)));
    card.appendChild(grid);

    card.appendChild(whyBox(xp));

    var gwrap = el('div', null, 'groups');
    [['Blockers', 'avoid', '✕', dec.blockers], ['Cautions', 'caution', '!', dec.cautions],
     ['Positives', 'ok', '✓', dec.positives], ['Unknown', 'unknown', '?', dec.unknowns]].forEach(function (g) {
      if (!Array.isArray(g[3]) || !g[3].length) return;
      var box = el('div', null, 'grp g-' + g[1]);
      var gh = el('div', null, 'gh');
      gh.appendChild(el('i', g[2]));
      gh.appendChild(el('span', g[0]));
      gh.appendChild(el('em', g[3].length));
      box.appendChild(gh);
      box.appendChild(list(g[3]));
      gwrap.appendChild(box);
    });
    if (gwrap.firstChild) { card.appendChild(el('h3', 'Signals')); card.appendChild(gwrap); }

    var flags = el('div');
    (Array.isArray(d.flags) ? d.flags : []).slice(0, 24).forEach(function (f) { flags.appendChild(el('span', nice(f), 'flag')); });
    if (flags.firstChild) { card.appendChild(el('h3', 'Flags')); card.appendChild(flags); }

    card.appendChild(el('h3', 'Cost to sell (Jupiter)'));
    card.appendChild(sellBox(ex));

    var next = list(d.suggested_next || dec.next_checks);
    if (next.firstChild) { card.appendChild(el('h3', 'Next steps')); card.appendChild(next); }

    card.appendChild(el('p', dec.disclaimer || 'Heuristic output, not financial advice.', 'note')).style.marginTop = '1rem';

    var det = el('details');
    det.appendChild(el('summary', 'Raw JSON'));
    det.appendChild(el('pre', JSON.stringify(d, null, 2)));
    card.appendChild(det);
    out.appendChild(card);
    if (!still) requestAnimationFrame(function () { requestAnimationFrame(function () { ring.style.setProperty('--p', target); }); });
    if (!still) saveRecent(d.mint, d.token || d.name);
  }

  function showError(msg) {
    clear(out);
    out.setAttribute('aria-busy', 'false');
    var c = el('div', null, 'card');
    c.appendChild(el('p', msg, 'err'));
    out.appendChild(c);
  }

  function getJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (b) {
        return { ok: r.ok, status: r.status, retry: r.headers.get('Retry-After'), body: b };
      });
    });
  }

  function check() {
    var mint = input.value.trim();
    if (!MINT_RE.test(mint)) {
      showError('That does not look like a Solana token address. Paste a mint (32–44 base58 characters).');
      return;
    }
    btn.disabled = true;
    btn.textContent = 'Checking…';
    showSkeleton();
    var q = encodeURIComponent(mint);
    Promise.all([
      getJson('/signal?mint=' + q),
      getJson('/exit?mint=' + q + '&sizes=100,1000'),
      getJson('/signal?mint=' + q + '&explain=1').catch(function () { return { ok: false, body: {} }; })
    ]).then(function (res) {
      var sig = res[0], ex = res[1], xp = res[2];
      if (!sig.ok) {
        var msg = (sig.body && (sig.body.detail || sig.body.message)) || ('HTTP ' + sig.status);
        if (sig.status === 429) msg = 'Rate limited. Retry after ' + (sig.retry || 'a few') + 's.';
        if (sig.status === 503) msg = 'Service temporarily unavailable (host may be sleeping). Retry in a few seconds.';
        showError(msg);
        return;
      }
      render(sig.body, ex.ok ? ex.body : null, (xp.ok && xp.body && xp.body.explain) ? xp.body.explain : null);
    }).catch(function (e) {
      showError(e.message || 'Network error');
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = 'Check';
    });
  }

  drawRecent();
  btn.addEventListener('click', check);
  input.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') check(); });
  document.querySelectorAll('.chip').forEach(function (c) {
    c.addEventListener('click', function () {
      input.value = c.getAttribute('data-mint');
      check();
    });
  });
  var preset = new URLSearchParams(window.location.search).get('mint');
  if (preset && MINT_RE.test(preset.trim())) {
    input.value = preset.trim();
    check();
  }
})();
</script>
</body>
</html>
"""


@app.get("/play", include_in_schema=False)
async def playground():
    return HTMLResponse(PLAY_HTML, headers={"Cache-Control": "no-cache"})


print(f"[part26] v{VERSION} playground ready at /play (share a token with /play?mint=<address>)")

# --- part27 ---
# ---------- part27: v2.14.0 - optional Telegram bot: send a token address, get the verdict ----------
# Loads before part7. Does nothing unless BOTH env vars are set: TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET.
# Telegram sends updates to /telegram/webhook; the secret header must match, so strangers cannot make the bot send messages.
# Work runs in the background so the webhook answers at once (Telegram retries slow webhooks and would double the replies).
import hmac
import html as _html

VERSION = "2.14.0"
app.version = VERSION
app.openapi_schema = None

TG_RATE_PER_MIN = 8   # per chat; over that the bot stays silent
TG_FETCH_TIMEOUT_S = 25.0
_TG_CHECK_RE = re.compile(r"^/check(?:@\w+)?\s+(\S+)", re.I)
_TG_HELP = ("<b>TVibex402 bot</b>\n\nSend a Solana token address, or <code>/check &lt;address&gt;</code>.\n"
            "You get the verdict, the reasons and holder quality.\n\n"
            "Heuristic output, not a security audit and not financial advice.")


def _tg_cfg() -> tuple:
    return (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip(), (os.getenv("TELEGRAM_WEBHOOK_SECRET") or "").strip()


def _e(x: Any, limit: int = 120) -> str:
    """Escape text that came from the network before it goes into an HTML message."""
    return _html.escape(str(x if x is not None else "-")[:limit], quote=False)


def _tg_format(d: dict) -> str:
    v = str(d.get("verdict") or "unknown")
    icon = {"ok": "\u2705", "caution": "\u26a0\ufe0f", "avoid": "\U0001f6ab"}.get(v, "\u2139\ufe0f")
    dec, hq = d.get("decision") or {}, d.get("holder_quality") or {}
    try:
        liq = f"${float(d.get('liquidity_usd')):,.0f}"
    except (TypeError, ValueError):
        liq = "-"
    lines = [f"{icon} <b>{_e(d.get('token') or d.get('name') or 'token', 32)}</b> - <b>{_e(v.upper(), 12)}</b>",
             f"Risk {_e(d.get('risk_score'), 6)}/100 | Holder quality {_e(hq.get('score'), 6)}/100 | Liquidity {_e(liq, 20)}"]
    if d.get("summary"):
        lines += ["", _e(d["summary"], 300)]
    for title, key in (("Blockers", "blockers"), ("Cautions", "cautions")):
        items = [x for x in (dec.get(key) or []) if x][:5]
        if items:
            lines += ["", f"<b>{title}:</b>"] + [f"- {_e(x, 160)}" for x in items]
    mint = str(d.get("mint") or "")
    if MINT_RE.match(mint):  # validated base58, safe inside a link
        lines += ["", f'<a href="https://solscan.io/token/{mint}">Solscan</a>']
    lines += ["", "<i>Heuristic output, not financial advice.</i>"]
    return "\n".join(lines)[:4000]


async def _tg_send(client: httpx.AsyncClient, token: str, chat_id: int, text: str) -> None:
    try:
        await client.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=10.0,
                          json={"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True})
    except Exception:  # noqa: BLE001
        pass  # never raise out of a background task, and never log the token


async def _tg_handle(client: httpx.AsyncClient, token: str, chat_id: int, text: str, private: bool) -> None:
    low = text.lower()
    if low.startswith("/start") or low.startswith("/help"):
        await _tg_send(client, token, chat_id, _TG_HELP)
        return
    m = _TG_CHECK_RE.match(text)
    mint = m.group(1) if m else (text if private else "")  # in groups only /check reacts, so the bot does not answer every message
    if not mint:
        return
    if not MINT_RE.match(mint):
        await _tg_send(client, token, chat_id, "That does not look like a Solana token address.\n\n" + _TG_HELP)
        return
    try:
        result, _status = await asyncio.wait_for(build_signal(client, mint, True), TG_FETCH_TIMEOUT_S)
    except HTTPException as exc:
        await _tg_send(client, token, chat_id, f"No data for this token: {_e(exc.detail, 100)}")
        return
    except Exception:  # noqa: BLE001
        await _tg_send(client, token, chat_id, "Could not get data right now. Please try again in a minute.")
        return
    await _tg_send(client, token, chat_id, _tg_format(result))


@app.post("/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request):
    token, secret = _tg_cfg()
    if not token or not secret:
        raise HTTPException(status_code=404, detail="Not found")  # feature is off
    given = request.headers.get("x-telegram-bot-api-secret-token") or ""
    if not hmac.compare_digest(given.encode(), secret.encode()):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        update = await request.json()
    except Exception:  # noqa: BLE001
        return {"ok": True}
    msg = (update.get("message") or update.get("edited_message") or {}) if isinstance(update, dict) else {}
    chat = msg.get("chat") or {}
    chat_id, text = chat.get("id"), str(msg.get("text") or "").strip()[:200]
    if not isinstance(chat_id, int) or not text:
        return {"ok": True}
    if rate_limited(f"tg:{chat_id}", limit=TG_RATE_PER_MIN):
        return {"ok": True}
    client = getattr(request.app.state, "client", None)
    if client is not None:
        schedule(_tg_handle(client, token, chat_id, text, chat.get("type") == "private"))
    return {"ok": True}


print(f"[part27] v{VERSION} Telegram bot: {'ON' if all(_tg_cfg()) else 'off (needs TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET)'}")

# --- part28 ---
# ---------- part28: v2.15.0 - watchlist with signed webhooks (OFF by default; needs an API key) ----------
# Loads before part7. Set WATCH_ENABLED=true to switch it on. Each watched token is re-checked about every WATCH_POLL_S seconds
# by the resolver loop that already runs (no extra task, no lifespan change). A webhook is called only when something that
# matters changed. Webhook URLs are checked (https, public address) before use because the server makes the request.
import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import urllib.parse

VERSION = "2.15.0"
app.version = VERSION
app.openapi_schema = None

WATCH_ENABLED = (os.getenv("WATCH_ENABLED") or "false").lower() in ("1", "true", "yes")
WATCH_MAX_PER_KEY = max(1, int(os.getenv("WATCH_MAX_PER_KEY") or "10"))
WATCH_GLOBAL_MAX = max(1, int(os.getenv("WATCH_GLOBAL_MAX") or "20"))   # protects the shared upstream and Redis budget
WATCH_POLL_S = max(300, int(os.getenv("WATCH_POLL_S") or "900"))
WATCH_BATCH = 8                 # tokens re-checked per resolver cycle
WATCH_COOLDOWN_S = 600          # minimum gap between two notifications of the same token (a worse verdict skips it)
WATCH_RISK_DELTA = 15           # risk score move (vs the last notification) that counts as a change
WATCH_MAX_FAILS = 5             # failed deliveries in a row before the watch is paused
WATCH_TTL_S = 30 * 86400        # a watch expires after 30 days unless renewed with PATCH
_WATCH_RANK = {"ok": 0, "caution": 1, "avoid": 2}
_BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home", ".corp", ".intranet")


# ---------- webhook URL safety (the server makes this request, so it must not reach private networks) ----------
def _ip_is_public(text: str) -> bool:
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global


async def _resolve_host(host: str) -> list:
    infos = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM), 4.0)
    return [i[4][0] for i in infos]


async def _webhook_problem(url: str) -> Optional[str]:
    """None if the URL is fine, otherwise a short reason."""
    if not url or len(url) > 300:
        return "webhook URL is empty or too long"
    try:
        parts = urllib.parse.urlsplit(url)
        port = parts.port
    except ValueError:
        return "webhook URL is not valid"
    if parts.scheme != "https":
        return "webhook must use https"
    if parts.username or parts.password:
        return "do not put credentials in the webhook URL"
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or host == "localhost" or host.endswith(_BLOCKED_SUFFIXES):
        return "this host is not allowed"
    if port not in (None, 443):
        return "only port 443 is allowed"
    try:
        ipaddress.ip_address(host)
        return None if _ip_is_public(host) else "this address is not allowed"
    except ValueError:
        pass
    try:
        addrs = await _resolve_host(host)
    except Exception:  # noqa: BLE001
        return "could not resolve the webhook host"
    if not addrs or not all(_ip_is_public(a) for a in addrs):
        return "this host resolves to an address that is not allowed"
    return None


async def _deliver(client: httpx.AsyncClient, url: str, secret: str, event: str, payload: dict) -> tuple:
    problem = await _webhook_problem(url)  # checked again at delivery time, DNS can change
    if problem:
        return False, problem
    body = json.dumps(dict(payload, event=event, version=VERSION), sort_keys=True, separators=(",", ":")).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    try:
        resp = await client.post(url, content=body, timeout=8.0, follow_redirects=False, headers={
            "Content-Type": "application/json", "User-Agent": f"TVibex402-Watch/{VERSION}",
            "X-TVibe-Event": event, "X-TVibe-Signature": f"sha256={sig}"})
    except Exception as exc:  # noqa: BLE001
        return False, f"request failed ({type(exc).__name__})"
    return 200 <= resp.status_code < 300, f"HTTP {resp.status_code}"


# ---------- what counts as a change ----------
def _watch_decide(ref: dict, cur: dict, last_notified: int, now: int) -> Optional[str]:
    """Reason to notify, or None. `ref` is what the last notification (or the start) said."""
    ref_v, cur_v = ref.get("verdict"), cur.get("verdict")
    worse = _WATCH_RANK.get(cur_v, 0) > _WATCH_RANK.get(ref_v, 0)
    if cur_v != ref_v:
        reason = "verdict_changed"
    elif set(cur.get("blockers") or []) - set(ref.get("blockers") or []):
        reason = "new_blocker"
    elif abs(float(cur.get("risk") or 0) - float(ref.get("risk") or 0)) >= WATCH_RISK_DELTA:
        reason = "risk_moved"
    else:
        return None
    if not worse and now - last_notified < WATCH_COOLDOWN_S:
        return None
    return reason


def _watch_view(sig: dict) -> dict:
    dec = sig.get("decision") or {}
    return {"verdict": sig.get("verdict"), "risk": float(sig.get("risk_score") or 0),
            "blockers": [str(x)[:120] for x in (dec.get("blockers") or [])][:10]}


# ---------- storage layout ----------
def _w_owner(ident: str) -> str:
    return hashlib.sha256(ident.encode()).hexdigest()[:16]  # never put key material in Redis key names


def _w_keys(owner: str, mint: str) -> tuple:
    return f"watch:{owner}:{mint}", f"watch:idx:{owner}", f"{owner}|{mint}"  # hash, per-owner set, queue/all member


def _w_guard(request: Request) -> str:
    if not WATCH_ENABLED:
        raise HTTPException(status_code=404, detail="Watchlist is not enabled on this server")
    ident = client_ip(request)
    if not str(ident).startswith("key:"):
        raise HTTPException(status_code=401, detail="Watchlist needs an API key (x-api-key header)")
    wait = rate_limited(ident, cost=2)
    if wait:
        raise HTTPException(status_code=429, detail="rate limited", headers={"Retry-After": str(wait)})
    return _w_owner(ident)


async def _w_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Send a JSON object")
    return body


def _w_mint(mint: str) -> str:
    mint = (mint or "").strip()
    if not MINT_RE.match(mint):
        raise HTTPException(status_code=400, detail="Invalid Solana token address")
    return mint


def _w_label(text: Any) -> str:
    return re.sub(r"[^\w .\-]", "", str(text or ""))[:40].strip()


@app.post("/watch", tags=["watchlist"], summary="Watch a token; optional signed webhook when it changes")
async def watch_add(request: Request):
    owner = _w_guard(request)
    body = await _w_body(request)
    mint = _w_mint(str(body.get("mint") or ""))
    webhook = str(body.get("webhook") or "").strip()
    if webhook:
        problem = await _webhook_problem(webhook)
        if problem:
            raise HTTPException(status_code=400, detail=problem)
    client = request.app.state.client
    hkey, idx, member = _w_keys(owner, mint)
    got = await redis_pipe(client, [["SCARD", idx], ["SCARD", "watch:all"], ["EXISTS", hkey]])
    if not got:
        raise HTTPException(status_code=503, detail="The store is not available right now")
    count, total, exists = int(got[0] or 0), int(got[1] or 0), int(got[2] or 0)
    if exists:
        raise HTTPException(status_code=409, detail="Already watching this token (use PATCH to change it)")
    if count >= WATCH_MAX_PER_KEY:
        raise HTTPException(status_code=429, detail=f"Watchlist full for this key (max {WATCH_MAX_PER_KEY})")
    if total >= WATCH_GLOBAL_MAX:
        raise HTTPException(status_code=503, detail="The server watchlist is full right now")
    try:
        sig, _status = await asyncio.wait_for(build_signal(client, mint, True), 25.0)
    except HTTPException as exc:
        raise HTTPException(status_code=400, detail=str(exc.detail)[:120])
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Could not read this token right now")
    now, view = int(time.time()), _watch_view(sig)
    secret = secrets.token_hex(16) if webhook else ""
    await redis_pipe(client, [
        ["HSET", hkey, "mint", mint, "label", _w_label(body.get("label")) or str(sig.get("token") or mint[:8])[:40],
         "webhook", webhook, "secret", secret, "paused", "0", "fails", "0", "created", now, "expires", now + WATCH_TTL_S,
         "last_check", now, "last_verdict", view["verdict"] or "", "last_risk", view["risk"], "last_notified", 0,
         "last_error", "", "ref_verdict", view["verdict"] or "", "ref_risk", view["risk"],
         "ref_blockers", json.dumps(view["blockers"])],
        ["EXPIRE", hkey, WATCH_TTL_S], ["SADD", idx, mint], ["SADD", "watch:all", member],
        ["ZADD", "watch:q", now + WATCH_POLL_S, member]])
    out = {"status": "watching", "mint": mint, "verdict": view["verdict"], "risk_score": view["risk"],
           "check_every_s": WATCH_POLL_S, "expires_in_days": WATCH_TTL_S // 86400}
    if webhook:
        out["webhook_secret"] = secret
        out["note"] = "Keep this secret: it is shown once. Verify X-TVibe-Signature = sha256 HMAC of the raw body."
    return JSONResponse(content=out, headers={"Cache-Control": "no-store"})


@app.get("/watch", tags=["watchlist"], summary="Your watched tokens and their last known state")
async def watch_list(request: Request):
    owner = _w_guard(request)
    client = request.app.state.client
    _h, idx, _m = _w_keys(owner, "x")
    got = await redis_pipe(client, [["SMEMBERS", idx]])
    mints = [m for m in ((got or [[]])[0] or []) if MINT_RE.match(str(m))]
    hashes = await redis_pipe(client, [["HGETALL", _w_keys(owner, m)[0]] for m in mints]) if mints else []
    items = []
    for mint, h in zip(mints, hashes or []):
        d = to_dict(h)
        if not d.get("mint"):
            continue
        host = urllib.parse.urlsplit(d.get("webhook") or "").hostname if d.get("webhook") else None
        items.append({"mint": mint, "label": d.get("label"), "paused": d.get("paused") == "1", "webhook_host": host,
                      "last_verdict": d.get("last_verdict"), "last_risk": float(d.get("last_risk") or 0),
                      "last_check": int(d.get("last_check") or 0), "last_notified": int(d.get("last_notified") or 0),
                      "failed_deliveries": int(d.get("fails") or 0), "last_error": d.get("last_error") or None,
                      "expires": int(d.get("expires") or 0)})
    return JSONResponse(content={"count": len(items), "limit": WATCH_MAX_PER_KEY,
                                 "items": sorted(items, key=lambda x: x["mint"])}, headers={"Cache-Control": "no-store"})


@app.delete("/watch/{mint}", tags=["watchlist"], summary="Stop watching a token")
async def watch_remove(mint: str, request: Request):
    owner = _w_guard(request)
    hkey, idx, member = _w_keys(owner, _w_mint(mint))
    await redis_pipe(request.app.state.client, [["DEL", hkey], ["SREM", idx, mint], ["SREM", "watch:all", member],
                                                ["ZREM", "watch:q", member]])
    return {"status": "removed", "mint": mint}


@app.patch("/watch/{mint}", tags=["watchlist"], summary="Change webhook, label or pause; any PATCH also renews the 30 days")
async def watch_update(mint: str, request: Request):
    owner = _w_guard(request)
    body = await _w_body(request)
    mint = _w_mint(mint)
    client = request.app.state.client
    hkey, _i, _m = _w_keys(owner, mint)
    got = await redis_pipe(client, [["EXISTS", hkey]])
    if not got or not int(got[0] or 0):
        raise HTTPException(status_code=404, detail="Not in your watchlist")
    sets: list = ["expires", int(time.time()) + WATCH_TTL_S]
    out: Dict[str, Any] = {"status": "updated", "mint": mint}
    if "webhook" in body:
        url = str(body.get("webhook") or "").strip()
        if url:
            problem = await _webhook_problem(url)
            if problem:
                raise HTTPException(status_code=400, detail=problem)
            secret = secrets.token_hex(16)
            sets += ["webhook", url, "secret", secret, "fails", "0", "last_error", ""]
            out["webhook_secret"] = secret
        else:
            sets += ["webhook", "", "secret", ""]
    if "label" in body:
        sets += ["label", _w_label(body.get("label"))]
    if "paused" in body:
        sets += ["paused", "1" if body.get("paused") else "0"]
        if not body.get("paused"):
            sets += ["fails", "0", "last_error", ""]
    await redis_pipe(client, [["HSET", hkey, *sets], ["EXPIRE", hkey, WATCH_TTL_S]])
    return JSONResponse(content=out, headers={"Cache-Control": "no-store"})


@app.post("/watch/{mint}/test", tags=["watchlist"], summary="Send a test event to the webhook")
async def watch_test(mint: str, request: Request):
    owner = _w_guard(request)
    mint = _w_mint(mint)
    client = request.app.state.client
    got = await redis_pipe(client, [["HGETALL", _w_keys(owner, mint)[0]]])
    d = to_dict((got or [None])[0])
    if not d.get("mint"):
        raise HTTPException(status_code=404, detail="Not in your watchlist")
    if not d.get("webhook"):
        raise HTTPException(status_code=400, detail="This watch has no webhook")
    ok, info = await _deliver(client, d["webhook"], d.get("secret") or "", "test", {"mint": mint, "message": "test event"})
    return {"delivered": ok, "detail": info}


# ---------- the worker: a tick inside the resolver cycle that already exists ----------
async def _watch_tick(client: httpx.AsyncClient) -> int:
    if not WATCH_ENABLED:
        return 0
    now = int(time.time())
    got = await redis_pipe(client, [["ZRANGEBYSCORE", "watch:q", "-inf", now, "LIMIT", 0, WATCH_BATCH]])
    members = (got or [[]])[0] or []
    done = 0
    for member in members:
        owner, _, mint = str(member).partition("|")
        hkey, idx, _m = _w_keys(owner, mint)
        try:
            h = await redis_pipe(client, [["HGETALL", hkey]])
            d = to_dict((h or [None])[0])
            if not d.get("mint") or int(d.get("expires") or 0) < now:  # gone or expired: forget it everywhere
                await redis_pipe(client, [["DEL", hkey], ["SREM", idx, mint], ["SREM", "watch:all", member], ["ZREM", "watch:q", member]])
                continue
            if d.get("paused") == "1":
                await redis_pipe(client, [["ZADD", "watch:q", now + WATCH_POLL_S * 3, member]])
                continue
            try:
                sig, _status = await asyncio.wait_for(build_signal(client, mint, True), 20.0)
            except Exception:  # noqa: BLE001
                await redis_pipe(client, [["ZADD", "watch:q", now + WATCH_POLL_S, member]])
                continue
            cur = _watch_view(sig)
            ref = {"verdict": d.get("ref_verdict"), "risk": float(d.get("ref_risk") or 0),
                   "blockers": json.loads(d.get("ref_blockers") or "[]")}
            reason = _watch_decide(ref, cur, int(d.get("last_notified") or 0), now) if d.get("webhook") else None
            sets: list = ["last_check", now, "last_verdict", cur["verdict"] or "", "last_risk", cur["risk"]]
            if reason:
                dec = sig.get("decision") or {}
                ok, info = await _deliver(client, d["webhook"], d.get("secret") or "", "signal_changed", {
                    "mint": mint, "label": d.get("label"), "reason": reason, "timestamp": now,
                    "previous": {"verdict": ref["verdict"], "risk_score": ref["risk"]},
                    "current": {"verdict": cur["verdict"], "risk_score": cur["risk"], "summary": str(sig.get("summary") or "")[:300],
                                "blockers": cur["blockers"], "cautions": [str(x)[:120] for x in (dec.get("cautions") or [])][:10]},
                    "holder_quality": (sig.get("holder_quality") or {}).get("score")})
                if ok:
                    sets += ["fails", "0", "last_error", "", "last_notified", now, "ref_verdict", cur["verdict"] or "",
                             "ref_risk", cur["risk"], "ref_blockers", json.dumps(cur["blockers"])]
                else:
                    fails = int(d.get("fails") or 0) + 1
                    sets += ["fails", str(fails), "last_error", info[:120]]
                    if fails >= WATCH_MAX_FAILS:
                        sets += ["paused", "1"]  # stop hammering a dead endpoint; PATCH {"paused": false} resumes
            await redis_pipe(client, [["HSET", hkey, *sets], ["ZADD", "watch:q", now + WATCH_POLL_S, member]])
            done += 1
        except Exception:  # noqa: BLE001
            try:
                await redis_pipe(client, [["ZADD", "watch:q", now + WATCH_POLL_S * 2, member]])  # one broken item never blocks the rest
            except Exception:  # noqa: BLE001
                pass
    return done


_resolve_due_v24 = resolve_due


async def resolve_due(client: httpx.AsyncClient) -> int:
    n = await _resolve_due_v24(client)
    try:
        await _watch_tick(client)  # not added to n: n decides how soon the resolver runs again
    except Exception:  # noqa: BLE001
        pass
    return n


print(f"[part28] v{VERSION} watchlist: {'ON' if WATCH_ENABLED else 'off (set WATCH_ENABLED=true)'}, "
      f"per key {WATCH_MAX_PER_KEY}, total {WATCH_GLOBAL_MAX}, every {WATCH_POLL_S}s")

# --- part29 ---
# ---------- part29: v2.16.0 - /me: your own rate limit and how much of it is used ----------
# Loads before part7. Reads the in-memory limiter that already exists (no Redis, no new middleware, no extra cost per request).
# Without a key it only says "free"; it never shows the IP. /whoami is the place for checking how the server sees an IP.
VERSION = "2.16.0"
app.version = VERSION
app.openapi_schema = None


@app.get("/me", tags=["account"], summary="Your rate limit and how much of it is used in the current minute")
async def me(request: Request):
    ident = str(client_ip(request))  # "key:<label>" for a valid X-API-Key, otherwise the client IP
    keyed = ident.startswith("key:")
    limit = KEY_RATE_LIMIT if keyed else RATE_LIMIT
    now = time.time()
    with _rl_lock:
        dq = _hits.get(ident)
        used = sum(1 for t in dq if now - t <= RATE_WINDOW) if dq else 0
    watch = None
    if "WATCH_ENABLED" in globals():  # only present when the watchlist part is installed
        watch = {"enabled": bool(WATCH_ENABLED), "max_per_key": WATCH_MAX_PER_KEY if WATCH_ENABLED else None}
    return JSONResponse(content={
        "plan": "key" if keyed else "free",
        "key_label": ident[4:] if keyed else None,
        "limit_per_min": limit, "used_in_window": used, "remaining": max(0, limit - used), "window_s": RATE_WINDOW,
        "batch_max": MAX_BATCH, "watchlist": watch,
        "note": ("Send your key in the X-API-Key header to see its limit. Keys are issued by hand during the beta, see /pricing."
                 if not keyed else "Limits are per key. Calls to this endpoint are not counted."),
    }, headers={"Cache-Control": "no-store"})


print(f"[part29] v{VERSION} /me ready")

# --- part30 ---
# ---------- part30: v2.17.0 - /start onboarding page and llms.txt additions (numbers come from the live settings) ----------
# Loads before part7. Replaces nothing: /pricing, /llms.txt and the MCP tools stay as they are. This part only adds a short
# onboarding page and appends accurate sections to llms.txt. A link is shown only when its page exists on this server.
import html as _html

VERSION = "2.17.0"
app.version = VERSION
app.openapi_schema = None


def _has_route(path: str) -> bool:
    return any(getattr(r, "path", None) == path for r in app.routes)


def render_start(base: str) -> str:
    e = lambda s: _html.escape(str(s), quote=True)  # noqa: E731
    watch_on = "WATCH_ENABLED" in globals() and bool(WATCH_ENABLED)
    play_link = ' at <a href="/play">/play</a>' if _has_route("/play") else ""
    me_link = ' <a href="/me">/me</a> shows your current limit and use.' if _has_route("/me") else ""
    curl = "curl &quot;" + e(base) + "/signal?mint=So11111111111111111111111111111111111111112&quot;"
    steps = [
        ("Try it", "<p>Check a token in the browser" + play_link + ", or call the API directly:</p><pre>" + curl + "</pre>"
                   "<p class=\"muted\">The free tier needs no signup: " + str(RATE_LIMIT) + " requests per minute per IP, batches of up to "
                   + str(MAX_BATCH) + " tokens.</p>"),
        ("Use it from an AI agent", "<p>Add this as a remote MCP server (Streamable HTTP):</p><pre>" + e(base) + "/mcp</pre>"
                                    "<p>Machine-readable docs: <a href=\"/llms.txt\">/llms.txt</a> and <a href=\"/docs\">/docs</a>.</p>"),
        ("Higher limits", "<p>An <code>X-API-Key</code> header raises the limit to " + str(KEY_RATE_LIMIT) + " requests per minute. "
                          "Keys are issued by hand during the beta: see <a href=\"/pricing\">/pricing</a>." + me_link + "</p>"),
    ]
    if watch_on:
        steps.append(("Get notified", "<p>With a key you can watch up to " + str(WATCH_MAX_PER_KEY) + " tokens: <code>POST /watch</code> with "
                                      "<code>{&quot;mint&quot;: &quot;...&quot;, &quot;webhook&quot;: &quot;https://...&quot;}</code>. The webhook is called when the verdict "
                                      "changes, a new blocker appears or the risk score moves by " + str(WATCH_RISK_DELTA) + "+, checked about every "
                                      + str(max(1, WATCH_POLL_S // 60)) + " minutes, and each call is signed (<code>X-TVibe-Signature</code>).</p>"))
    check_links = " - ".join('<a href="' + p + '">' + p + "</a>" for p in ("/accuracy", "/methodology", "/ledger", "/status") if _has_route(p))
    steps.append(("Check our work", "<p>" + check_links + "</p><p class=\"muted\">Verdicts are heuristics, not a security audit and not "
                  "financial advice. The free host can sleep, so retry after a 503.</p>"))
    body = "".join(f'<div class="step"><h2><span class="n">{i}</span>{t}</h2>{c}</div>' for i, (t, c) in enumerate(steps, 1))
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Get started - TVibex402</title><style>
:root{{--bg:#070b14;--card:#111827;--border:#1f2937;--text:#f3f4f6;--muted:#9ca3af;--accent:#6366f1}}
body{{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);line-height:1.55;margin:0;padding:1rem}}
.wrap{{max-width:760px;margin:0 auto}} h1{{font-size:1.8rem;margin:.5rem 0}} .muted{{color:var(--muted);font-size:.9rem}}
.step{{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:1.2rem;margin:1rem 0}}
h2{{font-size:1.05rem;margin:0 0 .6rem;display:flex;align-items:center}}
.n{{display:inline-flex;align-items:center;justify-content:center;width:26px;height:26px;background:var(--accent);border-radius:50%;margin-right:.6rem;font-size:.85rem}}
pre,code{{background:#0b1220;border-radius:6px;font-size:.85rem}} pre{{padding:.8rem;overflow-x:auto;border:1px solid var(--border)}} code{{padding:.1rem .35rem}}
a{{color:#60a5fa}}</style></head><body><div class="wrap"><h1>Get started with TVibex402</h1>
<p class="muted">A free Solana token signal API for people, bots and AI agents.</p>{body}</div></body></html>"""


@app.get("/start", response_class=HTMLResponse, include_in_schema=False)
async def onboarding(request: Request):
    base = os.getenv("PUBLIC_URL") or ("https://" + request.url.netloc)
    return HTMLResponse(render_start(base.rstrip("/")), headers={"Cache-Control": "public, max-age=300"})


if "GET /play" not in LLMS_TXT:
    LLMS_TXT = LLMS_TXT + """
## Try it, check it, see your limit
GET /play is a web page to check a token by hand (/play?mint=ADDRESS pre-fills it). GET /status shows live source health.
GET /me shows your own rate limit and how much of the current minute is used (send X-API-Key to see the key limit).
GET /start is a short onboarding page.
"""
if "WATCH_ENABLED" in globals() and WATCH_ENABLED and "POST /watch" not in LLMS_TXT:
    LLMS_TXT = LLMS_TXT + f"""
## Watchlist and webhooks (needs an X-API-Key)
POST /watch {{mint, webhook?, label?}} starts watching a token; GET /watch lists yours; PATCH /watch/MINT changes webhook, label or pause;
DELETE /watch/MINT stops it; POST /watch/MINT/test sends a test event. Up to {WATCH_MAX_PER_KEY} tokens per key.
The webhook must be https on a public address. It is called when the verdict changes, a new blocker appears or the risk score moves
by {WATCH_RISK_DELTA}+ since the last notification (at most one call per {WATCH_COOLDOWN_S // 60} minutes unless the verdict gets worse).
Each call is signed: X-TVibe-Signature is sha256= plus the HMAC-SHA256 of the raw body with the secret shown once when you add the webhook.
Tokens are re-checked about every {max(1, WATCH_POLL_S // 60)} minutes, so this is not a real-time alert.
"""

if '<a href="/accuracy">/accuracy</a>' in HOME_HTML and 'href="/play"' not in HOME_HTML and _has_route("/play"):
    HOME_HTML = HOME_HTML.replace('<a href="/accuracy">/accuracy</a>', '<a href="/accuracy">/accuracy</a> &bull; <a href="/play">/play</a>', 1)

print(f"[part30] v{VERSION} /start onboarding page and llms.txt additions ready")

# --- part32 ---
# ---------- part32: v2.19.0 - /dataset.csv: export of the labelled dataset collected by part24 (admin only) ----------
# Loads before part7. Each judged verdict leaves one row: the numbers the verdict was based on, our labels, and what happened
# after 1h, 6h and 24h. No mint and no token name. Needs ADMIN_SECRET; without it the routes answer 404 as if they did not exist.
import csv
import hmac
import io
import json

VERSION = "2.19.0"
app.version = VERSION
app.openapi_schema = None

_DS_FIXED = ["ts", "src", "verdict", "risk", "flags", "shadow", "ret_h1", "ret_h6", "ret_24h", "liq_ratio", "bad"]


def _ds_allowed(request: Request) -> bool:
    secret = (os.getenv("ADMIN_SECRET") or "").strip()
    if not secret:
        return False
    given = request.headers.get("x-admin-key") or request.query_params.get("key") or ""  # the header is safer; ?key= is for a phone browser
    return hmac.compare_digest(given.encode(), secret.encode())


def _ds_guard(request: Request) -> None:
    if not _ds_allowed(request):
        raise HTTPException(status_code=404, detail="Not found")  # same answer for "off" and "wrong key"
    wait = rate_limited(client_ip(request), cost=5)
    if wait:
        raise HTTPException(status_code=429, detail="rate limited", headers={"Retry-After": str(wait)})


async def _ds_rows(request: Request, limit: int) -> list:
    got = await redis_pipe(request.app.state.client, [["LRANGE", "ds:rows", 0, limit - 1]])
    rows = []
    for raw in (got or [[]])[0] or []:
        try:
            row = json.loads(raw)
            if isinstance(row, dict):
                rows.append(row)
        except ValueError:
            continue
    return rows


def _ds_limit(request: Request) -> int:
    try:
        return max(1, min(2000, int(request.query_params.get("limit") or 500)))
    except ValueError:
        return 500


def _ds_cell(v: Any) -> Any:
    if isinstance(v, str) and v[:1] in ("=", "+", "@", "\t", "\r"):
        return "'" + v  # a spreadsheet must never treat our text as a formula
    return "" if v is None else v


def rows_to_csv(rows: list) -> str:
    feats = sorted({k for r in rows for k in (r.get("feat") or {})})
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(_DS_FIXED + [f"f.{k}" for k in feats])
    for r in rows:
        feat = r.get("feat") or {}
        fixed = [_ds_cell("|".join(r.get("flags") or [])) if k == "flags" else _ds_cell(r.get(k)) for k in _DS_FIXED]
        w.writerow(fixed + [_ds_cell(feat.get(k)) for k in feats])
    return out.getvalue()


@app.get("/dataset", include_in_schema=False)
async def dataset_json(request: Request):
    _ds_guard(request)
    rows = await _ds_rows(request, _ds_limit(request))
    return JSONResponse(content={"count": len(rows), "rows": rows}, headers={"Cache-Control": "no-store"})


@app.get("/dataset.csv", include_in_schema=False)
async def dataset_csv(request: Request):
    _ds_guard(request)
    rows = await _ds_rows(request, _ds_limit(request))
    return PlainTextResponse(rows_to_csv(rows), media_type="text/csv; charset=utf-8",
                             headers={"Cache-Control": "no-store", "Content-Disposition": 'attachment; filename="tvibe-dataset.csv"'})


print(f"[part32] v{VERSION} /dataset.csv ready ({'admin key set' if os.getenv('ADMIN_SECRET') else 'off: set ADMIN_SECRET'})")

# --- part33 ---
# ---------- part33: v2.20.0 - /explain: why this verdict, in plain words (English or Vietnamese) ----------
# Loads before part7. Built on the live engine: the English reasons come from REASONS, the points from ACTIVE_WEIGHTS (so they follow
# the auto-tuning), which flags force the verdict is read from the decision object the engine already produced, and the score
# rule is the engine's own: score = min(100, sum of the points of the flags that are scored). Nothing here changes /signal.
VERSION = "2.20.0"
app.version = VERSION
app.openapi_schema = None

_AVOID_AT, _CAUTION_AT = 50, 25   # the same lines add_verdict uses
_POSITIVE_FLAGS = {"holders_stable", "whale_accumulating", "dip_absorbed"}
_ROLE_ORDER = {"blocker": 0, "caution": 1, "scores": 2, "info": 3, "positive": 4}
_EN_EXTRA = {
    "very_new_pair": "Pair is very young, so there is little history",
    "new_pair": "Pair is young",
    "high_turnover": "Trading volume is high compared with liquidity",
    "heavy_selling": "Recent trades lean heavily to selling",
    "extreme_volume_spike": "Volume jumped abnormally in the last minutes",
    "transfer_fee_set": "The token has a transfer fee configured (a small one)",
}
_VI = {
    "mint_authority_active": "Quyền đúc (mint) còn hiệu lực: có thể tạo thêm token, làm loãng giá trị",
    "freeze_authority_active": "Quyền đóng băng còn hiệu lực: có thể khóa ví của người nắm giữ",
    "risky_token_extension": "Tiện ích Token-2022 có thể hạn chế hoặc đánh thuế khi chuyển token",
    "lp_not_locked": "Thanh khoản chưa bị khóa hay đốt: team có thể rút ra",
    "dump_risk": "Giá đang giảm rất nhanh",
    "extreme_holder_concentration": "10 ví lớn nhất nắm từ 80% nguồn cung trở lên",
    "very_low_liquidity": "Thanh khoản dưới 20 nghìn USD",
    "low_liquidity": "Thanh khoản dưới 50 nghìn USD",
    "high_holder_concentration": "10 ví lớn nhất nắm từ 50% nguồn cung trở lên",
    "dominant_holder": "Một ví nắm từ 20% nguồn cung trở lên",
    "lp_partially_locked": "Thanh khoản chỉ được khóa hoặc đốt một phần",
    "brand_new_pair": "Cặp giao dịch mới tạo chưa tới 1 giờ",
    "very_new_pair": "Cặp giao dịch còn rất mới nên ít lịch sử",
    "new_pair": "Cặp giao dịch còn mới",
    "extreme_turnover": "Khối lượng giao dịch cực lớn so với thanh khoản (nguy cơ rửa lệnh)",
    "high_turnover": "Khối lượng giao dịch cao so với thanh khoản",
    "heavy_selling": "Các giao dịch gần đây nghiêng mạnh về phía bán",
    "extreme_volume_spike": "Khối lượng tăng đột biến bất thường trong vài phút gần nhất",
    "lp_unverified": "Không xác minh được việc khóa hoặc đốt thanh khoản (pool PumpSwap)",
    "permanent_delegate_active": "Một địa chỉ ủy quyền vĩnh viễn có thể chuyển hoặc đốt token của bất kỳ ai",
    "transfer_fee_extreme": "Phí chuyển token từ 25% trở lên ở mỗi lần chuyển (như thuế khi bán)",
    "default_account_frozen": "Tài khoản token mới bị đóng băng mặc định: người nắm giữ không chuyển được cho đến khi bên phát hành mở",
    "transfer_fee_high": "Phí chuyển token từ 5% trở lên ở mỗi lần chuyển",
    "transfer_hook_active": "Một chương trình hook chạy ở mỗi lần chuyển và có thể chặn giao dịch",
    "transfer_fee_set": "Token có cấu hình phí chuyển (mức nhỏ)",
    "no_sell_route": "Không tìm thấy đường bán trên Jupiter khi kiểm tra cách đây vài phút",
    "high_exit_cost": "Bán ra sẽ mất một phần lớn giá trị vì phí và trượt giá (theo kiểm tra gần đây)",
    "holders_churning": "Các ví lớn nhất thay đổi liên tục",
    "whale_dumping": "Các ví lớn nhất có dấu hiệu giảm nắm giữ",
    "weak_absorption": "Giá giảm nhưng lực mua đỡ yếu",
    "holders_stable": "Các ví lớn nhìn chung không đổi (độ tin cậy cao hơn)",
    "whale_accumulating": "Các ví lớn nhất có dấu hiệu mua thêm",
    "dip_absorbed": "Giá giảm nhưng có lực mua đỡ tốt",
    "late_entry_risk": "Tăng trên 100% trong 1 giờ qua trên cặp dưới 1 ngày tuổi: vào muộn khi đang bơm",
    "one_sided_flow": "Hơn 90% giao dịch trong 5 phút gần nhất nằm về một phía, với mức hoạt động cao",
    "no_recent_trades": "Không có giao dịch nào trong 5 phút gần nhất: giá và báo giá bán kém tin cậy hơn",
}
_T = {
    "en": {
        "verdict": {"ok": "OK", "caution": "CAUTION", "avoid": "AVOID"},
        "blocked": "A blocking red flag forces AVOID whatever the score: ",
        "avoid_score": "The risk score {s} is at or above the avoid line ({a}).",
        "caution_flags": "These flags keep the verdict at CAUTION: ",
        "caution_score": "The risk score {s} is at or above the caution line ({c}).",
        "ok": "No blocking or caution flags, and the risk score is below the caution line ({c}).",
        "sum": "The score is the sum of the points of the scored flags, capped at 100: {t} points, shown as {s}.",
        "sum_capped": "The score is the sum of the points of the scored flags, capped at 100: {t} points, shown as 100.",
        "stay_avoid": "It stays AVOID while any of these is present: ",
        "to_leave_avoid": "To leave AVOID by score it must fall below {a}, which is {n} points less. The biggest contributors: ",
        "stay_caution": "It stays CAUTION while any of these flags is present: ",
        "to_leave_caution": "To reach OK the score must fall below {c}, which is {n} points less. The biggest contributors: ",
        "headroom": "{n} more points of risk would make it CAUTION.",
        "none": "no major red flags found",
        "head": "{v} (risk {s}/100). {r}.",
        "points": "pts",
        "disc": "Heuristic output, not financial advice.",
        "lang_note": None,
    },
    "vi": {
        "verdict": {"ok": "OK", "caution": "THẬN TRỌNG", "avoid": "TRÁNH"},
        "blocked": "Một cờ đỏ chặn buộc kết quả là TRÁNH dù điểm thế nào: ",
        "avoid_score": "Điểm rủi ro {s} bằng hoặc vượt ngưỡng tránh ({a}).",
        "caution_flags": "Các cờ này giữ kết quả ở mức THẬN TRỌNG: ",
        "caution_score": "Điểm rủi ro {s} bằng hoặc vượt ngưỡng thận trọng ({c}).",
        "ok": "Không có cờ chặn hay cờ thận trọng, và điểm rủi ro thấp hơn ngưỡng thận trọng ({c}).",
        "sum": "Điểm là tổng điểm của các cờ được tính, tối đa 100: {t} điểm, hiển thị là {s}.",
        "sum_capped": "Điểm là tổng điểm của các cờ được tính, tối đa 100: {t} điểm, hiển thị là 100.",
        "stay_avoid": "Vẫn là TRÁNH chừng nào còn bất kỳ cờ nào sau: ",
        "to_leave_avoid": "Để thoát mức TRÁNH theo điểm, điểm phải xuống dưới {a}, tức giảm {n} điểm. Đóng góp lớn nhất: ",
        "stay_caution": "Vẫn là THẬN TRỌNG chừng nào còn bất kỳ cờ nào sau: ",
        "to_leave_caution": "Để lên mức OK, điểm phải xuống dưới {c}, tức giảm {n} điểm. Đóng góp lớn nhất: ",
        "headroom": "Thêm {n} điểm rủi ro nữa sẽ chuyển thành THẬN TRỌNG.",
        "none": "không thấy cờ đỏ lớn",
        "head": "{v} (rủi ro {s}/100). {r}.",
        "points": "điểm",
        "disc": "Kết quả mang tính heuristic, không phải lời khuyên tài chính.",
        "lang_note": "Phần tích cực, cần lưu ý và chưa biết lấy từ engine nên vẫn bằng tiếng Anh.",
    },
}


def _en_text(flag: str) -> str:
    hyp = globals().get("HYPOTHESES") or {}
    return REASONS.get(flag) or hyp.get(flag) or _EN_EXTRA.get(flag) or flag.replace("_", " ")


def _flag_text(flag: str, lang: str) -> str:
    return (_VI.get(flag) if lang == "vi" else None) or _en_text(flag)


def build_explanation(sig: dict, lang: str = "en") -> dict:
    """Pure function: one signal in, one explanation out. Never invents a number: it reads what the engine produced."""
    lang = lang if lang in _T else "en"
    t = _T[lang]
    dec = sig.get("decision") or {}
    verdict = str(sig.get("verdict") or "unknown")
    score = int(sig.get("risk_score") or 0)
    not_scored = set(sig.get("flags_not_scored") or [])
    blockers, cautions = set(dec.get("blockers") or []), set(dec.get("cautions") or [])
    items = []
    for f in [x for x in (sig.get("flags") or []) if isinstance(x, str)]:
        counted = f not in not_scored
        pts = int(ACTIVE_WEIGHTS.get(f, 0)) if counted else 0
        en = _en_text(f)
        role = ("blocker" if en in blockers else "caution" if en in cautions else "positive" if f in _POSITIVE_FLAGS
                else "scores" if pts > 0 else "info")
        items.append({"flag": f, "role": role, "points": pts, "counted": counted, "text": _flag_text(f, lang)})
    items.sort(key=lambda i: (_ROLE_ORDER[i["role"]], -i["points"], i["flag"]))
    total = sum(i["points"] for i in items)
    hard = [i for i in items if i["role"] == "blocker"]
    soft = [i for i in items if i["role"] == "caution"]
    scored = [i for i in items if i["points"] > 0]
    top = ", ".join(f"{i['flag']} (+{i['points']})" for i in sorted(scored, key=lambda x: -x["points"])[:3])
    why, change = [], []
    if verdict == "avoid" and hard:
        why.append(t["blocked"] + "; ".join(i["text"] for i in hard) + ".")
        change.append(t["stay_avoid"] + ", ".join(i["flag"] for i in hard) + ".")
    elif verdict == "avoid":
        why.append(t["avoid_score"].format(s=score, a=_AVOID_AT))
        change.append(t["to_leave_avoid"].format(a=_AVOID_AT, n=score - _AVOID_AT + 1) + top + ".")
    elif verdict == "caution" and soft:
        why.append(t["caution_flags"] + "; ".join(i["text"] for i in soft) + ".")
        change.append(t["stay_caution"] + ", ".join(i["flag"] for i in soft) + ".")
    elif verdict == "caution":
        why.append(t["caution_score"].format(s=score, c=_CAUTION_AT))
        change.append(t["to_leave_caution"].format(c=_CAUTION_AT, n=score - _CAUTION_AT + 1) + top + ".")
    elif verdict == "ok":
        why.append(t["ok"].format(c=_CAUTION_AT))
        change.append(t["headroom"].format(n=max(0, _CAUTION_AT - score)))
    why.append((t["sum_capped"] if total > 100 else t["sum"]).format(t=total, s=score))
    main = (hard[0]["text"] if hard else soft[0]["text"] if soft else t["none"] if score < _CAUTION_AT else
            t["avoid_score" if verdict == "avoid" else "caution_score"].format(s=score, a=_AVOID_AT, c=_CAUTION_AT)).rstrip(".")
    return {
        "verdict": verdict, "risk_score": score, "scoring": sig.get("scoring"), "asset_class": dec.get("asset_class") or sig.get("asset_class"),
        "language": lang, "headline": t["head"].format(v=t["verdict"].get(verdict, verdict.upper()), s=score, r=main),
        "why": why, "flags": items, "points_total": total, "capped": total > 100, "what_would_change": change,
        "positives": list(dec.get("positives") or [])[:6], "unknowns": list(dec.get("unknowns") or [])[:6],
        "note": dec.get("note"), "language_note": t["lang_note"], "disclaimer": t["disc"],
    }


async def _explain(request: Request, mint: str, lang: str):
    wait = rate_limited(client_ip(request))
    if wait:
        raise HTTPException(status_code=429, detail="rate limited", headers={"Retry-After": str(wait)})
    mint = (mint or "").strip()
    if not MINT_RE.match(mint):
        raise HTTPException(status_code=400, detail="Invalid Solana token address")
    lang = (lang or "en").lower()[:4]
    sig, _status = await build_signal(request.app.state.client, mint, True)  # build_signal returns (result, cache status)
    if lang == "both":
        body = {"en": build_explanation(sig, "en"), "vi": build_explanation(sig, "vi")}
    else:
        body = build_explanation(sig, "vi" if lang.startswith("vi") else "en")
    return JSONResponse(content={"mint": mint, "token": sig.get("token"), "explanation": body, "generated_from": "live rules and weights"},
                        headers={"Cache-Control": "public, max-age=15"})


@app.get("/explain", tags=["signal"], summary="Why this verdict, in plain words (lang=en|vi|both)")
async def explain_query(request: Request, mint: str = "", lang: str = "en"):
    return await _explain(request, mint, lang)


@app.get("/explain/{mint}", tags=["signal"], include_in_schema=False)
async def explain_path(mint: str, request: Request, lang: str = "en"):
    return await _explain(request, mint, lang)


print(f"[part33] v{VERSION} /explain ready (lang=en|vi|both)")

# --- part31 ---
# ---------- part31: v2.18.0 - new landing page at / (the old home stays at /classic) ----------
# Loads before part7. Marketing copy that only says what the server can back up: the numbers (rate limit, batch size) come from
# the live settings, the proof strip and the example are fetched live from /stats and /signal and drawn with textContent,
# and a link is shown only if its page exists on this server.
VERSION = "2.18.1"
app.version = VERSION
app.openapi_schema = None

_CLASSIC_HOME_HTML = HOME_HTML


def _route_exists(path: str) -> bool:
    return any(getattr(r, "path", None) == path for r in app.routes)


def _links(items: list, tmpl: str) -> str:
    return "".join(tmpl.replace("%P%", p).replace("%L%", label) for p, label in items if _route_exists(p))


_LANDING_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVibex402 - Solana token signals for AI agents</title>
<meta name="description" content="A free Solana token API for AI agents and bots: a verdict, the reasons and the sell cost in one JSON response. No API key to start. Measured results are public.">
<meta property="og:type" content="website">
<meta property="og:title" content="TVibex402 - Solana token signals for AI agents">
<meta property="og:description" content="Verdict, reasons and sell cost for any Solana token in one request. Free to start, results measured in public.">
<meta name="twitter:card" content="summary">
<link rel="icon" href="/favicon.ico">
<style>
:root{--bg:#05080f;--card:#0f1420;--border:#1e2638;--text:#f1f5f9;--muted:#94a3b8;--accent:#6366f1;--green:#22c55e;--yellow:#eab308;--red:#ef4444;--grey:#64748b}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;background:var(--bg);color:var(--text);line-height:1.6}
.container{max-width:1040px;margin:0 auto;padding:0 1.25rem}
nav{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem;padding:1rem 0;border-bottom:1px solid var(--border)}
.logo{font-weight:800;font-size:1.2rem;letter-spacing:-.03em}.logo span{color:var(--accent)}
nav .links a{color:var(--muted);text-decoration:none;margin-right:1.1rem;font-size:.92rem}nav .links a:hover{color:var(--text)}
.hero{text-align:center;padding:3.5rem 0 2.5rem}
.hero h1{font-size:clamp(2.1rem,6vw,3.4rem);font-weight:800;letter-spacing:-.04em;line-height:1.15;margin-bottom:1rem}
.hl{background:linear-gradient(135deg,#818cf8,#c084fc);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.hero p{font-size:1.1rem;color:var(--muted);max-width:620px;margin:0 auto 1.75rem}
.cta{display:flex;gap:.8rem;justify-content:center;flex-wrap:wrap}
.btn{display:inline-block;padding:.8rem 1.5rem;border-radius:.7rem;font-weight:600;text-decoration:none;font-size:.98rem}
.btn-primary{background:var(--accent);color:#fff}.btn-outline{border:1px solid var(--border);color:var(--text)}
.btn:hover{filter:brightness(1.12)}
.try{display:flex;gap:.5rem;max-width:560px;margin:0 auto .6rem}
.try input{flex:1;min-width:0;background:var(--card);border:1px solid var(--border);border-radius:.7rem;padding:.8rem 1rem;color:var(--text);font-size:.95rem}
.try input:focus{outline:none;border-color:var(--accent)}
.try button{background:var(--accent);color:#fff;border:0;border-radius:.7rem;padding:0 1.3rem;font-weight:600;font-size:.95rem}
.tryhint{text-align:center;font-size:.85rem;margin-bottom:1.6rem}
#proof{display:none;text-align:center;margin:0 auto 2rem;max-width:720px;background:var(--card);border:1px solid var(--border);border-radius:.9rem;padding:.9rem 1.1rem;font-size:.95rem}
#proof .muted,.muted{color:var(--muted)}
.section{padding:2.5rem 0}
h2.t{text-align:center;font-size:1.7rem;font-weight:750;letter-spacing:-.03em;margin-bottom:.5rem}
.sub{text-align:center;color:var(--muted);max-width:560px;margin:0 auto 2rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:1rem}
.card{background:var(--card);border:1px solid var(--border);border-radius:1rem;padding:1.4rem}
.card h3{font-size:1.05rem;margin-bottom:.4rem}.card p{color:var(--muted);font-size:.93rem}
.badge{display:inline-block;padding:.2rem .7rem;border-radius:9999px;font-size:.78rem;font-weight:700;text-transform:uppercase}
.ok{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3)}
.caution{background:rgba(234,179,8,.15);color:var(--yellow);border:1px solid rgba(234,179,8,.3)}
.avoid{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3)}
.unknown{background:rgba(100,116,139,.2);color:var(--muted);border:1px solid var(--border)}
#example{min-height:6rem}
#example ul{margin:.4rem 0 .4rem 1.1rem;font-size:.92rem}
pre{background:#0a0e17;border:1px solid var(--border);border-radius:.8rem;padding:1rem;overflow-x:auto;font-size:.85rem;margin:.8rem 0}
.honest li{margin:.35rem 0 .35rem 1.1rem;color:var(--muted);font-size:.95rem}
.final{text-align:center;padding:3rem 0}
footer{border-top:1px solid var(--border);padding:2rem 0;text-align:center;color:var(--muted);font-size:.85rem}
footer a{color:#60a5fa;text-decoration:none;margin:0 .6rem}
a{color:#60a5fa}
</style>
</head>
<body>
<div class="container">
<nav><div class="logo">TVibe<span>x402</span></div><div class="links">%%NAV%%</div></nav>

<section class="hero">
<h1>Solana token signals<br><span class="hl">built for AI agents</span></h1>
<p>A verdict, the reasons and the cost of selling, for any Solana token, in one JSON request. Free to start, no API key, and the results are measured in public.</p>
<div class="cta">%%CTA%%</div>
</section>

%%TRY%%
<div id="proof"></div>

<section class="section">
<h2 class="t">What one call gives you</h2>
<p class="sub">Four data sources read for you, combined into one decision-ready answer.</p>
<div class="grid">
<div class="card"><h3>Verdict with reasons</h3><p>ok, caution or avoid, plus blockers, cautions, positives and what is still unknown.</p></div>
%%EXPLAINCARD%%<div class="card"><h3>Holder quality</h3><p>A 0-100 score and flags such as whale accumulating, whale dumping, holders churning and dip absorbed.</p></div>
<div class="card"><h3>Security checks</h3><p>Mint and freeze authority, LP lock status, Token-2022 risks and holder concentration.</p></div>
<div class="card"><h3>Sell cost</h3><p>Jupiter quotes for several sizes, so an agent can see what leaving would cost. A quote is not proof that a sell will succeed.</p></div>
<div class="card"><h3>Measured in public</h3><p>Every verdict is recorded and judged about 24 hours later. Results, rules and a hash-chained ledger are open to read.</p></div>
<div class="card"><h3>MCP ready</h3><p>Add the server URL to Claude, Cursor or any MCP client. Tools: get_token_signal, check_token_risk, check_tokens_batch, check_exit, get_track_record.</p></div>
</div>
</section>

<section class="section">
<h2 class="t">A live example</h2>
<p class="sub">Fetched from this server right now. SOL is a major asset; new tokens usually look very different.</p>
<div class="card" id="example"><p class="muted">Loading...</p></div>
<pre>curl "%%BASE%%/signal?mint=So11111111111111111111111111111111111111112"</pre>
</section>

<section class="section">
<h2 class="t">Use it from an agent</h2>
<p class="sub">Remote MCP server (Streamable HTTP). Paste this URL into your client:</p>
<pre>%%BASE%%/mcp</pre>
</section>

<section class="section">
<h2 class="t">Honest limits</h2>
<div class="card"><ul class="honest">
<li>Free tier: %%RATE%% requests per minute per IP, batches of up to %%BATCH%% tokens. An API key raises the limit to %%KEYRATE%% requests per minute; keys are issued by hand during the beta.</li>
<li>Verdicts are heuristics, not a security audit and not financial advice.</li>
<li>Only tokens that are checked get measured, so the track record is not a random sample of all tokens.</li>
<li>The free host can sleep. If you get a 503, retry after a few seconds.</li>
<li>Data comes from DexScreener, Solana RPC, RugCheck and Jupiter and can be late or wrong.</li>
</ul></div>
</section>

<section class="final">
<h2 class="t">Try a token now</h2>
<p class="sub">Paste an address and see the verdict, the reasons and the sell cost.</p>
<div class="cta">%%CTA%%</div>
</section>

<footer><div>%%FOOT%%</div><p style="margin-top:1rem">TVibex402 - Heuristic signals only - Not financial advice</p></footer>
</div>
<script>
(function () {
  var BASE = %%BASEJS%%;
  Array.prototype.forEach.call(document.querySelectorAll('pre'), function (p) { p.textContent = p.textContent.split(BASE).join(window.location.origin); });
  function el(tag, text, cls) { var n = document.createElement(tag); if (text !== undefined && text !== null) { n.textContent = String(text); } if (cls) { n.className = cls; } return n; }
  function clear(n) { while (n.firstChild) { n.removeChild(n.firstChild); } }
  function getJson(url) { return fetch(url, { cache: 'no-store' }).then(function (r) { if (!r.ok) { throw new Error('HTTP ' + r.status); } return r.json(); }); }

  function proof() {
    getJson('/stats').then(function (d) {
      var a = ((d.performance || {}).all_tracked) || {};
      var judged = Number(a.judged), bad = Number(a.bad_outcomes);
      if (!isFinite(judged) || judged < 1 || !isFinite(bad)) { return; }
      var box = document.getElementById('proof');
      clear(box);
      box.appendChild(el('strong', judged + ' verdicts judged so far. '));
      box.appendChild(el('span', Math.round(bad / judged * 100) + '% of the tokens we tracked ended badly within ' + Math.round(d.horizon_hours || 24) + ' hours (price down 50%, liquidity down 70% or pair gone). ', 'muted'));
      var link = el('a', 'See every number'); link.href = '/accuracy'; box.appendChild(link);
      box.style.display = 'block';
    }).catch(function () {});
  }

  function usd(x) { var n = Number(x); return isFinite(n) ? '$' + n.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '-'; }
  function example() {
    var box = document.getElementById('example');
    getJson('/signal?mint=So11111111111111111111111111111111111111112').then(function (d) {
      clear(box);
      var known = ['ok', 'caution', 'avoid'].indexOf(d.verdict) >= 0;
      var head = el('p'); head.appendChild(el('span', d.verdict || 'unknown', 'badge ' + (known ? d.verdict : 'unknown')));
      head.appendChild(el('span', '  ' + (d.token || 'SOL') + ' - risk ' + d.risk_score + '/100 - liquidity ' + usd(d.liquidity_usd) + ' - holder quality ' + ((d.holder_quality || {}).score) + '/100'));
      box.appendChild(head);
      if (d.summary) { box.appendChild(el('p', d.summary, 'muted')); }
      var dec = d.decision || {};
      [['Positives', dec.positives], ['Cautions', dec.cautions], ['Unknown', dec.unknowns]].forEach(function (g) {
        var items = Array.isArray(g[1]) ? g[1].slice(0, 4) : [];
        if (!items.length) { return; }
        box.appendChild(el('strong', g[0]));
        var ul = el('ul'); items.forEach(function (x) { ul.appendChild(el('li', x)); }); box.appendChild(ul);
      });
    }).catch(function () { clear(box); box.appendChild(el('p', 'The live example is not available right now. Try the playground instead.', 'muted')); });
  }

  setTimeout(function () { proof(); example(); }, 200);
})();
</script>
</body>
</html>"""


def render_landing(base: str) -> str:
    nav = _links([("/play", "Playground"), ("/docs", "Docs"), ("/pricing", "Pricing"), ("/accuracy", "Accuracy"), ("/start", "Get started")],
                 '<a href="%P%">%L%</a>')
    cta = ('<a href="/play" class="btn btn-primary">Open the playground</a>' if _route_exists("/play")
           else '<a href="/docs" class="btn btn-primary">Read the docs</a>')
    cta += ('<a href="/start" class="btn btn-outline">Get started</a>' if _route_exists("/start")
            else '<a href="/pricing" class="btn btn-outline">Pricing</a>')
    foot = _links([("/play", "Playground"), ("/docs", "Docs"), ("/pricing", "Pricing"), ("/accuracy", "Accuracy"), ("/methodology", "Methodology"),
                   ("/ledger", "Ledger"), ("/status", "Status"), ("/llms.txt", "llms.txt")], '<a href="%P%">%L%</a>')
    ex_mint = "So11111111111111111111111111111111111111112"
    try_form = ('<form class="try" action="/play" method="get"><input name="mint" required autocomplete="off" spellcheck="false" '
                'placeholder="Paste a Solana token address" pattern="[1-9A-HJ-NP-Za-km-z]{32,44}" title="A Solana token address (32 to 44 characters)">'
                '<button type="submit">Check</button></form>'
                '<p class="tryhint muted">or try the example: <a href="/play?mint=' + ex_mint + '">SOL</a></p>') if _route_exists("/play") else ""
    explain_card = ('<div class="card"><h3>Explained verdicts</h3><p>Each verdict can be explained flag by flag, in English or Vietnamese: the points '
                    'each flag adds and what would change the result.</p></div>') if _route_exists("/explain") else ""
    return (_LANDING_TEMPLATE.replace("%%TRY%%", try_form).replace("%%EXPLAINCARD%%", explain_card).replace("%%NAV%%", nav).replace("%%CTA%%", cta).replace("%%FOOT%%", foot)
            .replace("%%BASEJS%%", _json_mod.dumps(base).replace("</", "<\\/")).replace("%%BASE%%", _html_escape(base)).replace("%%RATE%%", str(RATE_LIMIT))
            .replace("%%KEYRATE%%", str(KEY_RATE_LIMIT)).replace("%%BATCH%%", str(MAX_BATCH)))


import html as _html_mod  # noqa: E402
import json as _json_mod  # noqa: E402


def _html_escape(s: str) -> str:
    return _html_mod.escape(str(s), quote=True)


HOME_HTML = render_landing(os.getenv("PUBLIC_URL", "https://signal-api-24q4.onrender.com").rstrip("/"))  # "/" returns this variable


@app.get("/classic", response_class=HTMLResponse, include_in_schema=False)
async def classic_home():
    return _CLASSIC_HOME_HTML  # the previous home page, kept as a fallback


print(f"[part31] v{VERSION} new landing page at / (old home at /classic)")

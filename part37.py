# ---------- part37: v2.24.0 — source harden + seed growth + OG share card ----------
# 1) Source reliability: skip DexScreener when cooling (go straight to Gecko),
#    longer cache/stale while degraded, clearer health note.
# 2) Accuracy growth: seed still runs when Dex is cooling (Gecko candidates),
#    higher daily cap + shorter interval (overridable by env).
# 3) Social share: /og.svg card + og:image / twitter:image on the landing page.
#
# Load after part36, before part7. SKIP checksum.

VERSION = "2.24.0"
app.version = VERSION
app.openapi_schema = None

# ---------------------------------------------------------------------------
# 1. Source reliability
# ---------------------------------------------------------------------------

try:
    BASE_CACHE_TTL = max(int(BASE_CACHE_TTL), 45)
except Exception:
    BASE_CACHE_TTL = 45
try:
    STALE_MAX = max(int(STALE_MAX), 2400)
except Exception:
    pass

_homeostat_prev = homeostat


def homeostat() -> int:
    global CACHE_TTL
    status = (src_status().get("dexscreener") or {}).get("status")
    CACHE_TTL = BASE_CACHE_TTL * {"degraded": 4, "down": 8}.get(status, 1)
    return CACHE_TTL


_fetch_dex_prev = fetch_dex


async def fetch_dex(client: httpx.AsyncClient, mint: str) -> dict:
    cooling = False
    try:
        cooling = float(_DEX_COOLDOWN.get("until") or 0) > time.time()
    except Exception:
        pass
    if cooling:
        pairs = await _gt_fetch(client, mint)
        if pairs:
            _FALLBACK_MINTS[mint] = time.time()
            return {"pairs": pairs}
    return await _fetch_dex_prev(client, mint)


# ---------------------------------------------------------------------------
# 2. Seed / accuracy growth
# ---------------------------------------------------------------------------

try:
    if SEED_INTERVAL_S >= 900:
        SEED_INTERVAL_S = max(300, int(os.getenv("SEED_INTERVAL_S", "600")))
    if SEED_MAX_PER_DAY <= 40:
        SEED_MAX_PER_DAY = max(SEED_MAX_PER_DAY, int(os.getenv("SEED_MAX_PER_DAY", "80")))
except Exception:
    pass

_run_one_seed_prev = run_one_seed


async def run_one_seed(client: httpx.AsyncClient) -> dict:
    if not SEED_ENABLED:
        return {"ok": False, "detail": "SEED_TRAFFIC disabled"}
    if not _seed_day_ok():
        return {"ok": False, "detail": f"daily seed cap {SEED_MAX_PER_DAY} reached"}
    now = time.time()
    if now - _seed_state["last"] < SEED_INTERVAL_S:
        wait = int(SEED_INTERVAL_S - (now - _seed_state["last"]))
        return {"ok": False, "detail": "too soon", "retry_after_s": wait}

    mints = await _seed_candidate_mints(client)
    if not mints:
        _seed_state["errors"] += 1
        return {"ok": False, "detail": "no solana candidates from boosts/profiles/gecko"}

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
                break
            continue
        except Exception as e:
            last_err = str(e)[:120]
            continue
    _seed_state["errors"] += 1
    _seed_state["last"] = time.time()
    return {"ok": False, "detail": last_err or "all candidates failed"}


# ---------------------------------------------------------------------------
# 3. Open Graph share card
# ---------------------------------------------------------------------------

_PUBLIC_URL = (os.getenv("PUBLIC_URL") or "https://signal-api-24q4.onrender.com").rstrip("/")

_OG_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#05080f"/>
      <stop offset="100%" stop-color="#0f172a"/>
    </linearGradient>
    <linearGradient id="hl" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#818cf8"/>
      <stop offset="100%" stop-color="#c084fc"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect x="48" y="48" width="1104" height="534" rx="24" fill="#0f1420" stroke="#1e2638" stroke-width="2"/>
  <text x="100" y="180" font-family="ui-sans-serif,system-ui,sans-serif" font-size="42" font-weight="800" fill="#f1f5f9">TVibe<tspan fill="#6366f1">x402</tspan></text>
  <text x="100" y="280" font-family="ui-sans-serif,system-ui,sans-serif" font-size="56" font-weight="800" fill="url(#hl)">Solana token signals</text>
  <text x="100" y="350" font-family="ui-sans-serif,system-ui,sans-serif" font-size="56" font-weight="800" fill="#f1f5f9">built for AI agents</text>
  <text x="100" y="430" font-family="ui-sans-serif,system-ui,sans-serif" font-size="28" fill="#94a3b8">Verdict · reasons · sell cost · measured in public</text>
  <text x="100" y="520" font-family="ui-sans-serif,system-ui,sans-serif" font-size="22" fill="#64748b">Free to start · No API key · MCP ready</text>
</svg>"""


@app.get("/og.svg", include_in_schema=False)
async def og_svg():
    from starlette.responses import Response as _Resp
    return _Resp(
        content=_OG_SVG,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _inject_og(html: str) -> str:
    if not isinstance(html, str) or "og:image" in html:
        return html
    tags = (
        f'<meta property="og:image" content="{_PUBLIC_URL}/og.svg">'
        f'<meta property="og:image:width" content="1200">'
        f'<meta property="og:image:height" content="630">'
        f'<meta name="twitter:card" content="summary_large_image">'
        f'<meta name="twitter:image" content="{_PUBLIC_URL}/og.svg">'
    )
    html = html.replace('<meta name="twitter:card" content="summary">', tags, 1)
    if "og:image" not in html:
        if '<meta property="og:description"' in html:
            html = html.replace(
                '<meta property="og:description"',
                tags + '<meta property="og:description"',
                1,
            )
        elif '<meta charset="utf-8">' in html:
            html = html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + tags, 1)
    return html


try:
    if "HOME_HTML" in globals() and isinstance(HOME_HTML, str):
        HOME_HTML = _inject_og(HOME_HTML)
except Exception:
    pass


print(
    f"[part37] v{VERSION} source harden (gecko-first when cooling, cache×4/×8) · "
    f"seed interval={SEED_INTERVAL_S}s max/day={SEED_MAX_PER_DAY} (runs while dex cooling) · "
    f"OG card at /og.svg"
)
# ---------- part39: v2.26.0 - seed mature tokens so ok/caution samples fill ----------
import datetime as _dt

VERSION = "2.26.0"
app.version = VERSION
app.openapi_schema = None

SEED_EST_MIN_LIQ = float(os.getenv("SEED_EST_MIN_LIQ", "150000"))
SEED_EST_MIN_AGE_D = float(os.getenv("SEED_EST_MIN_AGE_D", "3"))
SEED_EST_EVERY = max(1, int(os.getenv("SEED_EST_EVERY", "3")))
_est_seen = {}


async def _est_candidates(client: httpx.AsyncClient) -> list:
    page = 1 + int(time.time() // SEED_INTERVAL_S) % 5
    url = ("https://api.geckoterminal.com/api/v2/networks/solana/pools"
           f"?page={page}&sort=h24_volume_usd_desc&order=h24_volume_usd_desc")
    out = []
    try:
        resp = await client.get(url, headers={"Accept": "application/json;version=20230302"}, timeout=8.0)
        if resp.status_code != 200:
            return out
        now = time.time()
        for row in resp.json().get("data") or []:
            at = row.get("attributes") or {}
            rel = (row.get("relationships") or {}).get("base_token") or {}
            mint = ((rel.get("data") or {}).get("id") or "").replace("solana_", "", 1)
            if not MINT_RE.match(mint) or mint in MAJOR_ASSETS:
                continue
            if float(at.get("reserve_in_usd") or 0) < SEED_EST_MIN_LIQ:
                continue
            if now - _est_seen.get(mint, 0) < 86400:
                continue
            try:
                born = _dt.datetime.fromisoformat(str(at.get("pool_created_at")).replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if now - born < SEED_EST_MIN_AGE_D * 86400:
                continue
            out.append(mint)
    except Exception:
        pass
    return out


_seed_candidates_prev = _seed_candidate_mints


async def _seed_candidate_mints(client: httpx.AsyncClient) -> list:
    base = await _seed_candidates_prev(client)
    if _seed_state["count"] % SEED_EST_EVERY != SEED_EST_EVERY - 1:
        return base
    est = await _est_candidates(client)
    if not est:
        return base
    _est_seen[est[0]] = time.time()
    return est[:3] + [m for m in base if m not in est[:3]]


print(f"[part39] v{VERSION} mature-token seeding (every {SEED_EST_EVERY}th seed, "
      f"liq>=${SEED_EST_MIN_LIQ:,.0f}, age>={SEED_EST_MIN_AGE_D}d)")
# TVibe Signal — Render env checklist (free tier)

Set these on the **Web Service → Environment** (not in public git secrets).

## Required for Redis track-record

```text
UPSTASH_REDIS_REST_URL=https://xxxx.upstash.io
UPSTASH_REDIS_REST_TOKEN=...
```

Use **REST** URL + token (not only `rediss://` Redis URL).

## Seed / cache (recommended free)

```text
SEED_TRAFFIC=true
SEED_MAX_PER_DAY=40
SEED_INTERVAL_S=900
CACHE_TTL_OK=30
CACHE_TTL_CAUTION=90
CACHE_TTL_AVOID=3600
```

Optional when you change thresholds:

```text
RULES_VERSION=2026.10.28.a
```

Bump `RULES_VERSION` and document on `/rules` when heuristics change — no stealth retune.

## After save

1. Manual Deploy / restart  
2. `GET /health` → `track_record_store.reachable: true`  
3. `GET /ops/cache-policy` → `seed.max_per_day: 40`  
4. Cron: only `GET /ping` or `/health` every 5–10 min, **save response OFF**

## Do not set on public free instance

- Aggressive seed (`SEED_MAX_PER_DAY=120+`) unless Upstash/Dex headroom is confirmed  
- Cron hitting `/omni` or heavy `/seed` loops  

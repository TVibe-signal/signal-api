# TVibe Signal — Ops (free tier)

## Keep-alive (Render)

- **One** cron job only: `GET /ping` or `GET /health`
- Interval: **5–10 minutes**
- **Save response history: OFF** (cron-job.org free tier)
- Do **not** cron `/omni`, heavy `/seed`, or experimental SI paths

## Env (recommended free)

```text
SEED_TRAFFIC=true
SEED_MAX_PER_DAY=40
SEED_INTERVAL_S=900
CACHE_TTL_OK=30
CACHE_TTL_CAUTION=90
CACHE_TTL_AVOID=3600
```

Optional: `RULES_VERSION=2026.10.28.a` when you change thresholds (always changelog via `/rules`).

## Nurture cadence

- 8–12 distinct mints per batch, a few times per day if convenient
- Mix risk (not only trending winners)
- Read `/stats` every few days before changing heuristics
- Bump `rules_version` when thresholds change — no stealth retune

## Health checks

| URL | Use |
|-----|-----|
| `/ping` | Light keep-alive |
| `/health` | Redis / MCP status |
| `/ops/cache-policy` | TTL + seed caps |
| `/stats` | Track-record |
| `/rules` | Public rules version |

## Fair use

Public instance is free. Prefer self-host for heavy traffic. See `/pricing` or `/agents` if present.

# TVibe Signal

Free **Solana mint risk gate** for AI agents. Heuristic `pass` / `review` / `skip` with a public track record.

- Live: https://signal-api-24q4.onrender.com
- Primary call: `GET /omni?mint=<MINT>&view=agent`
- PRO call: `GET /pro_json?mint=<MINT>` (grade A-F + holders / LP / dev / authority breakdown)
- Quick call: `GET /check?mint=<MINT>` (compact JSON for bots)
- Track record: `GET /stats` · Methodology: `GET /methodology` · History: `GET /history`
- **NFA** — not financial advice. `ok` / `pass` is a cleared risk gate, not a buy order.

## Agent setup (Claude / Cursor)

```json
{ "mcpServers": { "tvibe": { "url": "https://signal-api-24q4.onrender.com/mcp" } } }
```

One-liner for any agent: `GET https://signal-api-24q4.onrender.com/omni?mint=<MINT>&view=agent`
Machine docs: `/llms.txt` · skill: `/skill.json`

## How to read a PRO result

| Field | Meaning |
|-------|---------|
| `action` | `pass` \| `review` \| `skip` |
| `verdict` | `ok` \| `caution` \| `avoid` \| `unverified` |
| `confidence` | `high` / `medium` / `low` - low means on-chain data was missing |
| `data_quality.missing` | Which checks could not run (holders, authority, creator, lp) |
| `verdict_capped_by` | Why a good score was capped (e.g. `missing_core_data`) |
| `valid_for_s` | Stale after this - re-fetch |

`unverified` = the on-chain data could not be read. Never size a trade on it.

## Limits and configuration

Public instance is **free** with fair use. Defaults (override with env vars):

| Env | Default | Meaning |
|-----|---------|---------|
| `SOLANA_RPC_URL` (or `HELIUS_URL`, `PRIVATE_RPC`) | - | RPC for on-chain checks |
| `PRO_RATE_PER_MIN` | 30 | Per-IP requests per minute (batch = 1 per mint) |
| `PRO_GLOBAL_PER_MIN` | 300 | All callers together |
| `PRO_CACHE_FRESH_S` | 90 | Cache time per mint |
| `PRO_CACHE_STALE_S` | 900 | Serve stale only when upstream fails |
| `PRO_CREATOR_MAX_PAGES` | 4 | Pages of 1000 signatures searched for the creator |

## Self-host

```bash
git clone https://github.com/TVibe-signal/signal-api
cd signal-api
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Tests (offline): `python tests/test_pro_engine.py`

## Links

- X: https://x.com/realTVibe
- Telegram: https://t.me/Gotvibesolbot
- Donate (optional, free product): Sol `3iAVBvE4aU4A5DTKCqzu6jg79UfW6aEnqUD1pjfew18n`

# TVibe Signal

Free, open-source **Solana token risk API** for humans and AI agents.

**Not financial advice.** Heuristics with a public track record on `/stats`.

- **Live:** https://signal-api-24q4.onrender.com  
- **X:** https://x.com/realTVibe  
- **Telegram:** https://t.me/Gotvibesolbot  

## Quick use

```text
GET /omni?mint=<MINT>&view=agent
GET /agent/playbook
GET /llms.txt
GET /stats
GET /rules
MCP  https://signal-api-24q4.onrender.com/mcp
```

## Repo layout

```text
main.py           # loader only
core.py           # base API + scoring
features.py       # omni / SI / extras
extensions.py     # agent view, MCP last, ops patches
requirements.txt
runtime.txt
docs/             # ops, agents, phase notes
examples/         # client scripts (not on Render)
```

## Deploy (Render)

- **Build:** `pip install -r requirements.txt`
- **Start:** `python -m uvicorn main:app --host 0.0.0.0 --port $PORT`
- **Env:** see [docs/ENV_CHECKLIST.md](docs/ENV_CHECKLIST.md) (`SEED_MAX_PER_DAY=40`, Redis REST, …)

## Docs

| Doc | Topic |
|-----|--------|
| [docs/AGENTS.md](docs/AGENTS.md) | Agent / MCP contract |
| [docs/OPS.md](docs/OPS.md) | Cron + free tier |
| [docs/DATA_FEEDER.md](docs/DATA_FEEDER.md) | Data nurture prompts (ops only, NFA) |
| [docs/PHASE2_CALIBRATION.md](docs/PHASE2_CALIBRATION.md) | Stats-based calibration log |
| [docs/PHASE3_WATCH.md](docs/PHASE3_WATCH.md) | Watch / recheck client |
| [examples/](examples/) | `gate` · `warmer` · `watch_recheck` |

## Track record

See live `GET /stats`. Compare within the same `rules_version`. NFA.

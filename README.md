# TVibe Signal

Free **Solana mint risk gate** for AI agents. Heuristic `pass` / `review` / `skip` with a public track record.

- Live: https://signal-api-24q4.onrender.com  
- Primary call: `GET /omni?mint=<MINT>&view=agent`  
- Track record: `GET /stats` · Methodology: `GET /methodology` · History: `GET /history`  
- **NFA** — not financial advice. `ok` / `pass` is a cleared risk gate, not a buy order.

## Agent setup (Claude / Cursor) — copy paste

### Claude Desktop — `claude_desktop_config.json`

```json
{
  "mcpServers": {
    "tvibe": {
      "url": "https://signal-api-24q4.onrender.com/mcp"
    }
  }
}
```

### Cursor — MCP / tools config

```json
{
  "mcp": {
    "tvibe": {
      "url": "https://signal-api-24q4.onrender.com/mcp"
    }
  }
}
```

### One-liner (HTTP, any agent)

```text
GET https://signal-api-24q4.onrender.com/omni?mint=<MINT>&view=agent
```

Machine docs: https://signal-api-24q4.onrender.com/llms.txt · skill: `/skill.json`

## What you get (`view=agent`)

| Field | Meaning |
|--------|---------|
| `action` | `pass` \| `review` \| `skip` |
| `filter.pass` | Gate cleared only when true |
| `unknowns` | Non-empty → do not size |
| `valid_for_s` / `expires_at` | Stale after expiry — re-fetch |
| `rules_version` | Compare `/stats` only within the same version |

## Public verify

| URL | Role |
|-----|------|
| `/stats` | Measured outcomes |
| `/methodology` · `/methodology.html` | How verdicts work |
| `/history` | Verdict table (from ledger) |
| `/ledger` | Hash-chained snapshots |
| `/rules` · `/ops/rules-changelog` | Thresholds & changelog |

## Fair use

Public instance is **free** with fair use (`GET /ops/fair-use`). High volume → self-host this repo.

## Self-host (short)

```bash
git clone https://github.com/TVibe-signal/signal-api
cd signal-api
# set REDIS / RPC env as needed — see .env.example if present
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Links

- X: https://x.com/realTVibe  
- Telegram: https://t.me/Gotvibesolbot  
- Donate (optional, free product): Sol `3iAVBvE4aU4A5DTKCqzu6jg79UfW6aEnqUD1pjfew18n`

## License

Open source — see repo `LICENSE` if present.

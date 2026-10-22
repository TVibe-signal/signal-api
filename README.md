# TVibe Signal

Solana token **risk signals** for **AI agents**. Heuristics, measured in public. **Not financial advice.**

Free public instance · open source · self-host anytime.

| | |
|---|---|
| **Public API** | https://signal-api-24q4.onrender.com |
| **Repo** | https://github.com/TVibe-signal/signal-api |
| **X** | https://x.com/realTVibe |
| **Telegram bot** | https://t.me/Gotvibesolbot |

Market data: DexScreener / GeckoTerminal · On-chain: Solana RPC · LP: RugCheck · Exit quotes: Jupiter.

---

## For agents (start here)

| Use | Value |
|-----|--------|
| **Primary HTTP** | `GET /omni?mint=<MINT>` |
| **Gate** | `filter.pass` + `decision.verdict` |
| **Policies** | `default` · `strict` · `research` (`?policy=` or see `/filter/policies`) |
| **MCP** | `https://signal-api-24q4.onrender.com/mcp` |
| **MCP tool** | `omni(mint)` |
| **Machine docs** | https://signal-api-24q4.onrender.com/llms.txt |
| **Agent page** | https://signal-api-24q4.onrender.com/agents |
| **Reliability / fair use** | `/agents/reliability` · `/pricing` |
| **Accuracy** | `/stats` |
| **Rule candidates** | `/stats/rule-candidates` |
| **Walk-forward (no auto-promote)** | `/filter/walk-forward` |
| **Pattern benchmark** | `/benchmark/prerug` |

```bash
curl -sS "https://signal-api-24q4.onrender.com/omni?mint=So11111111111111111111111111111111111111112" \
  | jq '{verdict: .decision.verdict, filter: .filter, risk: .decision.risk_score}'
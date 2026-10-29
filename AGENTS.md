# TVibe Signal — For AI agents

**NFA.** Heuristic risk filter for Solana mints — not financial advice.

## Quick start

1. Read: `GET https://signal-api-24q4.onrender.com/llms.txt`
2. Optional: `GET /agent/playbook`
3. Discovery card: `GET /.well-known/agent-card.json`
4. Primary call: `GET /omni?mint=<MINT>&view=agent`
5. Before sizing: exit / `check_exit` if unknowns remain
6. Calibrate occasionally: `GET /stats`

## MCP

- URL: `https://signal-api-24q4.onrender.com/mcp`
- Tools: `check_token_risk`, `check_tokens_batch`, `check_exit`, `get_track_record`, `screen_hot`
- `screen_hot` = boost shortlist + filters only (not full-chain discovery)

## Agent view fields

| Field | Meaning |
|-------|---------|
| `action` | `pass` \| `review` \| `skip` |
| `filter.pass` | Hard gate boolean |
| `risk_score` | Heuristic 0–100 (higher = worse) |
| `confidence` | low / medium (never treat as certainty) |
| `data_quality` | completeness / freshness |
| `sizing_hint` | policy hint only (`zero`, `tiny_or_skip`, …) |
| `unknowns` | Missing checks — lower confidence |
| `rules_version` | Compare outcomes within the same version |

## Errors

Machine-readable when available:

```json
{
  "ok": false,
  "error": {
    "code": "RATE_LIMIT",
    "retryable": true,
    "agent_action": "backoff",
    "retry_after_s": 30
  }
}
```

Honor `retryable` and never invent `filter.pass`.

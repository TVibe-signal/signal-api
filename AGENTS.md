# For AI agents — TVibe Signal

**Not financial advice.** Heuristic risk gate for Solana mints.

## Quick path

1. `GET https://signal-api-24q4.onrender.com/llms.txt`
2. `GET /agent/playbook`
3. `GET /omni?mint=<MINT>&view=agent`
4. If `action` is `skip` or `filter.pass` is false → do not size
5. If `unknowns` non-empty → call exit / `check_exit` before any size talk
6. Calibrate with `GET /stats` (same `rules_version`)

## MCP

- URL: `https://signal-api-24q4.onrender.com/mcp`
- Tools: `check_token_risk`, `check_tokens_batch`, `check_exit`, `get_track_record`, `screen_hot`
- `screen_hot` = boost shortlist only, not full-chain discovery

## Fields that matter

| Field | Use |
|-------|-----|
| `action` | pass / review / skip |
| `filter.pass` | hard gate |
| `risk_score` | 0–100, higher = worse |
| `sizing_hint` | policy hint only |
| `data_quality` | lower confidence if partial/stale |
| `rules_version` | compare outcomes within version |

## Errors

Honor `error.code`, `retryable`, `retry_after_s` when present.

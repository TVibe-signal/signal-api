# part132.py — free-forever agent discovery (llms.txt). No paywall. No x402.
VERSION = "3.0.3"
app.version = VERSION
app.openapi_schema = None

_LLMS = """# TVibe Signal
> Solana token **risk** signals for AI agents. Heuristics, measured in public. Not financial advice.
> Free public instance — no paywall on core signal. Self-host anytime.

## Primary interface (use this first)
- HTTP: GET https://signal-api-24q4.onrender.com/omni?mint=<SOLANA_MINT>
- Gate: response.filter.pass + response.decision.verdict
- Policies: default | strict | research — GET /filter/policies  or  ?policy=strict
- MCP:  https://signal-api-24q4.onrender.com/mcp
- MCP tool: omni(mint)

Reading order: filter.pass → filter.reasons → decision.verdict → blockers/cautions/unknowns → sim → system_stress.
Trust decision.* first. Treat debate / residual / dna / shadow_* as optional context only.
When decision.unknowns is non-empty, prefer caution over size.
If decision.verdict_raw is present, the verdict was lowered (capped) from that value.

## Agent pattern (before size)
1. omni(mint) or GET /omni?mint=
2. if filter.pass is false → do not size (or hard-cap)
3. if pass and verdict ok → still read cautions, sim, system_stress
4. cache mint for valid_for_s seconds (often \~120)

## Prove it (do not skip)
- GET /stats
- GET /stats/rule-candidates
- GET /filter/walk-forward   (score_35 checklist — promote_allowed false until operator)
- GET /benchmark/daily

## Honesty fields
- blockers, cautions, positives, unknowns
- valid_for_s, would_change_my_mind, track_record_context
- system_stress, sim (Jupiter quote heuristic — not full honeypot VM)

## Fair use (always free core)
- best_effort_free — /agents/reliability · /pricing
- \~30 req/min without a key. Heavy use: self-host.
- Cron: GET /ping every 10–14m (do not save large response bodies)

## Secondary
- /signal · /signals?mints= (max 10) · /exit · /health · /ping
- /stats/deployer-shadow · /stats/shadow-avoid (research only)

## Repo · social
- https://github.com/TVibe-signal/signal-api
- https://x.com/realTVibe
- Telegram: https://t.me/Gotvibesolbot

## Disclaimer
Heuristics for agents and research. Not financial advice. Data can be late, partial, or wrong.
"""


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt_free_forever():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(_LLMS, media_type="text/plain; charset=utf-8")


print("[part132] v%s free llms.txt — filter gate + agent pattern" % VERSION)
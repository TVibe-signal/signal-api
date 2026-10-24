# part132.py - llms.txt for agents (override any earlier /llms.txt) (v3.0.4, reviewed)
# Review fixes vs v3.0.3: "\~120" and "\~30" were invalid escapes (SyntaxWarning, and the text showed a backslash);
# "GET /filter/walk-forward" does not exist, the endpoint is /stats/walk-forward.
# Check that GET /ping exists (the health board at /ops/health reports missing routes); if not, use /health.
VERSION = "3.0.4"
app.version = VERSION
app.openapi_schema = None

from fastapi.responses import PlainTextResponse

_LLMS = """# TVibe Signal
> Solana token **risk** signals for AI agents. Heuristics, measured in public. Not financial advice.
> Free public instance: no paywall on the core signal today. Self-host anytime.

## Primary interface (use this first)
- HTTP: GET https://signal-api-24q4.onrender.com/omni?mint=<SOLANA_MINT>
- Gate: response.filter.pass + response.decision.verdict
- Policies: default | strict | research. GET /filter/policies or ?policy=strict
- MCP:  https://signal-api-24q4.onrender.com/mcp
- MCP tool: omni(mint)

Reading order: filter.pass, filter.reasons, decision.verdict, blockers/cautions/unknowns, sim, system_stress.
Trust decision.* first. Treat debate / residual / dna / shadow_* as optional context only.
When decision.unknowns is non-empty, prefer caution over size.

## Agent pattern (before size)
1. omni(mint) or GET /omni?mint=
2. if filter.pass is false: do not size (or hard-cap)
3. if pass and verdict ok: still read cautions, sim, system_stress
4. cache the mint for valid_for_s seconds (15 to 120, see decision.valid_for_s)

## Prove it
- GET /stats
- GET /stats/rule-candidates
- GET /stats/walk-forward
- GET /benchmark/daily
- GET /verify (check a signed verdict in the browser)

## Fair use (free core, best effort)
- /agents/reliability and /pricing
- about 30 requests per minute. Heavy use: self-host.
- Keep-alive: GET /ping every 10 to 14 minutes (do not save large response bodies)

## Secondary
- /signal, /signals, /exit, /health, /ping

## Repo and social
- https://github.com/TVibe-signal/signal-api
- https://x.com/realTVibe
- Telegram: https://t.me/Gotvibesolbot

## Disclaimer
Heuristics for agents and research. Not financial advice. Data can be late, partial, or wrong.
"""

try:
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/llms.txt"]
except Exception as _e:
    print("[part132] could not drop older /llms.txt:", str(_e)[:100])


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt_free_core():
    return PlainTextResponse(_LLMS, media_type="text/plain; charset=utf-8")


print("[part132] v%s /llms.txt overridden (filter.pass, walk-forward, verify)" % VERSION)

# ---------- v2.91: llms.txt — TVibe Signal, honest agent surface ----------
VERSION = "2.91.0"
app.version = VERSION
app.openapi_schema = None

from fastapi.responses import PlainTextResponse

LLMS_TXT = """# TVibe Signal
> Solana token signals for AI agents. Heuristics, measured in public. Not financial advice.

## Primary interface (use this first)
- HTTP: GET https://signal-api-24q4.onrender.com/omni?mint=<SOLANA_MINT>
- MCP:  https://signal-api-24q4.onrender.com/mcp
- MCP tool: omni(mint)

Trust decision.verdict first. Treat debate / residual / pre_rug as optional context.
When decision.unknowns is non-empty, prefer caution over size.

## Prove it (do not skip)
- GET https://signal-api-24q4.onrender.com/stats
- GET https://signal-api-24q4.onrender.com/benchmark/daily
- Avoid precision vs base rate and vs a simple liquidity/age baseline are published there.

## Honesty fields on omni / decision
- blockers, cautions, positives, unknowns
- valid_for_s — cache hint in seconds
- would_change_my_mind — what would revise the call
- track_record_context — similar past verdicts (not P(this mint fails))

## Secondary
- GET /signal?mint=  — classic signal
- GET /signals?mints=A,B,C&view=compact — batch max 10
- GET /exit?mint= — Jupiter sell cost
- GET /health
- GET /attest — signed verdict verification
- GET /stats/deployer-shadow — research only, not live verdict
- GET /stats/shadow-avoid — research only

## Fair use
Free public instance. \~30 req/min. Cache the same mint 15–30s. Heavy use: self-host.
GitHub: https://github.com/TVibe-signal/signal-api

## Disclaimer
Heuristics for agents and research. Not financial advice. Data can be late or wrong.
"""


@app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
async def llms_txt_v291():
    return LLMS_TXT


print(f"[part111] v{VERSION} /llms.txt TVibe Signal")
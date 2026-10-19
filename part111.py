# ---------- v2.91.1: llms.txt - TVibe Signal, honest agent surface (reviewed) ----------
# Review fixes vs v2.91.0:
#   - an older part may already serve /llms.txt (first route wins), so remove it before registering this one
#   - "\~30" (invalid escape, SyntaxWarning) -> "~30"
#   - GitHub link matched to the one on the home page (TVibex402)
#   - mentions /verify and the attestation field
VERSION = "2.91.1"
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
If decision.verdict_raw is present, the verdict was lowered (capped) from that value.

## Prove it (do not skip)
- GET https://signal-api-24q4.onrender.com/stats
- GET https://signal-api-24q4.onrender.com/benchmark/daily
- Avoid precision vs base rate and vs a simple liquidity/age baseline are published there.
- Only tokens that people query are measured, so this is not a random sample of all tokens.

## Honesty fields on omni / decision
- blockers, cautions, positives, unknowns
- valid_for_s: cache hint in seconds
- would_change_my_mind: what would revise the call
- track_record_context: similar past verdicts (not the probability that this mint fails)

## Signed verdicts
- Every /omni response includes `attestation`: an Ed25519 signature and a hash chain.
- Check one in the browser: https://signal-api-24q4.onrender.com/verify
- Signing key and chain status: GET /attest

## Secondary
- GET /signal?mint=  classic signal
- GET /signals?mints=A,B,C&view=compact  batch, max 10
- GET /exit?mint=  Jupiter sell cost
- GET /health
- GET /stats/deployer-shadow  research only, not live verdict
- GET /stats/shadow-avoid  research only

## Fair use
Free public instance. ~30 req/min. Cache the same mint 15-30s. Heavy use: self-host.
GitHub: https://github.com/TVibex402/signal-api

## Disclaimer
Heuristics for agents and research. Not financial advice. Data can be late or wrong.
"""

try:
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != "/llms.txt"]
except Exception as _e:
    print("[part111] could not replace an older /llms.txt route:", str(_e)[:100])


@app.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
async def llms_txt_v291():
    return LLMS_TXT


print(f"[part111] v{VERSION} /llms.txt TVibe Signal")

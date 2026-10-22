# part132.py — free-forever agent discovery: llms.txt + light /agents brand
# No payments. No x402. Core /omni stays free.
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

## Prove it (do not skip)
- GET https://signal-api-24q4.onrender.com/stats
- GET https://signal-api-24q4.onrender.com/stats/rule-candidates
- GET https://signal-api-24q4.onrender.com/filter/walk-forward  (score_35 checklist — promote_allowed stays false until operator)
- GET https://signal-api-24q4.onrender.com/benchmark/daily
Avoid precision vs base rate is published on /stats. Only queried tokens are measured (not a random census).

## Honesty fields on omni / decision
- blockers, cautions, positives, unknowns
- valid_for_s: cache hint in seconds (reuse the same mint)
- would_change_my_mind: what would revise the call
- track_record_context: similar past verdicts (not P(this mint fails))
- system_stress: when open/half, prefer smaller size or wait
- sim: Jupiter quote heuristic — not a full honeypot sandbox

## Reliability & fair use (always free core)
- Class: best_effort_free — GET /agents/reliability · GET /pricing
- \~30 req/min without a key. Cache the same mint for valid_for_s (often \~120s).
- Heavy use: self-host from GitHub. Do not hammer Dex via us.
- Cron keep-alive: GET /ping every 10–14m; do not require large response logs.

## Secondary
- GET /signal?mint=
- GET /signals?mints=A,B,C&view=compact  (batch, max 10)
- GET /exit?mint=  sell friction quote
- GET /health · GET /ping
- GET /stats/deployer-shadow · /stats/shadow-avoid  research only

## Signed verdicts
- attestation on /omni when enabled · verify: /verify · keys: GET /attest

## Repo · social
- https://github.com/TVibe-signal/signal-api
- https://x.com/realTVibe
- Telegram: https://t.me/Gotvibesolbot

## Disclaimer
Heuristics for agents and research. Not financial advice. Data can be late, partial, or wrong.
"""


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt_v303():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(_LLMS, media_type="text/plain; charset=utf-8")


# Soft-brand /agents title if HTML handler exists — never break
_agents_prev = None
for _n, _f in list(globals().items()):
    if callable(_f) and _n in ("agents_page", "agents_html", "for_agents"):
        _agents_prev = _f
        break

if _agents_prev is not None:
    async def agents_page_free(*a, **k):
        res = await _agents_prev(*a, **k) if asyncio.iscoroutinefunction(_agents_prev) else _agents_prev(*a, **k)
        try:
            from fastapi.responses import HTMLResponse
            if isinstance(res, HTMLResponse) or (hasattr(res, "body") and b"TVibex402" in getattr(res, "body", b"")):
                body = res.body.decode("utf-8", "ignore") if hasattr(res, "body") else str(res)
                body = body.replace("TVibex402", "TVibe Signal")
                return HTMLResponse(body)
        except Exception:
            pass
        return res

    try:
        import asyncio  # noqa: F401
    except Exception:
        pass

print("[part132] v%s free-forever llms.txt — filter.pass + no paywall" % VERSION)
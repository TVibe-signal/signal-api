# ---------- v2.72: Agent snippets + SI noise reduction ----------
VERSION = "2.72.0"
app.version = VERSION
app.openapi_schema = None

from fastapi.responses import PlainTextResponse, HTMLResponse

AGENT_SNIPPETS = r'''# TVibex402 — agent snippets (copy-paste)

Base: https://signal-api-24q4.onrender.com
Primary: GET /omni?mint=<MINT>
MCP: POST /mcp  tool omni(mint)
Not financial advice.

## curl
curl -s "https://signal-api-24q4.onrender.com/omni?mint=So11111111111111111111111111111111111111112"

## Python httpx
import httpx
r = httpx.get(
    "https://signal-api-24q4.onrender.com/omni",
    params={"mint": "So11111111111111111111111111111111111111112"},
    timeout=60,
)
data = r.json()
verdict = (data.get("decision") or {}).get("verdict")

## LangChain-style tool (pseudo)
# Use StructuredTool that GETs /omni and returns decision.verdict + summary only.

## CrewAI / AutoGen
# One tool: fetch_omni(mint) -> trust decision.*; treat debate/residual/pre_rug as optional context.

## Claude MCP / Cursor
# Add MCP server URL: https://signal-api-24q4.onrender.com/mcp
# Prefer tool: omni

## How to read the payload
1. decision.verdict  (primary)
2. decision.blockers / cautions / unknowns
3. Optional: debate, attention_residuals, pre_rug, shadow_avoid (experimental)
4. Prove: GET /stats  GET /stats/horizons  GET /stats/bias  GET /benchmark/prerug
'''


@app.get("/agents/snippets", response_class=PlainTextResponse, tags=["product"])
async def agents_snippets():
    return AGENT_SNIPPETS


@app.get("/agents/snippets.html", response_class=HTMLResponse, tags=["product"], include_in_schema=False)
async def agents_snippets_html():
    body = AGENT_SNIPPETS.replace("&", "&amp;").replace("<", "&lt;")
    return f"""<!doctype html><html><head><meta charset=utf-8>
<title>TVibex402 agent snippets</title>
<style>body{{font-family:ui-monospace,monospace;background:#0b1220;color:#e8eef6;padding:24px}}
pre{{white-space:pre-wrap;background:#121a2a;padding:16px;border-radius:12px}}</style></head>
<body><h1>Agent snippets</h1><pre>{body}</pre>
<p><a href="/agents" style="color:#14f195">/agents</a> · <a href="/llms.txt" style="color:#14f195">/llms.txt</a></p>
</body></html>"""


def _si_quiet(result: dict) -> dict:
    """Mark experimental blocks so agents know what is primary."""
    if not isinstance(result, dict):
        return result
    exp = []
    for k in ("debate", "attention_residuals", "shadow_avoid", "pre_rug", "dna", "time_to_death",
              "counterfactual", "hypotheses_matched", "genetic_risk", "attention_trap", "swarm"):
        if result.get(k) is not None:
            exp.append(k)
    result["si_reading_order"] = {
        "primary": ["decision.verdict", "decision.blockers", "decision.cautions", "decision.unknowns"],
        "experimental": exp,
        "note": "Trust decision.* first. Experimental fields are context, not overrides.",
        "version": VERSION,
    }
    return result


_build_prev_quiet = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_quiet(client, mint, security, prefetched)
    try:
        if isinstance(result, dict):
            result = _si_quiet(result)
    except Exception:
        pass
    return result, status


print(f"[part94] v{VERSION} agent snippets + si_reading_order → /agents/snippets")
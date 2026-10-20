# part118.py — Slow learning surface: publish shadow + circuit for agents (no ML weights)
VERSION = "2.93.0"
app.version = VERSION
app.openapi_schema = None


@app.get("/agent/brain", tags=["agents"], include_in_schema=False)
async def agent_brain(request: Request):
    """One glance for agents: what is measured, what is shadow, system stress."""
    out = {
        "version": VERSION,
        "role": "on-chain signal + measured track record; social is optional via the agent (X), not scraped here",
        "primary": "GET /omni?mint=",
        "prove": ["GET /stats", "GET /benchmark/daily"],
        "system": {},
        "shadow": {},
        "learning": {
            "online_ml": False,
            "mechanism": "outcomes → calibration / shadow rules; promote only when measured",
            "offline": "optional parquet → LightGBM later; not required for production verdicts",
        },
        "slippage": "GET /exit?mint= — impact band when quote works; no MEV protection claim",
        "disclaimer": "Heuristic. Not financial advice.",
    }
    try:
        if "circuit_status" in globals():
            out["system"] = circuit_status()
    except Exception:
        pass
    try:
        # best-effort: reuse public stats if handler exists
        client = request.app.state.client
        out["shadow"]["note"] = "See GET /stats/shadow-avoid and /stats/deployer-shadow (research only)"
    except Exception:
        pass
    return out


print(f"[part118] v{VERSION} GET /agent/brain — honest agent map (no fake ML)")
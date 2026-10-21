# part118.py - agent map (v2.93.1, reviewed): GET /agent/brain
# Review fix: it said "/exit has an impact band" - the band is `sim.slippage_band` on /signal and /omni (part119).
VERSION = "2.93.1"
app.version = VERSION
app.openapi_schema = None


@app.get("/agent/brain", tags=["agents"], include_in_schema=False)
async def agent_brain(request: Request):
    """One glance for agents: what is measured, what is shadow, system stress."""
    out = {
        "version": VERSION,
        "role": "on-chain signal + measured track record; social is optional via the agent (X), not scraped here",
        "primary": "GET /omni?mint=",
        "prove": ["GET /stats", "GET /benchmark/daily", "GET /verify"],
        "system": {},
        "shadow": {"note": "See GET /stats/shadow-avoid, /stats/deployer-shadow and /stats/cluster-shadow (research only)"},
        "learning": {
            "online_ml": False,
            "mechanism": "outcomes -> calibration / shadow rules; promote only when measured",
            "offline": "optional feature export for later offline models; not used for live verdicts",
        },
        "sell_cost": "sim.* on /signal and /omni (quote-based); GET /exit?mint= for the full quote. No MEV protection claim.",
        "disclaimer": "Heuristic. Not financial advice.",
    }
    try:
        if "circuit_status" in globals():
            out["system"] = circuit_status()
    except Exception:
        pass
    return out


print(f"[part118] v{VERSION} GET /agent/brain")

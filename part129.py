# part129.py — Phase D policy status (read-only, no live rule changes)
VERSION = "3.0.1"
app.version = VERSION
app.openapi_schema = None

@app.get("/filter/phase-d", tags=["agents"], include_in_schema=False)
async def filter_phase_d():
    strong, judged, err = [], None, None
    try:
        import httpx
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal", timeout=30) as c:
            r = await c.get("/stats/rule-candidates")
            d = r.json() if r.status_code == 200 else {}
            strong = d.get("strong_candidates") or []
            judged = d.get("judged")
            err = d.get("error")
    except Exception as e:
        err = str(e)[:120]
    ready = bool(strong) and not err
    return {
        "version": VERSION,
        "phase": "D",
        "live_rules_unchanged": True,
        "promote_ready": ready,
        "strong_candidates": strong,
        "judged": judged,
        "error": err,
        "how_to_use_now": {
            "default": "GET /omni?mint=  → filter.pass",
            "strict": "GET /omni?mint=&policy=strict  (stricter gate, still no silent rule rewrite)",
            "research": "policy=research → pass always true, reasons only",
        },
        "promote_checklist": [
            "strong_candidates non-empty on /stats/rule-candidates",
            "clean data after outages",
            "walk-forward when available",
            "public version bump + changelog before any live rule change",
        ],
        "note": "Phase D does not auto-promote. Empty strong_candidates means wait and feed outcomes.",
    }

print("[part129] v%s GET /filter/phase-d (no auto-promote)" % VERSION)
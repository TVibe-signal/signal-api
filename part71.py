# ---------- v2.51.1: Nightly Self-Reflection Report ----------
VERSION = "2.51.1"
app.version = VERSION
app.openapi_schema = None

import json
import time
from fastapi.responses import HTMLResponse, PlainTextResponse

REPORT_KEY = "si:report:latest"
REPORT_HISTORY = "si:report:history"
_last_report_ts = 0
REPORT_INTERVAL = 20 * 3600  # \~ daily, triggered opportunistically

async def build_si_report(client) -> dict:
    report = {
        "ts": int(time.time()),
        "date": time.strftime("%Y-%m-%d", time.gmtime()),
        "headline": "SI daily reflection",
        "sections": {},
    }
    try:
        if "get_regime" in globals():
            report["sections"]["regime"] = await get_regime(client)
    except Exception:
        pass
    try:
        if "counterfactual_summary" in globals():
            report["sections"]["counterfactual"] = await counterfactual_summary(client)
    except Exception:
        pass
    try:
        if "get_debate_leaderboard" in globals():
            report["sections"]["debate"] = await get_debate_leaderboard(client)
    except Exception:
        pass
    try:
        if "_load_hypotheses" in globals():
            hy = await _load_hypotheses(client)
            report["sections"]["hypotheses"] = [
                {"id": h.get("id"), "status": h.get("status"), "n": h.get("n"), "bad": h.get("bad")}
                for h in (hy or [])[:8]
            ]
    except Exception:
        pass
    try:
        if PRED_ENABLED:
            raw = await redis_pipe(client, [["LRANGE", "evol:log", 0, 4]])
            logs = []
            for x in (raw or [[]])[0] or []:
                try:
                    logs.append(json.loads(x))
                except Exception:
                    pass
            report["sections"]["evolution"] = logs
    except Exception:
        pass

    # Short narrative
    reg = (report["sections"].get("regime") or {}).get("regime") or "unknown"
    cf = report["sections"].get("counterfactual") or {}
    help_pct = cf.get("avoid_would_help_pct")
    narrative = [
        f"Regime appears {reg}.",
    ]
    if help_pct is not None:
        narrative.append(
            f"Counterfactual: in {round(help_pct*100)}% of bad cases, an avoid verdict would have helped."
        )
    deb = report["sections"].get("debate") or {}
    if deb:
        best = sorted(
            [(k, v.get("accuracy"), v.get("n")) for k, v in deb.items() if v.get("accuracy") is not None],
            key=lambda x: (x[1] or 0),
            reverse=True,
        )
        if best:
            narrative.append(f"Leading debate persona: {best[0][0]} ({round((best[0][1] or 0)*100)}% on n={best[0][2]}).")
    report["narrative"] = " ".join(narrative)
    return report

async def maybe_write_report(client):
    global _last_report_ts
    now = time.time()
    if now - _last_report_ts < REPORT_INTERVAL:
        return None
    _last_report_ts = now
    report = await build_si_report(client)
    try:
        if PRED_ENABLED:
            await redis_pipe(client, [
                ["SET", REPORT_KEY, json.dumps(report), "EX", 7 * 86400],
                ["LPUSH", REPORT_HISTORY, json.dumps(report)],
                ["LTRIM", REPORT_HISTORY, 0, 13],
            ])
    except Exception:
        pass
    return report

@app.get("/si/report", tags=["product"])
async def si_report_json(request: Request):
    client = request.app.state.client
    raw = None
    try:
        if PRED_ENABLED:
            raw = await redis_get(client, REPORT_KEY)
    except Exception:
        pass
    if raw:
        return json.loads(raw)
    report = await build_si_report(client)
    return report

@app.get("/si/report/view", tags=["product"], response_class=HTMLResponse)
async def si_report_view(request: Request):
    data = await si_report_json(request)
    narrative = data.get("narrative") or ""
    sections = data.get("sections") or {}
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>SI Daily Reflection</title>
<style>
 body{{margin:0;background:#07090f;color:#e8eef9;font-family:system-ui,sans-serif}}
 .w{{max-width:800px;margin:0 auto;padding:32px 16px}}
 h1{{font-size:1.6rem;margin:0 0 8px}}
 .muted{{color:#8b98b0}}
 .card{{background:#0e121b;border:1px solid #1c2433;border-radius:14px;padding:16px;margin:14px 0}}
 pre{{white-space:pre-wrap;word-break:break-word;font-size:12px;color:#cbd5e1}}
 a{{color:#5ce1ff}}
</style></head><body><div class="w">
<div class="muted">TVibex402 · SI Reflection</div>
<h1>Daily Self-Reflection</h1>
<p class="muted">{data.get("date") or ""} UTC</p>
<div class="card"><strong>Narrative</strong><p>{narrative}</p></div>
<div class="card"><strong>Raw sections</strong><pre>{json.dumps(sections, indent=2)}</pre></div>
<p class="muted"><a href="/si">Command Center</a> · <a href="/si/report">JSON</a></p>
</div></body></html>"""
    return HTMLResponse(html)

# Opportunistic trigger on signal traffic (very low frequency)
_build_prev_report = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_report(client, mint, security, prefetched)
    try:
        await maybe_write_report(client)
    except Exception:
        pass
    return result, status

print(f"[part71] v{VERSION} Nightly Self-Reflection Report loaded")
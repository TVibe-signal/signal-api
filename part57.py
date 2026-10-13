# ---------- v2.43: Self-Improving Signal Loop + Evolution Dashboard ----------
VERSION = "2.43.0"
app.version = VERSION
app.openapi_schema = None

import os
import json
import time
from typing import Dict, Any, List
from fastapi.responses import HTMLResponse

# Feature flags
SELF_IMPROVE = os.getenv("SELF_IMPROVE", "true").lower() in ("1", "true", "yes")
SELF_APPLY = os.getenv("SELF_APPLY", "false").lower() in ("1", "true", "yes")

# Safety limits
MIN_SAMPLES_FLAG = 40
MIN_TOTAL_JUDGED = 200
MAX_WEIGHT_CHANGE = 6
WEIGHT_FLOOR = 0
WEIGHT_CEILING = 45

EVOL_LOG_KEY = "evol:log"
EVOL_INTERVAL = 6 * 3600
_last_evol = 0

async def _get_flag_performance(client) -> Dict[str, Dict]:
    """Fetch current performance of each flag from track-record stats."""
    if not PRED_ENABLED:
        return {}
    try:
        raw = await redis_pipe(client, [["HGETALL", "st"]])
        st = to_dict((raw or [{}])[0] or {})
        perf = {}
        for k, v in st.items():
            if k.startswith("f:") and k.endswith(":n"):
                flag = k[2:-2]
                n = int(v or 0)
                bad = int(st.get(f"f:{flag}:bad", 0))
                if n >= 5:
                    perf[flag] = {
                        "n": n,
                        "bad": bad,
                        "bad_rate": round(bad / n, 3) if n else 0.0,
                    }
        return perf
    except Exception:
        return {}

async def _propose_adjustments(client) -> List[Dict]:
    """Propose weight changes based on flag performance."""
    if not SELF_IMPROVE:
        return []

    perf = await _get_flag_performance(client)
    if not perf:
        return []

    proposals = []
    current_weights = dict(RISK_WEIGHTS) if "RISK_WEIGHTS" in globals() else {}

    for flag, data in perf.items():
        if data["n"] < MIN_SAMPLES_FLAG:
            continue

        rate = data["bad_rate"]
        old_w = current_weights.get(flag, 0)
        new_w = old_w
        reason = ""

        if rate >= 0.75 and old_w < WEIGHT_CEILING:
            delta = min(MAX_WEIGHT_CHANGE, 4)
            new_w = min(WEIGHT_CEILING, old_w + delta)
            reason = f"high bad_rate {rate:.2f} → increase"
        elif rate <= 0.35 and old_w > WEIGHT_FLOOR:
            delta = min(MAX_WEIGHT_CHANGE, 3)
            new_w = max(WEIGHT_FLOOR, old_w - delta)
            reason = f"low bad_rate {rate:.2f} → decrease"

        if new_w != old_w:
            proposals.append({
                "flag": flag,
                "old_weight": old_w,
                "new_weight": new_w,
                "n": data["n"],
                "bad_rate": rate,
                "reason": reason,
            })

    return proposals

async def _apply_proposals(client, proposals: List[Dict]) -> bool:
    """Apply proposals only when SELF_APPLY is enabled."""
    if not SELF_APPLY or not proposals:
        return False
    try:
        entry = {
            "ts": int(time.time()),
            "applied": True,
            "changes": proposals,
        }
        await redis_pipe(client, [
            ["LPUSH", EVOL_LOG_KEY, json.dumps(entry)],
            ["LTRIM", EVOL_LOG_KEY, 0, 49],
        ])
        for p in proposals:
            if p["flag"] in RISK_WEIGHTS:
                RISK_WEIGHTS[p["flag"]] = p["new_weight"]
        return True
    except Exception:
        return False

async def run_self_improve(client) -> Dict[str, Any]:
    """Run one self-improvement cycle."""
    if not SELF_IMPROVE:
        return {"status": "disabled"}

    proposals = await _propose_adjustments(client)
    applied = False

    if proposals and SELF_APPLY:
        applied = await _apply_proposals(client, proposals)
    elif proposals:
        entry = {
            "ts": int(time.time()),
            "applied": False,
            "changes": proposals,
        }
        await redis_pipe(client, [
            ["LPUSH", EVOL_LOG_KEY, json.dumps(entry)],
            ["LTRIM", EVOL_LOG_KEY, 0, 49],
        ])

    return {
        "status": "ok",
        "proposals": len(proposals),
        "applied": applied,
        "details": proposals[:8],
    }

@app.get("/evolution", tags=["experimental"])
async def evolution_log(request: Request, limit: int = 10):
    """Return recent evolution events as JSON."""
    if not PRED_ENABLED:
        return {"enabled": False, "logs": []}
    client = request.app.state.client
    res = await redis_pipe(client, [["LRANGE", EVOL_LOG_KEY, 0, max(1, min(limit, 30)) - 1]])
    logs = []
    for raw in (res or [[]])[0] or []:
        try:
            logs.append(json.loads(raw))
        except Exception:
            continue
    return {
        "self_improve": SELF_IMPROVE,
        "self_apply": SELF_APPLY,
        "logs": logs,
    }

@app.get("/evolution/view", tags=["experimental"], response_class=HTMLResponse)
async def evolution_dashboard(request: Request):
    """Simple HTML dashboard for the evolution log."""
    client = request.app.state.client
    logs = []
    try:
        if PRED_ENABLED:
            res = await redis_pipe(client, [["LRANGE", EVOL_LOG_KEY, 0, 19]])
            for raw in (res or [[]])[0] or []:
                try:
                    logs.append(json.loads(raw))
                except Exception:
                    continue
    except Exception:
        pass

    rows = ""
    for entry in logs:
        ts = time.strftime("%Y-%m-%d %H:%M", time.gmtime(entry.get("ts", 0)))
        applied = "APPLIED" if entry.get("applied") else "proposal only"
        changes = entry.get("changes") or []
        detail = "<br>".join(
            f"{c['flag']}: {c['old_weight']} → {c['new_weight']} "
            f"(n={c['n']}, bad_rate={c['bad_rate']}) — {c['reason']}"
            for c in changes
        ) or "—"
        rows += f"""
        <tr>
            <td>{ts}</td>
            <td>{applied}</td>
            <td style="text-align:left;font-size:13px">{detail}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>TVibex402 — Evolution Log</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 960px; margin: 40px auto; padding: 0 16px; background: #0f1115; color: #e6e8ec; }}
    h1 {{ font-size: 1.5rem; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 24px; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #2a2e38; }}
    th {{ text-align: left; color: #9aa3b2; font-weight: 500; }}
    .badge {{ display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 12px; }}
    .on {{ background: #143d2a; color: #3dd68c; }}
    .off {{ background: #3d1a1a; color: #f87171; }}
  </style>
</head>
<body>
  <h1>Self-Improving Evolution Log</h1>
  <p>
    Self-Improve: <span class="badge {'on' if SELF_IMPROVE else 'off'}">{'ON' if SELF_IMPROVE else 'OFF'}</span>
    &nbsp; Auto-Apply: <span class="badge {'on' if SELF_APPLY else 'off'}">{'ON' if SELF_APPLY else 'OFF'}</span>
  </p>
  <p style="color:#9aa3b2;font-size:14px;">
    Only proposals with enough samples are shown. Weight changes are limited for safety.
  </p>
  <table>
    <thead>
      <tr>
        <th>Time (UTC)</th>
        <th>Status</th>
        <th>Proposed Changes</th>
      </tr>
    </thead>
    <tbody>
      {rows or '<tr><td colspan="3">No evolution events yet.</td></tr>'}
    </tbody>
  </table>
</body>
</html>"""
    return HTMLResponse(html)

# Periodically trigger self-improve (very low frequency)
_build_prev_evol = build_signal

async def build_signal(client, mint, security, prefetched=None):
    global _last_evol
    result, status = await _build_prev_evol(client, mint, security, prefetched)
    try:
        now = time.time()
        if SELF_IMPROVE and now - _last_evol > EVOL_INTERVAL:
            _last_evol = now
            await run_self_improve(client)
    except Exception:
        pass
    return result, status

print(f"[part57] v{VERSION} Self-Improving Loop + Evolution Dashboard loaded")
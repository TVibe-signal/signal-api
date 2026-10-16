# ---------- v2.67: Offline feature export (JSONL) for LightGBM later ----------
VERSION = "2.67.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Any, Dict, List, Optional

EXPORT_BUF = "si:export:buf"       # list of recent feature rows
EXPORT_MAX = 2000
EXPORT_TTL = 14 * 86400


def _feature_row(mint: str, result: dict) -> Optional[dict]:
    if not isinstance(result, dict):
        return None
    dec = result.get("decision") or {}
    dq = result.get("data_quality") or {}
    tr = result.get("track_record_context") or {}
    ar = result.get("attention_residuals") or {}
    flags = result.get("flags") or []
    return {
        "ts": int(time.time()),
        "mint": mint,
        "verdict": dec.get("verdict") or result.get("verdict"),
        "risk_score": result.get("risk_score"),
        "liquidity_usd": result.get("liquidity_usd"),
        "pair_age_minutes": result.get("pair_age_minutes"),
        "data_confidence": dq.get("data_confidence") or dec.get("confidence"),
        "track_n": tr.get("n"),
        "track_bad_rate": tr.get("bad_outcome_rate"),
        "residual_verdict": ar.get("residual_verdict"),
        "alpha": ar.get("alpha"),
        "flags": flags[:20],
        "label": None,  # filled offline when outcome known
    }


async def _export_push(client, row: dict) -> None:
    if not PRED_ENABLED or not client or not row:
        return
    try:
        await redis_pipe(client, [
            ["LPUSH", EXPORT_BUF, json.dumps(row, separators=(",", ":"), default=str)],
            ["LTRIM", EXPORT_BUF, 0, EXPORT_MAX - 1],
            ["EXPIRE", EXPORT_BUF, EXPORT_TTL],
        ])
    except Exception:
        pass


_build_prev_exp = build_signal


async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_exp(client, mint, security, prefetched)
    try:
        if isinstance(result, dict):
            row = _feature_row(mint, result)
            if row:
                await _export_push(client, row)
    except Exception:
        pass
    return result, status


@app.get("/export/features", tags=["operator"], include_in_schema=False)
async def export_features(request: Request, limit: int = 200):
    """
    Soft operator dump: recent feature rows as JSONL-ready list.
    Protect with X-API-Key / OPERATOR_SECRET if configured.
    """
    # soft-gate if project has it
    gate = globals().get("require_operator") or globals().get("soft_gate_operator")
    if callable(gate):
        try:
            await gate(request)
        except Exception:
            pass
    client = request.app.state.client
    limit = max(1, min(int(limit or 200), 500))
    if not PRED_ENABLED or not client:
        return {"ok": False, "rows": []}
    try:
        res = await redis_pipe(client, [["LRANGE", EXPORT_BUF, 0, limit - 1]])
        rows = []
        for raw in (res or [[]])[0] or []:
            try:
                rows.append(json.loads(raw))
            except Exception:
                continue
        return {"ok": True, "n": len(rows), "rows": rows, "version": VERSION,
                "note": "Join with /stats outcomes offline to set label; then train LightGBM locally."}
    except Exception as e:
        return {"ok": False, "error": str(e)[:120], "rows": []}


print(f"[part89] v{VERSION} offline feature export → GET /export/features")
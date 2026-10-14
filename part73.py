# ---------- v2.53: SI Event Log (Soft Event Sourcing) ----------
VERSION = "2.53.0"
app.version = VERSION
app.openapi_schema = None

import json
import time
from typing import Any, Dict, List, Optional

# Streams (Redis Lists as append-only logs)
EV_GLOBAL = "si:ev:global"          # all events (trimmed)
EV_MINT = "si:ev:mint:{}"           # per-mint stream
EV_META = "si:ev:meta"              # counters
EV_GLOBAL_MAX = 500
EV_MINT_MAX = 80
EV_TTL = 45 * 86400

# Event types (convention)
# signal_seen, verdict_emitted, outcome_judged, community_shift,
# regime_changed, evolution_proposed, hypothesis_updated,
# feedback_received, entity_refreshed, attention_trap, genetic_risk

def _ev(kind: str, mint: Optional[str] = None, payload: Optional[dict] = None) -> dict:
    return {
        "ts": int(time.time()),
        "kind": kind,
        "mint": mint,
        "payload": payload or {},
        "v": 1,
    }

async def si_emit(client, kind: str, mint: Optional[str] = None, payload: Optional[dict] = None) -> bool:
    """Append one event to global + optional per-mint stream."""
    if not PRED_ENABLED or not client:
        return False
    try:
        event = _ev(kind, mint, payload)
        raw
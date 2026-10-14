# ---------- v2.41.1: Community polish (English summary) ----------
VERSION = "2.41.1"
app.version = VERSION
app.openapi_schema = None

def _community_summary(attn: dict, conv: dict) -> str:
    """Create a short human-readable community summary in English."""
    parts = []

    a24 = attn.get("24h", 0)
    if a24 >= 15:
        parts.append(f"high attention ({a24} queries/24h)")
    elif a24 >= 5:
        parts.append(f"some attention ({a24} queries/24h)")

    n = conv.get("n", 0)
    if n >= 5:
        dom = conv.get("dominant")
        avoid = conv.get("avoid_pct", 0)
        ok = conv.get("ok_pct", 0)

        if dom == "avoid" and avoid >= 50:
            parts.append(f"community leans avoid ({avoid}%)")
        elif dom == "ok":
            parts.append(f"community mostly ok ({ok}%)")
        else:
            parts.append(f"mixed community signals (n={n})")

    return "; ".join(parts) if parts else ""

def _ensure_community_summary(result: dict):
    """Ensure the community object has a clean English summary."""
    comm = result.get("community")
    if not comm:
        return

    attn = comm.get("attention") or {}
    conv = comm.get("conviction") or {}
    summary = _community_summary(attn, conv)

    if summary:
        comm["summary"] = summary
    else:
        comm.pop("summary", None)

# Override build_signal to always apply English summary
_build_prev_comm = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_comm(client, mint, security, prefetched)
    try:
        _ensure_community_summary(result)
    except Exception:
        pass
    return result, status

# Optional: keep llms.txt update
if "LLMS_TXT" in globals():
    LLMS_TXT += """

## Community context
Every signal may include a `community` object when enough data exists:
- attention: how many times the mint was queried in 1h / 6h / 24h
- conviction: distribution of recent verdicts (ok / caution / avoid %) + dominant
- summary: short human-readable English sentence

Use community as extra context only. It is not financial advice.
"""

print(f"[part54] v{VERSION} Community polish (English summary) loaded")
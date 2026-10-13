# ---------- v2.41: Community polish + better agent docs ----------
VERSION = "2.41.1"
app.version = VERSION
app.openapi_schema = None

# Đảm bảo community summary luôn có (nếu part49 cũ chưa có)
def _ensure_community_summary(result: dict):
    comm = result.get("community")
    if not comm or comm.get("summary"):
        return
    attn = comm.get("attention") or {}
    conv = comm.get("conviction") or {}
    parts = []
    a24 = attn.get("24h", 0)
    if a24 >= 15:
        parts.append(f"high attention ({a24}/24h)")
    elif a24 >= 5:
        parts.append(f"some attention ({a24}/24h)")
    n = conv.get("n", 0)
    if n >= 5:
        dom = conv.get("dominant")
        if dom == "avoid" and conv.get("avoid_pct", 0) >= 50:
            parts.append(f"community leans avoid ({conv.get('avoid_pct')}%)")
        elif dom == "ok":
            parts.append(f"community mostly ok ({conv.get('ok_pct')}%)")
        else:
            parts.append(f"mixed community (n={n})")
    if parts:
        comm["summary"] = "; ".join(parts)

_build_prev_comm = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_comm(client, mint, security, prefetched)
    try:
        _ensure_community_summary(result)
    except Exception:
        pass
    return result, status

# Cải thiện llms.txt
if "LLMS_TXT" in globals():
    LLMS_TXT += """

## Community context (Network Effects)
Every /signal may include a `community` object when enough data exists:
- attention: how many times this mint was queried in 1h / 6h / 24h
- conviction: distribution of recent verdicts (ok / caution / avoid %) + dominant
- summary: short human-readable sentence

Use it as additional context, not as the main decision. More queries → better community signal over time.
"""
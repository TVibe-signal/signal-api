# ---------- v2.44: Multi-Agent Debate Layer ----------
VERSION = "2.44.0"
app.version = VERSION
app.openapi_schema = None

from typing import Dict, Any, List

def _persona_conservative(signal: dict) -> Dict[str, Any]:
    """Prioritizes safety and downside protection."""
    risk = float(signal.get("risk_score") or 50)
    verdict = (signal.get("decision") or {}).get("verdict") or signal.get("verdict")
    flags = signal.get("flags") or []

    score = risk
    if "very_low_liquidity" in flags or "brand_new_pair" in flags:
        score += 12
    if verdict == "avoid":
        score += 8

    final = "avoid" if score >= 55 else ("caution" if score >= 28 else "ok")
    return {
        "persona": "conservative",
        "verdict": final,
        "confidence": 0.75,
        "reason": "Emphasizes liquidity, age and existing avoid flags",
    }

def _persona_aggressive(signal: dict) -> Dict[str, Any]:
    """Looks for opportunity and tolerates more risk."""
    risk = float(signal.get("risk_score") or 50)
    conv = (signal.get("community") or {}).get("conviction") or {}
    attention = (signal.get("community") or {}).get("attention") or {}

    score = risk * 0.7
    if conv.get("ok_pct", 0) >= 55:
        score -= 10
    if attention.get("24h", 0) >= 20:
        score -= 6

    final = "avoid" if score >= 65 else ("caution" if score >= 35 else "ok")
    return {
        "persona": "aggressive",
        "verdict": final,
        "confidence": 0.65,
        "reason": "Gives more weight to community interest and upside potential",
    }

def _persona_community(signal: dict) -> Dict[str, Any]:
    """Follows recent community conviction."""
    conv = (signal.get("community") or {}).get("conviction") or {}
    n = conv.get("n", 0)
    if n < 4:
        return {
            "persona": "community",
            "verdict": "caution",
            "confidence": 0.40,
            "reason": "Not enough community data yet",
        }

    dominant = conv.get("dominant", "caution")
    return {
        "persona": "community",
        "verdict": dominant,
        "confidence": min(0.85, 0.45 + n * 0.02),
        "reason": f"Based on {n} recent community verdicts (dominant={dominant})",
    }

def _persona_historical(signal: dict) -> Dict[str, Any]:
    """Uses track-record context when available."""
    ctx = signal.get("track_record_context") or {}
    n = ctx.get("n", 0)
    bad_rate = ctx.get("bad_outcome_rate")
    if n < 15 or bad_rate is None:
        return {
            "persona": "historical",
            "verdict": "caution",
            "confidence": 0.35,
            "reason": "Insufficient historical samples",
        }

    if bad_rate >= 0.55:
        verdict = "avoid"
    elif bad_rate <= 0.25:
        verdict = "ok"
    else:
        verdict = "caution"

    return {
        "persona": "historical",
        "verdict": verdict,
        "confidence": min(0.80, 0.40 + n * 0.01),
        "reason": f"Historical bad-outcome rate {bad_rate:.2f} from {n} similar cases",
    }

def run_debate(signal: dict) -> Dict[str, Any]:
    """Run all personas and produce a meta-verdict."""
    personas = [
        _persona_conservative(signal),
        _persona_aggressive(signal),
        _persona_community(signal),
        _persona_historical(signal),
    ]

    votes = {"ok": 0.0, "caution": 0.0, "avoid": 0.0}
    for p in personas:
        votes[p["verdict"]] += p["confidence"]

    meta = max(votes, key=votes.get)
    total = sum(votes.values()) or 1.0
    agreement = votes[meta] / total

    return {
        "meta_verdict": meta,
        "agreement": round(agreement, 2),
        "votes": {k: round(v, 2) for k, v in votes.items()},
        "personas": personas,
    }

# Attach debate result to every signal
_build_prev_debate = build_signal

async def build_signal(client, mint, security, prefetched=None):
    result, status = await _build_prev_debate(client, mint, security, prefetched)

    try:
        debate = run_debate(result)
        result["debate"] = debate

        if debate["agreement"] >= 0.70:
            decision = dict(result.get("decision") or {})
            unknowns = list(decision.get("unknowns") or [])
            note = f"Debate consensus: {debate['meta_verdict']} (agreement {debate['agreement']})"
            if note not in unknowns:
                unknowns.append(note)
            decision["unknowns"] = unknowns
            result["decision"] = decision
    except Exception:
        pass

    return result, status

# ---------- MCP tool ----------
def _register_debate_tool():
    try:
        if "mcp_server" not in globals() or mcp_server is None:
            return

        @mcp_server.tool()
        async def get_debate(mint: str) -> dict:
            """Run multi-agent debate on a token and return the meta-verdict."""
            sig, _ = await build_signal(app.state.client, mint, True)
            return {
                "mint": mint,
                "debate": sig.get("debate"),
                "verdict": (sig.get("decision") or {}).get("verdict"),
                "risk_score": sig.get("risk_score"),
            }
    except Exception as e:
        print(f"[part59] MCP tool registration skipped: {e}")

# Delay registration slightly so MCP is ready
try:
    import asyncio
    asyncio.get_event_loop().call_later(3, _register_debate_tool)
except Exception:
    _register_debate_tool()

print(f"[part59] v{VERSION} Multi-Agent Debate Layer loaded")
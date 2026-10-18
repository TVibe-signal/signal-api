# ---------- v2.78: Shadow outcome wire + fair-use + donate (reviewed) ----------
# B: after resolve_due, feed judged labels into on_outcome_for_si (shadow-avoid etc.)
#    - only ids that really left the "due" set, labelled once (SET NX guard)
#    - a failed/untrusted DexScreener answer NEVER becomes "bad": it is retried instead
#    - set P100_WIRE=0 to switch B off (use that if /stats/shadow-avoid judged already grows)
# C: fair-use copy on /support + /donate (free instance; optional SOL tips)
VERSION = "2.78.0"
app.version = VERSION
app.openapi_schema = None

import asyncio
import os
import time
from typing import Dict, Optional

from fastapi.responses import HTMLResponse, PlainTextResponse

# --- Public free-host tips (optional). Not required to use the API. ---
DONATE_SOL = "3iAVBvE4aU4A5DTKCqzu6jg79UfW6aEnqUD1pjfew18n"
DONATE_NOTE = (
    "TVibex402 is free and open source. If the public instance helps your agents, "
    "you can tip SOL to cover Render/RPC. Never required."
)
FAIR_USE_RPM = os.environ.get("FAIR_USE_RPM", "30")  # keep equal to the real limiter

# ---------------------------------------------------------------------------
# B) Wire outcomes into shadow + SI hooks
# ---------------------------------------------------------------------------
P100_WIRE = os.environ.get("P100_WIRE", "1").lower() not in ("0", "false", "off")
_P100_LABEL_TTL = 7 * 86400
_P100_RETRY: list = []  # [(snapshot, attempts)] when DexScreener could not be trusted
_SOL_DEFAULT = "So11111111111111111111111111111111111111112"


def _p100_val(x):
    return x.get("result") if isinstance(x, dict) else x


def _p100_pair(pairs, mint):
    cand = [p for p in pairs if (p.get("baseToken") or {}).get("address") == mint]
    if not cand:
        return None
    fn = globals().get("pick_best_pair")
    if callable(fn):
        try:
            return fn(cand, mint)
        except Exception:
            pass
    return max(cand, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))


async def _p100_fetch(client, mints, sol) -> Optional[Dict[str, Optional[dict]]]:
    """{mint: pair or None} only when the answer is trustworthy, else None.
    SOL rides along as a canary: if its pair is missing the answer is a rate limit /
    partial reply, not proof that a token's pair is gone."""
    out: Dict[str, Optional[dict]] = {}
    for i in range(0, len(mints), 29):
        chunk = mints[i:i + 29]
        ask = chunk if sol in chunk else chunk + [sol]
        try:
            r = await client.get("https://api.dexscreener.com/latest/dex/tokens/" + ",".join(ask))
            if r.status_code != 200:
                return None
            pairs = (r.json() or {}).get("pairs") or []
        except Exception:
            return None
        if _p100_pair(pairs, sol) is None:
            return None
        for m in chunk:
            out[m] = _p100_pair(pairs, m)
    return out


_prev_resolve_due = resolve_due


async def resolve_due(client: "httpx.AsyncClient") -> int:
    if not P100_WIRE:
        return await _prev_resolve_due(client)
    snaps = []
    try:
        batch = int(globals().get("RESOLVE_BATCH") or 20)
        lim = min(max(batch * 2, 60), 150)
        got = await redis_pipe(client, [["ZRANGEBYSCORE", "due", "-inf", int(time.time()), "LIMIT", 0, lim]])
        ids = (got or [[]])[0] or []
        if ids:
            hashes = await redis_pipe(client, [["HGETALL", f"pred:{i}"] for i in ids])
            for i, h in zip(ids, hashes or []):
                d = to_dict(h)
                if d.get("mint"):
                    d["_id"] = i
                    snaps.append(d)
    except Exception as e:
        print(f"[part100] pre-resolve snap: {e}")

    n = await _prev_resolve_due(client)

    try:
        work = [(d, 0) for d in snaps]
        if snaps:  # keep only what the core resolver really took out of "due"
            left = await redis_pipe(client, [["ZSCORE", "due", d["_id"]] for d in snaps])
            if left and len(left) == len(snaps):
                work = [(d, 0) for d, z in zip(snaps, left) if _p100_val(z) is None]
            else:
                work = []
        work += _P100_RETRY
        _P100_RETRY.clear()
        if not work:
            return n

        horizon = int(globals().get("PRED_HORIZON_S") or 86400)
        now = int(time.time())
        work = [(d, a) for d, a in work if now - int(d.get("ts") or 0) <= horizon * 3]
        mints = sorted({d["mint"] for d, _ in work})
        if not mints:
            return n
        best = await _p100_fetch(client, mints, globals().get("SOL_MINT") or _SOL_DEFAULT)
        if best is None:
            for d, a in work:
                if a < 5 and len(_P100_RETRY) < 300:
                    _P100_RETRY.append((d, a + 1))
            print(f"[part100] label fetch untrusted, {len(work)} snapshot(s) queued for retry")
            return n

        bad_ret = float(globals().get("BAD_RETURN_PCT") or -50)
        bad_liq = float(globals().get("BAD_LIQ_RATIO") or 0.3)
        fn = globals().get("on_outcome_for_si")
        sa = globals().get("shadow_avoid_on_outcome")
        for d, _ in work:
            mint = d["mint"]
            guard = await redis_pipe(client, [["SET", f"si:lab:{d['_id']}", 1, "NX", "EX", _P100_LABEL_TTL]])
            if not (guard and _p100_val(guard[0])):
                continue  # this prediction was already labelled
            p0, l0 = float(d.get("price") or 0), float(d.get("liq") or 0)
            pair = best.get(mint)
            if pair is None:
                ret, liq_ratio = -100.0, 0.0
            else:
                try:
                    p1 = float(pair.get("priceUsd") or 0)
                    l1 = float((pair.get("liquidity") or {}).get("usd") or 0)
                except (TypeError, ValueError):
                    p1, l1 = 0.0, 0.0
                ret = (p1 / p0 - 1) * 100 if p0 > 0 else 0.0
                liq_ratio = l1 / l0 if l0 > 0 else 1.0
            bad = bool(ret <= bad_ret or liq_ratio <= bad_liq)
            meta = {"source": "part100_resolve"}
            try:
                if callable(fn):  # part93 wrapper already calls shadow_avoid_on_outcome
                    try:
                        await fn(client, mint, bad, meta)
                    except TypeError:
                        await fn(client, mint, bad)
                elif callable(sa):
                    await sa(client, mint, bad, meta)
            except Exception as e:
                print(f"[part100] outcome hook: {e}")
    except Exception as e:
        print(f"[part100] post-resolve labels: {e}")
    return n


# ---------------------------------------------------------------------------
# C) Fair use + donate (free product)
# ---------------------------------------------------------------------------
FAIR_USE = """
TVibex402 public instance — FREE, fair use
• About """ + FAIR_USE_RPM + """ requests/minute without a key (429 if exceeded)
• /signals batch: max 10 mints per call
• Cache the same mint 15–30s on the client
• Prefer GET /omni once over polling many small routes
• Heavy use: self-host from GitHub (track-record starts empty on your Redis)
• Not financial advice. Heuristics only.

Optional tips (never required) keep the public host online:
  SOL: """ + DONATE_SOL + """
"""


@app.get("/support", response_class=PlainTextResponse, tags=["product"])
async def support_fair_use():
    return FAIR_USE.strip() + "\n"


@app.get("/donate", tags=["product"])
async def donate_json():
    return {
        "free": True,
        "required": False,
        "asset": "SOL",
        "address": DONATE_SOL,
        "note": DONATE_NOTE,
        "fair_use": "/support",
        "self_host": "https://github.com/TVibex402/signal-api",
        "disclaimer": "Not financial advice. Donations are voluntary tips for hosting/RPC only.",
        "version": VERSION,
    }


@app.get("/donate.html", response_class=HTMLResponse, tags=["product"], include_in_schema=False)
async def donate_html():
    return f"""<!doctype html><html lang="en"><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>TVibex402 — free & tips</title>
<style>
body{{margin:0;font-family:system-ui,sans-serif;background:#070b12;color:#e8eef6;line-height:1.55}}
.wrap{{max-width:640px;margin:0 auto;padding:32px 16px}}
h1{{font-size:1.6rem;background:linear-gradient(120deg,#9945ff,#14f195);-webkit-background-clip:text;color:transparent}}
.card{{background:rgba(18,25,35,.85);border:1px solid rgba(34,48,66,.8);border-radius:14px;padding:18px;margin:16px 0}}
code{{word-break:break-all;color:#14f195}}
.muted{{color:#8b9bb4;font-size:.9rem}}
a{{color:#14f195}}
</style></head><body><div class=wrap>
<h1>Free for agents</h1>
<p class=muted>Open source · measured on <a href="/stats">/stats</a> · not financial advice.</p>
<div class=card>
<strong>Fair use</strong>
<pre style="white-space:pre-wrap;font-size:.85rem">{FAIR_USE.strip()}</pre>
</div>
<div class=card>
<strong>Optional SOL tip</strong>
<p class=muted>{DONATE_NOTE}</p>
<p><code>{DONATE_SOL}</code></p>
</div>
<p class=muted><a href="/agents">/agents</a> · <a href="/support">/support</a> ·
<a href="https://github.com/TVibex402/signal-api">GitHub</a></p>
</div></body></html>"""


# part94 already owns GET /agents/snippets (first registered wins), so replace that route.
if globals().get("AGENT_SNIPPETS"):
    if callable(globals().get("_drop_routes")):
        _drop_routes({"/agents/snippets"})

    @app.get("/agents/snippets", response_class=PlainTextResponse, tags=["product"])
    async def agents_snippets_v100():
        text = AGENT_SNIPPETS.rstrip()
        if "Fair use" not in text:
            text += (
                "\n\n## Fair use (public host)\n"
                f"Free. About {FAIR_USE_RPM} req/min. Batch max 10. Cache mint 15–30s. "
                "429 = slow down or self-host.\n"
                f"Optional SOL tip (never required): {DONATE_SOL}\n"
                "Not financial advice.\n"
            )
        return text


ENV_EXAMPLE = """# .env.example — copy to .env, never commit real secrets
REDIS_URL=
SOLANA_RPC_URL=
JUPITER_API_KEY=
OPERATOR_SECRET=
PRED_ENABLED=true
# Optional tuning
# SI_RES_TEMP=1.25
# SI_RES_RISK_FLOOR=0.18
# P98_ENABLED=1
# P100_WIRE=1
# FAIR_USE_RPM=30
"""


@app.get("/env.example", response_class=PlainTextResponse, tags=["product"], include_in_schema=False)
async def env_example_file():
    return ENV_EXAMPLE


print(f"[part100] v{VERSION} resolve_due→on_outcome (wire={'on' if P100_WIRE else 'off'}) · /support · /donate · /env.example")

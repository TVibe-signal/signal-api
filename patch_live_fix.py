"""patch_live_fix v33-solid — blank-proof homepage + stable /omni /play."""
from __future__ import annotations
import re
from typing import Any, Optional

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

# ---------- Beautiful solid homepage ----------
HOME = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#070b12">
<title>TVibe Signal — Solana risk gate for AI agents</title>
<meta name="description" content="Free Solana mint risk filter. One request → verdict + reasons. Measured in public. NFA.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #070b12;
  --card: rgba(15,22,34,.92);
  --line: rgba(40,56,78,.9);
  --text: #e8eef6;
  --muted: #8b9bb4;
  --green: #14f195;
  --purple: #9945ff;
  --cyan: #00f0ff;
  --rose: #ff4d8d;
  --amber: #ffd166;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: Inter, system-ui, -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.55;
  min-height: 100vh;
}
.bg {
  position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background:
    radial-gradient(ellipse 80% 50% at 20% -10%, rgba(153,69,255,.25), transparent),
    radial-gradient(ellipse 60% 40% at 90% 20%, rgba(20,241,149,.12), transparent);
}
.wrap { position: relative; z-index: 1; max-width: 720px; margin: 0 auto; padding: 32px 20px 80px; }
header { margin-bottom: 36px; }
.logo {
  font-weight: 700; font-size: 15px; letter-spacing: .04em;
  color: var(--cyan); margin-bottom: 18px;
}
h1 {
  font-size: clamp(28px, 5vw, 36px);
  font-weight: 700; line-height: 1.15;
  margin-bottom: 12px;
}
.sub { color: var(--muted); font-size: 15px; max-width: 520px; }
.card {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 24px;
  margin: 28px 0;
}
label { display: block; font-size: 13px; font-weight: 600; color: var(--muted); margin-bottom: 8px; }
input#mint {
  width: 100%;
  font-size: 16px;
  padding: 16px 18px;
  border-radius: 12px;
  border: 2px solid rgba(0,240,255,.35);
  background: #0b0f1a;
  color: #fff;
  font-family: "JetBrains Mono", monospace;
  outline: none;
  transition: border-color .15s;
}
input#mint:focus { border-color: var(--cyan); }
.btn-row { display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
button, .btn {
  font-family: Inter, sans-serif;
  font-weight: 600;
  font-size: 14px;
  padding: 12px 20px;
  border-radius: 10px;
  border: none;
  cursor: pointer;
  transition: opacity .15s;
}
button.primary { background: linear-gradient(90deg, var(--purple), var(--cyan)); color: #000; }
button.ghost, a.btn {
  background: transparent;
  border: 1px solid var(--line);
  color: var(--text);
  text-decoration: none;
  display: inline-flex; align-items: center;
}
button:hover, .btn:hover { opacity: .88; }
#out {
  margin-top: 20px;
  min-height: 48px;
  font-size: 15px;
  line-height: 1.5;
}
.badge {
  display: inline-block;
  padding: 5px 12px;
  font-weight: 700;
  font-size: 13px;
  border-radius: 6px;
  color: #000;
  margin-right: 8px;
}
.links {
  display: flex; flex-wrap: wrap; gap: 12px 20px;
  margin-top: 32px;
  font-size: 13px;
}
.links a { color: var(--muted); text-decoration: none; }
.links a:hover { color: var(--cyan); }
footer {
  margin-top: 48px;
  font-size: 12px;
  color: var(--muted);
  border-top: 1px solid var(--line);
  padding-top: 20px;
}
code { font-family: "JetBrains Mono", monospace; font-size: 12.5px; background: rgba(255,255,255,.06); padding: 2px 6px; border-radius: 4px; }
</style>
</head>
<body>
<div class="bg"></div>
<div class="wrap">
  <header>
    <div class="logo">TVIBE SIGNAL</div>
    <h1>Solana risk gate<br>for AI agents</h1>
    <p class="sub">One request → verdict, reasons, unknowns. Free · open source · measured on <a href="/stats" style="color:var(--cyan)">/stats</a>. Not financial advice.</p>
  </header>

  <div class="card">
    <label for="mint">Paste Solana mint address</label>
    <input id="mint" type="text" placeholder="So11111111111111111111111111111111111111112" spellcheck="false" autocomplete="off">
    <div class="btn-row">
      <button class="primary" onclick="check()">Check live</button>
      <button class="ghost" onclick="document.getElementById('mint').value='So11111111111111111111111111111111111111112';check()">Try SOL</button>
    </div>
    <div id="out"></div>
  </div>

  <div class="links">
    <a href="/omni?mint=So11111111111111111111111111111111111111112">/omni example</a>
    <a href="/stats">Public track record</a>
    <a href="/docs">API docs</a>
    <a href="/llms.txt">llms.txt</a>
    <a href="https://github.com/TVibe-signal/signal-api">GitHub</a>
  </div>

  <footer>
    Primary call: <code>GET /omni?mint=&lt;MINT&gt;&view=agent</code><br>
    NFA — pass / ok is a cleared risk gate, not a buy signal.
  </footer>
</div>

<script>
async function check(){
  const m = (document.getElementById('mint').value || '').trim();
  const out = document.getElementById('out');
  const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  if (!m) { out.innerHTML = '<span style="color:var(--rose)">Paste a mint first.</span>'; return; }
  if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(m)) {
    out.innerHTML = '<span style="color:var(--rose)">Not a valid Solana mint (32-44 base58).</span>'; return;
  }
  out.innerHTML = '<span style="color:var(--muted)">Checking…</span>';
  try {
    const r = await fetch('/omni?mint=' + encodeURIComponent(m), { cache: 'no-store' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      out.innerHTML = '<span style="color:var(--rose)">Error ' + r.status + '</span><br>' + esc(d.detail || d.error || 'Upstream issue');
      return;
    }
    const dec = d.decision || {};
    const raw = String(dec.verdict || d.verdict || d.action || '').toLowerCase();
    let label = '—', color = 'var(--cyan)';
    if (raw === 'ok' || raw === 'pass') { label = 'PASS'; color = 'var(--green)'; }
    else if (raw === 'caution' || raw === 'review') { label = 'REVIEW'; color = 'var(--amber)'; }
    else if (raw === 'avoid' || raw === 'skip') { label = 'SKIP'; color = 'var(--rose)'; }
    else { label = (raw || '—').toUpperCase(); }
    const risk = dec.risk_score ?? d.risk_score ?? '—';
    const liq = d.liquidity_usd != null ? Number(d.liquidity_usd).toLocaleString() : '—';
    out.innerHTML =
      '<span class="badge" style="background:' + color + '">' + esc(label) + '</span>' +
      '<b>Risk ' + esc(risk) + '</b> · Liq $' + esc(liq) +
      '<br><a href="/omni?mint=' + encodeURIComponent(m) + '" target="_blank" style="color:var(--cyan);font-size:13px;margin-top:8px;display:inline-block">Open full /omni JSON →</a>';
  } catch (e) {
    out.innerHTML = '<span style="color:var(--rose)">Network error — try again.</span>';
  }
}
// Enter key
document.getElementById('mint').addEventListener('keydown', e => { if (e.key === 'Enter') check(); });
</script>
</body>
</html>
"""

def _drop(app, path: str) -> None:
    try:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", None) != path]
    except Exception:
        pass

def _omni_handler(g):
    from fastapi import Query, Request, HTTPException
    from fastapi.responses import JSONResponse

    async def handler(
        request: Request,
        mint: Optional[str] = Query(None),
        request_param: Optional[str] = Query(None, alias="request"),
        view: str = Query("full"),
    ):
        m = (mint or request_param or request.query_params.get("mint") or "").strip()
        if not m:
            return JSONResponse({"error": "mint is required", "nfa": True}, status_code=400)
        if not MINT_RE.match(m):
            return JSONResponse({"error": "Invalid Solana mint", "mint": m, "nfa": True}, status_code=400)

        # rate limit best-effort
        try:
            rl = g.get("rate_limited")
            ipf = g.get("client_ip")
            if callable(rl) and callable(ipf):
                wait = rl(ipf(request), cost=4)
                if wait:
                    raise HTTPException(status_code=429, detail=f"rate limited, retry after {wait}s")
        except HTTPException:
            raise
        except Exception:
            pass

        client = getattr(request.app.state, "client", None)
        build = g.get("build_omni") or g.get("build_signal")
        if not callable(build):
            return JSONResponse({"mint": m, "error": "builder unavailable", "action": "skip", "nfa": True})

        try:
            if build.__name__ == "build_signal" or "build_signal" in str(build):
                pkt = await build(client, m, security=True)
            else:
                pkt = await build(client, m)
            if isinstance(pkt, tuple):
                pkt = pkt[0] if pkt else {}
            if not isinstance(pkt, dict):
                pkt = {"mint": m, "error": "bad packet", "nfa": True}
        except Exception as e:
            return JSONResponse({"mint": m, "error": str(e)[:200], "action": "skip", "nfa": True}, status_code=500)

        if (view or "").lower() in ("agent", "compact", "action"):
            av = g.get("_tvibe_agent_view")
            if callable(av):
                try:
                    return av(pkt)
                except Exception:
                    pass
            # minimal fallback agent view
            dec = pkt.get("decision") or {}
            verdict = str(dec.get("verdict") or pkt.get("verdict") or "caution").lower()
            action = "pass" if verdict in ("ok", "pass") else "skip" if verdict in ("avoid", "skip") else "review"
            return {
                "mint": m,
                "action": action,
                "verdict": verdict,
                "risk_score": dec.get("risk_score") or pkt.get("risk_score"),
                "filter": {"pass": action == "pass"},
                "unknowns": (dec.get("unknowns") or [])[:6],
                "nfa": True,
            }
        return pkt

    return handler

def apply(g: dict) -> None:
    if not isinstance(g, dict):
        raise TypeError("apply expects dict")
    app = g.get("app")
    if app is None:
        print("[patch_live_fix] no app — skip")
        return

    from fastapi.responses import HTMLResponse, PlainTextResponse

    # 1. Solid homepage — never empty
    _drop(app, "/")
    @app.get("/", tags=["product"], response_class=HTMLResponse, include_in_schema=False)
    async def home():
        return HTMLResponse(content=HOME, status_code=200)
    g["HOME_HTML"] = HOME
    print("[patch_live_fix] / solid homepage installed (v33)")

    # 2. Stable /omni + /play
    for path in ("/omni", "/play"):
        _drop(app, path)
        app.add_api_route(path, _omni_handler(g), methods=["GET"], tags=["product"])
    print("[patch_live_fix] /omni + /play replaced (v33)")

    # 3. Tiny status + agent helpers
    _drop(app, "/__main_status")
    @app.get("/__main_status", tags=["product"])
    async def main_status():
        return {
            "main_py": "loader",
            "patch_live_fix": "v33-solid",
            "homepage": "solid",
            "wrapper": "none",
        }

    _drop(app, "/agent.json")
    @app.get("/agent.json", tags=["product"])
    async def agent_json():
        return {
            "name": "TVibe Signal",
            "version": "v33-solid",
            "endpoints": {
                "check": "GET /omni?mint=<MINT>",
                "agent": "GET /omni?mint=<MINT>&view=agent",
                "play": "GET /play?mint=<MINT>",
            },
            "nfa": True,
        }

    print("[patch_live_fix] applied v33-solid — blank-proof")
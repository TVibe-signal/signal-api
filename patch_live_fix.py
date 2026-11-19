"""patch_live_fix v34-premium — world-class homepage + stable /omni /play."""
from __future__ import annotations
import re
from typing import Optional

MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")

# ---------- Premium homepage ----------
HOME = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#05060a">
<meta name="color-scheme" content="dark">
<title>TVibe Signal — Solana risk gate for AI agents</title>
<meta name="description" content="Free Solana mint risk filter. One request → verdict, reasons, unknowns. Measured in public. NFA.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #05060a;
  --surface: #0c0f17;
  --surface2: #111522;
  --border: rgba(255,255,255,0.08);
  --border-hover: rgba(255,255,255,0.16);
  --text: #f1f3f9;
  --muted: #8b95a8;
  --dim: #5c667a;
  --green: #14f195;
  --green-dim: rgba(20,241,149,0.12);
  --purple: #9945ff;
  --cyan: #00e8ff;
  --amber: #ffc14d;
  --rose: #ff4d6a;
  --radius: 14px;
  --radius-sm: 10px;
}
*,*::before,*::after { box-sizing: border-box; margin: 0; padding: 0; }
html { -webkit-text-size-adjust: 100%; }
body {
  font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  background: var(--bg);
  color: var(--text);
  line-height: 1.55;
  min-height: 100dvh;
  -webkit-font-smoothing: antialiased;
}
/* ambient glow */
.ambient {
  position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background:
    radial-gradient(ellipse 90% 60% at 15% -15%, rgba(153,69,255,0.22), transparent 55%),
    radial-gradient(ellipse 70% 50% at 95% 10%, rgba(0,232,255,0.08), transparent 50%),
    radial-gradient(ellipse 50% 40% at 50% 110%, rgba(20,241,149,0.06), transparent 50%);
}
.shell {
  position: relative; z-index: 1;
  max-width: 680px;
  margin: 0 auto;
  padding: 28px 18px 64px;
}
/* header */
.brand {
  display: flex; align-items: center; gap: 10px;
  margin-bottom: 32px;
}
.brand-mark {
  width: 28px; height: 28px;
  border-radius: 8px;
  background: linear-gradient(135deg, var(--purple), var(--cyan));
  display: grid; place-items: center;
  font-weight: 700; font-size: 13px; color: #000;
  letter-spacing: -0.02em;
}
.brand-name {
  font-size: 14px; font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--muted);
  text-transform: uppercase;
}
h1 {
  font-size: clamp(26px, 6vw, 34px);
  font-weight: 700;
  line-height: 1.18;
  letter-spacing: -0.025em;
  margin-bottom: 10px;
}
.lead {
  font-size: 15px;
  color: var(--muted);
  max-width: 480px;
  margin-bottom: 28px;
}
.lead a { color: var(--cyan); text-decoration: none; }
.lead a:hover { text-decoration: underline; }

/* card */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 22px;
  margin-bottom: 20px;
}
.card-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--dim);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 10px;
}
#mint {
  width: 100%;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 14.5px;
  font-weight: 500;
  padding: 15px 16px;
  border-radius: var(--radius-sm);
  border: 1.5px solid var(--border);
  background: var(--surface2);
  color: var(--text);
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
#mint::placeholder { color: var(--dim); }
#mint:focus {
  border-color: rgba(0,232,255,0.45);
  box-shadow: 0 0 0 3px rgba(0,232,255,0.1);
}
.actions {
  display: flex; gap: 10px; margin-top: 14px; flex-wrap: wrap;
}
.btn {
  font-family: inherit;
  font-size: 14px;
  font-weight: 600;
  padding: 11px 18px;
  border-radius: var(--radius-sm);
  border: none;
  cursor: pointer;
  transition: opacity 0.15s, transform 0.1s;
  display: inline-flex; align-items: center; gap: 6px;
}
.btn:active { transform: scale(0.98); }
.btn-primary {
  background: linear-gradient(135deg, #8b3dff 0%, #00d4ff 100%);
  color: #05060a;
}
.btn-ghost {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text);
}
.btn-ghost:hover { border-color: var(--border-hover); }
.btn:hover { opacity: 0.9; }

/* result */
#out {
  margin-top: 18px;
  min-height: 0;
  font-size: 14.5px;
}
#out:empty { display: none; }
.result {
  display: flex; flex-direction: column; gap: 10px;
  padding-top: 4px;
}
.badge {
  display: inline-flex; align-items: center;
  font-size: 12px; font-weight: 700;
  letter-spacing: 0.04em;
  padding: 5px 11px;
  border-radius: 6px;
  color: #05060a;
  width: fit-content;
}
.badge-pass { background: var(--green); }
.badge-review { background: var(--amber); }
.badge-skip { background: var(--rose); }
.badge-other { background: var(--cyan); }
.meta {
  color: var(--muted);
  font-size: 13.5px;
}
.meta b { color: var(--text); font-weight: 600; }
.raw-link {
  font-size: 13px;
  color: var(--cyan);
  text-decoration: none;
  margin-top: 2px;
}
.raw-link:hover { text-decoration: underline; }
.err { color: var(--rose); }
.loading { color: var(--dim); }

/* agent strip */
.agent-strip {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 18px;
  margin-bottom: 20px;
}
.agent-strip h2 {
  font-size: 12px;
  font-weight: 600;
  color: var(--dim);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 10px;
}
.agent-strip code {
  display: block;
  font-family: "JetBrains Mono", ui-monospace, monospace;
  font-size: 12.5px;
  font-weight: 500;
  color: var(--green);
  background: var(--green-dim);
  padding: 10px 12px;
  border-radius: 8px;
  overflow-x: auto;
  white-space: nowrap;
  margin-bottom: 8px;
}
.agent-strip p {
  font-size: 12.5px;
  color: var(--muted);
  line-height: 1.5;
}

/* nav links */
.nav {
  display: flex; flex-wrap: wrap; gap: 8px 16px;
  margin-bottom: 28px;
}
.nav a {
  font-size: 13px;
  color: var(--muted);
  text-decoration: none;
  transition: color 0.12s;
}
.nav a:hover { color: var(--cyan); }

/* footer */
footer {
  border-top: 1px solid var(--border);
  padding-top: 18px;
  font-size: 12px;
  color: var(--dim);
  line-height: 1.6;
}
footer strong { color: var(--muted); font-weight: 500; }

/* mobile polish */
@media (max-width: 480px) {
  .shell { padding: 22px 14px 56px; }
  h1 { font-size: 26px; }
  .card { padding: 18px; }
  #mint { font-size: 13.5px; padding: 14px; }
}
</style>
</head>
<body>
<div class="ambient" aria-hidden="true"></div>
<div class="shell">
  <div class="brand">
    <div class="brand-mark">T</div>
    <span class="brand-name">TVibe Signal</span>
  </div>

  <h1>Solana risk gate<br>for AI agents</h1>
  <p class="lead">
    One request → verdict, reasons & unknowns.
    Free · open source · measured on <a href="/stats">/stats</a>.
    Not financial advice.
  </p>

  <div class="card">
    <div class="card-label">Check a mint</div>
    <input id="mint" type="text" placeholder="Paste Solana mint address…" spellcheck="false" autocomplete="off" inputmode="text">
    <div class="actions">
      <button class="btn btn-primary" onclick="check()">Check live</button>
      <button class="btn btn-ghost" onclick="trySol()">Try SOL</button>
    </div>
    <div id="out" role="status" aria-live="polite"></div>
  </div>

  <div class="agent-strip">
    <h2>For agents</h2>
    <code>GET /omni?mint=&lt;MINT&gt;&view=agent</code>
    <p>
      Returns <strong style="color:var(--text)">action</strong> (pass | review | skip),
      filter.pass, risk_score, unknowns, valid_for_s.
      Non-empty unknowns → do not size. NFA.
    </p>
  </div>

  <nav class="nav">
    <a href="/omni?mint=So11111111111111111111111111111111111111112">/omni example</a>
    <a href="/stats">Track record</a>
    <a href="/docs">API docs</a>
    <a href="/llms.txt">llms.txt</a>
    <a href="/agent/playbook">Playbook</a>
    <a href="https://github.com/TVibe-signal/signal-api" target="_blank" rel="noopener">GitHub</a>
  </nav>

  <footer>
    <strong>Primary call</strong> · <code style="font-family:inherit;color:var(--muted)">GET /omni?mint=&lt;MINT&gt;&view=agent</code><br>
    pass / ok = risk gate cleared — not a buy signal. Heuristics only.
  </footer>
</div>

<script>
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function trySol() {
  $('mint').value = 'So11111111111111111111111111111111111111112';
  check();
}

async function check() {
  const m = ($('mint').value || '').trim();
  const out = $('out');
  if (!m) {
    out.innerHTML = '<div class="err">Paste a mint address first.</div>';
    return;
  }
  if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(m)) {
    out.innerHTML = '<div class="err">Not a valid Solana mint (32–44 base58 chars).</div>';
    return;
  }
  out.innerHTML = '<div class="loading">Checking…</div>';
  try {
    const r = await fetch('/omni?mint=' + encodeURIComponent(m), { cache: 'no-store' });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) {
      out.innerHTML = '<div class="err">Error ' + r.status + ' — ' +
        esc(d.detail || d.error || 'upstream issue') + '</div>';
      return;
    }
    const dec = d.decision || {};
    const raw = String(dec.verdict || d.verdict || d.action || '').toLowerCase();
    let label = '—', cls = 'badge-other';
    if (raw === 'ok' || raw === 'pass') { label = 'PASS'; cls = 'badge-pass'; }
    else if (raw === 'caution' || raw === 'review') { label = 'REVIEW'; cls = 'badge-review'; }
    else if (raw === 'avoid' || raw === 'skip') { label = 'SKIP'; cls = 'badge-skip'; }
    else { label = (raw || '—').toUpperCase(); }

    const risk = dec.risk_score ?? d.risk_score ?? '—';
    const liq = d.liquidity_usd != null
      ? '$' + Number(d.liquidity_usd).toLocaleString(undefined, { maximumFractionDigits: 0 })
      : '—';
    const unknowns = (dec.unknowns || d.unknowns || []).length;

    out.innerHTML =
      '<div class="result">' +
        '<span class="badge ' + cls + '">' + esc(label) + '</span>' +
        '<div class="meta"><b>Risk ' + esc(risk) + '</b> · Liquidity ' + esc(liq) +
          (unknowns ? ' · <span style="color:var(--amber)">' + unknowns + ' unknown' + (unknowns > 1 ? 's' : '') + '</span>' : '') +
        '</div>' +
        '<a class="raw-link" href="/omni?mint=' + encodeURIComponent(m) + '" target="_blank" rel="noopener">Open full JSON →</a>' +
      '</div>';
  } catch (e) {
    out.innerHTML = '<div class="err">Network error — try again.</div>';
  }
}

$('mint').addEventListener('keydown', e => {
  if (e.key === 'Enter') check();
});
</script>
</body>
</html>
"""


def _drop(app, path: str) -> None:
    """Aggressively remove every route matching the path."""
    try:
        app.router.routes[:] = [
            r for r in app.router.routes
            if getattr(r, "path", None) != path
        ]
    except Exception:
        pass


def _omni_handler(g):
    from fastapi import Request, HTTPException
    from fastapi.responses import JSONResponse

    async def handler(request: Request):
        # Read everything from query_params — never rely on FastAPI Query() validation
        qp = request.query_params
        m = (qp.get("mint") or qp.get("request") or "").strip()
        view = (qp.get("view") or "full").strip().lower()

        if not m:
            return JSONResponse(
                {"error": "mint is required", "nfa": True}, status_code=400
            )
        if not MINT_RE.match(m):
            return JSONResponse(
                {"error": "Invalid Solana mint", "mint": m, "nfa": True},
                status_code=400,
            )

        # best-effort rate limit
        try:
            rl = g.get("rate_limited")
            ipf = g.get("client_ip")
            if callable(rl) and callable(ipf):
                wait = rl(ipf(request), cost=4)
                if wait:
                    raise HTTPException(
                        status_code=429,
                        detail=f"rate limited, retry after {wait}s",
                    )
        except HTTPException:
            raise
        except Exception:
            pass

        client = getattr(request.app.state, "client", None)
        build = g.get("build_omni") or g.get("build_signal")
        if not callable(build):
            return JSONResponse(
                {
                    "mint": m,
                    "error": "builder unavailable",
                    "action": "skip",
                    "nfa": True,
                }
            )

        try:
            name = getattr(build, "__name__", "") or ""
            if "build_signal" in name:
                pkt = await build(client, m, security=True)
            else:
                pkt = await build(client, m)
            if isinstance(pkt, tuple):
                pkt = pkt[0] if pkt else {}
            if not isinstance(pkt, dict):
                pkt = {"mint": m, "error": "bad packet", "nfa": True}
        except Exception as e:
            return JSONResponse(
                {
                    "mint": m,
                    "error": str(e)[:200],
                    "action": "skip",
                    "nfa": True,
                },
                status_code=500,
            )

        if view in ("agent", "compact", "action"):
            av = g.get("_tvibe_agent_view")
            if callable(av):
                try:
                    return av(pkt)
                except Exception:
                    pass
            dec = pkt.get("decision") or {}
            verdict = str(
                dec.get("verdict") or pkt.get("verdict") or "caution"
            ).lower()
            action = (
                "pass"
                if verdict in ("ok", "pass")
                else "skip"
                if verdict in ("avoid", "skip")
                else "review"
            )
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

    from fastapi.responses import HTMLResponse

    # 1. Premium solid homepage
    _drop(app, "/")
    @app.get("/", tags=["product"], response_class=HTMLResponse, include_in_schema=False)
    async def home():
        return HTMLResponse(content=HOME, status_code=200)
    g["HOME_HTML"] = HOME
    print("[patch_live_fix] / premium homepage installed (v34)")

    # 2. Stable /omni + /play — no Query() validation, read raw query_params
    for path in ("/omni", "/play"):
        _drop(app, path)
        # also try removing any residual routes that might still match
        try:
            app.router.routes[:] = [
                r for r in app.router.routes
                if not (getattr(r, "path", None) == path)
            ]
        except Exception:
            pass
        app.add_api_route(path, _omni_handler(g), methods=["GET"], tags=["product"])
    print("[patch_live_fix] /omni + /play replaced (v34.1 — no 422)")

    # 3. Status + agent helpers
    _drop(app, "/__main_status")
    @app.get("/__main_status", tags=["product"])
    async def main_status():
        return {
            "main_py": "loader",
            "patch_live_fix": "v34.1-no422",
            "homepage": "premium",
            "wrapper": "none",
        }

    _drop(app, "/agent.json")
    @app.get("/agent.json", tags=["product"])
    async def agent_json():
        return {
            "name": "TVibe Signal",
            "version": "v34.1-no422",
            "endpoints": {
                "check": "GET /omni?mint=<MINT>",
                "agent": "GET /omni?mint=<MINT>&view=agent",
                "play": "GET /play?mint=<MINT>",
            },
            "nfa": True,
        }

    print("[patch_live_fix] applied v34.1-no422")

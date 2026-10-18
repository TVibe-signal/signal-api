# ---------- v2.82: Agent-first home + donate + fair-use (complete) ----------
VERSION = "2.82.0"
app.version = VERSION
app.openapi_schema = None

from fastapi.responses import HTMLResponse, PlainTextResponse

DONATE_SOL = "3iAVBvE4aU4A5DTKCqzu6jg79UfW6aEnqUD1pjfew18n"
BASE = "https://signal-api-24q4.onrender.com"
DONATE_NOTE = (
    "TVibex402 is free and open source. If the public instance helps your agents, "
    "you can tip SOL to cover Render/RPC. Never required."
)

FAIR_USE = f"""TVibex402 public instance — FREE, fair use
• About 30 requests/minute without a key (429 if exceeded)
• /signals batch: max 10 mints per call
• Cache the same mint 15–30s on the client
• Prefer GET /omni once over polling many small routes
• Heavy use: self-host from GitHub (your track-record starts empty)
• Not financial advice. Heuristics only.

Optional SOL tip (never required):
  {DONATE_SOL}
"""

HOME_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#070b12">
<meta name="color-scheme" content="dark">
<title>TVibex402 — Solana signals for AI agents</title>
<meta name="description" content="Free Solana token signals for AI agents. One call: verdict, reasons, measured track record. Not financial advice.">
<meta property="og:type" content="website">
<meta property="og:title" content="TVibex402 — Solana signals for AI agents">
<meta property="og:description" content="Verdict + reasons in one JSON. Free, open source, accuracy public on /stats.">
<meta property="og:image" content="{BASE}/og.svg">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>
:root {{
  --bg:#070b12; --card:rgba(15,22,34,.92); --line:rgba(40,56,78,.9);
  --text:#e8eef6; --muted:#8b9bb4; --a:#14f195; --b:#9945ff; --c:#6366f1;
}}
* {{ box-sizing:border-box; margin:0; padding:0 }}
body {{
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.55;
  min-height: 100vh;
}}
.bg {{ position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }}
.bg span {{
  position: absolute; width: 55vmax; height: 55vmax; border-radius: 50%;
  filter: blur(10px); opacity: .42;
}}
.bg span:nth-child(1) {{
  left: -20vmax; top: -25vmax;
  background: radial-gradient(circle, rgba(153,69,255,.55), transparent 65%);
}}
.bg span:nth-child(2) {{
  right: -25vmax; top: 18vh;
  background: radial-gradient(circle, rgba(20,241,149,.28), transparent 65%);
}}
.bg span:nth-child(3) {{
  left: 18vw; bottom: -35vmax;
  background: radial-gradient(circle, rgba(99,102,241,.38), transparent 65%);
}}
.wrap {{ position: relative; z-index: 1; max-width: 960px; margin: 0 auto; padding: 0 1.25rem 4rem }}
nav {{
  display: flex; justify-content: space-between; align-items: center;
  padding: 1.1rem 0; border-bottom: 1px solid var(--line); flex-wrap: wrap; gap: .6rem;
}}
.logo {{ font-weight: 800; letter-spacing: -.03em; font-size: 1.15rem }}
.logo em {{
  font-style: normal;
  background: linear-gradient(120deg, var(--b), var(--a));
  -webkit-background-clip: text; background-clip: text; color: transparent;
}}
nav a {{ color: var(--muted); text-decoration: none; margin-left: 1rem; font-size: .92rem }}
nav a:hover {{ color: var(--text) }}
.hero {{ text-align: center; padding: 3.2rem 0 2rem }}
.badge {{
  display: inline-block; font-size: .72rem; letter-spacing: .07em; text-transform: uppercase;
  color: var(--a); border: 1px solid rgba(20,241,149,.35); padding: .35rem .75rem;
  border-radius: 999px; margin-bottom: 1rem;
}}
h1 {{
  font-size: clamp(2rem, 5.5vw, 3.1rem); font-weight: 800; letter-spacing: -.04em;
  line-height: 1.12; margin-bottom: 1rem;
}}
h1 span {{
  background: linear-gradient(135deg, #a78bfa, #14f195);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}}
.sub {{ color: var(--muted); font-size: 1.08rem; max-width: 560px; margin: 0 auto 1.6rem }}
.sub a {{ color: var(--a) }}
.cta {{ display: flex; flex-wrap: wrap; gap: .7rem; justify-content: center }}
.btn {{
  display: inline-block; padding: .75rem 1.35rem; border-radius: .75rem;
  font-weight: 600; text-decoration: none; font-size: .95rem;
}}
.btn-p {{ background: linear-gradient(135deg, var(--b), var(--c)); color: #fff }}
.btn-g {{ background: rgba(20,241,149,.12); color: var(--a); border: 1px solid rgba(20,241,149,.35) }}
.btn-o {{ border: 1px solid var(--line); color: var(--text) }}
.grid {{
  display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem; margin: 2rem 0;
}}
.card {{
  background: var(--card); border: 1px solid var(--line); border-radius: 1rem;
  padding: 1.15rem 1.2rem;
}}
.card h3 {{ font-size: .95rem; margin-bottom: .4rem }}
.card p {{ color: var(--muted); font-size: .88rem }}
.card code {{ color: var(--a); font-size: .8rem }}
pre {{
  background: #0c121c; border: 1px solid var(--line); border-radius: .85rem;
  padding: 1rem 1.1rem; overflow-x: auto; font-size: .82rem; color: #c7d2fe;
  margin: 1rem 0 0;
}}
section {{ margin: 2.25rem 0 }}
section h2 {{ font-size: 1.15rem; margin-bottom: .75rem }}
.muted {{ color: var(--muted); font-size: .9rem }}
.donate-box {{
  background: linear-gradient(145deg, rgba(153,69,255,.14), rgba(20,241,149,.08));
  border: 1px solid rgba(20,241,149,.32);
  border-radius: 1rem; padding: 1.25rem 1.3rem;
}}
.sol {{
  word-break: break-all; color: var(--a);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .85rem; margin-top: .65rem; user-select: all;
}}
.copy-row {{ margin-top: .75rem; display: flex; flex-wrap: wrap; gap: .5rem; align-items: center }}
.copy-btn {{
  cursor: pointer; border: 1px solid rgba(20,241,149,.4); background: rgba(20,241,149,.1);
  color: var(--a); border-radius: .5rem; padding: .4rem .85rem; font-size: .85rem; font-weight: 600;
}}
footer {{
  margin-top: 3rem; padding-top: 1.25rem; border-top: 1px solid var(--line);
  color: var(--muted); font-size: .85rem; text-align: center;
}}
footer a {{ color: var(--a) }}
</style>
</head>
<body>
<div class="bg" aria-hidden="true"><span></span><span></span><span></span></div>
<div class="wrap">
  <nav>
    <div class="logo">TVibe<em>x402</em></div>
    <div>
      <a href="/agents">Agents</a>
      <a href="/stats">Stats</a>
      <a href="/docs">API</a>
      <a href="#donate">Donate</a>
      <a href="https://github.com/TVibex402/signal-api">GitHub</a>
    </div>
  </nav>

  <header class="hero">
    <div class="badge">Free · Open source · Measured in public</div>
    <h1>Solana token signals<br>for <span>AI agents</span></h1>
    <p class="sub">
      One request → verdict, reasons, and context.
      Track record is public on <a href="/stats">/stats</a>.
      Heuristics only — not financial advice.
    </p>
    <div class="cta">
      <a class="btn btn-p" href="/omni?mint=So11111111111111111111111111111111111111112">Try /omni</a>
      <a class="btn btn-g" href="/stats">Live accuracy</a>
      <a class="btn btn-o" href="/mcp">MCP</a>
    </div>
  </header>

  <div class="grid">
    <div class="card">
      <h3>Primary call</h3>
      <p><code>GET /omni?mint=…</code></p>
      <p>Verdict + decision block agents should trust first.</p>
    </div>
    <div class="card">
      <h3>Prove it</h3>
      <p><code>GET /stats</code></p>
      <p>Precision / recall on judged outcomes — not marketing claims.</p>
    </div>
    <div class="card">
      <h3>MCP</h3>
      <p><code>omni(mint)</code></p>
      <p>Wire into Cursor, Claude, or your agent runtime.</p>
    </div>
    <div class="card">
      <h3>Self-host</h3>
      <p><code>github.com/TVibex402/signal-api</code></p>
      <p>Same code. Your Redis starts its own track record.</p>
    </div>
  </div>

  <section>
    <h2>Quick start</h2>
    <pre>curl -s "{BASE}/omni?mint=So11111111111111111111111111111111111111112" | jq .decision</pre>
    <p class="muted" style="margin-top:.75rem">
      Batch: <code>/signals?mints=a,b,c&amp;view=compact</code> (max 10).
      Cache the same mint 15–30s.
    </p>
  </section>

  <section>
    <h2>Fair use</h2>
    <div class="card">
      <p class="muted">
        Public host is <strong style="color:var(--text)">free</strong>.
        \~30 req/min without a key · batch max 10 · please cache.
        Heavy traffic → self-host or slow down on HTTP 429.
        Full text: <a href="/support" style="color:var(--a)">/support</a>
      </p>
    </div>
  </section>

  <section id="donate">
    <h2>Optional tip (never required)</h2>
    <div class="donate-box">
      <p class="muted">{DONATE_NOTE}</p>
      <p class="sol" id="sol-addr">{DONATE_SOL}</p>
      <div class="copy-row">
        <button type="button" class="copy-btn"
          onclick="navigator.clipboard.writeText('{DONATE_SOL}').then(()=>{{this.textContent='Copied'}}).catch(()=>{{}})">
          Copy address
        </button>
        <a class="btn btn-o" style="padding:.4rem .85rem;font-size:.85rem" href="/donate">/donate JSON</a>
      </div>
    </div>
  </section>

  <footer>
    <p>Not financial advice. Heuristics for agents and research.</p>
    <p style="margin-top:.4rem">
      <a href="/support">/support</a> ·
      <a href="/agents">/agents</a> ·
      <a href="/llms.txt">llms.txt</a> ·
      <a href="https://github.com/TVibex402/signal-api">source</a>
    </p>
  </footer>
</div>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home_v282():
    return HOME_HTML


@app.get("/donate", tags=["product"])
async def donate_json():
    return {{
        "free": True,
        "required": False,
        "asset": "SOL",
        "address": DONATE_SOL,
        "note": DONATE_NOTE,
        "fair_use": "/support",
        "self_host": "https://github.com/TVibex402/signal-api",
        "disclaimer": "Not financial advice. Donations are voluntary tips for hosting/RPC only.",
        "version": VERSION,
    }}


@app.get("/donate.html", response_class=HTMLResponse, tags=["product"], include_in_schema=False)
async def donate_html():
    return f"""<!doctype html><html lang="en"><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Donate — TVibex402</title>
<style>
body{{margin:0;font-family:system-ui,sans-serif;background:#070b12;color:#e8eef6;line-height:1.55}}
.w{{max-width:560px;margin:0 auto;padding:32px 16px}}
h1{{font-size:1.5rem;background:linear-gradient(120deg,#9945ff,#14f195);-webkit-background-clip:text;color:transparent}}
.card{{background:rgba(15,22,34,.9);border:1px solid rgba(40,56,78,.9);border-radius:14px;padding:18px;margin-top:16px}}
code{{word-break:break-all;color:#14f195}} a{{color:#14f195}} .m{{color:#8b9bb4;font-size:.9rem}}
</style></head><body><div class=w>
<h1>Optional SOL tip</h1>
<p class=m>{DONATE_NOTE}</p>
<div class=card><code>{DONATE_SOL}</code></div>
<p class=m style="margin-top:16px"><a href="/">Home</a> · <a href="/support">Fair use</a></p>
</div></body></html>"""


@app.get("/support", response_class=PlainTextResponse, tags=["product"])
async def support_fair_use():
    return FAIR_USE.strip() + "\\n"


print(f"[part103] v{{VERSION}} home+donate+support → GET / · /donate · /support")
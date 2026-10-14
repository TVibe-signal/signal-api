# ---------- v2.50: SI Command Center UI ----------
VERSION = "2.50.0"
app.version = VERSION
app.openapi_schema = None

from fastapi.responses import HTMLResponse

SI_UI_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>TVibex402 — SI Command Center</title>
<style>
  :root {
    --bg: #07090f;
    --panel: #0e121b;
    --line: #1c2433;
    --text: #e8eef9;
    --muted: #8b98b0;
    --cyan: #5ce1ff;
    --violet: #a78bfa;
    --green: #34d399;
    --red: #fb7185;
    --amber: #fbbf24;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    background:
      radial-gradient(1200px 600px at 10% -10%, #15203a 0%, transparent 55%),
      radial-gradient(900px 500px at 100% 0%, #1a1030 0%, transparent 50%),
      var(--bg);
    color: var(--text);
    min-height: 100vh;
  }
  .wrap { max-width: 1120px; margin: 0 auto; padding: 28px 18px 80px; }
  header {
    display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between;
    gap: 16px; margin-bottom: 28px;
  }
  .brand { font-size: 13px; letter-spacing: .18em; text-transform: uppercase; color: var(--cyan); }
  h1 {
    margin: 6px 0 0;
    font-size: clamp(1.6rem, 3vw, 2.2rem);
    font-weight: 650;
    background: linear-gradient(90deg, #fff, #9ad8ff 40%, #c4b5fd);
    -webkit-background-clip: text; background-clip: text; color: transparent;
  }
  .sub { color: var(--muted); font-size: 14px; margin-top: 6px; max-width: 520px; }
  .pill {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 8px 12px; border-radius: 999px;
    background: rgba(92,225,255,.08); border: 1px solid rgba(92,225,255,.25);
    color: var(--cyan); font-size: 12px; letter-spacing: .04em;
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 12px var(--green); }
  .grid {
    display: grid;
    grid-template-columns: repeat(12, 1fr);
    gap: 14px;
  }
  .card {
    background: linear-gradient(180deg, rgba(255,255,255,.03), transparent 40%), var(--panel);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 16px 16px 14px;
    position: relative;
    overflow: hidden;
  }
  .card::before {
    content: "";
    position: absolute; inset: 0 auto auto 0; width: 100%; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(92,225,255,.35), transparent);
  }
  .c4 { grid-column: span 4; }
  .c6 { grid-column: span 6; }
  .c8 { grid-column: span 8; }
  .c12 { grid-column: span 12; }
  @media (max-width: 860px) {
    .c4, .c6, .c8, .c12 { grid-column: span 12; }
  }
  .label {
    font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted);
    margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;
  }
  .value { font-size: 1.55rem; font-weight: 650; }
  .muted { color: var(--muted); font-size: 13px; }
  .row { display: flex; gap: 10px; flex-wrap: wrap; }
  .tag {
    font-size: 12px; padding: 4px 9px; border-radius: 8px;
    background: #151b28; border: 1px solid var(--line); color: #cbd5e1;
  }
  .tag.ok { color: var(--green); border-color: rgba(52,211,153,.35); }
  .tag.bad { color: var(--red); border-color: rgba(251,113,133,.35); }
  .tag.warn { color: var(--amber); border-color: rgba(251,191,36,.35); }
  .tag.cyan { color: var(--cyan); border-color: rgba(92,225,255,.3); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 6px; border-bottom: 1px solid var(--line); vertical-align: top; }
  th { color: var(--muted); font-weight: 500; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; }
  .bar {
    height: 6px; border-radius: 99px; background: #182033; overflow: hidden; margin-top: 8px;
  }
  .bar > i { display: block; height: 100%; background: linear-gradient(90deg, var(--violet), var(--cyan)); }
  input[type=text] {
    width: 100%; background: #0a0e16; border: 1px solid var(--line); color: var(--text);
    border-radius: 12px; padding: 12px 14px; font-size: 14px; outline: none;
  }
  input[type=text]:focus { border-color: rgba(92,225,255,.45); box-shadow: 0 0 0 3px rgba(92,225,255,.12); }
  button {
    background: linear-gradient(135deg, #2dd4ff, #818cf8);
    color: #061018; border: 0; border-radius: 12px; padding: 12px 16px;
    font-weight: 650; cursor: pointer;
  }
  button.secondary {
    background: transparent; color: var(--text); border: 1px solid var(--line);
  }
  .actions { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
  pre {
    background: #0a0e16; border: 1px solid var(--line); border-radius: 12px;
    padding: 12px; overflow: auto; font-size: 12px; line-height: 1.45; color: #cbd5e1;
    max-height: 320px;
  }
  .footer { margin-top: 28px; color: var(--muted); font-size: 12px; text-align: center; }
  a { color: var(--cyan); text-decoration: none; }
  .skeleton { opacity: .45; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <div class="brand">TVibex402 · Super Intelligence Layer</div>
      <h1>SI Command Center</h1>
      <p class="sub">Live view of regime, debate learning, hypotheses, causal memory and predictive attention — the self-improving stack behind every signal.</p>
    </div>
    <div class="pill"><span class="dot"></span> <span id="liveState">Connecting…</span></div>
  </header>

  <div class="grid">
    <section class="card c4">
      <div class="label">Market Regime</div>
      <div class="value" id="regimeName">—</div>
      <div class="muted" id="regimeMeta">confidence · samples</div>
      <div class="bar"><i id="regimeBar" style="width:0%"></i></div>
    </section>

    <section class="card c4">
      <div class="label">SI Learning</div>
      <div class="value" id="siFed">—</div>
      <div class="muted">outcomes fed into debate + hypotheses</div>
      <div class="row" style="margin-top:10px" id="siTags"></div>
    </section>

    <section class="card c4">
      <div class="label">Predictive Attention</div>
      <div class="value" id="predCount">—</div>
      <div class="muted">tokens with rising short-term attention</div>
      <div class="row" style="margin-top:10px" id="predTop"></div>
    </section>

    <section class="card c6">
      <div class="label">Debate Persona Accuracy</div>
      <div id="debateTable" class="muted">Loading…</div>
    </section>

    <section class="card c6">
      <div class="label">Active Hypotheses</div>
      <div id="hypoTable" class="muted">Loading…</div>
    </section>

    <section class="card c12">
      <div class="label">Inspect a mint</div>
      <input id="mintInput" type="text" placeholder="Paste a Solana mint address" value="So11111111111111111111111111111111111111112"/>
      <div class="actions">
        <button onclick="inspectMint()">Run SI inspect</button>
        <button class="secondary" onclick="loadAll()">Refresh dashboard</button>
      </div>
      <div style="margin-top:14px" id="inspectOut"><pre class="skeleton">Waiting for inspect…</pre></div>
    </section>

    <section class="card c12">
      <div class="label">Evolution proposals (self-improve)</div>
      <div id="evolBox" class="muted">Loading…</div>
    </section>
  </div>

  <div class="footer">
    Heuristic SI layer · Not financial advice ·
    <a href="/docs">API docs</a> ·
    <a href="/accuracy/story">Accuracy story</a> ·
    <a href="/llms.txt">llms.txt</a>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);

async function j(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
}

function tag(text, cls="") {
  return `<span class="tag \( {cls}"> \){text}</span>`;
}

async function loadRegime() {
  try {
    const d = await j("/regime");
    $("regimeName").textContent = (d.regime || d.name || "unknown").replaceAll("_", " ");
    const conf = Math.round((d.confidence || 0) * 100);
    \( ("regimeMeta").textContent = ` \){conf}% confidence · n=\( {d.n ?? "—"} · bad_rate= \){d.bad_rate ?? "—"}`;
    $("regimeBar").style.width = conf + "%";
  } catch {
    $("regimeName").textContent = "unavailable";
  }
}

async function loadSI() {
  try {
    const d = await j("/si/status");
    const m = d.meta || {};
    $("siFed").textContent = m.outcomes_fed || 0;
    const layers = d.layers || {};
    $("siTags").innerHTML = Object.entries(layers)
      .map(([k,v]) => tag(k, v ? "ok" : "bad")).join("");
    $("liveState").textContent = "SI online · " + (d.version || "");
  } catch {
    $("siFed").textContent = "—";
    $("liveState").textContent = "Partial SI";
  }
}

async function loadPred() {
  try {
    const d = await j("/predictive-attention?limit=5");
    const items = d.items || [];
    $("predCount").textContent = items.length;
    $("predTop").innerHTML = items.slice(0,3)
      .map(i => tag((i.mint || "").slice(0,4) + "…" + (i.mint || "").slice(-4) + " · " + i.score, "cyan"))
      .join("") || tag("no signals yet");
  } catch {
    $("predCount").textContent = "—";
  }
}

async function loadDebate() {
  try {
    const d = await j("/debate/scores");
    const s = d.persona_accuracy || {};
    const rows = Object.entries(s).map(([name, v]) => {
      const acc = v.accuracy == null ? "—" : Math.round(v.accuracy * 100) + "%";
      return `<tr><td>\( {name}</td><td> \){acc}</td><td>${v.n || 0}</td></tr>`;
    }).join("");
    $("debateTable").innerHTML = rows
      ? `<table><thead><tr><th>Persona</th><th>Accuracy</th><th>n</th></tr></thead><tbody>${rows}</tbody></table>`
      : "No scored debates yet — waiting for outcomes.";
  } catch {
    $("debateTable").textContent = "Unavailable";
  }
}

async function loadHypo() {
  try {
    const d = await j("/hypotheses");
    const list = d.hypotheses || [];
    const rows = list.map(h => {
      const rate = h.n ? Math.round((h.bad || 0) / h.n * 100) + "%" : "—";
      const cls = h.status === "supported" ? "ok" : h.status === "weak" ? "bad" : "warn";
      return `<tr>
        <td><div>\( {h.id}</div><div class="muted"> \){h.claim || ""}</div></td>
        <td>${tag(h.status || "collecting", cls)}</td>
        <td>${h.n || 0}</td>
        <td>${rate}</td>
      </tr>`;
    }).join("");
    $("hypoTable").innerHTML = rows
      ? `<table><thead><tr><th>Hypothesis</th><th>Status</th><th>n</th><th>bad</th></tr></thead><tbody>${rows}</tbody></table>`
      : "No hypotheses loaded.";
  } catch {
    $("hypoTable").textContent = "Unavailable";
  }
}

async function loadEvol() {
  try {
    const d = await j("/evolution?limit=5");
    const logs = d.logs || [];
    if (!logs.length) {
      $("evolBox").textContent = "No evolution proposals yet.";
      return;
    }
    $("evolBox").innerHTML = logs.map(e => {
      const when = new Date((e.ts || 0) * 1000).toISOString().replace("T", " ").slice(0, 16);
      const changes = (e.changes || []).map(c =>
        `${c.flag}: ${c.old_weight} → ${c.new_weight}`
      ).join(" · ") || "—";
      return `<div style="margin-bottom:10px">
        <div>\( {tag(e.applied ? "applied" : "proposal", e.applied ? "ok" : "cyan")} <span class="muted"> \){when} UTC</span></div>
        <div style="margin-top:6px">${changes}</div>
      </div>`;
    }).join("");
  } catch {
    $("evolBox").textContent = "Evolution endpoint hidden or unavailable.";
  }
}

async function inspectMint() {
  const mint = $("mintInput").value.trim();
  if (!mint) return;
  $("inspectOut").innerHTML = `<pre>Inspecting ${mint}…</pre>`;
  try {
    const [sig, causal] = await Promise.all([
      j("/signal?mint=" + encodeURIComponent(mint)),
      j("/causal/" + encodeURIComponent(mint)).catch(() => null),
    ]);
    const view = {
      token: sig.token,
      verdict: (sig.decision || {}).verdict || sig.verdict,
      risk_score: sig.risk_score,
      community: sig.community,
      debate: sig.debate,
      regime: sig.regime,
      causal: sig.causal || causal,
      hypotheses_matched: sig.hypotheses_matched,
    };
    \( ("inspectOut").innerHTML = `<pre> \){JSON.stringify(view, null, 2)}</pre>`;
  } catch (e) {
    $("inspectOut").innerHTML = `<pre>Error: ${e.message}</pre>`;
  }
}

async function loadAll() {
  $("liveState").textContent = "Refreshing…";
  await Promise.all([
    loadRegime(), loadSI(), loadPred(), loadDebate(), loadHypo(), loadEvol()
  ]);
}

loadAll();
setInterval(loadAll, 60000);
</script>
</body>
</html>
"""

@app.get("/si", tags=["product"], response_class=HTMLResponse)
@app.get("/si/", tags=["product"], response_class=HTMLResponse, include_in_schema=False)
async def si_command_center():
    return HTMLResponse(SI_UI_HTML)

print(f"[part69] v{VERSION} SI Command Center UI loaded → GET /si")
# ---------- v2.50.1: SI Command Center UI (resilient) ----------
VERSION = "2.50.1"
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
  .pill.warn { border-color: rgba(251,191,36,.35); color: var(--amber); background: rgba(251,191,36,.08); }
  .pill.bad { border-color: rgba(251,113,133,.35); color: var(--red); background: rgba(251,113,133,.08); }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--green); box-shadow: 0 0 12px var(--green); }
  .dot.warn { background: var(--amber); box-shadow: 0 0 12px var(--amber); }
  .dot.bad { background: var(--red); box-shadow: 0 0 12px var(--red); }
  .grid { display: grid; grid-template-columns: repeat(12, 1fr); gap: 14px; }
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
  .c12 { grid-column: span 12; }
  @media (max-width: 860px) {
    .c4, .c6, .c12 { grid-column: span 12; }
  }
  .label {
    font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted);
    margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;
  }
  .value { font-size: 1.55rem; font-weight: 650; word-break: break-word; }
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
  .bar { height: 6px; border-radius: 99px; background: #182033; overflow: hidden; margin-top: 8px; }
  .bar > i { display: block; height: 100%; background: linear-gradient(90deg, var(--violet), var(--cyan)); width: 0%; transition: width .4s ease; }
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
  button.secondary { background: transparent; color: var(--text); border: 1px solid var(--line); }
  .actions { display: flex; gap: 10px; margin-top: 10px; flex-wrap: wrap; }
  pre {
    background: #0a0e16; border: 1px solid var(--line); border-radius: 12px;
    padding: 12px; overflow: auto; font-size: 12px; line-height: 1.45; color: #cbd5e1;
    max-height: 320px; white-space: pre-wrap; word-break: break-word;
  }
  .footer { margin-top: 28px; color: var(--muted); font-size: 12px; text-align: center; }
  a { color: var(--cyan); text-decoration: none; }
  .empty { color: var(--muted); font-size: 13px; line-height: 1.5; }
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
    <div class="pill" id="statusPill"><span class="dot" id="statusDot"></span> <span id="liveState">Loading…</span></div>
  </header>

  <div class="grid">
    <section class="card c4">
      <div class="label">Market Regime</div>
      <div class="value" id="regimeName">…</div>
      <div class="muted" id="regimeMeta">—</div>
      <div class="bar"><i id="regimeBar"></i></div>
    </section>

    <section class="card c4">
      <div class="label">SI Learning</div>
      <div class="value" id="siFed">…</div>
      <div class="muted">outcomes fed into debate + hypotheses</div>
      <div class="row" style="margin-top:10px" id="siTags"></div>
    </section>

    <section class="card c4">
      <div class="label">Predictive Attention</div>
      <div class="value" id="predCount">…</div>
      <div class="muted">tokens with rising short-term attention</div>
      <div class="row" style="margin-top:10px" id="predTop"></div>
    </section>

    <section class="card c6">
      <div class="label">Debate Persona Accuracy</div>
      <div id="debateTable" class="empty">Loading…</div>
    </section>

    <section class="card c6">
      <div class="label">Active Hypotheses</div>
      <div id="hypoTable" class="empty">Loading…</div>
    </section>

    <section class="card c12">
      <div class="label">Inspect a mint</div>
      <input id="mintInput" type="text" placeholder="Paste a Solana mint address" value="So11111111111111111111111111111111111111112"/>
      <div class="actions">
        <button onclick="inspectMint()">Run SI inspect</button>
        <button class="secondary" onclick="loadAll()">Refresh</button>
      </div>
      <div style="margin-top:14px" id="inspectOut"><pre class="empty">Paste a mint and run inspect.</pre></div>
    </section>

    <section class="card c12">
      <div class="label">Evolution proposals</div>
      <div id="evolBox" class="empty">Loading…</div>
    </section>
  </div>

  <div class="footer">
    Heuristic SI layer · Not financial advice ·
    <a href="/">Home</a> ·
    <a href="/docs">API docs</a> ·
    <a href="/accuracy/story">Accuracy story</a> ·
    <a href="/llms.txt">llms.txt</a>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);

async function j(url) {
  const r = await fetch(url, { headers: { "Accept": "application/json" } });
  const text = await r.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { raw: text }; }
  if (!r.ok) {
    const err = new Error((data && (data.detail || data.message)) || (url + " → " + r.status));
    err.status = r.status;
    err.data = data;
    throw err;
  }
  return data;
}

function tag(text, cls) {
  return `<span class="tag \( {cls || ""}"> \){text}</span>`;
}

function setStatus(mode, text) {
  const pill = $("statusPill");
  const dot = $("statusDot");
  pill.className = "pill" + (mode === "ok" ? "" : mode === "warn" ? " warn" : " bad");
  dot.className = "dot" + (mode === "ok" ? "" : mode === "warn" ? " warn" : " bad");
  $("liveState").textContent = text;
}

async function loadRegime() {
  try {
    const d = await j("/regime");
    const name = (d.regime || d.name || "unknown").toString().replaceAll("_", " ");
    $("regimeName").textContent = name;
    const conf = Math.round((Number(d.confidence) || 0) * 100);
    \( ("regimeMeta").textContent = ` \){conf}% confidence · n=\( {d.n ?? "—"} · bad_rate= \){d.bad_rate ?? "—"}`;
    $("regimeBar").style.width = Math.min(100, Math.max(0, conf)) + "%";
    return true;
  } catch (e) {
    $("regimeName").textContent = "unavailable";
    $("regimeMeta").textContent = e.status === 404 ? "endpoint not loaded" : String(e.message || e);
    $("regimeBar").style.width = "0%";
    return false;
  }
}

async function loadSI() {
  try {
    const d = await j("/si/status");
    const m = d.meta || {};
    $("siFed").textContent = m.outcomes_fed ?? 0;
    const layers = d.layers || {};
    $("siTags").innerHTML = Object.keys(layers).length
      ? Object.entries(layers).map(([k, v]) => tag(k, v ? "ok" : "bad")).join("")
      : tag("no layer info", "warn");
    return true;
  } catch (e) {
    $("siFed").textContent = "—";
    $("siTags").innerHTML = tag(e.status === 404 ? "si/status missing" : "error", "bad");
    return false;
  }
}

async function loadPred() {
  try {
    const d = await j("/predictive-attention?limit=5");
    const items = d.items || [];
    $("predCount").textContent = items.length;
    $("predTop").innerHTML = items.length
      ? items.slice(0, 3).map(i => {
          const m = (i.mint || "").toString();
          const short = m.length > 10 ? m.slice(0, 4) + "…" + m.slice(-4) : m;
          return tag(short + " · " + i.score, "cyan");
        }).join("")
      : tag("no rising tokens yet", "warn");
    return true;
  } catch (e) {
    $("predCount").textContent = "—";
    $("predTop").innerHTML = tag(e.status === 404 ? "not loaded" : "error", "bad");
    return false;
  }
}

async function loadDebate() {
  try {
    const d = await j("/debate/scores");
    const s = d.persona_accuracy || {};
    const entries = Object.entries(s);
    if (!entries.length) {
      $("debateTable").innerHTML = `<div class="empty">No scored debates yet.<br/>Waiting for outcomes to land.</div>`;
      return true;
    }
    const rows = entries.map(([name, v]) => {
      const acc = v.accuracy == null ? "—" : Math.round(Number(v.accuracy) * 100) + "%";
      return `<tr><td>\( {name}</td><td> \){acc}</td><td>${v.n || 0}</td></tr>`;
    }).join("");
    \( ("debateTable").innerHTML = `<table><thead><tr><th>Persona</th><th>Accuracy</th><th>n</th></tr></thead><tbody> \){rows}</tbody></table>`;
    return true;
  } catch (e) {
    \( ("debateTable").innerHTML = `<div class="empty"> \){e.status === 404 ? "Endpoint not loaded yet." : String(e.message || e)}</div>`;
    return false;
  }
}

async function loadHypo() {
  try {
    const d = await j("/hypotheses");
    const list = d.hypotheses || [];
    if (!list.length) {
      $("hypoTable").innerHTML = `<div class="empty">No hypotheses loaded.</div>`;
      return true;
    }
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
    \( ("hypoTable").innerHTML = `<table><thead><tr><th>Hypothesis</th><th>Status</th><th>n</th><th>bad</th></tr></thead><tbody> \){rows}</tbody></table>`;
    return true;
  } catch (e) {
    \( ("hypoTable").innerHTML = `<div class="empty"> \){e.status === 404 ? "Endpoint not loaded yet." : String(e.message || e)}</div>`;
    return false;
  }
}

async function loadEvol() {
  try {
    const d = await j("/evolution?limit=5");
    const logs = d.logs || [];
    if (!logs.length) {
      $("evolBox").innerHTML = `<div class="empty">No evolution proposals yet.</div>`;
      return true;
    }
    $("evolBox").innerHTML = logs.map(e => {
      const when = new Date((e.ts || 0) * 1000).toISOString().replace("T", " ").slice(0, 16);
      const changes = (e.changes || []).map(c => `${c.flag}: ${c.old_weight} → ${c.new_weight}`).join(" · ") || "—";
      return `<div style="margin-bottom:12px">
        <div>\( {tag(e.applied ? "applied" : "proposal", e.applied ? "ok" : "cyan")} <span class="muted"> \){when} UTC</span></div>
        <div style="margin-top:6px">${changes}</div>
      </div>`;
    }).join("");
    return true;
  } catch (e) {
    \( ("evolBox").innerHTML = `<div class="empty"> \){e.status === 404 ? "Evolution is hidden or not loaded (set EVOLUTION_PUBLIC=true to show)." : String(e.message || e)}</div>`;
    return false;
  }
}

async function inspectMint() {
  const mint = $("mintInput").value.trim();
  if (!mint) return;
  $("inspectOut").innerHTML = `<pre>Inspecting ${mint}…</pre>`;
  try {
    const sig = await j("/signal?mint=" + encodeURIComponent(mint));
    let causal = null;
    try { causal = await j("/causal/" + encodeURIComponent(mint)); } catch {}
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
    $("inspectOut").innerHTML = `<pre>Error: ${e.message || e}</pre>`;
  }
}

async function loadAll() {
  setStatus("warn", "Refreshing…");
  const results = await Promise.all([
    loadRegime(), loadSI(), loadPred(), loadDebate(), loadHypo(), loadEvol()
  ]);
  const ok = results.filter(Boolean).length;
  if (ok === results.length) setStatus("ok", `SI online · \( {ok}/ \){results.length} panels`);
  else if (ok === 0) setStatus("bad", "No SI endpoints reachable");
  else setStatus("warn", `Partial · \( {ok}/ \){results.length} panels`);
}

loadAll();
setInterval(loadAll, 90000);
</script>
</body>
</html>
"""

@app.get("/si", tags=["product"], response_class=HTMLResponse)
@app.get("/si/", tags=["product"], response_class=HTMLResponse, include_in_schema=False)
async def si_command_center():
    return HTMLResponse(SI_UI_HTML)

print(f"[part69] v{VERSION} SI Command Center UI (resilient) → GET /si")
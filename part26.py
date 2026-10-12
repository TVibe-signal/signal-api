# ---------- part26: v2.13.3 - /play: polished playground for any Solana token ----------
# Loads before part7. One route, no new dependency. Calls public /signal + /exit (rate limits apply).
# All network text is rendered with textContent (never innerHTML) — token names are hostile.
VERSION = "2.13.3"
app.version = VERSION
app.openapi_schema = None

PLAY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0b0f19">
<meta name="color-scheme" content="dark">
<title>TVibex402 playground</title>
<style>
  :root {
    --bg: #0b0f19;
    --card: #151a28;
    --border: #2d3348;
    --text: #e2e8f0;
    --muted: #94a3b8;
    --accent: #6366f1;
    --accent-hover: #4f46e5;
    --green: #22c55e;
    --yellow: #eab308;
    --red: #ef4444;
    --grey: #64748b;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: system-ui, -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.55;
    padding: 1.25rem 1rem 3rem;
  }
  .wrap { max-width: 720px; margin: 0 auto; }
  h1 { font-size: 1.45rem; font-weight: 700; letter-spacing: -0.02em; margin-bottom: 0.3rem; }
  .sub { color: var(--muted); font-size: 0.9rem; margin-bottom: 1.25rem; }
  .disclaimer {
    background: #121722;
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.7rem 0.9rem;
    font-size: 0.82rem;
    color: var(--muted);
    margin-bottom: 1.25rem;
  }
  .row { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; flex-wrap: wrap; }
  input {
    flex: 1;
    min-width: 180px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 0.8rem 0.95rem;
    color: var(--text);
    font-size: 0.95rem;
    outline: none;
  }
  input:focus { border-color: var(--accent); }
  button {
    background: var(--accent);
    color: #fff;
    border: 0;
    border-radius: 10px;
    padding: 0 1.25rem;
    font-weight: 600;
    font-size: 0.95rem;
    cursor: pointer;
    min-height: 44px;
    white-space: nowrap;
  }
  button:hover { background: var(--accent-hover); }
  button:disabled { opacity: 0.55; cursor: not-allowed; }
  .chips { display: flex; flex-wrap: wrap; gap: 0.45rem; margin-bottom: 1.5rem; }
  .chip {
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--muted);
    padding: 0.35rem 0.75rem;
    border-radius: 999px;
    font-size: 0.8rem;
    cursor: pointer;
  }
  .chip:hover { border-color: var(--accent); color: var(--text); }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 1.15rem;
    margin-bottom: 1rem;
  }
  .verdict { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; margin-bottom: 0.5rem; }
  .badge {
    display: inline-block;
    padding: 0.2rem 0.7rem;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }
  .ok { background: rgba(34,197,94,0.18); color: var(--green); }
  .caution { background: rgba(234,179,8,0.18); color: var(--yellow); }
  .avoid { background: rgba(239,68,68,0.18); color: var(--red); }
  .unknown { background: rgba(100,116,139,0.25); color: #cbd5e1; }
  .summary { font-size: 0.95rem; margin-bottom: 0.25rem; }
  .meta { color: var(--muted); font-size: 0.82rem; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
    gap: 0.55rem;
    margin: 0.9rem 0;
  }
  .metric {
    background: #0f131f;
    border-radius: 10px;
    padding: 0.7rem 0.8rem;
  }
  .metric .l { color: var(--muted); font-size: 0.72rem; margin-bottom: 0.15rem; }
  .metric .v { font-size: 1.05rem; font-weight: 600; }
  h3 {
    font-size: 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 1rem 0 0.35rem;
  }
  ul { margin: 0.2rem 0; padding-left: 1.15rem; }
  li { margin: 0.2rem 0; font-size: 0.9rem; }
  .flag {
    display: inline-block;
    background: #1e2433;
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.15rem 0.5rem;
    font-size: 0.76rem;
    margin: 0.15rem 0.2rem 0.15rem 0;
    color: var(--muted);
  }
  .err { color: var(--red); }
  pre {
    background: #0f131f;
    border-radius: 10px;
    padding: 0.8rem;
    overflow-x: auto;
    font-size: 0.72rem;
    max-height: 280px;
    margin-top: 0.5rem;
  }
  details { margin-top: 0.9rem; }
  summary { cursor: pointer; color: var(--muted); font-size: 0.85rem; }
  .tabs { display: flex; gap: 0.4rem; margin: 0.35rem 0 0.6rem; }
  .tab {
    background: #0f131f;
    color: var(--muted);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.3rem 0.8rem;
    font-size: 0.8rem;
    cursor: pointer;
  }
  .tab.on { background: var(--accent); color: #fff; border-color: var(--accent); }
  .why {
    background: #0f131f;
    border-left: 4px solid var(--accent);
    border-radius: 10px;
    padding: 0.9rem 1rem;
  }
  .why .head { font-weight: 650; margin-bottom: 0.45rem; }
  .why p { margin: 0.3rem 0; font-size: 0.88rem; color: var(--muted); }
  .fl {
    display: flex;
    gap: 0.55rem;
    padding: 0.4rem 0;
    border-top: 1px solid #1e293b;
    font-size: 0.88rem;
  }
  .pts { min-width: 2.5rem; font-weight: 700; color: var(--yellow); }
  .role { font-size: 0.7rem; text-transform: uppercase; color: var(--muted); }
  .role.blocker { color: var(--red); }
  .role.caution { color: var(--yellow); }
  .role.positive { color: var(--green); }
  .links { margin-top: 1.75rem; font-size: 0.82rem; color: var(--muted); }
  .links a { color: #60a5fa; text-decoration: none; margin-right: 0.9rem; }
  .links a:hover { text-decoration: underline; }
  @keyframes shimmer {
    0% { background-position: -600px 0; }
    100% { background-position: 600px 0; }
  }
  @keyframes rise {
    from { opacity: 0; transform: translateY(8px); }
    to { opacity: 1; transform: none; }
  }
  @keyframes pop {
    0% { opacity: 0; transform: scale(0.85); }
    70% { transform: scale(1.06); }
    100% { opacity: 1; transform: scale(1); }
  }
  .sk {
    background: linear-gradient(90deg, #141a2a 0%, #1f2848 50%, #141a2a 100%);
    background-size: 1200px 100%;
    animation: shimmer 1.4s linear infinite;
    border-radius: 8px;
  }
  .sk-line { height: 0.85rem; margin: 0.55rem 0; }
  .sk-l60 { width: 60%; }
  .sk-l90 { width: 90%; }
  .sk-badge { display: inline-block; width: 4.6rem; height: 1.5rem; border-radius: 9999px; }
  .sk-title { display: inline-block; width: 8rem; height: 1.3rem; margin-left: 0.5rem; vertical-align: middle; }
  .sk-metric { height: 3.2rem; border-radius: 10px; }
  .enter { animation: rise 0.35s ease-out both; }
  .enter .metric { animation: rise 0.4s ease-out both; }
  .enter .metric:nth-child(2) { animation-delay: 0.05s; }
  .enter .metric:nth-child(3) { animation-delay: 0.1s; }
  .enter .metric:nth-child(4) { animation-delay: 0.15s; }
  .enter .metric:nth-child(5) { animation-delay: 0.2s; }
  .badge.pop { animation: pop 0.4s ease-out 0.1s both; }
  @media (prefers-reduced-motion: reduce) {
    .sk { animation: none; }
    .enter, .enter .metric, .badge.pop { animation: none !important; }
  }
  @media (max-width: 480px) {
    .row { flex-direction: column; }
    .row button { width: 100%; }
  }
</style>
</head>
<body>
<div class="wrap">
  <h1>TVibex402 playground</h1>
  <p class="sub">Paste a Solana token mint → verdict, reasons, holder quality &amp; sell-cost check</p>

  <div class="disclaimer">
    Heuristic only — not a security audit and not financial advice. Data can be late or wrong.
  </div>

  <div class="row">
    <input id="mint" type="text" placeholder="Token mint address" autocomplete="off" spellcheck="false">
    <button id="btn" type="button">Check</button>
  </div>

  <div class="chips">
    <span class="chip" data-mint="So11111111111111111111111111111111111111112">SOL</span>
    <span class="chip" data-mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v">USDC</span>
  </div>

  <div id="result"></div>

  <p class="links">
    <a href="/">Home</a>
    <a href="/status">Status</a>
    <a href="/accuracy">Accuracy</a>
    <a href="/docs">API docs</a>
    <a href="/methodology">Methodology</a>
    <a href="/pricing">Pricing</a>
  </p>
</div>

<script>
(function () {
  var MINT_RE = /^[1-9A-HJ-NP-Za-km-z]{32,44}$/;
  var out = document.getElementById('result');
  var input = document.getElementById('mint');
  var btn = document.getElementById('btn');
  var lang = ((navigator.language || 'en').toLowerCase().indexOf('vi') === 0) ? 'vi' : 'en';
  var last = null;

  function el(tag, text, cls) {
    var n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function badge(v) {
    var known = ['ok', 'caution', 'avoid'].indexOf(v) >= 0;
    return el('span', v || 'unknown', 'badge ' + (known ? v : 'unknown'));
  }
  function usd(x) {
    var n = Number(x);
    return isFinite(n) ? '$' + n.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—';
  }
  function price(x) {
    var n = Number(x);
    return isFinite(n) && n > 0 ? '$' + n.toPrecision(4) : '—';
  }
  function age(min) {
    var m = Number(min);
    if (!isFinite(m) || m < 0) return '—';
    var h = m / 60;
    return h < 48 ? Math.floor(h) + ' h' : Math.floor(h / 24) + ' d';
  }
  function metric(label, value) {
    var d = el('div', null, 'metric');
    d.appendChild(el('div', label, 'l'));
    d.appendChild(el('div', value, 'v'));
    return d;
  }
  function list(items, none) {
    var ul = el('ul');
    var arr = Array.isArray(items) ? items : [];
    if (!arr.length) ul.appendChild(el('li', none || '—', 'meta'));
    arr.slice(0, 10).forEach(function (x) { ul.appendChild(el('li', x)); });
    return ul;
  }
  function sk(cls) { return el('div', null, 'sk ' + cls); }

  function showSkeleton() {
    clear(out);
    out.setAttribute('aria-busy', 'true');
    var card = el('div', null, 'card');
    var head = el('div', null, 'verdict');
    head.appendChild(sk('sk-badge'));
    head.appendChild(sk('sk-title'));
    card.appendChild(head);
    card.appendChild(sk('sk-line sk-l90'));
    var grid = el('div', null, 'grid');
    for (var i = 0; i < 5; i++) grid.appendChild(sk('sk-metric'));
    card.appendChild(grid);
    card.appendChild(sk('sk-line sk-l60'));
    card.appendChild(sk('sk-line sk-l90'));
    out.appendChild(card);
  }

  function section(card, title, node) {
    card.appendChild(el('h3', title));
    card.appendChild(node);
  }

  function whyBox(xp) {
    var box = el('div');
    var e = xp && xp[lang];
    if (!e) return box;
    box.appendChild(el('h3', lang === 'vi' ? 'Vì sao có kết quả này' : 'Why this verdict'));
    var tabs = el('div', null, 'tabs');
    [['en', 'English'], ['vi', 'Tiếng Việt']].forEach(function (t) {
      var b = el('button', t[1], 'tab' + (lang === t[0] ? ' on' : ''));
      b.type = 'button';
      b.addEventListener('click', function () {
        lang = t[0];
        if (last) render(last.d, last.ex, last.xp, true);
      });
      tabs.appendChild(b);
    });
    box.appendChild(tabs);
    var w = el('div', null, 'why');
    w.appendChild(el('div', e.headline, 'head'));
    (e.why || []).forEach(function (x) { w.appendChild(el('p', x)); });
    (e.flags || []).slice(0, 12).forEach(function (f) {
      var row = el('div', null, 'fl');
      row.appendChild(el('div', f.counted ? '+' + f.points : '—', 'pts'));
      var body = el('div');
      body.appendChild(el('div', f.text));
      var rc = ['blocker', 'caution', 'positive'].indexOf(f.role) >= 0 ? f.role : '';
      body.appendChild(el('div', f.flag + ' · ' + f.role + (f.counted ? '' : ' (not scored)'), 'role ' + rc));
      row.appendChild(body);
      w.appendChild(row);
    });
    (e.what_would_change || []).forEach(function (x) { w.appendChild(el('p', x)); });
    if (e.note) w.appendChild(el('p', e.note));
    box.appendChild(w);
    return box;
  }

  function render(d, ex, xp, still) {
    last = { d: d, ex: ex, xp: xp };
    clear(out);
    out.setAttribute('aria-busy', 'false');
    var dec = d.decision || {};
    var hq = d.holder_quality || {};
    var card = el('div', null, still ? 'card' : 'card enter');

    var head = el('div', null, 'verdict');
    var vb = badge(d.verdict);
    if (!still) vb.className += ' pop';
    head.appendChild(vb);
    head.appendChild(el('span', (d.token || d.name || 'token') + (d.risk_score != null ? ' · risk ' + d.risk_score + '/100' : '')));
    card.appendChild(head);

    card.appendChild(el('p', d.summary || '', 'summary'));
    card.appendChild(el('p', (d.mint || ''), 'meta'));

    var grid = el('div', null, 'grid');
    grid.appendChild(metric('Risk score', (d.risk_score !== undefined ? d.risk_score : '—') + ' / 100'));
    grid.appendChild(metric('Liquidity', usd(d.liquidity_usd)));
    grid.appendChild(metric('Price', price(d.price_usd)));
    grid.appendChild(metric('Pair age', age(d.pair_age_minutes)));
    grid.appendChild(metric('Holder quality', (hq.score !== undefined ? hq.score : '—') + ' / 100'));
    card.appendChild(grid);

    card.appendChild(whyBox(xp));

    var cols = el('div', null, 'grid');
    [['Blockers', dec.blockers], ['Cautions', dec.cautions], ['Positives', dec.positives], ['Unknown', dec.unknowns]].forEach(function (c) {
      var box = el('div');
      box.appendChild(el('h3', c[0]));
      box.appendChild(list(c[1], '—'));
      cols.appendChild(box);
    });
    card.appendChild(cols);

    var flags = el('div');
    (Array.isArray(d.flags) ? d.flags : []).slice(0, 24).forEach(function (f) {
      flags.appendChild(el('span', f, 'flag'));
    });
    if (flags.firstChild) section(card, 'Flags', flags);

    var exitBox = el('div');
    if (ex && ex.exit && ex.exit.available) {
      exitBox.appendChild(el('p', 'Grade: ' + (ex.exit.grade || '—') + ' · combined: ' + (ex.combined_verdict || '—')));
      var ul = el('ul');
      (ex.exit.levels || []).forEach(function (l) {
        var loss = Number(l.loss_vs_market_pct);
        ul.appendChild(el('li',
          'Sell ' + usd(l.size_usd) + ': ' +
          (isFinite(loss) ? loss.toFixed(1) + '% below market' : (l.status || 'no quote'))
        ));
      });
      exitBox.appendChild(ul);
      exitBox.appendChild(el('p', 'A quote does not prove a real sell will succeed.', 'meta'));
    } else {
      exitBox.appendChild(el('p', 'Exit check not available for this token right now.', 'meta'));
    }
    section(card, 'Sell cost (Jupiter)', exitBox);

    section(card, 'Next steps', list(d.suggested_next || dec.next_checks, '—'));
    card.appendChild(el('p', dec.disclaimer || 'Heuristic output, not financial advice.', 'meta'));

    var det = el('details');
    det.appendChild(el('summary', 'Raw JSON'));
    det.appendChild(el('pre', JSON.stringify(d, null, 2)));
    card.appendChild(det);

    out.appendChild(card);
  }

  function showError(msg) {
    clear(out);
    out.setAttribute('aria-busy', 'false');
    var c = el('div', null, 'card');
    c.appendChild(el('p', msg, 'err'));
    out.appendChild(c);
  }

  function getJson(url) {
    return fetch(url, { cache: 'no-store' }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (b) {
        return { ok: r.ok, status: r.status, retry: r.headers.get('Retry-After'), body: b };
      });
    });
  }

  function check() {
    var mint = input.value.trim();
    if (!MINT_RE.test(mint)) {
      showError('That does not look like a Solana token address. Paste a mint (32–44 base58 characters).');
      return;
    }
    btn.disabled = true;
    btn.textContent = '…';
    showSkeleton();
    var q = encodeURIComponent(mint);

    Promise.all([
      getJson('/signal?mint=' + q),
      getJson('/exit?mint=' + q + '&sizes=100,1000'),
      getJson('/signal?mint=' + q + '&explain=1').catch(function () { return { ok: false, body: {} }; })
    ]).then(function (res) {
      var sig = res[0], ex = res[1], xp = res[2];
      if (!sig.ok) {
        var msg = (sig.body && (sig.body.detail || sig.body.message)) || ('HTTP ' + sig.status);
        if (sig.status === 429) msg = 'Rate limited. Retry after ' + (sig.retry || 'a few') + 's.';
        if (sig.status === 503) msg = 'Service temporarily unavailable (host may be sleeping). Retry in a few seconds.';
        showError(msg);
        return;
      }
      render(sig.body, ex.ok ? ex.body : null, (xp.ok && xp.body && xp.body.explain) ? xp.body.explain : null);
    }).catch(function (e) {
      showError(e.message || 'Network error');
    }).finally(function () {
      btn.disabled = false;
      btn.textContent = 'Check';
    });
  }

  btn.addEventListener('click', check);
  input.addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') check();
  });

  document.querySelectorAll('.chip').forEach(function (c) {
    c.addEventListener('click', function () {
      input.value = c.getAttribute('data-mint');
      check();
    });
  });

  var preset = new URLSearchParams(window.location.search).get('mint');
  if (preset && MINT_RE.test(preset.trim())) {
    input.value = preset.trim();
    check();
  }
})();
</script>
</body>
</html>"""

@app.get("/play", include_in_schema=False)
async def playground():
    return HTMLResponse(PLAY_HTML, headers={"Cache-Control": "no-cache"})

print(f"[part26] v{VERSION} playground ready at /play (share a token with /play?mint=<address>)")
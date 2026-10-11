# ---------- part26: v2.13.0 - /play: a small web page to check any Solana token in the browser ----------
# Loads before part7. One route, no new dependency. It calls the public /signal and /exit endpoints, so the usual rate limits
# apply. Everything that comes from the network is shown with textContent (never innerHTML): token names are chosen by
# whoever creates the token and must be treated as hostile text.
VERSION = "2.13.1"
app.version = VERSION
app.openapi_schema = None

PLAY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TVibex402 playground</title>
<style>
  :root { --bg:#0b0f19; --card:#151a28; --border:#2d3348; --text:#e2e8f0; --muted:#94a3b8; --accent:#6366f1; --green:#22c55e; --yellow:#eab308; --red:#ef4444; --grey:#64748b; }
  * { box-sizing:border-box; }
  body { font-family:system-ui, sans-serif; background:var(--bg); color:var(--text); margin:0; padding:1rem; }
  .wrap { max-width:760px; margin:0 auto; }
  h1 { font-size:1.5rem; margin:.25rem 0; }
  .muted { color:var(--muted); font-size:.85rem; }
  .row { display:flex; gap:.5rem; margin:1rem 0; }
  input { flex:1; min-width:0; background:var(--card); border:1px solid var(--border); border-radius:10px; padding:.8rem; color:var(--text); font-size:1rem; }
  button { background:var(--accent); color:#fff; border:0; border-radius:10px; padding:0 1.2rem; font-weight:600; font-size:.95rem; }
  button:disabled { opacity:.5; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:14px; padding:1.1rem; margin-bottom:1rem; }
  .verdict { display:flex; align-items:center; gap:.6rem; font-size:1.2rem; font-weight:700; flex-wrap:wrap; }
  .badge { display:inline-block; padding:.2rem .65rem; border-radius:9999px; font-size:.75rem; font-weight:700; text-transform:uppercase; }
  .ok { background:var(--green); color:#052e16; } .caution { background:var(--yellow); color:#422006; }
  .avoid { background:var(--red); color:#450a0a; } .unknown { background:var(--grey); color:#f1f5f9; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(140px, 1fr)); gap:.6rem; margin:.9rem 0; }
  .metric { background:#0f131f; border-radius:10px; padding:.7rem; }
  .metric .l { color:var(--muted); font-size:.75rem; } .metric .v { font-size:1.05rem; font-weight:600; }
  h3 { font-size:.8rem; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; margin:1rem 0 .3rem; }
  ul { margin:.2rem 0; padding-left:1.1rem; } li { margin:.2rem 0; font-size:.92rem; }
  .flag { display:inline-block; background:#1e2433; border:1px solid var(--border); border-radius:6px; padding:.1rem .5rem; font-size:.78rem; margin:.15rem .2rem .15rem 0; }
  .err { color:var(--red); }
  pre { background:#0f131f; border-radius:10px; padding:.8rem; overflow-x:auto; font-size:.75rem; max-height:300px; }
  .tabs { display:flex; gap:.4rem; margin:.3rem 0 .6rem; }
  .tab { background:#0f131f; color:var(--muted); border:1px solid var(--border); border-radius:8px; padding:.3rem .8rem; font-size:.8rem; }
  .tab.on { background:var(--accent); color:#fff; border-color:var(--accent); }
  .why { background:#0f131f; border-left:4px solid var(--accent); border-radius:10px; padding:.9rem 1rem; }
  .why .head { font-weight:650; margin-bottom:.5rem; }
  .why p { margin:.35rem 0; }
  .fl { display:flex; gap:.6rem; padding:.4rem 0; border-top:1px solid #1e293b; font-size:.9rem; }
  .pts { min-width:2.6rem; font-weight:700; color:var(--yellow); }
  .role { font-size:.72rem; text-transform:uppercase; color:var(--muted); }
  .role.blocker { color:var(--red); } .role.caution { color:var(--yellow); } .role.positive { color:var(--green); }
  a { color:#60a5fa; }
</style>
</head>
<body>
<div class="wrap">
  <h1>TVibex402 playground</h1>
  <p class="muted">Paste a Solana token address to see the verdict, the reasons and a sell-cost check. A heuristic, not a security audit and not advice.</p>
  <div class="row">
    <input id="mint" type="text" placeholder="Token mint address" autocomplete="off" spellcheck="false" value="So11111111111111111111111111111111111111112">
    <button id="btn" type="button">Check</button>
  </div>
  <div id="result"></div>
  <p class="muted"><a href="/status">Status</a> - <a href="/accuracy">Track record</a> - <a href="/docs">API docs</a></p>
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
    if (text !== undefined && text !== null) { n.textContent = String(text); }
    if (cls) { n.className = cls; }
    return n;
  }
  function clear(n) { while (n.firstChild) { n.removeChild(n.firstChild); } }
  function badge(v) {
    var known = ['ok', 'caution', 'avoid'].indexOf(v) >= 0;
    return el('span', v || 'unknown', 'badge ' + (known ? v : 'unknown'));
  }
  function usd(x) { var n = Number(x); return isFinite(n) ? '$' + n.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '-'; }
  function price(x) { var n = Number(x); return isFinite(n) && n > 0 ? '$' + n.toPrecision(4) : '-'; }
  function age(min) {
    var m = Number(min);
    if (!isFinite(m) || m < 0) { return '-'; }
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
    if (!arr.length) { ul.appendChild(el('li', none, 'muted')); }
    arr.slice(0, 8).forEach(function (x) { ul.appendChild(el('li', x)); });
    return ul;
  }
  function section(card, title, node) { card.appendChild(el('h3', title)); card.appendChild(node); }

  function whyBox(xp) {
    var box = el('div');
    var e = xp && xp[lang];
    if (!e) { return box; }
    box.appendChild(el('h3', lang === 'vi' ? 'Vì sao có kết quả này' : 'Why this verdict'));
    var tabs = el('div', null, 'tabs');
    [['en', 'English'], ['vi', 'Tiếng Việt']].forEach(function (t) {
      var b = el('button', t[1], 'tab' + (lang === t[0] ? ' on' : ''));
      b.type = 'button';
      b.addEventListener('click', function () { lang = t[0]; if (last) { render(last.d, last.ex, last.xp); } });
      tabs.appendChild(b);
    });
    box.appendChild(tabs);
    var w = el('div', null, 'why');
    w.appendChild(el('div', e.headline, 'head'));
    (e.why || []).forEach(function (x) { w.appendChild(el('p', x, 'muted')); });
    (e.flags || []).slice(0, 12).forEach(function (f) {
      var row = el('div', null, 'fl');
      row.appendChild(el('div', f.counted ? '+' + f.points : '-', 'pts'));
      var body = el('div');
      body.appendChild(el('div', f.text));
      var rc = ['blocker', 'caution', 'positive'].indexOf(f.role) >= 0 ? f.role : '';
      body.appendChild(el('div', f.flag + ' - ' + f.role + (f.counted ? '' : ' (not scored for this asset)'), 'role ' + rc));
      row.appendChild(body);
      w.appendChild(row);
    });
    (e.what_would_change || []).forEach(function (x) { w.appendChild(el('p', x, 'muted')); });
    if (e.note) { w.appendChild(el('p', e.note, 'muted')); }
    if (e.language_note) { w.appendChild(el('p', e.language_note, 'muted')); }
    box.appendChild(w);
    return box;
  }

  function render(d, ex, xp) {
    last = { d: d, ex: ex, xp: xp };
    clear(out);
    var dec = d.decision || {};
    var hq = d.holder_quality || {};
    var card = el('div', null, 'card');
    var head = el('div', null, 'verdict');
    head.appendChild(badge(d.verdict));
    head.appendChild(el('span', d.token || d.name || 'token'));
    card.appendChild(head);
    card.appendChild(el('p', d.summary || '', 'muted'));
    var grid = el('div', null, 'grid');
    grid.appendChild(metric('Risk score', (d.risk_score !== undefined ? d.risk_score : '-') + ' / 100'));
    grid.appendChild(metric('Liquidity', usd(d.liquidity_usd)));
    grid.appendChild(metric('Price', price(d.price_usd)));
    grid.appendChild(metric('Pair age', age(d.pair_age_minutes)));
    grid.appendChild(metric('Holder quality', (hq.score !== undefined ? hq.score : '-') + ' / 100'));
    card.appendChild(grid);
    card.appendChild(whyBox(xp));
    var cols = el('div', null, 'grid');
    [['Blockers', dec.blockers], ['Cautions', dec.cautions], ['Positives', dec.positives], ['Unknown', dec.unknowns]].forEach(function (c) {
      var box = el('div');
      box.appendChild(el('h3', c[0]));
      box.appendChild(list(c[1], '-'));
      cols.appendChild(box);
    });
    card.appendChild(cols);
    var flags = el('div');
    (Array.isArray(d.flags) ? d.flags : []).slice(0, 20).forEach(function (f) { flags.appendChild(el('span', f, 'flag')); });
    if (flags.firstChild) { section(card, 'Flags', flags); }
    var exitBox = el('div');
    if (ex && ex.exit && ex.exit.available) {
      exitBox.appendChild(el('p', 'Grade: ' + (ex.exit.grade || '-') + ' - combined verdict: ' + (ex.combined_verdict || '-')));
      var ul = el('ul');
      (ex.exit.levels || []).forEach(function (l) {
        var loss = Number(l.loss_vs_market_pct);
        ul.appendChild(el('li', 'Selling ' + usd(l.size_usd) + ': ' + (isFinite(loss) ? loss.toFixed(1) + '% below market' : (l.status || 'no quote'))));
      });
      exitBox.appendChild(ul);
      exitBox.appendChild(el('p', 'A quote does not prove a real sell will succeed.', 'muted'));
    } else {
      exitBox.appendChild(el('p', 'Exit check not available for this token right now.', 'muted'));
    }
    section(card, 'Sell cost (Jupiter quote)', exitBox);
    section(card, 'Next steps', list(d.suggested_next || dec.next_checks, '-'));
    card.appendChild(el('p', dec.disclaimer || 'Heuristic output, not financial advice.', 'muted'));
    var det = el('details');
    det.appendChild(el('summary', 'Raw JSON'));
    det.appendChild(el('pre', JSON.stringify(d, null, 2)));
    card.appendChild(det);
    out.appendChild(card);
  }

  function showError(msg) {
    clear(out);
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
    if (!MINT_RE.test(mint)) { showError('That does not look like a Solana token address.'); return; }
    btn.disabled = true;
    btn.textContent = '...';
    clear(out);
    out.appendChild(el('p', 'Loading...', 'muted'));
    var q = encodeURIComponent(mint);
    Promise.all([getJson('/signal?mint=' + q), getJson('/exit?mint=' + q + '&sizes=100,1000'), getJson('/explain?mint=' + q + '&lang=both')])
      .then(function (res) {
        var s = res[0], e = res[1], x = res[2];
        if (!s.ok) {
          if (s.status === 429) { showError('Too many requests. Try again in ' + (s.retry || 'a few') + ' seconds.'); }
          else { showError(typeof s.body.detail === 'string' ? s.body.detail : 'Could not get data for this token (HTTP ' + s.status + ').'); }
          return;
        }
        render(s.body, e.ok ? e.body : null, x.ok && x.body ? x.body.explanation : null);
      })
      .catch(function () { showError('Network error. Please try again.'); })
      .then(function () { btn.disabled = false; btn.textContent = 'Check'; });
  }

  btn.addEventListener('click', check);
  input.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') { check(); } });
  var preset = new URLSearchParams(window.location.search).get('mint');
  if (preset && MINT_RE.test(preset.trim())) { input.value = preset.trim(); check(); }
})();
</script>
</body>
</html>"""


@app.get("/play", include_in_schema=False)
async def playground():
    return HTMLResponse(PLAY_HTML, headers={"Cache-Control": "no-cache"})


print(f"[part26] v{VERSION} playground ready at /play (share a token with /play?mint=<address>)")

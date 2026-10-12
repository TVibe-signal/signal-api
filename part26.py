# ---------- part26: v2.13.4 - /play: polished playground for any Solana token ----------
# Loads before part7. One route, no new dependency. Calls public /signal + /exit (rate limits apply).
# All network text is rendered with textContent (never innerHTML) — token names are hostile.
VERSION = "2.13.4"
app.version = VERSION
app.openapi_schema = None

PLAY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#080b12">
<meta name="color-scheme" content="dark">
<title>TVibex402 playground</title>
<style>
:root {
  --bg: #080b12;
  --bg2: #0d111c;
  --card: #121826;
  --border: #1e2738;
  --border-light: #2a3548;
  --text: #e8eef7;
  --muted: #8b9bb4;
  --accent: #6366f1;
  --accent-soft: rgba(99, 102, 241, 0.15);
  --green: #34d399;
  --yellow: #fbbf24;
  --red: #f87171;
  --grey: #64748b;
  --radius: 14px;
  --shadow: 0 4px 24px rgba(0,0,0,0.35);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background: var(--bg);
  background-image:
    radial-gradient(ellipse 80% 50% at 50% -20%, rgba(99,102,241,0.12), transparent),
    radial-gradient(ellipse 60% 40% at 100% 0%, rgba(34,197,94,0.04), transparent);
  color: var(--text);
  line-height: 1.55;
  min-height: 100vh;
  padding: 1.5rem 1rem 4rem;
}
.wrap { max-width: 680px; margin: 0 auto; }
h1 {
  font-size: 1.55rem;
  font-weight: 700;
  letter-spacing: -0.03em;
  margin-bottom: 0.25rem;
  background: linear-gradient(135deg, #e8eef7 0%, #a5b4fc 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.sub { color: var(--muted); font-size: 0.88rem; margin-bottom: 1.4rem; }
.disclaimer {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.65rem 0.9rem;
  font-size: 0.8rem;
  color: var(--muted);
  margin-bottom: 1.35rem;
  line-height: 1.45;
}
.row {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.7rem;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 0.35rem;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.row:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
input {
  flex: 1;
  min-width: 0;
  background: transparent;
  border: 0;
  padding: 0.7rem 0.85rem;
  color: var(--text);
  font-size: 0.92rem;
  outline: none;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
button {
  background: var(--accent);
  color: #fff;
  border: 0;
  border-radius: 9px;
  padding: 0 1.3rem;
  font-weight: 600;
  font-size: 0.9rem;
  cursor: pointer;
  min-height: 42px;
  transition: background 0.15s, transform 0.1s;
}
button:hover { background: #4f46e5; }
button:active { transform: scale(0.97); }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 1.6rem; }
.chip {
  background: var(--card);
  border: 1px solid var(--border);
  color: var(--muted);
  padding: 0.32rem 0.8rem;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.chip:hover {
  border-color: var(--accent);
  color: var(--text);
  background: var(--accent-soft);
}
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.25rem;
  margin-bottom: 1rem;
  box-shadow: var(--shadow);
}
.verdict {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  flex-wrap: wrap;
  margin-bottom: 0.55rem;
}
.badge {
  display: inline-block;
  padding: 0.22rem 0.75rem;
  border-radius: 9999px;
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.ok { background: rgba(52,211,153,0.15); color: var(--green); border: 1px solid rgba(52,211,153,0.25); }
.caution { background: rgba(251,191,36,0.15); color: var(--yellow); border: 1px solid rgba(251,191,36,0.25); }
.avoid { background: rgba(248,113,113,0.15); color: var(--red); border: 1px solid rgba(248,113,113,0.25); }
.unknown { background: rgba(100,116,139,0.2); color: #cbd5e1; border: 1px solid rgba(100,116,139,0.3); }
.summary { font-size: 0.93rem; margin-bottom: 0.2rem; line-height: 1.5; }
.meta { color: var(--muted); font-size: 0.8rem; word-break: break-all; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(125px, 1fr));
  gap: 0.5rem;
  margin: 1rem 0;
}
.metric {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 0.75rem 0.85rem;
  transition: border-color 0.15s;
}
.metric:hover { border-color: var(--border-light); }
.metric .l {
  color: var(--muted);
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-bottom: 0.2rem;
}
.metric .v { font-size: 1.08rem; font-weight: 650; letter-spacing: -0.01em; }
h3 {
  font-size: 0.72rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 1.15rem 0 0.4rem;
  font-weight: 600;
}
ul { margin: 0.15rem 0; padding-left: 1.1rem; }
li { margin: 0.22rem 0; font-size: 0.88rem; color: #c8d0e0; }
.flag {
  display: inline-block;
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.18rem 0.55rem;
  font-size: 0.74rem;
  margin: 0.15rem 0.2rem 0.15rem 0;
  color: var(--muted);
}
.err { color: var(--red); font-size: 0.92rem; }
pre {
  background: var(--bg2);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 0.85rem;
  overflow-x: auto;
  font-size: 0.7rem;
  max-height: 260px;
  margin-top: 0.5rem;
  color: #94a3b8;
}
details { margin-top: 1rem; }
summary { cursor: pointer; color: var(--muted); font-size: 0.82rem; user-select: none; }
summary:hover { color: var(--text); }
.why {
  background: var(--bg2);
  border-left: 3px solid var(--accent);
  border-radius: 0 10px 10px 0;
  padding: 0.9rem 1rem;
  margin-top: 0.4rem;
}
.why .head { font-weight: 650; margin-bottom: 0.45rem; font-size: 0.95rem; }
.why p { margin: 0.3rem 0; font-size: 0.88rem; color: var(--muted); }
.fl {
  display: flex;
  gap: 0.6rem;
  padding: 0.45rem 0;
  border-top: 1px solid var(--border);
  font-size: 0.88rem;
}
.pts { min-width: 2.5rem; font-weight: 700; color: var(--yellow); font-size: 0.9rem; }
.role { font-size: 0.7rem; text-transform: uppercase; color: var(--muted); margin-top: 0.1rem; }
.role.blocker { color: var(--red); }
.role.caution { color: var(--yellow); }
.role.positive { color: var(--green); }
.tabs { display: flex; gap: 0.35rem; margin: 0.3rem 0 0.55rem; }
.tab {
  background: var(--bg2);
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.28rem 0.75rem;
  font-size: 0.78rem;
  cursor: pointer;
  transition: all 0.15s;
}
.tab.on, .tab:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
.links {
  margin-top: 2rem;
  font-size: 0.8rem;
  color: var(--muted);
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem 1rem;
}
.links a { color: #818cf8; text-decoration: none; }
.links a:hover { color: #a5b4fc; text-decoration: underline; }
@keyframes shimmer {
  0% { background-position: -600px 0; }
  100% { background-position: 600px 0; }
}
@keyframes rise {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: none; }
}
@keyframes pop {
  0% { opacity: 0; transform: scale(0.82); }
  70% { transform: scale(1.05); }
  100% { opacity: 1; transform: scale(1); }
}
.sk {
  background: linear-gradient(90deg, #121826 0%, #1c2438 50%, #121826 100%);
  background-size: 1200px 100%;
  animation: shimmer 1.4s linear infinite;
  border-radius: 8px;
}
.sk-line { height: 0.8rem; margin: 0.5rem 0; }
.sk-l60 { width: 60%; }
.sk-l90 { width: 90%; }
.sk-badge { display: inline-block; width: 4.5rem; height: 1.45rem; border-radius: 9999px; }
.sk-title { display: inline-block; width: 7.5rem; height: 1.25rem; margin-left: 0.5rem; vertical-align: middle; }
.sk-metric { height: 3.1rem; border-radius: 11px; }
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
  .row { flex-direction: column; padding: 0.4rem; }
  .row button { width: 100%; }
  body { padding: 1.1rem 0.75rem 3rem; }
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
    <input id="mint" type="text" placeholder="Paste Solana mint address…" autocomplete="off" spellcheck="false">
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
"""

@app.get("/play", include_in_schema=False)
async def playground():
    return HTMLResponse(PLAY_HTML, headers={"Cache-Control": "no-cache"})

print(f"[part26] v{VERSION} playground ready at /play (share a token with /play?mint=<address>)")

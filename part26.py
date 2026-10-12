# ---------- part26: v2.13.6 - /play: polished playground for any Solana token ----------
# Loads before part7. One route, no new dependency. Calls public /signal + /exit (rate limits apply).
# All network text is rendered with textContent (never innerHTML) — token names are hostile.
VERSION = "2.13.6"
app.version = VERSION
app.openapi_schema = None

PLAY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#070a10">
<meta name="color-scheme" content="dark">
<title>TVibex402 playground</title>
<style>
@property --p { syntax: "<number>"; inherits: false; initial-value: 0; }
:root {
  --bg: #070a10; --surface: #0f1521; --raised: #151d2d; --line: #222d42; --line2: #34425e;
  --text: #eef2f8; --muted: #8fa0bb; --accent: #7c83ff; --accent-soft: rgba(124,131,255,.16);
  --ok: #2dd4a0; --caution: #f5b83d; --avoid: #ff5d6c; --unknown: #7d8aa3;
  --track: #1b2437; --radius: 16px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  background-image: radial-gradient(ellipse 70% 40% at 50% -10%, rgba(124,131,255,.16), transparent);
  background-repeat: no-repeat;
  color: var(--text); line-height: 1.55; min-height: 100vh; padding: 1.75rem 1rem 4rem;
}
.wrap { max-width: 700px; margin: 0 auto; }
h1 { font-size: 1.7rem; font-weight: 750; letter-spacing: -.03em; }
h1 span { color: var(--accent); }
.sub { color: var(--muted); font-size: .92rem; margin: .2rem 0 1.2rem; }
.disclaimer {
  font-size: .8rem; color: var(--muted); margin-bottom: 1.3rem;
  padding: .55rem .85rem; border-left: 3px solid var(--caution);
  background: rgba(245,184,61,.06); border-radius: 0 10px 10px 0;
}
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.row {
  display: flex; gap: .5rem; padding: .4rem; margin-bottom: .75rem;
  background: var(--surface); border: 1px solid var(--line2); border-radius: 14px;
  transition: border-color .2s, box-shadow .2s;
}
.row:focus-within { border-color: var(--accent); box-shadow: 0 0 0 4px var(--accent-soft); }
input {
  flex: 1; min-width: 0; background: transparent; border: 0; outline: none; color: var(--text);
  padding: .75rem .85rem; font-size: .95rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
button {
  background: var(--accent); color: #fff; border: 0; border-radius: 10px; padding: 0 1.5rem;
  font-weight: 650; font-size: .95rem; cursor: pointer; min-height: 44px;
  transition: filter .15s, transform .1s;
}
button:hover { filter: brightness(1.12); }
button:active { transform: scale(.97); }
button:disabled { opacity: .5; cursor: not-allowed; }
.chips { display: flex; align-items: center; flex-wrap: wrap; gap: .4rem; margin-bottom: 1.6rem; font-size: .8rem; color: var(--muted); }
.chip {
  background: var(--surface); border: 1px solid var(--line); color: var(--text);
  padding: .3rem .85rem; border-radius: 999px; font-size: .8rem; font-weight: 550; cursor: pointer;
  min-height: 0; transition: border-color .15s, background .15s;
}
.chip:hover { border-color: var(--accent); background: var(--accent-soft); filter: none; }

/* verdict colour system: every card/group sets --vc (main), --vs (tint), --vb (border) */
.v-ok, .g-ok { --vc: var(--ok); --vs: rgba(45,212,160,.14); --vb: rgba(45,212,160,.4); }
.v-caution, .g-caution { --vc: var(--caution); --vs: rgba(245,184,61,.14); --vb: rgba(245,184,61,.4); }
.v-avoid, .g-avoid { --vc: var(--avoid); --vs: rgba(255,93,108,.15); --vb: rgba(255,93,108,.45); }
.v-unknown, .g-unknown { --vc: var(--unknown); --vs: rgba(125,138,163,.14); --vb: rgba(125,138,163,.35); }

.card {
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius);
  padding: 1.25rem; margin-bottom: 1rem;
}
.card.hero { background: linear-gradient(150deg, var(--vs), transparent 60%), var(--surface); border-color: var(--vb); }
.top { display: flex; align-items: center; gap: 1.1rem; }
.ring {
  --p: 0; flex: none; position: relative; width: 96px; height: 96px; border-radius: 50%;
  display: grid; place-items: center; text-align: center;
  background: conic-gradient(var(--vc) calc(var(--p) * 1%), var(--track) 0);
  transition: --p 1.1s cubic-bezier(.2, .8, .2, 1);
}
.ring::before { content: ""; position: absolute; inset: 9px; border-radius: 50%; background: var(--surface); }
.ring div { position: relative; line-height: 1.1; }
.ring b { display: block; font-size: 1.7rem; font-weight: 750; font-variant-numeric: tabular-nums; }
.ring small { font-size: .68rem; color: var(--muted); }
.vword { display: flex; align-items: center; gap: .55rem; font-size: 2rem; font-weight: 800; letter-spacing: -.03em; color: var(--vc); line-height: 1.1; }
.vicon {
  display: inline-grid; place-items: center; width: 1.7rem; height: 1.7rem; border-radius: 50%;
  background: var(--vc); color: var(--bg); font-size: 1rem; font-weight: 800;
}
.tname { font-weight: 600; margin-top: .25rem; }
.summary { font-size: .95rem; margin: 1rem 0 .3rem; }
.meta { color: var(--muted); font-size: .78rem; word-break: break-all; font-family: ui-monospace, Menlo, monospace; }
.note { color: var(--muted); font-size: .8rem; }

.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(135px, 1fr)); gap: .55rem; margin: 1.1rem 0 .4rem; }
.metric { background: var(--raised); border: 1px solid var(--line); border-radius: 12px; padding: .75rem .9rem; border-top: 3px solid var(--line2); }
.metric .l { color: var(--muted); font-size: .76rem; margin-bottom: .15rem; }
.metric .v { font-size: 1.15rem; font-weight: 700; font-variant-numeric: tabular-nums; }
.metric.t-ok { border-top-color: var(--ok); }
.metric.t-caution { border-top-color: var(--caution); }
.metric.t-avoid { border-top-color: var(--avoid); }

h3 { font-size: .95rem; font-weight: 700; margin: 1.4rem 0 .55rem; letter-spacing: -.01em; }
.groups { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: .6rem; align-items: start; }
.g-unknown { grid-column: 1 / -1; }
.grp { background: var(--vs); border: 1px solid var(--vb); border-left: 4px solid var(--vc); border-radius: 12px; padding: .75rem .9rem; }
.gh { display: flex; align-items: center; gap: .5rem; font-weight: 700; font-size: .9rem; color: var(--vc); margin-bottom: .3rem; }
.gh i {
  font-style: normal; display: inline-grid; place-items: center; width: 1.2rem; height: 1.2rem;
  border-radius: 50%; background: var(--vc); color: var(--bg); font-size: .72rem; font-weight: 800;
}
.gh em { margin-left: auto; font-style: normal; font-size: .75rem; color: var(--muted); font-weight: 600; }
ul { padding-left: 1.05rem; }
li { margin: .25rem 0; font-size: .88rem; color: #d3dbe9; }
.flag { display: inline-block; background: var(--raised); border: 1px solid var(--line2); border-radius: 8px; padding: .3rem .7rem; font-size: .84rem; font-weight: 550; margin: .2rem .3rem .2rem 0; color: #cdd6e8; }
.acts { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .7rem; }
.ghost { background: var(--raised); border: 1px solid var(--line2); color: var(--muted); min-height: 0; padding: .3rem .85rem; font-size: .78rem; font-weight: 600; border-radius: 8px; }
.ghost:hover { color: var(--text); border-color: var(--accent); filter: none; }

.sellhead { display: flex; align-items: center; gap: .6rem; flex-wrap: wrap; margin-bottom: .6rem; font-size: .88rem; }
.sell { display: grid; grid-template-columns: 5.5rem 1fr 5rem; align-items: center; gap: .7rem; padding: .3rem 0; font-size: .88rem; }
.bar { height: 8px; border-radius: 99px; background: var(--track); overflow: hidden; }
.bar i { display: block; height: 100%; border-radius: 99px; background: var(--vc); }
.sell b { text-align: right; color: var(--vc); font-variant-numeric: tabular-nums; }

.badge { display: inline-block; padding: .18rem .7rem; border-radius: 99px; font-size: .75rem; font-weight: 700; color: var(--vc); background: var(--vs); border: 1px solid var(--vb); }
.err { color: var(--avoid); font-size: .92rem; border-left: 4px solid var(--avoid); padding-left: .8rem; }

pre { background: var(--bg); border: 1px solid var(--line); border-radius: 10px; padding: .85rem; overflow-x: auto; font-size: .72rem; max-height: 260px; margin-top: .5rem; color: #94a3b8; }
details { margin-top: 1.1rem; }
summary { cursor: pointer; color: var(--muted); font-size: .84rem; user-select: none; }
summary:hover { color: var(--text); }
.why { background: var(--raised); border-left: 4px solid var(--accent); border-radius: 0 12px 12px 0; padding: .9rem 1rem; }
.why .head { font-weight: 700; margin-bottom: .45rem; }
.why p { margin: .3rem 0; font-size: .88rem; color: var(--muted); }
.fl { display: flex; gap: .7rem; padding: .5rem 0; border-top: 1px solid var(--line); font-size: .88rem; }
.pts { min-width: 2.6rem; font-weight: 750; color: var(--caution); font-variant-numeric: tabular-nums; }
.role { font-size: .75rem; color: var(--muted); margin-top: .1rem; }
.role.blocker { color: var(--avoid); } .role.caution { color: var(--caution); } .role.positive { color: var(--ok); }
.tabs { display: inline-flex; gap: .2rem; padding: .2rem; margin-bottom: .6rem; background: var(--raised); border: 1px solid var(--line); border-radius: 10px; }
.tab { background: transparent; color: var(--muted); border-radius: 8px; padding: .25rem .8rem; font-size: .8rem; min-height: 0; font-weight: 600; }
.tab.on { background: var(--accent); color: #fff; }
.links { margin-top: 2rem; font-size: .82rem; display: flex; flex-wrap: wrap; gap: .3rem 1.1rem; }
.links a { color: #9aa0ff; text-decoration: none; }
.links a:hover { text-decoration: underline; }

@keyframes shimmer { 0% { background-position: -600px 0; } 100% { background-position: 600px 0; } }
@keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
.sk { background: linear-gradient(90deg, #121826 0%, #1c2438 50%, #121826 100%); background-size: 1200px 100%; animation: shimmer 1.4s linear infinite; border-radius: 10px; }
.sk-ring { width: 96px; height: 96px; border-radius: 50%; flex: none; }
.sk-line { height: .8rem; margin: .55rem 0; } .sk-l60 { width: 60%; } .sk-l90 { width: 90%; }
.sk-metric { height: 3.6rem; border-radius: 12px; }
.enter { animation: rise .4s ease-out both; }
@media (prefers-reduced-motion: reduce) { .sk, .enter { animation: none !important; } .ring { transition: none !important; } }
@media (max-width: 480px) {
  .row { flex-direction: column; } .row button { width: 100%; }
  body { padding: 1.2rem .75rem 3rem; } .vword { font-size: 1.6rem; }
  .sell { grid-template-columns: 4.6rem 1fr 4.2rem; }
}
</style>
</head>
<body>
<div class="wrap">
<h1>TVibex402 <span>playground</span></h1>
<p class="sub">Paste a Solana token address to get a verdict, the reasons behind it, and what it costs to sell.</p>
<div class="disclaimer">Heuristic only. Not a security audit and not financial advice. Data can be late or wrong.</div>
<div class="row">
<input id="mint" type="text" placeholder="Paste Solana mint address…" autocomplete="off" spellcheck="false" aria-label="Solana mint address">
<button id="btn" type="button">Check</button>
</div>
<div class="chips">Try
<button type="button" class="chip" data-mint="So11111111111111111111111111111111111111112">SOL</button>
<button type="button" class="chip" data-mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v">USDC</button>
<span id="recent" style="display:contents"></span>
</div>
<div id="result" aria-live="polite"></div>
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
  var VERDICTS = { ok: ['Looks OK', '✓'], caution: ['Caution', '!'], avoid: ['Avoid', '✕'], unknown: ['Unknown', '?'] };

  function el(tag, text, cls) {
    var n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function vkey(v) { return VERDICTS[v] ? v : 'unknown'; }
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
  function scoreTone(s) {
    var n = Number(s);
    if (!isFinite(n)) return '';
    return n >= 60 ? 't-ok' : n >= 35 ? 't-caution' : 't-avoid';
  }
  function nice(f) { var t = String(f).replace(/_/g, ' '); return t.charAt(0).toUpperCase() + t.slice(1); }
  function gradeKey(g) {
    g = String(g || '').toLowerCase();
    if (['good', 'great', 'excellent', 'a', 'b'].indexOf(g) >= 0) return 'ok';
    if (['fair', 'ok', 'moderate', 'medium', 'c'].indexOf(g) >= 0) return 'caution';
    if (!g || g === '—') return 'unknown';
    return 'avoid';
  }
  function copyBtn(label, text) {
    var b = el('button', label, 'ghost');
    b.type = 'button';
    b.addEventListener('click', function () {
      var done = function (t) { b.textContent = t; setTimeout(function () { b.textContent = label; }, 1400); };
      try { navigator.clipboard.writeText(text).then(function () { done('Copied ✓'); }, function () { done('Copy failed'); }); }
      catch (e) { done('Copy failed'); }
    });
    return b;
  }
  var RKEY = 'tvx402_recent';
  function loadRecent() {
    try { var a = JSON.parse(localStorage.getItem(RKEY) || '[]'); return Array.isArray(a) ? a : []; } catch (e) { return []; }
  }
  function saveRecent(mint, name) {
    if (!mint || !MINT_RE.test(mint)) return;
    var a = loadRecent().filter(function (x) { return x && x.m !== mint; });
    a.unshift({ m: mint, n: String(name || mint.slice(0, 4)).slice(0, 12) });
    try { localStorage.setItem(RKEY, JSON.stringify(a.slice(0, 5))); } catch (e) {}
    drawRecent();
  }
  function drawRecent() {
    var box = document.getElementById('recent');
    clear(box);
    loadRecent().forEach(function (x) {
      if (!x || !MINT_RE.test(String(x.m))) return;
      var c = el('button', x.n, 'chip');
      c.type = 'button';
      c.addEventListener('click', function () { input.value = x.m; check(); });
      box.appendChild(c);
    });
  }
  function lossKey(p) { return p < 3 ? 'ok' : p < 10 ? 'caution' : 'avoid'; }
  function metric(label, value, tone) {
    var d = el('div', null, 'metric ' + (tone || ''));
    d.appendChild(el('div', label, 'l'));
    d.appendChild(el('div', value, 'v'));
    return d;
  }
  function list(items) {
    var ul = el('ul');
    (Array.isArray(items) ? items : []).slice(0, 10).forEach(function (x) { ul.appendChild(el('li', x)); });
    return ul;
  }
  function sk(cls) { return el('div', null, 'sk ' + cls); }

  function showSkeleton() {
    clear(out);
    out.setAttribute('aria-busy', 'true');
    var card = el('div', null, 'card');
    var top = el('div', null, 'top');
    top.appendChild(sk('sk-ring'));
    var side = el('div');
    side.style.flex = '1';
    side.appendChild(sk('sk-line sk-l60'));
    side.appendChild(sk('sk-line sk-l90'));
    top.appendChild(side);
    card.appendChild(top);
    var grid = el('div', null, 'grid');
    for (var i = 0; i < 4; i++) grid.appendChild(sk('sk-metric'));
    card.appendChild(grid);
    card.appendChild(sk('sk-line sk-l90'));
    out.appendChild(card);
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

  function sellBox(ex) {
    var box = el('div');
    if (!(ex && ex.exit && ex.exit.available)) {
      box.appendChild(el('p', 'Sell check is not available for this token right now.', 'note'));
      return box;
    }
    var head = el('div', null, 'sellhead');
    head.appendChild(el('span', 'Exit grade: ' + (ex.exit.grade || '—'), 'badge v-' + gradeKey(ex.exit.grade)));
    head.appendChild(el('span', 'Overall: ' + (ex.combined_verdict || '—'), 'badge v-' + vkey(ex.combined_verdict)));
    box.appendChild(head);
    (ex.exit.levels || []).forEach(function (l) {
      var loss = Number(l.loss_vs_market_pct);
      var ok = isFinite(loss);
      var row = el('div', null, 'sell v-' + (ok ? lossKey(loss) : 'unknown'));
      row.appendChild(el('span', 'Sell ' + usd(l.size_usd)));
      var bar = el('div', null, 'bar');
      var fill = el('i');
      fill.style.width = (ok ? Math.max(3, Math.min(100, loss * 4)) : 0) + '%';
      bar.appendChild(fill);
      row.appendChild(bar);
      row.appendChild(el('b', ok ? loss.toFixed(1) + '% lost' : (l.status || 'no quote')));
      box.appendChild(row);
    });
    box.appendChild(el('p', 'A quote does not prove a real sell will succeed.', 'note'));
    return box;
  }

  function render(d, ex, xp, still) {
    last = { d: d, ex: ex, xp: xp };
    clear(out);
    out.setAttribute('aria-busy', 'false');
    var dec = d.decision || {};
    var hq = d.holder_quality || {};
    var vk = vkey(d.verdict);
    var card = el('div', null, 'card hero v-' + vk + (still ? '' : ' enter'));

    var top = el('div', null, 'top');
    var ring = el('div', null, 'ring');
    var risk = Number(d.risk_score);
    var target = isFinite(risk) ? Math.max(0, Math.min(100, risk)) : 0;
    ring.style.setProperty('--p', still ? target : 0);
    var inner = el('div');
    inner.appendChild(el('b', isFinite(risk) ? risk : '—'));
    inner.appendChild(el('small', 'risk / 100'));
    ring.appendChild(inner);
    top.appendChild(ring);
    var side = el('div');
    var vw = el('div', null, 'vword');
    vw.appendChild(el('span', VERDICTS[vk][1], 'vicon'));
    vw.appendChild(el('span', VERDICTS[vk][0]));
    side.appendChild(vw);
    side.appendChild(el('div', d.token || d.name || 'Unnamed token', 'tname'));
    top.appendChild(side);
    card.appendChild(top);

    card.appendChild(el('p', d.summary || '', 'summary'));
    card.appendChild(el('p', d.mint || '', 'meta'));
    if (d.mint) {
      var acts = el('div', null, 'acts');
      acts.appendChild(copyBtn('Copy address', d.mint));
      acts.appendChild(copyBtn('Copy link', location.origin + '/play?mint=' + encodeURIComponent(d.mint)));
      card.appendChild(acts);
    }

    var grid = el('div', null, 'grid');
    grid.appendChild(metric('Liquidity', usd(d.liquidity_usd)));
    grid.appendChild(metric('Price', price(d.price_usd)));
    grid.appendChild(metric('Pair age', age(d.pair_age_minutes)));
    grid.appendChild(metric('Holder quality', (hq.score !== undefined ? hq.score : '—') + ' / 100', scoreTone(hq.score)));
    card.appendChild(grid);

    card.appendChild(whyBox(xp));

    var gwrap = el('div', null, 'groups');
    [['Blockers', 'avoid', '✕', dec.blockers], ['Cautions', 'caution', '!', dec.cautions],
     ['Positives', 'ok', '✓', dec.positives], ['Unknown', 'unknown', '?', dec.unknowns]].forEach(function (g) {
      if (!Array.isArray(g[3]) || !g[3].length) return;
      var box = el('div', null, 'grp g-' + g[1]);
      var gh = el('div', null, 'gh');
      gh.appendChild(el('i', g[2]));
      gh.appendChild(el('span', g[0]));
      gh.appendChild(el('em', g[3].length));
      box.appendChild(gh);
      box.appendChild(list(g[3]));
      gwrap.appendChild(box);
    });
    if (gwrap.firstChild) { card.appendChild(el('h3', 'Signals')); card.appendChild(gwrap); }

    var flags = el('div');
    (Array.isArray(d.flags) ? d.flags : []).slice(0, 24).forEach(function (f) { flags.appendChild(el('span', nice(f), 'flag')); });
    if (flags.firstChild) { card.appendChild(el('h3', 'Flags')); card.appendChild(flags); }

    card.appendChild(el('h3', 'Cost to sell (Jupiter)'));
    card.appendChild(sellBox(ex));

    var next = list(d.suggested_next || dec.next_checks);
    if (next.firstChild) { card.appendChild(el('h3', 'Next steps')); card.appendChild(next); }

    card.appendChild(el('p', dec.disclaimer || 'Heuristic output, not financial advice.', 'note')).style.marginTop = '1rem';

    var det = el('details');
    det.appendChild(el('summary', 'Raw JSON'));
    det.appendChild(el('pre', JSON.stringify(d, null, 2)));
    card.appendChild(det);
    out.appendChild(card);
    if (!still) requestAnimationFrame(function () { requestAnimationFrame(function () { ring.style.setProperty('--p', target); }); });
    if (!still) saveRecent(d.mint, d.token || d.name);
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
    btn.textContent = 'Checking…';
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

  drawRecent();
  btn.addEventListener('click', check);
  input.addEventListener('keydown', function (ev) { if (ev.key === 'Enter') check(); });
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
</html>
"""


@app.get("/play", include_in_schema=False)
async def playground():
    return HTMLResponse(PLAY_HTML, headers={"Cache-Control": "no-cache"})


print(f"[part26] v{VERSION} playground ready at /play (share a token with /play?mint=<address>)")

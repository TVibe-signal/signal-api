# ---------- part36: v2.23.0 — source badge, favicon, degraded-source hint ----------
# Continues the UX polish after part35:
#   1. Favicon (SVG) on every page that has a <head>
#   2. On /play: show a clear "Data from GeckoTerminal (DexScreener rate-limited)" badge
#      when the signal used the fallback source
#   3. Soft degraded banner at the top of /play when health says dexscreener is down
#
# Safe to load after part35, before part7. SKIP checksum.

VERSION = "2.23.0"
app.version = VERSION
app.openapi_schema = None

_FAVICON_SVG = (
    "data:image/svg+xml," 
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='8' fill='%2305080f'/%3E"
    "%3Ctext x='16' y='22' text-anchor='middle' font-size='16' font-family='system-ui,sans-serif' "
    "font-weight='800' fill='%236366f1'%3Ex%3C/text%3E%3C/svg%3E"
)
_FAVICON_LINK = f'<link rel="icon" href="{_FAVICON_SVG}">'


def _inject_favicon(html: str) -> str:
    if not isinstance(html, str) or _FAVICON_LINK in html:
        return html
    if '<meta charset="utf-8">' in html:
        return html.replace('<meta charset="utf-8">', '<meta charset="utf-8">' + _FAVICON_LINK, 1)
    if "<head>" in html:
        return html.replace("<head>", "<head>" + _FAVICON_LINK, 1)
    return html


# Patch static HTML blobs
for _name in ("PLAY_HTML", "STATUS_HTML", "HOME_HTML"):
    if _name in globals() and isinstance(globals()[_name], str):
        globals()[_name] = _inject_favicon(globals()[_name])

# Also patch accuracy error pages and dynamic renders that go through _ui_patch
_ui_patch_prev = globals().get("_ui_patch")
if callable(_ui_patch_prev):
    def _ui_patch(html: str, active: str, with_nav: bool = True) -> str:
        return _inject_favicon(_ui_patch_prev(html, active, with_nav=with_nav))
    globals()["_ui_patch"] = _ui_patch


# ---------------------------------------------------------------------------
# Playground: source badge + degraded banner
# ---------------------------------------------------------------------------

_SOURCE_CSS = """
/* part36 source badge + degraded banner */
.src-badge{display:inline-flex;align-items:center;gap:.35rem;font-size:.78rem;padding:.25rem .55rem;border-radius:999px;margin-top:.5rem;background:#1e293b;color:#94a3b8;border:1px solid #334155}
.src-badge.warn{background:#422006;color:#fbbf24;border-color:#78350f}
.degraded-banner{background:#422006;color:#fde68a;border:1px solid #78350f;border-radius:10px;padding:.65rem .9rem;margin-bottom:1rem;font-size:.88rem;display:none}
.degraded-banner.show{display:block}
.degraded-banner a{color:#fbbf24}
"""

_SOURCE_JS = r"""
  // --- part36: source badge + degraded banner ---
  function sourceBadge(d) {
    var src = (d && (d.source || (d.data_quality && d.data_quality.source))) || '';
    src = String(src).toLowerCase();
    if (!src || src === 'dexscreener') return null;
    var b = el('span', null, 'src-badge warn');
    if (src === 'geckoterminal' || src === 'gecko') {
      b.textContent = 'Data from GeckoTerminal (DexScreener rate-limited)';
    } else {
      b.textContent = 'Data source: ' + src;
    }
    return b;
  }

  // Hook into existing render: after summary paragraph, attach badge
  var _render36 = render;
  render = function (d, ex, xp, still) {
    _render36(d, ex, xp, still);
    try {
      var card = out.querySelector('.card');
      if (!card) return;
      var summary = card.querySelector('p.muted');
      var badge = sourceBadge(d);
      if (badge && summary && summary.parentNode === card) {
        if (summary.nextSibling) card.insertBefore(badge, summary.nextSibling);
        else card.appendChild(badge);
      } else if (badge) {
        card.appendChild(badge);
      }
    } catch (e) {}
  };

  // Soft banner when dexscreener is down
  (function checkHealth() {
    var banner = document.createElement('div');
    banner.className = 'degraded-banner';
    banner.innerHTML = 'Market data source is degraded — some fields may use fallback data. <a href="/status">See status</a>';
    var wrap = document.querySelector('.wrap');
    if (wrap && wrap.firstChild) wrap.insertBefore(banner, wrap.firstChild);
    fetch('/health').then(function (r) { return r.json(); }).then(function (h) {
      var src = (h.sources || {}).dexscreener || {};
      if (src.status === 'down' || src.status === 'degraded' || (h.status && h.status !== 'ok')) {
        banner.classList.add('show');
      }
    }).catch(function () {});
  })();
"""


def _patch_play_source():
    global PLAY_HTML
    if "PLAY_HTML" not in globals() or not isinstance(PLAY_HTML, str):
        return
    if "part36" in PLAY_HTML or "sourceBadge" in PLAY_HTML:
        return

    if "</style>" in PLAY_HTML:
        PLAY_HTML = PLAY_HTML.replace("</style>", _SOURCE_CSS + "</style>", 1)

    marker = "})();\n</script>"
    alt = "})();</script>"
    if marker in PLAY_HTML:
        PLAY_HTML = PLAY_HTML.replace(marker, _SOURCE_JS + "\n})();\n</script>", 1)
    elif alt in PLAY_HTML:
        PLAY_HTML = PLAY_HTML.replace(alt, _SOURCE_JS + "})();</script>", 1)


try:
    _patch_play_source()
except Exception:
    pass

try:
    if "PLAY_HTML" in globals():
        PLAY_HTML = _inject_favicon(PLAY_HTML)
except Exception:
    pass

print(f"[part36] v{VERSION} favicon · source badge on /play · degraded banner when DexScreener is down")
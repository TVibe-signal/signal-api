# ---------- part35: v2.22.0 — harden /accuracy + playground UX + shared nav on accuracy ----------
# Fixes:
#   1. /accuracy no longer 500s when Redis / ledger_head / render helpers fail
#   2. Paste button + auto-check on paste for /play
#   3. Shared top-nav + theme-color on the accuracy page (was missing)
#   4. Better mobile touch targets and loading feedback on playground
#   5. Clearer error message when mint is invalid
#
# Safe to load last before part7. Uses SKIP checksum in main.py.

import traceback
import time
from typing import Optional, Any

VERSION = "2.22.0"
app.version = VERSION
app.openapi_schema = None

# ---------------------------------------------------------------------------
# 1. Harden /accuracy
# ---------------------------------------------------------------------------

_original_accuracy_page = accuracy_page


def _accuracy_error_page(title: str, body: str, status: int = 503, extra: str = "") -> HTMLResponse:
    nav = ""
    try:
        if "_ui_nav" in globals():
            nav = _ui_nav("/accuracy")
    except Exception:
        pass
    css = ""
    try:
        if "_UI_CSS" in globals():
            css = _UI_CSS
    except Exception:
        pass
    return HTMLResponse(
        content=f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#05080f"><meta name="color-scheme" content="dark">
<title>TVibex402 accuracy</title>
<style>
:root{{--bg:#070b12;--card:rgba(18,25,35,.88);--text:#e8eef6;--muted:#8b9bb4;--a:#14f195;--err:#f85149;--line:#1e2638}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--text);font-family:system-ui,sans-serif;line-height:1.55}}
.wrap{{max-width:720px;margin:0 auto;padding:1.5rem 1rem 3rem}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1.5rem}}
h1{{font-size:1.4rem;margin-bottom:.75rem}}
a{{color:var(--a)}} .muted{{color:var(--muted);font-size:.9rem}}
pre{{background:#0d1117;padding:12px;border-radius:8px;overflow:auto;font-size:11px;color:var(--err);margin-top:1rem;max-height:240px}}
{css}
</style></head><body>
{nav}
<div class="wrap"><div class="card">
  <h1>{_html.escape(title)}</h1>
  <p>{body}</p>
  {extra}
  <p class="muted" style="margin-top:1.25rem">
    <a href="/">Home</a> · <a href="/stats">Raw JSON</a> · <a href="/status">Status</a> · <a href="/play">Playground</a>
  </p>
</div></div></body></html>""",
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


# Remove any previously registered /accuracy route so ours is the only one
# (FastAPI matches in registration order; part10 registered first)
app.router.routes[:] = [
    r for r in app.router.routes
    if not (getattr(r, "path", None) == "/accuracy" and "GET" in (getattr(r, "methods", None) or set()))
]


@app.get("/accuracy", response_class=HTMLResponse, tags=["trust"], summary="Public accuracy dashboard")
async def accuracy_page(request: Request):
    wait = rate_limited(client_ip(request))
    if wait:
        raise too_many(wait)

    client = request.app.state.client
    head = None

    # --- stats_report can fail if Redis is down ---
    try:
        rep = await stats_report(client)
    except Exception as e:
        return _accuracy_error_page(
            "Measured accuracy",
            "The statistics store is temporarily unavailable. Please try again in a minute.",
            status=503,
            extra=f'<p class="muted">Error: {_html.escape(str(e)[:160])}</p>',
        )

    # --- ledger_head is optional; never let it crash the page ---
    if PRED_ENABLED:
        try:
            if time.time() - _head_cache.get("ts", 0.0) > 60:
                got = await redis_pipe(client, [["GET", "ledger_head"]])
                _head_cache.update(ts=time.time(), head=got[0] if got else None)
            head = _head_cache.get("head")
        except Exception:
            head = None

    # --- render itself can fail if a helper receives unexpected shape ---
    try:
        html_out = render_accuracy(rep, head)
    except Exception:
        tb = _html.escape(traceback.format_exc()[:2200])
        return _accuracy_error_page(
            "Measured accuracy — render error",
            "Something went wrong while building the page. The raw data is still available at <a href=\"/stats\">/stats</a>.",
            status=500,
            extra=f"<pre>{tb}</pre>",
        )

    # Apply shared top-nav + theme if the polish layer is present
    try:
        if "_ui_patch" in globals():
            html_out = _ui_patch(html_out, "/accuracy")
    except Exception:
        pass

    return HTMLResponse(html_out, headers={"Cache-Control": "public, max-age=30"})


# ---------------------------------------------------------------------------
# 2. Playground UX improvements
# ---------------------------------------------------------------------------

_PLAY_EXTRA_CSS = """
/* part35 playground polish */
.row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:stretch}
.row input{flex:1;min-width:180px}
.row button{min-height:44px;cursor:pointer;white-space:nowrap}
#pasteBtn{background:#1e293b;color:#94a3b8;border:1px solid #334155;border-radius:10px;padding:0 1rem;font-weight:500;font-size:.9rem}
#pasteBtn:hover{background:#273549;color:#e2e8f0}
#btn.loading{opacity:.7;pointer-events:none}
@media (max-width:480px){
  .row{flex-direction:column}
  .row button{width:100%}
}
"""


def _patch_playground():
    global PLAY_HTML
    if "PLAY_HTML" not in globals() or not isinstance(PLAY_HTML, str):
        return
    if 'id="pasteBtn"' in PLAY_HTML:
        return  # already patched

    # Inject extra CSS
    if "</style>" in PLAY_HTML:
        PLAY_HTML = PLAY_HTML.replace("</style>", _PLAY_EXTRA_CSS + "</style>", 1)

    # Add Paste button next to Check
    PLAY_HTML = PLAY_HTML.replace(
        '<button id="btn" type="button">Check</button>',
        '<button id="pasteBtn" type="button" title="Paste from clipboard">Paste</button>'
        '<button id="btn" type="button">Check</button>',
        1,
    )

    # Richer JS: paste button, auto-check on paste, clearer loading
    old_btn = "var btn = document.getElementById('btn');"
    new_btn = """var btn = document.getElementById('btn');
  var pasteBtn = document.getElementById('pasteBtn');

  function setLoading(on) {
    btn.disabled = !!on;
    btn.classList.toggle('loading', !!on);
    btn.textContent = on ? 'Checking…' : 'Check';
    if (pasteBtn) pasteBtn.disabled = !!on;
  }

  if (pasteBtn) {
    pasteBtn.addEventListener('click', function () {
      if (!navigator.clipboard || !navigator.clipboard.readText) {
        input.focus();
        input.select();
        return;
      }
      navigator.clipboard.readText().then(function (t) {
        var v = (t || '').trim();
        if (v) { input.value = v; check(); }
        else { input.focus(); }
      }).catch(function () { input.focus(); input.select(); });
    });
  }

  // Auto-run when user pastes a valid mint
  input.addEventListener('paste', function () {
    setTimeout(function () {
      var v = input.value.trim();
      if (MINT_RE.test(v)) check();
    }, 40);
  });
"""
    if old_btn in PLAY_HTML:
        PLAY_HTML = PLAY_HTML.replace(old_btn, new_btn, 1)

    # Patch loading state to use setLoading
    for candidate in (
        "btn.disabled = true; btn.textContent = '…';",
        "btn.disabled = true; btn.textContent = '...';",
        "btn.disabled = true;\n    btn.textContent = '…';",
    ):
        if candidate in PLAY_HTML:
            PLAY_HTML = PLAY_HTML.replace(candidate, "setLoading(true);", 1)
            break

    old_enable = "btn.disabled = false; btn.textContent = 'Check';"
    if old_enable in PLAY_HTML:
        PLAY_HTML = PLAY_HTML.replace(old_enable, "setLoading(false);", 1)

    # Clearer invalid-mint message
    old_err = "showError('That does not look like a Solana token address.');"
    if old_err in PLAY_HTML:
        PLAY_HTML = PLAY_HTML.replace(
            old_err,
            "showError('That does not look like a Solana token address. Paste a mint (32–44 base58 characters).');",
            1,
        )


try:
    _patch_playground()
except Exception:
    pass


# Re-apply UI polish nav (part34 ran before us)
try:
    if "PLAY_HTML" in globals() and "_ui_patch" in globals():
        PLAY_HTML = _ui_patch(PLAY_HTML, "/play")
except Exception:
    pass


print(f"[part35] v{VERSION} /accuracy hardened · Paste + auto-check on /play · shared nav on accuracy · mobile polish")
"""main.py — TVibe FILTER loader (THIS file is what Render runs). Order matters.
Render Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
(core.py is now a thin shim, so `uvicorn core:app` also lands here.)

FIXED:
- /health NameError: mcp_error is not defined
- /play 422: Field required [query, request]
"""
from __future__ import annotations

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _exec_module_file(path: str, g: dict, label: str) -> None:
    """Run a .py file in the shared namespace (same pattern as legacy multi-part main)."""
    if not os.path.isfile(path):
        print(f"[loader] skip {label}: missing {path}")
        return
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    try:
        code = compile(src, path, "exec")
        exec(code, g, g)
        print(f"[loader] {label} loaded ({os.path.basename(path)})")
    except Exception as e:
        print(f"[loader] {label} FAILED: {e}")
        traceback.print_exc()
        raise


def _apply_patch(modname: str, g: dict) -> None:
    try:
        mod = __import__(modname)
        mod.apply(g)
        print(f"[loader] {modname} applied")
    except Exception as e:
        print(f"[loader] {modname} NOT applied: {e}")


def _sync_to_core(core, g: dict) -> None:
    """Copy names created by extensions/patches back into core_final's module globals.

    /health is DEFINED in core_final, so it looks up globals in core_final.__dict__,
    NOT in the loader dict `g`. If a name only exists in `g`, /health raises NameError.
    """
    for _k, _v in list(g.items()):
        if _k not in core.__dict__:
            core.__dict__[_k] = _v
    # FIX 2: force defaults — even if extensions.py failed / never assigned them.
    # Never leave mcp_error undefined.
    core.__dict__.setdefault("mcp_error", None)
    core.__dict__.setdefault("mcp_server", None)
    # If extensions DID define it, take the real value (overrides the default).
    for _k in ("mcp_server", "mcp_error"):
        if _k in g:
            core.__dict__[_k] = g[_k]


# 1) Core — FastAPI app + base /signal /stats
import core_final as core  # noqa: E402,F401

# FIX 2 (early): define BEFORE anything runs, so /health can never NameError,
# even if extensions.py crashes before assigning mcp_error.
core.__dict__.setdefault("mcp_error", None)
core.__dict__.setdefault("mcp_server", None)

g = dict(vars(core))
g["__name__"] = "__main__"
g["__file__"] = os.path.join(ROOT, "main.py")
# Also seed the shared dict, so exec'd files see the defaults.
g.setdefault("mcp_error", None)
g.setdefault("mcp_server", None)

# 2) features.py — heuristics layers (shared namespace)
_exec_module_file(os.path.join(ROOT, "features.py"), g, "features")
_sync_to_core(core, g)

# 3) extensions.py — MCP, /omni, ops, SI (must be after core/features)
_exec_module_file(os.path.join(ROOT, "extensions.py"), g, "extensions")

# 3b) Sync back to core_final (see _sync_to_core docstring).
_sync_to_core(core, g)

# 4) Optional patches, in order
for _name in ("patch_builder", "patch_stats_fix", "patch_p0", "patch_filter_v4", "patch_usdc_pair_v2"):
    _apply_patch(_name, g)
    _sync_to_core(core, g)

app = g.get("app")
if app is None:
    raise RuntimeError("app not found after loader chain (core → features → extensions)")

# Re-export for uvicorn: main:app
globals().update(g)

print("[loader] ready app=%s version=%s" % (type(app).__name__, g.get("VERSION") or getattr(app, "version", "?")))

# 5) FINAL (must be last): live homepage check() + /omni fallback + /health never-500
_apply_patch("patch_live_fix", g)
_sync_to_core(core, g)
app = g.get("app")  # wrapped app (patch_live_fix) — this is what uvicorn serves
globals()["app"] = app

# v34: FIX 1 REMOVED — it re-added /play with a param named `request` AFTER patch_live_fix,
# so FastAPI treated `request` as required query -> 422 {loc:[query,request]}.
# /play + /omni are now owned ONLY by patch_live_fix v34. Do not re-add them here.

# Final guarantee for /health, after ALL patches.
core.__dict__.setdefault("mcp_error", None)
core.__dict__.setdefault("mcp_server", None)
g.setdefault("mcp_error", core.__dict__["mcp_error"])
g.setdefault("mcp_server", core.__dict__["mcp_server"])

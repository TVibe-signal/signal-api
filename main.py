"""main.py — TVibe FILTER loader (THIS file is what Render runs). Order matters.
FIX 16/11: load core_final (TVibe FILTER 2070 + /omni), NOT old core.py.
Render Start Command MUST be: uvicorn main:app --host 0.0.0.0 --port $PORT
If Render still runs `uvicorn core:app`, this file is ignored and web stays old.
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


# 1) Core — FastAPI app + base /signal /stats
import core_final as core  # noqa: F401  # FIX: old core.py has no FILTER/2070/no /omni

g = dict(vars(core))  # core_final already has FILTER landing + /omni
g["__name__"] = "__main__"
g["__file__"] = os.path.join(ROOT, "main.py")

# 2) features.py — heuristics layers (shared namespace)
_exec_module_file(os.path.join(ROOT, "features.py"), g, "features")

# 3) extensions.py — MCP, /omni, ops, SI, parts 94…157 (must be after core/features)
_exec_module_file(os.path.join(ROOT, "extensions.py"), g, "extensions")

# 4) Optional stats display fix
try:
    import patch_stats_fix

    patch_stats_fix.apply(g)
    print("[loader] patch_stats_fix applied")
except Exception as e:
    print(f"[loader] patch_stats_fix NOT applied: {e}")

# 5) Optional P0 runtime pin (version / stale / client_ip) — after extensions
try:
    import patch_p0

    patch_p0.apply(g)
    print("[loader] patch_p0 applied")
except Exception as e:
    print(f"[loader] patch_p0 NOT applied: {e}")

# 5b) Filter v4 (private thresholds stay in patch_filter_v4, never exposed on web)
try:
    import patch_filter_v4
    patch_filter_v4.apply(g)
    print("[loader] patch_filter_v4 applied")
except Exception as e:
    print(f"[loader] patch_filter_v4 NOT applied: {e}")

# 5c) USDC-pair fix: CBUCKS/USDC (PumpSwap) mint as quoteToken + search fallback
try:
    import patch_usdc_pair_v2
    patch_usdc_pair_v2.apply(g)
    print("[loader] patch_usdc_pair_v2 applied")
except Exception as e:
    print(f"[loader] patch_usdc_pair_v2 NOT applied: {e}")

# 6) FINAL: override homepage DEMO -> LIVE (must be LAST, after extensions overwrites HOME_HTML)
try:
    import patch_home_live_v2 as patch_home_live
    patch_home_live.apply(g)
    print("[loader] patch_home_live_v2 applied")
except Exception as e:
    print(f"[loader] patch_home_live_v2 NOT applied: {e}")

app = g.get("app")
if app is None:
    raise RuntimeError("app not found after loader chain (core → features → extensions)")

# Re-export for uvicorn: main:app
globals().update(g)

print("[loader] ready app=%s version=%s" % (type(app).__name__, g.get("VERSION") or getattr(app, "version", "?")))

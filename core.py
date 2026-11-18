"""core.py — compatibility shim (safe against circular import).

Real app = main.py (core_final + features + extensions + patches).
- If something imports `core` while main.py is still loading (old patches do this),
  `core` simply becomes core_final (no circular import).
- If the host runs `uvicorn core:app` directly, it gets the full app from main.py.
Old 340KB core.py is preserved in git history.
"""
import sys

if "main" in sys.modules:
    import core_final
    sys.modules[__name__] = core_final
else:
    import core_final as _cf
    globals().update({k: v for k, v in vars(_cf).items() if not k.startswith("__")})
    from main import app  # noqa: F401,E402

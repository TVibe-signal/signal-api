"""core.py — compatibility shim.

The real app is assembled by main.py (core_final + features + extensions + patches).
If the host still runs `uvicorn core:app`, it now gets the same live app instead of the
old demo page. The previous 340KB core.py is preserved in git history.
"""
from main import app  # noqa: F401

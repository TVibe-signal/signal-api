"""main.py - TVibe Signal API loader (thin). Order matters."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

# 1) Core (giữ nguyên, không sửa)
import core  # noqa: F401
g = dict(vars(core))
g["__name__"] = "__main__"

# 2) Stats fix (đã chạy, giữ)
try:
    import patch_stats_fix
    patch_stats_fix.apply(g)
    print("[loader] patch_stats_fix applied")
except Exception as e:
    print(f"[loader] patch_stats_fix NOT applied: {e}")

# 3) Filter v4.1 - hard vetoes + scoring (mới)
try:
    import patch_filter_v4
    patch_filter_v4.apply(g)
    print("[loader] patch_filter_v4 applied")
except Exception as e:
    print(f"[loader] patch_filter_v4 NOT applied: {e}")

# 4) Expose app for Render / uvicorn
app = g.get("app")
if app is None:
    raise RuntimeError("app not found after loading core.py")

# Re-export globals so uvicorn / Render thấy đúng app
globals().update(g)

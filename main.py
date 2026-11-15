"""
TVibe Signal API — thin loader
Loads core.py -> features.py -> extensions.py
+ patch_p0.py (P0 fix) after all.
"""
import os

_FILES = ("core.py", "features.py", "extensions.py")

def _load():
    folder = os.path.dirname(os.path.abspath(__file__))
    for name in _FILES:
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            raise RuntimeError(f"Missing {name}")
        with open(path, encoding="utf-8-sig") as fh:
            code = fh.read()
        exec(compile(code, path, "exec"), globals())
        print(f"[loader] loaded {name}")

_load()
del _load

# P0 fix - chỉ cần 3 dòng này, khỏi sửa file 10k dòng
try:
    import patch_p0
    patch_p0.apply(globals())
except Exception as e:
    print(f"[loader] patch_p0 not applied: {e}")
# Stats fix - thay /stats bi loi AsyncClient.app
try:
    import patch_stats_fix
    patch_stats_fix.apply(globals())
except Exception as e:
    print(f"[loader] patch_stats_fix not applied: {e}")
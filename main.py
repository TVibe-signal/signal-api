"""
TVibe Signal API — thin loader
Loads core.py → features.py → extensions.py into one shared namespace.
Same runtime behavior as the original 130-part design, but only 3 files.
Deploy on Render: just these 4 files + requirements.txt
+ P0 fix modules (verdict.py, config.py, etc) loaded after core.
"""
import os

_FILES = ("core.py", "features.py", "extensions.py")

def _load():
    folder = os.path.dirname(os.path.abspath(__file__))
    for name in _FILES:
        path = os.path.join(folder, name)
        if not os.path.exists(path):
            raise RuntimeError(f"Missing {name}. Put core.py, features.py, extensions.py next to main.py")
        with open(path, encoding="utf-8-sig") as fh:
            code = fh.read()
        exec(compile(code, path, "exec"), globals())
        print(f"[loader] loaded {name}")

_load()
del _load

# --- P0 FIX: bump version + wire verdict.py ---
# File mới không tự chạy được, phải nối ở đây.
try:
    from verdict import build_verdict
    globals()["build_verdict"] = build_verdict
    print("[loader] wired verdict.build_verdict")
except Exception as e:
    print(f"[loader] verdict.py not wired: {e}")

# Ép version lên 3.0.28 dù version cũ nằm ở core.py / extensions.py
for _k in ("VERSION", "APP_VERSION", "__version__", "API_VERSION"):
    globals()[_k] = "3.0.28"

# Ép config P0 nếu code cũ vẫn dùng số cũ
try:
    globals()["STALE_MAX_S"] = 600
    globals()["CACHE_SIZE"] = 1000
    globals()["UPSTREAM_EVERY_S"] = 60
except Exception:
    pass
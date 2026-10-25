"""
TVibe Signal API — thin loader
Loads core.py → features.py → extensions.py into one shared namespace.
Same runtime behavior as the original 130-part design, but only 3 files.
Deploy on Render: just these 4 files + requirements.txt
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

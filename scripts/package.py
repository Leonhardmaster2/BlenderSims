"""Rebuild hesiod_teaser.zip (the file you install in Blender) from the source folder.

    python scripts/package.py
"""
import os
import zipfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SRC = os.path.join(ROOT, "hesiod_teaser")
OUT = os.path.join(ROOT, "hesiod_teaser.zip")

with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
    for folder, dirs, files in os.walk(SRC):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith((".py", ".toml")):
                path = os.path.join(folder, name)
                arc = os.path.join("hesiod_teaser", os.path.relpath(path, SRC))
                info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))   # reproducible
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(path, "rb") as fh:
                    zf.writestr(info, fh.read())
print("wrote", os.path.normpath(OUT))

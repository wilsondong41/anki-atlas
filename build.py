"""Package Anki Atlas into dist/:

  dist/anki-atlas.ankiaddon          to install from a local file
  dist/anki-atlas-ankiweb.ankiaddon  to upload to AnkiWeb (no manifest.json)
"""

import os
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(ROOT, "anki_atlas")
DIST = os.path.join(ROOT, "dist")


def package(out: str, skip: set[str]) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, filenames in os.walk(SRC):
            dirnames[:] = sorted(d for d in dirnames if d not in ("__pycache__", "user_files"))
            for name in sorted(filenames):
                if name.endswith(".pyc") or name == ".DS_Store" or name in skip:
                    continue
                path = os.path.join(dirpath, name)
                z.write(path, os.path.relpath(path, SRC))
    print(f"built {out}")


def main() -> None:
    os.makedirs(DIST, exist_ok=True)
    package(os.path.join(DIST, "anki-atlas.ankiaddon"), set())
    package(os.path.join(DIST, "anki-atlas-ankiweb.ankiaddon"), {"manifest.json"})


if __name__ == "__main__":
    main()

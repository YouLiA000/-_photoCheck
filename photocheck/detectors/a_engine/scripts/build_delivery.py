"""Package A's complete delivery tree into one zip.

Why this script exists: hand-made zips repeated three mistakes - missing files,
`__pycache__` folders inside, and non-ASCII entry names that unpack as mojibake on
the other side. All three happened during the first handoff.

Usage:
    python scripts/build_delivery.py                 # -> dist/A_delivery_v2_<date>.zip
    python scripts/build_delivery.py --out D:/x.zip
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Must ship (relative to the project root)
INCLUDE_DIRS = ("core", "badcases", "reports", "scripts", "tests", "samples")
INCLUDE_FILES = ("README.md", "交付说明_v2.md", "requirements.txt", "express_001.png", "express_001.json")

# Never ship
EXCLUDE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".venv", "_archive", ".workbuddy", ".git"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _collect() -> list[Path]:
    files: list[Path] = []
    for name in INCLUDE_FILES:
        path = ROOT / name
        if not path.is_file():
            raise SystemExit(f"missing required file: {name}")
        files.append(path)

    for dirname in INCLUDE_DIRS:
        base = ROOT / dirname
        if not base.is_dir():
            raise SystemExit(f"missing required directory: {dirname}")
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix in EXCLUDE_SUFFIXES:
                continue
            if any(part in EXCLUDE_DIR_NAMES for part in path.relative_to(ROOT).parts):
                continue
            files.append(path)
    return sorted(files, key=lambda p: p.relative_to(ROOT).as_posix())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Package A's delivery tree")
    parser.add_argument("--out", help="output zip path")
    args = parser.parse_args(argv)

    # The archive name stays Chinese because it is the artifact name the receiving
    # side already refers to; zipfile sets the UTF-8 entry flag (0x800) by itself,
    # so the Chinese file names inside unpack correctly.
    out = Path(args.out) if args.out else ROOT / "dist" / f"A_交付_v2_{date.today().isoformat()}.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    files = _collect()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arc = path.relative_to(ROOT).as_posix()
            zf.write(path, arc)

    digest = hashlib.sha256(out.read_bytes()).hexdigest().upper()
    print(f"packed {len(files)} file(s)")
    print(f"  output: {out}")
    print(f"  size:   {out.stat().st_size / 1024:.1f} KB")
    print(f"  SHA-256: {digest}")
    for path in files:
        print(f"    {path.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

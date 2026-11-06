"""Validate badcases/ and regenerate index.json.

Usage:
    python scripts/badcase_index.py            # validate + write badcases/index.json
    python scripts/badcase_index.py --check    # validate only, no write (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = ROOT.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from photocheck.detectors.a_engine.core.badcase import BadcaseError, build_index, load_all  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Failure-case library index and validation")
    parser.add_argument("--check", action="store_true", help="validate only, do not write index.json")
    parser.add_argument("--root", default=str(ROOT / "badcases"), help="badcases directory")
    args = parser.parse_args()

    try:
        cases = load_all(args.root, tests_dir=ROOT / "tests")
    except BadcaseError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    index = build_index(cases)
    print(f"validation passed: {index['total']} case(s)")
    for label, count in index["by_reason"].items():
        print(f"  {label}: {count}")
    print(f"  by status: {index['by_status']}")

    if args.check:
        return 0

    out = Path(args.root) / "index.json"
    out.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"written {out.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

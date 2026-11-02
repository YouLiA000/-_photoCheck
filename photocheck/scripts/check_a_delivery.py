"""CLI for auditing an A delivery before integration."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from photocheck.detectors.delivery_check import inspect_a_delivery


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("delivery_root", type=Path)
    args = parser.parse_args()

    report = inspect_a_delivery(args.delivery_root)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.detector_source_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

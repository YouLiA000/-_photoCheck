"""Run the vendored A engine through B's ingestion and contract adapter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from photocheck.core import ingest_image
from photocheck.detectors import a_detector_status, analyze_a


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    with ingest_image(args.image) as ingested:
        envelope = analyze_a(
            ingested.image,
            ingested.descriptor["image_id"],
        )

    payload = {
        "image_descriptor": envelope.image_descriptor,
        "detections": list(envelope.detections),
        "warnings": list(envelope.warnings),
        "timings_ms": dict(envelope.timings_ms),
        "detector_status": a_detector_status(),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
        print(args.out.resolve())
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

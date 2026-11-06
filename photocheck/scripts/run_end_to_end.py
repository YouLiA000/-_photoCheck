"""Run one image through A detection, B redaction/export and content recheck."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_NETWORK_GUARD = None
if os.environ.get("PHOTOCHECK_OFFLINE_GUARD") == "1":
    from photocheck.network_guard import assert_network_blocked, install_network_guard

    _NETWORK_GUARD = install_network_guard()
    assert_network_blocked()

from photocheck.contract import build_redaction_plan, validate_records
from photocheck.core import ingest_image, process_and_export
from photocheck.detectors import analyze_a


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    output_dir = args.output_dir or args.image.parent / "photocheck-output"
    with ingest_image(args.image) as ingested:
        envelope = analyze_a(
            ingested.image,
            ingested.descriptor["image_id"],
        )
        detections = [
            dict(item)
            for item in (*ingested.detections, *envelope.detections)
        ]
        decisions = [
            {
                "contract_version": "photocheck/v4",
                "record_type": "Decision",
                "finding_id": detection["id"],
                "action": "redact",
                "revision": 1,
            }
            for detection in detections
            if detection["kind"] != "meta"
        ]
        validate_records([ingested.descriptor, *detections, *decisions])
        plan = build_redaction_plan(
            ingested.descriptor,
            detections,
            decisions,
            revision=1,
        )
        result = process_and_export(
            ingested,
            plan,
            output_dir=output_dir,
            detections=detections,
            decisions=decisions,
            run_full_recheck=True,
        )

    payload = {
        "source": str(args.image.resolve()),
        "output": str(result.export.output_path.resolve()),
        "source_sha256": result.export.source_sha256,
        "output_sha256": result.export.output_sha256,
        "image_id": ingested.descriptor["image_id"],
        "plan_revision": plan["revision"],
        "detection_count": len(detections),
        "detections_by_kind": {
            kind: sum(item["kind"] == kind for item in detections)
            for kind in ("meta", "text", "qr", "face")
        },
        "warnings": list(envelope.warnings),
        "timings_ms": dict(envelope.timings_ms),
        "verification": result.verification,
        "full_file_recheck": result.full_recheck,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
        print(args.report.resolve())
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

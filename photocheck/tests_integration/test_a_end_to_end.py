from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from photocheck.contract import build_redaction_plan
from photocheck.core import ingest_image, metadata_residual_tags, process_and_export, read_metadata
from photocheck.detectors import analyze_a, probe_a_region

SAMPLE = (
    Path(__file__).resolve().parents[1]
    / "detectors"
    / "a_engine"
    / "express_001.png"
)


class AEndToEndTests(unittest.TestCase):
    def test_sample_is_detected_redacted_exported_and_rechecked(self) -> None:
        source_hash = hashlib.sha256(SAMPLE.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temp_dir:
            with ingest_image(SAMPLE) as ingested:
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
                plan = build_redaction_plan(
                    ingested.descriptor,
                    detections,
                    decisions,
                    revision=1,
                )
                result = process_and_export(
                    ingested,
                    plan,
                    output_dir=temp_dir,
                    detections=detections,
                    decisions=decisions,
                    run_full_recheck=True,
                )

                self.assertEqual(result.verification["disposal_state"], "passed")
                self.assertEqual(
                    {check["method"] for check in result.verification["checks"]},
                    {"a_ocr_probe", "a_qr_probe"},
                )
                self.assertEqual(
                    metadata_residual_tags(read_metadata(result.export.output_path)),
                    (),
                )

                qr = next(
                    detection
                    for detection in detections
                    if detection["kind"] == "qr"
                )
                qr_probe = probe_a_region(
                    result.export.output_path,
                    qr["bbox"],
                    kinds=("qr",),
                )
                self.assertEqual(qr_probe["residual_qr_detected"], 0)
                self.assertEqual(qr_probe["residual_qr_decodable"], 0)
                self.assertEqual(
                    result.full_recheck["unplanned_count"],
                    0,
                )

        self.assertEqual(hashlib.sha256(SAMPLE.read_bytes()).hexdigest(), source_hash)


if __name__ == "__main__":
    unittest.main()

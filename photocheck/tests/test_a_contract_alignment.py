from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from photocheck.contract import build_redaction_plan
from photocheck.core import IngestedImage, SecretStore, process_and_export
from photocheck.detectors import (
    AAdapterError,
    inspect_a_delivery,
    load_a_envelope,
    parse_a_envelope,
)
from photocheck.detectors.delivery_check import REQUIRED_ENGINE_FILES
from photocheck.detectors import a_contract as framework

FIXTURE = Path(__file__).with_name("fixtures") / "express_001.json"


def detection(
    *,
    finding_id: str = "det-1",
    kind: str = "text",
    subtype: str = "phone",
    details: dict | None = None,
):
    return framework.Detection(
        id=finding_id,
        image_id="image-1",
        kind=kind,
        subtype=subtype,
        bbox=None if kind == "meta" else (10, 20, 100, 30),
        detector_score=0.9,
        risk=2,
        details=details if details is not None else {"masked_preview": "138****8000"},
    )


class AContractTests(unittest.TestCase):
    def test_v4_sample_passes_a_and_b_validation(self) -> None:
        envelope = load_a_envelope(FIXTURE)
        framework.validate_records(envelope.records)
        self.assertEqual(envelope.image_descriptor["image_id"], "express_001")
        self.assertEqual(len(envelope.detections), 3)
        self.assertNotIn("warnings", envelope.records)
        self.assertNotIn("timings_ms", envelope.records)

    def test_image_descriptor_rejects_unknown_orientation(self) -> None:
        with self.assertRaises(framework.ContractError):
            framework.ImageDescriptor(
                image_id="image-1",
                width=100,
                height=100,
                orientation="unknown",
            )

    def test_phone_mask_cannot_keep_separated_plaintext(self) -> None:
        with self.assertRaises(framework.ContractError):
            detection(details={"masked_preview": "138-0013-8000"})

    def test_idcard_mask_can_end_with_x(self) -> None:
        item = detection(
            kind="text",
            subtype="idcard",
            details={
                "masked_preview": "1101**********001X",
                "idcard_check": "pass",
            },
        )
        self.assertEqual(item.details["masked_preview"], "1101**********001X")

    def test_idcard_mask_normalizes_lowercase_x(self) -> None:
        item = detection(
            kind="text",
            subtype="idcard",
            details={
                "masked_preview": "1101**********001x",
                "idcard_check": "pass",
            },
        )
        self.assertEqual(item.details["masked_preview"], "1101**********001X")

    def test_idcard_mask_still_requires_correct_shape(self) -> None:
        with self.assertRaises(framework.ContractError):
            detection(
                kind="text",
                subtype="idcard",
                details={
                    "masked_preview": "1101**********0X",
                    "idcard_check": "pass",
                },
            )

    def test_meta_datetime_preview_is_not_treated_as_plaintext(self) -> None:
        item = detection(
            kind="meta",
            subtype="datetime",
            details={"masked_preview": "2024-06-01"},
        )
        self.assertEqual(item.details["masked_preview"], "2024-06-01")

    def test_meta_preview_with_long_digit_run_is_rejected(self) -> None:
        with self.assertRaises(framework.ContractError):
            detection(
                kind="meta",
                subtype="serial",
                details={"masked_preview": "1234567890"},
            )

    def test_qr_summary_is_rejected(self) -> None:
        with self.assertRaises(framework.ContractError):
            detection(
                kind="qr",
                subtype="qr_link",
                details={"decodable": True, "summary": "example.com"},
            )

    def test_qr_domain_is_normalized(self) -> None:
        item = detection(
            kind="qr",
            subtype="qr_link",
            details={"decodable": True, "safe_domain": "Example.COM."},
        )
        self.assertEqual(item.details["safe_domain"], "example.com")

    def test_wifi_ssid_uses_typed_field(self) -> None:
        item = detection(
            kind="qr",
            subtype="qr_wifi",
            details={"decodable": True, "safe_ssid": "Campus WiFi"},
        )
        self.assertEqual(item.details["safe_ssid"], "Campus WiFi")

    def test_detection_must_match_descriptor_image(self) -> None:
        descriptor = framework.ImageDescriptor(
            image_id="image-2",
            width=100,
            height=100,
        ).to_dict()
        with self.assertRaises(framework.ContractError):
            framework.validate_records([descriptor, detection().to_dict()])

    def test_envelope_rejects_unknown_runtime_fields(self) -> None:
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        payload["unexpected"] = True
        with self.assertRaises(AAdapterError):
            parse_a_envelope(payload)

    def test_a_sample_enters_b_pipeline(self) -> None:
        envelope = load_a_envelope(FIXTURE)
        descriptor = envelope.image_descriptor
        detections = list(envelope.detections)
        decisions = [
            {
                "contract_version": "photocheck/v4",
                "record_type": "Decision",
                "finding_id": item["id"],
                "action": "redact",
                "revision": 1,
            }
            for item in detections
        ]
        plan = build_redaction_plan(
            descriptor,
            detections,
            decisions,
            revision=1,
        )
        store = SecretStore()
        raw_ref = store.put({})
        image = Image.new("RGB", (descriptor["width"], descriptor["height"]), (220, 220, 220))
        ingested = IngestedImage(
            descriptor=descriptor,
            image=image,
            detections=(),
            raw_metadata_ref=raw_ref,
            source_sha256="fixture",
            source_format="PNG",
            _secret_store=store,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result = process_and_export(
                ingested,
                plan,
                output_dir=temp_dir,
                detections=detections,
                decisions=decisions,
                content_probe=lambda image, bbox, *, kinds: {
                    "residual_text": 0,
                    "residual_qr_detected": 0,
                    "residual_qr_decodable": 0,
                    "residual_face": 0,
                    "unavailable": [],
                },
            )
            self.assertTrue(result.export.output_path.is_file())
            self.assertEqual(result.verification["disposal_state"], "passed")
        ingested.close()

    def test_a_and_b_both_access_schema(self) -> None:
        self.assertEqual(framework.CONTRACT_VERSION, "photocheck/v4")

    def test_contract_only_delivery_is_reported_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shutil.copyfile(FIXTURE, root / "express_001.json")
            report = inspect_a_delivery(root)
        self.assertTrue(report.contract_sample_valid)
        self.assertFalse(report.detector_source_ready)
        self.assertEqual(set(report.missing_engine_files), set(REQUIRED_ENGINE_FILES))

    def test_complete_engine_layout_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            shutil.copyfile(FIXTURE, root / "express_001.json")
            (root / "express_001.png").write_bytes(b"fixture")
            detect = root / "core" / "detect"
            detect.mkdir(parents=True)
            for name in REQUIRED_ENGINE_FILES:
                body = ""
                if name == "pipeline.py":
                    body = "def analyze(*args, **kwargs):\n    pass\n\ndef probe_region(*args, **kwargs):\n    pass\n"
                elif name == "qr_classify.py":
                    body = "def classify(*args, **kwargs):\n    pass\n"
                (detect / name).write_text(body, encoding="utf-8")
            report = inspect_a_delivery(root)
        self.assertTrue(report.detector_source_ready)
        self.assertEqual(report.missing_engine_files, ())
        self.assertEqual(report.missing_functions, ())


if __name__ == "__main__":
    unittest.main()

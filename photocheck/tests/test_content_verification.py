from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from photocheck.contract import build_redaction_plan
from photocheck.core import ingest_image, process_and_export
from photocheck.tests.test_pre_detection import patterned_image


def finding(image_id: str, kind: str) -> dict[str, Any]:
    common = {
        "contract_version": "photocheck/v4",
        "record_type": "Detection",
        "id": f"det-{kind}",
        "image_id": image_id,
        "kind": kind,
        "bbox": [70, 35, 60, 45],
        "detector_score": 0.9,
        "risk": 2,
    }
    if kind == "text":
        return {
            **common,
            "subtype": "phone",
            "evidence": "ocr_rule",
            "details": {"masked_preview": "138****0000"},
        }
    if kind == "qr":
        return {
            **common,
            "subtype": "qr_unknown",
            "evidence": "qr_payload",
            "details": {"decodable": False},
        }
    return {
        **common,
        "subtype": "face_region",
        "evidence": "face_box",
        "details": {},
    }


def run_probe_case(kind: str, response: dict[str, Any]) -> tuple[dict[str, Any], list]:
    calls: list[tuple] = []

    def probe(image: Any, bbox: tuple[int, int, int, int], *, kinds: tuple[str, ...]):
        calls.append((Path(image), tuple(bbox), tuple(kinds)))
        return response

    with tempfile.TemporaryDirectory() as temp_dir:
        directory = Path(temp_dir)
        source = directory / "source.png"
        patterned_image().save(source, format="PNG")
        with ingest_image(source) as ingested:
            detection = finding(ingested.descriptor["image_id"], kind)
            decision = {
                "contract_version": "photocheck/v4",
                "record_type": "Decision",
                "finding_id": detection["id"],
                "action": "redact",
                "revision": 1,
            }
            plan = build_redaction_plan(
                ingested.descriptor,
                [detection],
                [decision],
                revision=1,
            )
            result = process_and_export(
                ingested,
                plan,
                output_dir=directory / "output",
                detections=[detection],
                decisions=[decision],
                content_probe=probe,
            )
    return result.verification, calls


class ContentVerificationTests(unittest.TestCase):
    def test_qr_is_failed_when_detected_and_decodable(self) -> None:
        report, calls = run_probe_case(
            "qr",
            {
                "residual_qr_detected": 1,
                "residual_qr_decodable": 1,
                "unavailable": [],
            },
        )
        self.assertEqual(report["disposal_state"], "failed")
        self.assertEqual(report["checks"][0]["method"], "a_qr_probe")
        self.assertEqual(calls[0][2], ("qr",))

    def test_qr_is_failed_when_detected_but_undecodable(self) -> None:
        report, _ = run_probe_case(
            "qr",
            {
                "residual_qr_detected": 1,
                "residual_qr_decodable": 0,
                "unavailable": [],
            },
        )
        self.assertEqual(report["disposal_state"], "failed")

    def test_qr_passes_only_when_nothing_is_detected(self) -> None:
        report, _ = run_probe_case(
            "qr",
            {
                "residual_qr_detected": 0,
                "residual_qr_decodable": 0,
                "unavailable": [],
            },
        )
        self.assertEqual(report["disposal_state"], "passed")

    def test_qr_is_pending_when_detector_is_unavailable(self) -> None:
        report, _ = run_probe_case(
            "qr",
            {
                "residual_qr_detected": 0,
                "residual_qr_decodable": 0,
                "unavailable": ["qr"],
            },
        )
        self.assertEqual(report["disposal_state"], "pending")
        self.assertEqual(report["checks"][0]["method"], "a_qr_unavailable")

    def test_inconsistent_qr_probe_fails_safe(self) -> None:
        report, _ = run_probe_case(
            "qr",
            {
                "residual_qr_detected": 0,
                "residual_qr_decodable": 1,
                "unavailable": [],
            },
        )
        self.assertEqual(report["disposal_state"], "failed")
        self.assertEqual(report["checks"][0]["method"], "a_qr_probe_inconsistent")

    def test_ocr_residual_fails_and_clean_passes(self) -> None:
        failed, _ = run_probe_case(
            "text",
            {"residual_text": 2, "unavailable": []},
        )
        self.assertEqual(failed["disposal_state"], "failed")

        passed, _ = run_probe_case(
            "text",
            {"residual_text": 0, "unavailable": []},
        )
        self.assertEqual(passed["disposal_state"], "passed")

    def test_ocr_unavailable_is_pending(self) -> None:
        report, _ = run_probe_case(
            "text",
            {"residual_text": 0, "unavailable": ["text"]},
        )
        self.assertEqual(report["disposal_state"], "pending")

    def test_face_residual_and_unavailable(self) -> None:
        failed, _ = run_probe_case(
            "face",
            {"residual_face": 1, "unavailable": []},
        )
        self.assertEqual(failed["disposal_state"], "failed")

        pending, _ = run_probe_case(
            "face",
            {"residual_face": 0, "unavailable": ["face"]},
        )
        self.assertEqual(pending["disposal_state"], "pending")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from photocheck.core.full_recheck import full_file_recheck
from photocheck.detectors import AEnvelope


def detection(
    finding_id: str,
    *,
    kind: str = "text",
    subtype: str = "phone",
    bbox: list[int] | None = None,
) -> dict:
    return {
        "contract_version": "photocheck/v4",
        "record_type": "Detection",
        "id": finding_id,
        "image_id": "image-1",
        "kind": kind,
        "subtype": subtype,
        "bbox": bbox or [10, 10, 100, 30],
        "detector_score": 0.9,
        "evidence": "ocr_rule" if kind == "text" else "qr_payload",
        "risk": 2,
        "details": (
            {"masked_preview": "138****0000"}
            if kind == "text"
            else {"decodable": False}
        ),
    }


class FullRecheckTests(unittest.TestCase):
    def run_recheck(self, analyzed: list[dict], decisions: list[dict]) -> dict:
        original = detection("known")

        def analyzer(*args, **kwargs):
            return AEnvelope(
                image_descriptor={
                    "contract_version": "photocheck/v4",
                    "record_type": "ImageDescriptor",
                    "image_id": "image-1",
                    "width": 200,
                    "height": 100,
                    "orientation": "exif_transposed",
                    "coordinate_space": "top_left_pixels",
                },
                detections=tuple(analyzed),
                warnings=(),
                timings_ms={},
            )

        return full_file_recheck(
            "unused.png",
            {"image_id": "image-1", "revision": 1, "items": []},
            [original],
            decisions,
            analyzer=analyzer,
        )

    def test_user_retained_detection_is_not_unplanned(self) -> None:
        decision = {
            "contract_version": "photocheck/v4",
            "record_type": "Decision",
            "finding_id": "known",
            "action": "retain",
            "revision": 1,
        }
        result = self.run_recheck([detection("new")], [decision])
        self.assertEqual(result["retained_count"], 1)
        self.assertEqual(result["unplanned_count"], 0)

    def test_detection_outside_retained_plan_is_unplanned(self) -> None:
        result = self.run_recheck(
            [detection("new", bbox=[120, 10, 50, 30])],
            [],
        )
        self.assertEqual(result["retained_count"], 0)
        self.assertEqual(result["unplanned_count"], 1)


if __name__ == "__main__":
    unittest.main()

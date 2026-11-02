from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import jsonschema

from photocheck.contract import (
    ContractError,
    build_redaction_plan,
    build_verification_report,
    compute_disposal_state,
    convert_v3_finding,
    validate_record,
    validate_records,
)
from photocheck.contract.validation import load_schema

EXAMPLE_PATH = Path(__file__).parents[1] / "examples" / "valid_records.json"


def load_example_records() -> list[dict]:
    with EXAMPLE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def records_of(records: list[dict], record_type: str) -> list[dict]:
    return [record for record in records if record["record_type"] == record_type]


def image() -> dict:
    return records_of(load_example_records(), "ImageDescriptor")[0]


def detection(
    finding_id: str = "det-phone",
    *,
    kind: str = "text",
    subtype: str = "phone",
    bbox: list[int] | None = None,
) -> dict:
    record = copy.deepcopy(
        next(item for item in load_example_records() if item.get("id") == "det-phone-001")
    )
    record["id"] = finding_id
    record["kind"] = kind
    record["subtype"] = subtype
    record["bbox"] = bbox if bbox is not None else [10, 20, 100, 30]
    if kind == "meta":
        record["evidence"] = "exif"
        record["subtype"] = "gps"
        record["bbox"] = None
        record["details"] = {"masked_preview": "GPS present"}
    elif kind == "qr":
        record["evidence"] = "qr_payload"
        record["subtype"] = "qr_unknown"
        record["details"] = {"decodable": False}
    elif kind == "face":
        record["evidence"] = "face_box"
        record["subtype"] = "face_region"
        record["details"] = {}
    return record


def decision(finding_id: str, action: str, revision: int = 1) -> dict:
    return {
        "contract_version": "photocheck/v4",
        "record_type": "Decision",
        "finding_id": finding_id,
        "action": action,
        "revision": revision,
    }


class SchemaTests(unittest.TestCase):
    def test_json_schema_itself_is_valid(self) -> None:
        jsonschema.Draft202012Validator.check_schema(load_schema())

    def test_valid_records_pass_schema_and_cross_record_validation(self) -> None:
        records = load_example_records()
        for record in records:
            validate_record(record, image=image())
        validate_records(records)

    def test_raw_sensitive_fields_are_rejected_by_strict_schema(self) -> None:
        record = detection()
        record["text_ref"] = "13800138000"
        with self.assertRaises(ContractError):
            validate_record(record)

    def test_meta_and_region_bbox_rules_are_kind_specific(self) -> None:
        meta = detection(kind="meta")
        meta["bbox"] = [1, 2, 3, 4]
        with self.assertRaises(ContractError):
            validate_record(meta)

        qr = detection(kind="qr", subtype="qr_unknown")
        qr["bbox"] = None
        with self.assertRaises(ContractError):
            validate_record(qr)

    def test_bbox_must_stay_inside_canonical_image(self) -> None:
        edge_safe = detection(bbox=[1400, 1160, 200, 40])
        validate_record(edge_safe, image=image())

        outside = detection(bbox=[1400, 1160, 201, 41])
        with self.assertRaises(ContractError):
            validate_record(outside, image=image())

    def test_duplicate_finding_ids_are_rejected(self) -> None:
        image_record = image()
        first = detection("duplicate")
        second = detection("duplicate", bbox=[10, 20, 100, 30])
        with self.assertRaises(ContractError):
            validate_records([image_record, first, second])

    def test_multiple_qr_findings_with_unique_ids_are_supported(self) -> None:
        first = detection("qr-one", kind="qr", subtype="qr_unknown", bbox=[10, 10, 100, 100])
        second = detection("qr-two", kind="qr", subtype="qr_wifi", bbox=[200, 10, 100, 100])
        validate_records([image(), first, second])


class WorkflowTests(unittest.TestCase):
    def test_plan_rejects_an_undecided_non_metadata_detection(self) -> None:
        phone = detection("phone-1")
        qr = detection("qr-1", kind="qr", subtype="qr_unknown", bbox=[200, 20, 100, 100])
        with self.assertRaises(ContractError):
            build_redaction_plan(
                image(),
                [phone, qr],
                [decision("phone-1", "redact")],
                revision=1,
            )

    def test_retain_is_a_residual_and_not_part_of_processing_success(self) -> None:
        phone = detection("phone-1")
        plan = build_redaction_plan(
            image(),
            [phone],
            [decision("phone-1", "retain")],
            revision=1,
        )
        report = build_verification_report(image(), plan, [phone], [decision("phone-1", "retain")], [])
        self.assertEqual(report["disposal_state"], "not_applicable")
        self.assertEqual(report["residuals"][0]["reason"], "retained")

    def test_empty_plan_is_not_applicable(self) -> None:
        validate_records([image()])
        plan = build_redaction_plan(image(), [], [], revision=1)
        report = build_verification_report(image(), plan, [], [], [])
        self.assertEqual(report["disposal_state"], "not_applicable")

    def test_pending_passed_and_failed_states(self) -> None:
        phone = detection("phone-1")
        redact = [decision("phone-1", "redact")]
        plan = build_redaction_plan(image(), [phone], redact, revision=1)

        pending = build_verification_report(image(), plan, [phone], redact, [])
        self.assertEqual(pending["disposal_state"], "pending")

        passed = build_verification_report(
            image(),
            plan,
            [phone],
            redact,
            [{"region_id": "redact:phone-1", "status": "passed", "method": "ocr"}],
        )
        self.assertEqual(passed["disposal_state"], "passed")

        failed = build_verification_report(
            image(),
            plan,
            [phone],
            redact,
            [{"region_id": "redact:phone-1", "status": "failed", "method": "ocr"}],
        )
        self.assertEqual(failed["disposal_state"], "failed")
        self.assertEqual(failed["residuals"][0]["reason"], "verification_failed")

    def test_changed_revision_makes_old_report_stale(self) -> None:
        phone = detection("phone-1")
        old_decision = decision("phone-1", "redact", revision=1)
        plan_v1 = build_redaction_plan(image(), [phone], [old_decision], revision=1)
        report_v1 = build_verification_report(
            image(),
            plan_v1,
            [phone],
            [old_decision],
            [{"region_id": "redact:phone-1", "status": "passed", "method": "ocr"}],
        )

        new_decision = decision("phone-1", "retain", revision=2)
        plan_v2 = build_redaction_plan(image(), [phone], [new_decision], revision=2)
        stale_report = copy.deepcopy(report_v1)
        with self.assertRaises(ContractError):
            validate_records([image(), phone, new_decision, plan_v2, stale_report])

    def test_manual_region_exists_only_in_redaction_plan(self) -> None:
        manual = {"id": "manual-1", "bbox": [10, 20, 50, 60]}
        plan = build_redaction_plan(image(), [], [], revision=1, manual_regions=[manual])
        self.assertIsNone(plan["items"][0]["finding_id"])
        self.assertEqual(plan["items"][0]["method"], "solid")
        report = build_verification_report(
            image(),
            plan,
            [],
            [],
            [{"region_id": "manual-1", "status": "not_applicable", "method": "visual"}],
        )
        self.assertEqual(report["disposal_state"], "pending")

    def test_metadata_cannot_be_retained_or_receive_a_decision(self) -> None:
        meta = detection("meta-1", kind="meta")
        with self.assertRaises(ContractError):
            build_redaction_plan(
                image(),
                [meta],
                [decision("meta-1", "retain")],
                revision=1,
            )

    def test_disposal_state_requires_every_region_to_pass(self) -> None:
        plan = {
            "items": [
                {"id": "one", "finding_id": "f-1", "bbox": [0, 0, 2, 2], "method": "solid"},
                {"id": "two", "finding_id": "f-2", "bbox": [3, 3, 2, 2], "method": "solid"},
            ]
        }
        checks = [
            {"region_id": "one", "status": "passed"},
            {"region_id": "two", "status": "not_applicable"},
        ]
        self.assertEqual(compute_disposal_state(plan, checks), "pending")


class AdapterTests(unittest.TestCase):
    def legacy_finding(self, **overrides: object) -> dict:
        record = {
            "id": "f-001",
            "kind": "text",
            "subtype": "phone",
            "bbox": [10, 20, 100, 30],
            "score": 0.9,
            "evidence": "ocr_rule",
            "text_ref": None,
            "payload_ref": None,
            "decodable": True,
            "idcard_check": "na",
            "risk": 2,
            "default_action": "hide",
            "selected": True,
            "action": "hide",
            "verify_status": "pass",
        }
        record.update(overrides)
        return record

    def test_unambiguous_v3_redact_is_converted(self) -> None:
        result = convert_v3_finding(self.legacy_finding(), image_id="image-1")
        self.assertEqual(result.detection["id"], "legacy:image-1:f-001")
        self.assertEqual(result.decision["action"], "redact")
        self.assertNotIn("verify_status", result.detection)

    def test_keep_and_skip_become_retain(self) -> None:
        for action in ("keep", "skip"):
            result = convert_v3_finding(
                self.legacy_finding(selected=False, action=action),
                image_id="image-1",
            )
            self.assertEqual(result.decision["action"], "retain")

    def test_v3_conflict_is_rejected(self) -> None:
        with self.assertRaises(ContractError):
            convert_v3_finding(
                self.legacy_finding(selected=False, action="hide"),
                image_id="image-1",
            )

    def test_v3_raw_sensitive_fields_are_rejected(self) -> None:
        for field in ("text_ref", "payload_ref", "raw_exif"):
            with self.subTest(field=field), self.assertRaises(ContractError):
                convert_v3_finding(
                    self.legacy_finding(**{field: "13800138000"}),
                    image_id="image-1",
                )

    def test_v3_metadata_keep_is_rejected(self) -> None:
        meta = self.legacy_finding(
            id="meta-1",
            kind="meta",
            subtype="gps",
            bbox=None,
            evidence="exif",
            selected=False,
            action="keep",
        )
        with self.assertRaises(ContractError):
            convert_v3_finding(meta, image_id="image-1")

    def test_v3_metadata_hide_becomes_detection_only(self) -> None:
        meta = self.legacy_finding(
            id="meta-1",
            kind="meta",
            subtype="gps",
            bbox=None,
            evidence="exif",
        )
        result = convert_v3_finding(meta, image_id="image-1")
        self.assertIsNone(result.decision)


if __name__ == "__main__":
    unittest.main()

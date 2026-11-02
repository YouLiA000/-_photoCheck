"""Construction of redaction plans and verification reports."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .validation import (
    CONTRACT_VERSION,
    ContractError,
    compute_disposal_state,
    validate_record,
    validate_records,
)


def build_redaction_plan(
    image: Mapping[str, Any],
    detections: Iterable[Mapping[str, Any]],
    decisions: Iterable[Mapping[str, Any]],
    *,
    revision: int,
    manual_regions: Iterable[Mapping[str, Any]] = (),
    method_by_finding: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a plan from redact decisions using solid masks by default."""

    image = dict(image)
    detections = [dict(detection) for detection in detections]
    decisions = [dict(decision) for decision in decisions]
    validate_records([image, *detections, *decisions])
    actionable_ids = {
        detection["id"] for detection in detections if detection["kind"] != "meta"
    }
    decided_ids = {decision["finding_id"] for decision in decisions}
    if decided_ids != actionable_ids:
        raise ContractError("every non-metadata Detection requires exactly one Decision")

    detection_by_id = {detection["id"]: detection for detection in detections}
    method_by_finding = dict(method_by_finding or {})
    items: list[dict[str, Any]] = []

    for decision in decisions:
        if decision["revision"] != revision:
            raise ContractError("decision revision differs from the requested plan revision")
        finding = detection_by_id.get(decision["finding_id"])
        if finding is None:
            raise ContractError(f"decision references unknown finding {decision['finding_id']}")
        if finding["kind"] == "meta":
            raise ContractError("metadata cannot have a Decision; it is always removed globally")
        if decision["action"] != "redact":
            continue
        if finding["bbox"] is None:
            raise ContractError("only region-based findings can be redacted")
        method = method_by_finding.get(finding["id"], "solid")
        if method not in {"solid", "blur", "mosaic"}:
            raise ContractError(f"unsupported redaction method {method!r}")
        items.append(
            {
                "id": f"redact:{finding['id']}",
                "finding_id": finding["id"],
                "bbox": list(finding["bbox"]),
                "method": method,
            }
        )

    for region in manual_regions:
        item = {
            "id": region["id"],
            "finding_id": None,
            "bbox": list(region["bbox"]),
            "method": region.get("method", "solid"),
        }
        items.append(item)

    plan = {
        "contract_version": CONTRACT_VERSION,
        "record_type": "RedactionPlan",
        "image_id": image["image_id"],
        "revision": revision,
        "items": items,
    }
    validate_record(plan, image=image)
    item_ids = [item["id"] for item in items]
    if len(item_ids) != len(set(item_ids)):
        raise ContractError("manual region IDs must be unique and cannot collide with redact IDs")
    return plan


def build_verification_report(
    image: Mapping[str, Any],
    plan: Mapping[str, Any],
    detections: Iterable[Mapping[str, Any]],
    decisions: Iterable[Mapping[str, Any]],
    checks: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a report, adding not_run checks for every unchecked region."""

    image = dict(image)
    plan = dict(plan)
    detections = [dict(detection) for detection in detections]
    decisions = [dict(decision) for decision in decisions]
    validate_records([image, *detections, *decisions, plan])
    detection_by_id = {detection["id"]: detection for detection in detections}
    plans_items = list(plan["items"])
    region_ids = {item["id"] for item in plans_items}

    normalized_checks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for check in checks:
        check = dict(check)
        if check["region_id"] not in region_ids:
            raise ContractError(f"check references unknown region {check['region_id']}")
        if check["region_id"] in seen:
            raise ContractError(f"duplicate check for region {check['region_id']}")
        seen.add(check["region_id"])
        normalized_checks.append(check)
    for item in plans_items:
        if item["id"] not in seen:
            normalized_checks.append(
                {
                    "region_id": item["id"],
                    "status": "not_run",
                    "method": "none",
                }
            )

    residuals: list[dict[str, Any]] = []
    for decision in decisions:
        if decision["action"] != "retain":
            continue
        finding = detection_by_id[decision["finding_id"]]
        residuals.append(_residual(finding, region_id=None, reason="retained"))

    item_by_region = {item["id"]: item for item in plans_items}
    for check in normalized_checks:
        if check["status"] != "failed":
            continue
        item = item_by_region[check["region_id"]]
        finding = detection_by_id.get(item["finding_id"]) if item["finding_id"] else None
        if finding is None:
            finding = {"kind": "manual", "subtype": "region"}
        residuals.append(
            _residual(
                finding,
                region_id=item["id"],
                reason="verification_failed",
            )
        )

    report = {
        "contract_version": CONTRACT_VERSION,
        "record_type": "VerificationReport",
        "image_id": image["image_id"],
        "plan_revision": plan["revision"],
        "disposal_state": compute_disposal_state(plan, normalized_checks),
        "checks": normalized_checks,
        "residuals": residuals,
    }
    validate_record(report, image=image)
    validate_records([image, *detections, *decisions, plan, report])
    return report


def _residual(
    finding: Mapping[str, Any],
    *,
    region_id: str | None,
    reason: str,
) -> dict[str, Any]:
    kind = finding["kind"]
    subtype = finding["subtype"]
    return {
        "region_id": region_id,
        "finding_id": finding.get("id"),
        "reason": reason,
        "kind": kind,
        "subtype": subtype,
        "masked_summary": f"{kind}/{subtype}",
    }


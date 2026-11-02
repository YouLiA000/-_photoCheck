"""Conservative v3 Finding to v4 Detection/Decision adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .validation import CONTRACT_VERSION, ContractError, validate_record

RAW_SENSITIVE_FIELDS = {
    "raw_exif",
    "text",
    "payload",
    "text_value",
    "payload_value",
}


@dataclass(frozen=True)
class AdapterResult:
    """Converted records; metadata has no Decision because it is auto-cleared."""

    detection: dict[str, Any]
    decision: dict[str, Any] | None


def convert_v3_finding(
    finding_v3: Mapping[str, Any],
    *,
    image_id: str,
    revision: int = 1,
) -> AdapterResult:
    """Convert a single legacy Finding, rejecting ambiguous or unsafe data."""

    source = dict(finding_v3)
    unsafe = RAW_SENSITIVE_FIELDS.intersection(source)
    for reference in ("text_ref", "payload_ref"):
        if source.get(reference) is not None:
            unsafe.add(reference)
    if unsafe:
        raise ContractError(
            "v3 record contains non-serializable or raw sensitive fields: "
            + ", ".join(sorted(unsafe))
        )

    kind = source.get("kind")
    subtype = source.get("subtype")
    if kind not in {"meta", "text", "qr", "face"}:
        raise ContractError(f"unsupported v3 kind {kind!r}")

    expected_evidence = {
        "meta": "exif",
        "text": "ocr_rule",
        "qr": "qr_payload",
        "face": "face_box",
    }[kind]
    evidence = source.get("evidence", expected_evidence)
    if evidence != expected_evidence:
        raise ContractError(f"v3 {kind} evidence must be {expected_evidence!r}")

    bbox = source.get("bbox")
    risk = source.get("risk")
    details: dict[str, Any] = {}
    if kind == "text" and subtype == "idcard":
        idcard_check = source.get("idcard_check")
        if idcard_check not in {"pass", "fail", "na"}:
            raise ContractError("v3 idcard finding requires idcard_check pass/fail/na")
        details["idcard_check"] = idcard_check
    if kind == "qr":
        decodable = source.get("decodable")
        if not isinstance(decodable, bool):
            raise ContractError("v3 qr finding requires boolean decodable")
        details["decodable"] = decodable

    legacy_id = source.get("id")
    if not isinstance(legacy_id, str) or not legacy_id:
        raise ContractError("v3 finding requires a non-empty id")

    detection = {
        "contract_version": CONTRACT_VERSION,
        "record_type": "Detection",
        "id": f"legacy:{image_id}:{legacy_id}",
        "image_id": image_id,
        "kind": kind,
        "subtype": subtype,
        "bbox": bbox,
        "detector_score": source.get("score"),
        "evidence": evidence,
        "risk": risk,
        "details": details,
    }
    validate_record(detection)

    decision = _convert_decision(source, detection["id"], revision)
    if decision is not None:
        validate_record(decision)
    return AdapterResult(detection=detection, decision=decision)


def _convert_decision(
    source: Mapping[str, Any],
    finding_id: str,
    revision: int,
) -> dict[str, Any] | None:
    selected = source.get("selected")
    action = source.get("action")
    if not isinstance(selected, bool):
        raise ContractError("v3 finding requires boolean selected")
    if action not in {"hide", "keep", "skip"}:
        raise ContractError("v3 finding action must be hide/keep/skip")

    if source["kind"] == "meta":
        if selected is not True or action != "hide":
            raise ContractError("v3 metadata cannot be retained; v4 removes it globally")
        return None

    if selected is True and action == "hide":
        normalized_action = "redact"
    elif selected is False and action in {"keep", "skip"}:
        normalized_action = "retain"
    else:
        raise ContractError(
            "v3 selected/action conflict; the adapter will not guess user intent"
        )

    return {
        "contract_version": CONTRACT_VERSION,
        "record_type": "Decision",
        "finding_id": finding_id,
        "action": normalized_action,
        "revision": revision,
    }


"""Contract validation tests: this is what costs the most to rework after W6, so pin it now."""

import pytest

from photocheck.detectors.a_engine.core.contract import CONTRACT_VERSION, ContractError, Detection, validate_records


def phone_dict() -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "record_type": "Detection",
        "id": "det-phone-001",
        "image_id": "image-demo-001",
        "kind": "text",
        "subtype": "phone",
        "bbox": [520, 410, 220, 42],
        "detector_score": 0.96,
        "evidence": "ocr_rule",
        "risk": 2,
        "details": {"masked_preview": "138****0000"},
    }


def test_roundtrip_ok():
    det = Detection.from_dict(phone_dict())
    out = det.to_dict()
    assert out["contract_version"] == CONTRACT_VERSION
    assert out["evidence"] == "ocr_rule"
    assert out["bbox"] == [520, 410, 220, 42]
    validate_records([out])


def test_unknown_field_rejected():
    bad = phone_dict()
    bad["raw_text"] = "13800138000"
    with pytest.raises(ContractError, match="unknown field"):
        Detection.from_dict(bad)


def test_evidence_must_match_kind():
    bad = phone_dict()
    bad["evidence"] = "exif"
    with pytest.raises(ContractError, match="evidence does not match kind"):
        Detection.from_dict(bad)


def test_meta_bbox_must_be_null():
    with pytest.raises(ContractError, match="bbox must be null when kind=meta"):
        Detection(id="det-meta-001", image_id="img", kind="meta", subtype="gps", bbox=(1, 2, 3, 4), risk=3)
    ok = Detection(id="det-meta-001", image_id="img", kind="meta", subtype="gps", bbox=None, risk=3)
    assert ok.to_dict()["bbox"] is None


def test_text_bbox_required():
    with pytest.raises(ContractError, match="bbox must not be null when kind=text"):
        Detection(id="det-phone-001", image_id="img", kind="text", subtype="phone", bbox=None, risk=2)


def test_idcard_requires_check():
    with pytest.raises(ContractError, match="missing required details"):
        Detection(
            id="det-idcard-001",
            image_id="img",
            kind="text",
            subtype="idcard",
            bbox=(0, 0, 10, 10),
            risk=3,
            details={"masked_preview": "1101**********0011"},
        )


def test_qr_requires_decodable():
    with pytest.raises(ContractError, match="missing required details"):
        Detection(id="det-qr-001", image_id="img", kind="qr", subtype="qr_wifi", bbox=(0, 0, 10, 10), risk=3, details={})


def test_details_reject_plaintext_keys():
    with pytest.raises(ContractError, match="must not contain plaintext fields"):
        Detection(
            id="det-phone-001",
            image_id="img",
            kind="text",
            subtype="phone",
            bbox=(0, 0, 10, 10),
            risk=2,
            details={"masked_preview": "138****0000", "text": "13800138000"},
        )


def test_masked_preview_must_actually_mask():
    with pytest.raises(ContractError, match="phone masked_preview"):
        Detection(
            id="det-phone-001",
            image_id="img",
            kind="text",
            subtype="phone",
            bbox=(0, 0, 10, 10),
            risk=2,
            details={"masked_preview": "13800138000"},
        )


def test_unknown_subtype_rejected():
    with pytest.raises(ContractError, match="does not allow subtype"):
        Detection(id="det-x-001", image_id="img", kind="text", subtype="bankcard", bbox=(0, 0, 10, 10), risk=2)


def test_risk_range():
    with pytest.raises(ContractError, match="risk"):
        Detection(id="det-phone-001", image_id="img", kind="text", subtype="phone", bbox=(0, 0, 10, 10), risk=4)


def test_bbox_must_be_positive_size():
    with pytest.raises(ContractError, match="width and height must be positive"):
        Detection(id="det-phone-001", image_id="img", kind="text", subtype="phone", bbox=(0, 0, 0, 10), risk=2)


def test_duplicate_id_within_image_rejected():
    a = phone_dict()
    b = phone_dict()
    b["bbox"] = [10, 10, 20, 20]
    with pytest.raises(ContractError, match="duplicate id within image_id"):
        validate_records([a, b])


def test_same_id_different_image_allowed():
    a = phone_dict()
    b = phone_dict()
    b["image_id"] = "image-demo-002"
    validate_records([a, b])


def test_score_out_of_range():
    with pytest.raises(ContractError, match="within 0..1"):
        Detection(
            id="det-phone-001",
            image_id="img",
            kind="text",
            subtype="phone",
            bbox=(0, 0, 10, 10),
            detector_score=1.4,
            risk=2,
        )

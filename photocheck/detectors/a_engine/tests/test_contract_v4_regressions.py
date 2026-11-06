"""Regression tests after the v4 contract revision - locks down the four review findings.

Each one maps to a scenario that really fires on real data, not a synthetic edge case:

1. ID number ending in X (spec card line 416: "18 digits, last may be X"; about 1 in 11 real cards)
2. meta masked_preview killed by the phone-number rule (EXIF dates, serial numbers)
3. details still mutable after validation, so plaintext leaks through to_dict()
4. an illegal QR summary drops the whole batch of detections (contract changed, qr.py lagged)
"""

from __future__ import annotations

import pytest

from photocheck.detectors.a_engine.core.contract import ContractError, Detection, ImageDescriptor, validate_records
from photocheck.detectors.a_engine.core.detect.entities import mask_idcard, mask_phone
from photocheck.detectors.a_engine.core.detect.qr import QRHit, build_detections


def _det(**kw):
    base = dict(
        id="det-1",
        image_id="image-1",
        kind="text",
        subtype="phone",
        bbox=(10, 20, 100, 30),
        detector_score=0.9,
        risk=2,
        details={"masked_preview": "138****8000"},
    )
    base.update(kw)
    return Detection(**base)


# --- 1. ID number ending in X ----------------------------------------------


def test_idcard_mask_ending_with_x_is_accepted():
    det = _det(
        subtype="idcard",
        risk=3,
        details={"masked_preview": "1101**********001X", "idcard_check": "pass"},
    )
    assert det.details["masked_preview"] == "1101**********001X"


def test_idcard_lowercase_x_is_normalized_not_rejected():
    det = _det(
        subtype="idcard",
        risk=3,
        details={"masked_preview": "1101**********001x", "idcard_check": "pass"},
    )
    assert det.details["masked_preview"] == "1101**********001X"


def test_idcard_mask_wrong_length_still_rejected():
    with pytest.raises(ContractError):
        _det(subtype="idcard", risk=3, details={"masked_preview": "1101****001X", "idcard_check": "pass"})


def test_real_mask_function_round_trips_through_contract():
    """mask_idcard output must go straight into a record, or W4 acceptance collapses."""
    for raw in ("110105199001010011", "11010519900101001X", "11010119900307001x"):
        masked = mask_idcard(raw)
        det = _det(subtype="idcard", risk=3, details={"masked_preview": masked, "idcard_check": "pass"})
        assert det.details["masked_preview"] == masked


# --- 2. meta masked_preview ------------------------------------------------


@pytest.mark.parametrize(
    "subtype,preview",
    [
        ("datetime", "2024-06-01 12:30"),
        ("datetime", "2024-06-01"),
        ("datetime", "2024-**-**"),
        ("device", "Xiaomi 14"),
        ("gps", "39.90,116.40"),
        ("serial", "SN****3456"),
    ],
)
def test_meta_preview_is_not_mistaken_for_plaintext(subtype, preview):
    det = _det(kind="meta", subtype=subtype, bbox=None, details={"masked_preview": preview})
    assert det.details["masked_preview"] == preview


def test_meta_serial_with_long_digit_run_is_rejected():
    with pytest.raises(ContractError):
        _det(kind="meta", subtype="serial", bbox=None, details={"masked_preview": "SN-2024-000123456"})


# --- 3. details are read-only ----------------------------------------------


def test_details_cannot_be_mutated_after_validation():
    det = _det()
    with pytest.raises(TypeError):
        det.details["raw_text"] = "13800138000"  # type: ignore[index]


# --- 4. bbox must stay inside the working image ----------------------------


def test_bbox_outside_image_is_rejected_on_full_snapshot():
    descriptor = ImageDescriptor(image_id="image-1", width=900, height=620).to_dict()
    det = _det(bbox=(850, 300, 200, 22)).to_dict()
    with pytest.raises(ContractError):
        validate_records([descriptor, det])


def test_bbox_inside_image_passes_full_snapshot():
    descriptor = ImageDescriptor(image_id="image-1", width=900, height=620).to_dict()
    validate_records([descriptor, _det(bbox=(850, 300, 50, 22)).to_dict()])


# --- 5. QR: typed fields + degrade without dropping the box ----------------


def test_qr_details_use_typed_fields():
    hits = [
        QRHit(payload="WIFI:S:MyHome;T:WPA;P:secret123;;", bbox=(10, 10, 80, 80), decodable=True, symbology="QRCODE"),
        QRHit(payload="https://example.com/a?b=1", bbox=(10, 100, 80, 80), decodable=True, symbology="QRCODE"),
    ]
    dets = build_detections(hits, "image-1")
    wifi = next(d for d in dets if d.subtype == "qr_wifi")
    link = next(d for d in dets if d.subtype == "qr_link")
    assert wifi.details == {"decodable": True, "safe_ssid": "MyHome"}
    assert link.details == {"decodable": True, "safe_domain": "example.com"}
    assert "secret123" not in str([d.to_dict() for d in dets])


def test_qr_with_illegal_domain_keeps_box_instead_of_dropping_batch():
    """An intranet QR host is localhost, not a legal domain - degrade the summary, keep the box."""
    hits = [QRHit(payload="http://localhost:8080/admin", bbox=(5, 5, 60, 60), decodable=True, symbology="QRCODE")]
    dets = build_detections(hits, "image-1")
    assert len(dets) == 1
    assert dets[0].bbox == (5, 5, 60, 60)
    assert dets[0].details == {"decodable": True}


# --- 6. phone masking must not eat the area code ---------------------------


def test_mask_phone_strips_country_code():
    assert mask_phone("+8613800138000") == "138****8000"
    assert mask_phone("8613800138000") == "138****8000"
    assert mask_phone("+86 138 0013 8000") == "138****8000"
    assert mask_phone("13800138000") == "138****8000"

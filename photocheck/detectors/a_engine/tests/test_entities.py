"""K-04 unit tests: phone and ID number, positive/negative samples, tri-state check digit, masking.

K-04 acceptance: at least 3 positives and 3 negatives per kind; positive recall >= 80%;
at most 2 false positives per image; a valid check digit -> pass(risk 3); one tampered
digit -> must not be pass, but the fail(risk 2) detection must be kept.
The "one tampered digit" case is a hard assertion because it is the spot most likely to
regress to the pre-v1.3 logic.

Chinese text inside the test data is intentional - those are the documents the rules
must match, not code comments.
"""

import pytest

from photocheck.detectors.a_engine.core.detect.entities import (
    blocks_to_detections,
    find_entities,
    idcard_check,
    mask_idcard,
    mask_phone,
    scan_text,
)
from photocheck.detectors.a_engine.core.detect.ocr import TextBlock

# Fictional sample: 110101, born 1990-03-07, sequence 001, check digit 1 (MOD 11-2)
VALID_ID = "110101199003070011"
TAMPERED_ID = VALID_ID[:-1] + ("0" if VALID_ID[-1] != "0" else "9")
INVALID_DATE_BODY = "11010119901332001"


def with_check_digit(body17: str) -> str:
    from photocheck.detectors.a_engine.core.detect.entities import (
        ISO7064_CODES,
        ISO7064_WEIGHTS,
    )

    total = sum(int(char) * weight for char, weight in zip(body17, ISO7064_WEIGHTS))
    return body17 + ISO7064_CODES[total % 11]


# ---------- check digit ----------

def test_idcard_check_pass():
    assert idcard_check(VALID_ID) == "pass"


def test_idcard_check_tampered_is_fail_not_pass():
    assert idcard_check(TAMPERED_ID) == "fail"


def test_idcard_check_invalid_length_is_na():
    assert idcard_check("11010119900307001") == "na"
    assert idcard_check("") == "na"


# ---------- masking ----------

def test_mask_phone():
    assert mask_phone("13800138000") == "138****8000"


def test_mask_idcard():
    masked = mask_idcard(VALID_ID)
    assert masked == "1101**********0011"
    assert len(masked) == 18
    assert VALID_ID[4:14] not in masked


# ---------- phone ----------

@pytest.mark.parametrize(
    "text",
    [
        "联系电话：13800138000",
        "手机 138 0013 8000",
        "手机：138-0013-8000",
        "手机：１３８－００１３－８０００",  # 全角
        "TEL:13800138000,",
    ],
)
def test_phone_positive(text):
    dets = scan_text(text)
    phones = [d for d in dets if d.subtype == "phone"]
    assert len(phones) == 1, f"{text}: no phone number recognised"
    assert phones[0].risk == 2
    assert phones[0].details["masked_preview"] == "138****8000"


@pytest.mark.parametrize(
    "text",
    [
        "手机：+8613800138000",
        "手机：008613800138000",
        "TEL: +86 138 0013 8000",
    ],
)
def test_phone_positive_with_country_code(text):
    phones = [d for d in scan_text(text) if d.subtype == "phone"]
    assert len(phones) == 1
    assert phones[0].details["masked_preview"] == "138****8000"


@pytest.mark.parametrize(
    "text",
    [
        "1380013800",  # 少一位
        "138001380001",  # 多一位
        "快递单号 7801234567890",
        "内部工号 20231102",
        "订单号：SF1234567890123",
    ],
)
def test_phone_negative(text):
    assert [d for d in scan_text(text) if d.subtype == "phone"] == []


# ---------- ID number ----------

def test_idcard_pass_risk3():
    dets = scan_text(f"公民身份号码 {VALID_ID}")
    ids = [d for d in dets if d.subtype == "idcard"]
    assert len(ids) == 1
    assert ids[0].details["idcard_check"] == "pass"
    assert ids[0].risk == 3


def test_idcard_tampered_still_reported_but_risk2():
    dets = scan_text(f"公民身份号码 {TAMPERED_ID}")
    ids = [d for d in dets if d.subtype == "idcard"]
    assert len(ids) == 1, "a mistyped number leaks just as much; it must not be dropped silently"
    assert ids[0].details["idcard_check"] == "fail"
    assert ids[0].details["idcard_check"] != "pass"
    assert ids[0].risk == 2


def test_idcard_not_swallowed_by_phone_rule():
    """An 18-digit ID contains an 11-digit run; the phone rule must not slice it into a phone."""
    dets = scan_text(VALID_ID)
    assert [d.subtype for d in dets] == ["idcard"]


def test_invalid_birth_date_with_valid_checksum_is_not_an_idcard():
    serial = with_check_digit(INVALID_DATE_BODY)
    assert idcard_check(serial) == "pass"
    assert [d for d in scan_text(serial) if d.subtype == "idcard"] == []


def test_invalid_birth_date_with_bad_checksum_is_still_reported():
    serial = with_check_digit(INVALID_DATE_BODY)
    bad = serial[:-1] + ("0" if serial[-1] != "0" else "1")
    ids = [d for d in scan_text(bad) if d.subtype == "idcard"]
    assert len(ids) == 1
    assert ids[0].details["idcard_check"] == "fail"
    assert ids[0].risk == 2


# ---------- context switch (K-04 fallback path) ----------

def test_require_context_switch():
    block = TextBlock(text=VALID_ID, bbox=(0, 0, 320, 22), score=0.9)
    assert blocks_to_detections([block], "img-a", require_idcard_context=True) == []
    loose = blocks_to_detections([block], "img-b", require_idcard_context=False)
    assert len(loose) == 1


def test_context_keyword_in_neighbor_line_keeps_detection():
    blocks = [
        TextBlock(text="公民身份号码", bbox=(0, 0, 160, 22), score=0.9),
        TextBlock(text=VALID_ID, bbox=(0, 26, 320, 22), score=0.9),
    ]
    dets = blocks_to_detections(blocks, "img-c", require_idcard_context=True)
    assert [d.subtype for d in dets] == ["idcard"]


# ---------- bbox and id ----------

def test_bbox_stays_inside_block():
    block = TextBlock(text="电话13800138000", bbox=(100, 50, 160, 20), score=0.9)
    det = blocks_to_detections([block], "img-d")[0]
    x, y, w, h = det.bbox
    assert 100 <= x < x + w <= 260
    assert (y, h) == (50, 20)


def test_ids_are_unique_and_sequential():
    dets = scan_text("13800138000 与 13900139000")
    assert [d.id for d in dets] == ["det-phone-001", "det-phone-002"]


def test_no_entity_returns_empty():
    assert find_entities("今天天气不错") == []
    assert find_entities("") == []

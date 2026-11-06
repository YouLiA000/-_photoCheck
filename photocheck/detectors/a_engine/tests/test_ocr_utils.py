"""K-03 pure-logic tests: no RapidOCR needed, synthetic boxes verify dedupe, same-line merge
and coordinate conversion.

"a phone number split into three boxes is still recognised" is written into K-04's
acceptance, but the outcome actually depends on K-03's same-line merge - so it is pinned
end to end here. Chinese TextBlock contents are test data, not comments.
"""

from photocheck.detectors.a_engine.core.config import OcrConfig
from photocheck.detectors.a_engine.core.detect.entities import scan_text
from photocheck.detectors.a_engine.core.detect.ocr import TextBlock, _box_to_bbox, _dedupe, _merge_same_line


def test_merge_split_phone_blocks():
    blocks = [
        TextBlock("138", (100, 50, 30, 20), 0.90),
        TextBlock("0013", (135, 50, 40, 20), 0.90),
        TextBlock("8000", (180, 50, 40, 20), 0.90),
    ]
    merged = _merge_same_line(blocks, OcrConfig())
    assert len(merged) == 1, "fragments on one line must merge, otherwise the phone number is torn apart"
    dets = scan_text(merged[0].text)
    assert [d.subtype for d in dets] == ["phone"]


def test_no_merge_across_columns():
    blocks = [
        TextBlock("收货人", (40, 50, 60, 20), 0.90),
        TextBlock("13900139000", (400, 50, 120, 20), 0.90),
    ]
    assert len(_merge_same_line(blocks, OcrConfig())) == 2


def test_no_merge_different_lines():
    blocks = [
        TextBlock("第一行文字", (40, 50, 100, 20), 0.90),
        TextBlock("第二行文字", (40, 90, 100, 20), 0.90),
    ]
    assert len(_merge_same_line(blocks, OcrConfig())) == 2


def test_dedupe_keeps_higher_score_on_overlap():
    low = TextBlock("号码", (10, 10, 20, 20), 0.60)
    high = TextBlock("号码", (11, 11, 20, 20), 0.95)
    out = _dedupe([low, high], 0.5)
    assert len(out) == 1
    assert out[0].score == 0.95


def test_dedupe_keeps_disjoint_blocks():
    a = TextBlock("甲", (0, 0, 20, 20), 0.9)
    b = TextBlock("乙", (200, 200, 20, 20), 0.9)
    assert len(_dedupe([a, b], 0.5)) == 2


def test_box_to_bbox_applies_scale_and_offset():
    """Coordinates must map back to the full image so B can compare a recheck box with the plan."""
    box = [[0, 0], [10, 0], [10, 20], [0, 20]]
    assert _box_to_bbox(box, scale=1.0, offset=(100, 50), bounds=(640, 480)) == (100, 50, 10, 20)
    assert _box_to_bbox(box, scale=2.0, offset=(100, 50), bounds=(640, 480)) == (100, 50, 5, 10)

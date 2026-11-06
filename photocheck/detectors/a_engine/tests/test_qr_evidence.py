"""Finder-pattern evidence: what separates a QR code from text that looks like one.

The gate exists because `cv2.QRCodeDetector` returns a quadrilateral over dense
text when a decode fails, and reporting every such box as `qr_unknown` gave 7
false positives on C's dev set (precision 12.5% for that subtype).

The trap this file is written against
-------------------------------------
The first version of the fix counted *nested squares* with `findContours`, on the
theory that a finder pattern is three nested contours. It is, but so is the
character `回`: outer square, light ring, inner square. Measured on a plate
reading "返回 回收 回报 回执 / 回龙观 回民 回访 回头" that check scored 16 finder
patterns; a cv2 quad over such a block would pass the gate and the false positive
would be back. So the assertions here are about the ratio (1:1:3:1:1) and the
arrangement (right isosceles triangle, one shared module size), not about
counting shapes.

Chinese literals in this file are test data - the glyphs the rule has to survive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from photocheck.detectors.a_engine.core.detect.qr_evidence import (  # noqa: E402
    FinderPattern,
    count_finder_patterns,
    find_finder_patterns,
    has_qr_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "express_001.png"
# The region cv2 reported as an undecodable QR on B's export: a name and address.
TEXT_REGION = (152, 194, 322, 290)

_CJK_FONTS = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)


def _sample_gray():
    Image = pytest.importorskip("PIL.Image")
    if not SAMPLE.is_file():
        pytest.skip(f"missing sample {SAMPLE.name} (rebuild with scripts/make_sample.py)")
    return np.array(Image.open(SAMPLE).convert("L"))


def _text_plate(text: str, font_px: int = 44) -> np.ndarray:
    Image = pytest.importorskip("PIL.Image")
    ImageDraw = pytest.importorskip("PIL.ImageDraw")
    ImageFont = pytest.importorskip("PIL.ImageFont")
    path = next((p for p in _CJK_FONTS if Path(p).is_file()), None)
    if path is None:
        pytest.skip("no CJK font on this host")
    img = Image.new("L", (620, 60 + font_px * text.count("\n") + 120), 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(path, font_px)
    y = 8
    for line in text.split("\n"):
        draw.text((8, y), line, fill=0, font=font)
        y += font_px + 6
    return np.array(img)


def _rings(size: int, thickness: int, gap: int) -> np.ndarray:
    """Concentric dark squares, i.e. the shape a contour check cannot tell from a finder."""
    img = np.full((size, size), 255, np.uint8)
    for i in range(3):
        pad = i * (thickness + gap)
        cv2.rectangle(img, (pad, pad), (size - 1 - pad, size - 1 - pad), 0, thickness)
    return img


# --------------------------------------------------------------------------- #
# a real code is recognised
# --------------------------------------------------------------------------- #


def test_real_qr_yields_three_verified_finders():
    patterns = find_finder_patterns(_sample_gray(), tol=0.6)

    assert len(patterns) == 3, f"expected the three corner finders, got {len(patterns)}"
    modules = [p.module for p in patterns]
    assert max(modules) < 1.5 * min(modules), f"module sizes disagree: {modules}"


def test_qr_region_passes_the_gate():
    gray = _sample_gray()
    assert count_finder_patterns(gray, TEXT_REGION) == 0
    assert has_qr_evidence(gray, None, min_finders=3)


# --------------------------------------------------------------------------- #
# text that imitates a finder pattern is rejected
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "text",
    [
        "返回 回收 回报 回执\n回龙观 回民 回访 回头",
        "田田田田田田田田\n田田田田田田田田",
        "收货地址：回龙观东大街\n订单号：7801234567890",
    ],
)
def test_cjk_nested_squares_are_not_finder_patterns(text):
    """`回` is three nested squares; it is not a finder pattern.

    The distinguishing fact is that its centre pixel is the hollow interior, so
    the 1:1:3:1:1 scan cannot start - no amount of contour nesting helps it.
    """
    plate = _text_plate(text)
    assert count_finder_patterns(plate) == 0


def test_nested_rings_with_equal_thickness_are_rejected():
    """Three nested squares with the wrong run ratios are still not a finder."""
    img = _rings(size=120, thickness=10, gap=10)
    assert count_finder_patterns(img) == 0


def test_text_region_of_the_sample_has_no_evidence():
    """The exact bbox that produced the false positive carries no finder at all."""
    assert has_qr_evidence(_sample_gray(), TEXT_REGION, min_finders=2) is False


# --------------------------------------------------------------------------- #
# arrangement
# --------------------------------------------------------------------------- #


def _p(x: float, y: float, module: float = 5.0) -> FinderPattern:
    return FinderPattern(x=x, y=y, module=module)


def test_three_finders_in_a_right_triangle_pass():
    from photocheck.detectors.a_engine.core.detect.qr_evidence import _arrangement_ok

    corner, right, down = _p(10, 10), _p(110, 10), _p(10, 110)
    assert _arrangement_ok([corner, right, down], 3) is True


def test_three_collinear_finders_are_rejected():
    """Three squares in a row (a line of `回`) is not a code."""
    from photocheck.detectors.a_engine.core.detect.qr_evidence import _arrangement_ok

    row = [_p(10, 10), _p(80, 10), _p(150, 10)]
    assert _arrangement_ok(row, 3) is False


def test_two_aligned_finders_pass_at_min_finders_two():
    """A code cropped at the frame edge keeps two finders; K-05 still wants the box."""
    from photocheck.detectors.a_engine.core.detect.qr_evidence import _arrangement_ok

    assert _arrangement_ok([_p(10, 10), _p(110, 12)], 2) is True


def test_two_finders_with_mismatched_module_are_rejected():
    from photocheck.detectors.a_engine.core.detect.qr_evidence import _arrangement_ok

    assert _arrangement_ok([_p(10, 10, 4.0), _p(110, 12, 12.0)], 2) is False


def test_a_single_finder_is_never_enough():
    from photocheck.detectors.a_engine.core.detect.qr_evidence import _arrangement_ok

    assert _arrangement_ok([_p(10, 10)], 2) is False

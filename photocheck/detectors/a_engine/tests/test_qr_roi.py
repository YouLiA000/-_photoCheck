"""QR ROI re-check: quiet zone handling (K-09c risk area).

Why this file exists
--------------------
`Detection.bbox` hugs the QR modules. Cropping exactly at that box removes the
quiet zone (4 modules of light margin) and the decoder fails. In a re-check that
failure reads as "no residual", which turns a perfectly visible, unredacted code
into a `passed` verification. That is worse than a miss: the user sees a green
result for an unprotected code.

Test design notes
-----------------
An earlier version asserted "with zero padding the code must NOT decode". That is
a statement about the decoder, not about our code: pyzbar with internal
thresholding can still decode a tight crop, so the test failed on machines whose
zbar build behaves differently, telling us nothing about a regression.

What is asserted now:
  * behaviour that must hold on any backend (visible code is found; solid cover
    is not decodable; padding never decreases what is decodable);
  * the expansion itself as pure geometry (margin applied, capped, clamped),
    which is decoder independent and therefore stable everywhere.
"""

from __future__ import annotations

from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from photocheck.detectors.a_engine.core.config import QrConfig  # noqa: E402
from photocheck.detectors.a_engine.core.detect import qr as qr_mod  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "express_001.png"
PAYLOAD = "https://example.com/order/12345"

pytestmark = pytest.mark.skipif(qr_mod.backend() == "none", reason="no QR decoder backend")


def _sample_image():
    Image = pytest.importorskip("PIL.Image")
    if not SAMPLE.is_file():
        pytest.skip(f"missing sample {SAMPLE.name} (rebuild with scripts/make_sample.py)")
    return Image.open(SAMPLE).convert("RGB")


def _encode(text: str, scale: int = 4) -> np.ndarray:
    if not hasattr(cv2, "QRCodeEncoder_create"):
        pytest.skip("this OpenCV build has no QR encoder")
    code = cv2.QRCodeEncoder_create().encode(text)
    if code.ndim == 2:
        code = cv2.cvtColor(code, cv2.COLOR_GRAY2BGR)
    # encoder output is 29x29 only; detectors need a larger symbol
    return cv2.resize(code, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)


def _sample_qr_bbox() -> tuple[int, int, int, int]:
    """bbox of the QR as K-09c actually sees it: taken from a Detection."""
    hits = qr_mod.detect_qr(_sample_image())
    assert hits, "sample has no QR at all; the fixture is broken"
    return hits[0].bbox


# --------------------------------------------------------------------------- #
# behaviour that must hold on every backend
# --------------------------------------------------------------------------- #


def test_visible_code_is_found_through_probe_region():
    """The real K-09c call: probe_region(export, detection.bbox) must still see the code."""
    from photocheck.detectors.a_engine.core.detect import probe_region

    probe = probe_region(_sample_image(), _sample_qr_bbox())
    assert probe.residual_qr_detected >= 1, "visible code not detected inside its own bbox"
    assert probe.residual_qr_decodable >= 1, "visible code detected but not decodable"


def test_solid_cover_makes_code_undecodable():
    """A filled rectangle over the code must leave nothing decodable."""
    img = _sample_image()
    x, y, w, h = _sample_qr_bbox()
    arr = np.array(img)
    # cover the bbox plus margin, well past the quiet zone
    arr[max(0, y - 20) : y + h + 20, max(0, x - 20) : x + w + 20] = 0

    hits = qr_mod.detect_qr(arr, roi=(x, y, w, h))
    assert not any(hit.decodable for hit in hits), "solid cover still decodable"


def test_padding_never_reduces_decodability():
    """Monotonicity, not a fixed outcome: more context cannot lose a code.

    Both backends may decode a tight crop; neither may decode *less* after the
    quiet zone is restored. This is the invariant the fix depends on.
    """
    img = _sample_image()
    bbox = _sample_qr_bbox()
    tight = QrConfig(quiet_zone_min_px=0, quiet_zone_max_px=0)

    without = sum(1 for h in qr_mod.detect_qr(img, roi=bbox, cfg=tight) if h.decodable)
    with_padding = sum(1 for h in qr_mod.detect_qr(img, roi=bbox) if h.decodable)

    assert with_padding >= without


# --------------------------------------------------------------------------- #
# expansion as pure geometry (decoder independent, stable)
# --------------------------------------------------------------------------- #


def test_expansion_applies_configured_margin():
    cfg = QrConfig(quiet_zone_ratio=0.12, quiet_zone_min_px=8, quiet_zone_max_px=64)
    x0, y0, w, h = qr_mod._expand_for_quiet_zone((100, 100, 200, 200), 900, 900, cfg)

    # 0.12 * short side (200) = 24 px, inside [8, 64]; the box grows on all sides
    assert (x0, y0) == (76, 76)
    assert (w, h) == (248, 248)


def test_expansion_respects_min_and_max():
    small = QrConfig(quiet_zone_ratio=0.01, quiet_zone_min_px=8, quiet_zone_max_px=64)
    x0, y0, _, _ = qr_mod._expand_for_quiet_zone((100, 100, 20, 20), 900, 900, small)
    assert (x0, y0) == (92, 92), "min padding not applied"

    huge = QrConfig(quiet_zone_ratio=5.0, quiet_zone_min_px=8, quiet_zone_max_px=64)
    x0, y0, _, _ = qr_mod._expand_for_quiet_zone((100, 100, 20, 20), 900, 900, huge)
    assert (x0, y0) == (36, 36), "max padding not applied"


def test_expansion_clamped_to_image_bounds():
    """A code that fills the image has no room to expand; must not go negative."""
    cfg = QrConfig(quiet_zone_ratio=0.12, quiet_zone_min_px=8, quiet_zone_max_px=64)
    x0, y0, w, h = qr_mod._expand_for_quiet_zone((0, 0, 300, 300), 300, 300, cfg)
    assert (x0, y0) == (0, 0)
    assert (w, h) == (300, 300)

    x0, y0, w, h = qr_mod._expand_for_quiet_zone((20, 20, 260, 260), 300, 300, cfg)
    assert x0 >= 0 and y0 >= 0
    assert x0 + w <= 300 and y0 + h <= 300


def test_expansion_does_not_swallow_distant_code():
    """Expanding a ROI that holds nothing must not reach a code placed far away."""
    code = _encode(PAYLOAD)
    canvas = np.full((600, 600, 3), 255, dtype=np.uint8)
    h, w = code.shape[:2]
    canvas[300 : 300 + h, 300 : 300 + w] = code

    cfg = QrConfig()
    ex0, ey0, ew, eh = qr_mod._expand_for_quiet_zone((20, 20, 60, 60), 600, 600, cfg)
    assert ex0 + ew <= 300 and ey0 + eh <= 300, "expansion reached the code region"

    assert qr_mod.detect_qr(canvas, roi=(20, 20, 60, 60)) == []


def test_backend_is_reported():
    """A silent fallback hides a real capability gap: cv2 cannot read 1D barcodes."""
    assert qr_mod.backend() in {"pyzbar", "cv2"}


# --------------------------------------------------------------------------- #
# undecoded candidates need evidence, decoded ones do not
# --------------------------------------------------------------------------- #

# Where cv2 reported an undecodable QR on B's export: a name, a dorm address and
# an order-like number. No code in it.
TEXT_REGION = (152, 194, 322, 290)


def test_cv2_fallback_rejects_dense_text_quadrilateral(monkeypatch):
    """An undecoded cv2 quad over text must not become a `qr_unknown` record."""
    monkeypatch.setattr(qr_mod, "pyzbar_available", lambda: False)
    assert qr_mod.detect_qr(_sample_image(), roi=TEXT_REGION) == []


def test_finder_pattern_evidence_distinguishes_qr_from_text():
    gray = cv2.cvtColor(np.array(_sample_image())[:, :, ::-1], cv2.COLOR_BGR2GRAY)

    assert qr_mod._finder_pattern_count(gray, _sample_qr_bbox()) >= 3
    assert qr_mod._finder_pattern_count(gray, TEXT_REGION) == 0


def test_a_decoded_payload_is_never_gated():
    """Proof by payload: the gate must not touch a successful decode."""
    hits = qr_mod.detect_qr(_sample_image())
    assert any(h.decodable for h in hits), "the gate swallowed a real decode"


def test_multiple_codes_are_all_reported(monkeypatch):
    """Regression: `detectMulti` returns 2 values on OpenCV 4.10.

    The old code unpacked 4 and the surrounding `except` swallowed the ValueError
    on every call, so a photo holding several codes silently yielded one.
    """
    monkeypatch.setattr(qr_mod, "pyzbar_available", lambda: False)
    code = _encode(PAYLOAD)
    canvas = np.full((420, 900, 3), 255, dtype=np.uint8)
    h, w = code.shape[:2]
    canvas[60 : 60 + h, 40 : 40 + w] = code
    canvas[60 : 60 + h, 560 : 560 + w] = code

    hits = qr_mod.detect_qr(canvas)
    assert len(hits) >= 2, f"only {len(hits)} of 2 codes reported"

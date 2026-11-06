"""Pipeline integration tests: mock detectors drive "one image -> v4 record" without
RapidOCR or mediapipe installed.

Three things under test:
1. plaintext never appears in the serialised output (the red line most likely to break
   silently once Gradio is wired in);
2. one detector raising does not abort the run, it becomes a warning;
3. the output passes validate_records' cross-record checks.

Chinese text in the mocked detector output is test data, not comments.
"""

import json

import pytest

from photocheck.detectors.a_engine.core.detect import face as face_mod
from photocheck.detectors.a_engine.core.detect import ocr as ocr_mod
from photocheck.detectors.a_engine.core.detect import pipeline
from photocheck.detectors.a_engine.core.detect import qr as qr_mod
from photocheck.detectors.a_engine.core.detect.qr import QRHit


@pytest.fixture()
def white_image():
    Image = pytest.importorskip("PIL.Image")
    return Image.new("RGB", (640, 480), "white")


def test_analyze_with_mocked_detectors(monkeypatch, white_image):
    monkeypatch.setattr(
        ocr_mod,
        "detect_text_blocks",
        lambda image, roi=None, cfg=None: [
            ocr_mod.TextBlock(text="联系电话 138 0013 8000", bbox=(20, 30, 300, 24), score=0.93)
        ],
    )
    monkeypatch.setattr(
        qr_mod,
        "detect_qr",
        lambda image, roi=None, cfg=None: [
            QRHit(payload="WIFI:S:MyHome;T:WPA;P:x;;", bbox=(100, 200, 120, 120), decodable=True, symbology="QRCODE")
        ],
    )
    monkeypatch.setattr(face_mod, "detect_faces", lambda image, roi=None, cfg=None: [])

    result = pipeline.analyze(white_image, "image-test-001")

    subtypes = sorted(d["subtype"] for d in result.detections)
    assert subtypes == ["phone", "qr_wifi"]
    assert result.warnings == []

    blob = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "13800138000" not in blob
    assert "MyHome" in blob  # 域名 / SSID 属允许的安全摘要
    assert "secret123" not in blob

    phone = next(d for d in result.detections if d["subtype"] == "phone")
    assert phone["details"]["masked_preview"] == "138****8000"
    assert phone["evidence"] == "ocr_rule"
    assert phone["image_id"] == "image-test-001"

    qr = next(d for d in result.detections if d["subtype"] == "qr_wifi")
    assert qr["details"] == {"decodable": True, "safe_ssid": "MyHome"}
    assert qr["evidence"] == "qr_payload"


def test_detector_failure_is_warning_not_crash(monkeypatch, white_image):
    def boom(image, roi=None, cfg=None):
        raise RuntimeError("simulated OCR crash")

    monkeypatch.setattr(ocr_mod, "detect_text_blocks", boom)
    monkeypatch.setattr(qr_mod, "detect_qr", lambda image, roi=None, cfg=None: [])
    monkeypatch.setattr(face_mod, "detect_faces", lambda image, roi=None, cfg=None: [])

    result = pipeline.analyze(white_image, "image-test-002")

    assert result.detections == []
    assert any("OCR failed" in w for w in result.warnings)
    assert "text" in result.timings_ms


def test_unavailable_face_is_explicit(monkeypatch, white_image):
    def unavailable(image, roi=None, cfg=None):
        raise face_mod.DetectorUnavailable("mediapipe 未安装")

    monkeypatch.setattr(ocr_mod, "detect_text_blocks", lambda image, roi=None, cfg=None: [])
    monkeypatch.setattr(qr_mod, "detect_qr", lambda image, roi=None, cfg=None: [])
    monkeypatch.setattr(face_mod, "detect_faces", unavailable)

    result = pipeline.analyze(white_image, "image-test-003")
    assert any("not_applicable" in w for w in result.warnings), "unavailable face detection must degrade explicitly, never fake a pass"


def test_tiny_image_does_not_crash(monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    monkeypatch.setattr(ocr_mod, "detect_text_blocks", lambda image, roi=None, cfg=None: [])
    monkeypatch.setattr(qr_mod, "detect_qr", lambda image, roi=None, cfg=None: [])
    monkeypatch.setattr(face_mod, "detect_faces", lambda image, roi=None, cfg=None: [])

    tiny = Image.new("RGB", (1, 1), "black")
    result = pipeline.analyze(tiny, "image-tiny")
    assert result.detections == []
    assert result.image_descriptor["width"] == 1


def test_probe_region_reports_counts(monkeypatch, white_image):
    monkeypatch.setattr(
        ocr_mod,
        "detect_text_blocks",
        lambda image, roi=None, cfg=None: [ocr_mod.TextBlock(text="残留文字", bbox=(0, 0, 50, 20), score=0.8)],
    )
    monkeypatch.setattr(qr_mod, "detect_qr", lambda image, roi=None, cfg=None: [])
    monkeypatch.setattr(face_mod, "detect_faces", lambda image, roi=None, cfg=None: [])

    probe = pipeline.probe_region(white_image, [10, 20, 100, 100])
    assert probe.residual_text == 1
    assert probe.residual_text_score_max == pytest.approx(0.8)
    assert probe.residual_qr_decodable == 0
    assert probe.to_dict()["region"] == [10, 20, 100, 100]

    # Undecodable-only means "no code at all" here, so both counters stay 0.
    assert probe.residual_qr_detected == 0
    assert probe.unavailable == ()


def test_probe_region_separates_detected_from_decodable(monkeypatch, white_image):
    """A visible but unreadable code is a residual, not a clean region.

    K-09c decides between passed / pending / failed on these two numbers. If the
    probe only reported decodable codes, a partially covered code would look
    exactly like an empty region and the redaction would pass while the code is
    still on the image.
    """
    monkeypatch.setattr(ocr_mod, "detect_text_blocks", lambda image, roi=None, cfg=None: [])
    monkeypatch.setattr(
        qr_mod,
        "detect_qr",
        lambda image, roi=None, cfg=None: [QRHit(payload=None, bbox=(10, 20, 50, 50), decodable=False, symbology="QRCODE")],
    )
    monkeypatch.setattr(face_mod, "detect_faces", lambda image, roi=None, cfg=None: [])

    probe = pipeline.probe_region(white_image, [10, 20, 100, 100])
    assert probe.residual_qr_detected == 1
    assert probe.residual_qr_decodable == 0
    assert probe.to_dict()["residual_qr_detected"] == 1


def test_probe_region_marks_unavailable_detectors(monkeypatch, white_image):
    """Zero from a detector that never ran must not read as "nothing found"."""
    monkeypatch.setattr(ocr_mod, "available", lambda: False)
    monkeypatch.setattr(qr_mod, "available", lambda: False)
    monkeypatch.setattr(face_mod, "available", lambda: False)

    probe = pipeline.probe_region(white_image, [0, 0, 10, 10])
    assert probe.residual_text == 0
    assert probe.residual_qr_decodable == 0
    assert set(probe.unavailable) == {"text", "qr", "face"}
    assert probe.to_dict()["unavailable"] == ["text", "qr", "face"]


def test_probe_region_accepts_a_path(monkeypatch, white_image, tmp_path):
    """K-09 rechecks exported images read back from disk, so a path must behave like an object."""
    saved = tmp_path / "exported.png"
    white_image.save(saved)

    monkeypatch.setattr(
        ocr_mod,
        "detect_text_blocks",
        lambda image, roi=None, cfg=None: [ocr_mod.TextBlock(text="残留", bbox=(0, 0, 50, 20), score=0.7)],
    )
    monkeypatch.setattr(qr_mod, "detect_qr", lambda image, roi=None, cfg=None: [])
    monkeypatch.setattr(face_mod, "detect_faces", lambda image, roi=None, cfg=None: [])

    from_path = pipeline.probe_region(str(saved), [10, 20, 100, 100])
    from_object = pipeline.probe_region(white_image, [10, 20, 100, 100])
    assert from_path == from_object
    assert from_path.residual_text == 1

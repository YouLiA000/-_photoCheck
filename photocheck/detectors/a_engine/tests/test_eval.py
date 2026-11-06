"""Tests for the evaluation module: wrong metric definitions are worse than no metrics.

Three things break most easily and are covered explicitly here:

1. Greedy pairing: two GTs must never share one prediction (that would inflate recall).
2. Two levels: a correct box with a wrong subtype counts as "geometry hit, type miss",
   never as a miss.
3. Annotation errors (out of bounds, unknown subtype) must fail loudly at load time
   instead of leaking into the metrics.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from photocheck.detectors.a_engine.core.eval import (
    DEFAULT_IOU,
    EvalError,
    GtImage,
    GtObject,
    load_gt,
    match_image,
    iou,
    evaluate,
)


# ---------- iou ----------

def test_iou_identical():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)


def test_iou_disjoint_is_zero():
    assert iou((0, 0, 10, 10), (100, 100, 10, 10)) == 0.0


def test_iou_half_overlap():
    # left: 0..10 x 0..10; right: 5..15 x 0..10 -> intersection 5*10, union 200-50=150
    assert iou((0, 0, 10, 10), (5, 0, 10, 10)) == pytest.approx(50 / 150)


def test_iou_touching_edges_is_zero():
    # touching edges is not overlap
    assert iou((0, 0, 10, 10), (10, 0, 10, 10)) == 0.0


# ---------- pairing ----------

def _gt(objects: tuple[GtObject, ...], image_id: str = "t") -> GtImage:
    return GtImage(image_id=image_id, image=f"{image_id}.png", width=1000, height=1000, objects=objects)


def _obj(gid: str, kind: str, subtype: str, bbox) -> GtObject:
    return GtObject(gt_id=gid, kind=kind, subtype=subtype, bbox=bbox)


def _pred(pid: str, kind: str, subtype: str, bbox, risk: int = 2) -> dict:
    return {"id": pid, "kind": kind, "subtype": subtype, "bbox": bbox, "risk": risk}


def test_perfect_match():
    gt = _gt((_obj("g1", "text", "phone", (0, 0, 100, 20)),))
    row = match_image(gt, [_pred("p1", "text", "phone", (0, 0, 100, 20))])
    assert (row.tp, row.fp, row.fn, row.type_ok) == (1, 0, 0, 1)


def test_low_iou_counts_as_miss_and_false_positive():
    gt = _gt((_obj("g1", "text", "phone", (0, 0, 100, 20)),))
    # shifted by 60 -> intersection 40*20=800, union 2000+2000-800=3200 -> 0.25 < 0.5
    row = match_image(gt, [_pred("p1", "text", "phone", (60, 0, 100, 20))])
    assert (row.tp, row.fp, row.fn) == (0, 1, 1)
    assert row.missed[0].gt_id == "g1"
    assert row.extra[0]["pred_id"] == "p1"


def test_subtype_mismatch_is_geometry_hit_but_type_miss():
    """Right box, wrong type - the classic K-05 pass / K-06 fail shape.

    If the implementation treated a subtype mismatch as "no match", recall and
    precision would both drop and it would look like a broken detector while only
    the classifier is wrong. This test pins the two-level definition down.
    """
    gt = _gt((_obj("g1", "qr", "qr_link", (0, 0, 200, 200)),))
    row = match_image(gt, [_pred("p1", "qr", "qr_unknown", (0, 0, 200, 200), risk=1)])
    assert (row.tp, row.fp, row.fn) == (1, 0, 0)   # geometry hit
    assert row.type_ok == 0                        # type wrong
    assert row.matches[0].subtype_ok is False


def test_two_gt_cannot_share_one_prediction():
    """Greedy pairing must be one-to-one, otherwise two GTs inflate recall."""
    gt = _gt(
        (
            _obj("g1", "text", "phone", (0, 0, 100, 100)),
            _obj("g2", "text", "phone", (10, 10, 100, 100)),  # IoU with the same pred ~0.68
        )
    )
    preds = [_pred("p1", "text", "phone", (0, 0, 100, 100))]
    row = match_image(gt, preds)
    assert row.tp == 1
    assert row.fn == 1
    assert row.fp == 0


def test_kind_mismatch_never_matches():
    gt = _gt((_obj("g1", "qr", "qr_link", (0, 0, 100, 100)),))
    row = match_image(gt, [_pred("p1", "face", "face_region", (0, 0, 100, 100))])
    assert (row.tp, row.fp, row.fn) == (0, 1, 1)


def test_negative_image_all_predictions_are_false_positives():
    gt = _gt(())
    row = match_image(gt, [_pred("p1", "text", "phone", (0, 0, 10, 10))])
    assert (row.tp, row.fp, row.fn) == (0, 1, 0)


def test_bbox_none_prediction_is_skipped_not_dropped():
    gt = _gt(())
    row = match_image(gt, [_pred("p1", "meta", "datetime", None)])
    assert row.fp == 0                 # excluded from geometry stats
    assert len(row.skipped) == 1       # but it must still be reported
    assert "bbox" in row.skipped[0]["reason"]


def test_kinds_filter_applies_to_both_sides():
    gt = _gt(
        (
            _obj("g1", "text", "phone", (0, 0, 10, 10)),
            _obj("g2", "qr", "qr_link", (50, 50, 50, 50)),
        )
    )
    preds = [
        _pred("p1", "text", "phone", (0, 0, 10, 10)),
        _pred("p2", "qr", "qr_link", (50, 50, 50, 50)),
    ]
    row = match_image(gt, preds, kinds=["qr"])
    assert row.gt_count == 1
    assert row.tp == 1
    assert row.fp == 0


# ---------- annotation loading ----------

def _write_gt(tmp_path: Path, **overrides) -> Path:
    doc = {
        "image_id": "img1",
        "image": "img1.png",
        "width": 200,
        "height": 100,
        "objects": [{"gt_id": "g1", "kind": "text", "subtype": "phone", "bbox": [0, 0, 50, 20]}],
        "negative": False,
    }
    doc.update(overrides)
    path = tmp_path / f"{doc.get('image_id', 'img1')}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_gt_ok(tmp_path):
    gt = load_gt(_write_gt(tmp_path))
    assert gt.image_id == "img1"
    assert gt.objects[0].subtype == "phone"


def test_load_gt_rejects_unknown_subtype(tmp_path):
    path = _write_gt(
        tmp_path,
        objects=[{"gt_id": "g1", "kind": "text", "subtype": "face_region", "bbox": [0, 0, 10, 10]}],
    )
    with pytest.raises(EvalError, match="subtype"):
        load_gt(path)


def test_load_gt_rejects_out_of_image_bbox(tmp_path):
    path = _write_gt(
        tmp_path,
        objects=[{"gt_id": "g1", "kind": "text", "subtype": "phone", "bbox": [190, 0, 50, 20]}],
    )
    with pytest.raises(EvalError, match="exceeds image"):
        load_gt(path)


def test_load_gt_rejects_duplicate_gt_id(tmp_path):
    path = _write_gt(
        tmp_path,
        objects=[
            {"gt_id": "g1", "kind": "text", "subtype": "phone", "bbox": [0, 0, 10, 10]},
            {"gt_id": "g1", "kind": "text", "subtype": "phone", "bbox": [20, 0, 10, 10]},
        ],
    )
    with pytest.raises(EvalError, match="duplicate"):
        load_gt(path)


def test_load_gt_rejects_non_integer_bbox(tmp_path):
    path = _write_gt(
        tmp_path,
        objects=[{"gt_id": "g1", "kind": "text", "subtype": "phone", "bbox": [0.5, 0, 10, 10]}],
    )
    with pytest.raises(EvalError, match="integers"):
        load_gt(path)


# ---------- end to end (fake analyze injected, no model needed) ----------

class _FakeResult:
    def __init__(self, detections, timings_ms=None, warnings=None):
        self.detections = detections
        self.timings_ms = timings_ms or {}
        self.warnings = warnings or []


def test_evaluate_end_to_end(tmp_path):
    img_dir = tmp_path / "img"
    gt_dir = tmp_path / "gt"
    img_dir.mkdir()
    gt_dir.mkdir()
    (img_dir / "a.png").write_bytes(b"not-a-real-image")
    (gt_dir / "a.json").write_text(
        json.dumps(
            {
                "image_id": "a",
                "image": "a.png",
                "width": 100,
                "height": 100,
                "objects": [{"gt_id": "g1", "kind": "text", "subtype": "phone", "bbox": [0, 0, 40, 20]}],
            }
        ),
        encoding="utf-8",
    )

    calls: list[str] = []

    def fake_analyze(path, image_id):
        calls.append(image_id)
        return _FakeResult(
            detections=[{"id": "p1", "kind": "text", "subtype": "phone", "bbox": [0, 0, 40, 20], "risk": 2}],
            timings_ms={"text": 123.4},
        )

    report = evaluate(gt_dir, img_dir, fake_analyze, warmup_runs=1)
    # warmup + timed run = 2 calls, but only 1 image is counted
    assert len(calls) == 2
    assert len(report.images) == 1
    assert (report.tp, report.fp, report.fn) == (1, 0, 0)
    assert report.recall == 1.0
    assert report.timings_ms["text"] == [123.4]
    assert report.warmup_runs == 1


def test_evaluate_missing_image_raises(tmp_path):
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    (gt_dir / "x.json").write_text(
        json.dumps({"image_id": "x", "image": "missing.png", "width": 10, "height": 10, "objects": []}),
        encoding="utf-8",
    )
    with pytest.raises(EvalError, match="cannot find the image"):
        evaluate(gt_dir, tmp_path / "img", lambda p, i: _FakeResult([]))


def test_report_markdown_has_two_level_metrics(tmp_path):
    """The rendered report is Chinese (deliverable), so the assertions match Chinese headers."""
    img_dir = tmp_path / "img"
    gt_dir = tmp_path / "gt"
    img_dir.mkdir()
    gt_dir.mkdir()
    (img_dir / "a.png").write_bytes(b"x")
    (gt_dir / "a.json").write_text(
        json.dumps(
            {
                "image_id": "a",
                "image": "a.png",
                "width": 100,
                "height": 100,
                "objects": [{"gt_id": "g1", "kind": "qr", "subtype": "qr_link", "bbox": [0, 0, 50, 50]}],
            }
        ),
        encoding="utf-8",
    )

    def fake_analyze(path, image_id):
        return _FakeResult(
            detections=[{"id": "p1", "kind": "qr", "subtype": "qr_unknown", "bbox": [0, 0, 50, 50], "risk": 1}]
        )

    report = evaluate(gt_dir, img_dir, fake_analyze, warmup_runs=0)
    md = report.to_markdown()
    assert "几何召回 | 100.0%" in md
    assert "类型召回 | 0.0%" in md   # box right, type wrong
    assert "qr_unknown" in md        # the false-positive source shows the classification error


def test_default_iou_is_aligned_with_documented_value():
    assert DEFAULT_IOU == 0.5

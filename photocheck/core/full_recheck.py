"""R-03 full-file recheck on the final exported image."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Mapping

from photocheck.detectors import AEnvelope, analyze_a


def full_file_recheck(
    output_path: str,
    plan: Mapping[str, Any],
    detections: Iterable[Mapping[str, Any]],
    decisions: Iterable[Mapping[str, Any]],
    *,
    analyzer: Callable[..., AEnvelope] = analyze_a,
) -> dict[str, Any]:
    """Classify detections found by a fresh analysis of the final export."""

    detections = [dict(detection) for detection in detections]
    decisions = [dict(decision) for decision in decisions]
    detection_by_id = {detection["id"]: detection for detection in detections}
    retained = [
        detection_by_id[decision["finding_id"]]
        for decision in decisions
        if decision["action"] == "retain"
    ]

    envelope = analyzer(
        output_path,
        plan["image_id"],
        kinds=("text", "qr", "face"),
    )
    retained_hits: list[dict[str, Any]] = []
    unplanned: list[dict[str, Any]] = []
    for detection in envelope.detections:
        if any(_matches_retained(detection, known) for known in retained):
            retained_hits.append(dict(detection))
        else:
            unplanned.append(dict(detection))

    return {
        "image_id": plan["image_id"],
        "detections": [dict(item) for item in envelope.detections],
        "retained_count": len(retained_hits),
        "unplanned_count": len(unplanned),
        "unplanned": unplanned,
        "warnings": list(envelope.warnings),
    }


def _matches_retained(candidate: Mapping[str, Any], retained: Mapping[str, Any]) -> bool:
    if candidate["kind"] != retained["kind"] or candidate["subtype"] != retained["subtype"]:
        return False
    candidate_bbox = candidate.get("bbox")
    retained_bbox = retained.get("bbox")
    if not isinstance(candidate_bbox, list) or not isinstance(retained_bbox, list):
        return False
    return _iou(candidate_bbox, retained_bbox) >= 0.5


def _iou(first: list[int], second: list[int]) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    left = max(ax, bx)
    top = max(ay, by)
    right = min(ax + aw, bx + bw)
    bottom = min(ay + ah, by + bh)
    intersection = max(0, right - left) * max(0, bottom - top)
    if intersection == 0:
        return 0.0
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0.0


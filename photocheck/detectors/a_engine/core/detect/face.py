"""K-07 face detection (owner: A, optional card, P1). Detect only, never identify.

Ethical red line (spec K-07): no identity, gender, age or emotion output, and no
recognition model is imported anywhere. The UI copy is always "face region
detected". The return value here is a bbox and a score; the code has no concept of
"who this is" and must not grow one.

Fallback chain: mediapipe -> cv2.FaceDetectorYN (needs a local ONNX file) ->
manual box only (the K-11 entry point). If W7 runs late this card can be cut to
"manual box only" and its 1.5 person-days moved to K-09 and K-13.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ..config import DEFAULT_CONFIG, FaceConfig
from ..contract import BBox, Detection
from ._imgutil import crop, iou, resize_long_side, to_bgr

__all__ = ["FaceHit", "DetectorUnavailable", "available", "detect_faces", "build_detections"]


class DetectorUnavailable(RuntimeError):
    """Face detector unavailable. Callers record not_applicable; never fake a pass."""


@dataclass(frozen=True)
class FaceHit:
    bbox: BBox
    score: float | None = None


_DETECTOR: Any = None
_DETECTOR_LOCK = threading.Lock()
# Probe result cache. A successful import does not mean the detector works: the
# graph file is opened by the native layer, which fails on non-ASCII paths.
_PROBE: dict[str, Any] = {"done": False, "ok": False, "error": ""}


def _probe_mediapipe(cfg: FaceConfig) -> tuple[bool, str]:
    if not _PROBE["done"]:
        try:
            _get_mediapipe(cfg)
            _PROBE.update(done=True, ok=True, error="")
        except Exception as exc:  # noqa: BLE001
            _PROBE.update(done=True, ok=False, error=f"{type(exc).__name__}: {exc}")
    return bool(_PROBE["ok"]), str(_PROBE["error"])


def mediapipe_available() -> bool:
    return _probe_mediapipe(DEFAULT_CONFIG.face)[0]


def available() -> bool:
    return mediapipe_available() or Path(DEFAULT_CONFIG.face.yunet_model_path).exists()


def _get_mediapipe(cfg: FaceConfig) -> Any:
    global _DETECTOR
    with _DETECTOR_LOCK:
        if _DETECTOR is None:
            import mediapipe as mp

            _DETECTOR = (
                mp.solutions.face_detection,
                mp.solutions.face_detection.FaceDetection(
                    model_selection=cfg.model_selection,
                    min_detection_confidence=cfg.min_confidence,
                ),
            )
        return _DETECTOR


def _nms(hits: list[FaceHit], iou_thr: float) -> list[FaceHit]:
    kept: list[FaceHit] = []
    for hit in sorted(hits, key=lambda h: (h.score or 0.0), reverse=True):
        if all(iou(hit.bbox, k.bbox) <= iou_thr for k in kept):
            kept.append(hit)
    return kept


def _detect_mediapipe(arr: Any, scale: float, offset: tuple[int, int], bounds: tuple[int, int], cfg: FaceConfig) -> list[FaceHit]:
    import numpy as np

    _mp, detector = _get_mediapipe(cfg)
    rgb = np.ascontiguousarray(arr[:, :, ::-1])
    with _DETECTOR_LOCK:
        result = detector.process(rgb)
    if not result.detections:
        return []

    h, w = arr.shape[:2]
    bw, bh = bounds
    hits: list[FaceHit] = []
    for det in result.detections:
        box = det.location_data.relative_bounding_box
        x0 = box.xmin * w / scale + offset[0]
        y0 = box.ymin * h / scale + offset[1]
        x1 = (box.xmin + box.width) * w / scale + offset[0]
        y1 = (box.ymin + box.height) * h / scale + offset[1]
        xi0 = max(0, min(int(round(x0)), bw - 1))
        yi0 = max(0, min(int(round(y0)), bh - 1))
        xi1 = max(xi0 + 1, min(int(round(x1)), bw))
        yi1 = max(yi0 + 1, min(int(round(y1)), bh))
        score = float(det.score[0]) if getattr(det, "score", None) else None
        hits.append(FaceHit(bbox=(xi0, yi0, xi1 - xi0, yi1 - yi0), score=score))
    return hits


def _detect_yunet(arr: Any, scale: float, offset: tuple[int, int], bounds: tuple[int, int], cfg: FaceConfig) -> list[FaceHit]:
    import cv2

    model = Path(cfg.yunet_model_path)
    if not model.exists():
        raise DetectorUnavailable(
            f"mediapipe unavailable and no YuNet model at {model} "
            "(offline hosts must ship the ONNX file in advance)"
        )
    h, w = arr.shape[:2]
    detector = cv2.FaceDetectorYN_create(str(model), "", (w, h), cfg.min_confidence, cfg.nms_iou, 5000)
    _retval, faces = detector.detect(arr)
    if faces is None:
        return []

    bw, bh = bounds
    hits: list[FaceHit] = []
    for face in faces:
        fx, fy, fw, fh = face[:4]
        x0 = fx / scale + offset[0]
        y0 = fy / scale + offset[1]
        x1 = (fx + fw) / scale + offset[0]
        y1 = (fy + fh) / scale + offset[1]
        xi0 = max(0, min(int(round(x0)), bw - 1))
        yi0 = max(0, min(int(round(y0)), bh - 1))
        xi1 = max(xi0 + 1, min(int(round(x1)), bw))
        yi1 = max(yi0 + 1, min(int(round(y1)), bh))
        score = float(face[-1]) if len(face) > 14 else None
        hits.append(FaceHit(bbox=(xi0, yi0, xi1 - xi0, yi1 - yi0), score=score))
    return hits


def detect_faces(image: Any, roi: Sequence[int] | None = None, cfg: FaceConfig | None = None) -> list[FaceHit]:
    """Detect face regions only. Profile views and masks may be missed, no error."""
    cfg = cfg or DEFAULT_CONFIG.face
    arr = to_bgr(image)
    height, width = arr.shape[:2]
    if arr.size == 0 or height == 0 or width == 0:
        return []

    offset = (0, 0)
    if roi is not None:
        arr, offset = crop(arr, roi)

    base, scale = resize_long_side(arr, cfg.long_side)
    bounds = (width, height)

    hits: list[FaceHit] = []
    ok, error = _probe_mediapipe(cfg)
    mediapipe_ran = False
    if ok:
        try:
            hits = _detect_mediapipe(base, scale, offset, bounds, cfg)
            mediapipe_ran = True
        except Exception as exc:  # noqa: BLE001
            ok, error = False, f"{type(exc).__name__}: {exc}"

    # "Ran fine but found no face" is NOT unavailable. Do not take the fallback
    # path on an empty result, or a photo without faces starts reporting a broken
    # detector.
    if not mediapipe_ran:
        try:
            hits = _detect_yunet(base, scale, offset, bounds, cfg)
        except DetectorUnavailable as exc:
            reason = f"mediapipe failed ({error})" if error else "mediapipe is not installed"
            raise DetectorUnavailable(
                f"face detection unavailable: {reason}; {exc}. "
                "If mediapipe reports 'The path does not exist', the venv lives on a "
                "path containing non-ASCII characters (a project directory with a "
                "Chinese name is enough). Move the venv to a pure ASCII path such as "
                "C:/venvs/photocheck."
            ) from exc

    hits = _nms(hits, cfg.nms_iou)
    hits.sort(key=lambda h: (h.bbox[1], h.bbox[0]))
    return hits


def build_detections(hits: Sequence[FaceHit], image_id: str) -> list[Detection]:
    """FaceHit -> v4 Detection (kind=face, subtype=face_region).

    `details` is always empty: nothing about the person may be recorded.
    """
    return [
        Detection(
            id=f"det-face-{i:03d}",
            image_id=image_id,
            kind="face",
            subtype="face_region",
            bbox=hit.bbox,
            detector_score=hit.score,
            risk=1,
            details={},
        )
        for i, hit in enumerate(sorted(hits, key=lambda h: (h.bbox[1], h.bbox[0])), start=1)
    ]

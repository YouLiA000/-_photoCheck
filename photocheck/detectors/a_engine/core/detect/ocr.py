"""K-03 OCR text detection (owner: A).

Design constraints (spec K-03 + K-09):
1. Pure function. `detect_text_blocks(image, roi=None)` keeps no state across
   calls, because B's verifier (K-09) has to re-run the same code path on a
   region that was already redacted. ROI is a first-class argument, not a
   backdoor.
2. One coordinate system. Every bbox is `top_left_pixels` of the input image.
   When a ROI is passed the offset is added back automatically, so callers always
   receive full-image coordinates and never convert them by hand.
3. Output is UNCLASSIFIED text blocks (text / bbox / score). Sensitive-entity
   matching belongs to K-04, because the spec evaluates text recall and entity
   classification separately: merged together, you cannot tell whether OCR missed
   the text or the rules misread it.

Degradation: when the dual-scale pass is too slow, `OcrConfig(dual_scale=False)`
keeps a single 1600px pass. Recall decides, not the default.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Sequence

from ..config import DEFAULT_CONFIG, OcrConfig
from ..contract import BBox
from ._imgutil import clamp_roi as _clamp_roi
from ._imgutil import iou as _iou
from ._imgutil import resize_long_side as _resize_long_side
from ._imgutil import to_bgr as _to_bgr
from ._imgutil import union as _union

__all__ = ["TextBlock", "DetectorUnavailable", "available", "warmup", "detect_text_blocks"]


class DetectorUnavailable(RuntimeError):
    """Dependency or model missing. Callers apply each card's fallback row."""


@dataclass(frozen=True)
class TextBlock:
    """Raw OCR output, unclassified. Must NOT be serialised into a v4 record."""

    text: str
    bbox: BBox
    score: float


_ENGINES: dict[tuple[int, int, bool], Any] = {}
_ENGINE_LOCK = threading.Lock()


def available() -> bool:
    try:
        import cv2  # noqa: F401
        import numpy  # noqa: F401
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


def _thread_count(cfg: OcrConfig) -> int:
    if cfg.intra_op_num_threads and cfg.intra_op_num_threads > 0:
        return cfg.intra_op_num_threads
    import os

    return max(1, min(8, (os.cpu_count() or 4)))


def _get_engine(cfg: OcrConfig | None = None) -> Any:
    """Cache engines by parameters. Threads must be explicit: the default -1
    degrades to single-threaded on some Windows hosts (measured 3.3x slower)."""
    cfg = cfg or DEFAULT_CONFIG.ocr
    key = (_thread_count(cfg), cfg.inter_op_num_threads, cfg.use_cls)
    with _ENGINE_LOCK:
        engine = _ENGINES.get(key)
        if engine is None:
            if not available():
                raise DetectorUnavailable(
                    "RapidOCR is not installed (pip install rapidocr-onnxruntime). "
                    "Fallback: this card is unavailable and must be noted in the README."
                )
            from rapidocr_onnxruntime import RapidOCR

            engine = RapidOCR(
                intra_op_num_threads=key[0],
                inter_op_num_threads=key[1],
                use_cls=key[2],
            )
            _ENGINES[key] = engine
        return engine


def warmup() -> bool:
    """Warm the model up. Returns availability.

    Timing scripts must call this first, otherwise the first image carries the
    model load and T_ocr comes out several times too high.
    """
    try:
        engine = _get_engine()
    except DetectorUnavailable:
        return False
    import numpy as np

    engine(np.full((64, 64, 3), 255, dtype=np.uint8))
    return True


def _clahe_gray_bgr(arr: Any) -> Any:
    """Grayscale + CLAHE, then back to 3 channels for the OCR engine."""
    import cv2

    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)


def _box_to_bbox(box: Any, scale: float, offset: tuple[int, int], bounds: tuple[int, int]) -> BBox:
    import numpy as np

    pts = np.asarray(box, dtype=float).reshape(-1, 2)
    xs = pts[:, 0] / scale + offset[0]
    ys = pts[:, 1] / scale + offset[1]
    x0, y0 = float(xs.min()), float(ys.min())
    x1, y1 = float(xs.max()), float(ys.max())

    bw, bh = bounds
    xi0 = max(0, min(int(round(x0)), bw - 1))
    yi0 = max(0, min(int(round(y0)), bh - 1))
    xi1 = max(xi0 + 1, min(int(round(x1)), bw))
    yi1 = max(yi0 + 1, min(int(round(y1)), bh))
    return (xi0, yi0, xi1 - xi0, yi1 - yi0)


def _join_text(left: str, right: str) -> str:
    """Join two adjacent boxes. Add a space only between ASCII alphanumerics."""
    if not left:
        return right
    if not right:
        return left
    a, b = left[-1], right[0]
    if a.isascii() and a.isalnum() and b.isascii() and b.isalnum():
        return f"{left} {right}"
    return left + right


def _dedupe(blocks: list[TextBlock], iou_thr: float) -> list[TextBlock]:
    """Deduplicate dual-scale results: keep the higher score, drop heavy overlap."""
    kept: list[TextBlock] = []
    for blk in sorted(blocks, key=lambda b: b.score, reverse=True):
        drop = False
        for k in kept:
            iou = _iou(blk.bbox, k.bbox)
            if iou >= iou_thr or (blk.text == k.text and iou >= 0.3):
                drop = True
                break
        if not drop:
            kept.append(blk)
    return kept


def _merge_same_line(blocks: list[TextBlock], cfg: OcrConfig) -> list[TextBlock]:
    """Merge fragments that belong to the same line.

    When OCR splits a phone number into `138 0013 8000`, this is what puts it
    back together before K-04 ever sees it.
    """
    if not blocks:
        return []

    ordered = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
    lines: list[list[TextBlock]] = []
    for blk in ordered:
        bx, by, bw, bh = blk.bbox
        placed = False
        for line in lines:
            ly0 = min(b.bbox[1] for b in line)
            ly1 = max(b.bbox[1] + b.bbox[3] for b in line)
            overlap = min(ly1, by + bh) - max(ly0, by)
            if overlap > 0 and overlap >= cfg.line_overlap_ratio * min(ly1 - ly0, bh):
                line.append(blk)
                placed = True
                break
        if not placed:
            lines.append([blk])

    merged: list[TextBlock] = []
    for line in lines:
        line.sort(key=lambda b: b.bbox[0])
        cur = line[0]
        for nxt in line[1:]:
            gap = nxt.bbox[0] - (cur.bbox[0] + cur.bbox[2])
            char_w = cur.bbox[2] / max(1, len(cur.text))
            if gap <= cfg.line_gap_ratio * char_w:
                cur = TextBlock(
                    text=_join_text(cur.text, nxt.text),
                    bbox=_union(cur.bbox, nxt.bbox),
                    score=max(cur.score, nxt.score),
                )
            else:
                merged.append(cur)
                cur = nxt
        merged.append(cur)
    return merged


def _run_engine(arr: Any, cfg: OcrConfig) -> list[tuple[Any, str, float]]:
    engine = _get_engine(cfg)
    with _ENGINE_LOCK:
        result, _elapse = engine(arr)
    out: list[tuple[Any, str, float]] = []
    for item in result or []:
        if not item or len(item) < 3:
            continue
        box, text, score = item[0], item[1], item[2]
        text = str(text).strip()
        if not text:
            continue
        out.append((box, text, float(score)))
    return out


def detect_text_blocks(
    image: Any,
    roi: Sequence[int] | None = None,
    cfg: OcrConfig | None = None,
) -> list[TextBlock]:
    """Detect text blocks in the image, optionally inside one ROI.

    Args:
        image: PIL.Image or np.ndarray (RGB / BGR / grayscale).
        roi: `[x, y, w, h]`. When given, only that region is scanned, while the
             returned bboxes stay in full-image coordinates. K-09 re-runs this
             per RedactionPlan region with that region as the roi.
        cfg: K-03 parameters, see `core.config.OcrConfig`.

    Returns:
        Text blocks sorted by (row, column); an empty list when there is no text.
        No exception on empty input.
    """
    cfg = cfg or DEFAULT_CONFIG.ocr
    arr = _to_bgr(image)
    height, width = arr.shape[:2]
    if arr.size == 0 or width == 0 or height == 0:
        return []

    offset = (0, 0)
    if roi is not None:
        rx, ry, rw, rh = _clamp_roi(roi, width, height)
        arr = arr[ry : ry + rh, rx : rx + rw]
        offset = (rx, ry)

    passes: list[tuple[Any, float]] = []

    base, base_scale = _resize_long_side(arr, cfg.long_side)
    passes.append((_clahe_gray_bgr(base), base_scale))

    if cfg.dual_scale and cfg.upscale > 1.0:
        h2, w2 = base.shape[:2]
        if max(h2, w2) * cfg.upscale <= cfg.upscale_max_long_side:
            import cv2

            size = (max(1, int(round(w2 * cfg.upscale))), max(1, int(round(h2 * cfg.upscale))))
            up = cv2.resize(base, size, interpolation=cv2.INTER_CUBIC)
            passes.append((_clahe_gray_bgr(up), base_scale * cfg.upscale))

    raw: list[TextBlock] = []
    for proc, scale in passes:
        for box, text, score in _run_engine(proc, cfg):
            raw.append(TextBlock(text=text, bbox=_box_to_bbox(box, scale, offset, (width, height)), score=score))

    blocks = [b for b in _dedupe(raw, cfg.merge_iou) if b.score >= cfg.min_score]
    blocks = _merge_same_line(blocks, cfg)
    blocks.sort(key=lambda b: (b.bbox[1], b.bbox[0]))
    return blocks

"""Image helpers shared by the detectors (K-03 / K-05 / K-07).

Coordinate convention: every bbox is `[x, y, width, height]` in integer pixels,
origin at the top-left corner, matching the contract's
`coordinate_space = top_left_pixels`.
"""

from __future__ import annotations

from typing import Any, Sequence

from ..contract import BBox

__all__ = ["to_bgr", "clamp_roi", "resize_long_side", "iou", "union", "crop"]


def to_bgr(image: Any) -> Any:
    """Normalise PIL.Image / ndarray (RGB, BGR, grayscale, RGBA) to BGR uint8."""
    import numpy as np
    from PIL import Image

    if isinstance(image, Image.Image):
        arr = np.array(image.convert("RGB"))
    else:
        arr = np.asarray(image)
        if arr.ndim == 2:
            arr = np.repeat(arr[:, :, None], 3, axis=2)
        elif arr.ndim == 3 and arr.shape[2] == 4:
            arr = arr[:, :, :3]
        elif arr.ndim == 3 and arr.shape[2] == 3:
            pass
        else:
            raise ValueError(f"unsupported image array shape: {getattr(arr, 'shape', None)}")
    return np.ascontiguousarray(arr[:, :, ::-1])  # RGB -> BGR


def clamp_roi(roi: Sequence[int], width: int, height: int) -> BBox:
    """Clamp a ROI into the image. Out-of-range or negative input is not an error."""
    x, y, w, h = (int(v) for v in roi)
    x0 = max(0, min(x, width - 1))
    y0 = max(0, min(y, height - 1))
    x1 = max(x0 + 1, min(x + w, width))
    y1 = max(y0 + 1, min(y + h, height))
    return (x0, y0, x1 - x0, y1 - y0)


def crop(arr: Any, roi: Sequence[int]) -> tuple[Any, tuple[int, int]]:
    h, w = arr.shape[:2]
    x, y, bw, bh = clamp_roi(roi, w, h)
    return arr[y : y + bh, x : x + bw], (x, y)


def resize_long_side(arr: Any, long_side: int) -> tuple[Any, float]:
    """Downscale so the long side fits `long_side`. Returns (image, scale)."""
    import cv2

    h, w = arr.shape[:2]
    longest = max(h, w)
    if longest <= long_side:
        return arr, 1.0
    scale = long_side / float(longest)
    size = (max(1, int(round(w * scale))), max(1, int(round(h * scale))))
    return cv2.resize(arr, size, interpolation=cv2.INTER_AREA), scale


def iou(a: BBox, b: BBox) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    total = aw * ah + bw * bh - inter
    return inter / total if total > 0 else 0.0


def union(a: BBox, b: BBox) -> BBox:
    x0 = min(a[0], b[0])
    y0 = min(a[1], b[1])
    x1 = max(a[0] + a[2], b[0] + b[2])
    y1 = max(a[1] + a[3], b[1] + b[3])
    return (x0, y0, x1 - x0, y1 - y0)

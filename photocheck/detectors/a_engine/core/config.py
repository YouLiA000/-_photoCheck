"""Detector thresholds and pre-processing parameters.

Everything tunable lives here on purpose. K-04 threshold tuning must be a config
change, not a code change, otherwise every experiment becomes a diff and nobody
can tell whether a metric moved because of the parameter or the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class OcrConfig:
    """K-03 parameters."""

    # Post-processing: drop low-confidence boxes (spec: filter score < 0.5)
    min_score: float = 0.5
    # Pre-processing: cap the long side before inference
    long_side: int = 1600
    # Small-text pass: run the original and an N-times upscaled copy, merge by IoU
    dual_scale: bool = True
    upscale: float = 2.0
    upscale_max_long_side: int = 3200
    merge_iou: float = 0.5
    # Same-line merge: join when the horizontal gap < ratio * median char width
    line_gap_ratio: float = 0.6
    # Same-line merge: minimum vertical overlap ratio
    line_overlap_ratio: float = 0.5
    # RapidOCR thread count. The default (-1, auto) degrades to single-threaded on
    # some Windows hosts: measured 2.71s -> 0.81s on the same image. 0 means
    # "auto: min(8, cpu_count)".
    intra_op_num_threads: int = 0
    inter_op_num_threads: int = 2
    # 0/180 degree orientation classifier. Disabling it roughly halves the time
    # again (0.81s -> 0.38s) but drops upside-down text. Keep it on unless a
    # measurement says otherwise.
    use_cls: bool = True
    # K-04 fallback switch: when ID-card false positives are high, require a
    # context keyword nearby before reporting.
    require_idcard_context: bool = False


@dataclass(frozen=True)
class QrConfig:
    """K-05 parameters."""

    upscale: float = 2.0
    upscale_max_long_side: int = 2400
    # Adaptive binarisation window (odd number)
    adaptive_block: int = 31
    # Deduplicate pyzbar results against the cv2 fallback
    merge_iou: float = 0.5
    # When a ROI is given, decode an expanded crop. A QR code needs a quiet zone
    # (a light margin of ~4 modules); cropping exactly at the module boundary makes
    # decoders fail, which is exactly what K-09c does with Detection.bbox.
    # The margin is a ratio of the ROI short side, bounded by an absolute min/max.
    quiet_zone_ratio: float = 0.12
    quiet_zone_min_px: int = 8
    quiet_zone_max_px: int = 64

    # --- Evidence gate for UNDECODABLE candidates -------------------------
    # cv2 returns a quad even when it cannot decode, and on dense text that quad
    # covers a whole address block (7 false positives on C's dev set, plus one
    # reproduced on B's exported image). An undecoded candidate is kept only when
    # the crop really shows QR finder patterns; a decoded payload is its own
    # proof and is never gated.
    finder_min_count: int = 3
    # Tolerance on the 1:1:3:1:1 module run, as a fraction of one module
    finder_ratio_tol: float = 0.6
    # Anything smaller cannot hold three 7x7 finders plus a data area
    finder_min_side_px: int = 24


@dataclass(frozen=True)
class FaceConfig:
    """K-07 parameters."""

    long_side: int = 1280
    min_confidence: float = 0.5
    # 0 = short range (<=2m), 1 = full range (<=5m). The spec requires 1.
    model_selection: int = 1
    nms_iou: float = 0.4
    # The cv2.FaceDetectorYN fallback needs a local ONNX file; offline hosts must
    # ship it in advance.
    yunet_model_path: str = str(
        Path(__file__).resolve().parent
        / "detect"
        / "models"
        / "face_detection_yunet_2023mar.onnx"
    )


@dataclass(frozen=True)
class DetectConfig:
    ocr: OcrConfig = field(default_factory=OcrConfig)
    qr: QrConfig = field(default_factory=QrConfig)
    face: FaceConfig = field(default_factory=FaceConfig)


DEFAULT_CONFIG = DetectConfig()

__all__ = ["OcrConfig", "QrConfig", "FaceConfig", "DetectConfig", "DEFAULT_CONFIG"]

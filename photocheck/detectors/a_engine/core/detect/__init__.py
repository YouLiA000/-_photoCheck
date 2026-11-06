"""A: detector engine (K-03 OCR / K-04 sensitive entities / K-05 QR / K-06 class / K-07 face).

Only three entry points matter to the outside world:
    analyze()       one image -> ImageDescriptor + Detection list (B's UI, C's eval)
    probe_region()  re-run detection inside one region (B's K-09 verification)
    classify()      classify a QR payload (K-06, pure rules, offline)

Every detector is a pure `image (+ optional roi) -> result` function with no state
carried across calls. K-09 re-checks the same region through an independent code
path, which only works if nothing is cached between calls.
"""

from . import entities, face, ocr, pipeline, qr, qr_classify
from .entities import blocks_to_detections, find_entities, idcard_check, scan_text
from .ocr import TextBlock, detect_text_blocks
from .pipeline import ALL_KINDS, AnalysisResult, RegionProbe, analyze, detector_status, probe_region
from .qr import QRHit, detect_qr
from .qr_classify import QRClass, classify, to_display_class

__all__ = [
    "entities",
    "face",
    "ocr",
    "pipeline",
    "qr",
    "qr_classify",
    "TextBlock",
    "detect_text_blocks",
    "blocks_to_detections",
    "find_entities",
    "idcard_check",
    "scan_text",
    "QRHit",
    "detect_qr",
    "QRClass",
    "classify",
    "to_display_class",
    "AnalysisResult",
    "RegionProbe",
    "ALL_KINDS",
    "analyze",
    "probe_region",
    "detector_status",
]

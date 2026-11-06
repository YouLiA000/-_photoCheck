"""A-side detection pipeline: one image -> ImageDescriptor + Detection list.

Design points:
1. One failing detector must not take down the others. Exceptions are collected
   into `warnings` instead of failing the whole page, because the DoD requires
   "abnormal input does not crash": an all-black image, a tiny image and a
   non-image all have to reach a return value.
2. `timings_ms["text"]` is the T_ocr measurement K-03 asks for. The benchmark
   script reads it from here rather than timing the model separately.
3. `probe_region()` serves B's K-09 verification: re-run the same detectors on a
   region that was already redacted and report only what is still found there.
   It never decides passed / failed on B's behalf.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from ..config import DEFAULT_CONFIG, DetectConfig
from ..contract import BBox, Detection, validate_records
from ..secret_store import SecretStore
from . import face as face_det
from . import ocr as ocr_det
from . import qr as qr_det
from .entities import blocks_to_detections
from .standin_loader import describe, load_working_image

__all__ = ["ALL_KINDS", "AnalysisResult", "RegionProbe", "analyze", "probe_region", "detector_status"]

ALL_KINDS: tuple[str, ...] = ("text", "qr", "face")


@dataclass
class AnalysisResult:
    image_descriptor: dict[str, Any]
    detections: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_descriptor": self.image_descriptor,
            "detections": self.detections,
            "warnings": self.warnings,
            "timings_ms": self.timings_ms,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @property
    def counts_by_subtype(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for det in self.detections:
            out[det["subtype"]] = out.get(det["subtype"], 0) + 1
        return out


@dataclass(frozen=True)
class RegionProbe:
    """Evidence collected by re-running detectors on one region.

    This is not a verdict. K-09 turns these numbers into passed / failed / pending.

    `residual_qr_detected` and `residual_qr_decodable` are deliberately separate:
    a code that is still visible but no longer decodable is NOT the same as no code
    at all. Reporting only the decodable count makes "found a code but could not
    read it" look identical to "clean region", which would let a bad redaction pass.

    `unavailable` lists the detectors that could not run at all. An empty result
    from a detector that never ran must be treated as pending, never as passed.
    """

    region: BBox
    residual_text: int = 0
    residual_text_score_max: float = 0.0
    residual_qr_detected: int = 0
    residual_qr_decodable: int = 0
    residual_face: int = 0
    unavailable: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "region": list(self.region),
            "residual_text": self.residual_text,
            "residual_text_score_max": round(self.residual_text_score_max, 4),
            "residual_qr_detected": self.residual_qr_detected,
            "residual_qr_decodable": self.residual_qr_decodable,
            "residual_face": self.residual_face,
            "unavailable": list(self.unavailable),
        }


def detector_status() -> dict[str, str]:
    """Per-detector availability. The README fallback section quotes this directly.

    `qr` reports ok / unavailable only, keeping the external contract stable.
    `qr_backend` reports the decoder actually in use: `cv2` means 1D barcodes are
    not readable at all. That is a capability gap, so it has to be visible.
    """
    return {
        "ocr": "ok" if ocr_det.available() else "unavailable",
        "qr": "ok" if qr_det.available() else "unavailable",
        "face": "ok" if face_det.available() else "unavailable",
        "qr_backend": qr_det.backend(),
    }


def analyze(
    image: Any,
    image_id: str | None = None,
    cfg: DetectConfig | None = None,
    store: SecretStore | None = None,
    kinds: Sequence[str] = ALL_KINDS,
) -> AnalysisResult:
    """Run the full detection pipeline.

    Args:
        image: an image path, or an already loaded PIL.Image. When passing an
            image object it must already be orientation-corrected; otherwise every
            bbox will be rotated.
        image_id: identifier written into the records; defaults to the file stem.
        cfg: the three parameter groups, see `core.config`.
        store: plaintext container. If omitted, plaintext is not retained, which
            also means manual spot-checking is no longer possible.
        kinds: which detectors to run; all of them by default.
    """
    cfg = cfg or DEFAULT_CONFIG
    warnings: list[str] = []
    timings: dict[str, float] = {}

    if isinstance(image, (str, Path)):
        pil, descriptor = load_working_image(image, image_id)
    else:
        pil = image
        descriptor = describe(image, image_id or "image-001")
    image_id = descriptor.image_id

    detections: list[Detection] = []

    if "text" in kinds:
        started = time.perf_counter()
        try:
            blocks = ocr_det.detect_text_blocks(pil, cfg=cfg.ocr)
            detections.extend(blocks_to_detections(blocks, image_id, cfg=cfg.ocr, store=store))
        except ocr_det.DetectorUnavailable as exc:
            warnings.append(f"OCR unavailable, skipped: {exc}")
        except Exception as exc:  # noqa: BLE001 - one detector must not break the run
            warnings.append(f"OCR failed, skipped: {type(exc).__name__}: {exc}")
        timings["text"] = round((time.perf_counter() - started) * 1000, 1)

    if "qr" in kinds:
        started = time.perf_counter()
        try:
            hits = qr_det.detect_qr(pil, cfg=cfg.qr)
            detections.extend(qr_det.build_detections(hits, image_id, store=store))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"QR detection failed, skipped: {type(exc).__name__}: {exc}")
        timings["qr"] = round((time.perf_counter() - started) * 1000, 1)

    if "face" in kinds:
        started = time.perf_counter()
        try:
            hits = face_det.detect_faces(pil, cfg=cfg.face)
            detections.extend(face_det.build_detections(hits, image_id))
        except face_det.DetectorUnavailable as exc:
            warnings.append(f"face detection unavailable (recorded as not_applicable, "
                            f"fall back to a manual box): {exc}")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"face detection failed, skipped: {type(exc).__name__}: {exc}")
        timings["face"] = round((time.perf_counter() - started) * 1000, 1)

    detections.sort(key=lambda d: (d.bbox[1], d.bbox[0]) if d.bbox else (0, 0))
    records = [d.to_dict() for d in detections]
    validate_records(records)  # cross-record invariant: unique id per image_id

    return AnalysisResult(
        image_descriptor=descriptor.to_dict(),
        detections=records,
        warnings=warnings,
        timings_ms=timings,
    )


def probe_region(
    image: Any,
    bbox: Sequence[int],
    cfg: DetectConfig | None = None,
    kinds: Sequence[str] = ALL_KINDS,
) -> RegionProbe:
    """Re-run the detectors inside one region. Evidence for K-09, not a verdict.

    `image` accepts a path, a PIL.Image or an ndarray. K-09 usually works on an
    export re-read from disk, so accepting a path here saves the caller from
    loading and re-aligning coordinates by hand (and from getting it wrong).

    Results are counts, not conclusions. The caller decides passed / failed /
    pending. Two rules it must not break:

    - `residual_qr_detected > 0` with `residual_qr_decodable == 0` means a code is
      still visible but unreadable. That is a residual, not a clean region.
    - a kind listed in `unavailable` never ran. Its counter is 0 by default, which
      proves nothing.
    """
    cfg = cfg or DEFAULT_CONFIG
    if isinstance(image, (str, Path)):
        image, _ = load_working_image(image)
    region: BBox = (int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
    text_count = 0
    text_score = 0.0
    qr_detected = 0
    qr_decodable = 0
    face_count = 0
    unavailable: list[str] = []

    if "text" in kinds:
        if ocr_det.available():
            blocks = ocr_det.detect_text_blocks(image, roi=region, cfg=cfg.ocr)
            text_count = len(blocks)
            text_score = max((b.score for b in blocks), default=0.0)
        else:
            unavailable.append("text")

    if "qr" in kinds:
        if qr_det.available():
            hits = qr_det.detect_qr(image, roi=region, cfg=cfg.qr)
            qr_detected = len(hits)
            qr_decodable = sum(1 for h in hits if h.decodable)
        else:
            unavailable.append("qr")

    if "face" in kinds:
        if face_det.available():
            try:
                face_count = len(face_det.detect_faces(image, roi=region, cfg=cfg.face))
            except face_det.DetectorUnavailable:
                unavailable.append("face")
        else:
            unavailable.append("face")

    return RegionProbe(
        region=region,
        residual_text=text_count,
        residual_text_score_max=text_score,
        residual_qr_detected=qr_detected,
        residual_qr_decodable=qr_decodable,
        residual_face=face_count,
        unavailable=tuple(unavailable),
    )

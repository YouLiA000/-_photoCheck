"""K-09a structural and metadata verification before OCR/QR detectors exist."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
from PIL import Image

from photocheck.contract import build_verification_report, validate_records

from .ingest import IngestedImage
from .metadata import MetadataScanError, metadata_residual_tags, read_metadata
from .redaction import AppliedRegion, RedactedImage


class VerificationError(ValueError):
    """Raised when a final output fails a deterministic safety check."""


def verify_redacted_export(
    ingested: IngestedImage,
    output_path: str | os.PathLike[str],
    plan: Mapping[str, Any],
    redacted: RedactedImage,
    *,
    detections: Iterable[Mapping[str, Any]] = (),
    decisions: Iterable[Mapping[str, Any]] = (),
    exiftool_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Verify a final file and return a v4 VerificationReport."""

    detections = [dict(detection) for detection in detections]
    decisions = [dict(decision) for decision in decisions]
    descriptor = ingested.descriptor
    try:
        validate_records([descriptor, *detections, *decisions, dict(plan)])
    except Exception as exc:
        raise VerificationError(f"invalid workflow records: {exc}") from exc
    if redacted.plan_revision != plan["revision"]:
        raise VerificationError("redacted image revision does not match the plan")

    path = Path(output_path)
    try:
        with Image.open(path) as output:
            output.load()
            if output.size != ingested.image.size:
                raise VerificationError("final output dimensions differ from the working image")
    except VerificationError:
        raise
    except (OSError, ValueError) as exc:
        raise VerificationError("final output is not a readable image") from exc

    try:
        metadata = read_metadata(path, exiftool_path=exiftool_path)
    except MetadataScanError as exc:
        raise VerificationError("final metadata scan failed") from exc
    if metadata_residual_tags(metadata):
        raise VerificationError("final output still contains content metadata")

    checks = [
        _verify_region(path, region, detections)
        for region in redacted.applied_regions
    ]
    return build_verification_report(
        descriptor,
        plan,
        detections,
        decisions,
        checks,
    )


def _verify_region(
    output_path: Path,
    region: AppliedRegion,
    detections: list[dict[str, Any]],
) -> dict[str, Any]:
    finding = next(
        (
            detection
            for detection in detections
            if detection["id"] == region.finding_id
        ),
        None,
    )
    if finding is not None and finding["kind"] in {"text", "qr"}:
        return {
            "region_id": region.id,
            "status": "not_applicable",
            "method": "content_detector_pending",
        }
    if region.method != "solid":
        return {
            "region_id": region.id,
            "status": "not_applicable",
            "method": "semantic_verifier_pending",
        }

    try:
        with Image.open(output_path) as output:
            crop = output.crop(_bbox_xyxy(region.applied_bbox)).convert("RGBA")
            if crop.width <= 2 or crop.height <= 2:
                uniform = False
            else:
                interior = crop.crop((1, 1, crop.width - 1, crop.height - 1))
                pixels = np.asarray(interior, dtype=np.int16)
                rgb = pixels[..., :3]
                black_enough = bool(
                    float(rgb.mean()) <= 8
                    and float(np.percentile(rgb, 99)) <= 24
                )
                alpha_safe = bool(
                    pixels.shape[-1] == 3
                    or float(np.percentile(pixels[..., 3], 1)) >= 250
                )
                uniform = black_enough and alpha_safe
    except (OSError, ValueError):
        uniform = False
    return {
        "region_id": region.id,
        "status": "passed" if uniform else "failed",
        "method": "solid_black_region",
    }


def _bbox_xyxy(bbox: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x, y, width, height = bbox
    return x, y, x + width, y + height


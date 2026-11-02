"""K-08 region redaction in canonical image coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import cv2
import numpy as np
from PIL import Image, ImageDraw

from photocheck.contract import validate_record

from .ingest import IngestedImage

SUPPORTED_METHODS = frozenset({"solid", "blur", "mosaic"})


class RedactionError(ValueError):
    """Raised when a redaction plan cannot be safely applied."""


@dataclass(frozen=True)
class AppliedRegion:
    id: str
    finding_id: str | None
    source_bbox: tuple[int, int, int, int]
    applied_bbox: tuple[int, int, int, int]
    method: str


@dataclass
class RedactedImage:
    image: Image.Image
    image_id: str
    plan_revision: int
    applied_regions: tuple[AppliedRegion, ...]

    def close(self) -> None:
        self.image.close()

    def __enter__(self) -> "RedactedImage":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def redact_ingested(
    ingested: IngestedImage,
    plan: Mapping[str, Any],
    *,
    detections: Iterable[Mapping[str, Any]] = (),
) -> RedactedImage:
    """Apply a v4 plan to an IngestedImage."""

    return apply_redactions(
        ingested.image,
        plan,
        image_id=ingested.descriptor["image_id"],
        detections=detections,
    )


def apply_redactions(
    image: Image.Image,
    plan: Mapping[str, Any],
    *,
    image_id: str,
    detections: Iterable[Mapping[str, Any]] = (),
) -> RedactedImage:
    """Apply masks to a new pixel-only canvas and return the actual regions."""

    try:
        image.load()
    except (OSError, ValueError) as exc:
        raise RedactionError("image pixels are unavailable") from exc

    descriptor = {
        "contract_version": "photocheck/v4",
        "record_type": "ImageDescriptor",
        "image_id": image_id,
        "width": image.width,
        "height": image.height,
        "orientation": "exif_transposed",
        "coordinate_space": "top_left_pixels",
    }
    validate_record(descriptor)
    try:
        validate_record(plan, image=descriptor)
    except Exception as exc:
        raise RedactionError(f"invalid redaction plan: {exc}") from exc
    if plan.get("image_id") != image_id:
        raise RedactionError("redaction plan belongs to another image")

    working = _working_copy(image)
    detection_by_id = {detection["id"]: detection for detection in detections}
    ordered_items = sorted(
        plan.get("items", []),
        key=lambda item: _method_for_item(item, detection_by_id) == "solid",
    )

    applied: list[AppliedRegion] = []
    for item in ordered_items:
        method = _method_for_item(item, detection_by_id)
        if method not in SUPPORTED_METHODS:
            working.close()
            raise RedactionError(f"unsupported redaction method {method!r}")
        source_bbox = tuple(item["bbox"])
        applied_bbox = expand_bbox(source_bbox, working.size)
        try:
            _apply_region(working, applied_bbox, method)
        except Exception:
            working.close()
            raise
        applied.append(
            AppliedRegion(
                id=item["id"],
                finding_id=item["finding_id"],
                source_bbox=source_bbox,
                applied_bbox=applied_bbox,
                method=method,
            )
        )

    applied_by_id = {item.id: item for item in applied}
    ordered_regions = tuple(applied_by_id[item["id"]] for item in plan.get("items", []))
    return RedactedImage(
        image=working,
        image_id=image_id,
        plan_revision=plan["revision"],
        applied_regions=ordered_regions,
    )


def expand_bbox(
    bbox: tuple[int, int, int, int] | list[int],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """Expand by 4px plus 3% of the short side, clamped to the image."""

    x, y, width, height = (int(value) for value in bbox)
    image_width, image_height = image_size
    padding = 4 + math.ceil(min(width, height) * 0.03)
    left = max(0, x - padding)
    top = max(0, y - padding)
    right = min(image_width, x + width + padding)
    bottom = min(image_height, y + height + padding)
    return left, top, max(1, right - left), max(1, bottom - top)


def _method_for_item(
    item: Mapping[str, Any],
    detection_by_id: Mapping[str, Mapping[str, Any]],
) -> str:
    finding = detection_by_id.get(item.get("finding_id"))
    if finding is not None and finding["kind"] == "qr":
        return "solid"
    return str(item["method"])


def _working_copy(image: Image.Image) -> Image.Image:
    if image.mode == "RGBA":
        source = image.convert("RGBA")
    else:
        source = image.convert("RGB")
    rebuilt = Image.new(source.mode, source.size)
    rebuilt.paste(source)
    rebuilt.info.clear()
    return rebuilt


def _apply_region(
    image: Image.Image,
    bbox: tuple[int, int, int, int],
    method: str,
) -> None:
    x, y, width, height = bbox
    if method == "solid":
        draw = ImageDraw.Draw(image)
        fill = (0, 0, 0, 255) if image.mode == "RGBA" else (0, 0, 0)
        draw.rectangle((x, y, x + width - 1, y + height - 1), fill=fill)
        return

    crop = image.crop((x, y, x + width, y + height))
    alpha = crop.getchannel("A") if crop.mode == "RGBA" else None
    rgb = np.asarray(crop.convert("RGB")).copy()

    if method == "blur":
        kernel = max(3, min(width, height) // 4)
        if kernel % 2 == 0:
            kernel += 1
        processed = cv2.GaussianBlur(rgb, (kernel, kernel), 0)
    elif method == "mosaic":
        small_width = max(1, width // 20)
        small_height = max(1, height // 20)
        reduced = cv2.resize(rgb, (small_width, small_height), interpolation=cv2.INTER_AREA)
        processed = cv2.resize(
            reduced,
            (width, height),
            interpolation=cv2.INTER_NEAREST,
        )
    else:
        raise RedactionError(f"unsupported redaction method {method!r}")

    replacement = Image.fromarray(processed, mode="RGB")
    if alpha is not None:
        replacement = replacement.convert("RGBA")
        replacement.putalpha(alpha)
    image.paste(replacement, (x, y))


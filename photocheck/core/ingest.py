"""K-01 image loading, normalization and metadata detection."""

from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageOps, UnidentifiedImageError

from photocheck.contract import validate_record

from .metadata import (
    MetadataScanError,
    groups_are_system_metadata,
    read_metadata,
)
from .secrets import SecretStore

DEFAULT_MAX_FILE_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_PIXELS = 50_000_000
SUPPORTED_FORMATS = frozenset({"JPEG", "PNG"})


class ImageIngestError(ValueError):
    """Raised when an image cannot be safely normalized for processing."""


@dataclass
class IngestedImage:
    """Canonical image plus serializable metadata detections."""

    descriptor: dict[str, Any]
    image: Image.Image
    detections: tuple[dict[str, Any], ...]
    raw_metadata_ref: str
    source_sha256: str
    source_format: str
    _secret_store: SecretStore = field(repr=False)

    def get_raw_metadata(self) -> dict[str, Any]:
        return self._secret_store.get(self.raw_metadata_ref)

    def close(self) -> None:
        self._secret_store.discard(self.raw_metadata_ref)
        self.image.close()

    def __enter__(self) -> "IngestedImage":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def ingest_image(
    path: str | os.PathLike[str],
    *,
    secret_store: SecretStore | None = None,
    exiftool_path: str | os.PathLike[str] | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_pixels: int = DEFAULT_MAX_PIXELS,
) -> IngestedImage:
    """Load and normalize a JPEG/PNG and detect sensitive metadata classes."""

    source = Path(path)
    try:
        resolved = source.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ImageIngestError("image path does not exist") from exc
    if not resolved.is_file():
        raise ImageIngestError("image path must point to a regular file")

    size = resolved.stat().st_size
    if size == 0:
        raise ImageIngestError("image file is empty")
    if size > max_file_bytes:
        raise ImageIngestError(f"image file exceeds {max_file_bytes} bytes")

    source_bytes = resolved.read_bytes()
    source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    image_id = f"image-{source_sha256[:24]}"

    try:
        with Image.open(io.BytesIO(source_bytes)) as opened:
            image_format = opened.format
            if image_format not in SUPPORTED_FORMATS:
                raise ImageIngestError(
                    f"unsupported image format {image_format!r}; expected JPEG or PNG"
                )
            if opened.width * opened.height > max_pixels:
                raise ImageIngestError(f"image exceeds the {max_pixels}-pixel limit")
            if getattr(opened, "n_frames", 1) != 1:
                raise ImageIngestError("animated images are not supported")
            opened.load()
            canonical = ImageOps.exif_transpose(opened)
            if canonical.mode not in {"RGB", "RGBA"}:
                canonical = canonical.convert("RGB")
            canonical.load()
            working_image = canonical.copy()
    except ImageIngestError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageIngestError("file is not a valid JPEG or PNG image") from exc

    descriptor = {
        "contract_version": "photocheck/v4",
        "record_type": "ImageDescriptor",
        "image_id": image_id,
        "width": working_image.width,
        "height": working_image.height,
        "orientation": "exif_transposed",
        "coordinate_space": "top_left_pixels",
    }
    validate_record(descriptor)

    try:
        exif = read_metadata(resolved, exiftool_path=exiftool_path)
        detections = tuple(_metadata_detections(image_id, exif))
        for detection in detections:
            validate_record(detection)
    except MetadataScanError as exc:
        working_image.close()
        raise ImageIngestError(str(exc)) from exc
    except Exception:
        working_image.close()
        raise

    store = secret_store if secret_store is not None else SecretStore()
    raw_metadata_ref = store.put(exif)
    return IngestedImage(
        descriptor=descriptor,
        image=working_image,
        detections=detections,
        raw_metadata_ref=raw_metadata_ref,
        source_sha256=source_sha256,
        source_format=image_format,
        _secret_store=store,
    )


def _metadata_detections(
    image_id: str,
    metadata: Mapping[str, Any],
) -> list[dict[str, Any]]:
    tags = [_split_tag(key, value) for key, value in metadata.items()]
    rules = (
        (
            "gps",
            3,
            {
                "GPSLatitude",
                "GPSLongitude",
                "GPSPosition",
            },
            "GPS location present",
        ),
        (
            "datetime",
            2,
            {
                "DateTimeOriginal",
                "CreateDate",
                "DateTimeDigitized",
            },
            "Capture datetime present",
        ),
        (
            "serial",
            2,
            {
                "BodySerialNumber",
                "SerialNumber",
                "CameraSerialNumber",
                "InternalSerialNumber",
            },
            "Device serial present",
        ),
        (
            "device",
            1,
            {
                "Make",
                "Model",
                "LensModel",
                "UniqueCameraModel",
            },
            "Camera model or lens present",
        ),
        (
            "software",
            1,
            {
                "Software",
                "ProcessingSoftware",
                "CreatorTool",
            },
            "Processing software present",
        ),
    )

    found: list[dict[str, Any]] = []
    for subtype, risk, names, preview in rules:
        if any(_is_meaningful_tag(group, name, value, names) for group, name, value in tags):
            found.append(_meta_detection(image_id, subtype, risk, preview))

    if any(_is_thumbnail_tag(group, name, value) for group, name, value in tags):
        found.append(
            _meta_detection(
                image_id,
                "thumbnail",
                3,
                "Embedded thumbnail present",
            )
        )

    return sorted(found, key=lambda item: (-item["risk"], item["subtype"]))


def _meta_detection(
    image_id: str,
    subtype: str,
    risk: int,
    preview: str,
) -> dict[str, Any]:
    return {
        "contract_version": "photocheck/v4",
        "record_type": "Detection",
        "id": f"meta:{image_id}:{subtype}",
        "image_id": image_id,
        "kind": "meta",
        "subtype": subtype,
        "bbox": None,
        "detector_score": None,
        "evidence": "exif",
        "risk": risk,
        "details": {"masked_preview": preview},
    }


def _split_tag(key: str, value: Any) -> tuple[str, str, Any]:
    group, separator, name = key.partition(":")
    if not separator:
        return "", key, value
    return group, name, value


def _is_meaningful_tag(group: str, name: str, value: Any, names: set[str]) -> bool:
    if groups_are_system_metadata(group):
        return False
    if name not in names:
        return False
    return value is not None and value != "" and value != 0 and value != "(none)"


def _is_thumbnail_tag(group: str, name: str, value: Any) -> bool:
    if groups_are_system_metadata(group):
        return False
    if name in {"ThumbnailImage", "ThumbnailOffset", "ThumbnailLength"}:
        return value is not None and value != "" and value != 0
    return (
        group.startswith("IFD1")
        and name == "Compression"
        and value is not None
        and value != ""
        and value != 0
    )


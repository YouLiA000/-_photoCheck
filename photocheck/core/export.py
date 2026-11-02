"""K-02 metadata removal through pixel reconstruction."""

from __future__ import annotations

import io
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageCms, ImageStat, PngImagePlugin

from .ingest import IngestedImage
from .metadata import MetadataScanError, metadata_residual_tags, read_metadata

SUPPORTED_OUTPUT_FORMATS = frozenset({"JPEG", "PNG"})
_SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


class ExportError(ValueError):
    """Raised when a safe sanitized copy cannot be created."""


class UnsafeExportError(ExportError):
    """Raised when independent post-export verification finds metadata."""

    def __init__(self, residual_tags: tuple[str, ...]) -> None:
        self.residual_tags = residual_tags
        super().__init__(
            "sanitized export still contains metadata: " + ", ".join(residual_tags)
        )


@dataclass(frozen=True)
class SanitizedExport:
    output_path: Path
    source_format: str
    output_sha256: str
    source_sha256: str | None
    pixel_mean_abs_diff: float


def sanitize_ingested(
    ingested: IngestedImage,
    output_dir: str | os.PathLike[str],
    *,
    exiftool_path: str | os.PathLike[str] | None = None,
) -> SanitizedExport:
    """Export an IngestedImage using its detected source format."""

    return sanitize_image(
        ingested.image,
        output_dir,
        source_format=ingested.source_format,
        source_sha256=ingested.source_sha256,
        exiftool_path=exiftool_path,
    )


def sanitize_image(
    image: Image.Image,
    output_dir: str | os.PathLike[str],
    *,
    source_format: str,
    source_sha256: str | None = None,
    exiftool_path: str | os.PathLike[str] | None = None,
) -> SanitizedExport:
    """Reconstruct pixels, export without copied metadata, then verify the file."""

    output_format = source_format.upper()
    if output_format not in SUPPORTED_OUTPUT_FORMATS:
        raise ExportError("source format must be JPEG or PNG")
    if image.width <= 0 or image.height <= 0:
        raise ExportError("image has invalid dimensions")

    working = _working_copy(image, output_format)
    encoded = _encode_sanitized_image(working, output_format)
    output_path = _write_unique(output_dir, encoded, output_format)

    try:
        sha256 = _sha256_file(output_path)
        pixel_mean_abs_diff = _verify_pixels(working, output_path, output_format)
        metadata = read_metadata(output_path, exiftool_path=exiftool_path)
        residual_tags = metadata_residual_tags(metadata)
        if residual_tags:
            raise UnsafeExportError(residual_tags)
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        working.close()

    return SanitizedExport(
        output_path=output_path,
        source_format=output_format,
        output_sha256=sha256,
        source_sha256=source_sha256,
        pixel_mean_abs_diff=pixel_mean_abs_diff,
    )


def _working_copy(image: Image.Image, output_format: str) -> Image.Image:
    try:
        image.load()
    except (OSError, ValueError) as exc:
        raise ExportError("image pixels are unavailable") from exc

    if output_format == "PNG" and image.mode == "RGBA":
        source = image.convert("RGBA")
    else:
        source = image.convert("RGB")
    rebuilt = Image.new(source.mode, source.size)
    rebuilt.paste(source)
    rebuilt.info.clear()
    return rebuilt


def _encode_sanitized_image(image: Image.Image, output_format: str) -> bytes:
    buffer = io.BytesIO()
    try:
        if output_format == "JPEG":
            image.save(
                buffer,
                format="JPEG",
                quality=92,
                exif=b"",
                icc_profile=_SRGB_ICC,
            )
        else:
            image.save(
                buffer,
                format="PNG",
                pnginfo=PngImagePlugin.PngInfo(),
                icc_profile=_SRGB_ICC,
            )
    except (OSError, ValueError) as exc:
        raise ExportError("failed to encode sanitized image") from exc
    return buffer.getvalue()


def _write_unique(
    output_dir: str | os.PathLike[str],
    encoded: bytes,
    output_format: str,
) -> Path:
    directory = Path(output_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError("cannot create output directory") from exc
    if not directory.is_dir():
        raise ExportError("output path is not a directory")

    extension = "jpg" if output_format == "JPEG" else "png"
    for _ in range(5):
        destination = directory / f"photocheck-{uuid.uuid4().hex}.{extension}"
        try:
            with destination.open("xb") as handle:
                handle.write(encoded)
            return destination
        except FileExistsError:
            continue
        except OSError as exc:
            raise ExportError("cannot write sanitized image") from exc
    raise ExportError("could not allocate a unique output filename")


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_pixels(
    expected: Image.Image,
    output_path: Path,
    output_format: str,
) -> float:
    try:
        with Image.open(output_path) as decoded:
            decoded.load()
            if decoded.size != expected.size:
                raise ExportError("sanitized image dimensions changed")
            actual = decoded.convert(expected.mode)
            difference = ImageChops.difference(expected, actual)
            mean = sum(ImageStat.Stat(difference).mean) / len(difference.getbands())
            if output_format == "PNG" and mean != 0:
                raise ExportError("lossless PNG export changed pixel values")
            return float(mean)
    except ExportError:
        raise
    except (OSError, ValueError) as exc:
        raise ExportError("sanitized image could not be reopened") from exc


"""Temporary stand-in for B's K-01 (image loading and metadata parsing).

DELETE THIS FILE once B's `core/io/loader.py` lands. It only does the two things
A actually needs:
1. `ImageOps.exif_transpose` - fix orientation first, then fix the coordinate
   system. Without this every bbox on a portrait photo is silently rotated.
2. Emit an `ImageDescriptor` matching the contract (oriented width/height plus
   top_left_pixels).

It does not parse EXIF fields (that is B's job) and does not read thumbnails.
"""

from __future__ import annotations

from pathlib import Path

from ..contract import ImageDescriptor

__all__ = ["load_working_image", "describe"]


def _open_image(path: Path):
    from PIL import Image, ImageOps

    try:  # HEIC support is optional; skip it when the plugin is not installed
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:
        pass

    with Image.open(path) as raw:
        oriented = ImageOps.exif_transpose(raw)
        return oriented.convert("RGB")


def load_working_image(path: str | Path, image_id: str | None = None):
    """Return (PIL.Image, ImageDescriptor). Orientation already fixed via EXIF."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"image not found: {p}")
    image = _open_image(p)
    descriptor = describe(image, image_id or p.stem)
    return image, descriptor


def describe(image, image_id: str) -> ImageDescriptor:
    width, height = image.size
    return ImageDescriptor(image_id=image_id, width=int(width), height=int(height))

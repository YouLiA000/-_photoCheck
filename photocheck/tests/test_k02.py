from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image, PngImagePlugin

from photocheck.core import (
    ExportError,
    ingest_image,
    metadata_residual_tags,
    read_metadata,
    sanitize_ingested,
    sanitize_image,
)
from photocheck.core.export import _SRGB_ICC
from photocheck.tests.test_k01 import make_exif_jpeg


def png_chunk_types(path: Path) -> list[str]:
    payload = path.read_bytes()
    offset = 8
    chunk_types: list[str] = []
    while offset < len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        chunk_type = payload[offset + 4 : offset + 8].decode("ascii")
        chunk_types.append(chunk_type)
        offset += 12 + length
    return chunk_types


class SanitizeTests(unittest.TestCase):
    def test_jpeg_export_removes_metadata_without_modifying_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "原始照片.jpg"
            make_exif_jpeg(source, orientation=6)
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

            with ingest_image(source) as ingested:
                result = sanitize_ingested(ingested, directory / "output")
                self.assertNotEqual(result.output_path, source)
                self.assertTrue(result.output_path.name.startswith("photocheck-"))
                self.assertNotIn("原始照片", result.output_path.name)
                self.assertEqual(result.source_sha256, source_hash)
                self.assertLess(result.pixel_mean_abs_diff, 12)

            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)
            metadata = read_metadata(result.output_path)
            self.assertEqual(metadata_residual_tags(metadata), ())
            self.assertFalse(
                any(
                    key.startswith(("ExifIFD:", "GPS:", "IFD0:", "IFD1:", "XMP:", "IPTC:"))
                    for key in metadata
                )
            )
            with Image.open(result.output_path) as output:
                self.assertEqual(output.size, (40, 80))
                self.assertEqual(output.format, "JPEG")
                self.assertEqual(output.info.get("icc_profile"), _SRGB_ICC)

    def test_png_text_chunks_are_removed_and_pixels_are_lossless(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "截图.png"
            png_info = PngImagePlugin.PngInfo()
            png_info.add_text("Author", "Sensitive Author")
            png_info.add_text("Comment", "Sensitive Comment")
            original = Image.new("RGBA", (19, 13), (10, 20, 30, 128))
            original.save(source, format="PNG", pnginfo=png_info)

            source_chunks = png_chunk_types(source)
            self.assertIn("tEXt", source_chunks)
            with ingest_image(source) as ingested:
                expected_pixels = ingested.image.tobytes()
                result = sanitize_ingested(ingested, directory / "output")
                self.assertEqual(result.pixel_mean_abs_diff, 0)

            self.assertFalse(
                {"tEXt", "zTXt", "iTXt", "eXIf"} & set(png_chunk_types(result.output_path))
            )
            with Image.open(result.output_path) as output:
                output.load()
                self.assertEqual(output.size, (19, 13))
                self.assertEqual(output.mode, "RGBA")
                self.assertEqual(output.tobytes(), expected_pixels)
                self.assertEqual(output.info.get("icc_profile"), _SRGB_ICC)

    def test_each_export_gets_a_unique_safe_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            image = Image.new("RGB", (8, 6), (90, 100, 110))
            first = sanitize_image(image, directory, source_format="PNG")
            second = sanitize_image(image, directory, source_format="PNG")
            self.assertNotEqual(first.output_path, second.output_path)
            self.assertTrue(first.output_path.is_file())
            self.assertTrue(second.output_path.is_file())

    def test_unsupported_source_format_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image = Image.new("RGB", (2, 2))
            with self.assertRaises(ExportError):
                sanitize_image(image, temp_dir, source_format="GIF")


if __name__ == "__main__":
    unittest.main()

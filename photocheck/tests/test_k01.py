from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import piexif
from PIL import Image

from photocheck.core import ImageIngestError, SecretStore, ingest_image


def make_exif_jpeg(path: Path, *, orientation: int = 1) -> bytes:
    source = Image.new("RGB", (80, 40), (220, 120, 40))
    thumbnail_buffer = io.BytesIO()
    source.save(thumbnail_buffer, format="JPEG", quality=85)
    exif = {
        "0th": {
            piexif.ImageIFD.Make: b"PhotoCheckTest",
            piexif.ImageIFD.Model: b"CampusCam",
            piexif.ImageIFD.Software: b"PhotoCheckFixture",
            piexif.ImageIFD.Orientation: orientation,
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: b"2026:01:02 03:04:05",
            piexif.ExifIFD.BodySerialNumber: b"TEST-SERIAL-001",
        },
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLatitude: ((31, 1), (12, 1), (3400, 100)),
            piexif.GPSIFD.GPSLongitudeRef: b"E",
            piexif.GPSIFD.GPSLongitude: ((121, 1), (30, 1), (4500, 100)),
        },
        "1st": {},
        "thumbnail": thumbnail_buffer.getvalue(),
    }
    source.save(path, format="JPEG", exif=piexif.dump(exif), quality=95)
    return path.read_bytes()


class IngestTests(unittest.TestCase):
    def test_jpeg_is_normalized_and_sensitive_metadata_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "测试照片.jpg"
            original = make_exif_jpeg(path, orientation=6)
            original_hash = hashlib.sha256(original).hexdigest()

            with ingest_image(path) as result:
                self.assertEqual(result.descriptor["width"], 40)
                self.assertEqual(result.descriptor["height"], 80)
                self.assertEqual(result.image.size, (40, 80))
                self.assertEqual(result.source_sha256, original_hash)
                self.assertEqual(path.read_bytes(), original)

                subtypes = {item["subtype"] for item in result.detections}
                self.assertTrue(
                    {"gps", "datetime", "device", "serial", "software", "thumbnail"}
                    <= subtypes
                )
                self.assertTrue(all(item["bbox"] is None for item in result.detections))

                serialized = json.dumps(
                    {
                        "descriptor": result.descriptor,
                        "detections": result.detections,
                    }
                )
                self.assertNotIn("TEST-SERIAL-001", serialized)
                self.assertNotIn("31.2", serialized)
                self.assertIn("TEST-SERIAL-001", str(result.get_raw_metadata()))
                self.assertNotIn("SourceFile", result.get_raw_metadata())
                self.assertFalse(
                    any(
                        key.startswith(("System:", "File:", "ExifTool:"))
                        for key in result.get_raw_metadata()
                    )
                )

            with self.assertRaises(KeyError):
                result.get_raw_metadata()

    def test_png_without_exif_returns_no_metadata_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "clean.png"
            Image.new("RGBA", (24, 16), (1, 2, 3, 128)).save(path, format="PNG")
            with ingest_image(path) as result:
                self.assertEqual(result.detections, ())
                self.assertEqual(result.image.mode, "RGBA")
                self.assertEqual(
                    (result.descriptor["width"], result.descriptor["height"]),
                    (24, 16),
                )

    def test_invalid_and_unsupported_inputs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            invalid = directory / "not-image.png"
            invalid.write_bytes(b"not an image")
            with self.assertRaises(ImageIngestError):
                ingest_image(invalid)

            gif = directory / "unsupported.gif"
            Image.new("RGB", (2, 2)).save(gif, format="GIF")
            with self.assertRaises(ImageIngestError):
                ingest_image(gif)

    def test_size_and_pixel_limits_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "large.png"
            Image.new("RGB", (20, 20)).save(path, format="PNG")
            with self.assertRaises(ImageIngestError):
                ingest_image(path, max_file_bytes=10)
            with self.assertRaises(ImageIngestError):
                ingest_image(path, max_pixels=100)

    def test_missing_exiftool_is_reported_without_leaking_path_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "image.png"
            Image.new("RGB", (4, 4)).save(path, format="PNG")
            with self.assertRaises(ImageIngestError):
                ingest_image(path, exiftool_path=Path(temp_dir) / "missing.exe")

    def test_secret_store_uses_opaque_discardable_tokens(self) -> None:
        store = SecretStore()
        token = store.put({"value": "sensitive"})
        self.assertTrue(token.startswith("secret:"))
        self.assertEqual(store.get(token), {"value": "sensitive"})
        self.assertTrue(store.discard(token))
        self.assertFalse(store.discard(token))
        with self.assertRaises(KeyError):
            store.get(token)
        none_token = store.put(None)
        self.assertTrue(store.discard(none_token))


if __name__ == "__main__":
    unittest.main()


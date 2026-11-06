from __future__ import annotations

import hashlib
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, PngImagePlugin

from photocheck.contract import build_redaction_plan
from photocheck.core import (
    apply_redactions,
    ingest_image,
    metadata_residual_tags,
    process_and_export,
    read_metadata,
)
from photocheck.tests.test_k01 import make_exif_jpeg


def manual_plan(
    image: Image.Image,
    image_id: str,
    *,
    bbox: list[int],
    method: str = "solid",
    revision: int = 1,
) -> dict:
    return build_redaction_plan(
        {
            "contract_version": "photocheck/v4",
            "record_type": "ImageDescriptor",
            "image_id": image_id,
            "width": image.width,
            "height": image.height,
            "orientation": "exif_transposed",
            "coordinate_space": "top_left_pixels",
        },
        [],
        [],
        revision=revision,
        manual_regions=[
            {
                "id": f"manual-{method}-{bbox[0]}",
                "bbox": bbox,
                "method": method,
            }
        ],
    )


def patterned_image(size: tuple[int, int] = (200, 120)) -> Image.Image:
    image = Image.new("RGBA", size, (230, 230, 230, 255))
    draw = ImageDraw.Draw(image)
    for x in range(0, size[0], 8):
        draw.line((x, 0, x, size[1]), fill=(30, 90, 160, 255), width=2)
    draw.rectangle((70, 35, 130, 80), fill=(250, 40, 40, 255))
    return image


class RedactionTests(unittest.TestCase):
    def test_solid_mask_uses_padding_and_does_not_change_outside(self) -> None:
        source = patterned_image()
        plan = manual_plan(source, "image-test", bbox=[70, 35, 60, 45])
        outside_before = source.getpixel((2, 2))

        with apply_redactions(source, plan, image_id="image-test") as result:
            region = result.applied_regions[0]
            self.assertEqual(region.method, "solid")
            self.assertEqual(region.applied_bbox, (64, 29, 72, 57))
            self.assertEqual(result.image.getpixel((65, 30)), (0, 0, 0, 255))
            self.assertEqual(result.image.getpixel((2, 2)), outside_before)
            self.assertEqual(source.getpixel((80, 50)), (250, 40, 40, 255))

    def test_blur_and_mosaic_change_only_the_expanded_region(self) -> None:
        for method in ("blur", "mosaic"):
            with self.subTest(method=method):
                source = patterned_image()
                plan = manual_plan(source, "image-test", bbox=[40, 20, 80, 60], method=method)
                with apply_redactions(source, plan, image_id="image-test") as result:
                    region = result.applied_regions[0]
                    self.assertEqual(region.method, method)
                    self.assertNotEqual(
                        result.image.crop((40, 20, 120, 80)).tobytes(),
                        source.crop((40, 20, 120, 80)).tobytes(),
                    )
                    self.assertEqual(result.image.getpixel((0, 0)), source.getpixel((0, 0)))
                    self.assertEqual(result.image.getpixel((199, 119)), source.getpixel((199, 119)))

    def test_edge_mask_is_clamped_to_the_image(self) -> None:
        source = patterned_image((30, 20))
        plan = manual_plan(source, "image-test", bbox=[0, 0, 6, 4])
        with apply_redactions(source, plan, image_id="image-test") as result:
            region = result.applied_regions[0]
            self.assertEqual(region.applied_bbox[0], 0)
            self.assertEqual(region.applied_bbox[1], 0)
            self.assertLessEqual(region.applied_bbox[0] + region.applied_bbox[2], 30)
            self.assertLessEqual(region.applied_bbox[1] + region.applied_bbox[3], 20)

    def test_qr_finding_forces_solid_mask(self) -> None:
        source = patterned_image()
        descriptor = {
            "contract_version": "photocheck/v4",
            "record_type": "ImageDescriptor",
            "image_id": "image-qr",
            "width": source.width,
            "height": source.height,
            "orientation": "exif_transposed",
            "coordinate_space": "top_left_pixels",
        }
        qr = {
            "contract_version": "photocheck/v4",
            "record_type": "Detection",
            "id": "det-qr",
            "image_id": "image-qr",
            "kind": "qr",
            "subtype": "qr_unknown",
            "bbox": [50, 30, 80, 80],
            "detector_score": 0.9,
            "evidence": "qr_payload",
            "risk": 3,
            "details": {"decodable": False},
        }
        decision = {
            "contract_version": "photocheck/v4",
            "record_type": "Decision",
            "finding_id": "det-qr",
            "action": "redact",
            "revision": 1,
        }
        plan = build_redaction_plan(
            descriptor,
            [qr],
            [decision],
            revision=1,
            method_by_finding={"det-qr": "blur"},
        )
        with apply_redactions(
            source,
            plan,
            image_id="image-qr",
            detections=[qr],
        ) as result:
            self.assertEqual(result.applied_regions[0].method, "solid")

    def test_empty_plan_preserves_pixels(self) -> None:
        source = patterned_image((50, 40))
        plan = build_redaction_plan(
            {
                "contract_version": "photocheck/v4",
                "record_type": "ImageDescriptor",
                "image_id": "image-empty",
                "width": 50,
                "height": 40,
                "orientation": "exif_transposed",
                "coordinate_space": "top_left_pixels",
            },
            [],
            [],
            revision=1,
        )
        with apply_redactions(source, plan, image_id="image-empty") as result:
            self.assertEqual(result.image.tobytes(), source.tobytes())
            self.assertEqual(result.applied_regions, ())


class PipelineTests(unittest.TestCase):
    def test_manual_solid_box_completes_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "截图.png"
            png_info = PngImagePlugin.PngInfo()
            png_info.add_text("Author", "Sensitive Author")
            patterned_image().save(source, format="PNG", pnginfo=png_info)
            source_hash = hashlib.sha256(source.read_bytes()).hexdigest()

            with ingest_image(source) as ingested:
                plan = manual_plan(ingested.image, ingested.descriptor["image_id"], bbox=[70, 35, 60, 45])
                result = process_and_export(
                    ingested,
                    plan,
                    output_dir=directory / "output",
                )
                self.assertEqual(result.verification["disposal_state"], "passed")
                self.assertEqual(
                    result.verification["checks"][0]["method"],
                    "solid_black_region",
                )
                self.assertEqual(result.export.pixel_mean_abs_diff, 0)

            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), source_hash)
            output_metadata = read_metadata(result.export.output_path)
            self.assertEqual(metadata_residual_tags(output_metadata), ())
            with Image.open(result.export.output_path) as output:
                self.assertEqual(output.getpixel((68, 33)), (0, 0, 0, 255))

    def test_blur_without_semantic_verifier_remains_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "source.png"
            patterned_image().save(source, format="PNG")
            with ingest_image(source) as ingested:
                plan = manual_plan(
                    ingested.image,
                    ingested.descriptor["image_id"],
                    bbox=[70, 35, 60, 45],
                    method="blur",
                )
                result = process_and_export(
                    ingested,
                    plan,
                    output_dir=directory / "output",
                )
            self.assertEqual(result.verification["disposal_state"], "pending")
            self.assertEqual(
                result.verification["checks"][0]["status"],
                "not_applicable",
            )

    def test_text_detection_unavailable_remains_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "source.png"
            patterned_image().save(source, format="PNG")
            with ingest_image(source) as ingested:
                detection = {
                    "contract_version": "photocheck/v4",
                    "record_type": "Detection",
                    "id": "det-phone",
                    "image_id": ingested.descriptor["image_id"],
                    "kind": "text",
                    "subtype": "phone",
                    "bbox": [70, 35, 60, 45],
                    "detector_score": 0.95,
                    "evidence": "ocr_rule",
                    "risk": 2,
                    "details": {"masked_preview": "138****0000"},
                }
                decision = {
                    "contract_version": "photocheck/v4",
                    "record_type": "Decision",
                    "finding_id": "det-phone",
                    "action": "redact",
                    "revision": 1,
                }
                plan = build_redaction_plan(
                    ingested.descriptor,
                    [detection],
                    [decision],
                    revision=1,
                )
                result = process_and_export(
                    ingested,
                    plan,
                    output_dir=directory / "output",
                    detections=[detection],
                    decisions=[decision],
                    content_probe=lambda *args, **kwargs: {
                        "unavailable": ["text"],
                    },
                )
            self.assertEqual(result.verification["disposal_state"], "pending")
            self.assertEqual(
                result.verification["checks"][0]["method"],
                "a_text_unavailable",
            )

    def test_manual_solid_box_passes_on_jpeg_export(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            source = directory / "source.jpg"
            make_exif_jpeg(source, orientation=6)
            with ingest_image(source) as ingested:
                plan = manual_plan(
                    ingested.image,
                    ingested.descriptor["image_id"],
                    bbox=[10, 20, 15, 15],
                )
                result = process_and_export(
                    ingested,
                    plan,
                    output_dir=directory / "output",
                )
            self.assertEqual(result.verification["disposal_state"], "passed")
            self.assertEqual(metadata_residual_tags(read_metadata(result.export.output_path)), ())

    def test_single_region_on_4k_image_is_fast(self) -> None:
        source = Image.new("RGB", (3840, 2160), (200, 200, 200))
        plan = manual_plan(source, "image-4k", bbox=[1000, 800, 300, 180])
        start = time.perf_counter()
        with apply_redactions(source, plan, image_id="image-4k"):
            elapsed = time.perf_counter() - start
        self.assertLess(elapsed, 1.0)


if __name__ == "__main__":
    unittest.main()

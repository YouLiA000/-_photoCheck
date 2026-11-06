# PhotoCheck prototype

## Environment

- Python: `C:\Python311\Python311\python.exe`
- Virtual environment: `D:\Program Files\PhotoCheck\venv`
- ExifTool 13.61: `D:\Program Files\PhotoCheck\ExifTool-13.61\exiftool.exe`

ExifTool is mandatory. If it is missing, `ingest_image()` and sanitized export
fail closed with an actionable error rather than silently skipping metadata
verification. Check the full runtime with:

```powershell
& 'D:\Program Files\PhotoCheck\venv\Scripts\python.exe' `
  photocheck\scripts\check_environment.py
```

Install Python dependencies:

```powershell
& 'D:\Program Files\PhotoCheck\venv\Scripts\python.exe' -m pip install -r photocheck\requirements.txt
```

## K-01

`ingest_image()` validates a local JPEG/PNG, applies EXIF orientation once,
returns a canonical image plus `ImageDescriptor` and metadata `Detection`
records. Raw ExifTool output is stored only in a process-memory `SecretStore`
and is discarded when the `IngestedImage` context closes.

## K-02

`sanitize_ingested()` rebuilds the canonical pixels on a new canvas and exports
a new file without overwriting the source. The output:

- uses a random `photocheck-<id>` filename that does not contain the source name;
- contains no source EXIF, XMP, IPTC, PNG text or embedded thumbnail;
- embeds only a newly generated standard sRGB ICC profile;
- uses JPEG quality 92 when the source is JPEG, and lossless RGBA/RGB PNG for PNG;
- is reopened and checked with ExifTool before being returned.

If post-export verification finds residual content metadata, the output file is
deleted and `UnsafeExportError` is raised.

## K-08 before detector integration

`apply_redactions()` applies v4 region plans to a pixel-only copy:

- expands each box by 4px plus 3% of its short side and clamps it to the image;
- defaults to an opaque solid mask;
- applies blur and mosaic only when explicitly requested;
- applies solid masks last so overlapping QR or solid regions cannot be weakened;
- forces QR findings to solid even if their plan requested another method.

## K-09a-d content verification

`process_and_export()` runs the currently available pipeline:

```text
validate v4 records
→ apply RedactionPlan
→ remove all source metadata through K-02
→ reopen final file
→ check dimensions and metadata
→ call A probe_region() for text / QR / face regions
→ check solid regions are uniform
→ build VerificationReport
```

Content-specific rules:

- OCR unavailable → `pending`; residual text → `failed`; clean OCR → `passed`.
- QR unavailable → `pending`; any detected QR → `failed`, even if undecodable;
  only `detected=0` and `decodable=0` can pass.
- Face unavailable → `pending`; residual face region → `failed`.
- Manual blur/mosaic regions without a content type remain `pending`.

Same-detector passes do not prove human unreadability.

Example:

```python
from photocheck.contract import build_redaction_plan
from photocheck.core import ingest_image, process_and_export

with ingest_image(r"D:\images\source.jpg") as ingested:
    plan = build_redaction_plan(
        ingested.descriptor,
        [],
        [],
        revision=1,
        manual_regions=[{
            "id": "manual-1",
            "bbox": [120, 80, 300, 120],
            "method": "solid",
        }],
    )
    result = process_and_export(
        ingested,
        plan,
        output_dir=r"D:\images\photocheck-output",
    )
    print(result.export.output_path)
    print(result.verification["disposal_state"])
```

## Detector-side A integration

`photocheck.detectors` validates A runtime envelopes with both A's strict
contract models and the project's JSON Schema before they enter B's pipeline.
`warnings` and `timings_ms` remain runtime status and are not inserted into v4
records.

The complete 2026-11-06 A v2 detector engine is vendored under
`photocheck/detectors/a_engine/`. `analyze_a()` runs A's `analyze()` and applies
both A-side and B-side contract validation before returning an `AEnvelope`.
`probe_a_region()` exposes QR `detected`/`decodable` evidence separately for
K-09c integration.

Audit a new A archive before integration:

```powershell
& 'D:\Program Files\PhotoCheck\venv\Scripts\python.exe' `
  photocheck\scripts\check_a_delivery.py `
  D:\path\to\A-delivery
```

Run the integrated A engine smoke test:

```powershell
& 'D:\Program Files\PhotoCheck\venv\Scripts\python.exe' `
  photocheck\scripts\smoke_a_engine.py `
  photocheck\detectors\a_engine\express_001.png
```

Run the tests from the project root:

```powershell
& 'D:\Program Files\PhotoCheck\venv\Scripts\python.exe' -m unittest discover -s photocheck\tests -v
& 'D:\Program Files\PhotoCheck\venv\Scripts\python.exe' -m unittest discover -s photocheck\contract\tests -v
```

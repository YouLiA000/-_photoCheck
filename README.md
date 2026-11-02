# PhotoCheck

PhotoCheck is a local photo-privacy inspection prototype for Chinese campus
scenarios. It currently implements the B-side processing infrastructure:

- canonical JPEG/PNG ingestion with EXIF orientation normalization;
- sensitive metadata detection through ExifTool;
- metadata-free pixel reconstruction and safe exports;
- solid, blur and mosaic region redaction;
- structural verification and v4 verification reports;
- strict PhotoCheck v4 data-contract validation;
- validation of detector-side A runtime envelopes.

## Current status

The 2026-11-02 detector-side A delivery contained its contract models and one
runtime sample, but not the OCR, QR or face detector implementation. The project
validates A's output format, but it does **not** yet claim working OCR, QR
decoding or face detection.

See [the integration record](docs/A交付整合与下一步_2026-11-02.md) for the exact
inventory, verification evidence and required follow-up delivery.

## Environment

- Python 3.11
- Pillow 10.4.0
- piexif 1.1.3
- jsonschema 4.26.0
- OpenCV 4.10.0.84
- NumPy 1.26.4
- External ExifTool 13.60

Install Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

ExifTool is an external program. Set `PHOTOCHECK_EXIFTOOL` to its executable, or
install it at the default Windows path used by this project:

```text
D:\Program Files\PhotoCheck\ExifTool\exiftool.exe
```

## Tests

Run from the repository root:

```powershell
python -m unittest discover -s photocheck/tests -v
python -m unittest discover -s photocheck/contract/tests -v
```

Audit a newly delivered A package:

```powershell
python photocheck/scripts/check_a_delivery.py <A-delivery-directory>
```

## Documentation

- [Functional specification v1.4](docs/功能规格卡_v1.4.md)
- [System flow v3](docs/PhotoCheck系统流程图_v3.html)
- [A integration status and next steps](docs/A交付整合与下一步_2026-11-02.md)
- [Package usage details](photocheck/README.md)

## Privacy boundary

PhotoCheck removes all source metadata before export and embeds only a newly
generated standard sRGB ICC profile. It does not claim that an exported image is
absolutely safe or that a same-detector recheck proves human unreadability.


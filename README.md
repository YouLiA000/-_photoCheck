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

The complete 2026-11-06 A v2 engine is now vendored under
`photocheck/detectors/a_engine/` and exposed through the validated adapter.

See [the integration record](docs/A交付整合与下一步_2026-11-02.md) for the
historical delivery audit and [the forward plan](docs/后续推进计划_2026-11-06.md)
for current work.

## Environment

- Python 3.11
- Pillow 10.4.0
- piexif 1.1.3
- jsonschema 4.26.0
- OpenCV 4.10.0.84
- NumPy 1.26.4
- External ExifTool 13.60

ExifTool is a required external prerequisite for both metadata detection and
export verification. Run the preflight before using PhotoCheck:

```powershell
python photocheck/scripts/check_environment.py
```

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

Run the integrated A smoke test:

```powershell
python photocheck/scripts/smoke_a_engine.py photocheck/detectors/a_engine/express_001.png
```

Build a clean release archive. The script excludes `.git`, caches and local
outputs, and fails unless `docs/功能规格卡_v1.4.md` is present:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_release.ps1
```

## Documentation

- [Functional specification v1.4](docs/功能规格卡_v1.4.md)
- [System flow v3](docs/PhotoCheck系统流程图_v3.html)
- [A integration status and next steps](docs/A交付整合与下一步_2026-11-02.md)
- [Forward implementation plan 2026-11-06](docs/后续推进计划_2026-11-06.md)
- [K-14 offline verification record](docs/K14离线验证记录_2026-11-06.md)
- [K-14 acceptance-machine evidence steps](docs/K14验收机器断网取证清单_2026-11-06.md)
- [A synchronization checklist](docs/A同步修复清单_2026-11-06.md)
- [C integration checklist](docs/C最小界面对接清单_2026-11-06.md)
- [B integration package for A](docs/发给A_B集成测试包清单_2026-11-06.md)
- [Package usage details](photocheck/README.md)

## Privacy boundary

PhotoCheck removes all source metadata before export and embeds only a newly
generated standard sRGB ICC profile. It does not claim that an exported image is
absolutely safe or that a same-detector recheck proves human unreadability.


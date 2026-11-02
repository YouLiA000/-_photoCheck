# Detector integration status

The 2026-11-02 A delivery contains:

- its strict v4 contract models;
- one contract-alignment test suite;
- one runtime envelope example.

Those artifacts are vendored as `a_contract.py` and connected through
`a_adapter.py`, which requires both A-side and B-side validation before records
enter the processing pipeline. Runtime `warnings` and `timings_ms` stay outside
the v4 records.

The delivered folder does **not** contain the `core/detect` OCR, entity, QR or
face implementation, scripts, model assets, or the README's claimed 75 tests.
Consequently the project cannot yet call A's `analyze()` or `probe_region()`.
The integration deliberately exposes no fake detector fallback.

Audit a future delivery before copying it into the project:

```powershell
& 'D:\Program Files\PhotoCheck\venv\Scripts\python.exe' `
  photocheck\scripts\check_a_delivery.py `
  <A-delivery-directory>
```

The command exits with code 0 only when the contract sample is valid, all
required engine source files exist, `analyze`/`probe_region`/`classify` are
defined, and an `express_001` image is present.

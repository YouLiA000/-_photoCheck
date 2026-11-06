# Detector integration status

The complete 2026-11-06 A v2 engine is vendored under `a_engine/`.

- `a_engine/core/contract.py` is the authoritative A contract.
- `a_contract.py` is a compatibility re-export, not a second contract.
- `a_adapter.py` validates runtime envelopes with both A and B schema rules.
- `analyze_a()` runs OCR/entity/QR/face detection and returns an `AEnvelope`.
- `probe_a_region()` exposes `residual_text`, `residual_qr_detected`,
  `residual_qr_decodable`, `residual_face`, and `unavailable`.
- Runtime `warnings` and `timings_ms` stay outside v4 records.

The vendored A tests are under `a_engine/tests/`. Run them from the repository
root:

```powershell
python -m pytest photocheck/detectors/a_engine/tests -q
```

Integrated smoke test:

```powershell
python photocheck/scripts/smoke_a_engine.py `
  photocheck/detectors/a_engine/express_001.png
```

Audit a future delivery before copying it into the project:

```powershell
& 'D:\Program Files\PhotoCheck\venv\Scripts\python.exe' `
  photocheck\scripts\check_a_delivery.py `
  <A-delivery-directory>
```

The command exits with code 0 only when the contract sample is valid, all
required engine source files exist, `analyze`/`probe_region`/`classify` are
defined, and an `express_001` image is present.

# PhotoCheck data contract v4

This directory owns the machine-readable contract for detection, user decisions,
redaction plans and final-file verification.

## Records

- `ImageDescriptor` establishes the canonical, EXIF-transposed pixel coordinate space.
- `Detection` is immutable detector output. It never contains raw text, QR payloads or EXIF values.
- `Decision` has exactly two actions: `redact` and `retain`.
- `RedactionPlan` contains opaque-mask regions by default. Manual boxes are items with a null `finding_id`.
- `VerificationReport` is tied to one plan revision and uses four disposal states.

Metadata findings do not receive decisions. PhotoCheck always removes all source
metadata and keeps only the explicitly approved color profile at export.

## Validation

```powershell
python -m pip install -r photocheck/contract/requirements-contract.txt
python -m unittest discover -s photocheck/contract/tests -v
```

`validate_records()` checks the JSON Schema plus cross-record rules that JSON
Schema cannot express, including unique IDs, image bounds, one decision per
finding, plan references and stale verification revisions.

## v3 migration

`convert_v3_finding()` accepts only unambiguous v3 decisions:

- `selected=true` and `action=hide` become `redact`.
- `selected=false` and `action=keep|skip` become `retain`.
- Any other combination is rejected instead of guessed.

The adapter rejects any legacy `text_ref`, `payload_ref`, raw EXIF or other
plaintext-sensitive field. Historical verification status is not trusted and
must be recomputed for the v4 redaction plan.


---
id: BC-0009
title: cv2 fallback reports a dense-text quadrilateral as an undecodable QR code
found_at: 2026-11-06
layer: detection
reason: threshold
symptom: false_positive
kind: qr
subtype: qr_unknown
card: K-05
severity: P1
status: fixed
spec_ref: 功能规格卡 v1.4 §K-05「解不出也必须标框」
fix_test: test_cv2_fallback_rejects_dense_text_quadrilateral
---

## 复现

On B's final export of `express_001.png`, a full QR recheck returned:

```text
qr_unknown bbox=[152,194,322,290] decodable=False
```

The crop contains a name, a university dormitory address and an order-like
number. It contains no QR code. The candidate aspect ratio is about 1.11, so a
simple square/aspect-ratio filter is not enough.

## 根因

`cv2.QRCodeDetector` can return a quadrilateral for dense text. The previous
fallback reported every undecoded quadrilateral as `qr_unknown` without
checking for QR finder-pattern evidence.

## 修复

An undecoded cv2 candidate is retained only when at least three nested square
finder-pattern structures are found inside its bounding box. A normal
undecodable QR code still has three corner finders and remains reportable.

## 回归

- `test_cv2_fallback_rejects_dense_text_quadrilateral`
- `test_finder_pattern_evidence_distinguishes_qr_from_text`
- `test_visible_code_is_found_through_probe_region`

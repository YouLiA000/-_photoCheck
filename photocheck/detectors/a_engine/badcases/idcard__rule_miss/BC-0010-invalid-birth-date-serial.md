---
id: BC-0010
title: checksum-valid 18-digit serial with an impossible birth date was reported as an ID card
found_at: 2026-11-06
layer: detection
reason: rule_miss
symptom: false_positive
kind: text
subtype: idcard
card: K-04
severity: P1
status: fixed
spec_ref: 功能规格卡 v1.4 §K-04「身份证号 18 位 + 校验位」
fix_test: test_invalid_birth_date_with_valid_checksum_is_not_an_idcard
---

## 复现

An 18-digit order/serial number can be constructed so the ISO 7064 checksum
passes while positions 7-14 are not a valid date, for example month 13.

## 修复

- A passing checksum plus an impossible birth date is treated as a serial
  number and is not reported as an identity card.
- A failing checksum is still reported as `idcard_check=fail` and risk 2,
  because a mistyped ID still leaks the same kind of information.
- The matched span remains reserved so the phone rule cannot carve a false
  number out of the same digit string.

## 回归

- `test_invalid_birth_date_with_valid_checksum_is_not_an_idcard`
- `test_invalid_birth_date_with_bad_checksum_is_still_reported`

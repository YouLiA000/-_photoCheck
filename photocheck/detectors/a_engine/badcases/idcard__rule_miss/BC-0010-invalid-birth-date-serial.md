---
id: BC-0010
title: 校验位通过但生日段非法的 18 位流水号被报成身份证
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

## 现象

C 的 dev 集里 `image-dev-031` 第 3 个框是一串 18 位数字，生日段是
**2026 年 13 月 32 日**。C 的真值把它登记为负例（`verdict=negative`），
`negatives.json` 的备注写的是「18 位但生日段非法（13 月 32 日），是流水号不是证号」。

我们的输出把它判成了 `idcard`，`idcard_check=pass`、risk 3。

## 复现

```bash
C:/venvs/photocheck/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from core.detect.entities import idcard_check, scan_text, ISO7064_WEIGHTS, ISO7064_CODES
body='11010119901332001'
n=body+ISO7064_CODES[sum(int(c)*w for c,w in zip(body,ISO7064_WEIGHTS))%11]
print('checksum:', idcard_check(n))
print('detections:', [d.subtype for d in scan_text(n)])
"
```

修复前：`checksum: pass`、`detections: ['idcard']`。
修复后：同样 `checksum: pass`，但 `detections: []`。

## 根因

原规则只有"18 位 + MOD 11-2 校验位"。校验位是**可以被构造出来的**：
只要按算法反推末位，任意 17 位都能凑出一个 `pass`。所以"校验位通过"只能证明
这串数字**至少不是随手敲的**，不能证明它是身份证。

缺的是第 7–14 位的出生日期段合法性。`2026-13-32` 不是日期。

## 处置

加 `idcard_birth_date_valid()`，用 `datetime.strptime(s[6:14], '%Y%m%d')` 判日历合法性
（月份 13、32 日、平年 2 月 29 都会抛 `ValueError`），再加年份区间 1800–2100。

三态行为保持不变，但改在出生日期之后决定：

| 情况 | 产出 |
|---|---|
| 校验位通过 + 日期合法 | `idcard`，`idcard_check=pass`，risk 3 |
| 校验位通过 + **日期非法** | **不报**（这是流水号） |
| 校验位失败 | `idcard`，`idcard_check=fail`，risk 2 |

两条容易写反的地方：

1. **校验位失败不能丢**。打错一位的身份证泄露的信息和真号一样多，丢了就是漏遮盖。
   只有"校验位也通过、日期却不存在"这个组合才说明是构造出来的流水号。
2. **被丢弃的候选仍要占住字符区间**。否则手机号规则会从这 18 位里切出一个
   11 位"号码"，误报只是换了个 subtype 继续存在。实现上 `taken.append()` 提前到
   `continue` 之前。

有意**不做**的检查：日期是否在未来。真证不可能，但 OCR 把某一位日期看错时会被推到
未来，而那一天丢掉的是一条真号——漏遮盖比多一条误报严重得多。日历合法性是
"看错一位也到不了"的那部分，才适合当丢弃依据。

## 回归

- `test_invalid_birth_date_with_valid_checksum_is_not_an_idcard`
- `test_invalid_birth_date_with_bad_checksum_is_still_reported`
- `test_birth_date_valid_rejects_impossible_dates`（13 月 32 日 / 平年 2·29 / 0 月 0 日 / 66 月）
- `test_birth_date_valid_accepts_real_dates`（含闰年 2000-02-29）
- `test_rejected_serial_still_blocks_the_phone_rule`
- `test_idcard_tampered_still_reported_but_risk2`（原有断言，不能被这次改动带翻）

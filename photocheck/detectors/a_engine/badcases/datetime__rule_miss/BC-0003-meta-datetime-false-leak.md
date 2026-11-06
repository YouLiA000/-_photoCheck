---
id: BC-0003
title: 长数字串规则删掉分隔符后判定，EXIF 日期 2024-06-01 被当成未掩码
found_at: 2026-11-02
layer: contract
reason: rule_miss
symptom: false_positive
kind: meta
subtype: datetime
card: K-02
severity: P1
status: fixed
spec_ref: 功能规格卡 v1.4 §0.2「meta：无必填项；允许安全 masked_preview」
fix_test: test_meta_preview_is_not_mistaken_for_plaintext
---

## 现象

```python
Detection(kind="meta", subtype="datetime", bbox=None,
          details={"masked_preview": "2024-06-01"})
# ContractError: masked_preview 归一化后仍含长数字串，疑似未掩码：'2024-06-01'
```

`2024-06-01 12:30`、`39.90,116.40`（GPS）同样被拒。也就是说
**EXIF 里几乎所有有用的 meta 都构造不出记录**。

同一规则还误伤了 `serial` 的正常掩码形态：`SN-2024-000123456` 被判未掩码
（这条其实是真泄漏，应当拒——所以规则本身不对，而不是阈值太严）。

## 复现

```bash
C:/venvs/photocheck/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from core.contract import Detection
for v in ['2024-06-01', '2024-06-01 12:30', '39.90,116.40']:
    try:
        Detection(id='d1', image_id='i1', kind='meta', subtype='datetime',
                  bbox=None, detector_score=None, risk=1, details={'masked_preview': v})
        print('OK ', v)
    except Exception as e:
        print('ERR', v, e)
"
```

## 根因

防泄漏规则是「`masked_preview` 归一化后不得含 7 位以上连续数字」，
归一化的做法是**先删掉 `-` `:` 空格 等分隔符再数**。

这对手机号是对的（`138-0013-8000` 删完确实该被抓），
对 meta 是灾难：日期、坐标本来就用分隔符分段的短数字，拼起来一定超阈值。

根本问题是**用一条启发式规则覆盖了格式完全不同的两类字段**：
- 手机号 / 身份证 → 有固定形态，应该用白名单正则；
- meta → 没有固定形态，只能用启发式。

## 修复

- 手机号 / 身份证：**只**走各自的固定掩码正则（`138****8000` / `1101**********0011`），
  不再需要启发式兜底。`138-0013-8000` 靠正则就挡住了，防泄漏能力没有下降。
- meta：保留启发式，但**在原始串上判断**，不删分隔符。`2024-06-01` 最长连续 4 位，通过；
  `SN-2024-000123456` 有 9 位连续，仍被拒。

## 回归

- `test_meta_preview_is_not_mistaken_for_plaintext`：参数化覆盖 datetime / device / gps / serial 六种形态。
- `test_meta_serial_with_long_digit_run_is_rejected`：确认放宽之后仍然拦得住真泄漏。
- `test_phone_mask_cannot_keep_separated_plaintext`（对齐测试自带）：确认 `138-0013-8000` 依旧被拒。

> 教训：**放宽一条规则时，必须同时留下"它原本要拦的东西"的测试**，
> 否则下一次改动会把它悄悄放回去。

---
id: BC-0005
title: 带 +86 / 0086 前缀的手机号完全不匹配，整类漏检
found_at: 2026-11-02
layer: detection
reason: rule_miss
symptom: false_negative
kind: text
subtype: phone
card: K-04
severity: P1
status: fixed
spec_ref: 功能规格卡 v1.4 §K-04「1[3-9] + 9 位，两侧非数字，允许空格横线」
fix_test: test_phone_positive_with_country_code
---

## 现象

| 输入 | `find_entities()` |
|---|---|
| `手机 +8613800138000` | `[]` |
| `+86 13800138000` | `[]` |
| `电话:+86-138-0013-8000` | `[]` |
| `Tel: 0086 138 0013 8000` | `[]` |
| `联系人 13800138000` | `[('phone', '13800138000')]` ✅ |

凡是带国际区号的写法，一个都识别不出来。

## 复现

```bash
C:/venvs/photocheck/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from core.detect.entities import find_entities, normalize_with_index
for t in ['+86 13800138000', 'Tel: 0086 138 0013 8000']:
    print(repr(normalize_with_index(t)[0]), '->', find_entities(t))
"
```

## 根因

`PHONE_RE = r"(?<!\d)1[3-9]\d{9}(?!\d)"`。

归一化删掉空格和横线后，`+86 138 0013 8000` 变成 `+8613800138000`。
号码首位的 `1` 前面紧邻区号末位 `6`，`(?<!\d)`（左边不能是数字）直接失败，
整串不匹配。`0086` 同理。

这个环视断言本身是对的——没有它，`202613800138000` 这种长串会被从中间切出一个假号码。
问题在于断言没有把"合法的区号前缀"排除在外。

## 修复前的判断

不是修不动，是**现在没有依据判断该不该修**：

1. 规格卡原文只要求「两侧非数字，允许空格横线」，**没有要求支持国际区号**，
   严格说这属于范围外，不修也不算违约。
2. 放开断言会同时放开负样本：快递单上的 `0086` 开头订单号、`8613` 开头的运单号
   都可能被切成假号码，误报率会上升。误报 ≤2 处/张是硬验收线，不能拍脑袋改。
3. 需要的数据在 C 手里：**dev 集里带区号的正样本实际占比是多少**。没有这个数，改与不改都是猜。

## 处置

- `PHONE_RE` 支持 `+86` 与 `0086`，同时保留左右数字边界，防止从更长数字串截取手机号。
- `mask_phone()` 先剥离国家码，再保留前三后四。
- 回归：`test_phone_positive_with_country_code`。

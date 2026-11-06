---
id: BC-0004
title: 带国际区号的手机号，掩码把区号当号码掩掉、露出完整号段
found_at: 2026-11-02
layer: detection
reason: rule_miss
symptom: false_negative
kind: text
subtype: phone
card: K-04
severity: P1
status: fixed
spec_ref: 功能规格卡 v1.4 §K-04「手机号 138****0000」
fix_test: test_mask_phone_strips_country_code
---

## 现象

```python
mask_phone("+8613800138000")   # → "+86****8000"
```

期望 `138****8000`，实际把 `138` 号段掩成了 `****`，却把区号 `+86` 原样留在记录里。
既没有起到掩码作用（`138****8000` 之外还多暴露了 8 位尾号的位置信息），
又把"这是中国大陆号码"这一信息固化进了可序列化记录。

## 复现

```bash
C:/venvs/photocheck/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from core.detect.entities import mask_phone
for v in ['13800138000', '+8613800138000', '8613800138000', '+86 138 0013 8000']:
    print(f'{v:>20} -> {mask_phone(v)}')
"
```

## 根因

`mask_phone` 是朴素切片 `v[:3] + "****" + v[-4:]`，默认输入已经是 11 位纯号码。
一旦上游传入带区号的 13 位串，前 3 位取到的是 `+86`，掩码位置整体左移。

这个 bug 在评审时**不会触发**，因为 `PHONE_RE` 压根不匹配带区号的号码（见 BC-0005）。
属于"上游先挡住了，所以下游的错误姿态看不出来"——一旦 BC-0005 被修复，这条就会立刻显形。
所以两条必须一起处理。

## 修复

先归一化再掩码：

```python
digits = re.sub(r"[\s\-]", "", v)
if digits.startswith("+86"):     digits = digits[3:]
elif digits.startswith("0086"):  digits = digits[4:]
elif digits.startswith("86") and len(digits) == 13:  digits = digits[2:]
return f"{digits[:3]}****{digits[-4:]}"
```

## 回归

- `test_mask_phone_strips_country_code`：`+86…` / `86…` / `+86 …` / 纯 11 位 四种写法
  都必须产出同一个 `138****8000`。

这条测试同时锁住"掩码结果不随输入写法变化"这个性质——比只测一个用例更有用。

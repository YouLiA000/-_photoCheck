---
id: BC-0002
title: 身份证末位为 X 时掩码被契约拒绝，真实证件约 1/11 命中
found_at: 2026-11-02
layer: contract
reason: rule_miss
symptom: crash
kind: text
subtype: idcard
card: K-04
severity: P0
status: fixed
spec_ref: 功能规格卡 v1.4 §K-04「身份证号 18 位（末位可 X）+ 校验位」
fix_test: test_idcard_mask_ending_with_x_is_accepted
---

## 现象

```python
mask_idcard("11010519900101001X")   # → "1101**********001X"
Detection(details={"masked_preview": "1101**********001X", "idcard_check": "pass"})
# ContractError: 身份证 masked_preview 必须形如 1101**********0011，得到 '1101**********001X'
```

末位是数字的证件正常，末位是 X 的证件**整条记录构造失败**，该条 Finding 丢失。

## 复现

```bash
C:/venvs/photocheck/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from core.detect.entities import mask_idcard
from core.contract import Detection
m = mask_idcard('11010519900101001X')
print(m)
Detection(id='d1', image_id='i1', kind='text', subtype='idcard',
          bbox=(1,1,10,10), detector_score=0.9, risk=3,
          details={'masked_preview': m, 'idcard_check': 'pass'})
"
```

## 根因

契约里身份证掩码正则写成 `^\d{4}\*{10}\d{4}$`，结尾强制 4 位数字。
但身份证末位是 ISO 7064 MOD 11-2 的校验位，取值 `0-10`，其中 10 记作 `X`，
即 **约 1/11 的合法证件末位是 X**。正则把这一类整体排除掉了。

更隐蔽的是：A 自己的 `mask_idcard` 就产出 `…001X`，也就是说
**A 的实现与 A 交付的契约互相矛盾**，只要样本里出现一张 X 结尾的证件就会触发。
评审时四张合成样本恰好全是数字结尾，所以没暴露。

## 修复

- 正则改为 `^\d{4}\*{10}(?:\d{4}|\d{3}X)$`，允许末位 X。
- 手写 JSON 用小写 `x` 时自动归一为大写，而不是报错（避免 B 手工构造样例时踩坑）。
- `mask_idcard` 显式 `.upper()`，不依赖上游归一化。

## 回归

- `test_idcard_mask_ending_with_x_is_accepted`
- `test_idcard_lowercase_x_is_normalized_not_rejected`
- `test_real_mask_function_round_trips_through_contract`：拿 `mask_idcard` 的真实产出直接构造
  Detection，确保"实现产出"与"契约规则"永远对得上——这条才是根治，前两条只挡单点。

> 遗留：`test_idcard_mask_wrong_length_still_rejected` 保证放宽 X 之后不会把长度校验一起放掉。

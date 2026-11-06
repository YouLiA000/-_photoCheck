---
id: BC-0001
title: 契约禁止 summary 后，二维码检出被 try/except 吞成 warning，整批静默消失
found_at: 2026-11-02
layer: contract
reason: rule_miss
symptom: silent_drop
kind: qr
subtype: qr_link
card: K-05
severity: P0
status: fixed
spec_ref: 功能规格卡 v1.4 §0.2「details 只允许域名 / SSID 等安全摘要」
fix_test: test_qr_details_use_typed_fields
---

## 现象

把《A_交付_修订》的契约替换进管线后，四张合成样本里有二维码的两张全部丢结果：

| 样本 | 应有 | 实际 |
|---|---|---|
| `express_001.png` | 3 条（phone / qr_link / idcard） | **2 条**（qr_link 消失） |
| `qr_wifi_001.png` | 1 条（qr_wifi） | **0 条** |

进程不崩溃、退出码 0、`detector_status` 仍显示 `qr: ok`，只在 `warnings` 里留下一行：

```
[warn] 二维码检测异常已跳过：ContractError: Detection(det-qr-001).details:
details 不得包含明文字段 ['summary']（原始文字/payload/EXIF 只允许走 SecretStore）
```

## 复现

```bash
# 1. 取修订版契约（其 details 白名单里没有 summary）
cp /path/to/框架.py core/contract.py

# 2. 跑任一含二维码的样本
C:/venvs/photocheck/Scripts/python.exe scripts/smoke_detect.py samples/synthetic/qr_wifi_001.png
# → detections=0  +  一条 [warn]
```

## 根因

契约把 `summary` 从白名单移除、并列入禁止字段，但 `core/detect/qr.py` 的
`build_detections()` 仍写 `details["summary"] = cls.summary`。

`pipeline.analyze()` 对每个检测器单独 try/except（这是为了"单个检测器崩了不影响其它"），
于是 `ContractError` 被当作"二维码检测异常"收进 `warnings`，**整个二维码阶段的结果被丢弃**。

两个设计判断叠加出了最坏结果：
- 契约改动没跑端到端验证，只跑了它自带的 8 条单测；
- 流水线的降级策略是"整阶段丢弃"，而不是"单条降级"。

## 修复

1. `qr.py` 改 typed 字段：`qr_wifi` → `safe_ssid`，网页类 → `safe_domain`，不再有 `summary`。
2. 保留兜底但换粒度：摘要字段被拒时**只降级该条的摘要、保留框**，不能因为一个域名不合法
   就丢掉整批二维码。框还在，用户仍能看到"这里有个码"，B 还能遮。
3. 补回归测试。

## 回归

- `test_qr_details_use_typed_fields`：断言 wifi 码出 `safe_ssid`、链接码出 `safe_domain`，
  且 payload 里的密码不出现在任何序列化结果中。
- `test_qr_with_illegal_domain_keeps_box_instead_of_dropping_batch`：内网码 `localhost`
  不是合法域名，断言框仍保留、摘要降级为空。

这两条能挡住：字段名再变、以及"一个坏摘要毁掉整批"。

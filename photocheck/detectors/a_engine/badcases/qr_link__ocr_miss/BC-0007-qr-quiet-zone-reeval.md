---
id: BC-0007
title: 按 Detection.bbox 紧贴裁切复检，切掉静区导致解码失败，K-09c 把未遮盖的二维码判成无残留
found_at: 2026-11-02
layer: detection
reason: ocr_miss
symptom: false_negative
kind: qr
subtype: qr_link
card: K-05
severity: P0
status: fixed
spec_ref: 规格卡 K-09「对已遮区域用独立代码路径重新检测」/ K-09c 二维码重解码
fix_test: test_visible_code_is_found_through_probe_region
---

## 现象

同一张纸样，同一个坐标，全图能解、按检测框裁就解不出：

```python
img  = Image.open("express_001.png")   # 900×620
bbox = (654, 314, 192, 192)            # det-qr-001 的检测框

detect_qr(img)                  # → [decodable=True]    ✅
detect_qr(img, roi=bbox)        # → []                  ❌
detect_qr(img, roi=(650,310,200,200))   # 外扩 4px → [decodable=True]  ✅
```

后果不是"少一条检出"，而是**假通过**：B 的 K-09c 对已遮区域用 Detection.bbox 重新解码，
拿到 0 就判 `passed`。于是**一个完全没被遮住的二维码，被系统判定为"区域内无残留"**。
这比漏检更糟——漏检至少 User 还能在列表里看见这条 Finding，假通过是直接放行。

## 复现

```bash
C:/venvs/photocheck/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from PIL import Image
from core.detect.qr import detect_qr
from core.config import QrConfig
img = Image.open('express_001.png').convert('RGB'); bbox = (654,314,192,192)
print('全图    :', [h.decodable for h in detect_qr(img)])
print('按 bbox :', [h.decodable for h in detect_qr(img, roi=bbox)])
print('外扩归零:', [h.decodable for h in detect_qr(img, roi=bbox,
            cfg=QrConfig(quiet_zone_min_px=0, quiet_zone_max_px=0))])
"
```

## 根因

二维码规范要求四周有静区（4 个模块宽的白边），解码器靠它定位码的边界。
检测框是**紧贴模块**的，按框裁切等于把静区切掉，解码器直接放弃。

这个问题被掩盖了很久，因为：
- `analyze()` 走全图，从来不传 roi，所以日常冒烟永远正常；
- 只有 K-09c 这种"按框复检"的调用才会触发，而它到 W9 才接。

也就是说：**问题从 W4 就存在，到 W9 接入复检时才会炸**，中间隔了五周。

## 修复

在 `detect_qr()` 内部扩静区，不交给调用方：

```python
margin = clamp(min(w, h) * quiet_zone_ratio, quiet_zone_min_px, quiet_zone_max_px)
```

比例 0.12、下限 8px、上限 64px，都进 `QrConfig` 可调。
扩静区只影响"解码时的裁切范围"，返回的 bbox 仍换算回整图坐标；
是否算残留由 B 按区域判定，检测侧不改变结论。

## 回归

2026-11-06 按《后续推进计划》§7 重写了这组测试。原测试 `test_quiet_zone_is_what_makes_reeval_decode`
断言"外扩归零必须解不出"——这是**解码器的属性，不是我们代码的属性**：pyzbar 某些版本
带内部阈值化，紧贴裁切照样解得出来，于是这条测试在 B 的机器上必然失败，而且失败时
不说明我们有没有回归。

现在的判据换成两条不依赖具体后端的不变量：

- `test_visible_code_is_found_through_probe_region`：B 的真实调用路径
  （`probe_region(图, Detection.bbox)`），未被遮盖的码必须 `residual_qr_detected >= 1`
  且 `residual_qr_decodable >= 1`。
- `test_solid_cover_makes_code_undecodable`：实心遮盖后必须一条都解不出。
- `test_padding_never_reduces_decodability`：**单调性**——补上静区之后可解码数量不得减少。
  两个后端都可能解出紧贴裁切，但没有一个后端会因补静区而变差，这才是修复真正依赖的不变量。
- `test_expansion_applies_configured_margin` / `test_expansion_respects_min_and_max`：
  对 `_expand_for_quiet_zone` 做**纯几何**断言（比例、上下限），与解码器完全无关，
  因此换 pyzbar 版本、换 cv2 版本都不会误报。
- `test_expansion_clamped_to_image_bounds`：码贴边时不越界。
- `test_expansion_does_not_swallow_distant_code`：外扩不得够到框外的码。

## 备注

`reason` 记为 `ocr_miss`。规格卡的 5 类原因以 OCR 命名，这里按"检测器未产出"的语义
套用到二维码解码失败上；若 C 在结题时要求严格区分，需增加"解码失败"子类。

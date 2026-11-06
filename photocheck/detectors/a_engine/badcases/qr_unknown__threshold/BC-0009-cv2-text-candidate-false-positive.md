---
id: BC-0009
title: cv2 兜底把文字区的四边形报成"解不出的二维码"
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

## 现象

C 在 dev 集 40 张上报了 8 条误报，其中 7 条是同一个原因：
`qr_unknown` 的精确率只有 12.5%（1 TP / 7 FP）。

B 的导出图上也能独立复现一条——对导出文件整图重扫，得到：

```
qr  qr_unknown  bbox=[152, 194, 322, 290]  decodable=False
```

裁图确认：框里是「姓名 / 某某大学 3 号宿舍楼 / 8-2-1123」这块文字，没有任何二维码。
它的长宽比是 `322/290 = 1.11`，正好落在 C 建议的 `0.75 ≤ w/h ≤ 1.35` 之内，
所以**长宽比过滤这条路走不通**，必须上定位符证据。

## 复现

```bash
C:/venvs/photocheck/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from PIL import Image
from core.detect import qr
qr.pyzbar_available = lambda: False      # 强制走 cv2 兜底
img = Image.open('express_001.png').convert('RGB')
print([h.bbox for h in qr.detect_qr(img, roi=(152,194,322,290))])
"
```

修复前输出 `[(152, 194, 322, 290)]`，修复后输出 `[]`。

## 根因

`cv2.QRCodeDetector` 在解码失败时仍然会返回一个四边形。原实现把"解不出也保留框"
直接落在这些候选上，没有对候选本身做任何证据校验，于是随便一块文字都能变成一个
`qr_unknown` 记录。

## 处置

给**未解码**候选加一道证据门禁（`core/detect/qr_evidence.py`），已解码的结果不受影响——
有 payload 本身就是证据。

判据不是"框里有三个嵌套方块"，而是两条必须同时成立：

1. **模块比 1:1:3:1:1**。过定位符中心扫一行，五段游程的比例必须是
   外环 : 空白 : 3 模块实心核 : 空白 : 外环。旋转不变：斜 45° 时五段同比例放大 √2。
2. **中心必须是暗的**。定位符中心是实心 3×3 核，所以中心像素是黑的。

第 2 条是这版的关键。第一版只数"嵌套方块"，结果被汉字直接击穿：

```
输入：返回 回收 回报 回执 / 回龙观 回民 回访 回头
纯数嵌套方块：16 个"定位符"
加模块比与中心判定：0 个
```

`回` 本身就是外框 + 空白环 + 内框，轮廓链和定位符一模一样；但它的中心是空心，
是白的，所以 1:1:3:1:1 的扫描根本起不了头。

再加一条**排布**检查：真码的三个定位符构成等腰直角三角形，且三者模块大小一致。
文字能造出一个像样的方块，造不出三个尺寸一致、还摆成直角的方块。

配置项：`finder_min_count=3`、`finder_ratio_tol=0.6`、`finder_min_side_px=24`。

## 顺带修掉的第二个缺陷

`_decode_cv2()` 原本写 `ok, infos, points, _ = detector.detectMulti(gray)`，但
OpenCV 4.10 的 `detectMulti` 只返回 `(retval, points)` 两个值，`detectAndDecodeMulti`
才返回四个。解包每次都抛 `ValueError`，又被外面的 `except` 吞成"没找到码"——
**一张图有多个二维码时，永远只会报出一个**。现在先试 `detectAndDecodeMulti`，
再退回 `detectMulti`，两种返回形状都处理；回归测试见
`test_multiple_codes_are_all_reported`。

## 回归

- `test_cv2_fallback_rejects_dense_text_quadrilateral`
- `test_finder_pattern_evidence_distinguishes_qr_from_text`
- `test_cjk_nested_squares_are_not_finder_patterns`（三条汉字版面，均须为 0）
- `test_nested_rings_with_equal_thickness_are_rejected`
- `test_multiple_codes_are_all_reported`
- `test_visible_code_is_found_through_probe_region`（门禁不能误伤真码）

验收目标：B 的这张导出图，整图重扫 **pyzbar / cv2 两种后端都是 0 条**——已达成。

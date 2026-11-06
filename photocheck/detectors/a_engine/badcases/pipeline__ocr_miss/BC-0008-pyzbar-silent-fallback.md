---
id: BC-0008
title: pyzbar 的 libzbar DLL 加载失败被静默忽略，整个 sprint 实际用 cv2 兜底，一维条码完全不可用
found_at: 2026-11-02
layer: env
reason: ocr_miss
symptom: silent_drop
kind: qr
subtype: pipeline
card: K-05
severity: P1
status: open
spec_ref: 规格卡 K-05「二维码 / 一维条码检测解码」
---

## 现象

`pyzbar` 装了，DLL 也在，但加载失败：

```
FileNotFoundError: Could not find module
'...\pyzbar\libzbar-64.dll' (or one of its dependencies).
```

而 `pyzbar_available()` 是一个裸 `try/except`，失败返回 `False`，
`detect_qr()` 就静默走 cv2 兜底。结果是：

| 能力 | pyzbar | cv2 兜底 |
|---|---|---|
| QR 二维码 | ✅ | ✅ |
| EAN13 / Code128 等一维条码 | ✅ | ❌ **完全没有** |

而 `detector_status()` 一直返回 `{"qr": "ok"}`，README 的依赖表也写着 `pyzbar ✅`。
**一整个 sprint 都以为一维条码是支持的。**

## 复现

```bash
C:/venvs/photocheck/Scripts/python.exe -c "
try:
    from pyzbar import pyzbar; print('pyzbar OK')
except Exception as e:
    print('pyzbar FAIL:', type(e).__name__, e)
from core.detect.qr import backend; print('实际后端:', backend())
"
```

## 根因

两层原因叠加：

1. **环境**：`libzbar-64.dll` 存在且是合法 PE，但依赖加载失败。
   已排除：MSVC 运行时齐全、Python 64 位、`add_dll_directory` 显式加目录后仍失败。
   尚未定位到具体缺失的依赖项。
2. **代码**：可用性探测只回答"能不能 import"，不回答"实际用哪个后端"。
   import 失败 → 静默降级 → 没有任何地方能看出能力缩水了。

第 2 点才是真问题：任何依赖都可能在某台机器上部分失效，
**"降级了但没人知道"比"直接报错"危险得多**。

## 处置

已做（本 sprint）：
- 新增 `qr.backend()`，返回 `pyzbar` / `cv2` / `none`；
- `detector_status()` 增加 `qr_backend` 字段，降级对调用方可见；
- README 依赖表如实标注为 `⚠️ 本机 DLL 加载失败，当前走 cv2 兜底`。

未做（需决策）：
- 定位 libzbar 具体缺失的依赖（考虑 `dumpbin /dependents` 或 Dependency Walker）；
- 若无法修复，则在一维条码需求上直接记 `wontfix`，并在 README「已知限制」写明
  "当前只支持二维码，不支持一维条码"——**不能继续让状态显示 ok**。

判定线：K-05 的验收里若含一维条码正样本（规格卡写的是"二维码 / 一维条码"），
这条必须在 W4 前关闭；若数据集里没有条码样本，转 `wontfix` 并写明。

---
id: BC-0006
title: probe_region 只收内存图像对象，不认文件路径——K-09 复检按文档写法调用会直接崩
found_at: 2026-11-02
layer: detection
reason: rule_miss
symptom: crash
kind: text
subtype: pipeline
card: K-09
severity: P1
status: fixed
spec_ref: 规格卡 K-09「对已遮区域用独立代码路径重新检测」；B 侧冒烟写法 `probe_region(redacted.png, bbox)`
fix_test: test_probe_region_accepts_a_path
---

## 现象

```python
probe_region("exported.png", [232, 242, 162, 22])
# ValueError: 不支持的图像数组形状：()
```

`analyze()` 收路径没问题（内部自己载图），`probe_region()` 却把路径字符串原样传给
`np.asarray()`，得到 0 维数组后报错。

顺着 B 的接入文档第 7 节第四步 `probe_region(redacted.png, bbox)` 写，**第一次调用就崩**。

## 复现

```bash
C:/venvs/photocheck/Scripts/python.exe -c "
import sys; sys.path.insert(0,'.')
from core.detect import probe_region
print(probe_region('express_001.png', [232, 242, 162, 22]))
"
```

## 根因

接口不对称。`analyze()` 的入参是 `image + image_id`，内部走 `load_working_image()` 载图；
`probe_region()` 的入参也叫 `image`，但实际上是**已载入的内存对象**，签名和文档都没有区分这两件事。

K-09 的典型调用场景恰恰是「从磁盘重新读回导出图再复检」——
这时手上只有路径，没有内存对象。调用方必须自己载图、自己保证方向一致，
而载图这一步一旦和 A 内部的处理不一致（EXIF 方向、色彩空间），复检坐标就会整体偏移。

这个 bug 是在**打包后按干净目录重跑**时才暴露的：
本地开发一直是把 PIL 对象传进去，没人按文档的写法调过。

## 修复

`probe_region()` 接受路径、`PIL.Image`、`ndarray` 三种入参；传路径时统一走
`load_working_image()`，与 `analyze()` 共用同一条载图路径，坐标基准自然对齐。

```python
if isinstance(image, (str, Path)):
    image, _ = load_working_image(image)
```

## 回归

- `test_probe_region_accepts_a_path`：同一张图分别以路径和对象调用，
  断言两个 `RegionProbe` 完全相等。锁的是"入参形式不影响结果"这个性质，
  而不是某个具体数值。

## 备注

这条的 subtype 记为 `pipeline`——它不属于单一检测类型，四个检测器都会受影响。
案例库规范允许这个伪 subtype，用于流程/接口级问题（见 `badcases/README.md`）。

# PhotoCheck · A（检测引擎）

照片分享前隐私体检工具。本仓库当前是 **A 的检测引擎部分**：OCR 文字检测、敏感实体识别、二维码检测与分类、人脸区域检测。

> 规格卡 v1.4 / 共享契约 v4。分工：A 检测引擎，B 载入·脱敏·复检·导出，C 数据集·评测·界面。

## 快速开始

```bash
# 1. 一条命令建环境：建 venv（纯 ASCII 路径）→ 装依赖 → 卸掉重复的 OpenCV → 自检
#    见下方「坑 1」「坑 2」，这两步不能省
powershell -ExecutionPolicy Bypass -File scripts/bootstrap_env.ps1

# 2. 跑测试（168 条，纯逻辑部分不需要模型）
C:/venvs/photocheck/Scripts/python.exe -m pytest tests -q

# 3. 一张图出结果
C:/venvs/photocheck/Scripts/python.exe scripts/smoke_detect.py samples/synthetic/express_001.png

# 4. 跑指标（R-02 基线表 A 的来源）
C:/venvs/photocheck/Scripts/python.exe scripts/eval_detect.py

# 5. 环境有问题时先跑这个，它会指出是哪一条
C:/venvs/photocheck/Scripts/python.exe scripts/check_env.py
```

自己造几张虚构样本（同时产出真值 `samples/gt/`）：`python scripts/make_sample.py`。

> **真值不得从检测结果反推**——用检测输出当 GT，召回永远 100%，这种基线表比没有更危险。
> `make_sample.py` 在绘制时用 `ImageDraw.textbbox` 记录坐标，GT 文件里也不存号码明文。

## ⚠️ 坑 1：venv 路径不能有中文（否则 K-07 直接废）

mediapipe 的 native 层加载 graph 文件时按 UTF-8 单字节路径打开，**路径含非 ASCII 字符就报
`The path does not exist`**，即使文件明明存在。

- 复现：venv 在 `C:\Users\xxx\WorkBuddy\雏雁计划\.venv` → 人脸检测 100% 失败
- 对照：同样的项目目录 + venv 在 `C:\venvs\photocheck` → 正常
- **结论：项目目录可以带中文，venv 不行。** 全队统一用 `C:/venvs/photocheck`

代码里已做防护：探针失败时抛 `DetectorUnavailable` 并在消息里直接说明这个原因，不会静默返回 0 张脸。

## ⚠️ 坑 2：只能装一个 OpenCV 分发

`rapidocr-onnxruntime` 声明依赖 `opencv-python`，`mediapipe` 声明依赖
`opencv-contrib-python`。**两个 wheel 写进同一个 `cv2` 目录**，装完之后
`cv2.__version__` 和目录里的实际文件可能对不上——本机实测就是
`cv2.__version__ == 4.10.0`，而元数据写的是 contrib 4.11.0.86。

统一口径：**只留 `opencv-contrib-python==4.10.0.84`**。它是 `opencv-python` 的超集，
`QRCodeDetector` / `QRCodeEncoder_create` 都在里面。安装必须是两步：

```bash
uv pip install --python <venv>/Scripts/python.exe -r requirements.txt
uv pip uninstall --python <venv>/Scripts/python.exe opencv-python   # 被 rapidocr 带回来的
```

`scripts/bootstrap_env.ps1` 已封好这两步，`scripts/check_env.py` 校验「只有一个分发」
以及 `cv2.__version__`。

> 依赖声明不自洽是 RapidOCR 上游的问题，**不能靠同时保留两个 wheel 掩盖**。
> 已知副作用：`pip check` 会报 `rapidocr-onnxruntime` 的 `opencv-python` 未满足；
> 运行期无影响，因为 contrib 提供了同名模块。

## 代码语言约定

`.py` 文件里除产品文案外一律 ASCII：

- 注释、docstring、异常消息、日志、`warnings`、控制台输出全部英文；
- 例外全是**数据/产品文案**，不是注释，改动会改变产品行为或交付物：
  - `core/detect/qr_classify.py` 的展示类名与风险说明（`普通链接` / `Wi-Fi`，UI 与测试都依赖）；
  - `core/detect/entities.py` 的身份证上下文关键词（要匹配中文单据上的实际文字）；
  - `core/eval.py` 的 `to_markdown()` 报表文字（直接贴进结题材料，不转英文）；
  - `core/badcase.py` 的规格卡固定标签（`规则未匹配` 等，进 `index.json`）与案例正文标题（`## 复现` / `## 处置`）；
  - `scripts/make_sample.py` 画在合成图上的中文单据文字，以及写进真值 JSON 的 `note`。

`requirements.txt` 必须纯 ASCII：Windows 的 pip 在 GBK 代码页下读 UTF-8 中文注释会直接
`UnicodeDecodeError`，连版本号都还没解析就退出。这条比源码更致命——它在别人机器上
第一次安装时炸。

## 目录结构

```
core/
  contract.py           v4 记录类型 + 硬校验（未知字段 / evidence 对应 / details 字段集 / id 唯一）
  badcase.py            失败案例库的解析与归档规范校验（R-02）
  eval.py               检测指标：IoU 贪心配对，几何级 / 类型级分开统计（R-02）
  config.py             三组检测参数（阈值调优改这里，不改代码）
  secret_store.py       进程内短期明文容器（原文只准存在这里）
  detect/
    ocr.py              K-03 文字检测（双尺度 + 同行合并，支持 ROI）
    entities.py         K-04 手机号 / 身份证（MOD 11-2 三态）
    qr.py               K-05 二维码 / 一维条码（解不出也给框）
    qr_evidence.py      未解码候选的定位符证据（1:1:3:1:1 + 三角排布）
    qr_classify.py      K-06 内容分类（纯规则，不联网）
    face.py             K-07 人脸区域（只检测不识别）
    pipeline.py         analyze() / probe_region() / detector_status()
    standin_loader.py   K-01 的临时替身（B 交付后删除）
badcases/               必交成果 3：按 subtype__reason 归档，每条一个 .md
  index.json            由 scripts/badcase_index.py 生成
reports/
  基线表_v1.md          R-02 的检测基线表（两级口径 + 耗时 + 案例分布）· 现行版
  基线表_v0.md          已废弃，仅留存判断依据
  eval_synthetic.json   指标原始数据（脚本产出，非手填）
samples/
  synthetic/            4 张虚构样本（make_sample.py 生成）
  gt/                   对应真值，绘制时用 textbbox 记录，不含号码明文
scripts/
  bench_ocr.py          W2 必做：实测 T_ocr（同图多次取 min，验收以此为准）
  eval_detect.py        按标注跑指标 → 召回 / 精确 / 误报每张 / 耗时
  smoke_detect.py       一张图 → 校验过的 Detection JSON
  make_sample.py        生成虚构样本 + 真值
  badcase_index.py      校验案例库并生成索引
tests/                  168 条，纯逻辑部分不依赖模型
```

## 对外接口（B / C 只需要这三个）

```python
from core.detect import analyze, probe_region, classify

result = analyze("img.jpg", "image-001")        # → ImageDescriptor + Detection[]（已过契约校验）
result.detections                               # 可序列化，可直接 json.dumps
result.timings_ms["text"]                       # 就是 T_ocr 的来源

probe_region(image_or_path, [x, y, w, h])       # K-09 复检素材：区域内还检出什么（收路径/PIL/ndarray）
classify(payload)                               # K-06 → (subtype, risk, 域名/SSID 摘要, 说明)
```

三个检测器都是 `f(image, roi=None) → 结果` 的**纯函数**，没有跨调用状态——
B 的复检器能对已遮盖区域独立重跑，这是 K-09 验收的前提。

## 契约要点（A 侧只产 ImageDescriptor / Detection）

- `id` 形如 `det-phone-001` / `det-qr-002` / `det-face-001`，同一 `image_id` 内唯一
- `evidence` 由 `kind` 派生，不接受手填：text→`ocr_rule`、qr→`qr_payload`、face→`face_box`
- 原始文字 / payload / EXIF 值**永不进入记录**，只走 `SecretStore`
- 二维码使用 typed 字段：网页类只写 `safe_domain`，Wi-Fi 只写 `safe_ssid`，不再使用通用 `summary`
- `idcard_check` 三态：`pass`(risk 3) / `fail`(risk 2) / `na`；校验位不通过仍要报，不静默丢
- 手机号掩码 `138****8000`（带区号 `+86138****8000`）；身份证 `1101**********0011`，**末位可为 X**
- `meta` 没有固定掩码格式，退化为"不得含 7 位以上连续数字"，日期类 `2024-06-01` 不会被误杀
- `Detection.details` 是只读视图，校验通过后再塞明文会抛 `TypeError`；未知字段 / 明文键 / 掩码不符 → `ContractError`
- 完整快照下 `bbox` 必须落在工作图内（K-09 按 bbox 裁剪，越界会静默判成"无残留"）

### 2026-11-02 评审修复（合并契约修订后）

| 问题 | 后果 | 处理 |
|---|---|---|
| 身份证掩码正则只认 `\d{4}` 结尾 | 末位 X 的真实证件（约 1/11）被拒，整条记录抛异常 | 允许末位 X，小写自动归一 |
| 长数字串规则无差别作用于 meta | EXIF 日期 `2024-06-01` 被判成未掩码 | 该规则只保留给 meta，且在原始串上判断 |
| `details` 是普通 dict | 校验后仍可塞入 `raw_text`，随 `to_dict()` 落盘 | 改为 `MappingProxyType` 只读视图 |
| `qr.py` 仍写 `details["summary"]` | 修订版契约禁止该字段，**所有二维码被 try/except 静默丢弃** | 改 typed 字段；摘要不合法时降级保留框 |
| `mask_phone("+86...")` 产出 `+86****8000` | 掩掉区号、露出 8 位号段 | 先剥 `+86` / `0086` 再掩码 |
- 手机号掩码只接受 `138****8000` 形态，身份证只接受 `1101**********0011` 形态
- `ImageDescriptor.orientation` 固定为 `exif_transposed`，ID 规则与 B 的 schema 一致
- `validate_records()` 可验证完整 `ImageDescriptor + Detection[]` 快照，也兼容只传 Detection 列表
- `Detection.details` 出现未知字段、明文键或未正确掩码的内容 → 直接抛 `ContractError`

`express_001.json` 的顶层是运行时 envelope，不是单个 v4 记录。B 接入时应提取：

```python
records = [result["image_descriptor"], *result["detections"]]
validate_records(records)
```

`warnings` 和 `timings_ms` 只作为运行状态，不写入 Detection 或 VerificationReport。

## 失败案例库（必交成果 3）

`badcases/` 按 `subtype__reason` 归档，每条一个 Markdown，头部是机器可读的 front matter。
完整规范见 `badcases/README.md`。

```bash
C:/venvs/photocheck/Scripts/python.exe scripts/badcase_index.py          # 校验 + 生成 index.json
C:/venvs/photocheck/Scripts/python.exe scripts/badcase_index.py --check  # 只校验
```

三条规矩是这个库不退化成的关键：

1. **`reason` 只能取规格卡的 5 类**（OCR 未检出 / 错字 / 规则未匹配 / 阈值误判 / 多目标重叠）。
   分类不可自由发挥，否则结题时归不了组。
2. **`status: fixed` 必须给出 `fix_test`，且该测试真实存在**。校验脚本会去 `tests/` 里找，
   找不到直接报错——这是唯一能挡住同一个坑踩两次的机制。
3. **必须有 `## 复现`**，能照着敲出问题。写"某张图有问题"不算归档。

当前 8 条，6 条已修 + 2 条 `open`（`+86` 前缀手机号漏检、pyzbar 降级）。

## 实测数据（本机，n=4 张合成样本）

### 检测指标（2026-11-06，`scripts/eval_detect.py`）

| 指标 | 值 | 口径 |
|---|---|---|
| 几何召回 | 100%（5/5） | 同 kind 且 IoU≥0.5 |
| 类型召回 | 100%（5/5） | 命中框里 subtype 也对 |
| 精确 | 100%（TP 5 / 误报 0） | |
| 误报/张 | 0.00 | 4 张含 1 张干净负样本 |

**只有 5 个真值，这张表只能证明管线连通，不能对外宣称召回率。**
口径与完整表见 `reports/基线表_v1.md`。

### 耗时（2026-11-06 重测）

| 配置 | T_ocr（中位数） | 检出块数 | 说明 |
|---|---|---|---|
| 双尺度（默认，规格卡要求） | **1686 ms** | 5/13/6/5 | 只有 1 张比单尺度多检出 |
| 单尺度（降级方案） | **660 ms** | 5/13/6/3 | 3 张完全一致，另 1 张少 1 条标题 + 2 条噪声 |

同日复测 3 次取 min 得 **1640.5 ms**（`reports/t_ocr_baseline_20261106_2036.json`），
即本机抖动约 ±3%（1640~1686 ms）。**基线取偏保守的 1686 ms**：取最小值虽然让验收线更严，
但会把"机器今天慢一点"误判成性能退化，W4 会变成噪声检测器。

W4 验收线 = T_ocr × 1.2 = **2023.6 ms**（`reports/t_ocr_baseline_20261106_1951.json`）。
若按 1640.5 ms 计则为 1968.6 ms；两个数都记着，验收时以当次 `bench_ocr.py` 输出为准。

- 线程数是最大的隐藏开销：RapidOCR 默认 `-1` 在本机退化为单线程（2.71s），显式给 8 线程后 0.81s。
  `OcrConfig.intra_op_num_threads=0` 表示自动 `min(8, CPU 核数)`。
- `use_cls=False` 可再省一半（0.81s → 0.38s），但倒置文字会丢，**默认开着**。
- **测量方法会决定结论**：不预热 → 4584ms（假超标）、只预热第一张 → 3157ms（假超标）、
  每图预热 → 1776ms、每图 5 次取 min → 1686ms。原因是 OCR 推理开销与输入尺寸相关，
  换尺寸的第一张图必定偏慢。所以跨图评测必须每图预热，验收必须以 `bench_ocr.py` 为准。
- 结论待数据集到位后确认：若真实数据上双尺度召回优势不明显，按规格卡 K-03 降级栏切单尺度。

## 依赖状态

| 组件 | 状态 | 备注 |
|---|---|---|
| RapidOCR 1.4.4 | ✅ | 8 线程下 0.66~1.63 s/张 |
| pyzbar 0.1.9 | ⚠️ 本机 DLL 加载失败 | 走 cv2 兜底：**只解二维码，一维条码不支持**（BC-0008）。`detector_status()["qr_backend"]` 会如实报 `cv2` |
| mediapipe 0.10.14 | ⚠️ | 仅在 ASCII 路径的 venv 下可用，见坑 1 |
| opencv-contrib-python 4.10.0.84 | ✅ | **唯一允许的 OpenCV 分发**，见坑 2 |
| pillow-heif | ❌ | 未装，HEIC 不支持（README 需提示先转 JPG） |

## 已知限制（写进报告时不能越界）

- OCR 复检用的是**同一套模型**，只能证明"同一检测器不再读出"，不能证明人眼读不出（K-09 边界，R-03/R-04 才回答）
- 二维码解不出时只给框，不给 subtype（`qr_unknown` / risk 1）
- 人脸只给区域，`details` 为空；侧脸、口罩允许漏
- 人脸**尚未在真人脸上验证过**：只验证过 mediapipe 能初始化，4 张合成样本里没有人脸。
  代码能跑 ≠ 能力可用，K-07 的召回目前是未知数
- 身份证上下文关键词是开关（`OcrConfig.require_idcard_context`），默认为关（宁可多报）
- **指标数字全部来自自造合成样本**（字体清晰、无透视、无遮挡、无光照变化）。
  真实照片上的召回会显著低于表里的 100%，任何对外材料都不得引用

## 待与 B / C 对齐

1. `ImageDescriptor.orientation` 已固定为 `exif_transposed`
2. `Detection.detector_score` 对 qr / face 可能为 null（解码器不给校准分），不编造
3. `probe_region` 只给计数和最高分，`passed/failed` 由 B 的 K-09 判定
4. K-13 要求 A 出 10 张样本：`make_sample.py` 可直接扩，但入库要 C 统一编号与标注
5. **评测口径必须与 C 的 `eval.py` 对齐**，这两条是我的暂定值：
   - IoU 阈值 **0.5**
   - 匹配分**几何级 / 类型级**两级，不合成单指标（理由见 `reports/基线表_v1.md`）
   若 C 的口径不同，两边算出的召回没有可比性，`core/eval.py` 需要改一处 `iou_threshold` 与 `match_image`。
   **实测依据**：同一批检测结果，阈值 0.5 → 召回 100%，阈值 0.6 → 60%（idcard 全掉，
   其 IoU 仅 0.541）。文字框扁长，对高度误差过敏，`text` 建议不用纯 IoU 匹配。
   这一条必须先定，否则 A 报 100%、C 算 60%。

性能数据需区分冷启动与预热。`express_001.json` 的单次 `text=6618.5 ms` 很可能是首次模型加载，
不能直接与 README 中预热后的 1.69 s 中位数比较。

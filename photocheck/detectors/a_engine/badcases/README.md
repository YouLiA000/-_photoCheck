# 失败案例库（必交成果 3 / R-02）

按 `subtype__reason` 归档的 badcase，每条一个 Markdown 文件，头部是机器可读的 front matter。
`python scripts/badcase_index.py` 会校验全部条目并生成 `index.json`。

## 为什么要有它

这条是**必交成果**，即使软件现场崩了也能独立结题。所以它的价值不在"记录了几条 bug"，
而在于**每条都能解释清楚：检测为什么失败、下次怎么不再失败、有没有回归测试兜住**。

一条没有原因标签、或者没有可复现命令的 badcase，等于没归档。

## 目录与命名

```
badcases/
  <subtype>__<reason>/
    BC-0001-<短标题>.md
```

- `subtype` 用契约里的枚举值：`phone` / `idcard` / `qr_link` / `qr_wifi` / `qr_vcard` / `face_region` / `datetime` …
  流程或接口级问题（不属于单一检测类型）用伪 subtype `pipeline`，例如"复检入口不认文件路径"。
- 一个 subtype 下可以有多条，文件名用 `BC-<4 位序号>-<短标题>.md`，序号全局唯一。
- 同一张图同时暴露多个问题时，**按 subtype 拆成多条**，不要合并——否则指标归因不了。

## 失败原因（规格卡固定 5 类，不得增删）

| reason | 含义 | 典型样子 |
|---|---|---|
| `ocr_miss` | 未检出 | 号码在图上但一个字都没读出来；二维码**解码失败**也归此类 |
| `ocr_error` | OCR 错字 | 读出来了但 `l`/`1`、`O`/`0` 混淆导致规则不匹配 |
| `rule_miss` | 规则未匹配 | 文字正确，但正则/掩码/契约规则没接住它 |
| `threshold` | 阈值误判 | 分数卡在阈值附近，该留的丢了或该丢的留了 |
| `overlap` | 多目标重叠 | 两个目标框合并成一个，或框切在中间 |

`layer` 是补充维度，用来区分这次是检测器的问题、契约的问题还是环境的问题：

| layer | 含义 |
|---|---|
| `detection` | 检测逻辑本身（OCR / 正则 / 分类 / 阈值） |
| `contract` | 记录结构与校验规则 |
| `env` | 依赖、路径、模型文件 |

`layer` 不参与检测指标统计，只做追溯。**`reason` 必须落在上面 5 类之一**——
规格卡只认这 5 类，结题材料按它们分组。

## 字段

front matter 必填：

| 字段 | 说明 |
|---|---|
| `id` | `BC-0001`，全局唯一，与文件名前缀一致 |
| `title` | 一句话说清"什么输入 → 什么错误结果" |
| `found_at` | 发现日期 |
| `layer` | 见上表 |
| `reason` | 见上表 5 类 |
| `symptom` | `false_negative` / `false_positive` / `wrong_subtype` / `silent_drop` / `crash` |
| `kind` | `text` / `qr` / `face` / `meta` |
| `subtype` | 契约枚举值 |
| `card` | 归属卡号，如 `K-04` |
| `severity` | `P0` / `P1` / `P2` |
| `status` | `open` / `fixed` / `wontfix` |

`status: fixed` 时必须同时给出 `fix_test`，指向 `tests/` 里真实存在的测试函数名。
校验脚本会去 `tests/` 里找这个名字，找不到就报错——**这是唯一能防止同一个坑踩两次的机制**。

`wontfix` 必须写清为什么不修（属于降级范围 / 规格卡外 / 成本不划算），不能空着。

## 正文结构

```markdown
## 现象        看到什么，带数字
## 复现        能直接粘进终端的命令，或最小代码片段
## 根因        机制层面为什么错，不写"修复了"这种结论
## 修复        改了什么；未修则写清处置
## 回归        测试名 + 它能挡住什么
```

`## 复现` 是硬要求：**别人照着敲能重现，才算归档**。写"某张图有问题"不算。

## 谁往里放

- A：检测失败（OCR、实体规则、二维码、人脸）——本库主要作者
- B：复检漏判、残留误判
- C：标注分歧、数据集本身的坑

跨角色的 badcase 也放这里，用 `card` / `layer` 区分归属，不要另起一套目录。

## 当前条目

| id | subtype | reason | severity | status |
|---|---|---|---|---|
| BC-0001 | qr_link | rule_miss | P0 | fixed |
| BC-0002 | idcard | rule_miss | P0 | fixed |
| BC-0003 | datetime | rule_miss | P1 | fixed |
| BC-0004 | phone | rule_miss | P1 | fixed |
| BC-0005 | phone | rule_miss | P1 | **open** |
| BC-0006 | pipeline | rule_miss | P1 | fixed |
| BC-0007 | qr_link | ocr_miss | P0 | fixed |
| BC-0008 | pipeline | ocr_miss | P1 | **open** |

> 第一批 5 条全部来自 2026-11-02 对《A_交付_修订》契约的评审。
> 它们有个共同点：**在真实数据上会静默失败**——不报错、不崩溃，只是结果里少了东西。
> 这类问题正是没有 badcase 库时最容易漏掉的。
>
> BC-0005 保持 `open`，因为改它需要 C 的 dev 集给出"带区号号码占比"才能判断
> 值不值得付出误报代价。`open` 不是贬义——它是"已知、已定位、等一个数据再决策"。

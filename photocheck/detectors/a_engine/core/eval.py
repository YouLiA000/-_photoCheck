"""Detection metrics - the single source of truth for the R-02 baseline table.

Why this is a separate module:

1. **IoU is implemented here, never reused from `core.detect._imgutil.iou`.**
   If the evaluator borrows the geometry helper of the code under test, one bug
   poisons both sides and the metric stops being a check.
2. **Geometry level and type level are counted separately:**
   - geometry (box hit): same kind and IoU >= threshold -> TP, answers "was it found"
   - type (correct subtype): the matched box also has the right subtype, answers
     "was it identified correctly"
   K-05 (can it be boxed / decoded) and K-06 (is the classification right) must be
   accepted independently. Counting strict matches only would make a "boxed but
   labelled qr_unknown" case lose recall and precision at once, which looks like a
   detection failure while it is really a classification failure - and a wrong
   attribution points the fix at the wrong card.
3. **No guessing, no filling in, no dropping:** predictions with bbox None (e.g.
   meta) go into `skipped` and are reported explicitly; they must never vanish
   from the denominator silently.

Metric definitions live in `reports/基线表_v0.md`; the default IoU threshold is
0.5 and must stay aligned with C's `eval.py`.

Encoding note: code, comments and raised messages are English. The rendered
Markdown report (`to_markdown`) stays Chinese because it is a deliverable table
pasted into the closing materials, not a log.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .contract import KIND_SUBTYPES, BBox

__all__ = [
    "DEFAULT_IOU",
    "EvalError",
    "GtObject",
    "GtImage",
    "Match",
    "ImageEval",
    "EvalReport",
    "iou",
    "load_gt",
    "match_image",
    "evaluate",
]

DEFAULT_IOU = 0.5


class EvalError(ValueError):
    """The annotation file itself is broken - the labels are wrong, not the detector."""


@dataclass(frozen=True)
class GtObject:
    gt_id: str
    kind: str
    subtype: str
    bbox: BBox


@dataclass(frozen=True)
class GtImage:
    image_id: str
    image: str
    width: int
    height: int
    objects: tuple[GtObject, ...]
    negative: bool = False
    source: str = ""

    def of_kinds(self, kinds: Iterable[str] | None) -> tuple[GtObject, ...]:
        if kinds is None:
            return self.objects
        allow = set(kinds)
        return tuple(o for o in self.objects if o.kind in allow)


@dataclass(frozen=True)
class Match:
    gt_id: str
    pred_id: str
    pred_index: int
    gt_kind: str
    gt_subtype: str
    pred_subtype: str
    overlap: float

    @property
    def subtype_ok(self) -> bool:
        return self.gt_subtype == self.pred_subtype

    def to_dict(self) -> dict[str, Any]:
        return {
            "gt_id": self.gt_id,
            "pred_id": self.pred_id,
            "gt_subtype": self.gt_subtype,
            "pred_subtype": self.pred_subtype,
            "iou": round(self.overlap, 4),
            "subtype_ok": self.subtype_ok,
        }


@dataclass
class ImageEval:
    image_id: str
    gt_count: int
    pred_count: int
    matches: list[Match] = field(default_factory=list)
    missed: list[GtObject] = field(default_factory=list)
    extra: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def tp(self) -> int:
        return len(self.matches)

    @property
    def fn(self) -> int:
        return len(self.missed)

    @property
    def fp(self) -> int:
        return len(self.extra)

    @property
    def type_ok(self) -> int:
        return sum(1 for m in self.matches if m.subtype_ok)

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_id": self.image_id,
            "gt": self.gt_count,
            "pred": self.pred_count,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "type_ok": self.type_ok,
            "matches": [m.to_dict() for m in self.matches],
            "missed": [
                {"gt_id": o.gt_id, "kind": o.kind, "subtype": o.subtype, "bbox": list(o.bbox)}
                for o in self.missed
            ],
            "extra": self.extra,
            "skipped": self.skipped,
            "warnings": self.warnings,
        }


def iou(a: Sequence[int], b: Sequence[int]) -> float:
    """Intersection over union of two xywh boxes. Deliberately not reusing the detector side."""
    ax, ay, aw, ah = (float(v) for v in a)
    bx, by, bw, bh = (float(v) for v in b)
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
    iw, ih = x1 - x0, y1 - y0
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _as_bbox(value: Any, where: str) -> BBox:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise EvalError(f"{where}: bbox must be [x, y, w, h], got {value!r}")
    out = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, int):
            raise EvalError(f"{where}: bbox must contain integers, got {value!r}")
        out.append(int(v))
    x, y, w, h = out
    if w <= 0 or h <= 0:
        raise EvalError(f"{where}: bbox width/height must be positive, got {value!r}")
    return (x, y, w, h)


def load_gt(path: str | Path) -> GtImage:
    """Read and validate one annotation file. Bad labels must fail here, not inside the metrics."""
    p = Path(path)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalError(f"{p.name}: JSON parse failed: {exc}") from exc
    if not isinstance(doc, dict):
        raise EvalError(f"{p.name}: top level must be an object")

    image_id = str(doc.get("image_id") or p.stem)
    image = str(doc.get("image") or f"{image_id}.png")
    width = doc.get("width")
    height = doc.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise EvalError(f"{p.name}: width/height must be positive integers, got {width!r}x{height!r}")

    objects: list[GtObject] = []
    seen: set[str] = set()
    raw_objects = doc.get("objects") or []
    if not isinstance(raw_objects, list):
        raise EvalError(f"{p.name}: objects must be an array")

    for i, raw in enumerate(raw_objects):
        where = f"{p.name}#objects[{i}]"
        if not isinstance(raw, Mapping):
            raise EvalError(f"{where}: must be an object")
        kind = raw.get("kind")
        subtype = raw.get("subtype")
        if kind not in KIND_SUBTYPES:
            raise EvalError(f"{where}: unknown kind={kind!r}, allowed {sorted(KIND_SUBTYPES)}")
        if subtype not in KIND_SUBTYPES[kind]:
            raise EvalError(
                f"{where}: kind={kind} has no subtype={subtype!r}, allowed {KIND_SUBTYPES[kind]}"
            )
        gt_id = str(raw.get("gt_id") or f"g{i + 1}")
        if gt_id in seen:
            raise EvalError(f"{where}: duplicate gt_id: {gt_id}")
        seen.add(gt_id)
        bbox = _as_bbox(raw.get("bbox"), where)
        # Ground-truth boxes must sit inside the image; going out of bounds means the
        # annotation or the generator is wrong, not the detector.
        x, y, w, h = bbox
        if x < 0 or y < 0 or x + w > width or y + h > height:
            raise EvalError(
                f"{where}: bbox {list(bbox)} exceeds image {width}x{height} "
                f"(annotation error, not a detection failure)"
            )
        objects.append(GtObject(gt_id=gt_id, kind=kind, subtype=subtype, bbox=bbox))

    negative = bool(doc.get("negative", not objects))
    return GtImage(
        image_id=image_id,
        image=image,
        width=width,
        height=height,
        objects=tuple(objects),
        negative=negative,
        source=str(doc.get("source") or ""),
    )


def match_image(
    gt: GtImage,
    predictions: Sequence[Mapping[str, Any]],
    iou_threshold: float = DEFAULT_IOU,
    kinds: Sequence[str] | None = None,
) -> ImageEval:
    """Pair one image's predictions with its ground truth.

    Greedy global pairing (walk IoU descending, each side used once) rather than
    "for each GT take the best prediction" - the latter lets two GTs grab the same
    prediction and counts one hit twice.
    """
    gt_objects = gt.of_kinds(kinds)

    preds: list[Mapping[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for i, pred in enumerate(predictions):
        if kinds is not None and pred.get("kind") not in set(kinds):
            continue
        if pred.get("bbox") in (None, [], ()):
            # meta-like records have no geometry. Count them as skipped and report
            # them; never let them disappear from the denominator silently.
            skipped.append(
                {
                    "pred_id": pred.get("id"),
                    "kind": pred.get("kind"),
                    "subtype": pred.get("subtype"),
                    "reason": "empty bbox, cannot do geometric matching",
                }
            )
            continue
        preds.append(pred)

    candidates: list[tuple[float, int, int]] = []
    for gi, obj in enumerate(gt_objects):
        for pi, pred in enumerate(preds):
            if pred.get("kind") != obj.kind:
                continue
            overlap = iou(obj.bbox, pred["bbox"])
            if overlap >= iou_threshold:
                candidates.append((overlap, gi, pi))
    # Stable sort on (gi, pi) for equal IoU so repeated runs give identical results
    candidates.sort(key=lambda t: (-t[0], t[1], t[2]))

    used_gt: set[int] = set()
    used_pred: set[int] = set()
    matches: list[Match] = []
    for overlap, gi, pi in candidates:
        if gi in used_gt or pi in used_pred:
            continue
        used_gt.add(gi)
        used_pred.add(pi)
        obj, pred = gt_objects[gi], preds[pi]
        matches.append(
            Match(
                gt_id=obj.gt_id,
                pred_id=str(pred.get("id") or f"pred-{pi}"),
                pred_index=pi,
                gt_kind=obj.kind,
                gt_subtype=obj.subtype,
                pred_subtype=str(pred.get("subtype") or ""),
                overlap=overlap,
            )
        )

    matches.sort(key=lambda m: (m.gt_kind, m.gt_subtype, m.gt_id))
    missed = [o for i, o in enumerate(gt_objects) if i not in used_gt]
    extra = [
        {
            "pred_id": str(preds[i].get("id") or f"pred-{i}"),
            "kind": preds[i].get("kind"),
            "subtype": preds[i].get("subtype"),
            "bbox": list(preds[i]["bbox"]),
            "risk": preds[i].get("risk"),
        }
        for i in range(len(preds))
        if i not in used_pred
    ]

    return ImageEval(
        image_id=gt.image_id,
        gt_count=len(gt_objects),
        pred_count=len(preds),
        matches=matches,
        missed=missed,
        extra=extra,
        skipped=skipped,
    )


@dataclass
class EvalReport:
    iou_threshold: float
    images: list[ImageEval] = field(default_factory=list)
    timings_ms: dict[str, list[float]] = field(default_factory=dict)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    warmup_runs: int = 0

    @property
    def timing_note(self) -> str:
        # Report-facing text, kept Chinese: it is printed into the deliverable table.
        base = "单次测量，未做多次采样；T_ocr 的正式值以 scripts/bench_ocr.py 为准"
        return (
            f"已预热 {self.warmup_runs} 轮后统计；{base}"
            if self.warmup_runs
            else f"**含模型冷启动**；{base}"
        )

    # ---- aggregates ----
    @property
    def tp(self) -> int:
        return sum(i.tp for i in self.images)

    @property
    def fp(self) -> int:
        return sum(i.fp for i in self.images)

    @property
    def fn(self) -> int:
        return sum(i.fn for i in self.images)

    @property
    def gt_total(self) -> int:
        return sum(i.gt_count for i in self.images)

    @property
    def type_ok(self) -> int:
        return sum(i.type_ok for i in self.images)

    @property
    def recall(self) -> float:
        return self.tp / self.gt_total if self.gt_total else 0.0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def type_recall(self) -> float:
        """Share of all GT whose matched box also carries the right subtype."""
        return self.type_ok / self.gt_total if self.gt_total else 0.0

    @property
    def fp_per_image(self) -> float:
        return self.fp / len(self.images) if self.images else 0.0

    def negative_images(self) -> list[ImageEval]:
        """Clean negatives: images with no GT, so every fp on them is a false alarm."""
        return [i for i in self.images if i.gt_count == 0]

    def per_subtype(self) -> list[dict[str, Any]]:
        """Recall per GT subtype; type accuracy gets its own column."""
        stats: dict[str, dict[str, Any]] = {}
        for img in self.images:
            for m in img.matches:
                row = stats.setdefault(
                    m.gt_subtype, {"subtype": m.gt_subtype, "kind": m.gt_kind, "gt": 0, "hit": 0, "type_ok": 0}
                )
                row["gt"] += 1
                row["hit"] += 1
                if m.subtype_ok:
                    row["type_ok"] += 1
            for obj in img.missed:
                row = stats.setdefault(
                    obj.subtype, {"subtype": obj.subtype, "kind": obj.kind, "gt": 0, "hit": 0, "type_ok": 0}
                )
                row["gt"] += 1
        rows = []
        for row in stats.values():
            row["recall"] = row["hit"] / row["gt"] if row["gt"] else 0.0
            row["type_recall"] = row["type_ok"] / row["gt"] if row["gt"] else 0.0
            rows.append(row)
        rows.sort(key=lambda r: (r["kind"], r["subtype"]))
        return rows

    def fp_by_pred_subtype(self) -> list[dict[str, Any]]:
        stats: dict[tuple[str, str], int] = {}
        for img in self.images:
            for item in img.extra:
                key = (str(item.get("kind")), str(item.get("subtype")))
                stats[key] = stats.get(key, 0) + 1
        rows = [
            {"kind": k, "subtype": s, "fp": n} for (k, s), n in stats.items()
        ]
        rows.sort(key=lambda r: (-r["fp"], r["kind"], r["subtype"]))
        return rows

    def type_confusion(self) -> list[dict[str, Any]]:
        """Box hit with a wrong subtype, itemised.

        These are neither misses nor false alarms; they only show up as a drop in
        "type recall". Without this list the report would say "type recall 0%" and
        hide what the detector actually said, leaving K-06 with nothing to debug.
        """
        stats: dict[tuple[str, str], dict[str, Any]] = {}
        for img in self.images:
            for m in img.matches:
                if m.subtype_ok:
                    continue
                key = (m.gt_subtype, m.pred_subtype)
                row = stats.setdefault(
                    key,
                    {"gt_subtype": key[0], "pred_subtype": key[1], "count": 0, "examples": []},
                )
                row["count"] += 1
                if len(row["examples"]) < 3:
                    row["examples"].append(f"{img.image_id}:{m.gt_id}")
        return sorted(stats.values(), key=lambda r: (-r["count"], r["gt_subtype"], r["pred_subtype"]))

    def timing_summary(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for kind, values in self.timings_ms.items():
            if not values:
                continue
            ordered = sorted(values)
            mid = len(ordered) // 2
            median = (
                ordered[mid]
                if len(ordered) % 2
                else (ordered[mid - 1] + ordered[mid]) / 2
            )
            out[kind] = {
                "n": float(len(ordered)),
                "min": round(ordered[0], 1),
                "median": round(median, 1),
                "max": round(ordered[-1], 1),
            }
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "photocheck/eval/v1",
            "iou_threshold": self.iou_threshold,
            "images": len(self.images),
            "gt_total": self.gt_total,
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "type_ok": self.type_ok,
            "recall": round(self.recall, 4),
            "precision": round(self.precision, 4),
            "type_recall": round(self.type_recall, 4),
            "fp_per_image": round(self.fp_per_image, 4),
            "per_subtype": [
                {**r, "recall": round(r["recall"], 4), "type_recall": round(r["type_recall"], 4)}
                for r in self.per_subtype()
            ],
            "fp_by_pred_subtype": self.fp_by_pred_subtype(),
            "type_confusion": self.type_confusion(),
            "timings": self.timing_summary(),
            "timing_note": self.timing_note,
            "warmup_runs": self.warmup_runs,
            "skipped": self.skipped,
            "detail": [i.to_dict() for i in self.images],
        }

    def to_markdown(self, title: str = "检测指标") -> str:
        """Render the deliverable Markdown table.

        The rendered text stays Chinese on purpose - it is pasted into the closing
        materials, so only code/comments/messages are English.
        """
        lines = [f"## {title}", ""]
        lines.append(f"IoU 阈值 **{self.iou_threshold}** · 图像 **{len(self.images)}** 张 · 真值 **{self.gt_total}** 个")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|---|---|")
        lines.append(f"| 几何召回 | {self.recall:.1%}（{self.tp}/{self.gt_total}） |")
        lines.append(f"| 几何精确 | {self.precision:.1%}（TP {self.tp} / 误报 {self.fp}） |")
        lines.append(f"| 类型召回 | {self.type_recall:.1%}（{self.type_ok}/{self.gt_total}） |")
        lines.append(f"| 误报/张 | {self.fp_per_image:.2f} |")
        lines.append("")

        rows = self.per_subtype()
        if rows:
            lines.append("### 按 subtype（召回口径 = 框命中；类型准确另列）")
            lines.append("")
            lines.append("| kind | subtype | 真值 | 命中 | 召回 | 类型正确 | 类型准确 |")
            lines.append("|---|---|---|---|---|---|---|")
            for r in rows:
                lines.append(
                    f"| {r['kind']} | {r['subtype']} | {r['gt']} | {r['hit']} | "
                    f"{r['recall']:.1%} | {r['type_ok']} | {r['type_recall']:.1%} |"
                )
            lines.append("")

        confusion = self.type_confusion()
        if confusion:
            lines.append("### 类型误判（框命中但 subtype 不一致 —— K-06 的直接证据）")
            lines.append("")
            lines.append("| GT subtype | 判成了 | 次数 | 示例 |")
            lines.append("|---|---|---|---|")
            for r in confusion:
                lines.append(
                    f"| {r['gt_subtype']} | **{r['pred_subtype']}** | {r['count']} | "
                    + "、".join(r["examples"])
                    + " |"
                )
            lines.append("")

        fp_rows = self.fp_by_pred_subtype()
        if fp_rows:
            lines.append("### 误报来源")
            lines.append("")
            lines.append("| kind | 预测 subtype | 误报数 |")
            lines.append("|---|---|---|")
            for r in fp_rows:
                lines.append(f"| {r['kind']} | {r['subtype']} | {r['fp']} |")
            lines.append("")

        timings = self.timing_summary()
        if timings:
            lines.append("### 耗时（ms）")
            lines.append("")
            lines.append(f"> {self.timing_note}")
            lines.append("")
            lines.append("| 检测器 | n | min | 中位 | max |")
            lines.append("|---|---|---|---|---|")
            for kind, t in sorted(timings.items()):
                lines.append(
                    f"| {kind} | {int(t['n'])} | {t['min']} | {t['median']} | {t['max']} |"
                )
            lines.append("")

        if self.skipped:
            lines.append(f"### 未参与几何匹配的预测（{len(self.skipped)} 条，不计入分母）")
            lines.append("")
            for item in self.skipped:
                lines.append(f"- {item['pred_id']}（{item.get('kind')}/{item.get('subtype')}）：{item['reason']}")
            lines.append("")

        bad = [i for i in self.images if i.fn or i.fp]
        if bad:
            lines.append("### 有问题的图")
            lines.append("")
            for img in bad:
                bits = []
                if img.fn:
                    bits.append("漏 " + "、".join(f"{o.gt_id}({o.subtype})" for o in img.missed))
                if img.fp:
                    bits.append("误报 " + "、".join(f"{e['pred_id']}({e.get('subtype')})" for e in img.extra))
                lines.append(f"- `{img.image_id}`：{'；'.join(bits)}")
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"


def _resolve_image(image_root: Path, gt: GtImage, gt_path: Path) -> Path:
    candidates = [image_root / gt.image, image_root / gt.image_id]
    candidates += [image_root / f"{gt.image_id}.png", image_root / f"{gt.image_id}.jpg"]
    found = next((c for c in candidates if c.is_file()), None)
    if found is None:
        raise EvalError(
            f"{gt_path.name}: cannot find the image (image={gt.image!r}, image_id={gt.image_id!r}); "
            f"tried those names under {image_root}"
        )
    return found


def evaluate(
    gt_dir: str | Path,
    image_root: str | Path,
    analyze_fn: Callable[..., Any],
    iou_threshold: float = DEFAULT_IOU,
    kinds: Sequence[str] | None = None,
    gt_files: Sequence[Path] | None = None,
    warmup_runs: int = 1,
) -> EvalReport:
    """Run the full evaluation.

    `analyze_fn(path, image_id)` must return an object exposing `.detections`,
    `.warnings` and `.timings_ms` (i.e. `core.detect.pipeline.analyze`). Injected
    instead of imported so tests can substitute a fake.

    `warmup_runs` defaults to 1: **each image** is analysed once with the result
    thrown away before the timed run.
    - Without warmup, model loading lands in the first image's timing (measured:
      face 14.5s on the first image vs 16ms steady state).
    - Warming up only the first image is not enough either: RapidOCR's cost depends
      on input size, so the first image at a new size is still slow (measured: 5.1s
      for the first 900x620 vs 2.0s steady state at the same size). Cross-image
      evaluation must warm up every image, otherwise the timing column produces a
      fake conclusion like "OCR takes 3 seconds".
    - Timings are trend-only. The official T_ocr value comes from
      `scripts/bench_ocr.py` (same size, repeated, take the min).
    """
    root = Path(gt_dir)
    image_root = Path(image_root)
    files = list(gt_files) if gt_files is not None else sorted(root.glob("*.json"))
    if not files:
        raise EvalError(f"no *.json annotation files found under {root}")

    pairs: list[tuple[GtImage, Path]] = []
    for gt_path in files:
        gt = load_gt(gt_path)
        pairs.append((gt, _resolve_image(image_root, gt, gt_path)))

    report = EvalReport(iou_threshold=iou_threshold, warmup_runs=max(0, warmup_runs))

    for gt, image_path in pairs:
        for _ in range(max(0, warmup_runs)):
            analyze_fn(str(image_path), gt.image_id)  # discarded; only warms this size

        result = analyze_fn(str(image_path), gt.image_id)
        result_warnings = list(getattr(result, "warnings", []) or [])
        row = match_image(gt, result.detections, iou_threshold=iou_threshold, kinds=kinds)
        row.warnings = result_warnings
        report.images.append(row)
        report.skipped.extend(row.skipped)

        for kind, ms in (getattr(result, "timings_ms", {}) or {}).items():
            report.timings_ms.setdefault(str(kind), []).append(float(ms))

    return report

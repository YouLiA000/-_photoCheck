#!/usr/bin/env python
"""Run detection metrics against annotations - the generator for R-02 baseline table A.

Ground truth comes from `samples/gt/*.json`, recorded by `make_sample.py` at draw
time rather than reverse-engineered from detector output.
Metrics: geometry recall (box hit) and type recall (correct subtype) are counted
separately; IoU defaults to 0.5.

Usage:
    python scripts/eval_detect.py                                  # evaluate every annotation under samples/gt
    python scripts/eval_detect.py --kinds text,qr                   # skip face
    python scripts/eval_detect.py --gt dataset/dev_gt --images dataset/dev --iou 0.5
    python scripts/eval_detect.py --json reports/eval.json --md reports/eval.md
    python scripts/eval_detect.py --strict                          # exit 1 on any miss/false alarm (CI)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from photocheck.detectors.a_engine.core.detect import ALL_KINDS, analyze  # noqa: E402
from photocheck.detectors.a_engine.core.eval import DEFAULT_IOU, EvalError, evaluate  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run detection metrics against annotations")
    parser.add_argument("--gt", default=str(ROOT / "samples" / "gt"), help="annotation directory")
    parser.add_argument(
        "--images", default=str(ROOT / "samples" / "synthetic"), help="image directory"
    )
    parser.add_argument("--iou", type=float, default=DEFAULT_IOU, help=f"IoU threshold, default {DEFAULT_IOU}")
    parser.add_argument(
        "--kinds", default=",".join(ALL_KINDS), help="detectors to evaluate, comma separated"
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="warmup passes per image, default 1; 0 = no warmup (timings then include model "
        "loading, only useful when checking recall)",
    )
    parser.add_argument("--json", default="", help="write metrics to JSON")
    parser.add_argument("--md", default="", help="write metrics to Markdown")
    parser.add_argument("--strict", action="store_true", help="return non-zero when anything is missed or extra")
    parser.add_argument("--quiet", action="store_true", help="do not print the detail table, only write files")
    args = parser.parse_args(argv)

    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    unknown = set(kinds) - set(ALL_KINDS)
    if unknown:
        print(f"[error] unknown detector(s): {sorted(unknown)}, allowed {list(ALL_KINDS)}", file=sys.stderr)
        return 2
    if not 0.0 < args.iou <= 1.0:
        print(f"[error] --iou must be in (0, 1], got {args.iou}", file=sys.stderr)
        return 2
    if args.warmup < 0:
        print(f"[error] --warmup cannot be negative, got {args.warmup}", file=sys.stderr)
        return 2

    try:
        report = evaluate(
            gt_dir=args.gt,
            image_root=args.images,
            analyze_fn=analyze,
            iou_threshold=args.iou,
            kinds=kinds,
            warmup_runs=args.warmup,
        )
    except EvalError as exc:
        print(f"[error] annotation problem: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    markdown = report.to_markdown()
    payload = report.to_dict()

    # Synthetic samples must declare their origin inside the artifact, so nobody
    # quotes these numbers as real-scene performance.
    payload["note"] = "合成样本（make_sample.py 生成），数字只证明管线连通，不代表真实场景能力"

    if args.json:
        _write(Path(args.json), json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    if args.md:
        _write(Path(args.md), markdown)

    # One-line summary: printed even with --quiet, otherwise the CI log holds only
    # an exit code and the failure cause is unrecoverable.
    print(
        f"[eval] {len(report.images)} image(s) / gt {report.gt_total} / "
        f"geometry recall {report.recall:.1%} / type recall {report.type_recall:.1%} / "
        f"false alarms {report.fp} ({report.fp_per_image:.2f} per image)"
    )
    if not args.quiet:
        print()
        print(markdown, end="")
        if args.json:
            print(f"\nJSON: {args.json}")
        if args.md:
            print(f"Markdown: {args.md}")

    if args.strict and (report.fn or report.fp):
        print(f"\n[strict] missed {report.fn} / false alarms {report.fp}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

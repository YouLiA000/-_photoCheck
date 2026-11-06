#!/usr/bin/env python
"""K-03 / W2 must-do: measure the T_ocr baseline.

The K-03 performance section fixes the procedure: **no fixed number is promised**.
W2 measures the baseline T_ocr first, and only then does the W4 acceptance line
become "per image <= T_ocr x 1.2". This script is what produces that number.

Outputs:
  1. Console table: per-image timing plus global percentiles
  2. reports/t_ocr_baseline_<date>.json: quotable by README / closing report
  3. Prints the W4 acceptance line (T_ocr x 1.2)

Privacy: the report holds **file name, size, timing, block count** only - never any
recognised text.

Usage:
    python scripts/bench_ocr.py ../../dataset/dev --limit 20 --repeat 3
    python scripts/bench_ocr.py a.jpg b.jpg --repeat 5
    python scripts/bench_ocr.py dataset/dev --single-scale   # timing of the fallback path
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from photocheck.detectors.a_engine.core.config import OcrConfig  # noqa: E402
from photocheck.detectors.a_engine.core.detect import ocr as ocr_mod  # noqa: E402

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic"}


def collect_files(inputs: list[str], limit: int) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES))
        elif path.is_file():
            files.append(path)
        else:
            print(f"[warn] skipping a path that does not exist: {path}", file=sys.stderr)
    return files[:limit] if limit and limit > 0 else files


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
    return ordered[idx]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="K-03 T_ocr baseline measurement (W2)")
    parser.add_argument("inputs", nargs="+", help="image directory or image files")
    parser.add_argument("--limit", type=int, default=0, help="max images to measure (0 = no limit)")
    parser.add_argument("--repeat", type=int, default=3, help="repeats per image, min is kept")
    parser.add_argument("--single-scale", dest="dual_scale", action="store_false", default=True,
                        help="disable dual-scale (measures the fallback path)")
    parser.add_argument("--out-dir", default="reports")
    args = parser.parse_args(argv)

    if not ocr_mod.warmup():
        print("[error] RapidOCR unavailable (dependency missing). Degraded: card unusable, README must say so.",
              file=sys.stderr)
        return 3

    files = collect_files(args.inputs, args.limit)
    if not files:
        print("[error] no images found", file=sys.stderr)
        return 2

    from PIL import Image, ImageOps

    cfg = OcrConfig(dual_scale=args.dual_scale)
    rows: list[dict[str, object]] = []
    print(f"{len(files)} image(s), {max(1, args.repeat)} repeat(s) each (min kept, jitter removed)\n")
    header = f"{'file':<28}{'size':>12}{'blocks':>8}{'min(ms)':>10}{'mean(ms)':>10}"
    print(header)
    print("-" * len(header))

    for path in files:
        try:
            with Image.open(path) as raw:
                image = ImageOps.exif_transpose(raw).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] cannot open {path.name}: {type(exc).__name__}", file=sys.stderr)
            continue

        ocr_mod.detect_text_blocks(image, cfg=cfg)  # one warmup pass, not timed
        samples: list[float] = []
        blocks = 0
        for _ in range(max(1, args.repeat)):
            started = time.perf_counter()
            blocks = len(ocr_mod.detect_text_blocks(image, cfg=cfg))
            samples.append((time.perf_counter() - started) * 1000.0)

        row = {
            "file": path.name,
            "width": image.width,
            "height": image.height,
            "blocks": blocks,
            "min_ms": round(min(samples), 1),
            "mean_ms": round(statistics.fmean(samples), 1),
        }
        rows.append(row)
        size = f"{row['width']}x{row['height']}"
        print(f"{str(row['file'])[:27]:<28}{size:>12}{blocks:>8}{row['min_ms']:>10}{row['mean_ms']:>10}")

    if not rows:
        print("[error] not a single image completed", file=sys.stderr)
        return 4

    mins = [float(r["min_ms"]) for r in rows]
    t_ocr = statistics.median(mins)
    target = t_ocr * 1.2

    try:
        import rapidocr_onnxruntime

        rapidocr_version = getattr(rapidocr_onnxruntime, "__version__", "unknown")
    except Exception:
        rapidocr_version = "unknown"

    summary = {
        "t_ocr_ms": round(t_ocr, 1),
        "w4_target_ms": round(target, 1),
        "samples": len(rows),
        "median_min_ms": round(statistics.median(mins), 1),
        "mean_min_ms": round(statistics.fmean(mins), 1),
        "p95_min_ms": round(_percentile(mins, 0.95), 1),
        "max_min_ms": round(max(mins), 1),
        "dual_scale": bool(args.dual_scale),
    }

    print("\n" + "=" * 46)
    print(f"T_ocr (median)          = {summary['t_ocr_ms']} ms  (n={summary['samples']} images)")
    print(f"p95                     = {summary['p95_min_ms']} ms")
    print(f"W4 acceptance T_ocr*1.2 = {summary['w4_target_ms']} ms")
    print("=" * 46)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"t_ocr_baseline_{datetime.now():%Y%m%d_%H%M}.json"
    payload = {
        "card": "K-03",
        "note": "只含文件名/尺寸/耗时，不含任何识别文字",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "env": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "rapidocr": rapidocr_version,
        },
        "config": {
            "min_score": cfg.min_score,
            "long_side": cfg.long_side,
            "dual_scale": cfg.dual_scale,
            "upscale": cfg.upscale,
        },
        "summary": summary,
        "rows": rows,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwritten {out_path}")
    print("Copy T_ocr and the W4 acceptance line into the README performance section.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

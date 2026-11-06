#!/usr/bin/env python
"""Smoke test: one image -> ImageDescriptor + Detection JSON (already v4-validated).

B's Friday smoke test and C's eval.py can consume the `--out` JSON directly.
This command line is only a shell; the real logic lives in `core.detect.analyze`.

Usage:
    python scripts/smoke_detect.py dataset/dev/001.jpg
    python scripts/smoke_detect.py 001.jpg --out out.json
    python scripts/smoke_detect.py 001.jpg --kinds text,qr      # skip face
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

from photocheck.detectors.a_engine.core.detect import ALL_KINDS, analyze, detector_status  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PhotoCheck detection smoke test")
    parser.add_argument("image", help="image path")
    parser.add_argument("--out", help="output JSON path (stdout when omitted)")
    parser.add_argument("--image-id", help="image_id stored in the record, defaults to the file name")
    parser.add_argument(
        "--kinds", default=",".join(ALL_KINDS), help="detectors to run, comma separated"
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=0,
        metavar="N",
        help="run N throwaway passes first so model loading does not land in timings_ms "
        "(use --warmup 1 on sample files)",
    )
    args = parser.parse_args(argv)

    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    unknown = set(kinds) - set(ALL_KINDS)
    if unknown:
        print(f"[error] unknown detector(s): {sorted(unknown)}, allowed {list(ALL_KINDS)}", file=sys.stderr)
        return 2

    try:
        for _ in range(max(0, args.warmup)):
            analyze(args.image, args.image_id, kinds=kinds)
        result = analyze(args.image, args.image_id, kinds=kinds)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2

    text = result.to_json()
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"written {out_path}", file=sys.stderr)
    else:
        print(text)

    status = detector_status()
    counts = result.counts_by_subtype
    print(
        f"[summary] image_id={result.image_descriptor['image_id']} "
        f"size={result.image_descriptor['width']}x{result.image_descriptor['height']} "
        f"detections={len(result.detections)} {counts or '{}'} "
        f"timings={result.timings_ms}",
        file=sys.stderr,
    )
    print(f"[detectors] {status}", file=sys.stderr)
    for warning in result.warnings:
        print(f"[warn] {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

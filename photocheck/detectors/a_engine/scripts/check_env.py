#!/usr/bin/env python
"""Environment self-check: one command that answers "can this machine run A?".

Why this exists
---------------
The two failures that cost the most time in this project were both environment
problems that looked like code problems:

1. The venv lived on a path containing non-ASCII characters, so mediapipe's
   native layer could not open its graph file. The detector reported zero faces
   and looked broken.
2. Two OpenCV distributions were installed at once. They write the same `cv2`
   directory, so `cv2.__version__` and the actual wheel contents disagreed and
   every reproduction was unreliable.

Both are invisible from the detector API, so they get their own check.

Exit code: 0 = usable, 1 = something is wrong, 2 = argument error.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OPENCV_DISTS = (
    "opencv-python",
    "opencv-contrib-python",
    "opencv-python-headless",
    "opencv-contrib-python-headless",
)
EXPECTED_CV2 = "4.10.0"


def _dist_version(name: str) -> str | None:
    try:
        return md.version(name)
    except md.PackageNotFoundError:
        return None


def check_python(problems: list[str], warnings: list[str]) -> None:
    major_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    ok = (sys.version_info.major, sys.version_info.minor) == (3, 11)
    print(f"[{'OK ' if ok else 'WARN'}] python {sys.version.split()[0]} ({major_minor})")
    if not ok:
        warnings.append(
            f"Python {major_minor} is not 3.11. mediapipe / rapidocr have no wheels "
            "for 3.13+ on Windows."
        )


def check_ascii_path(problems: list[str]) -> None:
    exe = Path(sys.executable).resolve()
    bad = [part for part in exe.parts if not part.isascii()]
    ok = not bad
    print(f"[{'OK ' if ok else 'FAIL'}] venv path is ASCII: {exe.parent}")
    if not ok:
        example = "C:/venvs/photocheck"
        problems.append(
            f"venv path contains non-ASCII characters: {bad}. mediapipe cannot open "
            f"its graph file there and K-07 silently reports zero faces. "
            f"Recreate the venv on a pure ASCII path, e.g. {example}."
        )


def check_opencv(problems: list[str], warnings: list[str]) -> None:
    installed = {name: _dist_version(name) for name in OPENCV_DISTS}
    present = {name: ver for name, ver in installed.items() if ver}

    print(f"[----] OpenCV distributions: {present or 'none'}")
    if len(present) != 1:
        problems.append(
            f"expected exactly one OpenCV distribution, found {sorted(present)}. "
            "Two wheels writing the same cv2 namespace makes the effective version "
            "unpredictable. Keep opencv-contrib-python and uninstall the rest: "
            "uv pip uninstall opencv-python"
        )

    try:
        import cv2
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] import cv2 -> {type(exc).__name__}: {exc}")
        problems.append("cv2 cannot be imported")
        return

    version = getattr(cv2, "__version__", "unknown")
    ok = len(present) == 1 and version.startswith(EXPECTED_CV2)
    print(f"[{'OK ' if ok else 'WARN'}] cv2 {version} at {Path(cv2.__file__).parent}")
    if not ok and version and not version.startswith(EXPECTED_CV2):
        warnings.append(f"cv2 {version} != expected {EXPECTED_CV2}")

    needs = {
        "QRCodeDetector": hasattr(cv2, "QRCodeDetector"),
        "QRCodeEncoder_create": hasattr(cv2, "QRCodeEncoder_create"),
    }
    missing = [name for name, present_ in needs.items() if not present_]
    print(f"[{'OK ' if not missing else 'FAIL'}] cv2 symbols: {', '.join(needs)}")
    if missing:
        problems.append(f"cv2 is missing {missing}; the contrib wheel provides them")


def check_detectors(problems: list[str], warnings: list[str]) -> None:
    try:
        from photocheck.detectors.a_engine.core.detect import detector_status
    except Exception as exc:  # noqa: BLE001
        print(f"[FAIL] import core.detect -> {type(exc).__name__}: {exc}")
        problems.append("the detection package cannot be imported")
        return

    status = detector_status()
    for key, value in status.items():
        print(f"[----] detector {key}: {value}")

    # `qr_backend == cv2` is not fatal, but it silently reduces capability.
    if status.get("qr_backend") == "cv2":
        message = (
            "QR runs on the cv2 fallback: QR codes only, 1D barcodes are NOT "
            "supported. The pyzbar DLL failed to load (BC-0008)."
        )
        print(f"[WARN] {message}")
        warnings.append(message)
    for key in ("ocr", "qr", "face"):
        if status.get(key) != "ok":
            problems.append(f"detector {key} is unavailable: {status.get(key)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="check that this machine can run the A engine")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat warnings as failures too (use in CI)",
    )
    args = parser.parse_args(argv)

    problems: list[str] = []
    warnings: list[str] = []
    check_python(problems, warnings)
    check_ascii_path(problems)
    check_opencv(problems, warnings)
    check_detectors(problems, warnings)

    if not problems and not warnings:
        print("\n[env] environment OK")
        return 0

    if problems:
        print(f"\n[env] {len(problems)} blocking problem(s):")
        for i, item in enumerate(problems, start=1):
            print(f"  {i}. {item}")
    if warnings:
        print(f"\n[env] {len(warnings)} warning(s):")
        for i, item in enumerate(warnings, start=1):
            print(f"  {i}. {item}")

    if problems:
        return 1
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())

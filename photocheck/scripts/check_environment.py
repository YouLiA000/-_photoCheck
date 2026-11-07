"""Preflight check for Python, OpenCV, ExifTool and all PhotoCheck detectors."""

from __future__ import annotations

import importlib.metadata as metadata
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from photocheck.core import MetadataScanError, exiftool_version
from photocheck.detectors import a_detector_status

OPENCV_DISTRIBUTIONS = (
    "opencv-python",
    "opencv-contrib-python",
    "opencv-python-headless",
    "opencv-contrib-python-headless",
)
EXPECTED_EXIFTOOL_VERSION = "13.61"


def _distribution_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def assess_detector_status(status: dict[str, str]) -> tuple[list[str], list[str]]:
    """Split P0 detector failures from the optional face capability."""

    problems: list[str] = []
    warnings: list[str] = []
    for name in ("ocr", "qr"):
        if status.get(name) != "ok":
            problems.append(f"detector {name} unavailable: {status.get(name)}")
    if status.get("face") != "ok":
        warnings.append(
            "detector face unavailable: K-07 uses not_applicable and manual boxes"
        )
    return problems, warnings


def main() -> int:
    problems: list[str] = []
    warnings: list[str] = []

    print(f"[python] {sys.version.split()[0]} ({sys.executable})")
    if sys.version_info[:2] != (3, 11):
        problems.append("Python 3.11 is required")

    installed = {
        name: version
        for name in OPENCV_DISTRIBUTIONS
        if (version := _distribution_version(name)) is not None
    }
    print(f"[opencv] {installed}")
    if set(installed) != {"opencv-contrib-python"}:
        problems.append("exactly one OpenCV distribution is required: opencv-contrib-python")

    import cv2

    print(f"[cv2] {cv2.__version__} ({cv2.__file__})")
    if not cv2.__version__.startswith("4.10.0"):
        problems.append(f"expected cv2 4.10.0, found {cv2.__version__}")

    try:
        version = exiftool_version()
        print(f"[exiftool] {version}")
        if version != EXPECTED_EXIFTOOL_VERSION:
            problems.append(
                f"ExifTool {EXPECTED_EXIFTOOL_VERSION} is required, found {version}"
            )
    except MetadataScanError as exc:
        print(f"[exiftool] unavailable: {exc}")
        problems.append("ExifTool is required for metadata detection and export verification")

    try:
        status = a_detector_status()
        print(f"[detectors] {status}")
        detector_problems, detector_warnings = assess_detector_status(status)
        problems.extend(detector_problems)
        warnings.extend(detector_warnings)
    except Exception as exc:
        print(f"[detectors] unavailable: {type(exc).__name__}: {exc}")
        problems.append("A detector engine cannot be imported")

    if problems:
        print("\n[environment] FAIL")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    if warnings:
        print(f"\n[environment] OK ({len(warnings)} warning)")
        for warning in warnings:
            print(f"  - {warning}")
    else:
        print("\n[environment] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Vendored detector engine delivered by team A.

The implementation keeps A's internal package boundary under ``core`` while
exposing the three runtime entry points used by B.
"""

from .core.detect import (
    ALL_KINDS,
    AnalysisResult,
    RegionProbe,
    analyze,
    classify,
    detector_status,
    probe_region,
)

__all__ = [
    "ALL_KINDS",
    "AnalysisResult",
    "RegionProbe",
    "analyze",
    "classify",
    "detector_status",
    "probe_region",
]

"""Compatibility shim: B's delivery checker looks for `core/detect/config.py`.

The implementation is NOT here, it stays in `core/config.py`. This forwarder
exists so both path conventions work without a second copy of the parameters.
Two copies of a threshold table inevitably drift apart during tuning.
"""

from __future__ import annotations

from ..config import (  # noqa: F401
    DEFAULT_CONFIG,
    DetectConfig,
    FaceConfig,
    OcrConfig,
    QrConfig,
)

__all__ = ["OcrConfig", "QrConfig", "FaceConfig", "DetectConfig", "DEFAULT_CONFIG"]

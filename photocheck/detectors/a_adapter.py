"""Validate and isolate runtime envelopes produced by detector side A."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from photocheck.contract import validate_records as validate_b_records

from . import a_contract

_ENVELOPE_KEYS = {
    "image_descriptor",
    "detections",
    "warnings",
    "timings_ms",
}


class AAdapterError(ValueError):
    """Raised when an A runtime envelope cannot enter the B pipeline."""


@dataclass(frozen=True)
class AEnvelope:
    image_descriptor: dict[str, Any]
    detections: tuple[dict[str, Any], ...]
    warnings: tuple[str, ...]
    timings_ms: Mapping[str, float]

    @property
    def records(self) -> list[dict[str, Any]]:
        return [dict(self.image_descriptor), *(dict(item) for item in self.detections)]


def analyze_a(image: Any, image_id: str | None = None, **kwargs: Any) -> AEnvelope:
    """Run the vendored A engine and validate its envelope before returning it."""

    from .a_engine import analyze

    result = analyze(image, image_id, **kwargs)
    payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
    return parse_a_envelope(payload)


def probe_a_region(
    image: Any,
    bbox: list[int] | tuple[int, int, int, int],
    **kwargs: Any,
) -> dict[str, Any]:
    """Run A's detector probe on a final output file or in-memory image."""

    from .a_engine import probe_region

    result = probe_region(image, bbox, **kwargs)
    return result.to_dict() if hasattr(result, "to_dict") else dict(result)


def a_detector_status() -> dict[str, str]:
    """Report availability of the vendored A engine and its QR backend."""

    from .a_engine import detector_status

    return detector_status()


def load_a_envelope(path: str | Path) -> AEnvelope:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AAdapterError("A envelope is not readable JSON") from exc
    return parse_a_envelope(payload)


def parse_a_envelope(payload: Mapping[str, Any]) -> AEnvelope:
    """Validate with A's strict models and B's full v4 Schema."""

    if not isinstance(payload, Mapping):
        raise AAdapterError("A envelope must be a JSON object")
    unknown = set(payload) - _ENVELOPE_KEYS
    if unknown:
        raise AAdapterError(f"A envelope contains unknown fields: {sorted(unknown)}")

    descriptor = payload.get("image_descriptor")
    detections = payload.get("detections")
    warnings = payload.get("warnings", [])
    timings = payload.get("timings_ms", {})
    if not isinstance(descriptor, Mapping):
        raise AAdapterError("image_descriptor must be an object")
    if not isinstance(detections, list) or not all(
        isinstance(item, Mapping) for item in detections
    ):
        raise AAdapterError("detections must be an object array")
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        raise AAdapterError("warnings must be a string array")
    if not isinstance(timings, Mapping):
        raise AAdapterError("timings_ms must be an object")
    normalized_timings: dict[str, float] = {}
    for name, value in timings.items():
        if not isinstance(name, str) or isinstance(value, bool) or not isinstance(
            value, (int, float)
        ):
            raise AAdapterError("timings_ms must map strings to numbers")
        if float(value) < 0:
            raise AAdapterError("timing values cannot be negative")
        normalized_timings[name] = float(value)

    descriptor = dict(descriptor)
    detections = tuple(dict(item) for item in detections)
    records = [descriptor, *detections]
    try:
        a_contract.validate_records(records)
        validate_b_records(records)
    except Exception as exc:
        name = type(exc).__name__
        raise AAdapterError(f"A envelope failed {name}: {exc}") from exc

    return AEnvelope(
        image_descriptor=descriptor,
        detections=detections,
        warnings=tuple(warnings),
        timings_ms=normalized_timings,
    )


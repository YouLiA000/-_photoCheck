"""Detector-side integration adapters."""

from .a_adapter import (
    AAdapterError,
    AEnvelope,
    a_detector_status,
    analyze_a,
    load_a_envelope,
    parse_a_envelope,
    probe_a_region,
)
from .delivery_check import ADeliveryReport, inspect_a_delivery

__all__ = [
    "AAdapterError",
    "ADeliveryReport",
    "AEnvelope",
    "a_detector_status",
    "analyze_a",
    "inspect_a_delivery",
    "load_a_envelope",
    "parse_a_envelope",
    "probe_a_region",
]


"""Detector-side integration adapters."""

from .a_adapter import AAdapterError, AEnvelope, load_a_envelope, parse_a_envelope
from .delivery_check import ADeliveryReport, inspect_a_delivery

__all__ = [
    "AAdapterError",
    "ADeliveryReport",
    "AEnvelope",
    "inspect_a_delivery",
    "load_a_envelope",
    "parse_a_envelope",
]


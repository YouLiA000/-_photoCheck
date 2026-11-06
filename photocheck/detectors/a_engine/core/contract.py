"""PhotoCheck shared contract v4: record types and hard validation.

A produces ImageDescriptor / Detection only. The full contract is spec v1.4
section 0.2; the machine-checkable form is photocheck-v4.schema.json.

This module turns the red lines that people break most often into checks that
raise, because "remember not to do that" does not survive a deadline:

1. Unknown fields are rejected (`from_dict` is strict).
2. `evidence` is derived from `kind`, never supplied by the caller.
3. `details` keys are whitelisted per kind/subtype; raw text, payloads and EXIF
   values cannot enter.
4. `meta` must have `bbox = null`; everything else needs a positive width/height.
5. `id` is unique within one `image_id`; a full snapshot holds one descriptor.
6. `masked_preview` follows a fixed mask format for phone/ID card (the ID card
   mask allows a trailing X); `meta` has no fixed format and falls back to
   "no run of 7 or more digits".
7. QR details accept only the typed `safe_domain` / `safe_ssid`, never a free-form
   `summary`.
8. On a full snapshot, every `bbox` must lie inside the descriptor's working image.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Mapping

CONTRACT_VERSION = "photocheck/v4"

BBox = tuple[int, int, int, int]

# kind -> allowed subtypes (v4 enum; do not add or remove entries)
KIND_SUBTYPES: dict[str, tuple[str, ...]] = {
    "meta": ("gps", "datetime", "device", "serial", "thumbnail", "software"),
    "text": ("phone", "idcard"),
    "qr": (
        "qr_wechat_card",
        "qr_wechat_group",
        "qr_wechat_pay",
        "qr_alipay",
        "qr_wifi",
        "qr_vcard",
        "qr_contact",
        "qr_geo",
        "qr_code",
        "qr_link",
        "qr_unknown",
    ),
    "face": ("face_region",),
}

# evidence is derived from kind here; callers must not pass it
EVIDENCE_BY_KIND: dict[str, str] = {
    "meta": "exif",
    "text": "ocr_rule",
    "qr": "qr_payload",
    "face": "face_box",
}

_META_KEYS = frozenset({"masked_preview"})
_TEXT_PHONE_KEYS = frozenset({"masked_preview"})
_TEXT_IDCARD_KEYS = frozenset({"masked_preview", "idcard_check"})
_QR_KEYS = frozenset({"decodable", "safe_domain", "safe_ssid"})
_FACE_KEYS: frozenset[str] = frozenset()

# Any of these means someone pushed plaintext into a serialisable record
FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "text",
        "raw_text",
        "original",
        "payload",
        "raw_payload",
        "qr_payload",
        "raw_exif",
        "exif",
        "text_ref",
        "payload_ref",
        "summary",
        "value",
    }
)

IDCARD_CHECK_VALUES = ("pass", "fail", "na")

# Phone / ID card are whitelisted by mask shape instead of guessing from length
_PHONE_MASK = re.compile(r"^(?:\+?86[\s-]?)?1[3-9]\d\*{4}\d{4}$")
# Spec line 416: 18 chars, last char may be X. The mask keeps the first 4 and
# last 4, so a trailing X is legal.
_IDCARD_MASK = re.compile(r"^\d{4}\*{10}(?:\d{4}|\d{3}X)$")
# meta only: no fixed format to whitelist, so the rule is "no run of 7+ digits".
# Checked on the RAW string without stripping separators; stripping turns
# 2024-06-01 into 8 digits and rejects a perfectly masked date.
_UNSAFE_RAW_DIGITS = re.compile(r"\d{7,}")
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_SUMMARY_MAX_LEN = 64


class ContractError(ValueError):
    """A v4 contract violation."""


def allowed_detail_keys(kind: str, subtype: str) -> frozenset[str]:
    if kind == "meta":
        return _META_KEYS
    if kind == "text":
        if subtype == "phone":
            return _TEXT_PHONE_KEYS
        if subtype == "idcard":
            return _TEXT_IDCARD_KEYS
    if kind == "qr":
        allowed = {"decodable"}
        if subtype == "qr_wifi":
            allowed.add("safe_ssid")
        elif subtype in {
            "qr_wechat_card",
            "qr_wechat_group",
            "qr_wechat_pay",
            "qr_alipay",
            "qr_geo",
            "qr_link",
        }:
            allowed.add("safe_domain")
        return frozenset(allowed)
    if kind == "face":
        return _FACE_KEYS
    raise ContractError(f"unknown kind/subtype: {kind}/{subtype}")


def required_detail_keys(kind: str, subtype: str) -> frozenset[str]:
    if kind == "text" and subtype == "idcard":
        return frozenset({"idcard_check"})
    if kind == "qr":
        return frozenset({"decodable"})
    return frozenset()


def _check_bbox(bbox: Any, kind: str, where: str) -> BBox | None:
    if kind == "meta":
        if bbox is not None:
            raise ContractError(f"{where}: bbox must be null when kind=meta, got {bbox!r}")
        return None
    if bbox is None:
        raise ContractError(f"{where}: bbox must not be null when kind={kind}")
    if not isinstance(bbox, (tuple, list)) or len(bbox) != 4:
        raise ContractError(f"{where}: bbox must be [x, y, width, height], got {bbox!r}")
    vals = []
    for v in bbox:
        if isinstance(v, bool) or not isinstance(v, (int,)):
            raise ContractError(f"{where}: bbox must use integer coordinates, got {bbox!r}")
        vals.append(int(v))
    x, y, w, h = vals
    if w <= 0 or h <= 0:
        raise ContractError(f"{where}: bbox width and height must be positive, got {bbox!r}")
    if x < 0 or y < 0:
        raise ContractError(f"{where}: bbox origin must not be negative, got {bbox!r}")
    return (x, y, w, h)


def _check_details(kind: str, subtype: str, details: Any, where: str) -> dict[str, Any]:
    if details is None:
        details = {}
    if not isinstance(details, Mapping):
        raise ContractError(f"{where}: details must be an object, got {type(details).__name__}")

    keys = set(details)
    leaked = keys & FORBIDDEN_DETAIL_KEYS
    if leaked:
        raise ContractError(
            f"{where}: details must not contain plaintext fields {sorted(leaked)}; "
            "raw text / payload / EXIF may only live in the SecretStore"
        )

    allowed = allowed_detail_keys(kind, subtype)
    unknown = keys - allowed
    if unknown:
        raise ContractError(
            f"{where}: unknown field(s) {sorted(unknown)} in details for {kind}/{subtype}, "
            f"allowed {sorted(allowed)}"
        )

    missing = required_detail_keys(kind, subtype) - keys
    if missing:
        raise ContractError(f"{where}: missing required details for {kind}/{subtype}: {sorted(missing)}")

    out: dict[str, Any] = {}
    for k, v in details.items():
        if k == "idcard_check":
            if v not in IDCARD_CHECK_VALUES:
                raise ContractError(f"{where}: idcard_check must be one of {IDCARD_CHECK_VALUES}, got {v!r}")
        elif k == "decodable":
            if not isinstance(v, bool):
                raise ContractError(f"{where}: decodable must be a boolean, got {v!r}")
        elif k == "safe_domain":
            if not isinstance(v, str) or not v.strip():
                raise ContractError(f"{where}: safe_domain must be a non-empty string, got {v!r}")
            out[k] = _normalize_domain(v, where)
            continue
        elif k == "safe_ssid":
            if not isinstance(v, str) or not v:
                raise ContractError(f"{where}: safe_ssid must be a non-empty string, got {v!r}")
            if len(v) > _SUMMARY_MAX_LEN:
                raise ContractError(f"{where}: safe_ssid exceeds {_SUMMARY_MAX_LEN} characters")
            if any(ord(char) < 32 for char in v):
                raise ContractError(f"{where}: safe_ssid must not contain control characters")
        elif k == "masked_preview":
            if not isinstance(v, str) or not v:
                raise ContractError(f"{where}: masked_preview must be a non-empty string, got {v!r}")
            if len(v) > _SUMMARY_MAX_LEN:
                raise ContractError(f"{where}: masked_preview exceeds {_SUMMARY_MAX_LEN} characters")
            if kind == "text" and subtype == "phone":
                if not _PHONE_MASK.fullmatch(v):
                    raise ContractError(
                        f"{where}: phone masked_preview must look like 138****8000 "
                        f"(or +86138****8000 with a country code), got {v!r}"
                    )
            elif kind == "text" and subtype == "idcard":
                # Upper-case the trailing X before matching so a hand-written
                # lowercase x is not rejected for the wrong reason.
                v = v.upper()
                if not _IDCARD_MASK.fullmatch(v):
                    raise ContractError(
                        f"{where}: idcard masked_preview must look like 1101**********0011 "
                        f"(last character may be X), got {v!r}"
                    )
            elif kind == "meta":
                # No fixed format for meta, so the fallback rule is "no long digit
                # run". Evaluated on the raw string with separators intact,
                # otherwise the date 2024-06-01 is rejected as unmasked.
                if _UNSAFE_RAW_DIGITS.search(v):
                    raise ContractError(
                        f"{where}: meta masked_preview contains 7+ consecutive digits, "
                        f"looks unmasked: {v!r}"
                    )
        out[k] = v
    return out


def _normalize_domain(value: str, where: str) -> str:
    candidate = value.strip().rstrip(".").lower()
    if any(ord(char) < 32 or char.isspace() for char in candidate):
        raise ContractError(f"{where}: safe_domain must not contain whitespace or control characters")
    if any(char in candidate for char in "/\\@:;?#%&=+"):
        raise ContractError(f"{where}: safe_domain must be a bare domain, no scheme, path or query")
    try:
        ascii_domain = candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ContractError(f"{where}: safe_domain is not a valid domain: {value!r}") from exc
    labels = ascii_domain.split(".")
    if len(ascii_domain) > 253 or len(labels) < 2 or any(
        not _DOMAIN_LABEL.fullmatch(label) for label in labels
    ):
        raise ContractError(f"{where}: safe_domain is not a valid domain: {value!r}")
    return ascii_domain


@dataclass(frozen=True)
class Detection:
    """An immutable detection fact. No user choice, no verification state, no raw value."""

    id: str
    image_id: str
    kind: str
    subtype: str
    bbox: BBox | None = None
    detector_score: float | None = None
    risk: int = 1
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _ID_PATTERN.fullmatch(self.id):
            raise ContractError(
                f"invalid Detection.id: {self.id!r} (alphanumerics and _.:- only, length 1-128)"
            )
        if not isinstance(self.image_id, str) or not _ID_PATTERN.fullmatch(self.image_id):
            raise ContractError("Detection.image_id must satisfy the v4 Identifier rule")
        if self.kind not in KIND_SUBTYPES:
            raise ContractError(f"unknown kind: {self.kind!r}, allowed {sorted(KIND_SUBTYPES)}")
        if self.subtype not in KIND_SUBTYPES[self.kind]:
            raise ContractError(f"kind={self.kind} does not allow subtype={self.subtype!r}")
        if isinstance(self.risk, bool) or self.risk not in (1, 2, 3):
            raise ContractError(f"risk must be 1, 2 or 3, got {self.risk!r}")
        if self.detector_score is not None:
            if isinstance(self.detector_score, bool) or not isinstance(self.detector_score, (int, float)):
                raise ContractError(f"detector_score must be a number or null, got {self.detector_score!r}")
            if not (0.0 <= float(self.detector_score) <= 1.0):
                raise ContractError(f"detector_score must be within 0..1, got {self.detector_score!r}")

        object.__setattr__(self, "bbox", _check_bbox(self.bbox, self.kind, f"Detection({self.id}).bbox"))
        object.__setattr__(
            self,
            "details",
            # Read-only view. Pushing raw_text in after construction raises
            # TypeError on the spot, instead of quietly carrying plaintext into
            # the snapshot.
            MappingProxyType(
                _check_details(self.kind, self.subtype, self.details, f"Detection({self.id}).details")
            ),
        )
        if self.detector_score is not None:
            object.__setattr__(self, "detector_score", float(self.detector_score))

    @property
    def evidence(self) -> str:
        return EVIDENCE_BY_KIND[self.kind]

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "record_type": "Detection",
            "id": self.id,
            "image_id": self.image_id,
            "kind": self.kind,
            "subtype": self.subtype,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "detector_score": self.detector_score,
            "evidence": self.evidence,
            "risk": self.risk,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Detection":
        expected = {
            "contract_version",
            "record_type",
            "id",
            "image_id",
            "kind",
            "subtype",
            "bbox",
            "detector_score",
            "evidence",
            "risk",
            "details",
        }
        unknown = set(data) - expected
        if unknown:
            raise ContractError(f"Detection has unknown field(s) {sorted(unknown)}")
        missing = expected - set(data)
        if missing:
            raise ContractError(f"Detection is missing field(s) {sorted(missing)}")
        if data["contract_version"] != CONTRACT_VERSION:
            raise ContractError(
                f"contract_version must be {CONTRACT_VERSION}, got {data['contract_version']!r}"
            )
        if data["record_type"] != "Detection":
            raise ContractError(f"record_type must be Detection, got {data['record_type']!r}")
        kind = data["kind"]
        if kind in EVIDENCE_BY_KIND and data["evidence"] != EVIDENCE_BY_KIND[kind]:
            raise ContractError(
                f"evidence does not match kind: kind={kind} requires "
                f"{EVIDENCE_BY_KIND[kind]}, got {data['evidence']!r}"
            )
        bbox = data["bbox"]
        return cls(
            id=data["id"],
            image_id=data["image_id"],
            kind=kind,
            subtype=data["subtype"],
            bbox=bbox,
            detector_score=data["detector_score"],
            risk=data["risk"],
            details=data["details"] or {},
        )


@dataclass(frozen=True)
class ImageDescriptor:
    """Describes the normalised working image.

    Field definitions follow B's K-01 and photocheck-v4.schema.json. This class
    validates the minimum needed for A to test without B's module present.
    """

    image_id: str
    width: int
    height: int
    orientation: str = "exif_transposed"
    coordinate_space: str = "top_left_pixels"

    def __post_init__(self) -> None:
        if not isinstance(self.image_id, str) or not _ID_PATTERN.fullmatch(self.image_id):
            raise ContractError("ImageDescriptor.image_id must satisfy the v4 Identifier rule")
        if isinstance(self.width, bool) or not isinstance(self.width, int) or self.width <= 0:
            raise ContractError(f"ImageDescriptor.width must be a positive integer, got {self.width!r}")
        if isinstance(self.height, bool) or not isinstance(self.height, int) or self.height <= 0:
            raise ContractError(f"ImageDescriptor.height must be a positive integer, got {self.height!r}")
        if self.coordinate_space != "top_left_pixels":
            raise ContractError(f"coordinate_space is fixed to top_left_pixels, got {self.coordinate_space!r}")
        if self.orientation != "exif_transposed":
            raise ContractError(
                f"orientation is fixed to exif_transposed, got {self.orientation!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTRACT_VERSION,
            "record_type": "ImageDescriptor",
            "image_id": self.image_id,
            "width": self.width,
            "height": self.height,
            "orientation": self.orientation,
            "coordinate_space": self.coordinate_space,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ImageDescriptor":
        expected = {
            "contract_version",
            "record_type",
            "image_id",
            "width",
            "height",
            "orientation",
            "coordinate_space",
        }
        unknown = set(data) - expected
        if unknown:
            raise ContractError(f"ImageDescriptor has unknown field(s) {sorted(unknown)}")
        missing = expected - set(data)
        if missing:
            raise ContractError(f"ImageDescriptor is missing field(s) {sorted(missing)}")
        if data["contract_version"] != CONTRACT_VERSION:
            raise ContractError(
                f"contract_version must be {CONTRACT_VERSION}, got {data['contract_version']!r}"
            )
        if data["record_type"] != "ImageDescriptor":
            raise ContractError(
                f"record_type must be ImageDescriptor, got {data['record_type']!r}"
            )
        return cls(
            image_id=data["image_id"],
            width=data["width"],
            height=data["height"],
            orientation=data["orientation"],
            coordinate_space=data["coordinate_space"],
        )


def validate_records(records: Iterable[Mapping[str, Any]]) -> None:
    """Validate a full v4 snapshot. A Detection-only list is also accepted."""
    records = list(records)
    descriptors: list[ImageDescriptor] = []
    detections: list[Detection] = []
    seen: dict[str, set[str]] = {}
    for i, rec in enumerate(records):
        rec_type = rec.get("record_type")
        if rec_type == "Detection":
            detections.append(Detection.from_dict(rec))
        elif rec_type == "ImageDescriptor":
            descriptors.append(ImageDescriptor.from_dict(rec))
        else:
            raise ContractError(
                f"records[{i}] is neither a Detection nor an ImageDescriptor "
                f"(record_type={rec_type!r})"
            )
    if len(descriptors) > 1:
        raise ContractError("a validation snapshot may contain at most one ImageDescriptor")
    expected_image_id = descriptors[0].image_id if descriptors else None
    descriptor = descriptors[0] if descriptors else None
    for det in detections:
        if expected_image_id is not None and det.image_id != expected_image_id:
            raise ContractError(
                f"Detection.image_id={det.image_id} does not match the ImageDescriptor"
            )
        # Cross-record invariant: bbox must lie inside the working image. K-09
        # crops by bbox, so an out-of-range box crops to nothing and silently
        # reads as "no residual in this region".
        if descriptor is not None and det.bbox is not None:
            x, y, w, h = det.bbox
            if x + w > descriptor.width or y + h > descriptor.height:
                raise ContractError(
                    f"{det.id}: bbox={list(det.bbox)} lies outside the working image "
                    f"{descriptor.width}x{descriptor.height}"
                )
        bucket = seen.setdefault(det.image_id, set())
        if det.id in bucket:
            raise ContractError(f"duplicate id within image_id={det.image_id}: {det.id}")
        bucket.add(det.id)


__all__ = [
    "CONTRACT_VERSION",
    "BBox",
    "KIND_SUBTYPES",
    "EVIDENCE_BY_KIND",
    "IDCARD_CHECK_VALUES",
    "FORBIDDEN_DETAIL_KEYS",
    "ContractError",
    "Detection",
    "ImageDescriptor",
    "allowed_detail_keys",
    "required_detail_keys",
    "validate_records",
]

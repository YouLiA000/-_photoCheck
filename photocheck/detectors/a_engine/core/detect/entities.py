"""K-04 sensitive entity detection (owner: A). Two base types: phone, ID card.

Narrowed to these two on purpose: the time saved goes into threshold tuning and
negative-sample testing, which is where the accuracy actually comes from.

The important v1.3 change is the three-state ID-card checksum. A number that
fails the checksum still has to be reported, because a one-digit typo leaks the
same person; it is only downgraded to risk 2 with
`idcard_check = fail` so the UI can say "looks like an ID, checksum failed".

Three implementation rules:
1. Matching runs on NORMALISED text (full-width to half-width, separators
   removed) but bboxes must map back to the ORIGINAL character positions;
2. plaintext goes only into the SecretStore; serialisable records carry
   `masked_preview` and nothing else;
3. the ID-card context keyword requirement is a switch, not hard-coded, because
   K-04's fallback needs to tighten it when false positives are high.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from ..config import DEFAULT_CONFIG, OcrConfig
from ..contract import BBox, Detection
from ..secret_store import SecretStore
from .ocr import TextBlock

__all__ = [
    "EntityMatch",
    "PHONE_RE",
    "IDCARD_RE",
    "IDCARD_CONTEXT_KEYWORDS",
    "normalize_with_index",
    "idcard_check",
    "mask_phone",
    "mask_idcard",
    "find_entities",
    "scan_text",
    "blocks_to_detections",
]

# Phone: optional +86 / 0086 country code, then 1[3-9] and 9 digits.
PHONE_RE = re.compile(r"(?<!\d)(?:(?:\+86|0086)1[3-9]\d{9}|1[3-9]\d{9})(?!\d)")
# ID card: 18 chars, last may be X. The checksum is evaluated separately, never
# as part of the match, so a typo is still reported instead of silently dropped.
IDCARD_RE = re.compile(r"(?<!\d)\d{17}[\dX](?!\d)")

IDCARD_CONTEXT_KEYWORDS = ("身份证", "公民身份号码", "身份号码", "证件号", "有效期限")

# Separators dropped during normalisation (spec allows spaces and hyphens)
_SEPARATORS = {" ", "\t", "\u3000", "-", "_", "－", "—", "·", "."}

ISO7064_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
ISO7064_CODES = "10X98765432"

RISK_BY_IDCARD_CHECK = {"pass": 3, "fail": 2, "na": 2}
PHONE_RISK = 2


@dataclass(frozen=True)
class EntityMatch:
    subtype: str
    value: str  # normalised plaintext; SecretStore only
    start: int  # char index in the original text (inclusive)
    end: int  # char index in the original text (inclusive)
    check: str = "na"  # idcard: pass / fail / na；phone: na


def normalize_with_index(text: str) -> tuple[str, list[int]]:
    """Full-width to half-width, drop separators, and keep the mapping
    normalised[i] -> original[idx[i]] so bboxes can be mapped back."""
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        code = ord(ch)
        if 0xFF01 <= code <= 0xFF5E:  # full-width ASCII
            ch = chr(code - 0xFEE0)
        elif code == 0x3000:  # ideographic space
            ch = " "
        if ch in _SEPARATORS:
            continue
        out.append(ch.upper())
        index.append(i)
    return "".join(out), index


def idcard_check(number: str) -> str:
    """ISO 7064:1983 MOD 11-2 checksum. Returns pass / fail / na."""
    n = (number or "").strip().upper()
    if len(n) != 18 or not re.fullmatch(r"\d{17}[\dX]", n):
        return "na"
    total = sum(int(c) * w for c, w in zip(n[:17], ISO7064_WEIGHTS))
    return "pass" if ISO7064_CODES[total % 11] == n[17] else "fail"


def _idcard_birth_date_valid(number: str) -> bool:
    try:
        birthday = datetime.strptime(number[6:14], "%Y%m%d")
    except (TypeError, ValueError):
        return False
    return 1800 <= birthday.year <= 2100


def mask_phone(value: str) -> str:
    """138****8000.

    Strip the +86 / 0086 country code first. Masking before stripping hides the
    country code and leaves the 8-digit subscriber prefix exposed instead.
    """
    v = value.strip()
    digits = re.sub(r"[\s\-]", "", v)
    if digits.startswith("+86"):
        digits = digits[3:]
    elif digits.startswith("0086"):
        digits = digits[4:]
    elif digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return f"{digits[:3]}****{digits[-4:]}" if len(digits) >= 8 else "*" * len(digits)


def mask_idcard(value: str) -> str:
    """1101**********0011. The trailing X is upper-cased: the contract's mask
    pattern only accepts an upper-case X."""
    v = value.strip()
    return f"{v[:4]}{'*' * (len(v) - 8)}{v[-4:].upper()}" if len(v) > 8 else "*" * len(v)


def find_entities(text: str) -> list[EntityMatch]:
    """Find every sensitive entity in one text block.

    ID cards are matched first and their spans are reserved, so an 18-digit
    number cannot be partly consumed by the phone rule.
    """
    if not text:
        return []
    norm, index = normalize_with_index(text)
    if not norm:
        return []

    taken: list[tuple[int, int]] = []
    found: list[EntityMatch] = []

    for m in IDCARD_RE.finditer(norm):
        s, e = m.span()
        check = idcard_check(m.group(0))
        taken.append((s, e))
        if check == "pass" and not _idcard_birth_date_valid(m.group(0)):
            # A valid checksum on an impossible birth date is a serial number,
            # not a citizen ID. Keep the span reserved so the phone rule cannot
            # carve an 11-digit substring out of it.
            continue
        found.append(
            EntityMatch(
                subtype="idcard",
                value=m.group(0),
                start=index[s],
                end=index[e - 1],
                check=check,
            )
        )

    for m in PHONE_RE.finditer(norm):
        s, e = m.span()
        if any(s < te and ts < e for ts, te in taken):
            continue
        found.append(
            EntityMatch(subtype="phone", value=m.group(0), start=index[s], end=index[e - 1], check="na")
        )

    found.sort(key=lambda x: x.start)
    return found


def _slice_box(block: TextBlock, start: int, end: int) -> BBox:
    """Convert a character span inside a block into a pixel box.

    OCR only returns the whole line box, so the span is split proportionally by
    character count (equal-width assumption). Good enough for Chinese forms and
    document numbers; the residual error is absorbed by K-08's padding
    (4px base + 3% of the short side).
    """
    x, y, w, h = block.bbox
    n = max(1, len(block.text))
    start = max(0, min(start, n - 1))
    end = max(start, min(end, n - 1))
    x0 = x + int(round(start / n * w))
    x1 = x + int(round((end + 1) / n * w))
    x0 = max(x, min(x0, x + w - 1))
    x1 = max(x0 + 1, min(x1, x + w))
    return (x0, y, x1 - x0, h)


def _near_context(block: TextBlock, blocks: Sequence[TextBlock], keywords: Sequence[str]) -> bool:
    if any(k in block.text for k in keywords):
        return True
    bx, by, bh = block.bbox[0], block.bbox[1], block.bbox[3]
    reach = 2.5 * bh  # about one line above and below
    for other in blocks:
        if other is block:
            continue
        oy, oh = other.bbox[1], other.bbox[3]
        gap = max(0, max(by, oy) - min(by + bh, oy + oh))
        if gap > reach:
            continue
        if any(k in other.text for k in keywords):
            return True
    return False


def blocks_to_detections(
    blocks: Sequence[TextBlock],
    image_id: str,
    *,
    cfg: OcrConfig | None = None,
    store: SecretStore | None = None,
    require_idcard_context: bool | None = None,
) -> list[Detection]:
    """K-03 text blocks -> K-04 Detections (kind=text).

    Plaintext is written to `store` (when given) under `<detection_id>:raw`.
    The record itself only ever holds `masked_preview`.
    """
    cfg = cfg or DEFAULT_CONFIG.ocr
    require_ctx = cfg.require_idcard_context if require_idcard_context is None else require_idcard_context

    counters = {"phone": 0, "idcard": 0}
    detections: list[Detection] = []

    for block in blocks:
        for ent in find_entities(block.text):
            if ent.subtype == "idcard" and require_ctx and not _near_context(block, blocks, IDCARD_CONTEXT_KEYWORDS):
                continue

            counters[ent.subtype] += 1
            det_id = f"det-{ent.subtype}-{counters[ent.subtype]:03d}"

            if ent.subtype == "phone":
                details: dict[str, object] = {"masked_preview": mask_phone(ent.value)}
                risk = PHONE_RISK
            else:
                details = {"masked_preview": mask_idcard(ent.value), "idcard_check": ent.check}
                risk = RISK_BY_IDCARD_CHECK.get(ent.check, 2)

            detections.append(
                Detection(
                    id=det_id,
                    image_id=image_id,
                    kind="text",
                    subtype=ent.subtype,
                    bbox=_slice_box(block, ent.start, ent.end),
                    detector_score=round(float(block.score), 4),
                    risk=risk,
                    details=details,
                )
            )
            if store is not None:
                store.put(f"{det_id}:raw", ent.value)

    detections.sort(key=lambda d: (d.bbox[1], d.bbox[0]) if d.bbox else (0, 0))
    return detections


def scan_text(text: str, image_id: str = "text-scan") -> list[Detection]:
    """Convenience: run entity detection on a string, bypassing OCR.

    Used by unit tests and by command-line debugging, never in the pipeline.
    """
    block = TextBlock(text=text, bbox=(0, 0, max(1, len(text) * 10), 20), score=1.0)
    return blocks_to_detections([block], image_id)

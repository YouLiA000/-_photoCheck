"""K-05 QR detection and decoding (owner: A).

Rules from spec K-05:
1. An undecodable code is still reported as a box with `decodable = false`.
   The user must see "there is a code here and I cannot read it", not nothing.
2. 1D barcodes are reported too, with subtype `qr_code`.
3. Fully offline: `urllib.parse` only parses hostnames, it never issues a request.

Two stages: `detect_qr()` returns raw QRHit objects (payload is plaintext and must
never be serialised); `build_detections()` converts them into v4 records, sending
the payload to the SecretStore and keeping only `decodable` plus a typed summary.

Fallback: when pyzbar is missing, only cv2.QRCodeDetector runs. Record what the
decode rate actually becomes, do not assume it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from ..config import DEFAULT_CONFIG, QrConfig
from ..contract import BBox, ContractError, Detection
from ..secret_store import SecretStore
from ._imgutil import crop, iou, to_bgr
from .qr_classify import classify
from .qr_evidence import count_finder_patterns, has_qr_evidence

__all__ = [
    "QRHit",
    "pyzbar_available",
    "cv2_available",
    "available",
    "detect_qr",
    "build_detections",
]

_ONE_D_BARCODES = {
    "EAN13",
    "EAN8",
    "UPCA",
    "UPCE",
    "CODE128",
    "CODE39",
    "CODE93",
    "ITF",
    "I25",
    "CODABAR",
    "DATABAR",
    "DATABAR_EXP",
}


@dataclass(frozen=True)
class QRHit:
    """Raw decode result. `payload` is plaintext: SecretStore only."""

    payload: str | None
    bbox: BBox
    decodable: bool
    symbology: str  # QRCODE / EAN13 / qr_fallback


def pyzbar_available() -> bool:
    try:
        import pyzbar.pyzbar  # noqa: F401
        from PIL import Image  # noqa: F401
    except Exception:
        return False
    return True


def backend() -> str:
    """Which decoder is actually in use.

    pyzbar reads QR codes and 1D barcodes; the cv2 fallback reads QR codes only.
    That is a hard capability gap and it must not be silent: when the libzbar DLL
    failed to load on one host, everything ran on the cv2 fallback for a whole
    sprint while the status line kept reporting `ok`.
    """
    if pyzbar_available():
        return "pyzbar"
    if cv2_available():
        return "cv2"
    return "none"


def cv2_available() -> bool:
    try:
        import cv2  # noqa: F401
    except Exception:
        return False
    return True


def available() -> bool:
    return pyzbar_available() or cv2_available()


def _clamp_box(x0: float, y0: float, x1: float, y1: float, bounds: tuple[int, int]) -> BBox:
    bw, bh = bounds
    xi0 = max(0, min(int(round(x0)), bw - 1))
    yi0 = max(0, min(int(round(y0)), bh - 1))
    xi1 = max(xi0 + 1, min(int(round(x1)), bw))
    yi1 = max(yi0 + 1, min(int(round(y1)), bh))
    return (xi0, yi0, xi1 - xi0, yi1 - yi0)


def _variants(arr: Any, cfg: QrConfig) -> list[tuple[Any, float]]:
    """Three variants, tried in order: grayscale, 2x upscale, adaptive threshold."""
    import cv2

    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY) if arr.ndim == 3 else arr
    out: list[tuple[Any, float]] = [(gray, 1.0)]

    h, w = gray.shape[:2]
    longest = max(h, w)
    scale = 1.0
    if longest * cfg.upscale <= cfg.upscale_max_long_side:
        scale = cfg.upscale
        out.append(
            (
                cv2.resize(gray, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_CUBIC),
                scale,
            )
        )

    block = cfg.adaptive_block if cfg.adaptive_block % 2 == 1 else cfg.adaptive_block + 1
    block = max(3, min(block, (min(gray.shape[:2]) // 2) * 2 - 1))
    if block >= 3:
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 10
        )
        out.append((binary, 1.0))
    return out


def _decode_pyzbar(proc: Any, scale: float, offset: tuple[int, int], bounds: tuple[int, int]) -> list[QRHit]:
    from PIL import Image
    from pyzbar import pyzbar

    # No `symbols` filter: 1D barcodes must be reported too (spec K-05, rule 2)
    try:
        decoded = pyzbar.decode(Image.fromarray(proc))
    except Exception:
        return []

    hits: list[QRHit] = []
    for item in decoded:
        poly = getattr(item, "polygon", None) or []
        if poly:
            xs = [p.x / scale + offset[0] for p in poly]
            ys = [p.y / scale + offset[1] for p in poly]
        else:
            rect = getattr(item, "rect", None)
            if rect is None:
                continue
            xs = [rect.left / scale + offset[0], (rect.left + rect.width) / scale + offset[0]]
            ys = [rect.top / scale + offset[1], (rect.top + rect.height) / scale + offset[1]]
        payload = item.data.decode("utf-8", errors="replace") if item.data else ""
        hits.append(
            QRHit(
                payload=payload or None,
                bbox=_clamp_box(min(xs), min(ys), max(xs), max(ys), bounds),
                decodable=bool(payload),
                symbology=str(getattr(item, "type", "QRCODE")).upper(),
            )
        )
    return hits


def _local_bbox(quad: Any, shape: tuple[int, ...]) -> BBox:
    """Quad -> box in the coordinate space of `gray` (before the ROI offset)."""
    xs, ys = quad[:, 0], quad[:, 1]
    return _clamp_box(xs.min(), ys.min(), xs.max(), ys.max(), (shape[1], shape[0]))


def _accept_undecoded(gray: Any, local_bbox: BBox, cfg: QrConfig, payload: str) -> bool:
    """A payload is proof of a code; without one the box must show finder patterns.

    This is where the false positives came from: when a decode fails cv2 still
    returns a quad, and on dense text that quad covers an address block. Keeping
    every such box as `qr_unknown` gave 7 false positives on C's dev set.
    """
    if payload:
        return True
    if min(local_bbox[2], local_bbox[3]) < cfg.finder_min_side_px:
        return False
    return has_qr_evidence(
        gray, local_bbox, min_finders=cfg.finder_min_count, tol=cfg.finder_ratio_tol
    )


def _multi_quads(detector: Any, gray: Any) -> list[tuple[Any, str]]:
    """Multi-QR detection that survives OpenCV's changing return shapes.

    OpenCV 4.10: `detectMulti` -> (retval, points), detection only, while
    `detectAndDecodeMulti` -> (retval, decoded_info, points, straight). Asking
    `detectMulti` for four values raises ValueError on every call, and the
    surrounding `except` turned that into "no codes here" - so a photo holding
    several codes silently yielded at most one. Try the decoding variant first.
    """
    for name in ("detectAndDecodeMulti", "detectMulti"):
        fn = getattr(detector, name, None)
        if fn is None:
            continue
        try:
            result = fn(gray)
        except Exception:
            continue
        if len(result) < 2:
            continue
        ok = result[0]
        decodes_payloads = len(result) >= 3
        points = result[2] if decodes_payloads else result[1]
        if not ok or points is None:
            return []
        quads: list[tuple[Any, str]] = []
        for i, quad in enumerate(points):
            payload = ""
            if decodes_payloads:
                infos = result[1]
                if i < len(infos) and infos[i]:
                    payload = str(infos[i])
            quads.append((quad.reshape(-1, 2), payload))
        return quads
    return []


def _finder_pattern_count(gray: Any, bbox: BBox) -> int:
    """Verified finder patterns inside `bbox`.

    Kept as a module-level name because the QR tests pin it. It counts real
    1:1:3:1:1 structures rather than merely nested squares: the glyph `回` is
    three nested squares, so a contour-only check scores it as a finder.
    """
    return count_finder_patterns(gray, bbox)


def _decode_cv2(
    arr: Any,
    offset: tuple[int, int],
    bounds: tuple[int, int],
    cfg: QrConfig,
) -> list[QRHit]:
    import cv2

    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY) if arr.ndim == 3 else arr
    detector = cv2.QRCodeDetector()
    shape = gray.shape
    hits: list[QRHit] = []

    for quad, payload in _multi_quads(detector, gray):
        if not _accept_undecoded(gray, _local_bbox(quad, shape), cfg, payload):
            continue
        xs = quad[:, 0] + offset[0]
        ys = quad[:, 1] + offset[1]
        hits.append(
            QRHit(
                payload=payload or None,
                bbox=_clamp_box(xs.min(), ys.min(), xs.max(), ys.max(), bounds),
                decodable=bool(payload),
                symbology="QRCODE",
            )
        )
    if hits:
        return hits

    try:
        payload, points, _ = detector.detectAndDecode(gray)
    except Exception:
        return []
    if points is None:
        return []
    quad = points.reshape(-1, 2)
    if not _accept_undecoded(gray, _local_bbox(quad, shape), cfg, payload):
        return []
    xs = quad[:, 0] + offset[0]
    ys = quad[:, 1] + offset[1]
    return [
        QRHit(
            payload=payload or None,
            bbox=_clamp_box(xs.min(), ys.min(), xs.max(), ys.max(), bounds),
            decodable=bool(payload),
            symbology="QRCODE",
        )
    ]


def _dedupe(hits: list[QRHit], iou_thr: float) -> list[QRHit]:
    """Keep one hit per code when variants or both decoders agree: decodable wins."""
    kept: list[QRHit] = []
    for hit in sorted(hits, key=lambda h: (h.decodable, h.payload is not None), reverse=True):
        dup = False
        for k in kept:
            if iou(hit.bbox, k.bbox) >= iou_thr:
                dup = True
                break
        if not dup:
            kept.append(hit)
    return kept


def _expand_for_quiet_zone(roi: Sequence[int], width: int, height: int, cfg: QrConfig) -> BBox:
    """Expand a ROI by the quiet zone before decoding.

    A QR code needs a light margin of about 4 modules. Crop exactly at the module
    boundary and decoders fail, which is precisely what K-09c does when it reuses
    `Detection.bbox`. The expansion therefore lives here, not in the caller, so
    nobody can forget it.

    Margin = ratio of the ROI short side, clamped by an absolute min/max.
    Over-expanding is harmless: returned boxes still sit next to the original ROI
    and the caller decides whether they count as residual.
    """
    x, y, w, h = (int(v) for v in roi)
    short = max(1, min(w, h))
    margin = int(round(short * cfg.quiet_zone_ratio))
    margin = max(cfg.quiet_zone_min_px, min(cfg.quiet_zone_max_px, margin))
    x0 = max(0, x - margin)
    y0 = max(0, y - margin)
    x1 = min(width, x + w + margin)
    y1 = min(height, y + h + margin)
    return (x0, y0, max(1, x1 - x0), max(1, y1 - y0))


def detect_qr(image: Any, roi: Sequence[int] | None = None, cfg: QrConfig | None = None) -> list[QRHit]:
    """Detect and decode QR codes / 1D barcodes. Returns [] when nothing is found.

    `roi` is the region of interest; decoding happens on a quiet-zone-expanded
    crop (see `_expand_for_quiet_zone`), while every returned bbox is converted
    back to full-image coordinates.
    """
    cfg = cfg or DEFAULT_CONFIG.qr
    arr = to_bgr(image)
    height, width = arr.shape[:2]
    if arr.size == 0 or height == 0 or width == 0:
        return []

    offset = (0, 0)
    if roi is not None:
        arr, offset = crop(arr, _expand_for_quiet_zone(roi, width, height, cfg))

    bounds = (width, height)
    hits: list[QRHit] = []

    if pyzbar_available():
        for proc, scale in _variants(arr, cfg):
            hits.extend(_decode_pyzbar(proc, scale, offset, bounds))
        hits = _dedupe(hits, cfg.merge_iou)

    # Only fall back to cv2 when pyzbar decoded nothing (or is missing): at least
    # cv2 can still report a box.
    if cv2_available() and not any(h.decodable for h in hits):
        hits.extend(_decode_cv2(arr, offset, bounds, cfg))
        hits = _dedupe(hits, cfg.merge_iou)

    hits.sort(key=lambda h: (h.bbox[1], h.bbox[0]))
    return hits


def _typed_summary(subtype: str, summary: str | None) -> dict[str, str]:
    """Map the safe summary onto a typed v4 field.

    `qr_wifi` uses `safe_ssid`, everything web-facing uses `safe_domain`. Since v4
    details no longer accept a generic `summary`: the field name itself has to say
    that the value is safe to publish.
    """
    if not summary:
        return {}
    return {"safe_ssid": summary} if subtype == "qr_wifi" else {"safe_domain": summary}


def build_detections(hits: Sequence[QRHit], image_id: str, store: SecretStore | None = None) -> list[Detection]:
    """QRHit -> v4 Detection (kind=qr). Payload goes to the store only.

    When the contract rejects the summary field (for example `localhost` is not a
    valid public domain), degrade to a box-only record instead of dropping the
    batch. The box still tells the user a code is there, which is the part that
    matters for redaction.
    """
    detections: list[Detection] = []
    for i, hit in enumerate(sorted(hits, key=lambda h: (h.bbox[1], h.bbox[0])), start=1):
        det_id = f"det-qr-{i:03d}"
        if not hit.decodable or not hit.payload:
            details: dict[str, Any] = {"decodable": False}
            subtype, risk = "qr_unknown", 1
        elif hit.symbology.upper() != "QRCODE":
            subtype, risk = "qr_code", 1
            details = {"decodable": True}
        else:
            cls = classify(hit.payload)
            subtype, risk = cls.subtype, cls.risk
            details = {"decodable": True, **_typed_summary(subtype, cls.summary)}

        try:
            detection = Detection(
                id=det_id,
                image_id=image_id,
                kind="qr",
                subtype=subtype,
                bbox=hit.bbox,
                detector_score=None,  # neither decoder gives calibrated scores
                risk=risk,
                details=details,
            )
        except ContractError:
            if len(details) <= 1:
                raise
            detection = Detection(
                id=det_id,
                image_id=image_id,
                kind="qr",
                subtype=subtype,
                bbox=hit.bbox,
                detector_score=None,
                risk=risk,
                details={"decodable": True},
            )
        detections.append(detection)
        if store is not None and hit.payload:
            store.put(f"{det_id}:payload", hit.payload)
    return detections

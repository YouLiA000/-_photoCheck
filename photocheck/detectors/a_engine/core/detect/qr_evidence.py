"""Structural evidence that an undecodable candidate really is a QR code.

Why this module exists
----------------------
pyzbar only returns successful decodes, so every hit it gives is proof by
payload. `cv2.QRCodeDetector` also returns quads it merely *suspects*: on dense
text it happily reports a quadrilateral covering a whole address block. Keeping
those as `qr_unknown` records produced 7 false positives on C's dev set
(precision 12.5% for that subtype), and the same mechanism reproduced on B's
exported image (`bbox=[152,194,322,290]`, a pure text region).

Counting nested squares is NOT enough
-------------------------------------
The obvious check - "does the box contain three nested dark squares" - is what
the first fix did, and it is defeated by ordinary Chinese characters: `回` is an
outer square, a light ring and an inner square, i.e. exactly the contour chain a
finder pattern produces. Measured on a synthetic plate reading
"返回 回收 回报 回执 / 回龙观 回民 回访 回头": 16 "finder patterns" found, 0 of
them real. Any cv2 quad over such a block would sail through the gate.

A real finder pattern has a signature that a glyph cannot fake:
scanning through its centre gives five runs in the ratio 1:1:3:1:1 (outer ring,
light gap, 3-module core, light gap, outer ring), and the centre pixel is DARK
because the core is solid. `回`'s centre is the hollow interior - light - so the
ratio test rejects it before the numbers even matter. The ratio also survives
rotation: at 45 degrees every run scales by the same sqrt(2), so 1:1:3:1:1 is
preserved.

The second half of the check is arrangement: a QR has three finders forming an
isosceles right triangle (or, when the code is partly out of frame, two finders
aligned with their common edge) and all of them share one module size. Text can
produce one plausible square, never three that agree on module size and geometry.

Everything here is pure geometry over a boolean image, no decoders involved.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..contract import BBox

__all__ = [
    "FinderPattern",
    "find_finder_patterns",
    "count_finder_patterns",
    "has_qr_evidence",
]


@dataclass(frozen=True)
class FinderPattern:
    """One verified finder pattern, in crop-local pixels."""

    x: float
    y: float
    module: float  # estimated module size, derived from the 1:1:3:1:1 run

    @property
    def size(self) -> float:
        return self.module * 7.0


def _bilevel(gray):
    """Dark-pixel mask. Otsu keeps it usable under uneven lighting."""
    import cv2
    import numpy as np

    if getattr(gray, "ndim", 2) == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    if gray.size == 0:
        return np.zeros((0, 0), dtype=bool)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binary > 0


def _run_bounds(line):
    """(starts, ends) of every constant-value run in a 1D boolean array."""
    import numpy as np

    edges = np.flatnonzero(line[1:] != line[:-1]) + 1
    starts = np.concatenate(([0], edges)).astype(np.int64)
    ends = np.concatenate((edges, [line.size])).astype(np.int64)
    return starts, ends


def _ratio_ok(lengths: Sequence[int], tol: float) -> float | None:
    """Return the module size if the five runs fit 1:1:3:1:1, else None."""
    total = float(sum(lengths))
    unit = total / 7.0
    if unit < 1.5:  # sub-two-pixel modules are noise, not a code
        return None
    for length, expected in zip(lengths, (1, 1, 3, 1, 1)):
        allowed = tol * unit * (1.0 if expected == 1 else 1.5)
        if abs(length - expected * unit) > allowed:
            return None
    return unit


def _cross_check(line, index: int, tol: float) -> float | None:
    """Check the 1:1:3:1:1 signature across one scan line through `index`.

    `index` must land on the DARK core. That single condition is what rejects
    glyphs like `回`: their centre pixel is the hollow interior, i.e. light.
    """
    if index < 0 or index >= line.size or not line[index]:
        return None
    starts, ends = _run_bounds(line)
    k = int((ends > index).argmax())  # run containing `index`
    if k < 2 or k + 2 >= starts.size:
        return None
    window = [int(ends[i] - starts[i]) for i in range(k - 2, k + 3)]
    # runs alternate by construction; dark needs to be at k-2, k, k+2
    return _ratio_ok(window, tol)


def _nested_squares(binary) -> list[tuple[float, float, int]]:
    """Contour chains three levels deep: outer square, light ring, solid core.

    This only proposes centres; it is far too weak to decide on its own (see the
    module docstring). It is cheap and gives sub-pixel-accurate centres.
    """
    import cv2

    contours, hierarchy = cv2.findContours(
        binary.astype("uint8") * 255, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )
    if hierarchy is None or not len(contours):
        return []
    tree = hierarchy[0]
    out: list[tuple[float, float, int]] = []
    for i in range(len(contours)):
        child = int(tree[i][2])
        if child < 0:
            continue
        grandchild = int(tree[child][2])
        if grandchild < 0:
            continue
        x, y, w, h = cv2.boundingRect(contours[i])
        if w < 10 or h < 10:
            continue
        out.append((x + w / 2.0, y + h / 2.0, min(w, h)))
    return out


def _verify_at(binary, cx: float, cy: float, tol: float) -> float | None:
    """Module size if a finder pattern is centred here, else None."""
    h, w = binary.shape[:2]
    xi = int(round(cx))
    yi = int(round(cy))
    if not (0 <= xi < w and 0 <= yi < h):
        return None
    mh = _cross_check(binary[yi, :], xi, tol)
    if mh is None:
        return None
    mv = _cross_check(binary[:, xi], yi, tol)
    if mv is None:
        return None
    if max(mh, mv) > 1.6 * min(mh, mv):  # a square must measure square
        return None
    return (mh + mv) / 2.0


def find_finder_patterns(gray, tol: float = 0.6) -> list[FinderPattern]:
    """All verified finder patterns inside one crop, in crop-local pixels."""
    binary = _bilevel(gray)
    if binary.size == 0:
        return []
    found: list[FinderPattern] = []
    for cx, cy, _ in _nested_squares(binary):
        module = _verify_at(binary, cx, cy, tol)
        if module is None:
            continue
        # Same structure seen from nested contours: keep the first, they coincide.
        if any(math.hypot(p.x - cx, p.y - cy) <= 0.8 * module for p in found):
            continue
        found.append(FinderPattern(x=cx, y=cy, module=module))
    return found


def _right_triangle(patterns: Sequence[FinderPattern]) -> bool:
    """Three finders: two equal legs meeting at (almost) a right angle."""
    for corner in range(3):
        rest = [patterns[i] for i in range(3) if i != corner]
        ox, oy = patterns[corner].x, patterns[corner].y
        ax, ay = rest[0].x - ox, rest[0].y - oy
        bx, by = rest[1].x - ox, rest[1].y - oy
        la, lb = math.hypot(ax, ay), math.hypot(bx, by)
        module = max(p.module for p in patterns)
        if min(la, lb) < 6.0 * module:
            continue
        cos = abs(ax * bx + ay * by) / (la * lb)
        if cos <= 0.4 and 0.45 <= la / lb <= 2.2:
            return True
    return False


def _aligned_pair(patterns: Sequence[FinderPattern]) -> bool:
    """Two finders sharing an edge: a code partly out of frame.

    Still worth reporting - the user has to know a code is there even when it is
    cropped - but the evidence has to be tighter, hence alignment plus a shared
    module size.
    """
    a, b = patterns[0], patterns[1]
    if max(a.module, b.module) > 1.6 * min(a.module, b.module):
        return False
    dx, dy = abs(a.x - b.x), abs(a.y - b.y)
    module = max(a.module, b.module)
    span = max(dx, dy)
    if span < 6.0 * module:
        return False
    return min(dx, dy) <= 0.4 * span


def _arrangement_ok(patterns: Sequence[FinderPattern], min_finders: int) -> bool:
    from itertools import combinations

    if len(patterns) < min_finders or min_finders < 2:
        return len(patterns) >= min_finders and bool(patterns)
    if len(patterns) >= 3:
        if any(_right_triangle([patterns[i] for i in combo])
               for combo in combinations(range(len(patterns)), 3)):
            return True
        # A fourth plausible pattern does not invalidate a real code, but three
        # collinear ones do: fall through to the pair check only when we have
        # fewer than three.
        if len(patterns) < 4:
            return False
    return _aligned_pair(patterns[:2])


def count_finder_patterns(gray, bbox: BBox | None = None, tol: float = 0.6) -> int:
    """Number of verified finder patterns in `bbox` (or in the whole crop)."""
    if bbox is not None:
        x, y, w, h = (int(v) for v in bbox)
        if w <= 0 or h <= 0:
            return 0
        gray = gray[y : y + h, x : x + w]
    return len(find_finder_patterns(gray, tol=tol))


def has_qr_evidence(
    gray,
    bbox: BBox | None = None,
    *,
    min_finders: int = 2,
    tol: float = 0.6,
) -> bool:
    """True when the crop shows a QR-code-like arrangement of finder patterns."""
    if bbox is not None:
        x, y, w, h = (int(v) for v in bbox)
        if w <= 0 or h <= 0:
            return False
        gray = gray[y : y + h, x : x + w]
    patterns = find_finder_patterns(gray, tol=tol)
    return _arrangement_ok(patterns, min_finders)


def describe(patterns: Iterable[FinderPattern]) -> str:
    """One-line summary for warnings and badcase write-ups."""
    items = list(patterns)
    if not items:
        return "no finder pattern"
    modules = ", ".join(f"{p.module:.1f}px" for p in items)
    return f"{len(items)} finder pattern(s), module {modules}"

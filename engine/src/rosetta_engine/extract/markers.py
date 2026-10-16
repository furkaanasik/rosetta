"""Vector-drawn callout markers (❶ ❷ ❸ …) used by code listings and their explanation lists.

Some books (DDIA, O'Reilly toolchain) draw these markers as vector graphics instead of text: a
dark filled circle made of four Bézier curves with a white-filled digit path on top. The digit is
identified from the white path's drawing-command sequence (``DIGIT_OPS``). That table is
specific to the marker font of the book it was measured on; markers whose digit is unknown are
numbered sequentially, continuing from the previous page's last marker of the same kind.

Kinds: a *list* marker sits just left of the first line of a text line; anything else (to the
right of / inside a code listing) is a *code* callout.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Literal

from rosetta_engine.extract.geometry import v_overlap
from rosetta_engine.extract.pdf_reader import RawDrawing, RawPage
from rosetta_engine.models import BBox

MarkerKind = Literal["list", "code"]

# Path command sequences of the white digit glyphs ("l" line, "c" curve), measured on
# "Designing Data-Intensive Applications" (2nd ed.). Identical at both marker sizes.
DIGIT_OPS: dict[str, int] = {
    "lcllllll": 1,
    "cccclllccccl": 2,
    "lccclccclcccllcccl": 3,
    "cllllllllllllll": 4,
    "cccclccccllllll": 5,
    "cccccclcccccccl": 6,
}

CIRCLE_MIN, CIRCLE_MAX = 5.0, 12.0  # pt, diameter of the marker circle
SQUARE_TOL = 1.0
DARK_MAX = 0.4  # every RGB channel of the circle fill at most this
LIGHT_MIN = 0.9  # every RGB channel of the digit fill at least this
LIST_GAP = 15.0  # max distance from marker's right edge to the list text


@dataclass(frozen=True)
class Marker:
    bbox: BBox
    kind: MarkerKind
    number: int | None  # None until numbered: digit unknown
    known: bool = True  # digit read from the glyph (False: sequential fallback)

    @property
    def y_center(self) -> float:
        return (self.bbox[1] + self.bbox[3]) / 2


def to_char(n: int) -> str:
    """❶ … ❿ (U+2776…U+277F); larger numbers fall back to "(n)"."""
    return chr(0x2775 + n) if 1 <= n <= 10 else f"({n})"


def _is_circle(d: RawDrawing) -> bool:
    x0, y0, x1, y1 = d.rect
    w, h = x1 - x0, y1 - y0
    return (
        d.filled
        and d.ops == "cccc"
        and CIRCLE_MIN <= w <= CIRCLE_MAX
        and abs(w - h) <= SQUARE_TOL
        and d.fill is not None
        and max(d.fill) <= DARK_MAX
    )


def _is_glyph(d: RawDrawing) -> bool:
    return d.filled and bool(d.ops) and d.fill is not None and min(d.fill) >= LIGHT_MIN


def _inside(inner: BBox, outer: BBox, tol: float = 0.5) -> bool:
    return (
        inner[0] >= outer[0] - tol
        and inner[1] >= outer[1] - tol
        and inner[2] <= outer[2] + tol
        and inner[3] <= outer[3] + tol
    )


def _kind(bbox: BBox, page: RawPage) -> MarkerKind:
    for b in page.text_blocks:
        for ln in b.lines:
            if 0 <= ln.bbox[0] - bbox[2] <= LIST_GAP and v_overlap(bbox, ln.bbox) > 0:
                return "list"
    return "code"


def detect(page: RawPage) -> list[Marker]:
    """Markers on ``page`` in reading order (top to bottom), digits read where known."""
    glyphs = [d for d in page.drawings if _is_glyph(d)]
    found: list[Marker] = []
    for c in page.drawings:
        if not _is_circle(c):
            continue
        digit = next((g for g in glyphs if _inside(g.rect, c.rect)), None)
        number = DIGIT_OPS.get(digit.ops) if digit else None
        found.append(Marker(bbox=c.rect, kind=_kind(c.rect, page), number=number))
    return sorted(found, key=lambda m: (m.bbox[1], m.bbox[0]))


def assign_numbers(markers: Sequence[Marker], previous: Sequence[Marker] = ()) -> list[Marker]:
    """Fill unknown digits per kind: previous known/assigned number + 1, starting after the
    last marker of the same kind in ``previous`` (the previous page's numbered markers)."""
    last: dict[MarkerKind, int] = {}
    for m in previous:
        if m.number is not None:
            last[m.kind] = m.number
    out: list[Marker] = []
    for m in markers:
        n = m.number if m.number is not None else last.get(m.kind, 0) + 1
        if m.number is None:
            m = replace(m, number=n, known=False)
        last[m.kind] = n
        out.append(m)
    return out


def needs_previous(markers: Sequence[Marker]) -> bool:
    return any(m.number is None for m in markers)

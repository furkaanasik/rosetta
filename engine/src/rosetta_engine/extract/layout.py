"""Column detection and reading order.

Full-width "span" items cut the page into horizontal bands; inside a band, an empty vertical
corridor (>= 12pt) with enough content on both sides is a column gap. Monospace items never
create corridors (indented code) and are attached to the nearest column.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rosetta_engine.models import BBox

SPAN_WIDTH = 0.60
MIN_GAP = 12.0
MIN_COLUMN_BLOCKS = 2
MIN_COLUMN_COVERAGE = 0.25


@dataclass(frozen=True)
class LayoutItem:
    key: int
    bbox: BBox
    mono: bool = False


def _gaps(items: Sequence[LayoutItem]) -> list[float]:
    """x positions (gap centers) of empty vertical corridors between item x-ranges."""
    spans = sorted((it.bbox[0], it.bbox[2]) for it in items)
    gaps: list[float] = []
    if not spans:
        return gaps
    cur_end = spans[0][1]
    for x0, x1 in spans[1:]:
        if x0 - cur_end >= MIN_GAP:
            gaps.append((cur_end + x0) / 2)
        cur_end = max(cur_end, x1)
    return gaps


def _coverage(items: Sequence[LayoutItem]) -> float:
    return sum(it.bbox[3] - it.bbox[1] for it in items)


def _columns(items: Sequence[LayoutItem], page_height: float) -> list[list[LayoutItem]]:
    prose = [it for it in items if not it.mono]
    cuts: list[float] = []
    for g in _gaps(prose):
        left = [it for it in prose if it.bbox[2] <= g]
        right = [it for it in prose if it.bbox[0] >= g]
        ok = all(
            len(side) >= MIN_COLUMN_BLOCKS and _coverage(side) >= page_height * MIN_COLUMN_COVERAGE
            for side in (left, right)
        )
        if ok:
            cuts.append(g)
    if not cuts:
        return [list(items)]
    bounds = [-float("inf"), *cuts, float("inf")]
    cols: list[list[LayoutItem]] = [[] for _ in range(len(bounds) - 1)]
    for it in items:
        cx = (it.bbox[0] + it.bbox[2]) / 2
        for c in range(len(cols)):
            if bounds[c] <= cx < bounds[c + 1]:
                cols[c].append(it)
                break
    return [c for c in cols if c]


def reading_order(items: Sequence[LayoutItem], page_height: float) -> list[int]:
    if not items:
        return []
    x0 = min(it.bbox[0] for it in items)
    x1 = max(it.bbox[2] for it in items)
    content_w = max(x1 - x0, 1.0)
    by_y = sorted(items, key=lambda it: (it.bbox[1], it.bbox[0]))

    order: list[int] = []
    band: list[LayoutItem] = []

    def flush() -> None:
        for col in _columns(band, page_height):
            order.extend(it.key for it in sorted(col, key=lambda it: (it.bbox[1], it.bbox[0])))
        band.clear()

    for it in by_y:
        is_span = (it.bbox[2] - it.bbox[0]) > content_w * SPAN_WIDTH and not it.mono
        if is_span:
            flush()
            order.append(it.key)
        else:
            band.append(it)
    flush()
    return order

"""Small bbox helpers shared by the extract modules."""

from __future__ import annotations

from collections.abc import Iterable

from rosetta_engine.models import BBox


def area(b: BBox) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a: BBox, b: BBox) -> BBox | None:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if x1 < x0 or y1 < y0:
        return None
    return (x0, y0, x1, y1)


def overlap_ratio(inner: BBox, outer: BBox) -> float:
    """Share of ``inner``'s area lying inside ``outer`` (degenerate boxes count as points)."""
    inter = intersection(inner, outer)
    if inter is None:
        return 0.0
    a = area(inner)
    if a == 0:
        return 1.0
    return area(inter) / a


def union(boxes: Iterable[BBox]) -> BBox:
    bs = list(boxes)
    return (
        min(b[0] for b in bs),
        min(b[1] for b in bs),
        max(b[2] for b in bs),
        max(b[3] for b in bs),
    )


def expand(b: BBox, d: float) -> BBox:
    return (b[0] - d, b[1] - d, b[2] + d, b[3] + d)


def touches(a: BBox, b: BBox, tol: float = 0.0) -> bool:
    return intersection(expand(a, tol), b) is not None


def v_overlap(a: BBox, b: BBox) -> float:
    return max(0.0, min(a[3], b[3]) - max(a[1], b[1]))

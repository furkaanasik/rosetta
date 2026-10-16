"""Image, vector-figure and table regions; text inside a region is swallowed (never translated).

Box exceptions: a drawn box whose text is mostly monospace is a code background (text stays and
becomes CODE); a box holding >= 3 lines of prose is a note/sidebar (text stays, ``aside=True``).
Small images with text next to them are note/tip icons: decoration, and the text is ``aside``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from rosetta_engine.extract.fonts import font_family, is_monospace
from rosetta_engine.extract.geometry import area, overlap_ratio, touches, union, v_overlap
from rosetta_engine.extract.pdf_reader import RawBlock, RawPage
from rosetta_engine.extract.stats import TypographyStats
from rosetta_engine.models import BBox

DRAWING_TOLERANCE = 6.0
MIN_REGION_SHARE = 0.03  # drawing clusters smaller than 3% of the page are not figures
THIN = 2.0  # separators: height or width under 2pt
DECOR_IMAGE_SHARE = 0.02  # images under 2% of the page next to text are icons
MARKER_MAX = 14.0  # small vector glyphs (list numbers, code callouts)
SWALLOW_RATIO = 0.70
CODE_BOX_MONO = 0.60
TABLE_GAP = 12.0

TABLE_CAPTION = re.compile(r"^Table\s+[\dA-Z]+[-.\d]*")

RegionKind = Literal["image", "table"]


@dataclass(frozen=True)
class Region:
    kind: RegionKind
    bbox: BBox


@dataclass
class FigureAnalysis:
    regions: list[Region] = field(default_factory=list)
    swallowed: set[int] = field(default_factory=set)  # indexes into page.text_blocks
    aside: set[int] = field(default_factory=set)
    markers: list[BBox] = field(default_factory=list)  # small vector glyphs (list markers)


def _block_chars(block: RawBlock) -> tuple[int, int]:
    """(monospace chars, all chars)."""
    mono = total = 0
    for ln in block.lines:
        for s in ln.spans:
            n = len(s.text.strip())
            total += n
            if is_monospace(s.font, s.flags):
                mono += n
    return mono, total


def _dominant(block: RawBlock) -> tuple[str, float]:
    weights: dict[tuple[str, float], int] = {}
    for ln in block.lines:
        for s in ln.spans:
            k = (s.font, s.size)
            weights[k] = weights.get(k, 0) + len(s.text.strip())
    return max(weights.items(), key=lambda kv: kv[1])[0] if weights else ("", 0.0)


def _cluster(rects: Sequence[BBox], tol: float) -> list[BBox]:
    parent = list(range(len(rects)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            if touches(rects[i], rects[j], tol):
                parent[find(i)] = find(j)
    groups: dict[int, list[BBox]] = {}
    for i, r in enumerate(rects):
        groups.setdefault(find(i), []).append(r)
    return [union(g) for g in groups.values()]


def _is_prose_box(blocks: Sequence[RawBlock], stats: TypographyStats, width: float) -> bool:
    lines = [ln for b in blocks for ln in b.lines]
    if len(lines) < 3:
        return False
    prose_chars = total = 0
    for ln in lines:
        n = len(ln.text.strip())
        total += n
        sizes = [s.size for s in ln.spans if s.text.strip()]
        long_line = (ln.bbox[2] - ln.bbox[0]) >= width * 0.5
        if sizes and min(sizes) >= stats.body_size * 0.85 and long_line:
            prose_chars += n
    return total > 0 and prose_chars / total >= 0.6


def _is_table_body(block: RawBlock, stats: TypographyStats) -> bool:
    font, size = _dominant(block)
    if is_monospace(font):
        return False
    is_body = abs(size - stats.body_size) < 0.3 and font_family(font) == stats.body_font_family
    return not is_body


def _tables(
    page: RawPage, stats: TypographyStats, excluded: set[int]
) -> list[tuple[BBox, set[int]]]:
    blocks = page.text_blocks
    order = sorted(range(len(blocks)), key=lambda i: blocks[i].bbox[1])
    found: list[tuple[BBox, set[int]]] = []
    for pos, ci in enumerate(order):
        cap = blocks[ci]
        if not TABLE_CAPTION.match(cap.text.strip()):
            continue
        members: list[int] = []
        bottom = cap.bbox[3]
        for i in order[pos + 1 :]:
            b = blocks[i]
            if i in excluded or b.bbox[1] - bottom > TABLE_GAP or not _is_table_body(b, stats):
                break
            members.append(i)
            bottom = b.bbox[3]
        if not members:
            continue
        top = cap.bbox[3]
        boxes = [blocks[i].bbox for i in members]
        for d in page.drawings:
            if d.rect[1] >= top - 1 and d.rect[3] <= bottom + TABLE_GAP:
                boxes.append(d.rect)
        for t in page.table_bboxes:  # find_tables is only a hint: extend, never create
            if t[1] >= top - 1 and t[1] <= bottom:
                boxes.append(t)
        found.append((union(boxes), set(members)))
    return found


def analyze_figures(page: RawPage, stats: TypographyStats) -> FigureAnalysis:
    result = FigureAnalysis()
    blocks = page.text_blocks
    page_area = page.width * page.height

    # (a) raster images: icons next to text are decoration, the rest are figures
    image_boxes: list[BBox] = []
    for img in page.image_blocks:
        neighbours = [
            i
            for i, b in enumerate(blocks)
            if v_overlap(img.bbox, b.bbox) > 0
            and (0 <= b.bbox[0] - img.bbox[2] <= 30 or 0 <= img.bbox[0] - b.bbox[2] <= 30)
        ]
        if area(img.bbox) < page_area * DECOR_IMAGE_SHARE:
            result.aside.update(neighbours)
            continue
        image_boxes.append(img.bbox)

    # (c) tables first, so their rules/fills are not mistaken for figures
    tables = _tables(page, stats, result.aside)
    for bbox, members in tables:
        result.regions.append(Region("table", bbox))
        result.swallowed |= members

    # (b) vector drawings
    rects = [
        d.rect
        for d in page.drawings
        if not any(overlap_ratio(d.rect, r.bbox) > 0.5 for r in result.regions)
    ]
    for cl in _cluster(rects, DRAWING_TOLERANCE):
        w, h = cl[2] - cl[0], cl[3] - cl[1]
        if w < THIN or h < THIN:
            continue  # separator rule
        if area(cl) < page_area * MIN_REGION_SHARE:
            if w <= MARKER_MAX and h <= MARKER_MAX:
                result.markers.append(cl)
            continue
        merged = False
        for k, ib in enumerate(image_boxes):
            if touches(cl, ib, DRAWING_TOLERANCE):
                image_boxes[k] = union([ib, cl])  # frame around a raster figure
                merged = True
        if merged:
            continue
        inside = [i for i, b in enumerate(blocks) if overlap_ratio(b.bbox, cl) >= SWALLOW_RATIO]
        if inside:
            mono = sum(_block_chars(blocks[i])[0] for i in inside)
            total = sum(_block_chars(blocks[i])[1] for i in inside)
            if total and mono / total >= CODE_BOX_MONO:
                continue  # code background
            if _is_prose_box([blocks[i] for i in inside], stats, w):
                result.aside.update(inside)
                continue
        image_boxes.append(cl)

    for ib in image_boxes:
        result.regions.append(Region("image", ib))
    for i, b in enumerate(blocks):
        if i in result.swallowed:
            continue
        if any(overlap_ratio(b.bbox, r.bbox) >= SWALLOW_RATIO for r in result.regions):
            result.swallowed.add(i)
    result.aside -= result.swallowed
    return result

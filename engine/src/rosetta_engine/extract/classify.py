"""Block type classification for text units (after furniture/figure handling).

Priority: CODE -> CAPTION -> HEADING -> FOOTNOTE -> LIST_ITEM -> PARAGRAPH.
FURNITURE and IMAGE/TABLE are decided earlier (furniture.py, figures.py).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from rosetta_engine.extract.fonts import FLAG_SUPERSCRIPT, is_bold, is_italic, is_monospace
from rosetta_engine.extract.geometry import v_overlap
from rosetta_engine.extract.pdf_reader import RawLine
from rosetta_engine.extract.stats import TypographyStats
from rosetta_engine.models import BBox, BlockType

CODE_MONO_SHARE = 0.70
CAPTION_DISTANCE = 30.0
FOOTNOTE_SIZE = 0.85
FOOTNOTE_ZONE = 0.75  # bottom 25% of the page
HEADING_MAX_WORDS = 12
LIST_INDENT = 10.0
MARKER_GAP = 15.0

CAPTION_RE = re.compile(r"^(Figure|Fig\.|Table|Listing|Example)\s+[\dA-Z]+(?:[-.]\d+)*[.:](?:\s|$)")
BULLET_RE = re.compile(r"^([•●▪◦‣·–\-*])\s+")
NUMBER_RE = re.compile(r"^(\(?\d{1,2}[.)])\s+")
_NON_ALNUM = re.compile(r"[\W_]+")


def toc_key(text: str) -> str:
    """Loose key for matching block text to TOC titles (case, quotes, dashes, spacing)."""
    return _NON_ALNUM.sub("", text.lower())


@dataclass(frozen=True)
class Unit:
    """A run of lines that becomes one Block."""

    lines: tuple[RawLine, ...]
    bbox: BBox
    aside: bool = False

    @property
    def text(self) -> str:
        return " ".join(ln.text.strip() for ln in self.lines)


@dataclass(frozen=True)
class Style:
    font: str
    size: float
    bold: bool
    italic: bool
    mono_share: float
    all_bold: bool
    chars: int


@dataclass(frozen=True)
class PageContext:
    height: float
    stats: TypographyStats
    toc: Mapping[str, int] = field(default_factory=dict)  # toc_key(title) -> level
    anchors: Sequence[BBox] = ()  # IMAGE/TABLE regions and CODE blocks, for captions
    markers: Sequence[BBox] = ()  # small vector glyphs (list markers)
    body_left: float = 0.0


@dataclass(frozen=True)
class Classification:
    type: BlockType
    heading_level: int | None = None
    list_marker: str | None = None
    aside: bool = False


def style_of(lines: Sequence[RawLine]) -> Style:
    weights: dict[tuple[str, float, int], int] = {}
    mono = bold = total = 0
    for ln in lines:
        for s in ln.spans:
            n = len(s.text.strip())
            if not n:
                continue
            total += n
            weights[(s.font, s.size, s.flags)] = weights.get((s.font, s.size, s.flags), 0) + n
            if is_monospace(s.font, s.flags):
                mono += n
            if is_bold(s.font, s.flags):
                bold += n
    if not weights:
        return Style("", 0.0, False, False, 0.0, False, 0)
    font, size, flags = max(weights.items(), key=lambda kv: kv[1])[0]
    return Style(
        font=font,
        size=size,
        bold=is_bold(font, flags),
        italic=is_italic(font, flags),
        mono_share=mono / total,
        all_bold=bold == total,
        chars=total,
    )


def is_code(style: Style) -> bool:
    return style.chars > 0 and style.mono_share >= CODE_MONO_SHARE


def is_superscript(flags: int) -> bool:
    return bool(flags & FLAG_SUPERSCRIPT)


def _near(bbox: BBox, anchors: Sequence[BBox]) -> bool:
    for a in anchors:
        h_overlap = min(bbox[2], a[2]) - max(bbox[0], a[0]) > 0
        gap = max(a[1] - bbox[3], bbox[1] - a[3])
        if h_overlap and gap <= CAPTION_DISTANCE:
            return True
    return False


def _heading_level(unit: Unit, style: Style, ctx: PageContext) -> int | None:
    text = unit.text.strip()
    key = toc_key(text)
    if key and key in ctx.toc:
        return ctx.toc[key]
    if style.mono_share > 0.5 or len(unit.lines) > 3:
        return None
    level = ctx.stats.level_for_size(style.size)
    if level is not None:
        return level
    body = ctx.stats.body_size
    if (
        style.all_bold
        and len(unit.lines) <= 2
        and len(text.split()) <= HEADING_MAX_WORDS
        and not text.endswith(".")
        and style.size >= body * 0.95
    ):
        return 4
    return None


def _vector_marker(unit: Unit, ctx: PageContext) -> bool:
    if unit.bbox[0] <= ctx.body_left + LIST_INDENT:
        return False
    first = unit.lines[0].bbox
    return any(
        m[2] <= unit.bbox[0] + 1 and unit.bbox[0] - m[2] <= MARKER_GAP and v_overlap(m, first) > 0
        for m in ctx.markers
    )


def list_marker(text: str) -> str | None:
    m = BULLET_RE.match(text) or NUMBER_RE.match(text)
    return m.group(1) if m else None


def classify(unit: Unit, ctx: PageContext) -> Classification:
    style = style_of(unit.lines)
    text = unit.text.strip()
    body = ctx.stats.body_size

    if is_code(style):
        return Classification(BlockType.CODE, aside=unit.aside)
    if CAPTION_RE.match(text) and _near(unit.bbox, ctx.anchors):
        return Classification(BlockType.CAPTION, aside=unit.aside)
    level = _heading_level(unit, style, ctx)
    if level is not None:
        return Classification(BlockType.HEADING, heading_level=level, aside=unit.aside)
    if style.size <= body * FOOTNOTE_SIZE and unit.bbox[1] >= ctx.height * FOOTNOTE_ZONE:
        return Classification(BlockType.FOOTNOTE)
    marker = list_marker(text)
    if marker is not None:
        return Classification(BlockType.LIST_ITEM, list_marker=marker, aside=unit.aside)
    if _vector_marker(unit, ctx):
        return Classification(BlockType.LIST_ITEM, list_marker="", aside=unit.aside)
    small = style.size < body * 0.95
    epigraph = small and (style.italic or text.startswith(("—", "―")))
    return Classification(BlockType.PARAGRAPH, aside=unit.aside or epigraph)

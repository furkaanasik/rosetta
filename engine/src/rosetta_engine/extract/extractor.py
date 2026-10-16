"""Extraction pipeline: read -> figures -> furniture -> units -> classify -> layout -> sentences.

Pure functions; persistence happens in the service.

Storage of ``BookMeta``: the whole object is one JSON blob
(``meta.model_dump_json()`` / ``BookMeta.model_validate_json(s)``). The service stores it in
``books.typography_json``; ``books.furniture_json`` is not needed (may stay NULL).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import pymupdf
from pydantic import BaseModel, ConfigDict, Field

from rosetta_engine.errors import ExtractionError
from rosetta_engine.extract.classify import (
    BULLET_RE,
    NUMBER_RE,
    Classification,
    PageContext,
    Unit,
    classify,
    is_code,
    is_superscript,
    style_of,
    toc_key,
)
from rosetta_engine.extract.figures import analyze_figures
from rosetta_engine.extract.fonts import font_family, is_monospace
from rosetta_engine.extract.furniture import FurnitureModel, build_furniture, is_furniture
from rosetta_engine.extract.geometry import union, v_overlap
from rosetta_engine.extract.layout import LayoutItem, reading_order
from rosetta_engine.extract.markers import Marker, assign_numbers, detect, needs_previous, to_char
from rosetta_engine.extract.pdf_reader import RawBlock, RawLine, RawPage, RawSpan, read_page
from rosetta_engine.extract.sentences import split_sentences
from rosetta_engine.extract.stats import TypographyStats, compute_stats, sample_pages
from rosetta_engine.extract.text_clean import (
    ASCII_HYPHEN,
    Seg,
    code_text,
    inline_text,
)
from rosetta_engine.models import TRANSLATABLE, BBox, Block, BlockType, PageBlocks, text_hash

EXTRACTOR_VERSION = 3  # 2: vector callout markers; 3: ignore crop marks / page-wide frames

CODE_MERGE_GAP = 16.0  # consecutive code blocks closer than this are one listing
DROP_CAP_RATIO = 2.0
CALLOUT_TOL = 2.0  # pt; a code callout belongs to a code unit whose y-range (± this) holds it
LIST_MARKER_GAP = 15.0  # pt between a vector list marker's right edge and the item text
_SENTENCE_END = re.compile(r"[.:!?][\"”’)\]]*$")


class TocEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    level: int
    title: str
    page: int  # 1-based, as in doc.get_toc()


class BookMeta(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    page_count: int
    stats: TypographyStats
    furniture: FurnitureModel = Field(default_factory=FurnitureModel)
    toc: list[TocEntry] = Field(default_factory=list)
    soft_hyphen: str = ASCII_HYPHEN  # line-break hyphen used by this book's typesetter
    extractor_version: int = EXTRACTOR_VERSION

    def toc_for_page(self, page_no: int) -> dict[str, int]:
        """TOC titles (normalized) expected on 0-based ``page_no``."""
        return {toc_key(e.title): e.level for e in self.toc if e.page == page_no + 1}


def extract_book_meta(doc: pymupdf.Document) -> BookMeta:
    d: Any = doc
    page_count = int(d.page_count)
    samples = [read_page(doc, n, graphics=False) for n in sample_pages(page_count)]
    stats = compute_stats(samples)
    furniture = build_furniture(samples, stats.body_size)
    toc = [TocEntry(level=int(t[0]), title=str(t[1]), page=int(t[2])) for t in d.get_toc()]
    title = str((d.metadata or {}).get("title") or "").strip()
    return BookMeta(title=title, page_count=page_count, stats=stats, furniture=furniture, toc=toc)


# --- units ---------------------------------------------------------------------------------


def _starts_item(line: RawLine) -> bool:
    t = line.text.strip()
    return bool(BULLET_RE.match(t) or NUMBER_RE.match(t))


def _split_units(block: RawBlock, aside: bool) -> list[Unit]:
    """Split a block holding several bullet/numbered items into one unit per item."""
    lines = block.lines
    starts = [i for i, ln in enumerate(lines) if _starts_item(ln)]
    if len(starts) < 2 or starts[0] != 0:
        return [Unit(lines=lines, bbox=block.bbox, aside=aside)]
    units: list[Unit] = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(lines)
        part = lines[s:e]
        units.append(Unit(lines=part, bbox=union(ln.bbox for ln in part), aside=aside))
    return units


def _merge_code(units: list[Unit]) -> list[Unit]:
    """Merge vertically adjacent code units (a listing split by blank lines)."""
    out: list[Unit] = []
    for u in sorted(units, key=lambda u: (u.bbox[1], u.bbox[0])):
        if out and is_code(style_of(u.lines)) and is_code(style_of(out[-1].lines)):
            prev = out[-1]
            gap = u.bbox[1] - prev.bbox[3]
            if 0 <= gap <= CODE_MERGE_GAP and abs(u.bbox[0] - prev.bbox[0]) < 30:
                out[-1] = Unit(
                    lines=prev.lines + u.lines, bbox=union([prev.bbox, u.bbox]), aside=prev.aside
                )
                continue
        out.append(u)
    return out


def _merge_drop_caps(units: list[Unit], body: float) -> list[Unit]:
    out: list[Unit] = []
    pending: Unit | None = None
    for u in sorted(units, key=lambda u: (u.bbox[1], u.bbox[0])):
        t = u.text.strip()
        st = style_of(u.lines)
        if len(t) == 1 and t.isalpha() and st.size >= body * DROP_CAP_RATIO:
            pending = u
            continue
        if pending is not None:
            first = u.lines[0]
            cap = pending.lines[0].spans[0]
            merged_first = RawLine(
                spans=(
                    RawSpan(
                        text=pending.text.strip(),
                        font=first.spans[0].font,
                        size=first.spans[0].size,
                        flags=first.spans[0].flags,
                        bbox=cap.bbox,
                        origin=cap.origin,
                    ),
                    *first.spans,
                ),
                bbox=union([pending.bbox, first.bbox]),
            )
            u = Unit(
                lines=(merged_first, *u.lines[1:]),
                bbox=union([pending.bbox, u.bbox]),
                aside=u.aside,
            )
            pending = None
        out.append(u)
    if pending is not None:
        out.append(pending)
    return out


# --- text ----------------------------------------------------------------------------------


def _segments(line: RawLine) -> list[Seg]:
    return [
        Seg(
            s.text,
            mono=is_monospace(s.font, s.flags),
            superscript=is_superscript(s.flags) and s.text.strip().isdigit(),
        )
        for s in line.spans
    ]


def _callout_suffixes(unit: Unit, callouts: Sequence[Marker]) -> dict[int, str]:
    """Line index -> " ❸ ❹" for the callouts drawn on that line of a code unit."""
    out: dict[int, str] = {}
    for m in sorted(callouts, key=lambda m: m.bbox[0]):
        if m.number is None or not unit.lines:
            continue
        i = min(
            range(len(unit.lines)),
            key=lambda k: abs((unit.lines[k].bbox[1] + unit.lines[k].bbox[3]) / 2 - m.y_center),
        )
        out[i] = out.get(i, "") + " " + to_char(m.number)
    return out


def _unit_text(
    unit: Unit,
    kind: BlockType,
    marker: str | None,
    soft: str,
    callouts: Sequence[Marker] = (),
) -> str:
    if kind == BlockType.CODE:
        suffix = _callout_suffixes(unit, callouts)
        st = style_of(unit.lines)
        left = min(ln.bbox[0] for ln in unit.lines)
        raw: list[tuple[float, str]] = []
        prev_bottom: float | None = None
        line_h = st.size * 1.2 if st.size else 10.0
        for k, ln in enumerate(unit.lines):
            if prev_bottom is not None:
                blanks = round((ln.bbox[1] - prev_bottom) / line_h)
                raw.extend((left, "") for _ in range(max(0, blanks)))
            raw.append((ln.bbox[0], ln.text.rstrip() + suffix[k] if k in suffix else ln.text))
            prev_bottom = ln.bbox[3]
        return code_text(raw, left, st.size * 0.5)
    text = inline_text([_segments(ln) for ln in unit.lines], soft)
    if kind == BlockType.LIST_ITEM and marker:
        text = text[len(marker) :].lstrip()
    return text


# --- page ----------------------------------------------------------------------------------


def _make_block(
    page_no: int,
    bbox: BBox,
    kind: BlockType,
    *,
    unit: Unit | None = None,
    cls: Classification | None = None,
    soft: str = ASCII_HYPHEN,
    callouts: Sequence[Marker] = (),
) -> Block:
    if unit is None:
        return Block(
            page_no=page_no,
            order=0,
            type=kind,
            bbox=bbox,
            font="",
            size=0.0,
            bold=False,
            italic=False,
            text="",
            text_hash=text_hash(f"{kind}:{bbox}"),
        )
    st = style_of(unit.lines)
    marker = cls.list_marker if cls else None
    text = _unit_text(unit, kind, marker, soft, callouts)
    translatable = kind in TRANSLATABLE
    return Block(
        page_no=page_no,
        order=0,
        type=kind,
        bbox=bbox,
        font=st.font,
        size=st.size,
        bold=st.bold,
        italic=st.italic,
        family="mono" if kind == BlockType.CODE else font_family(st.font),
        heading_level=cls.heading_level if cls else None,
        aside=cls.aside if cls else False,
        list_marker=marker,
        text=text,
        sentences=split_sentences(text) if translatable else [],
        text_hash=text_hash(text),
    )


def extract_page(doc: pymupdf.Document, page_no: int, meta: BookMeta) -> PageBlocks:
    """Extract 0-based ``page_no``. Raises ExtractionError when out of range."""
    if not 0 <= page_no < meta.page_count:
        raise ExtractionError(f"page {page_no + 1} out of range (1-{meta.page_count})")
    raw = read_page(doc, page_no)
    if not raw.has_text_layer:
        return PageBlocks(
            page_no=page_no, width=raw.width, height=raw.height, has_text_layer=False, blocks=[]
        )
    stats = meta.stats
    texts = raw.text_blocks
    edges = (
        {
            min(range(len(texts)), key=lambda i: texts[i].bbox[1]),
            max(range(len(texts)), key=lambda i: texts[i].bbox[3]),
        }
        if texts
        else set()
    )
    furniture_idx = {
        i
        for i, b in enumerate(texts)
        if is_furniture(b, raw.height, meta.furniture, stats.body_size, edge=i in edges)
    }
    figs = analyze_figures(raw, stats)

    units: list[Unit] = []
    for i, b in enumerate(texts):
        if i in furniture_idx or i in figs.swallowed:
            continue
        units.extend(_split_units(b, aside=i in figs.aside))
    units = _merge_drop_caps(_merge_code(units), stats.body_size)

    code_boxes = [u.bbox for u in units if is_code(style_of(u.lines))]
    ctx = PageContext(
        height=raw.height,
        stats=stats,
        toc=meta.toc_for_page(page_no),
        anchors=[r.bbox for r in figs.regions] + code_boxes,
        markers=figs.markers,
        body_left=min((u.bbox[0] for u in units), default=0.0),
    )

    markers = _page_markers(doc, page_no, raw)
    code_units = [u for u in units if is_code(style_of(u.lines))]
    content: list[Block] = []
    for u in units:
        cls = classify(u, ctx)
        callouts = _callouts_for(u, code_units, markers) if cls.type == BlockType.CODE else []
        block = _make_block(
            page_no, u.bbox, cls.type, unit=u, cls=cls, soft=meta.soft_hyphen, callouts=callouts
        )
        if cls.type == BlockType.LIST_ITEM and cls.list_marker == "":
            n = _list_number(u, markers)
            if n is not None:  # text stays unchanged: only the marker becomes "6"
                block = block.model_copy(update={"list_marker": str(n)})
        content.append(block)
    for r in figs.regions:
        kind = BlockType.TABLE if r.kind == "table" else BlockType.IMAGE
        content.append(_make_block(page_no, r.bbox, kind))

    items = [
        LayoutItem(key=k, bbox=b.bbox, mono=b.type == BlockType.CODE) for k, b in enumerate(content)
    ]
    ordered = [content[k] for k in reading_order(items, raw.height)]

    furn = [
        _make_block(
            page_no,
            texts[i].bbox,
            BlockType.FURNITURE,
            unit=Unit(lines=texts[i].lines, bbox=texts[i].bbox),
        )
        for i in sorted(furniture_idx, key=lambda i: texts[i].bbox[1])
    ]
    top = [b for b in furn if b.bbox[1] < raw.height / 2]
    bottom = [b for b in furn if b.bbox[1] >= raw.height / 2]
    blocks = [b.model_copy(update={"order": n}) for n, b in enumerate([*top, *ordered, *bottom])]
    return PageBlocks(
        page_no=page_no,
        width=raw.width,
        height=raw.height,
        has_text_layer=True,
        continues_on_next_page=_continues(ordered),
        blocks=blocks,
    )


def _page_markers(doc: pymupdf.Document, page_no: int, raw: RawPage) -> list[Marker]:
    """Numbered vector markers of the page. Unknown digits continue from the previous page's
    markers (which are numbered without looking further back)."""
    found = detect(raw)
    previous: list[Marker] = []
    if needs_previous(found) and page_no > 0:
        previous = assign_numbers(detect(read_page(doc, page_no - 1)))
    return assign_numbers(found, previous)


def _callouts_for(
    unit: Unit, code_units: Sequence[Unit], markers: Sequence[Marker]
) -> list[Marker]:
    """Code callouts drawn on ``unit``: within its y-range and not left of it. A callout that
    matches several code units goes to the first one (top to bottom)."""

    def holds(u: Unit, m: Marker) -> bool:
        return (
            u.bbox[1] - CALLOUT_TOL <= m.y_center <= u.bbox[3] + CALLOUT_TOL
            and m.bbox[0] >= u.bbox[0] - CALLOUT_TOL
        )

    return [
        m
        for m in markers
        if m.kind == "code"
        and holds(unit, m)
        and next((u for u in code_units if holds(u, m)), None) is unit
    ]


def _list_number(unit: Unit, markers: Sequence[Marker]) -> int | None:
    first = unit.lines[0].bbox
    for m in markers:
        if (
            m.kind == "list"
            and m.bbox[2] <= unit.bbox[0] + 1
            and unit.bbox[0] - m.bbox[2] <= LIST_MARKER_GAP
            and v_overlap(m.bbox, first) > 0
        ):
            return m.number
    return None


def _continues(ordered: Sequence[Block]) -> bool:
    if not ordered:
        return False
    last = ordered[-1]
    return last.type == BlockType.PARAGRAPH and not _SENTENCE_END.search(last.text.strip())

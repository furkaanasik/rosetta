"""Turkish table of contents: book TOC → translated heading titles → anchors → PDF outline."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import pymupdf

from rosetta_engine.extract.classify import toc_key
from rosetta_engine.models import Block, BlockType, PageBlocks, Translation

log = logging.getLogger(__name__)

_MIN_PARTIAL_KEY = 4  # shorter keys only match exactly


class TocSource(Protocol):
    """``extractor.TocEntry`` or anything shaped like ``doc.get_toc()`` rows."""

    @property
    def level(self) -> int: ...
    @property
    def title(self) -> str: ...
    @property
    def page(self) -> int: ...  # 1-based


@dataclass(frozen=True)
class TocItem:
    level: int
    title: str  # Turkish translation of the heading when available, else the original
    original: str
    page_no: int  # 0-based source page
    anchor: str  # element id in the export HTML

    @property
    def translated(self) -> bool:
        return self.title != self.original


def page_anchor(page_no: int) -> str:
    return f"pg-{page_no + 1}"


def heading_anchor(block: Block) -> str:
    return f"h-{block.page_no + 1}-{block.order}"


def normalize_levels(levels: Sequence[int]) -> list[int]:
    """Make levels valid for ``set_toc``: start at 1, never jump down by more than one."""
    out: list[int] = []
    prev = 0
    for level in levels:
        level = max(1, min(level, prev + 1))
        out.append(level)
        prev = level
    return out


def match_heading(title: str, page: PageBlocks) -> Block | None:
    """Heading block of ``page`` that carries TOC ``title`` (exact key first, then containment)."""
    key = toc_key(title)
    if not key:
        return None
    ordered = sorted(page.blocks, key=lambda b: b.order)
    headings = [b for b in ordered if b.type is BlockType.HEADING]
    for b in headings:
        if toc_key(b.text) == key:
            return b
    if len(key) < _MIN_PARTIAL_KEY:
        return None
    for b in headings:
        hk = toc_key(b.text)
        if key in hk or (len(hk) >= _MIN_PARTIAL_KEY and hk in key):
            return b
    return None


def _title(block: Block, translations: Mapping[str, Translation]) -> str:
    t = translations.get(block.text_hash)
    return (t.text if t is not None else block.text).strip()


def build_toc(
    toc: Sequence[TocSource],
    pages: Mapping[int, PageBlocks],
    translations: Mapping[int, Mapping[str, Translation]],
) -> list[TocItem]:
    """TOC entries inside the exported ``pages`` (0-based), titled from translated headings.

    A book without an embedded TOC falls back to the extracted headings themselves.
    """
    items: list[TocItem] = []
    if toc:
        for entry in toc:
            page_no = entry.page - 1
            page = pages.get(page_no)
            if page is None:
                continue
            block = match_heading(entry.title, page)
            if block is None:
                items.append(
                    TocItem(entry.level, entry.title.strip(), entry.title.strip(), page_no,
                            page_anchor(page_no))
                )  # fmt: skip
                continue
            title = _title(block, translations.get(page_no, {}))
            original = block.text.strip()
            items.append(TocItem(entry.level, title, original, page_no, heading_anchor(block)))
    else:
        for page_no in sorted(pages):
            for b in sorted(pages[page_no].blocks, key=lambda b: b.order):
                if b.type is BlockType.HEADING:
                    title = _title(b, translations.get(page_no, {}))
                    items.append(
                        TocItem(b.heading_level or 2, title, b.text.strip(), page_no,
                                heading_anchor(b))
                    )  # fmt: skip
    levels = normalize_levels([i.level for i in items])
    return [
        TocItem(lv, i.title, i.original, i.page_no, i.anchor)
        for lv, i in zip(levels, items, strict=True)
    ]


@dataclass(frozen=True)
class LinkMap:
    targets: dict[str, int]  # anchor id → 0-based output page
    link_pages: frozenset[int]  # output pages that contain our TOC links


def read_link_targets(pdf: Path, anchors: set[str]) -> LinkMap:
    """Internal links Chromium emitted for ``<a href="#anchor">`` (named destinations)."""
    doc: Any = pymupdf.open(str(pdf))  # type: ignore[no-untyped-call]
    try:
        targets: dict[str, int] = {}
        link_pages: set[int] = set()
        for page in doc:
            for link in page.get_links():
                name = link.get("nameddest") or ""
                target = link.get("page", -1)
                if name in anchors and isinstance(target, int) and target >= 0:
                    targets.setdefault(name, target)
                    link_pages.add(page.number)
        return LinkMap(targets, frozenset(link_pages))
    finally:
        doc.close()


def outline(
    items: Sequence[TocItem], targets: Mapping[str, int], page_offset: int = 0
) -> list[list[Any]]:
    """``set_toc`` rows ``[level, title, 1-based page]``; entries without a target are dropped."""
    kept = [(i, targets[i.anchor] - page_offset) for i in items if i.anchor in targets]
    kept = [(i, p) for i, p in kept if p >= 0]
    dropped = len(items) - len(kept)
    if dropped:
        log.warning("%d TOC entries have no target page in the exported PDF", dropped)
    levels = normalize_levels([i.level for i, _ in kept])
    return [[lv, i.title, p + 1] for lv, (i, p) in zip(levels, kept, strict=True)]


def set_outline(pdf: Path, rows: Sequence[Sequence[Any]], title: str | None = None) -> None:
    """Write bookmarks (and document title) into ``pdf`` in place."""
    doc: Any = pymupdf.open(str(pdf))  # type: ignore[no-untyped-call]
    try:
        doc.set_toc([list(r) for r in rows])
        if title:
            meta = dict(doc.metadata or {})
            meta["title"] = title
            doc.set_metadata(meta)
        doc.saveIncr()
    finally:
        doc.close()

"""The only module that talks to PyMuPDF's page text/graphics APIs.

Converts a page into plain frozen dataclasses (RawPage) that the rest of the pipeline uses.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pymupdf

from rosetta_engine.errors import ExtractionError
from rosetta_engine.models import BBox

log = logging.getLogger(__name__)

# PyMuPDF's API is only partially annotated; route calls through Any to keep mypy strict.
_pm: Any = pymupdf

# PyMuPDF prints a "Consider using the pymupdf_layout package" notice to stdout; we don't use it.
if hasattr(_pm, "no_recommend_layout"):
    _pm.no_recommend_layout()

TEXT_FLAGS = (
    pymupdf.TEXT_PRESERVE_WHITESPACE | pymupdf.TEXT_MEDIABOX_CLIP | pymupdf.TEXT_PRESERVE_IMAGES
)  # TEXT_PRESERVE_LIGATURES deliberately absent: ligatures get expanded
_CHUNK = 1 << 20


@dataclass(frozen=True)
class RawSpan:
    text: str
    font: str
    size: float
    flags: int
    bbox: BBox
    origin: tuple[float, float]


@dataclass(frozen=True)
class RawLine:
    spans: tuple[RawSpan, ...]
    bbox: BBox

    @property
    def text(self) -> str:
        return "".join(s.text for s in self.spans)


@dataclass(frozen=True)
class RawBlock:
    kind: Literal["text", "image"]
    lines: tuple[RawLine, ...]
    bbox: BBox

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass(frozen=True)
class RawDrawing:
    rect: BBox
    filled: bool
    stroked: bool


@dataclass(frozen=True)
class RawPage:
    page_no: int
    width: float
    height: float
    blocks: tuple[RawBlock, ...]
    drawings: tuple[RawDrawing, ...] = ()
    table_bboxes: tuple[BBox, ...] = ()

    @property
    def has_text_layer(self) -> bool:
        return any(s.text.strip() for b in self.blocks for ln in b.lines for s in ln.spans)

    @property
    def text_blocks(self) -> tuple[RawBlock, ...]:
        return tuple(b for b in self.blocks if b.kind == "text")

    @property
    def image_blocks(self) -> tuple[RawBlock, ...]:
        return tuple(b for b in self.blocks if b.kind == "image")


def open_book(path: Path | str) -> pymupdf.Document:
    try:
        doc: pymupdf.Document = _pm.open(str(path))
        return doc
    except Exception as e:  # pymupdf raises its own FileDataError/RuntimeError types
        raise ExtractionError(f"cannot open PDF {path}: {e}") from e


def file_hash(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while chunk := f.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _bbox(v: Any) -> BBox:
    return (float(v[0]), float(v[1]), float(v[2]), float(v[3]))


def _contains(outer: BBox, inner: BBox, tol: float = 0.5) -> bool:
    return (
        inner[0] >= outer[0] - tol
        and inner[1] >= outer[1] - tol
        and inner[2] <= outer[2] + tol
        and inner[3] <= outer[3] + tol
    )


def _dedupe_lines(lines: list[RawLine]) -> list[RawLine]:
    """Drop phantom lines that repeat a prefix of a containing line (e.g. a lone bullet "•"
    emitted again after the full "• text" line)."""
    out: list[RawLine] = []
    for i, ln in enumerate(lines):
        t = ln.text.strip()
        dup = any(
            j != i
            and _contains(other.bbox, ln.bbox)
            and len(other.text.strip()) > len(t)
            and other.text.strip().startswith(t)
            for j, other in enumerate(lines)
        )
        if not dup:
            out.append(ln)
    return out


def _read_blocks(page: Any) -> tuple[RawBlock, ...]:
    raw = page.get_text("dict", flags=TEXT_FLAGS)
    blocks: list[RawBlock] = []
    for b in raw["blocks"]:
        if b.get("type") == 1:
            blocks.append(RawBlock(kind="image", lines=(), bbox=_bbox(b["bbox"])))
            continue
        lines: list[RawLine] = []
        for ln in b.get("lines", []):
            spans = tuple(
                RawSpan(
                    text=s["text"],
                    font=s["font"],
                    size=round(float(s["size"]), 2),
                    flags=int(s["flags"]),
                    bbox=_bbox(s["bbox"]),
                    origin=(float(s["origin"][0]), float(s["origin"][1])),
                )
                for s in ln.get("spans", [])
                if s["text"]
            )
            if spans and any(s.text.strip() for s in spans):
                lines.append(RawLine(spans=spans, bbox=_bbox(ln["bbox"])))
        lines = _dedupe_lines(lines)
        if lines:
            blocks.append(RawBlock(kind="text", lines=tuple(lines), bbox=_bbox(b["bbox"])))
    return tuple(blocks)


def _read_drawings(page: Any) -> tuple[RawDrawing, ...]:
    out: list[RawDrawing] = []
    for d in page.get_drawings():
        kind = d.get("type") or ""
        out.append(RawDrawing(rect=_bbox(d["rect"]), filled="f" in kind, stroked="s" in kind))
    return tuple(out)


def _read_tables(page: Any) -> tuple[BBox, ...]:
    try:
        return tuple(_bbox(t.bbox) for t in page.find_tables().tables)
    except Exception as e:  # table finder is a hint only; never fail extraction on it
        log.debug("find_tables failed on page %s: %s", page.number, e)
        return ()


def read_page(doc: pymupdf.Document, n: int, *, graphics: bool = True) -> RawPage:
    """Read 0-based page ``n``. ``graphics=False`` skips drawings/tables (cheap, for stats)."""
    if not 0 <= n < doc.page_count:
        raise ExtractionError(f"page {n + 1} out of range (1-{doc.page_count})")
    page: Any = doc[n]
    rect = page.rect
    return RawPage(
        page_no=n,
        width=float(rect.width),
        height=float(rect.height),
        blocks=_read_blocks(page),
        drawings=_read_drawings(page) if graphics else (),
        table_bboxes=_read_tables(page) if graphics else (),
    )

"""Blocks + translations -> local HTML pages (translation, EN|TR review, extractor debug).

LLM output is untrusted: every text goes through :func:`inline`, which escapes first and only
then adds our own ``<code>`` tags. Templates use autoescape; no other ``Markup`` is built from
book or model text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import pymupdf
from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup, escape

from rosetta_engine.models import Block, BlockType, Book, PageBlocks, Translation

Mode = Literal["tr", "review", "debug"]
_MODES: tuple[Mode, ...] = ("tr", "review", "debug")

ASSETS_DIR = "assets"
STYLE_FILE = "style.css"
CROP_DPI = 150

_BACKTICK = re.compile(r"``(.+?)``|`([^`]+)`")
_NUMERIC_MARKER = re.compile(r"^\(?\d{1,3}[.)]?$")
_FIGURE_TYPES = frozenset({BlockType.IMAGE, BlockType.TABLE, BlockType.CODE})

_env = Environment(
    loader=PackageLoader("rosetta_engine.render", "templates"),
    autoescape=select_autoescape(["html", "j2"], default_for_string=True, default=True),
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=False,
)


def inline(text: str) -> Markup:
    """Escape ``text`` and turn `inline code` (and ``double`` backticks) into <code>."""
    parts: list[Markup] = []
    pos = 0
    for m in _BACKTICK.finditer(text):
        parts.append(escape(text[pos : m.start()]))
        code = m.group(1).strip() if m.group(1) is not None else m.group(2)
        parts.append(Markup("<code>") + escape(code) + Markup("</code>"))
        pos = m.end()
    parts.append(escape(text[pos:]))
    return Markup("").join(parts)


def page_filename(page_no: int, mode: Mode) -> str:
    return f"p{page_no + 1:03d}.{mode}.html"


# --- view model -------------------------------------------------------------------------


@dataclass(frozen=True)
class TextView:
    spans: list[Markup]
    aligned: bool = True


@dataclass(frozen=True)
class BlockView:
    block: Block
    data_block: str
    classes: str
    style: str
    en: TextView
    tr: TextView | None  # None: untranslated or not translatable
    tag: str = "p"
    img: str | None = None
    tooltip: str = ""

    @property
    def kind(self) -> str:
        return self.block.type.value

    @property
    def shown(self) -> TextView:
        return self.tr or self.en


@dataclass
class ListView:
    ordered: bool
    items: list[BlockView]
    kind: str = "list"


@dataclass
class FigureView:
    main: BlockView
    before: list[BlockView] = field(default_factory=list)
    after: list[BlockView] = field(default_factory=list)
    kind: str = "figure"


Node = BlockView | ListView | FigureView


def _spans(sentences: Sequence[str], fallback: str) -> list[Markup]:
    items = [s for s in sentences if s] or ([fallback] if fallback else [])
    return [inline(s) for s in items]


def _style(block: Block) -> str:
    return f"font-size: calc(var(--scale) * {block.size:g}pt)" if block.size > 0 else ""


def _tooltip(block: Block) -> str:
    x0, y0, x1, y1 = block.bbox
    parts = [
        f"#{block.order} {block.type.value}",
        f"bbox=({x0:.1f}, {y0:.1f}, {x1:.1f}, {y1:.1f})",
        f"font={block.font or '-'} {block.size:g}pt",
        f"family={block.family}",
    ]
    if block.bold or block.italic:
        styles = [s for s, on in (("bold", block.bold), ("italic", block.italic)) if on]
        parts.append("style=" + "+".join(styles))
    if block.heading_level is not None:
        parts.append(f"heading_level={block.heading_level}")
    if block.aside:
        parts.append("aside")
    if block.list_marker is not None:
        parts.append(f"list_marker={block.list_marker!r}")
    if block.sentences:
        parts.append(f"sentences={len(block.sentences)}")
    return "\n".join(parts)


def _heading_level(block: Block) -> int:
    level = block.heading_level if block.heading_level is not None else 2
    return min(max(level, 1), 6)


def _crop(block: Block, out_dir: Path, doc: pymupdf.Document | None) -> str | None:
    rel = f"{ASSETS_DIR}/p{block.page_no + 1:03d}_b{block.order}.png"
    target = out_dir / rel
    if target.is_file():
        return rel
    if doc is None:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    d: Any = doc
    pix = d[block.page_no].get_pixmap(clip=block.bbox, dpi=CROP_DPI)
    pix.save(str(target))
    return rel


def _view(
    block: Block,
    translations: dict[str, Translation],
    out_dir: Path,
    doc: pymupdf.Document | None,
) -> BlockView:
    classes = [f"b-{block.type.value}", f"ff-{block.family}"]
    if block.aside:
        classes.append("aside")
    if block.bold:
        classes.append("bold")
    if block.italic:
        classes.append("italic")

    en = TextView(_spans(block.sentences, block.text))
    tr: TextView | None = None
    if block.translatable:
        t = translations.get(block.text_hash)
        if t is None:
            classes.append("untranslated")
        else:
            tr = TextView(_spans(t.sentences, t.text), aligned=t.sentence_aligned)

    tag = "p"
    if block.type is BlockType.HEADING:
        tag = f"h{_heading_level(block)}"
    elif block.type is BlockType.LIST_ITEM:
        tag = "li"

    img = _crop(block, out_dir, doc) if block.type in (BlockType.IMAGE, BlockType.TABLE) else None
    return BlockView(
        block=block,
        data_block=f"{block.page_no}-{block.order}",
        classes=" ".join(classes),
        style=_style(block),
        en=en,
        tr=tr,
        tag=tag,
        img=img,
        tooltip=_tooltip(block),
    )


def _ordered(items: Sequence[BlockView]) -> bool:
    markers = [v.block.list_marker for v in items]
    return all(m is not None and (m == "" or _NUMERIC_MARKER.match(m)) for m in markers)


def _group(views: Sequence[BlockView]) -> list[Node]:
    """Group consecutive list items into lists and attach captions to adjacent figures/code."""
    nodes: list[Node] = []
    pending: list[BlockView] = []  # captions waiting for the next figure-able block
    i = 0
    while i < len(views):
        v = views[i]
        t = v.block.type
        if t is BlockType.LIST_ITEM:
            run = [v]
            while i + 1 < len(views) and views[i + 1].block.type is BlockType.LIST_ITEM:
                i += 1
                run.append(views[i])
            nodes.extend(pending)
            pending = []
            nodes.append(ListView(ordered=_ordered(run), items=run))
        elif t in _FIGURE_TYPES:
            nodes.append(FigureView(main=v, before=pending))
            pending = []
        elif t is BlockType.CAPTION:
            prev = nodes[-1] if nodes and not pending else None
            nxt = views[i + 1] if i + 1 < len(views) else None
            next_is_figure = nxt is not None and nxt.block.type in _FIGURE_TYPES
            if (
                isinstance(prev, FigureView)
                and not prev.after
                and (v.block.text.startswith(("Figure", "Fig.")) or not next_is_figure)
            ):
                prev.after.append(v)
            elif next_is_figure:
                pending.append(v)
            else:
                nodes.append(v)
        else:
            nodes.extend(pending)
            pending = []
            nodes.append(v)
        i += 1
    nodes.extend(pending)
    return nodes


# --- public API ---------------------------------------------------------------------------


def build_page_html(
    book: Book,
    page: PageBlocks,
    translations: dict[str, Translation],
    mode: Mode,
    out_dir: Path,
    doc: pymupdf.Document | None = None,
    lang: str = "tr",
) -> str:
    """Render one page. ``translations`` is keyed by source ``text_hash``."""
    ordered = sorted(page.blocks, key=lambda b: b.order)
    if mode == "debug":
        views = [_view(b, translations, out_dir, doc) for b in ordered]
        return _env.get_template("debug.html.j2").render(
            book=book, page=page, views=views, lang="en", page_label=page.page_no + 1
        )

    body = [b for b in ordered if b.type is not BlockType.FURNITURE]
    main = [_view(b, translations, out_dir, doc) for b in body if b.type is not BlockType.FOOTNOTE]
    notes = [_view(b, translations, out_dir, doc) for b in body if b.type is BlockType.FOOTNOTE]
    template = "review.html.j2" if mode == "review" else "page.html.j2"
    return _env.get_template(template).render(
        book=book,
        page=page,
        nodes=_group(main),
        rows=main,
        footnotes=notes,
        lang=lang,
        page_label=page.page_no + 1,
    )


def _copy_style(out_dir: Path) -> None:
    css = files("rosetta_engine.render").joinpath("templates", STYLE_FILE).read_text("utf-8")
    target = out_dir / STYLE_FILE
    if not target.is_file() or target.read_text("utf-8") != css:
        target.write_text(css, encoding="utf-8")


def write_page(
    book: Book,
    page: PageBlocks,
    translations: dict[str, Translation],
    mode: Mode,
    out_dir: Path,
    doc: pymupdf.Document | None = None,
    lang: str = "tr",
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    _copy_style(out_dir)
    html = build_page_html(book, page, translations, mode, out_dir, doc, lang)
    target = out_dir / page_filename(page.page_no, mode)
    target.write_text(html, encoding="utf-8")
    return target


def write_index(book: Book, out_dir: Path, entries: Sequence[tuple[int, list[str]]]) -> Path:
    """``entries``: (0-based page_no, modes present) for each rendered page."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _copy_style(out_dir)
    rows = [
        (page_no + 1, [(m, page_filename(page_no, m)) for m in _MODES if m in modes])
        for page_no, modes in sorted(entries)
    ]
    html = _env.get_template("index.html.j2").render(book=book, rows=rows, lang="tr")
    target = out_dir / "index.html"
    target.write_text(html, encoding="utf-8")
    return target

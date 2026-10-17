"""Blocks + translations -> local HTML pages (translation, EN|TR review, learn, debug).

LLM output is untrusted: every text goes through :func:`inline` (or :func:`code_markup` for code
blocks, :func:`learn_markup` in learn mode), which escapes first and only then adds our own
``<code>``/``<span>``/``<ruby>`` tags. Templates use autoescape; no other ``Markup`` is built
from book or model text.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import pymupdf
from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup, escape

from rosetta_engine.extract.extractor import EXTRACTOR_VERSION
from rosetta_engine.models import Block, BlockType, Book, PageBlocks, Translation

Mode = Literal["tr", "review", "learn", "debug"]
_MODES: tuple[Mode, ...] = ("tr", "review", "learn", "debug")

ASSETS_DIR = "assets"
STYLE_FILE = "style.css"
CROP_DPI = 150

_BACKTICK = re.compile(r"``(.+?)``|`([^`]+)`")
_NUMERIC_MARKER = re.compile(r"^\(?(\d{1,3})[.)]?$")
_CALLOUT_MARKER = re.compile(r"^\d{1,2}$")  # bare digit: vector-drawn ❶-style marker
_CALLOUT_CHARS = re.compile("[\u2776-\u277f]")  # ❶ … ❿
_WORD = re.compile(r"[A-Za-z][A-Za-z'’]*(?:-[A-Za-z]+)*")
_CALLOUT_FIRST = 0x2776
_CALLOUT_MAX = 10
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


@dataclass(frozen=True)
class LearnOptions:
    """Learn mode: ``unknown`` maps lemma → short Turkish meaning (book-wide)."""

    unknown: Mapping[str, str]
    lemma_of: Callable[[str], str]


def _plain_learn(text: str, opts: LearnOptions, cache: dict[str, str]) -> Markup:
    parts: list[Markup] = []
    pos = 0
    for m in _WORD.finditer(text):
        parts.append(escape(text[pos : m.start()]))
        word = m.group()
        key = word.lower()
        lemma = cache.get(key)
        if lemma is None:
            lemma = cache[key] = opts.lemma_of(key)
        attrs = (
            Markup(' data-w="') + escape(key) + Markup('" data-l="') + escape(lemma) + Markup('"')
        )
        if lemma in opts.unknown:
            meaning = opts.unknown[lemma]
            rt = Markup("<rt>") + escape(meaning) + Markup("</rt>") if meaning else Markup("")
            parts.append(
                Markup('<ruby class="w unknown"') + attrs + Markup(">") + escape(word) + rt
                + Markup("</ruby>")
            )  # fmt: skip
        else:
            tag = Markup('<span class="w"') + attrs + Markup(">")
            parts.append(tag + escape(word) + Markup("</span>"))
        pos = m.end()
    parts.append(escape(text[pos:]))
    return Markup("").join(parts)


def learn_markup(text: str, opts: LearnOptions, cache: dict[str, str] | None = None) -> Markup:
    """Like :func:`inline`, but every word is clickable and unknown lemmas get a ``<ruby>``."""
    cache = {} if cache is None else cache
    parts: list[Markup] = []
    pos = 0
    for m in _BACKTICK.finditer(text):
        parts.append(_plain_learn(text[pos : m.start()], opts, cache))
        code = m.group(1).strip() if m.group(1) is not None else m.group(2)
        parts.append(Markup("<code>") + escape(code) + Markup("</code>"))
        pos = m.end()
    parts.append(_plain_learn(text[pos:], opts, cache))
    return Markup("").join(parts)


def code_markup(text: str) -> Markup:
    """Escape a code block and wrap ❶–❿ callout characters in ``<span class="callout">``."""
    parts: list[Markup] = []
    pos = 0
    for m in _CALLOUT_CHARS.finditer(text):
        parts.append(escape(text[pos : m.start()]))
        parts.append(Markup('<span class="callout">') + escape(m.group()) + Markup("</span>"))
        pos = m.end()
    parts.append(escape(text[pos:]))
    return Markup("").join(parts)


def marker_number(marker: str | None) -> int | None:
    """``"3"``, ``"3."``, ``"(3)"`` → 3; bullets and ``""`` → None."""
    if not marker:
        return None
    m = _NUMERIC_MARKER.match(marker)
    return int(m.group(1)) if m else None


def callout_glyph(marker: str | None) -> str | None:
    """Bare digit markers (from vector-drawn callouts) → the matching ❶… character."""
    if not marker or not _CALLOUT_MARKER.match(marker):
        return None
    n = int(marker)
    return chr(_CALLOUT_FIRST + n - 1) if 1 <= n <= _CALLOUT_MAX else None


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
    code: Markup | None = None  # escaped code block text (CODE only)
    number: int | None = None  # list item number from a numeric marker
    callout: str | None = None  # ❶… glyph for vector-drawn callout markers

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
    start: int | None = None  # <ol start>
    values: list[int | None] = field(default_factory=list)  # <li value> per item
    kind: str = "list"


@dataclass
class FigureView:
    main: BlockView
    before: list[BlockView] = field(default_factory=list)
    after: list[BlockView] = field(default_factory=list)
    kind: str = "figure"


Node = BlockView | ListView | FigureView


Formatter = Callable[[str], Markup]


def _spans(sentences: Sequence[str], fallback: str, fmt: Formatter = inline) -> list[Markup]:
    items = [s for s in sentences if s] or ([fallback] if fallback else [])
    return [fmt(s) for s in items]


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


_CHAPTER_LABEL = re.compile(
    r"^((?:CHAPTER|Chapter|BÖLÜM|Bölüm|PART|Part|KISIM|Kısım)\s+(?:\d+|[IVXLC]+))\s+(?=\S)"
)


def _labelled(fmt: Formatter) -> Formatter:
    """Chapter headings: "CHAPTER 1 Title" → ``<span class="h-label">CHAPTER 1</span> Title``
    so the UI can style the label like the original (escaped, our own span only)."""

    def wrap(text: str) -> Markup:
        m = _CHAPTER_LABEL.match(text)
        if m is None:
            return fmt(text)
        label = Markup('<span class="h-label">') + escape(m.group(1)) + Markup("</span>")
        return label + Markup(" ") + fmt(text[m.end() :])

    return wrap


def crop_name(block: Block) -> str:
    """Asset file name; extractor version + bbox hash make stale crops impossible to reuse."""
    key = f"{EXTRACTOR_VERSION}:{','.join(f'{v:.2f}' for v in block.bbox)}"
    digest = hashlib.sha256(key.encode()).hexdigest()[:8]
    return f"p{block.page_no + 1:03d}_b{block.order}_{digest}.png"


def _crop(block: Block, out_dir: Path, doc: pymupdf.Document | None) -> str | None:
    rel = f"{ASSETS_DIR}/{crop_name(block)}"
    target = out_dir / rel
    if target.is_file():
        return rel
    if doc is None:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    d: Any = doc
    pix = d[block.page_no].get_pixmap(clip=block.bbox, dpi=CROP_DPI)
    # Write then rename: a crash mid-write never leaves a truncated file that looks valid.
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        pix.save(str(tmp), output="png")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)
    return rel


def _view(
    block: Block,
    translations: dict[str, Translation],
    out_dir: Path,
    doc: pymupdf.Document | None,
    fmt: Formatter = inline,
    with_tr: bool = True,
) -> BlockView:
    classes = [f"b-{block.type.value}", f"ff-{block.family}"]
    if block.aside:
        classes.append("aside")
    if block.bold:
        classes.append("bold")
    if block.italic:
        classes.append("italic")

    en_fmt: Formatter = fmt
    tr_fmt: Formatter = inline
    if block.type is BlockType.HEADING and _heading_level(block) == 1:
        en_fmt, tr_fmt = _labelled(fmt), _labelled(inline)
    en = TextView(_spans(block.sentences, block.text, en_fmt))
    tr: TextView | None = None
    if block.translatable and with_tr:
        t = translations.get(block.text_hash)
        if t is None:
            classes.append("untranslated")
        elif t.unit_role == "tail" and not t.sentences and not t.text:
            # The paragraph's translation sits wholly on the previous page (joined unit).
            classes.extend(["cont-prev", "joined-empty"])
            tr = TextView([], aligned=t.sentence_aligned)
        else:
            if t.unit_role == "head":
                classes.append("cont-next")
            elif t.unit_role == "tail":
                classes.append("cont-prev")
            tr = TextView(_spans(t.sentences, t.text, tr_fmt), aligned=t.sentence_aligned)

    tag = "p"
    if block.type is BlockType.HEADING:
        tag = f"h{_heading_level(block)}"
    elif block.type is BlockType.LIST_ITEM:
        tag = "li"

    img = _crop(block, out_dir, doc) if block.type in (BlockType.IMAGE, BlockType.TABLE) else None
    is_item = block.type is BlockType.LIST_ITEM
    callout = callout_glyph(block.list_marker) if is_item else None
    if callout:
        classes.append("callout-item")
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
        code=code_markup(block.text) if block.type is BlockType.CODE else None,
        number=marker_number(block.list_marker) if is_item else None,
        callout=callout,
    )


def _ordered(items: Sequence[BlockView]) -> bool:
    markers = [v.block.list_marker for v in items]
    return all(m is not None and (m == "" or _NUMERIC_MARKER.match(m)) for m in markers)


def _list(run: list[BlockView]) -> ListView:
    """Build a list node: ``start`` from the first number, ``value`` where numbering jumps."""
    ordered = _ordered(run)
    numbers = [v.number for v in run]
    if not ordered or numbers[0] is None:
        return ListView(ordered=ordered, items=run, values=[None] * len(run))
    first = numbers[0]
    consecutive = all(n == first + k for k, n in enumerate(numbers))
    values = [
        n if (not consecutive or v.callout) and n is not None else None
        for v, n in zip(run, numbers, strict=True)
    ]
    return ListView(ordered=True, items=run, start=first, values=values)


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
            nodes.append(_list(run))
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
    learn: LearnOptions | None = None,
) -> str:
    """Render one page. ``translations`` is keyed by source ``text_hash``.

    ``learn`` mode shows the original English text; words are clickable (``data-w``/``data-l``)
    and lemmas in ``learn.unknown`` carry their Turkish meaning in ``<ruby>``.
    """
    ordered = sorted(page.blocks, key=lambda b: b.order)
    if mode == "debug":
        views = [_view(b, translations, out_dir, doc) for b in ordered]
        return _env.get_template("debug.html.j2").render(
            book=book, page=page, views=views, lang="en", page_label=page.page_no + 1
        )

    fmt: Formatter = inline
    with_tr = True
    if mode == "learn":
        opts = learn or LearnOptions(unknown={}, lemma_of=str.lower)
        cache: dict[str, str] = {}
        fmt = lambda text: learn_markup(text, opts, cache)  # noqa: E731
        with_tr = False

    def view(b: Block) -> BlockView:
        return _view(b, translations, out_dir, doc, fmt, with_tr)

    body = [b for b in ordered if b.type is not BlockType.FURNITURE]
    main = [view(b) for b in body if b.type is not BlockType.FOOTNOTE]
    notes = [view(b) for b in body if b.type is BlockType.FOOTNOTE]
    template = "review.html.j2" if mode == "review" else "page.html.j2"
    return _env.get_template(template).render(
        book=book,
        page=page,
        nodes=_group(main),
        rows=main,
        footnotes=notes,
        lang="en" if mode == "learn" else lang,
        mode=mode,
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
    learn: LearnOptions | None = None,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    _copy_style(out_dir)
    html = build_page_html(book, page, translations, mode, out_dir, doc, lang, learn)
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

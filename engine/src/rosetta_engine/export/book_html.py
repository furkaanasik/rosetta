"""Assemble one print-ready HTML document from per-page renders (render.html_builder).

Page bodies come from :func:`render.html_builder.build_page_html`, which already escapes all
book/model text; we only cut out its ``<main>`` and add our own wrapper, ids and print CSS.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Literal

import pymupdf
from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

from rosetta_engine.export.toc import TocItem, page_anchor
from rosetta_engine.models import Book, PageBlocks, Translation
from rosetta_engine.render.html_builder import Mode as RenderMode
from rosetta_engine.render.html_builder import build_page_html

ExportMode = Literal["tr", "bilingual"]
Paper = Literal["a4", "letter"]
EXPORT_MODES: tuple[ExportMode, ...] = ("tr", "bilingual")
PAPERS: tuple[Paper, ...] = ("a4", "letter")

_MAIN = re.compile(r"<main\b[^>]*>.*</main>", re.DOTALL)

_env = Environment(
    loader=PackageLoader("rosetta_engine.export", "templates"),
    autoescape=select_autoescape(["html", "j2"], default_for_string=True, default=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True)
class Section:
    page_no: int  # 0-based source page
    anchor: str
    html: Markup  # escaped page body produced by render


def main_fragment(page_html: str) -> str:
    """The page's ``<main>`` element (kept whole so render's ``main.page``/``main.review`` CSS
    still applies)."""
    m = _MAIN.search(page_html)
    return m.group(0) if m else ""


def add_anchor(fragment: str, data_block: str, anchor: str) -> str | None:
    """Give the first element with ``data-block=data_block`` the id ``anchor``."""
    needle = f'data-block="{data_block}"'
    at = fragment.find(needle)
    if at < 0:
        return None
    start = fragment.rfind("<", 0, at)
    m = re.match(r"<[A-Za-z][A-Za-z0-9]*", fragment[start:])
    if start < 0 or m is None:
        return None
    cut = start + m.end()
    return f'{fragment[:cut]} id="{anchor}"{fragment[cut:]}'


def render_sections(
    book: Book,
    pages: Mapping[int, PageBlocks],
    translations: Mapping[int, Mapping[str, Translation]],
    mode: ExportMode,
    out_dir: Path,
    doc: pymupdf.Document | None,
    lang: str,
    toc: Sequence[TocItem] = (),
) -> list[Section]:
    page_mode: RenderMode = "review" if mode == "bilingual" else "tr"
    anchors: dict[int, list[TocItem]] = {}
    for item in toc:
        anchors.setdefault(item.page_no, []).append(item)

    sections: list[Section] = []
    for page_no in sorted(pages):
        page_html = build_page_html(
            book, pages[page_no], dict(translations.get(page_no, {})), page_mode, out_dir, doc,
            lang,
        )  # fmt: skip
        fragment = main_fragment(page_html)
        orphans: list[str] = []
        for item in {i.anchor: i for i in anchors.get(page_no, [])}.values():
            if item.anchor == page_anchor(page_no):
                continue
            data_block = f"{page_no}-{item.anchor.rsplit('-', 1)[1]}"
            updated = add_anchor(fragment, data_block, item.anchor)
            if updated is None:
                orphans.append(item.anchor)
            else:
                fragment = updated
        lead = "".join(f'<span class="anchor" id="{a}"></span>' for a in orphans)
        # Safe: ``fragment`` is render's escaped output; anchors are our own ids.
        sections.append(Section(page_no, page_anchor(page_no), Markup(lead + fragment)))
    return sections


def _css(package: str, *parts: str) -> Markup:
    # Our own stylesheets, inlined so the HTML prints without external files.
    return Markup(files(package).joinpath(*parts).read_text("utf-8"))


def build_book_html(
    book: Book,
    sections: Sequence[Section],
    *,
    mode: ExportMode,
    lang: str,
    paper: Paper,
    toc: Sequence[TocItem] = (),
    toc_page: bool = True,
    numbers: Mapping[str, int] | None = None,
) -> str:
    """The full export document. ``numbers``: anchor → printed page number for the TOC page."""
    return _env.get_template("book.html.j2").render(
        book=book,
        sections=sections,
        mode=mode,
        lang=lang,
        paper=paper,
        toc=list(toc) if toc_page else [],
        numbers=numbers or {},
        base_css=_css("rosetta_engine.render", "templates", "style.css"),
        print_css=_css("rosetta_engine.export", "templates", "print.css"),
        page_size="A4" if paper == "a4" else "letter",
    )

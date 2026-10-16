"""Export translated pages as one PDF: HTML assembly → Chromium print → Turkish bookmarks.

Two print passes when a TOC exists: the first finds where each heading lands (Chromium turns
``<a href="#id">`` into named destinations), the second prints the TOC page with those page
numbers (or without the TOC page at all). Never calls an AI provider.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from rosetta_engine.export.book_html import (
    ExportMode,
    Paper,
    Section,
    build_book_html,
    render_sections,
)
from rosetta_engine.export.chromium import (
    DEFAULT_TIMEOUT_S,
    ExportError,
    PrintRunner,
    print_to_pdf,
    run_print,
)
from rosetta_engine.export.toc import (
    TocItem,
    TocSource,
    build_toc,
    outline,
    read_link_targets,
    set_outline,
)
from rosetta_engine.models import Book, PageBlocks, Translation
from rosetta_engine.store.repo import Repos

log = logging.getLogger(__name__)

EnsurePages = Callable[[Sequence[int]], Mapping[int, PageBlocks]]


@dataclass(frozen=True)
class ExportOptions:
    provider: str
    model: str
    lang: str = "tr"
    mode: ExportMode = "tr"
    paper: Paper = "a4"
    toc_page: bool = True
    pages: Sequence[int] | None = None  # 0-based; None = every page with translations


@dataclass(frozen=True)
class ExportResult:
    pdf: Path
    html: Path
    pages: list[int]
    total_blocks: int  # translatable blocks in the exported pages
    untranslated_blocks: int
    untranslated_pages: list[int] = field(default_factory=list)  # pages with ≥1 missing block
    bookmarks: int = 0


def count_untranslated(
    pages: Mapping[int, PageBlocks], translations: Mapping[int, Mapping[str, Translation]]
) -> tuple[int, int, list[int]]:
    """(translatable blocks, untranslated blocks, pages with an untranslated block)."""
    total = missing = 0
    missing_pages: list[int] = []
    for page_no in sorted(pages):
        found = translations.get(page_no, {})
        todo = [b for b in pages[page_no].blocks if b.translatable and b.text.strip()]
        gaps = sum(1 for b in todo if b.text_hash not in found)
        total += len(todo)
        missing += gaps
        if gaps:
            missing_pages.append(page_no)
    return total, missing, missing_pages


def export_book(
    book: Book,
    doc: pymupdf.Document,
    toc_source: Sequence[TocSource],
    repos: Repos,
    ensure_pages: EnsurePages,
    opts: ExportOptions,
    out_pdf: Path,
    work_dir: Path,
    *,
    browser: Path | None = None,
    runner: PrintRunner = run_print,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> ExportResult:
    page_list = sorted(set(opts.pages)) if opts.pages is not None else (
        repos.translations.translated_pages(book.id, opts.lang, opts.provider, opts.model)
    )  # fmt: skip
    if not page_list:
        raise ExportError(
            f"Dışa aktarılacak çeviri yok ({opts.lang}, {opts.provider}/{opts.model}). "
            "Önce sayfaları çevir ya da --pages ver."
        )
    blocks = dict(ensure_pages(page_list))
    translations = {
        p: repos.translations.for_page(book.id, p, opts.lang, opts.provider, opts.model)
        for p in page_list
    }
    total, missing, missing_pages = count_untranslated(blocks, translations)
    toc = build_toc(toc_source, blocks, translations)
    sections = render_sections(book, blocks, translations, opts.mode, work_dir, doc, opts.lang, toc)

    html_path = work_dir / f"export.{opts.mode}.{opts.lang}.html"
    rows = _print(
        book, sections, toc, opts, html_path, out_pdf, browser=browser, runner=runner,
        timeout_s=timeout_s,
    )  # fmt: skip
    set_outline(out_pdf, rows, title=book.title)
    return ExportResult(
        pdf=out_pdf,
        html=html_path,
        pages=page_list,
        total_blocks=total,
        untranslated_blocks=missing,
        untranslated_pages=missing_pages,
        bookmarks=len(rows),
    )


def _print(
    book: Book,
    sections: Sequence[Section],
    toc: Sequence[TocItem],
    opts: ExportOptions,
    html_path: Path,
    out_pdf: Path,
    *,
    browser: Path | None,
    runner: PrintRunner,
    timeout_s: float,
) -> list[list[object]]:
    def write(toc_page: bool, numbers: Mapping[str, int] | None) -> None:
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(
            build_book_html(
                book, sections, mode=opts.mode, lang=opts.lang, paper=opts.paper, toc=toc,
                toc_page=toc_page, numbers=numbers,
            ),
            encoding="utf-8",
        )  # fmt: skip

    def render(target: Path) -> Path:
        return print_to_pdf(html_path, target, browser=browser, timeout_s=timeout_s, runner=runner)

    anchors = {i.anchor for i in toc}
    if not toc:
        write(False, None)
        render(out_pdf)
        return []

    # Pass 1: TOC page without numbers, only to learn where every anchor lands.
    probe = html_path.with_suffix(".probe.pdf")
    write(True, None)
    render(probe)
    first = read_link_targets(probe, anchors)
    probe.unlink(missing_ok=True)

    if opts.toc_page:
        write(True, {a: p + 1 for a, p in first.targets.items()})
        render(out_pdf)
        final = read_link_targets(out_pdf, anchors)
        return [list(r) for r in outline(toc, final.targets)]

    # The TOC ends with a forced page break, so dropping it shifts every page by its length.
    toc_pages = max(first.link_pages) + 1 if first.link_pages else 0
    write(False, None)
    render(out_pdf)
    return [list(r) for r in outline(toc, first.targets, page_offset=toc_pages)]

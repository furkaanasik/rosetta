"""Faz 5: book HTML assembly, Turkish TOC mapping, Chromium printing and the export command."""

from __future__ import annotations

import shutil
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from typer.testing import CliRunner

from rosetta_engine import cli, config
from rosetta_engine.config import Settings
from rosetta_engine.export import book_html, chromium, toc
from rosetta_engine.export.book_html import build_book_html, render_sections
from rosetta_engine.export.chromium import ExportError, PrintRun, find_chromium, print_to_pdf
from rosetta_engine.export.exporter import ExportOptions, count_untranslated, export_book
from rosetta_engine.export.toc import TocItem, build_toc, normalize_levels, outline
from rosetta_engine.extract.extractor import TocEntry
from rosetta_engine.models import Block, BlockType, Book, PageBlocks, Translation, text_hash
from rosetta_engine.store import db
from rosetta_engine.store.repo import Repos
from rosetta_engine.translate.fake import FakeTranslator
from rosetta_engine.translate.service import PageTranslationService

HAS_CHROMIUM = any(shutil.which(n) for n in chromium.CANDIDATES)
needs_chromium = pytest.mark.skipif(not HAS_CHROMIUM, reason="no chromium binary")

BOOK = Book(id=1, file_hash="ab" * 32, title="Test Book", page_count=3)


def _block(
    order: int,
    text: str,
    kind: BlockType = BlockType.PARAGRAPH,
    page_no: int = 0,
    level: int | None = None,
) -> Block:
    return Block(
        page_no=page_no, order=order, type=kind, bbox=(50, 50 + order * 20, 500, 60 + order * 20),
        font="Minion", size=10.5, bold=False, italic=False, heading_level=level, text=text,
        sentences=[text] if kind not in (BlockType.CODE, BlockType.FURNITURE) else [],
        text_hash=text_hash(text),
    )  # fmt: skip


def _page(page_no: int, blocks: Sequence[Block]) -> PageBlocks:
    return PageBlocks(page_no=page_no, width=500, height=700, has_text_layer=True, blocks=blocks)


def _tr(block: Block, text: str) -> Translation:
    return Translation(
        page_no=block.page_no, text_hash=block.text_hash, sentences=[text], text=text,
        sentence_aligned=True,
    )  # fmt: skip


@pytest.fixture
def sample() -> tuple[dict[int, PageBlocks], dict[int, dict[str, Translation]]]:
    h1 = _block(0, "Chapter 5. Replication", BlockType.HEADING, level=1)
    p1 = _block(1, "Leaders and followers use `log` replication.")
    code = _block(2, "SELECT * FROM t WHERE a < 3;", BlockType.CODE)
    p2 = _block(3, "This paragraph has no translation.")
    foot = _block(4, "12", BlockType.FURNITURE)
    h2 = _block(0, "Synchronous Versus Asynchronous", BlockType.HEADING, page_no=1, level=2)
    p3 = _block(1, "More text.", page_no=1)
    pages = {0: _page(0, [h1, p1, code, p2, foot]), 1: _page(1, [h2, p3])}
    translations = {
        0: {
            h1.text_hash: _tr(h1, "Bölüm 5. Replikasyon"),
            p1.text_hash: _tr(p1, "Liderler <script>alert(1)</script> `log` kullanır."),
        },
        1: {h2.text_hash: _tr(h2, "Eşzamanlı ve Eşzamansız"), p3.text_hash: _tr(p3, "Daha fazla.")},
    }
    return pages, translations


# --- toc ---------------------------------------------------------------------------------


def test_normalize_levels_starts_at_one_and_never_skips() -> None:
    assert normalize_levels([2, 4, 1, 3, 3]) == [1, 2, 1, 2, 3]
    assert normalize_levels([]) == []


def test_match_heading_exact_then_partial(sample: Any) -> None:
    pages, _ = sample

    assert toc.match_heading("Chapter 5. Replication", pages[0]) is not None
    assert toc.match_heading("5 Replication", pages[0]) is not None  # contained
    assert toc.match_heading("Partitioning", pages[0]) is None
    assert toc.match_heading("5", pages[0]) is None  # too short for partial matching


def test_build_toc_uses_translated_heading_titles(sample: Any) -> None:
    pages, translations = sample
    entries = [
        TocEntry(level=1, title="Chapter 5. Replication", page=1),
        TocEntry(level=3, title="Synchronous Versus Asynchronous", page=2),
        TocEntry(level=2, title="Not On This Page", page=2),
        TocEntry(level=1, title="Outside The Range", page=9),
    ]

    items = build_toc(entries, pages, translations)

    assert [(i.level, i.title, i.anchor) for i in items] == [
        (1, "Bölüm 5. Replikasyon", "h-1-0"),
        (2, "Eşzamanlı ve Eşzamansız", "h-2-0"),
        (2, "Not On This Page", "pg-2"),  # no heading match → page anchor, original title
    ]
    assert items[0].translated and not items[2].translated


def test_build_toc_without_book_toc_falls_back_to_headings(sample: Any) -> None:
    pages, translations = sample

    items = build_toc([], pages, translations)

    assert [i.title for i in items] == ["Bölüm 5. Replikasyon", "Eşzamanlı ve Eşzamansız"]
    assert [i.level for i in items] == [1, 2]


def test_build_toc_untranslated_heading_keeps_original(sample: Any) -> None:
    pages, _ = sample

    items = build_toc([TocEntry(level=1, title="Chapter 5. Replication", page=1)], pages, {})

    assert items[0].title == "Chapter 5. Replication"


def test_outline_maps_targets_drops_missing_and_applies_offset() -> None:
    items = [
        TocItem(1, "A", "A", 0, "h-1-0"),
        TocItem(2, "B", "B", 0, "h-1-3"),
        TocItem(3, "C", "C", 1, "missing"),
        TocItem(1, "D", "D", 1, "pg-2"),
    ]

    rows = outline(items, {"h-1-0": 1, "h-1-3": 2, "pg-2": 4}, page_offset=1)

    assert rows == [[1, "A", 1], [2, "B", 2], [1, "D", 4]]


# --- html assembly ------------------------------------------------------------------------


def test_add_anchor_targets_first_matching_element_only() -> None:
    frag = '<h1 data-block="0-0" class="x">A</h1><h1 data-block="0-0">B</h1>'

    out = book_html.add_anchor(frag, "0-0", "h-1-0")

    assert out == '<h1 id="h-1-0" data-block="0-0" class="x">A</h1><h1 data-block="0-0">B</h1>'
    assert book_html.add_anchor(frag, "9-9", "x") is None


def test_main_fragment_keeps_main_element() -> None:
    html = '<html><body><nav>x</nav><main class="page" data-page="0"><p>a</p></main></body></html>'

    assert book_html.main_fragment(html) == '<main class="page" data-page="0"><p>a</p></main>'
    assert book_html.main_fragment("<p>none</p>") == ""


def test_tr_book_html_escapes_marks_untranslated_and_links_toc(sample: Any, tmp_path: Path) -> None:
    pages, translations = sample
    items = build_toc(
        [TocEntry(level=1, title="Chapter 5. Replication", page=1)], pages, translations
    )
    sections = render_sections(BOOK, pages, translations, "tr", tmp_path, None, "tr", items)

    html = build_book_html(
        BOOK, sections, mode="tr", lang="tr", paper="a4", toc=items, numbers={"h-1-0": 2}
    )

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)" not in html
    assert "<code>log</code>" in html
    assert 'class="b-paragraph ff-serif untranslated"' in html
    assert "This paragraph has no translation." in html
    assert 'id="h-1-0"' in html and 'href="#h-1-0"' in html
    assert '<span class="n">2</span>' in html
    assert "İçindekiler" in html
    assert 'id="pg-1"' in html and 'id="pg-2"' in html
    assert "SELECT * FROM t WHERE a &lt; 3;" in html  # code verbatim, escaped
    assert ">12<" not in html  # furniture omitted
    assert "size: A4" in html
    assert "break-inside: avoid" in html and "break-after: avoid" in html
    assert "--scale: 1;" in html  # original point sizes, no shrinking


def test_bilingual_book_html_has_both_languages_without_toc_page(
    sample: Any, tmp_path: Path
) -> None:
    pages, translations = sample
    items = build_toc([], pages, translations)
    sections = render_sections(BOOK, pages, translations, "bilingual", tmp_path, None, "tr", items)

    html = build_book_html(
        BOOK, sections, mode="bilingual", lang="tr", paper="letter", toc=items, toc_page=False
    )

    assert '<main class="review"' in html
    assert "Chapter 5. Replication" in html and "Bölüm 5. Replikasyon" in html
    assert '<nav class="toc">' not in html
    assert html.count('id="h-1-0"') == 1  # anchor only on the first (EN) occurrence
    assert "size: letter" in html
    assert '<div class="cols-head">' in html


def test_orphan_anchor_becomes_leading_span(sample: Any, tmp_path: Path) -> None:
    pages, translations = sample
    items = [TocItem(1, "Ghost", "Ghost", 0, "h-1-99")]

    sections = render_sections(BOOK, pages, translations, "tr", tmp_path, None, "tr", items)

    assert str(sections[0].html).startswith('<span class="anchor" id="h-1-99"></span>')


def test_count_untranslated(sample: Any) -> None:
    pages, translations = sample

    total, missing, missing_pages = count_untranslated(pages, translations)

    assert (total, missing, missing_pages) == (5, 1, [0])


# --- chromium -----------------------------------------------------------------------------


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_find_chromium_env_override(tmp_path: Path) -> None:
    exe = _exe(tmp_path / "my-chrome")

    assert find_chromium(env={"ROSETTA_CHROMIUM": str(exe)}, which=lambda _: None) == exe
    with pytest.raises(ExportError, match="ROSETTA_CHROMIUM"):
        find_chromium(env={"ROSETTA_CHROMIUM": str(tmp_path / "nope")}, which=lambda _: None)


def test_find_chromium_path_then_playwright_then_error(tmp_path: Path) -> None:
    hit = find_chromium(env={}, which=lambda n: "/usr/bin/chromium" if n == "chromium" else None)
    assert hit == Path("/usr/bin/chromium")

    cache = tmp_path / "ms-playwright"
    pw = _exe(cache / "chromium-1200" / "chrome-linux" / "chrome")
    assert find_chromium(env={}, which=lambda _: None, playwright_cache=cache) == pw

    with pytest.raises(ExportError, match="Chromium bulunamadı"):
        find_chromium(env={}, which=lambda _: None, playwright_cache=tmp_path / "empty")


def test_print_to_pdf_argv_and_failure(tmp_path: Path) -> None:
    html = tmp_path / "a.html"
    html.write_text("<p>x</p>")
    pdf = tmp_path / "out" / "a.pdf"
    seen: list[list[str]] = []

    def ok(argv: Sequence[str], timeout_s: float) -> PrintRun:
        seen.append(list(argv))
        pdf.write_bytes(b"%PDF-1.7 fake")
        return PrintRun(0, "")

    assert print_to_pdf(html, pdf, browser=Path("/bin/chromium"), runner=ok) == pdf
    argv = seen[0]
    assert argv[0] == "/bin/chromium" and "--headless" in argv
    assert f"--print-to-pdf={pdf}" in argv and "--no-pdf-header-footer" in argv
    assert any(a.startswith("--user-data-dir=") for a in argv)
    assert argv[-1] == html.resolve().as_uri()

    def broken(argv: Sequence[str], timeout_s: float) -> PrintRun:
        return PrintRun(1, "boom\nreal error")

    with pytest.raises(ExportError, match="real error"):
        print_to_pdf(html, pdf, browser=Path("/bin/chromium"), runner=broken)


# --- end to end (real chromium, fake translations) --------------------------------------


@pytest.fixture
def repos() -> Iterator[Repos]:
    conn = db.connect(":memory:")
    db.migrate(conn)
    yield Repos.from_conn(conn)
    conn.close()


def _translated(repos: Repos, pdf: Path) -> tuple[PageTranslationService, Any, Any, Any]:
    svc = PageTranslationService(FakeTranslator(), repos, Settings())
    book, doc, meta = svc.open_book(pdf)
    svc.execute(svc.plan(book, doc, meta, [0, 1], "tr"))
    return svc, book, doc, meta


@needs_chromium
@pytest.mark.parametrize(("mode", "toc_page"), [("tr", True), ("bilingual", False)])
def test_export_book_end_to_end(
    repos: Repos, book_pdf: Path, tmp_path: Path, mode: Any, toc_page: bool
) -> None:
    svc, book, doc, meta = _translated(repos, book_pdf)
    out = tmp_path / "out.pdf"

    result = export_book(
        book, doc, meta.toc, repos, lambda ps: svc.ensure_pages(book, doc, meta, ps),
        ExportOptions(provider="fake", model="fake", mode=mode, toc_page=toc_page),
        out, tmp_path / "work",
    )  # fmt: skip

    assert result.pages == [0, 1]
    assert result.untranslated_blocks == 0
    pdf: Any = pymupdf.open(str(out))  # type: ignore[no-untyped-call]
    try:
        assert len(pdf) > 0
        rows = pdf.get_toc()
        assert rows and rows[0][1].startswith("[TR] ")
        assert rows[0][2] == (2 if toc_page else 1)  # the TOC page comes first when printed
        assert "[TR]" in pdf[rows[0][2] - 1].get_text()
        assert pdf.metadata["title"] == book.title
    finally:
        pdf.close()
        doc.close()


@needs_chromium
def test_export_reports_untranslated_pages(repos: Repos, book_pdf: Path, tmp_path: Path) -> None:
    svc, book, doc, meta = _translated(repos, book_pdf)

    result = export_book(
        book, doc, meta.toc, repos, lambda ps: svc.ensure_pages(book, doc, meta, ps),
        ExportOptions(provider="fake", model="fake", pages=[0, 2]),
        tmp_path / "x.pdf", tmp_path / "work",
    )  # fmt: skip
    doc.close()

    assert result.pages == [0, 2]
    assert result.untranslated_pages == [2]
    assert result.untranslated_blocks > 0


def test_export_without_translations_is_an_error(
    repos: Repos, book_pdf: Path, tmp_path: Path
) -> None:
    svc = PageTranslationService(FakeTranslator(), repos, Settings())
    book, doc, meta = svc.open_book(book_pdf)

    with pytest.raises(ExportError, match="çeviri yok"):
        export_book(
            book, doc, meta.toc, repos, lambda ps: svc.ensure_pages(book, doc, meta, ps),
            ExportOptions(provider="fake", model="fake"), tmp_path / "x.pdf", tmp_path,
        )  # fmt: skip
    doc.close()


# --- CLI -------------------------------------------------------------------------------------

runner = CliRunner()


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path


def test_cli_export_without_translations_fails(isolated: Path, book_pdf: Path) -> None:
    result = runner.invoke(
        cli.app, ["export", str(book_pdf), "--provider", "fake", "--model", "fake"]
    )

    assert result.exit_code == 1
    assert "çeviri yok" in result.output


@needs_chromium
def test_cli_export_after_fake_translate(isolated: Path, book_pdf: Path) -> None:
    tr = runner.invoke(
        cli.app, ["translate", str(book_pdf), "--pages", "1", "--provider", "fake", "--yes"]
    )
    assert tr.exit_code == 0, tr.output
    out = isolated / "book.pdf"

    result = runner.invoke(
        cli.app,
        ["export", str(book_pdf), "--provider", "fake", "--model", "fake", "--out", str(out),
         "--mode", "bilingual", "--paper", "letter"],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert out.is_file()
    assert "Yer imleri: 1" in result.output
    assert (config.data_dir() / "out").is_dir()

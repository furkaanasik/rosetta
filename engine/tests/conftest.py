"""Synthetic PDFs generated with PyMuPDF (no real book needed)."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf
import pytest

# Rich must not colour CLI output in tests, even when the calling shell forces colour.
for _var in ("FORCE_COLOR", "CLICOLOR_FORCE"):
    os.environ.pop(_var, None)

DDIA_PATH = Path.home() / "SSD/Books/Designing Data-Intensive Applications 2nd.pdf"

LOREM = (
    "Replication means keeping a copy of the same data on multiple machines that are "
    "connected via a network. There are several reasons why you might want to replicate "
    "data. To keep data geographically close to your users, and thus reduce latency. "
    "To allow the system to continue working even if some of its parts have failed. "
)
LEFT_TEXT = "Left column. " + LOREM * 2
RIGHT_TEXT = "Right column. " + LOREM * 2

CODE = "SELECT * FROM users\n  WHERE id = 42\n  ORDER BY name;"


def _doc() -> Any:
    return pymupdf.open()


def build_book_page(page: Any, number: int) -> None:
    """A typical technical-book page: header, h1, 2 paragraphs, code, figure + caption,
    list, footnote, footer."""
    page.insert_text((50, 30), f"Chapter 5: Replication | {number}", fontname="helv", fontsize=8)
    page.insert_text((50, 90), "Chapter 5. Replication", fontname="tibo", fontsize=18)
    page.insert_textbox(pymupdf.Rect(50, 105, 545, 185), LOREM, fontname="tiro", fontsize=10)
    page.insert_textbox(pymupdf.Rect(50, 195, 545, 260), LOREM, fontname="tiro", fontsize=10)
    page.insert_text((50, 285), CODE, fontname="cour", fontsize=9)
    shape = page.new_shape()
    shape.draw_rect(pymupdf.Rect(100, 340, 495, 470))
    shape.draw_rect(pymupdf.Rect(130, 370, 230, 420))
    shape.draw_line((230, 395), (360, 395))
    shape.draw_rect(pymupdf.Rect(360, 370, 460, 420))
    shape.finish(color=(0, 0, 0), fill=(0.9, 0.9, 0.9))
    shape.commit()
    page.insert_text((150, 398), "Leader", fontname="helv", fontsize=7)
    page.insert_text((380, 398), "Follower", fontname="helv", fontsize=7)
    page.insert_text(
        (50, 488), "Figure 5-1. A leader and its followers.", fontname="tiit", fontsize=10
    )
    page.insert_text((60, 520), "• Writes go to the leader.", fontname="tiro", fontsize=10)
    page.insert_text((60, 545), "• Reads may go to any follower.", fontname="tiro", fontsize=10)
    page.insert_textbox(pymupdf.Rect(50, 570, 545, 640), LOREM, fontname="tiro", fontsize=10)
    page.insert_text(
        (50, 770), "1 Leaders are also called primaries.", fontname="tiro", fontsize=7.5
    )
    page.insert_text((290, 815), str(number), fontname="helv", fontsize=8)


@pytest.fixture
def make_pdf(tmp_path: Path) -> Callable[[Callable[[Any], None], str], Path]:
    """Build a PDF from a function that fills a fresh document."""

    def make(fill: Callable[[Any], None], name: str = "doc.pdf") -> Path:
        doc = _doc()
        fill(doc)
        out = tmp_path / name
        doc.save(out)
        return out

    return make


@pytest.fixture
def book_pdf(tmp_path: Path) -> Path:
    """Three book pages with a TOC entry for the chapter title on page 1."""
    doc = _doc()
    for n in range(3):
        build_book_page(doc.new_page(), n + 101)
    doc.set_toc([[1, "Chapter 5. Replication", 1]])
    out = tmp_path / "book.pdf"
    doc.save(out)
    return out


SPLIT_HEAD = (
    "Many systems today are distributed. Some of them were not designed with the cloud in "
    "mind. Others, however, were designed from the ground up to be"
)
SPLIT_TAIL = (
    "cloud native and have been shown to scale well. They also recover from faults quickly. "
    "Operators like them."
)


@pytest.fixture
def split_pdf(tmp_path: Path) -> Path:
    """Three pages; the last paragraph of page 1 continues on page 2 (lower-case start)."""
    doc = _doc()
    page = doc.new_page()
    page.insert_text((50, 90), "Chapter 1. Foundations", fontname="tibo", fontsize=18)
    page.insert_textbox(pymupdf.Rect(50, 105, 545, 185), LOREM, fontname="tiro", fontsize=10)
    page.insert_textbox(pymupdf.Rect(50, 195, 545, 260), SPLIT_HEAD, fontname="tiro", fontsize=10)
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 60, 545, 140), SPLIT_TAIL, fontname="tiro", fontsize=10)
    page.insert_textbox(pymupdf.Rect(50, 150, 545, 230), LOREM, fontname="tiro", fontsize=10)
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(50, 60, 545, 140), LOREM, fontname="tiro", fontsize=10)
    out = tmp_path / "split.pdf"
    doc.save(out)
    return out


# Term-consistency fixture: 9 distinct "replication" paragraphs (3 per page) and their
# translations; pages 1-2 say "çoğaltma", page 3 says "replikasyon".
TERMS_PAGES = [
    [
        ("Replication keeps copies of the data on several machines.",
         "Çoğaltma, verinin kopyalarını birkaç makinede tutar."),
        ("We discuss replication in depth in this chapter.",
         "Bu bölümde çoğaltmanın ayrıntılarını tartışıyoruz."),
        ("Replication helps with availability during outages.",
         "Çoğaltmayı kesintiler sırasında erişilebilirlik için kullanırız."),
    ],
    [
        ("Synchronous replication is slow but safe.",
         "Eşzamanlı çoğaltma yavaştır ama güvenlidir."),
        ("Replication lag is a common problem for readers.",
         "Çoğaltma gecikmesi okuyucular için yaygın bir sorundur."),
        ("Chained replication forwards every write.", "Zincirli çoğaltma her yazmayı iletir."),
    ],
    [
        ("Leaderless replication is popular in some stores.",
         "Liderli olmayan replikasyon bazı depolarda popülerdir."),
        ("Replication across regions is hard to operate.",
         "Bölgeler arası replikasyonu işletmek zordur."),
        ("Asynchronous replication may lose recent writes.",
         "Asenkron replikasyon son yazmaları kaybedebilir."),
    ],
]  # fmt: skip


@pytest.fixture
def terms_pdf(tmp_path: Path) -> Path:
    doc = _doc()
    for paragraphs in TERMS_PAGES:
        page = doc.new_page()
        for n, (en, _) in enumerate(paragraphs):
            top = 80 + n * 60
            page.insert_textbox(
                pymupdf.Rect(50, top, 545, top + 40), en, fontname="tiro", fontsize=10
            )
    out = tmp_path / "terms.pdf"
    doc.save(out)
    return out


def seed_terms(repos: Any, book_id: int, provider: str = "fake", model: str = "fake") -> None:
    """Cache the TERMS_PAGES translations for an extracted ``terms_pdf`` book."""
    from rosetta_engine.store.repo import TranslationRow

    by_en = {en: tr for paragraphs in TERMS_PAGES for en, tr in paragraphs}
    rows = []
    for p in range(len(TERMS_PAGES)):
        page = repos.blocks.get_page(book_id, p)
        assert page is not None
        for b in page.blocks:
            if b.text in by_en:
                tr = by_en[b.text]
                rows.append(
                    TranslationRow(
                        book_id, p, b.text_hash, "tr", provider, model, tr, [tr], True, 1
                    )
                )
    assert len(rows) == sum(len(x) for x in TERMS_PAGES), [b.text for b in page.blocks]
    repos.translations.put_rows(rows)


@pytest.fixture
def two_column_pdf(tmp_path: Path) -> Path:
    doc = _doc()
    page = doc.new_page()
    page.insert_text((50, 60), "Chapter 5. Replication", fontname="tibo", fontsize=18)
    for x0, x1, text in ((50, 290, LEFT_TEXT), (320, 560, RIGHT_TEXT)):
        for y0, y1 in ((80, 300), (320, 540)):
            page.insert_textbox(pymupdf.Rect(x0, y0, x1, y1), text, fontname="tiro", fontsize=10)
    out = tmp_path / "two_col.pdf"
    doc.save(out)
    return out


@pytest.fixture
def lorem() -> str:
    return LOREM


@pytest.fixture
def ddia_path() -> Path:
    if not DDIA_PATH.is_file():
        pytest.skip("DDIA test book not available")
    return DDIA_PATH


@pytest.fixture(autouse=True)
def _no_claude_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests decide whether `claude` exists by patching shutil.which; never find the real one."""
    monkeypatch.setattr("rosetta_engine.translate.claude_locate.fallback_candidates", lambda: [])

"""Synthetic PDFs generated with PyMuPDF (no real book needed)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf
import pytest

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

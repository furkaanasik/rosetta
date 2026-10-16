from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf

from rosetta_engine.extract.furniture import build_furniture, is_furniture, normalize
from rosetta_engine.extract.pdf_reader import open_book, read_page

MakePdf = Callable[..., Path]


def test_repeated_header_and_page_number_are_furniture(make_pdf: MakePdf, lorem: str) -> None:
    def fill(doc: Any) -> None:
        for n in range(5):
            page = doc.new_page()
            header = f"Chapter 5: Replication | 1{n:02d}"
            page.insert_text((50, 30), header, fontname="helv", fontsize=8)
            page.insert_textbox(
                pymupdf.Rect(50, 100, 545, 400), lorem, fontname="tiro", fontsize=10
            )
            page.insert_text((290, 815), str(100 + n), fontname="helv", fontsize=8)

    doc = open_book(make_pdf(fill, "furn.pdf"))
    pages = [read_page(doc, n, graphics=False) for n in range(5)]

    model = build_furniture(pages, body_size=10)

    assert "chapter #: replication | #" in model.texts
    for page in pages:
        flags = [is_furniture(b, page.height, model, 10) for b in page.text_blocks]
        assert flags[0] and flags[-1]
        assert not any(flags[1:-1])


def test_large_title_in_top_band_is_not_furniture(make_pdf: MakePdf) -> None:
    def fill(doc: Any) -> None:
        doc.new_page().insert_text((50, 40), "Chapter 1", fontname="tibo", fontsize=24)

    doc = open_book(make_pdf(fill, "title.pdf"))
    page = read_page(doc, 0, graphics=False)
    model = build_furniture([page], body_size=10)

    assert not is_furniture(page.text_blocks[0], page.height, model, 10)


def test_normalize() -> None:
    assert normalize("70 |  Chapter 3:\nData") == "# | chapter #: data"

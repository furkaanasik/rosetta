from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf

from rosetta_engine.extract.extractor import extract_book_meta, extract_page
from rosetta_engine.extract.pdf_reader import open_book
from rosetta_engine.models import BlockType, PageBlocks

MakePdf = Callable[..., Path]


def _extract(make_pdf: MakePdf, lorem: str, draw: Callable[[Any], None]) -> PageBlocks:
    def fill(doc: Any) -> None:
        page = doc.new_page()
        # body text so the book's body size is 10pt
        page.insert_textbox(pymupdf.Rect(50, 600, 545, 800), lorem, fontname="tiro", fontsize=10)
        draw(page)

    doc = open_book(make_pdf(fill, "fig.pdf"))
    return extract_page(doc, 0, extract_book_meta(doc))


def _types(page: PageBlocks) -> list[BlockType]:
    return [b.type for b in page.blocks]


def test_grey_box_with_courier_is_code_not_figure(make_pdf: MakePdf, lorem: str) -> None:
    def draw(page: Any) -> None:
        page.draw_rect(pymupdf.Rect(50, 100, 400, 200), color=None, fill=(0.85, 0.85, 0.85))
        page.insert_text(
            (60, 120), "def f(x):\n    return x + 1\nprint(f(2))", fontname="cour", fontsize=9
        )

    page = _extract(make_pdf, lorem, draw)

    assert BlockType.IMAGE not in _types(page)
    code = [b for b in page.blocks if b.type == BlockType.CODE]
    assert len(code) == 1
    assert code[0].text == "def f(x):\n    return x + 1\nprint(f(2))"


def test_vector_figure_swallows_labels(make_pdf: MakePdf, lorem: str) -> None:
    def draw(page: Any) -> None:
        page.draw_rect(pymupdf.Rect(100, 100, 220, 160), color=(0, 0, 0))
        page.draw_line((220, 130), (330, 130), color=(0, 0, 0))
        page.draw_rect(pymupdf.Rect(330, 100, 450, 160), color=(0, 0, 0))
        page.insert_text((120, 133), "Leader", fontname="helv", fontsize=7)
        page.insert_text((350, 133), "Follower", fontname="helv", fontsize=7)

    page = _extract(make_pdf, lorem, draw)

    images = [b for b in page.blocks if b.type == BlockType.IMAGE]
    assert len(images) == 1
    assert images[0].bbox[0] <= 100 and images[0].bbox[2] >= 450
    assert all("Leader" not in b.text and "Follower" not in b.text for b in page.blocks)


def test_note_box_is_aside_paragraph(make_pdf: MakePdf, lorem: str) -> None:
    def draw(page: Any) -> None:
        page.draw_rect(pymupdf.Rect(50, 90, 545, 200), color=(0, 0, 0))
        page.insert_textbox(pymupdf.Rect(60, 100, 535, 190), lorem, fontname="tiro", fontsize=10)

    page = _extract(make_pdf, lorem, draw)

    assert BlockType.IMAGE not in _types(page)
    note = page.blocks[0]
    assert note.type == BlockType.PARAGRAPH
    assert note.aside


def test_small_icon_is_decoration_and_text_is_aside(make_pdf: MakePdf, lorem: str) -> None:
    def draw(page: Any) -> None:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), False)
        pix.clear_with(128)
        page.insert_image(pymupdf.Rect(60, 100, 90, 140), pixmap=pix)
        page.insert_textbox(
            pymupdf.Rect(100, 100, 500, 160), "A tip. " * 20, fontname="tiro", fontsize=9
        )

    page = _extract(make_pdf, lorem, draw)

    assert BlockType.IMAGE not in _types(page)
    tip = page.blocks[0]
    assert tip.type == BlockType.PARAGRAPH and tip.aside


def test_table_region_from_caption(make_pdf: MakePdf, lorem: str) -> None:
    def draw(page: Any) -> None:
        page.insert_text((50, 80), "Table 1-1. Comparing systems", fontname="tiit", fontsize=10)
        page.draw_rect(pymupdf.Rect(50, 88, 545, 102), color=None, fill=(0, 0, 0))
        for i, row in enumerate(
            ["Property  OLTP  OLAP", "Reads  Point  Aggregate", "Size  GB  PB"]
        ):
            page.insert_text((55, 98 + 14 * i), row, fontname="helv", fontsize=9)
        page.draw_line((50, 135), (545, 135), color=(0, 0, 0))

    page = _extract(make_pdf, lorem, draw)

    assert _types(page)[:3] == [BlockType.CAPTION, BlockType.TABLE, BlockType.PARAGRAPH]
    table = page.blocks[1]
    assert table.bbox[3] >= 135
    assert all("Aggregate" not in b.text for b in page.blocks)

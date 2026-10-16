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


def test_crop_marks_larger_than_page_do_not_swallow_text(make_pdf: MakePdf, lorem: str) -> None:
    # Print-ready PDFs (e.g. Clean Code) carry stroke-only trim/crop marks that extend past the
    # page edges; they must not become a page-sized figure that swallows all the text.
    def draw(page: Any) -> None:
        w, h = page.rect.width, page.rect.height
        page.draw_rect(pymupdf.Rect(-38, -8, w + 38, h + 46), color=(0, 0, 0), fill=None)
        page.draw_polyline(
            [(-38, -8), (w + 38, -8), (w + 38, h + 46), (-38, h + 46), (-38, -8)],
            color=(0, 0, 0),
        )
        page.insert_textbox(pymupdf.Rect(50, 80, 545, 400), lorem, fontname="tiro", fontsize=10)

    page = _extract(make_pdf, lorem, draw)

    types = _types(page)
    assert BlockType.IMAGE not in types
    assert BlockType.TABLE not in types
    assert types.count(BlockType.PARAGRAPH) >= 2
    assert not any(b.aside for b in page.blocks)


def test_page_wide_listing_box_keeps_code_and_prose(make_pdf: MakePdf, lorem: str) -> None:
    # A drawn listing frame covering most of the page, holding code and a few prose lines,
    # is running text: code stays CODE, prose stays PARAGRAPH, nothing becomes a figure.
    code = "\n".join(f"    int value{i} = compute({i});" for i in range(14))

    def draw(page: Any) -> None:
        page.draw_rect(pymupdf.Rect(30, 40, 565, 580), color=(0, 0, 0), fill=None)
        page.insert_text((60, 70), code, fontname="cour", fontsize=8)
        page.insert_textbox(
            pymupdf.Rect(50, 300, 545, 360), lorem[:300], fontname="tiro", fontsize=10
        )

    page = _extract(make_pdf, lorem, draw)

    types = _types(page)
    assert BlockType.IMAGE not in types
    assert BlockType.CODE in types
    assert "value13" in next(b.text for b in page.blocks if b.type == BlockType.CODE)


def test_large_vector_diagram_with_small_labels_is_still_a_figure(
    make_pdf: MakePdf, lorem: str
) -> None:
    def draw(page: Any) -> None:
        page.draw_rect(pymupdf.Rect(40, 60, 555, 560), color=(0, 0, 0), fill=None)
        for row in range(5):
            y = 90 + row * 90
            page.draw_rect(pymupdf.Rect(80, y, 220, y + 50), color=(0, 0, 0))
            page.draw_rect(pymupdf.Rect(360, y, 500, y + 50), color=(0, 0, 0))
            page.draw_line((220, y + 25), (360, y + 25), color=(0, 0, 0))
            page.insert_text((95, y + 28), f"Node {row}", fontname="helv", fontsize=7)
            page.insert_text((375, y + 28), f"Replica {row}", fontname="helv", fontsize=7)

    page = _extract(make_pdf, lorem, draw)

    images = [b for b in page.blocks if b.type == BlockType.IMAGE]
    assert len(images) == 1
    x0, y0, x1, y1 = images[0].bbox
    assert x0 <= 40 and y0 <= 60 and x1 >= 555 and y1 >= 560


CLEAN_CODE = Path.home() / "SSD/Books/clean_code.pdf"


def test_clean_code_pages_keep_their_text() -> None:
    import pytest

    if not CLEAN_CODE.is_file():
        pytest.skip("Clean Code PDF not available")
    doc = open_book(CLEAN_CODE)
    meta = extract_book_meta(doc)
    for page_1 in (49, 157):  # crop marks; crop marks + a page-wide listing frame
        page = extract_page(doc, page_1 - 1, meta)
        area = page.width * page.height
        big = [
            b
            for b in page.blocks
            if b.type in (BlockType.IMAGE, BlockType.TABLE)
            and (b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1]) > 0.5 * area
        ]
        assert not big, page_1
        assert any(b.translatable for b in page.blocks), page_1
    p49 = extract_page(doc, 48, meta)
    assert any(b.type == BlockType.HEADING and "Intention-Revealing" in b.text for b in p49.blocks)
    assert any(b.type == BlockType.CODE for b in p49.blocks)

from pathlib import Path

from rosetta_engine.extract.extractor import extract_book_meta, extract_page
from rosetta_engine.extract.layout import LayoutItem, reading_order
from rosetta_engine.extract.pdf_reader import open_book

H = 842.0


def test_two_columns_left_column_first() -> None:
    items = [
        LayoutItem(0, (50, 80, 290, 300)),
        LayoutItem(1, (320, 80, 560, 300)),
        LayoutItem(2, (50, 320, 290, 540)),
        LayoutItem(3, (320, 320, 560, 540)),
    ]

    assert reading_order(items, H) == [0, 2, 1, 3]


def test_full_width_heading_and_footnote_cut_bands() -> None:
    items = [
        LayoutItem(10, (50, 700, 560, 740)),  # full-width footnote
        LayoutItem(0, (50, 40, 560, 70)),  # full-width heading
        LayoutItem(1, (50, 80, 290, 300)),
        LayoutItem(2, (320, 80, 560, 300)),
        LayoutItem(3, (50, 320, 290, 540)),
        LayoutItem(4, (320, 320, 560, 540)),
    ]

    assert reading_order(items, H) == [0, 1, 3, 2, 4, 10]


def test_single_column_with_indented_code_keeps_order() -> None:
    items = [
        LayoutItem(0, (72, 50, 432, 120)),
        LayoutItem(1, (110, 125, 250, 180), mono=True),
        LayoutItem(2, (72, 185, 432, 260)),
        LayoutItem(3, (300, 265, 330, 275)),  # short line far right: no fake column
        LayoutItem(4, (72, 280, 432, 300)),
    ]

    assert reading_order(items, H) == [0, 1, 2, 3, 4]


def test_margin_note_is_not_a_column() -> None:
    items = [
        LayoutItem(0, (72, 50, 300, 400)),
        LayoutItem(1, (72, 410, 300, 700)),
        LayoutItem(2, (330, 60, 400, 90)),  # small side note, too little coverage
    ]

    assert reading_order(items, H) == [0, 2, 1]


def test_two_column_pdf(two_column_pdf: Path) -> None:
    doc = open_book(two_column_pdf)
    page = extract_page(doc, 0, extract_book_meta(doc))

    starts = [b.text.split(".")[0] for b in page.blocks]

    assert starts[0] == "Chapter 5"
    assert starts[1:] == ["Left column", "Left column", "Right column", "Right column"]

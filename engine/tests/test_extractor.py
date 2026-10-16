from pathlib import Path
from typing import Any

import pymupdf
import pytest

from rosetta_engine.errors import ExtractionError
from rosetta_engine.extract.extractor import (
    EXTRACTOR_VERSION,
    BookMeta,
    extract_book_meta,
    extract_page,
)
from rosetta_engine.extract.pdf_reader import file_hash, open_book
from rosetta_engine.models import TRANSLATABLE, Block, BlockType, text_hash

T = BlockType


def test_synthetic_book_page_types_and_order(book_pdf: Path) -> None:
    doc = open_book(book_pdf)
    meta = extract_book_meta(doc)

    page = extract_page(doc, 0, meta)

    assert [b.type for b in page.blocks] == [
        T.FURNITURE, T.HEADING, T.PARAGRAPH, T.PARAGRAPH, T.CODE, T.IMAGE, T.CAPTION,
        T.LIST_ITEM, T.LIST_ITEM, T.PARAGRAPH, T.FOOTNOTE, T.FURNITURE,
    ]  # fmt: skip
    assert [b.order for b in page.blocks] == list(range(len(page.blocks)))
    heading = page.blocks[1]
    assert heading.heading_level == 1 and heading.text == "Chapter 5. Replication"
    assert page.blocks[4].text.splitlines()[1] == "  WHERE id = 42"
    assert page.blocks[7].text == "Writes go to the leader."


def test_blocks_carry_hash_sentences_family(book_pdf: Path) -> None:
    doc = open_book(book_pdf)
    page = extract_page(doc, 1, extract_book_meta(doc))

    for b in page.blocks:
        assert b.page_no == 1
        if b.type in (T.IMAGE, T.TABLE):
            assert b.text == ""
            continue
        assert b.text_hash == text_hash(b.text)
        assert bool(b.sentences) == (b.type in TRANSLATABLE)
    code = next(b for b in page.blocks if b.type == T.CODE)
    assert code.family == "mono"
    para = next(b for b in page.blocks if b.type == T.PARAGRAPH)
    assert para.family == "serif" and len(para.sentences) == 4


def test_meta_round_trips_as_json(book_pdf: Path) -> None:
    meta = extract_book_meta(open_book(book_pdf))

    again = BookMeta.model_validate_json(meta.model_dump_json())

    assert again == meta
    assert again.page_count == 3
    assert again.extractor_version == EXTRACTOR_VERSION
    assert again.toc_for_page(0)


def test_out_of_range_page_raises(book_pdf: Path) -> None:
    doc = open_book(book_pdf)
    meta = extract_book_meta(doc)

    with pytest.raises(ExtractionError):
        extract_page(doc, 3, meta)


def test_page_without_text_layer() -> None:
    doc = pymupdf.open()
    doc.new_page()
    meta = extract_book_meta(doc)

    page = extract_page(doc, 0, meta)

    assert not page.has_text_layer and page.blocks == []


def test_continues_on_next_page() -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), "This sentence goes on and on", fontname="tiro", fontsize=10)
    blocks = extract_page(doc, 0, extract_book_meta(doc))

    assert blocks.continues_on_next_page


def test_file_hash_is_content_based(book_pdf: Path, tmp_path: Path) -> None:
    copy = tmp_path / "elsewhere.pdf"
    copy.write_bytes(book_pdf.read_bytes())

    assert file_hash(copy) == file_hash(book_pdf)
    assert len(file_hash(book_pdf)) == 64


# --- real book (skipped when absent) --------------------------------------------------------


DDIA = Path.home() / "SSD/Books/Designing Data-Intensive Applications 2nd.pdf"


@pytest.fixture(scope="module")
def ddia() -> tuple[Any, BookMeta]:
    if not DDIA.is_file():
        pytest.skip("DDIA test book not available")
    doc = open_book(DDIA)
    return doc, extract_book_meta(doc)


def _page_types(ddia: tuple[Any, BookMeta], page_1based: int) -> list[Block]:
    doc, meta = ddia
    return extract_page(doc, page_1based - 1, meta).blocks


def test_ddia_chapter_start(ddia: tuple[Any, BookMeta]) -> None:
    blocks = _page_types(ddia, 25)

    assert blocks[0].type == T.HEADING and blocks[0].heading_level == 1
    assert blocks[1].type == T.PARAGRAPH and blocks[1].aside  # epigraph
    assert blocks[2].aside and blocks[2].text.startswith("—Thomas Sowell")
    assert blocks[-1].type == T.FURNITURE and blocks[-1].text == "1"


def test_ddia_table_and_note(ddia: tuple[Any, BookMeta]) -> None:
    types = [b.type for b in _page_types(ddia, 30)]

    assert types[:3] == [T.CAPTION, T.TABLE, T.PARAGRAPH]
    assert _page_types(ddia, 30)[2].aside


def test_ddia_code_inline_code_and_subheading(ddia: tuple[Any, BookMeta]) -> None:
    blocks = _page_types(ddia, 59)

    assert blocks[0].type == T.CODE
    assert "`follows`" in blocks[1].text
    heads = [b for b in blocks if b.type == T.HEADING]
    assert [(h.text, h.heading_level) for h in heads] == [
        ("Materializing and Updating Timelines", 3)
    ]


def test_ddia_figure_example_code(ddia: tuple[Any, BookMeta]) -> None:
    types = [b.type for b in _page_types(ddia, 94)]

    assert types == [T.IMAGE, T.CAPTION, T.CAPTION, T.CODE, T.FURNITURE]


def test_ddia_numbered_list_with_vector_markers(ddia: tuple[Any, BookMeta]) -> None:
    blocks = _page_types(ddia, 115)

    assert blocks[0].type == T.CODE
    items = [b for b in blocks if b.type == T.LIST_ITEM]
    assert [b.list_marker for b in items] == ["1", "2", "3", "4", "5"]

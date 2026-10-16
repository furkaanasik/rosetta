from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from rosetta_engine.extract.extractor import (
    EXTRACTOR_VERSION,
    BookMeta,
    extract_book_meta,
    extract_page,
)
from rosetta_engine.extract.markers import Marker, assign_numbers, detect, to_char
from rosetta_engine.extract.pdf_reader import open_book, read_page
from rosetta_engine.models import Block, BlockType

T = BlockType
CALLOUTS = {chr(c) for c in range(0x2776, 0x2780)}
DARK = (0.13, 0.12, 0.12)


def _marker(page: Any, x: float, y: float, d: float) -> None:
    """A dark circle with a white path inside whose command sequence is not in DIGIT_OPS."""
    shape = page.new_shape()
    shape.draw_circle((x + d / 2, y + d / 2), d / 2)
    shape.finish(color=DARK, fill=DARK)
    shape.draw_polyline(
        [(x + d * 0.4, y + d * 0.2), (x + d * 0.6, y + d * 0.5), (x + d * 0.4, y + d * 0.8)]
    )
    shape.finish(color=None, fill=(1, 1, 1), closePath=True)
    shape.commit()


def _fill(doc: Any) -> None:
    page = doc.new_page()
    for k in range(6):  # body text so stats find a body size
        rect = pymupdf.Rect(72, 60 + k * 30, 520, 88 + k * 30)
        body = "Plain body text for the statistics. " * 3
        page.insert_textbox(rect, body, fontname="tiro", fontsize=10)
    page.insert_text((72, 300), "SELECT * FROM vertices", fontname="cour", fontsize=9)
    _marker(page, 250, 293, 7)
    page.insert_text((72, 312), "  WHERE label = 'x'", fontname="cour", fontsize=9)
    _marker(page, 250, 305, 7)
    page.insert_text((96, 360), "First explanation of the query.", fontname="tiro", fontsize=10)
    _marker(page, 80, 352, 8.5)
    page.insert_text((96, 390), "Second explanation of the query.", fontname="tiro", fontsize=10)
    _marker(page, 80, 382, 8.5)


@pytest.fixture
def marker_pdf(make_pdf: Callable[[Callable[[Any], None], str], Path]) -> Path:
    return make_pdf(_fill, "markers.pdf")


def test_detects_markers_and_kinds_with_unknown_digits(marker_pdf: Path) -> None:
    raw = read_page(open_book(marker_pdf), 0)

    found = detect(raw)

    assert [m.kind for m in found] == ["code", "code", "list", "list"]
    assert all(m.number is None for m in found)


def test_unknown_digits_numbered_sequentially_per_kind() -> None:
    def mk(kind: str, y: float, n: int | None = None) -> Marker:
        return Marker(bbox=(0, y, 7, y + 7), kind=kind, number=n)  # type: ignore[arg-type]

    previous = [mk("list", 0, 4), mk("code", 5, 2)]

    out = assign_numbers(
        [mk("code", 10), mk("list", 20), mk("list", 30, 9), mk("list", 40)], previous
    )

    assert [m.number for m in out] == [3, 5, 9, 10]
    assert [m.known for m in out] == [False, False, True, False]


def test_to_char() -> None:
    assert to_char(1) == "❶"
    assert to_char(10) == "❿"
    assert to_char(11) == "(11)"


def test_synthetic_page_callouts_in_code_and_list_numbers(marker_pdf: Path) -> None:
    doc = open_book(marker_pdf)

    blocks = extract_page(doc, 0, extract_book_meta(doc)).blocks

    code = next(b for b in blocks if b.type == T.CODE)
    assert code.text.split("\n")[0].endswith("SELECT * FROM vertices ❶")
    assert code.text.split("\n")[1].endswith("WHERE label = 'x' ❷")
    items = [b for b in blocks if b.type == T.LIST_ITEM]
    assert [(b.list_marker, b.text) for b in items] == [
        ("1", "First explanation of the query."),
        ("2", "Second explanation of the query."),
    ]
    assert T.IMAGE not in {b.type for b in blocks}


def test_extractor_version_bumped() -> None:
    assert EXTRACTOR_VERSION == 2


# --- real book (skipped when absent) --------------------------------------------------------

DDIA = Path.home() / "SSD/Books/Designing Data-Intensive Applications 2nd.pdf"


@pytest.fixture(scope="module")
def ddia() -> tuple[Any, BookMeta]:
    if not DDIA.is_file():
        pytest.skip("DDIA test book not available")
    doc = open_book(DDIA)
    return doc, extract_book_meta(doc)


def _blocks(ddia: tuple[Any, BookMeta], page_1based: int) -> list[Block]:
    doc, meta = ddia
    return extract_page(doc, page_1based - 1, meta).blocks


def _callout_lines(blocks: list[Block]) -> list[str]:
    return [
        ln.strip()
        for b in blocks
        if b.type == T.CODE
        for ln in b.text.split("\n")
        if CALLOUTS & set(ln)
    ]


def _list_markers(blocks: list[Block]) -> list[str | None]:
    return [b.list_marker for b in blocks if b.type == T.LIST_ITEM and b.list_marker != "•"]


def test_ddia_p115_callouts_on_the_right_code_lines(ddia: tuple[Any, BookMeta]) -> None:
    blocks = _blocks(ddia, 115)

    lines = _callout_lines(blocks)

    assert [ln[-1] for ln in lines] == ["❸", "❹", "❺", "❻"]
    assert lines[0].endswith("'name' = 'Europe' ❸")
    assert lines[1].startswith("born_in_usa(vertex_id) AS (")
    assert lines[3].startswith("JOIN born_in_usa")
    assert _list_markers(blocks) == ["1", "2", "3", "4", "5"]


def test_ddia_p115_list_text_unchanged(ddia: tuple[Any, BookMeta]) -> None:
    items = [b for b in _blocks(ddia, 115) if b.type == T.LIST_ITEM]

    assert items[0].text.startswith("First find the vertex whose `name` property")
    assert items[1].text.startswith("Follow all incoming `within` edges")
    assert not any(CALLOUTS & set(b.text) for b in items)


@pytest.mark.parametrize(
    ("page", "code", "lists"),
    [
        (107, ["❶"], ["1"]),
        (114, ["❶", "❷"], []),
        (116, [], ["6"]),
        (325, ["❶"], ["1"]),
        (329, ["❶"], ["1"]),
        (478, ["❶", "❷", "❸", "❹", "❺", "❻"], ["1"]),
        (479, [], ["2", "3", "4", "5", "6"]),
        (480, ["❶", "❷", "❸", "❹", "❺"], ["1", "2", "3", "4", "5"]),
    ],
)
def test_ddia_marker_pages(
    ddia: tuple[Any, BookMeta], page: int, code: list[str], lists: list[str]
) -> None:
    blocks = _blocks(ddia, page)

    assert [ln[-1] for ln in _callout_lines(blocks)] == code
    assert _list_markers(blocks) == lists
    assert T.IMAGE not in {b.type for b in blocks}

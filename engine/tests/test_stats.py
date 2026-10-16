from collections.abc import Callable
from pathlib import Path
from typing import Any

import pymupdf

from rosetta_engine.extract.pdf_reader import open_book, read_page
from rosetta_engine.extract.stats import TypographyStats, compute_stats, sample_pages

MakePdf = Callable[..., Path]


def _book(make_pdf: MakePdf, lorem: str) -> Any:
    def fill(doc: Any) -> None:
        for _ in range(3):
            page = doc.new_page()
            page.insert_text((50, 60), "Big Title", fontname="tibo", fontsize=18)
            page.insert_text((50, 90), "Smaller Title", fontname="tibo", fontsize=14)
            page.insert_textbox(
                pymupdf.Rect(50, 100, 545, 400), lorem * 2, fontname="tiro", fontsize=10
            )
            page.insert_text((50, 450), "print('x')", fontname="cour", fontsize=20)

    return open_book(make_pdf(fill, "stats.pdf"))


def test_body_and_heading_sizes(make_pdf: MakePdf, lorem: str) -> None:
    doc = _book(make_pdf, lorem)

    stats = compute_stats(read_page(doc, n, graphics=False) for n in range(3))

    assert stats.body_size == 10
    assert stats.heading_sizes == {18: 1, 14: 2}  # 20pt mono is ignored
    assert stats.body_font_family == "serif"
    assert stats.level_for_size(14.1) == 2


def test_stats_json_round_trip(make_pdf: MakePdf, lorem: str) -> None:
    doc = _book(make_pdf, lorem)
    stats = compute_stats(read_page(doc, n, graphics=False) for n in range(3))

    assert TypographyStats.model_validate_json(stats.model_dump_json()) == stats


def test_sample_pages_skips_front_matter_and_caps() -> None:
    pages = sample_pages(673)

    assert len(pages) == 40
    assert min(pages) == int(673 * 0.05)
    assert sample_pages(3) == [0, 1, 2]

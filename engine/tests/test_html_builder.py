from pathlib import Path
from typing import Any

import pymupdf

from rosetta_engine.models import Block, BlockType, Book, PageBlocks, Translation, text_hash
from rosetta_engine.render.html_builder import (
    build_page_html,
    callout_glyph,
    code_markup,
    inline,
    marker_number,
    page_filename,
    write_index,
    write_page,
)

BOOK = Book(id=1, file_hash="ab" * 32, title="Test Book", page_count=10)


def mk(
    order: int,
    type_: BlockType,
    text: str = "",
    *,
    sentences: list[str] | None = None,
    level: int | None = None,
    marker: str | None = None,
    bbox: tuple[float, float, float, float] = (50, 50, 300, 80),
    page_no: int = 0,
) -> Block:
    if sentences is None and type_ in (BlockType.PARAGRAPH, BlockType.HEADING,
                                       BlockType.LIST_ITEM, BlockType.CAPTION,
                                       BlockType.FOOTNOTE):  # fmt: skip
        sentences = [text] if text else []
    return Block(
        page_no=page_no,
        order=order,
        type=type_,
        bbox=bbox,
        font="MinionPro-Regular",
        size=10.5,
        bold=False,
        italic=False,
        family="mono" if type_ is BlockType.CODE else "serif",
        heading_level=level,
        list_marker=marker,
        text=text,
        sentences=sentences or [],
        text_hash=text_hash(text or f"{type_}:{bbox}"),
    )


def page_of(*blocks: Block, page_no: int = 0) -> PageBlocks:
    return PageBlocks(page_no=page_no, width=504, height=661.5, has_text_layer=True,
                      blocks=list(blocks))  # fmt: skip


def tr(block: Block, *sentences: str, aligned: bool = True) -> Translation:
    return Translation(page_no=block.page_no, text_hash=block.text_hash,
                       sentences=list(sentences), text=" ".join(sentences),
                       sentence_aligned=aligned)  # fmt: skip


def render(page: PageBlocks, tmp_path: Path, trs: list[Translation] | None = None,
           mode: Any = "tr") -> str:  # fmt: skip
    return build_page_html(BOOK, page, {t.text_hash: t for t in trs or []}, mode, tmp_path)


def test_script_in_translation_is_escaped(tmp_path: Path) -> None:
    p = mk(0, BlockType.PARAGRAPH, "Hello world.")

    html = render(page_of(p), tmp_path, [tr(p, "<script>alert(1)</script> Merhaba.")])

    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_backticks_become_code_after_escaping() -> None:
    assert inline("Call `a<b>()` now") == "Call <code>a&lt;b&gt;()</code> now"
    assert inline("Use `` x`y `` here") == "Use <code>x`y</code> here"
    assert inline("<b>no code</b>") == "&lt;b&gt;no code&lt;/b&gt;"


def test_inline_code_in_translation(tmp_path: Path) -> None:
    p = mk(0, BlockType.PARAGRAPH, "Use `follows` table.")

    html = render(page_of(p), tmp_path, [tr(p, "`follows` tablosunu kullan.")])

    assert "<code>follows</code> tablosunu kullan." in html


def test_code_block_verbatim(tmp_path: Path) -> None:
    code = "if (a < b) {\n    return x && y;\n}"
    c = mk(0, BlockType.CODE, code)

    html = render(page_of(c), tmp_path)

    assert "<pre" in html
    assert "if (a &lt; b) {\n    return x &amp;&amp; y;\n}</code></pre>" in html


def test_heading_levels_and_clamp(tmp_path: Path) -> None:
    blocks = [
        mk(0, BlockType.HEADING, "Chapter", level=1),
        mk(1, BlockType.HEADING, "Section", level=3),
        mk(2, BlockType.HEADING, "Deep", level=9),
        mk(3, BlockType.HEADING, "Unknown", level=None),
    ]

    html = render(page_of(*blocks), tmp_path)

    assert '<h1 data-block="0-0"' in html
    assert '<h3 data-block="0-1"' in html
    assert '<h6 data-block="0-2"' in html
    assert '<h2 data-block="0-3"' in html


def test_data_block_and_sentence_spans(tmp_path: Path) -> None:
    p = mk(4, BlockType.PARAGRAPH, "One. Two.", sentences=["One.", "Two."], page_no=40)

    html = render(page_of(p, page_no=40), tmp_path, [tr(p, "Bir.", "İki.")])

    assert 'data-block="40-4"' in html
    assert '<span data-s="0">Bir.</span> <span data-s="1">İki.</span>' in html
    assert "font-size: calc(var(--scale) * 10.5pt)" in html


def test_furniture_hidden_in_tr_shown_in_debug(tmp_path: Path) -> None:
    f = mk(9, BlockType.FURNITURE, "70 | Chapter 3: Data Models")
    p = mk(0, BlockType.PARAGRAPH, "Body.")
    page = page_of(p, f)

    assert "Chapter 3: Data Models" not in render(page, tmp_path)
    assert "Chapter 3: Data Models" not in render(page, tmp_path, mode="review")
    debug = render(page, tmp_path, mode="debug")
    assert "Chapter 3: Data Models" in debug
    assert "t-furniture" in debug
    assert '<html lang="en">' in debug


def test_list_grouping_ordered_and_unordered(tmp_path: Path) -> None:
    blocks = [
        mk(0, BlockType.LIST_ITEM, "First", marker="•"),
        mk(1, BlockType.LIST_ITEM, "Second", marker="•"),
        mk(2, BlockType.PARAGRAPH, "Between."),
        mk(3, BlockType.LIST_ITEM, "Step one", marker=""),
        mk(4, BlockType.LIST_ITEM, "Step two", marker=""),
        mk(5, BlockType.LIST_ITEM, "Numbered", marker="3."),
    ]

    html = render(page_of(*blocks), tmp_path)

    assert html.count("<ul") == 1
    assert html.count("<ol") == 1
    ul = html[html.index("<ul") : html.index("</ul>")]
    assert "First" in ul and "Second" in ul
    ol = html[html.index("<ol") : html.index("</ol>")]
    assert "Step one" in ol and "Numbered" in ol


def test_untranslated_block_shows_original(tmp_path: Path) -> None:
    a = mk(0, BlockType.PARAGRAPH, "Translated.")
    b = mk(1, BlockType.PARAGRAPH, "Not yet.")

    html = render(page_of(a, b), tmp_path, [tr(a, "Çevrildi.")])

    assert "Çevrildi." in html
    assert "Not yet." in html
    assert html.count("untranslated") == 1
    assert '<html lang="tr">' in html


def test_review_pairs_en_and_tr(tmp_path: Path) -> None:
    a = mk(0, BlockType.PARAGRAPH, "One. Two.", sentences=["One.", "Two."])
    b = mk(1, BlockType.PARAGRAPH, "Three. Four.", sentences=["Three.", "Four."])

    html = render(
        page_of(a, b), tmp_path, [tr(a, "Bir.", "İki."), tr(b, "Üç dört.", aligned=False)],
        mode="review",
    )  # fmt: skip

    row_a = html[html.index('data-block="0-0"') - 200 : html.index("İki.")]
    assert 'data-aligned="1"' in row_a
    assert "Two." in row_a
    assert 'data-aligned="0"' in html
    assert "Üç dört." in html
    assert "<script>" in html  # our own hover script


def test_caption_attached_to_figure_and_code(tmp_path: Path) -> None:
    blocks = [
        mk(0, BlockType.IMAGE, bbox=(72, 70, 432, 300)),
        mk(1, BlockType.CAPTION, "Figure 3-1. A graph."),
        mk(2, BlockType.CAPTION, "Example 3-1. A query."),
        mk(3, BlockType.CODE, "SELECT 1;"),
    ]

    html = render(page_of(*blocks), tmp_path)

    first = html[html.index("<figure") : html.index("</figure>")]
    assert "Figure 3-1." in first and "Example" not in first
    rest = html[html.index("</figure>") + len("</figure>") :]
    assert rest.index("<figure") < rest.index("Example 3-1.") < rest.index("SELECT 1;")
    assert rest.index("SELECT 1;") < rest.index("</figure>")


def test_footnotes_rendered_at_end(tmp_path: Path) -> None:
    fn = mk(0, BlockType.FOOTNOTE, "1 A footnote.")
    p = mk(1, BlockType.PARAGRAPH, "Body text.")

    html = render(page_of(fn, p), tmp_path)

    assert (
        html.index("Body text.")
        < html.index('<aside class="footnotes">')
        < html.index("1 A footnote.")
    )


def test_image_crop_written(tmp_path: Path, book_pdf: Path) -> None:
    doc = pymupdf.open(book_pdf)
    img = mk(3, BlockType.IMAGE, bbox=(100, 340, 495, 470))
    out = tmp_path / "out"

    path = write_page(BOOK, page_of(img), {}, "tr", out, doc=doc)

    crop = out / "assets" / "p001_b3.png"
    assert crop.is_file() and crop.stat().st_size > 0
    assert path == out / "p001.tr.html"
    assert 'src="assets/p001_b3.png"' in path.read_text()
    assert (out / "style.css").is_file()


def test_missing_crop_without_doc_gives_placeholder(tmp_path: Path) -> None:
    img = mk(0, BlockType.TABLE, bbox=(72, 70, 432, 195))

    html = render(page_of(img), tmp_path)

    assert 'role="img"' in html
    assert "<img" not in html


def test_write_index_lists_pages(tmp_path: Path) -> None:
    path = write_index(BOOK, tmp_path, [(41, ["tr", "review"]), (40, ["debug"])])

    html = path.read_text()
    assert html.index("p041.debug.html") < html.index("p042.tr.html")
    assert "p042.review.html" in html
    assert page_filename(0, "review") == "p001.review.html"


def test_marker_number_and_callout_glyph() -> None:
    assert marker_number("3") == 3
    assert marker_number("3.") == 3
    assert marker_number("(12)") == 12
    assert marker_number("•") is None
    assert marker_number("") is None
    assert callout_glyph("3") == "❸"
    assert callout_glyph("10") == "❿"
    assert callout_glyph("3.") is None
    assert callout_glyph("11") is None


def test_list_starting_at_six_gets_ol_start(tmp_path: Path) -> None:
    items = [mk(i, BlockType.LIST_ITEM, f"Step {n}.", marker=f"{n}.") for i, n in enumerate((6, 7))]

    html = render(page_of(*items), tmp_path)

    assert '<ol class="list" start="6">' in html
    assert " value=" not in html  # consecutive numbering needs no per-item value


def test_list_with_gap_sets_li_values(tmp_path: Path) -> None:
    items = [
        mk(i, BlockType.LIST_ITEM, f"Step {n}.", marker=f"{n}.") for i, n in enumerate((1, 2, 5))
    ]

    html = render(page_of(*items), tmp_path)

    assert '<ol class="list">' in html
    assert 'value="1"' in html and 'value="2"' in html and 'value="5"' in html


def test_callout_list_items_show_glyph_and_keep_value(tmp_path: Path) -> None:
    items = [
        mk(i, BlockType.LIST_ITEM, f"Explain {n}.", marker=str(n)) for i, n in enumerate((6, 7))
    ]

    html = render(page_of(*items), tmp_path)

    assert '<ol class="list" start="6">' in html
    assert 'class="callout" aria-hidden="true">❻</span>' in html
    assert 'value="6"' in html and 'value="7"' in html
    assert "callout-item" in html


def test_empty_marker_list_stays_plain_ol(tmp_path: Path) -> None:
    items = [mk(i, BlockType.LIST_ITEM, f"Item {i}.", marker="") for i in range(2)]

    html = render(page_of(*items), tmp_path)

    assert '<ol class="list">' in html
    assert "start=" not in html and " value=" not in html


def test_code_callouts_wrapped_after_escaping(tmp_path: Path) -> None:
    code = mk(0, BlockType.CODE, "if a < b: ❸\n  run() ❹")

    html = render(page_of(code), tmp_path)

    assert code_markup("x < y ❸") == 'x &lt; y <span class="callout">❸</span>'
    assert 'a &lt; b: <span class="callout">❸</span>' in html
    assert '<span class="callout">❹</span>' in html
    assert "a < b" not in html


def test_review_keeps_list_numbering(tmp_path: Path) -> None:
    item = mk(0, BlockType.LIST_ITEM, "Follow edges.", marker="6")

    html = render(page_of(item), tmp_path, [tr(item, "Kenarları izle.")], mode="review")

    assert html.count('<ol class="list" start="6">') == 2  # EN and TR cells
    assert html.count('value="6"') == 2
    assert html.count(">❻</span>") == 2

"""Learn view mode: clickable words, <ruby> meanings for unknown lemmas, escaping."""

from __future__ import annotations

from pathlib import Path

from rosetta_engine.models import Block, BlockType, Book, PageBlocks, Translation, text_hash
from rosetta_engine.render.html_builder import LearnOptions, build_page_html, learn_markup

BOOK = Book(id=1, file_hash="a" * 64, title="T", page_count=10)


def _block(order: int, text: str, t: BlockType = BlockType.PARAGRAPH) -> Block:
    return Block(
        page_no=0, order=order, type=t, bbox=(0, 0, 1, 1), font="f", size=10, bold=False,
        italic=False, text=text, sentences=[text] if t is not BlockType.CODE else [],
        text_hash=text_hash(text),
    )  # fmt: skip


def _lemma(word: str) -> str:
    return {"replicated": "replicate", "queries": "query"}.get(word, word)


OPTS = LearnOptions(unknown={"replicate": "çoğaltmak", "latency": ""}, lemma_of=_lemma)


def test_learn_markup_wraps_words_and_rubies_unknown() -> None:
    html = str(learn_markup("Data is replicated; latency.", OPTS))

    assert '<span class="w" data-w="data" data-l="data">Data</span>' in html
    assert (
        '<ruby class="w unknown" data-w="replicated" data-l="replicate">replicated'
        "<rt>çoğaltmak</rt></ruby>"
    ) in html
    assert '<ruby class="w unknown" data-w="latency" data-l="latency">latency</ruby>' in html
    assert html.endswith(".")


def test_learn_markup_escapes_and_keeps_inline_code() -> None:
    html = str(learn_markup("Use `a<b()` & <script>alert(1)</script> queries", OPTS))

    assert "<script>" not in html
    assert "&lt;" in html and "&amp;" in html
    assert "<code>a&lt;b()</code>" in html
    assert 'data-l="query"' in html


def test_learn_page_shows_original_not_translation(tmp_path: Path) -> None:
    p = _block(0, "Data is replicated.")
    code = _block(1, "x = replicated()", BlockType.CODE)
    page = PageBlocks(page_no=0, width=1, height=1, has_text_layer=True, blocks=[p, code])
    tr = {p.text_hash: Translation(page_no=0, text_hash=p.text_hash, sentences=["Veri."],
                                   text="Veri.", sentence_aligned=True)}  # fmt: skip

    html = build_page_html(BOOK, page, tr, "learn", tmp_path, learn=OPTS)

    assert 'class="mode-learn"' in html
    assert '<html lang="en">' in html
    assert "Veri." not in html
    assert "<rt>çoğaltmak</rt>" in html
    assert "untranslated" not in html
    assert "<pre" in html and "x = replicated()" in html  # code untouched, not word-wrapped
    assert "rosetta:word" in html  # click hook for the app shell


def test_learn_mode_without_options_still_renders(tmp_path: Path) -> None:
    page = PageBlocks(page_no=0, width=1, height=1, has_text_layer=True,
                      blocks=[_block(0, "Plain text.")])  # fmt: skip

    html = build_page_html(BOOK, page, {}, "learn", tmp_path)

    assert 'data-w="plain"' in html
    assert "<ruby" not in html


def test_review_mode_has_click_to_pin_pairs(tmp_path: Path) -> None:
    p = _block(0, "One. Two.")
    page = PageBlocks(page_no=0, width=1, height=1, has_text_layer=True, blocks=[p])

    html = build_page_html(BOOK, page, {}, "review", tmp_path)

    assert "addEventListener('click'" in html
    assert "pin" in html

"""Page-break paragraph joins: detection, merging and splitting the translation back."""

from __future__ import annotations

from rosetta_engine.models import Block, BlockType, JoinedUnit, PageBlocks, text_hash
from rosetta_engine.translate.joins import (
    find_link,
    find_split,
    head_candidate,
    merged_block,
    split_translation,
    tail_candidate,
)


def _b(
    page: int,
    order: int,
    text: str,
    kind: BlockType = BlockType.PARAGRAPH,
    sentences: list[str] | None = None,
    **kw: object,
) -> Block:
    return Block(
        page_no=page,
        order=order,
        type=kind,
        bbox=(0, 0, 1, 1),
        font="Times",
        size=10,
        bold=False,
        italic=False,
        text=text,
        sentences=sentences if sentences is not None else [text],
        text_hash=text_hash(text),
        **kw,  # type: ignore[arg-type]
    )


def _page(page: int, *blocks: Block, has_text: bool = True) -> PageBlocks:
    return PageBlocks(
        page_no=page, width=600, height=800, has_text_layer=has_text, blocks=list(blocks)
    )


HEAD = _b(
    0,
    1,
    "It is old. They were designed from the ground up to be",
    sentences=["It is old.", "They were designed from the ground up to be"],
)
TAIL = _b(
    1,
    1,
    "cloud native have been shown. It works.",
    sentences=["cloud native have been shown.", "It works."],
)


def _pages(head: Block = HEAD, tail: Block = TAIL) -> tuple[PageBlocks, PageBlocks]:
    prev = _page(0, _b(0, 0, "Header", BlockType.FURNITURE), head)
    nxt = _page(1, _b(1, 0, "Running head", BlockType.FURNITURE), tail)
    return prev, nxt


def test_real_continuation_is_joined() -> None:
    unit = find_split(*_pages())

    assert unit is not None
    assert unit.head_count == 2
    assert unit.merged_sentences == [
        "It is old.",
        "They were designed from the ground up to be cloud native have been shown.",
        "It works.",
    ]
    assert unit.merged_text == (
        "It is old. They were designed from the ground up to be cloud native have been "
        "shown. It works."
    )
    assert unit.unit_hash == text_hash(unit.merged_text)
    assert (unit.head_page, unit.head_hash, unit.tail_page, unit.tail_hash) == (
        0,
        HEAD.text_hash,
        1,
        TAIL.text_hash,
    )


def test_table_of_contents_capitalised_next_line_is_not_joined() -> None:
    head = _b(0, 1, "Fault Tolerance 43")
    tail = _b(1, 1, "Hardware and Software Faults 44")
    assert find_split(*_pages(head, tail)) is None


def test_sentence_end_on_head_is_not_joined() -> None:
    head = _b(0, 1, "This sentence is complete.")
    assert find_split(*_pages(head)) is None


def test_aside_mismatch_is_not_joined() -> None:
    head = _b(0, 1, "An epigraph that runs on", aside=True)
    assert find_split(*_pages(head)) is None


def test_family_mismatch_is_not_joined() -> None:
    tail = _b(1, 1, "cloud native.", family="sans")
    assert find_split(*_pages(tail=tail)) is None


def test_footnote_after_head_is_skipped() -> None:
    prev = _page(0, HEAD, _b(0, 2, "1 A footnote.", BlockType.FOOTNOTE))
    nxt = _page(1, TAIL)
    assert head_candidate(prev) == HEAD
    assert find_split(prev, nxt) is not None


def test_heading_or_code_tail_is_not_joined() -> None:
    for kind in (BlockType.HEADING, BlockType.CODE):
        prev, _ = _pages()
        nxt = _page(1, _b(1, 0, "lower case start", kind), TAIL)
        assert tail_candidate(nxt) is None
        assert find_split(prev, nxt) is None


def test_hyphenated_head_joins_without_space() -> None:
    head = _b(0, 1, "Most modern systems are distrib-")
    tail = _b(1, 1, "uted systems are hard.")
    unit = find_split(*_pages(head, tail))
    assert unit is not None
    assert unit.merged_text == "Most modern systems are distributed systems are hard."
    assert unit.head_count == 1


def test_scanned_or_non_adjacent_page_is_not_joined() -> None:
    prev, _ = _pages()
    assert find_split(prev, _page(1, TAIL, has_text=False)) is None
    assert find_split(prev, _page(2, _b(2, 0, "cloud native."))) is None


def test_chain_is_not_continued_past_one_link() -> None:
    p0 = _page(0, HEAD)
    middle = _b(1, 0, "cloud native but still going on and on")
    p1 = _page(1, middle)
    p2 = _page(2, _b(2, 0, "and finally ends."))

    first = find_link(None, p0, p1)
    assert first is not None and first.tail_order == middle.order
    assert find_link(p0, p1, p2) is None  # middle is already a tail
    assert find_split(p1, p2) is not None  # without the look-back it would chain


def test_merged_block_takes_head_position() -> None:
    unit = find_split(*_pages())
    assert unit is not None
    block = merged_block(unit, HEAD)
    assert (block.page_no, block.order, block.type) == (0, 1, BlockType.PARAGRAPH)
    assert block.text_hash == unit.unit_hash
    assert block.sentences == unit.merged_sentences


def test_blank_sentences_fall_back_to_text() -> None:
    head = _b(0, 1, "half a sentence", sentences=[])
    tail = _b(1, 1, "and the rest.", sentences=[])
    unit = find_split(*_pages(head, tail))
    assert unit is not None
    assert unit.merged_sentences == ["half a sentence and the rest."]


def _unit(merged: int, head_count: int) -> JoinedUnit:
    return JoinedUnit(
        unit_hash="u",
        head_page=0,
        head_hash="h",
        head_order=0,
        tail_page=1,
        tail_hash="t",
        tail_order=0,
        head_count=head_count,
        merged_text="x",
        merged_sentences=[f"s{i}" for i in range(merged)],
    )


def test_split_translation_aligned() -> None:
    tr = [f"t{i}" for i in range(6)]
    assert split_translation(_unit(6, 4), tr, True) == (tr[:4], tr[4:], True)


def test_split_translation_tail_only_crossing_sentence() -> None:
    tr = ["t0", "t1", "t2"]
    assert split_translation(_unit(3, 3), tr, True) == (tr, [], True)


def test_split_translation_misaligned_goes_to_head() -> None:
    tr = ["t0", "t1"]
    assert split_translation(_unit(3, 2), tr, True) == (tr, [], False)
    assert split_translation(_unit(2, 1), tr, False) == (tr, [], False)

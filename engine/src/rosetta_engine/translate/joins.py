"""Paragraphs split by a page break: detect the pair, merge it into one translation unit and
split the translation back onto the two pages. Pure functions, no AI, no DB.

Only pairs (N, N+1) are joined. The head is the last body paragraph of page N (footnotes and
running headers/footers skipped) that does not end a sentence; the tail is the first body block
of page N+1, a paragraph of the same kind that starts lower-case (or the head ends with a
hyphen). A tail that is itself the head of the next break is not chained further.
"""

from __future__ import annotations

from rosetta_engine.extract.extractor import SENTENCE_END
from rosetta_engine.extract.text_clean import ASCII_HYPHEN, HYPHENS, join_across
from rosetta_engine.models import Block, BlockType, JoinedUnit, PageBlocks, text_hash

BODY_SKIP = frozenset({BlockType.FURNITURE, BlockType.FOOTNOTE})
_OPENERS = "“\"'(‘"


def _body(page: PageBlocks) -> list[Block]:
    return [b for b in page.blocks if b.type not in BODY_SKIP]


def head_candidate(page: PageBlocks) -> Block | None:
    """Last body block of the page if it is a paragraph that does not end a sentence."""
    if not page.has_text_layer:
        return None
    body = _body(page)
    if not body:
        return None
    last = body[-1]
    if last.type != BlockType.PARAGRAPH or not last.text.strip():
        return None
    if SENTENCE_END.search(last.text.strip()):
        return None
    return last


def tail_candidate(page: PageBlocks) -> Block | None:
    """First body block of the page if it is a non-blank paragraph."""
    if not page.has_text_layer:
        return None
    body = _body(page)
    if not body:
        return None
    first = body[0]
    if first.type != BlockType.PARAGRAPH or not first.text.strip():
        return None
    return first


def _sentences(block: Block) -> list[str]:
    return block.sentences or [block.text]


def find_split(prev: PageBlocks, nxt: PageBlocks, soft: str = ASCII_HYPHEN) -> JoinedUnit | None:
    """The joined unit of a paragraph running from ``prev`` onto ``nxt``, or None."""
    if nxt.page_no != prev.page_no + 1:
        return None
    head = head_candidate(prev)
    tail = tail_candidate(nxt)
    if head is None or tail is None:
        return None
    if head.aside != tail.aside or head.family != tail.family:
        return None
    starts_lower = tail.text.lstrip(_OPENERS)[:1].islower()
    if not starts_lower and not head.text.rstrip().endswith(HYPHENS):
        return None
    head_s, tail_s = _sentences(head), _sentences(tail)
    merged = [*head_s[:-1], join_across(head_s[-1], tail_s[0], soft), *tail_s[1:]]
    merged_text = join_across(head.text, tail.text, soft)
    return JoinedUnit(
        unit_hash=text_hash(merged_text),
        head_page=prev.page_no,
        head_hash=head.text_hash,
        head_order=head.order,
        tail_page=nxt.page_no,
        tail_hash=tail.text_hash,
        tail_order=tail.order,
        head_count=len(head_s),
        merged_text=merged_text,
        merged_sentences=merged,
    )


def find_link(
    before: PageBlocks | None, prev: PageBlocks, nxt: PageBlocks, soft: str = ASCII_HYPHEN
) -> JoinedUnit | None:
    """``find_split(prev, nxt)`` unless the head is already the tail of (before, prev).

    Looks back exactly one page, so the result depends only on the three pages and is the
    same whatever page range was requested."""
    unit = find_split(prev, nxt, soft)
    if unit is None or before is None:
        return unit
    back = find_split(before, prev, soft)
    if back is not None and back.tail_order == unit.head_order:
        return None
    return unit


def merged_block(unit: JoinedUnit, head: Block) -> Block:
    """The unit as one block: head's page and order, the merged text and sentences."""
    return head.model_copy(
        update={
            "text": unit.merged_text,
            "sentences": list(unit.merged_sentences),
            "text_hash": unit.unit_hash,
        }
    )


def split_translation(
    unit: JoinedUnit, sentences: list[str], aligned: bool
) -> tuple[list[str], list[str], bool]:
    """(head sentences, tail sentences, aligned). Misaligned output all goes to the head."""
    if aligned and len(sentences) == len(unit.merged_sentences):
        return list(sentences[: unit.head_count]), list(sentences[unit.head_count :]), True
    return list(sentences), [], False

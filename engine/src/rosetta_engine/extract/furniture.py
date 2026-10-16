"""Running headers/footers and page numbers (FURNITURE), learned at book level."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from rosetta_engine.extract.pdf_reader import RawBlock, RawPage
from rosetta_engine.extract.stats import HEADING_RATIO

BAND = 0.08  # top/bottom 8% of the page height
REPEAT_SHARE = 0.30  # normalized text on >= 30% of sampled pages

_DIGITS = re.compile(r"\d+")
_SPACE = re.compile(r"\s+")
_PAGE_NUMBER = re.compile(r"^(#|[ivxlcdm]+)$")
# "## | chapter #: title" or "section title | ##"
_NUMBERED_RUNNING = re.compile(r"^(#|[ivxlcdm]+)\s*[|·•—–]\s*\S|\S\s*[|·•—–]\s*(#|[ivxlcdm]+)$")
# "## chapter #: title" / "title ##" without a separator: only for the page's outermost line
_NUMBERED_EDGE = re.compile(r"^(#|[ivxlcdm]+) \S.{0,80}$|^\S.{0,80} (#|[ivxlcdm]+)$")


class FurnitureModel(BaseModel):
    model_config = ConfigDict(frozen=True)

    texts: list[str] = Field(default_factory=list)  # normalized repeated header/footer texts


def normalize(text: str) -> str:
    return _SPACE.sub(" ", _DIGITS.sub("#", text.lower())).strip()


def _in_band(block: RawBlock, page_height: float) -> bool:
    y0, y1 = block.bbox[1], block.bbox[3]
    center = (y0 + y1) / 2
    return center <= page_height * BAND or center >= page_height * (1 - BAND)


def _max_size(block: RawBlock) -> float:
    return max((s.size for ln in block.lines for s in ln.spans), default=0.0)


def build_furniture(pages: Sequence[RawPage], body_size: float) -> FurnitureModel:
    counts: Counter[str] = Counter()
    for page in pages:
        seen: set[str] = set()
        for block in page.text_blocks:
            if _in_band(block, page.height) and _max_size(block) <= body_size * HEADING_RATIO:
                seen.add(normalize(block.text))
        counts.update(seen)
    if not pages:
        return FurnitureModel()
    threshold = max(2, int(len(pages) * REPEAT_SHARE + 0.999))
    texts = sorted(t for t, n in counts.items() if n >= threshold and t)
    return FurnitureModel(texts=texts)


def is_furniture(
    block: RawBlock,
    page_height: float,
    model: FurnitureModel,
    body_size: float,
    *,
    edge: bool = False,
) -> bool:
    """``edge``: the block is the page's top-most or bottom-most text block."""
    if block.kind != "text" or not _in_band(block, page_height):
        return False
    if _max_size(block) > body_size * HEADING_RATIO:  # chapter title at the top of a page
        return False
    norm = normalize(block.text)
    return (
        norm in model.texts
        or bool(_PAGE_NUMBER.match(norm))
        or bool(_NUMBERED_RUNNING.search(norm))
        or (edge and len(block.lines) <= 2 and bool(_NUMBERED_EDGE.match(norm)))
    )

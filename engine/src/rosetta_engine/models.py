"""Domain models shared by extract, store, translate and render."""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BBox = tuple[float, float, float, float]
FontFamily = Literal["serif", "sans", "mono"]


class BlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    CODE = "code"
    IMAGE = "image"
    TABLE = "table"
    CAPTION = "caption"
    FOOTNOTE = "footnote"
    FURNITURE = "furniture"  # running header/footer, page number


TRANSLATABLE: frozenset[BlockType] = frozenset(
    {
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.LIST_ITEM,
        BlockType.CAPTION,
        BlockType.FOOTNOTE,
    }
)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Block(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_no: int  # 0-based internally, shown 1-based in the CLI
    order: int  # reading order within the page
    type: BlockType
    bbox: BBox
    font: str
    size: float
    bold: bool
    italic: bool
    family: FontFamily = "serif"
    heading_level: int | None = None
    aside: bool = False  # note/tip box, epigraph
    list_marker: str | None = None  # "•", "1.", "" (vector-drawn marker)
    text: str  # inline code wrapped in `backticks`; CODE keeps newlines/indentation
    sentences: list[str] = Field(default_factory=list)
    text_hash: str

    @property
    def translatable(self) -> bool:
        return self.type in TRANSLATABLE


class PageBlocks(BaseModel):
    model_config = ConfigDict(frozen=True)

    page_no: int
    width: float
    height: float
    has_text_layer: bool
    continues_on_next_page: bool = False
    blocks: list[Block]


class Book(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    file_hash: str
    title: str
    page_count: int
    file_path: str | None = None


class BookProfile(BaseModel):
    """Optional per-book translation hints. Accepts Turkish keys as aliases."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    genre: str = Field(default="", alias="tur")
    tone: str = Field(default="", alias="ton")
    target_lang: str = Field(default="tr", alias="hedef_dil")
    do_not_translate: list[str] = Field(default_factory=list, alias="cevrilmeyecek")
    glossary: dict[str, str] = Field(default_factory=dict, alias="sozluk")
    code_languages: list[str] = Field(default_factory=list, alias="kod_dili")


class CostEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    price_known: bool = True  # False: no price for the model; usd is 0 and meaningless


class Translation(BaseModel):
    """A translated block, keyed by (page_no, source text_hash)."""

    model_config = ConfigDict(frozen=True)

    page_no: int
    text_hash: str
    sentences: list[str]
    text: str
    sentence_aligned: bool
    unit_hash: str | None = None  # set on rows of a paragraph joined across a page break
    unit_role: Literal["head", "tail"] | None = None


class JoinedUnit(BaseModel):
    """A paragraph split by a page break, translated as one item.

    The head is the last body paragraph of ``head_page``, the tail the first body block of
    ``tail_page`` (= head_page + 1). ``head_count`` translated sentences go to the head row
    (the sentence that crosses the break included); the rest go to the tail row."""

    model_config = ConfigDict(frozen=True)

    unit_hash: str  # text_hash of the merged text
    head_page: int
    head_hash: str
    head_order: int
    tail_page: int
    tail_hash: str
    tail_order: int
    head_count: int
    merged_text: str
    merged_sentences: list[str]


class Batch(BaseModel):
    """One provider call: translatable blocks from up to N pages."""

    model_config = ConfigDict(frozen=True)

    pages: list[int]
    blocks: list[Block]
    context: list[str] = Field(default_factory=list)  # preceding paragraphs, not translated
    est_input_tokens: int = 0
    est_output_tokens: int = 0
    joins: dict[str, JoinedUnit] = Field(default_factory=dict)  # merged text_hash -> unit


class TranslationPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    book: Book
    lang: str
    provider: str
    model: str
    pages: list[int]
    force: bool = False
    total_blocks: int = 0  # translatable blocks in the requested pages
    cached_blocks: int = 0
    batches: list[Batch] = Field(default_factory=list)
    estimate: CostEstimate = Field(default_factory=CostEstimate)
    no_text_pages: list[int] = Field(default_factory=list)  # scanned pages, skipped
    targeted: bool = False  # only_blocks plan: rows are replaced, page status is never written
    joined_units: int = 0  # paragraphs joined across a page break (counted once)


class UsageTotals(BaseModel):
    model_config = ConfigDict(frozen=True)

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class TranslationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    done_pages: list[int] = Field(default_factory=list)
    failed_pages: dict[int, str] = Field(default_factory=dict)
    stopped_reason: str | None = None
    stop_kind: Literal["usage_limit", "auth", "budget", "unavailable", "paused"] | None = None
    usage: UsageTotals = Field(default_factory=UsageTotals)

"""Request bodies and response builders. JSON shapes follow app/API_CONTRACT.md (1-based pages)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from rosetta_engine.models import Book, CostEstimate, TranslationReport
from rosetta_engine.store.learn_repo import VocabRow
from rosetta_engine.store.repo import JobRow

Operation = Literal["translate", "job", "profile", "explain"]


class _Body(BaseModel):
    model_config = ConfigDict(extra="ignore")


class OpenBookBody(_Body):
    path: str


class ConfirmBody(_Body):
    confirm_token: str | None = None


class TranslateEstimateBody(_Body):
    pages: list[int] = Field(default_factory=list)
    lang: str | None = None
    provider: str | None = None
    model: str | None = None
    force: bool = False


class JobEstimateBody(TranslateEstimateBody):
    all: bool = False
    budget_usd: float | None = Field(default=None, ge=0)


class ExportBody(_Body):
    pages: list[int] | None = None
    mode: Literal["tr", "bilingual"] = "tr"
    paper: Literal["a4", "letter"] = "a4"
    lang: str | None = None
    out_path: str | None = None


class VocabCreateBody(_Body):
    word: str = Field(min_length=1)
    sentence: str | None = None
    book_id: int | None = None
    page: int | None = Field(default=None, ge=1)
    block_key: str | None = None
    meaning: str | None = None
    unknown: bool = True


class VocabPatchBody(_Body):
    unknown: bool


class ReviewBody(_Body):
    rating: str


class TermsAddBody(_Body):
    terms: list[str] | None = None


class ExplainEstimateBody(_Body):
    text: str = Field(min_length=1)
    book_id: int | None = None
    page: int | None = Field(default=None, ge=1)


# --- responses -------------------------------------------------------------------------------


def book_info(book: Book, path: str) -> dict[str, Any]:
    return {
        "id": book.id,
        "file_hash": book.file_hash,
        "title": book.title,
        "page_count": book.page_count,
        "path": path,
    }


def estimate(
    token: str,
    operation: Operation,
    *,
    provider: str,
    model: str,
    cost: CostEstimate,
    thinking: str | None,
    thinking_extra: int,
    pages: list[int],
    expires_in: int,
    total_blocks: int = 0,
    cached_blocks: int = 0,
    supports_profile: bool = True,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "confirm_token": token,
        "operation": operation,
        "provider": provider,
        "model": model,
        "calls": cost.calls,
        "input_tokens": cost.input_tokens,
        "output_tokens": cost.output_tokens,
        "usd": round(cost.usd, 6),
        "price_known": cost.price_known,
        "thinking": thinking,
        "thinking_extra_tokens": thinking_extra if thinking else 0,
        "total_blocks": total_blocks,
        "cached_blocks": cached_blocks,
        "pages": [p + 1 for p in pages],
        "supports_profile": supports_profile,
        "expires_in": expires_in,
        "warnings": list(warnings or []),
    }


def report(r: TranslationReport) -> dict[str, Any]:
    return {
        "done_pages": [p + 1 for p in r.done_pages],
        "failed_pages": {str(p + 1): reason for p, reason in sorted(r.failed_pages.items())},
        "stopped_reason": r.stopped_reason,
        "stop_kind": r.stop_kind,
        "usage": r.usage.model_dump(),
    }


def job(j: JobRow) -> dict[str, Any]:
    return {
        "id": j.id,
        "book_id": j.book_id,
        "status": j.status,
        "lang": j.lang,
        "provider": j.provider,
        "model": j.model,
        "pages": [p + 1 for p in j.pages],
        "done_pages": [p + 1 for p in j.done_pages],
        "failed_pages": {str(p + 1): reason for p, reason in sorted(j.failed.items())},
        "budget_usd": j.budget_usd,
        "spent_usd": round(j.spent_usd, 6),
        "stop_reason": j.stop_reason,
        "created_at": j.created_at,
        "updated_at": j.updated_at,
    }


def vocab(v: VocabRow) -> dict[str, Any]:
    return {
        "id": v.id,
        "word": v.word,
        "lemma": v.lemma,
        "sentence": v.sentence,
        "book_id": v.book_id,
        "page": v.page_no + 1 if v.page_no is not None else None,
        "block_key": (
            f"{v.page_no}-{v.block_ord}"
            if v.page_no is not None and v.block_ord is not None
            else None
        ),
        "meaning": v.meaning,
        "unknown": v.unknown,
        "created_at": v.created_at,
    }

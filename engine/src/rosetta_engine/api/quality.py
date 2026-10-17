"""Translation quality endpoints (no AI): term consistency of the cached translations.

Re-translating affected paragraphs goes through the normal ``/estimate`` (``blocks``) →
user confirmation → ``/translate`` flow; nothing here ever calls a provider.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from rosetta_engine.api.deps import Engine
from rosetta_engine.api.errors import bad_request, not_found
from rosetta_engine.api.schemas import TermAcceptBody, TermIgnoreBody
from rosetta_engine.api.state import EngineState, Session
from rosetta_engine.models import BookProfile
from rosetta_engine.quality.terms import Occurrence, TermIssue, analyze, sentence_pairs
from rosetta_engine.store.repo import PairRow
from rosetta_engine.textsafe import strip_controls

router = APIRouter(prefix="/api")

MAX_TERM_LEN = 200
MAX_AFFECTED = 200  # affected blocks listed per issue (the count is given separately)


def _clean(value: str, what: str) -> str:
    out = strip_controls(value).replace("\n", " ").replace("\t", " ").strip()
    if not out:
        raise bad_request(f"{what} boş olamaz")
    if len(out) > MAX_TERM_LEN:
        raise bad_request(f"{what} çok uzun (en fazla {MAX_TERM_LEN} karakter)")
    return out


def _book_or_404(s: Session, book_id: int) -> None:
    if s.repos.books.get(book_id) is None:
        raise not_found(f"Kitap bulunamadı: #{book_id}")


def _rows(eng: EngineState, s: Session, book_id: int, lang: str) -> tuple[list[PairRow], str, str]:
    t = eng.default_translator()
    return s.repos.translations.pairs_for_book(book_id, lang, t.name, t.model), t.name, t.model


def _example(o: Occurrence) -> dict[str, Any]:
    return {"page": o.page_no + 1, "block": f"{o.page_no}-{o.block_ord}", "en": o.en, "tr": o.tr}


def _affected(occ: list[Occurrence]) -> list[dict[str, Any]]:
    """One entry per block (several sentences of a paragraph may be affected)."""
    seen: dict[tuple[int, int], dict[str, Any]] = {}
    for o in occ:
        seen.setdefault(
            (o.page_no, o.block_ord),
            {
                "page": o.page_no + 1,
                "block": f"{o.page_no}-{o.block_ord}",
                "text_hash": o.text_hash,
            },
        )
    return list(seen.values())


def _issue(i: TermIssue) -> dict[str, Any]:
    affected = _affected(i.affected)
    return {
        "term": i.term,
        "source": i.source,
        "preferred": i.preferred,
        "occurrences": i.occurrences,
        "variants": [
            {
                "key": v.key,
                "label": v.label,
                "count": v.count,
                "examples": [_example(o) for o in v.examples],
            }
            for v in i.variants
        ],
        "affected": affected[:MAX_AFFECTED],
        "affected_count": len(affected),
    }


@router.get("/books/{book_id}/consistency")
def consistency(book_id: int, eng: Engine, lang: str | None = None) -> dict[str, Any]:
    target = lang or eng.settings.default_lang
    with eng.db() as s:
        _book_or_404(s, book_id)
        rows, provider, model = _rows(eng, s, book_id, target)
        profile = s.repos.profiles.get(book_id) or BookProfile(target_lang=target)
        ignored = s.repos.term_ignores.list(book_id, target)
    issues = analyze(sentence_pairs(rows), profile, ignored)
    aligned = sum(1 for r in rows if r.sentence_aligned)
    return {
        "lang": target,
        "provider": provider,
        "model": model,
        "analyzed_blocks": len(rows),
        "aligned_ratio": round(aligned / len(rows), 3) if rows else 1.0,
        "ignored": sorted(ignored),
        "issues": [_issue(i) for i in issues],
    }


@router.post("/books/{book_id}/consistency/accept")
def accept(book_id: int, body: TermAcceptBody, eng: Engine) -> dict[str, Any]:
    """Add ``term → tr`` to the book's glossary (no AI, the cache is untouched) and return the
    paragraphs that still use another rendering."""
    term = _clean(body.term, "Terim")
    tr = _clean(body.tr, "Karşılık")
    target = body.lang or eng.settings.default_lang
    with eng.db() as s:
        _book_or_404(s, book_id)
        current = s.repos.profiles.get(book_id) or BookProfile(target_lang=target)
        key = term.casefold()
        glossary = {k: v for k, v in current.glossary.items() if k.casefold() != key}
        glossary[term] = tr
        dnt = [t for t in current.do_not_translate if t.casefold() != key]
        profile = current.model_copy(update={"glossary": glossary, "do_not_translate": dnt})
        s.repos.profiles.put(book_id, profile)
        s.repos.term_ignores.remove(book_id, target, term)
        rows, _, _ = _rows(eng, s, book_id, target)
        stored = s.repos.profiles.get(book_id)
        assert stored is not None
    issues = analyze(sentence_pairs(rows), stored, terms=[term])
    affected = _affected(issues[0].affected) if issues else []
    return {
        "profile": stored.model_dump(by_alias=True),
        "affected": affected[:MAX_AFFECTED],
        "affected_count": len(affected),
    }


@router.post("/books/{book_id}/consistency/ignore")
def ignore(book_id: int, body: TermIgnoreBody, eng: Engine) -> dict[str, Any]:
    term = _clean(body.term, "Terim")
    target = body.lang or eng.settings.default_lang
    with eng.db() as s:
        _book_or_404(s, book_id)
        s.repos.term_ignores.add(book_id, target, term)
        return {"ignored": sorted(s.repos.term_ignores.list(book_id, target))}


@router.delete("/books/{book_id}/consistency/ignore")
def unignore(
    book_id: int, eng: Engine, term: str = Query(min_length=1), lang: str | None = None
) -> dict[str, Any]:
    clean = _clean(term, "Terim")
    target = lang or eng.settings.default_lang
    with eng.db() as s:
        _book_or_404(s, book_id)
        s.repos.term_ignores.remove(book_id, target, clean)
        return {"ignored": sorted(s.repos.term_ignores.list(book_id, target))}

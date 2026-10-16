"""Learning endpoints (Faz 6, no AI): dictionary lookup, vocabulary, flashcards, stats, terms."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Query, Response

from rosetta_engine.api.deps import Engine
from rosetta_engine.api.errors import bad_request, not_found
from rosetta_engine.api.schemas import (
    ReviewBody,
    TermsAddBody,
    VocabCreateBody,
    VocabPatchBody,
    vocab,
)
from rosetta_engine.api.state import EngineState, Session
from rosetta_engine.learn.dictionary import Dictionary
from rosetta_engine.learn.notebook import Notebook, add_terms, find_context, technical_terms
from rosetta_engine.learn.srs import Grade, ReviewService, stats
from rosetta_engine.models import PageBlocks
from rosetta_engine.store.learn_repo import ReviewRepo, VocabRepo, VocabRow

router = APIRouter(prefix="/api")


@dataclass
class _Learn:
    s: Session
    vocab: VocabRepo
    reviews: ReviewRepo
    srs: ReviewService
    dictionary: Dictionary
    notebook: Notebook


@contextmanager
def _learn(eng: EngineState) -> Iterator[_Learn]:
    dictionary = Dictionary()
    try:
        with eng.db() as s:
            v = VocabRepo(s.conn)
            r = ReviewRepo(s.conn)
            srs = ReviewService(v, r, lang=eng.settings.default_lang)
            yield _Learn(s, v, r, srs, dictionary, Notebook(v, srs, dictionary))
    finally:
        dictionary.close()


def _card(lr: _Learn, vocab_id: int, due_at: str) -> dict[str, Any]:
    c = lr.srs.flashcard(vocab_id)
    return {
        "vocab_id": vocab_id,
        "front": c.front,
        "word": c.back_word,
        "meaning": c.back_meaning,
        "sentence_tr": c.back_sentence_tr,
        "due_at": due_at,
    }


def _vocab_or_404(lr: _Learn, vocab_id: int) -> VocabRow:
    found = lr.vocab.get(vocab_id)
    if found is None:
        raise not_found(f"Kelime bulunamadı: #{vocab_id}")
    return found


@router.get("/lookup")
def lookup(q: str = Query(min_length=1)) -> dict[str, Any]:
    with Dictionary() as d:
        r = d.lookup(q)
    return {"query": r.query, "lemma": r.lemma, "tr": r.tr, "definitions": r.definitions}


@router.get("/vocab")
def vocab_list(
    eng: Engine,
    book_id: int | None = None,
    search: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    with _learn(eng) as lr:
        return [vocab(v) for v in lr.vocab.query(book_id=book_id, search=search, since=since)]


@dataclass(frozen=True)
class _Where:
    page: PageBlocks | None = None
    location: tuple[int, int, str] | None = None  # (page_no, block_ord, text_hash)
    sentence: str | None = None


def _where(eng: EngineState, lr: _Learn, body: VocabCreateBody) -> _Where:
    """Context of a saved word: the page, and with ``block_key`` exactly that block."""
    if body.book_id is None or body.page is None:
        return _Where(sentence=body.sentence)
    ob = eng.book(lr.s, body.book_id)
    (p,) = eng.check_pages(ob, [body.page])
    page = eng.pages(lr.s, ob, [p])[p]
    if not body.block_key:
        return _Where(page=page, sentence=body.sentence)
    try:
        page_no, order = (int(x) for x in body.block_key.split("-", 1))
    except ValueError as e:
        raise bad_request(f"Geçersiz block_key: {body.block_key}") from e
    block = next((b for b in page.blocks if b.page_no == page_no and b.order == order), None)
    if block is None:
        raise bad_request(f"Block bulunamadı: {body.block_key}")
    sentence = body.sentence
    if sentence is None:
        found = find_context(page.model_copy(update={"blocks": [block]}), body.word)
        sentence = found.sentence or (block.sentences[0] if block.sentences else block.text)
    return _Where(location=(block.page_no, block.order, block.text_hash), sentence=sentence)


@router.post("/vocab")
def vocab_add(body: VocabCreateBody, eng: Engine) -> dict[str, Any]:
    with _learn(eng) as lr:
        if body.book_id is not None and lr.s.repos.books.get(body.book_id) is None:
            raise not_found(f"Kitap bulunamadı: #{body.book_id}")
        where = _where(eng, lr, body)
        profile = lr.s.repos.profiles.get(body.book_id) if body.book_id is not None else None
        saved = lr.notebook.save(
            body.word,
            book_id=body.book_id,
            page=where.page,
            sentence=where.sentence,
            meaning=body.meaning,
            unknown=body.unknown,
            location=where.location,
            glossary=profile.glossary if profile else None,
        )
        return vocab(saved.vocab)


@router.patch("/vocab/{vocab_id}")
def vocab_patch(vocab_id: int, body: VocabPatchBody, eng: Engine) -> dict[str, Any]:
    with _learn(eng) as lr:
        found = _vocab_or_404(lr, vocab_id)
        lr.vocab.set_unknown(found.lemma, body.unknown)  # book-wide: keyed by lemma
        return vocab(_vocab_or_404(lr, vocab_id))


@router.delete("/vocab/{vocab_id}", status_code=204)
def vocab_delete(vocab_id: int, eng: Engine) -> Response:
    with _learn(eng) as lr:
        if not lr.vocab.delete(vocab_id):
            raise not_found(f"Kelime bulunamadı: #{vocab_id}")
    return Response(status_code=204)


@router.get("/review/due")
def review_due(eng: Engine, limit: int | None = Query(default=None, ge=1)) -> list[dict[str, Any]]:
    with _learn(eng) as lr:
        return [_card(lr, row.vocab_id, row.due_at) for row in lr.srs.due(limit)]


@router.post("/review/{vocab_id}")
def review(vocab_id: int, body: ReviewBody, eng: Engine) -> dict[str, Any] | None:
    try:
        grade = Grade.parse(body.rating)
    except ValueError as e:
        raise bad_request(str(e)) from e
    with _learn(eng) as lr:
        _vocab_or_404(lr, vocab_id)
        lr.srs.review(vocab_id, grade)
        nxt = lr.srs.due(1)
        return _card(lr, nxt[0].vocab_id, nxt[0].due_at) if nxt else None


@router.get("/stats")
def learn_stats(eng: Engine) -> dict[str, Any]:
    with _learn(eng) as lr:
        st = stats(lr.vocab, lr.reviews)
        return {
            "total_words": st.total_words,
            "mature_words": st.mature_words,
            "due_today": st.due_today,
            "reviewed_today": st.reviewed_today,
            "streak_days": st.streak_days,
        }


@router.get("/books/{book_id}/terms")
def terms(book_id: int, eng: Engine) -> list[dict[str, Any]]:
    with _learn(eng) as lr:
        if lr.s.repos.books.get(book_id) is None:
            raise not_found(f"Kitap bulunamadı: #{book_id}")
        profile = lr.s.repos.profiles.get(book_id)
        if profile is None:
            return []
        return [
            {"term": t.term, "tr": t.glossary_tr, "in_vocab": t.saved}
            for t in technical_terms(profile, lr.dictionary, lr.vocab)
        ]


@router.post("/books/{book_id}/terms/add")
def terms_add(book_id: int, body: TermsAddBody, eng: Engine) -> dict[str, int]:
    with _learn(eng) as lr:
        if lr.s.repos.books.get(book_id) is None:
            raise not_found(f"Kitap bulunamadı: #{book_id}")
        profile = lr.s.repos.profiles.get(book_id)
        if profile is None:
            return {"added": 0}
        wanted = None if body.terms is None else {t.casefold() for t in body.terms}
        items = [
            t
            for t in technical_terms(profile, lr.dictionary, lr.vocab)
            if not t.saved and (wanted is None or t.term.casefold() in wanted)
        ]
        saved = add_terms(lr.notebook, lr.vocab, book_id, items)
        return {"added": sum(1 for x in saved if x.created)}

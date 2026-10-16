"""Vocabulary notebook: save words with their book context; technical terms from the profile."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from rosetta_engine.learn.dictionary import Dictionary, normalize
from rosetta_engine.learn.srs import ReviewService
from rosetta_engine.models import BookProfile, PageBlocks
from rosetta_engine.store.learn_repo import VocabRepo, VocabRow

MEANING_MAX = 3  # Turkish equivalents kept as the short meaning
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Context:
    sentence: str
    block_ord: int | None = None
    text_hash: str | None = None


def find_context(page: PageBlocks, word: str) -> Context:
    """First translatable sentence on the page containing ``word`` (whole word, any case)."""
    pattern = re.compile(rf"(?<![\w]){re.escape(word)}(?![\w])", re.IGNORECASE)
    for block in sorted(page.blocks, key=lambda b: b.order):
        if not block.translatable:
            continue
        for sentence in block.sentences or [block.text]:
            if pattern.search(sentence):
                return Context(sentence=sentence, block_ord=block.order, text_hash=block.text_hash)
    return Context(sentence="")


def short_meaning(dictionary: Dictionary, word: str) -> str:
    r = dictionary.lookup(word)
    return ", ".join(r.tr[:MEANING_MAX])


@dataclass(frozen=True)
class SavedWord:
    vocab: VocabRow
    created: bool


class Notebook:
    def __init__(self, vocab: VocabRepo, reviews: ReviewService, dictionary: Dictionary) -> None:
        self._v = vocab
        self._srs = reviews
        self._d = dictionary

    def save(
        self,
        word: str,
        *,
        book_id: int | None = None,
        page: PageBlocks | None = None,
        sentence: str | None = None,
        meaning: str | None = None,
        unknown: bool = True,
        location: tuple[int, int, str] | None = None,
        glossary: Mapping[str, str] | None = None,
    ) -> SavedWord:
        """Save a word (keyed by lemma) with its context and schedule a flashcard.

        ``location`` = (page_no, block_ord, text_hash) when the caller already knows the block.
        Meaning: non-blank ``meaning`` → dictionary Turkish → book ``glossary`` (word or lemma).
        """
        clean = normalize(word)
        if not clean:
            raise ValueError("boş kelime kaydedilemez")
        lemma = self._d.lemma_of(clean)
        ctx = Context(sentence=sentence or "")
        page_no = page.page_no if page is not None else None
        if location is not None:
            page_no, block_ord, text_hash = location
            ctx = Context(sentence or "", block_ord, text_hash)
        elif page is not None:
            found = find_context(page, clean)
            ctx = found if sentence is None else Context(sentence, found.block_ord, found.text_hash)
        row, created = self._v.add(
            word=clean,
            lemma=lemma,
            sentence=ctx.sentence,
            book_id=book_id,
            page_no=page_no,
            block_ord=ctx.block_ord,
            text_hash=ctx.text_hash,
            meaning=(meaning or "").strip() or self._meaning(clean, lemma, glossary),
            unknown=unknown,
        )
        if not created and unknown and not row.unknown:
            self._v.set_unknown(lemma, True)
            row = self._v.by_lemma(lemma) or row
        self._srs.ensure_card(row.id)
        return SavedWord(row, created)

    def _meaning(self, word: str, lemma: str, glossary: Mapping[str, str] | None) -> str:
        found = short_meaning(self._d, word)
        if found or not glossary:
            return found
        folded = {k.casefold(): v for k, v in glossary.items()}
        return folded.get(word.casefold()) or folded.get(lemma.casefold()) or ""

    def mark(self, word: str, unknown: bool) -> bool:
        """Mark a lemma known/unknown everywhere; saves it first if it isn't in the notebook."""
        lemma = self._d.lemma_of(normalize(word))
        if self._v.set_unknown(lemma, unknown):
            return True
        if unknown:
            self.save(word, unknown=True)
            return True
        return False


@dataclass(frozen=True)
class Term:
    term: str
    glossary_tr: str
    dictionary_tr: list[str]
    definition: str
    saved: bool


def technical_terms(profile: BookProfile, dictionary: Dictionary, vocab: VocabRepo) -> list[Term]:
    """Glossary terms of the book profile, enriched with dictionary data."""
    terms: list[Term] = []
    for term, tr in sorted(profile.glossary.items(), key=lambda kv: kv[0].lower()):
        r = dictionary.lookup(term)
        terms.append(
            Term(
                term=term,
                glossary_tr=tr,
                dictionary_tr=r.tr[:MEANING_MAX],
                definition=r.definitions[0] if r.definitions else "",
                saved=vocab.by_lemma(dictionary.lemma_of(term)) is not None,
            )
        )
    return terms


def add_terms(
    notebook: Notebook,
    vocab: VocabRepo,
    book_id: int,
    terms: list[Term],
) -> list[SavedWord]:
    """Add terms to the notebook; context = first extracted block of the book using the term."""
    saved: list[SavedWord] = []
    for t in terms:
        ctx = vocab.find_context(book_id, t.term)
        sentence = ""
        location: tuple[int, int, str] | None = None
        if ctx is not None:
            page_no, ord_, text_hash, text = ctx
            location = (page_no, ord_, text_hash)
            candidates = vocab.block_sentences(book_id, page_no, text_hash) or _SENTENCE.split(text)
            needle = t.term.casefold()
            sentence = next((s for s in candidates if needle in s.casefold()), text)
        saved.append(
            notebook.save(
                t.term, book_id=book_id, sentence=sentence, meaning=t.glossary_tr, location=location
            )
        )
    return saved

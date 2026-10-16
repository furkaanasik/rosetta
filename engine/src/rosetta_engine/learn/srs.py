"""Spaced repetition with FSRS (``fsrs`` package): cards, reviews, cloze flashcards, stats."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum

from fsrs import Card, Rating, Scheduler, State

from rosetta_engine.store.learn_repo import ReviewRepo, ReviewRow, VocabRepo, VocabRow
from rosetta_engine.store.repo import Clock, utc_now

MATURE_STABILITY_DAYS = 21.0
CLOZE = "_____"


class Grade(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4

    @classmethod
    def parse(cls, value: str) -> Grade:
        key = value.strip().lower()
        aliases = {"1": "again", "2": "hard", "3": "good", "4": "easy", "a": "again", "h": "hard",
                   "g": "good", "e": "easy", "tekrar": "again", "zor": "hard", "iyi": "good",
                   "kolay": "easy"}  # fmt: skip
        key = aliases.get(key, key)
        try:
            return cls[key.upper()]
        except KeyError:
            raise ValueError(f"unknown rating {value!r} (again|hard|good|easy)") from None


def _row(vocab_id: int, card: Card, reps: int, lapses: int) -> ReviewRow:
    return ReviewRow(
        vocab_id=vocab_id,
        due_at=card.due.astimezone(UTC).isoformat(),
        stability=card.stability,
        difficulty=card.difficulty,
        state=int(card.state),
        step=card.step,
        reps=reps,
        lapses=lapses,
        last_review_at=card.last_review.astimezone(UTC).isoformat() if card.last_review else None,
        card_json=card.to_json(),
    )


@dataclass(frozen=True)
class Flashcard:
    vocab: VocabRow
    front: str  # book sentence with the word as cloze
    back_word: str
    back_meaning: str
    back_sentence_tr: str | None  # cached translation of the sentence, if any


def cloze(sentence: str, word: str) -> str:
    """Blank out ``word`` (case-insensitive, whole word) in ``sentence``."""
    if not sentence:
        return CLOZE
    pattern = re.compile(rf"(?<![\w]){re.escape(word)}(?![\w])", re.IGNORECASE)
    blanked, n = pattern.subn(CLOZE, sentence)
    return blanked if n else f"{sentence} ({CLOZE})"


class ReviewService:
    def __init__(
        self,
        vocab: VocabRepo,
        reviews: ReviewRepo,
        *,
        clock: Clock = utc_now,
        scheduler: Scheduler | None = None,
        lang: str = "tr",
    ) -> None:
        self._v = vocab
        self._r = reviews
        self._clock = clock
        self._s = scheduler or Scheduler(enable_fuzzing=False)
        self._lang = lang

    def ensure_card(self, vocab_id: int) -> ReviewRow:
        """Create a new FSRS card (due now) for a vocab entry if it has none."""
        existing = self._r.get(vocab_id)
        if existing is not None:
            return existing
        card = Card(due=self._clock())
        row = _row(vocab_id, card, reps=0, lapses=0)
        self._r.upsert(row)
        return row

    def review(self, vocab_id: int, grade: Grade) -> ReviewRow:
        current = self._r.get(vocab_id) or self.ensure_card(vocab_id)
        card = Card.from_json(current.card_json)
        was_review = card.state == State.Review
        now = self._clock()
        card, log = self._s.review_card(card, Rating(int(grade)), review_datetime=now)
        lapses = current.lapses + (1 if grade is Grade.AGAIN and was_review else 0)
        row = _row(vocab_id, card, reps=current.reps + 1, lapses=lapses)
        self._r.record(row, int(grade), now, log.to_json())
        return row

    def due(self, limit: int | None = None) -> list[ReviewRow]:
        return self._r.due(self._clock(), limit)

    def flashcard(self, vocab_id: int) -> Flashcard:
        v = self._v.get(vocab_id)
        if v is None:
            raise KeyError(vocab_id)
        return Flashcard(
            vocab=v,
            front=cloze(v.sentence, v.word),
            back_word=v.word,
            back_meaning=v.meaning,
            back_sentence_tr=self._translated_sentence(v),
        )

    def _translated_sentence(self, v: VocabRow) -> str | None:
        if v.book_id is None or v.page_no is None or not v.text_hash:
            return None
        found = self._v.translated_sentences(v.book_id, v.page_no, v.text_hash, self._lang)
        if found is None:
            return None
        tr_sentences, aligned = found
        src = self._v.block_sentences(v.book_id, v.page_no, v.text_hash) or []
        if aligned and v.sentence:
            for i, s in enumerate(src):
                if v.sentence.strip() in s or s in v.sentence:
                    return tr_sentences[i] if i < len(tr_sentences) else None
        return " ".join(tr_sentences) if tr_sentences else None


@dataclass(frozen=True)
class Stats:
    total_words: int
    unknown_words: int
    mature_words: int
    due_today: int
    reviewed_today: int
    streak_days: int


def _day_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def streak(days: list[str], today: str) -> int:
    """Consecutive review days ending today (or yesterday, if nothing reviewed yet today)."""
    have = set(days)
    day = datetime.fromisoformat(today).date()
    if today not in have:
        day -= timedelta(days=1)
    count = 0
    while day.isoformat() in have:
        count += 1
        day -= timedelta(days=1)
    return count


def stats(vocab: VocabRepo, reviews: ReviewRepo, clock: Clock = utc_now) -> Stats:
    now = clock()
    start, end = _day_bounds(now)
    rows = vocab.query()
    return Stats(
        total_words=len(rows),
        unknown_words=sum(1 for r in rows if r.unknown),
        mature_words=reviews.count_mature(MATURE_STABILITY_DAYS),
        due_today=reviews.count_due(end),
        reviewed_today=reviews.count_reviewed_between(start, end),
        streak_days=streak(reviews.review_days(), start.date().isoformat()),
    )

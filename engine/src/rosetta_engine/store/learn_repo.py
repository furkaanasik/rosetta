"""SQL for the learning module (Faz 6): vocabulary, FSRS review state, review log."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from rosetta_engine.store.repo import Clock, utc_now


@dataclass(frozen=True)
class VocabRow:
    id: int
    word: str
    lemma: str
    sentence: str
    book_id: int | None
    page_no: int | None
    block_ord: int | None
    text_hash: str | None
    meaning: str
    unknown: bool
    created_at: str


@dataclass(frozen=True)
class ReviewRow:
    vocab_id: int
    due_at: str
    stability: float | None
    difficulty: float | None
    state: int
    step: int | None
    reps: int
    lapses: int
    last_review_at: str | None
    card_json: str


def _vocab(r: sqlite3.Row) -> VocabRow:
    return VocabRow(
        id=r["id"],
        word=r["word"],
        lemma=r["lemma"],
        sentence=r["sentence"],
        book_id=r["book_id"],
        page_no=r["page_no"],
        block_ord=r["block_ord"],
        text_hash=r["text_hash"],
        meaning=r["meaning"],
        unknown=bool(r["unknown"]),
        created_at=r["created_at"],
    )


def _review(r: sqlite3.Row) -> ReviewRow:
    return ReviewRow(
        vocab_id=r["vocab_id"],
        due_at=r["due_at"],
        stability=r["stability"],
        difficulty=r["difficulty"],
        state=r["state"],
        step=r["step"],
        reps=r["reps"],
        lapses=r["lapses"],
        last_review_at=r["last_review_at"],
        card_json=r["card_json"],
    )


class VocabRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock = utc_now) -> None:
        self._c = conn
        self._clock = clock

    def add(
        self,
        *,
        word: str,
        lemma: str,
        sentence: str = "",
        book_id: int | None = None,
        page_no: int | None = None,
        block_ord: int | None = None,
        text_hash: str | None = None,
        meaning: str = "",
        unknown: bool = True,
    ) -> tuple[VocabRow, bool]:
        """Insert a lemma; an existing lemma is returned unchanged (``created`` False)."""
        existing = self.by_lemma(lemma)
        if existing is not None:
            return existing, False
        with self._c:
            cur = self._c.execute(
                "INSERT INTO vocab(word, lemma, sentence, book_id, page_no, block_ord, text_hash,"
                " meaning, unknown, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    word,
                    lemma,
                    sentence,
                    book_id,
                    page_no,
                    block_ord,
                    text_hash,
                    meaning,
                    int(unknown),
                    self._clock().isoformat(),
                ),
            )
        row = self.get(int(cur.lastrowid or 0))
        assert row is not None
        return row, True

    def get(self, vocab_id: int) -> VocabRow | None:
        r = self._c.execute("SELECT * FROM vocab WHERE id = ?", (vocab_id,)).fetchone()
        return _vocab(r) if r else None

    def by_lemma(self, lemma: str) -> VocabRow | None:
        r = self._c.execute("SELECT * FROM vocab WHERE lemma = ?", (lemma,)).fetchone()
        return _vocab(r) if r else None

    def query(
        self, *, book_id: int | None = None, search: str | None = None, since: str | None = None
    ) -> list[VocabRow]:
        sql = "SELECT * FROM vocab WHERE 1=1"
        args: list[object] = []
        if book_id is not None:
            sql += " AND book_id = ?"
            args.append(book_id)
        if search:
            sql += " AND (word LIKE ? OR lemma LIKE ? OR meaning LIKE ? OR sentence LIKE ?)"
            args += [f"%{search}%"] * 4
        if since:
            sql += " AND created_at >= ?"
            args.append(since)
        sql += " ORDER BY created_at DESC, id DESC"
        return [_vocab(r) for r in self._c.execute(sql, args)]

    def set_unknown(self, lemma: str, unknown: bool) -> bool:
        with self._c:
            cur = self._c.execute(
                "UPDATE vocab SET unknown = ? WHERE lemma = ?", (int(unknown), lemma)
            )
        return cur.rowcount > 0

    def delete(self, vocab_id: int) -> bool:
        """Remove a word and (via ON DELETE CASCADE) its review state and log."""
        with self._c:
            cur = self._c.execute("DELETE FROM vocab WHERE id = ?", (vocab_id,))
        return cur.rowcount > 0

    def set_meaning(self, vocab_id: int, meaning: str) -> None:
        with self._c:
            self._c.execute("UPDATE vocab SET meaning = ? WHERE id = ?", (meaning, vocab_id))

    def unknown_meanings(self) -> dict[str, str]:
        """lemma → short meaning for every word marked unknown (book-wide effect)."""
        return {
            r["lemma"]: r["meaning"]
            for r in self._c.execute("SELECT lemma, meaning FROM vocab WHERE unknown = 1")
        }

    def count(self) -> int:
        return int(self._c.execute("SELECT COUNT(*) FROM vocab").fetchone()[0])

    def find_context(self, book_id: int, term: str) -> tuple[int, int, str, str] | None:
        """First extracted block of the book containing ``term``: (page_no, ord, hash, text)."""
        r = self._c.execute(
            "SELECT page_no, ord, text_hash, text FROM blocks WHERE book_id = ? AND type IN"
            " ('paragraph','list_item','heading','caption','footnote') AND text LIKE ?"
            " ORDER BY page_no, ord LIMIT 1",
            (book_id, f"%{term}%"),
        ).fetchone()
        if r is None:
            return None
        return int(r["page_no"]), int(r["ord"]), str(r["text_hash"]), str(r["text"])

    def block_sentences(self, book_id: int, page_no: int, text_hash: str) -> list[str] | None:
        r = self._c.execute(
            "SELECT sentences_json FROM blocks WHERE book_id = ? AND page_no = ? AND text_hash = ?"
            " LIMIT 1",
            (book_id, page_no, text_hash),
        ).fetchone()
        return list(json.loads(r[0])) if r else None

    def translated_sentences(
        self, book_id: int, page_no: int, text_hash: str, lang: str
    ) -> tuple[list[str], bool] | None:
        """Most recent cached translation of a block in any provider/model."""
        r = self._c.execute(
            "SELECT sentences_json, sentence_aligned FROM translations WHERE book_id = ?"
            " AND page_no = ? AND text_hash = ? AND lang = ? ORDER BY created_at DESC LIMIT 1",
            (book_id, page_no, text_hash, lang),
        ).fetchone()
        return (list(json.loads(r[0])), bool(r[1])) if r else None


class ReviewRepo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock = utc_now) -> None:
        self._c = conn
        self._clock = clock

    def get(self, vocab_id: int) -> ReviewRow | None:
        r = self._c.execute("SELECT * FROM reviews WHERE vocab_id = ?", (vocab_id,)).fetchone()
        return _review(r) if r else None

    def upsert(self, row: ReviewRow) -> None:
        with self._c:
            self._upsert(row)

    def _upsert(self, row: ReviewRow) -> None:
        self._c.execute(
            "INSERT INTO reviews(vocab_id, due_at, stability, difficulty, state, step, reps,"
            " lapses, last_review_at, card_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(vocab_id) DO UPDATE SET due_at=excluded.due_at,"
            " stability=excluded.stability, difficulty=excluded.difficulty, state=excluded.state,"
            " step=excluded.step, reps=excluded.reps, lapses=excluded.lapses,"
            " last_review_at=excluded.last_review_at, card_json=excluded.card_json",
            (
                row.vocab_id,
                row.due_at,
                row.stability,
                row.difficulty,
                row.state,
                row.step,
                row.reps,
                row.lapses,
                row.last_review_at,
                row.card_json,
            ),
        )

    def record(self, row: ReviewRow, rating: int, reviewed_at: datetime, log_json: str) -> None:
        """New review state + log entry in one transaction."""
        with self._c:
            self._upsert(row)
            self._c.execute(
                "INSERT INTO review_log(vocab_id, rating, reviewed_at, log_json) VALUES (?,?,?,?)",
                (row.vocab_id, rating, reviewed_at.isoformat(), log_json),
            )

    def due(self, now: datetime, limit: int | None = None) -> list[ReviewRow]:
        sql = "SELECT * FROM reviews WHERE due_at <= ? ORDER BY due_at"
        args: list[object] = [now.isoformat()]
        if limit is not None:
            sql += " LIMIT ?"
            args.append(limit)
        return [_review(r) for r in self._c.execute(sql, args)]

    def count_due(self, until: datetime) -> int:
        q = "SELECT COUNT(*) FROM reviews WHERE due_at <= ?"
        return int(self._c.execute(q, (until.isoformat(),)).fetchone()[0])

    def count_mature(self, min_stability_days: float) -> int:
        q = "SELECT COUNT(*) FROM reviews WHERE stability >= ?"
        return int(self._c.execute(q, (min_stability_days,)).fetchone()[0])

    def review_days(self) -> list[str]:
        """Distinct UTC dates (YYYY-MM-DD) with at least one review, newest first."""
        return [
            r[0]
            for r in self._c.execute(
                "SELECT DISTINCT substr(reviewed_at, 1, 10) AS d FROM review_log ORDER BY d DESC"
            )
        ]

    def count_reviewed_between(self, start: datetime, end: datetime) -> int:
        q = "SELECT COUNT(*) FROM review_log WHERE reviewed_at >= ? AND reviewed_at < ?"
        return int(self._c.execute(q, (start.isoformat(), end.isoformat())).fetchone()[0])

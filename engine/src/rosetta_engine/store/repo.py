"""Repositories. Raw sqlite3; every SQL statement of the engine lives in this module."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, NamedTuple

from rosetta_engine.models import (
    TRANSLATABLE,
    Block,
    BlockType,
    Book,
    BookProfile,
    PageBlocks,
    Translation,
    UsageTotals,
)

Clock = Callable[[], datetime]
PageStatus = Literal["done", "failed"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class CacheKey(NamedTuple):
    page_no: int
    text_hash: str
    lang: str
    provider: str
    model: str


@dataclass(frozen=True)
class TranslationRow:
    book_id: int
    page_no: int
    text_hash: str
    lang: str
    provider: str
    model: str
    text: str
    sentences: list[str]
    sentence_aligned: bool
    prompt_version: int
    unit_hash: str | None = None  # joined-unit rows (page-break paragraph); None = alone
    unit_role: str | None = None  # "head" | "tail"


@dataclass(frozen=True)
class PairRow:
    """A cached translation joined with its source block (term-consistency input)."""

    page_no: int
    block_ord: int
    block_type: str
    text_hash: str
    en_text: str
    en_sentences: list[str]
    tr_text: str
    tr_sentences: list[str]
    sentence_aligned: bool
    unit_hash: str | None
    unit_role: str | None


@dataclass(frozen=True)
class PageStatusRow:
    book_id: int
    page_no: int
    lang: str
    provider: str
    model: str
    status: PageStatus
    error: str | None = None


@dataclass(frozen=True)
class UsageRow:
    book_id: int | None
    provider: str
    model: str
    operation: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    ok: bool
    cache_read_tokens: int = 0
    est_input_tokens: int | None = None
    est_output_tokens: int | None = None
    calibrate: bool = True  # False: excluded from estimator calibration


@dataclass(frozen=True)
class LibraryRow:
    book: Book
    last_opened_at: str | None
    last_page: int | None  # 0-based
    created_at: str


class _Repo:
    def __init__(self, conn: sqlite3.Connection, clock: Clock = utc_now) -> None:
        self._c = conn
        self._clock = clock

    def _now(self) -> str:
        return self._clock().astimezone(UTC).isoformat()


class BookRepo(_Repo):
    def get_or_create(
        self, file_hash: str, title: str, page_count: int, file_path: str | None
    ) -> Book:
        with self._c:
            self._c.execute(
                "INSERT INTO books(file_hash, title, page_count, file_path, created_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(file_hash) DO UPDATE SET "
                "file_path = COALESCE(excluded.file_path, books.file_path)",
                (file_hash, title, page_count, file_path, self._now()),
            )
        book = self.get_by_hash(file_hash)
        assert book is not None
        return book

    def get(self, book_id: int) -> Book | None:
        row = self._c.execute(
            "SELECT id, file_hash, title, page_count, file_path FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
        return None if row is None else self._book(row)

    def file_paths(self) -> list[str]:
        """Stored source PDF paths of every book (exports must never overwrite these)."""
        rows = self._c.execute("SELECT file_path FROM books WHERE file_path IS NOT NULL")
        return [r[0] for r in rows]

    def get_by_hash(self, file_hash: str) -> Book | None:
        row = self._c.execute(
            "SELECT id, file_hash, title, page_count, file_path FROM books WHERE file_hash = ?",
            (file_hash,),
        ).fetchone()
        if row is None:
            return None
        return self._book(row)

    def touch_opened(self, book_id: int) -> None:
        """Record that the book was just opened (library order)."""
        with self._c:
            self._c.execute(
                "UPDATE books SET last_opened_at = ? WHERE id = ?", (self._now(), book_id)
            )

    def set_progress(self, book_id: int, page_no: int) -> LibraryRow | None:
        """Remember the 0-based page the reader is on; also counts as "opened now"."""
        with self._c:
            self._c.execute(
                "UPDATE books SET last_page = ?, last_opened_at = ? WHERE id = ?",
                (page_no, self._now(), book_id),
            )
        rows = self.library(book_id=book_id)
        return rows[0] if rows else None

    def library(self, *, book_id: int | None = None) -> list[LibraryRow]:
        """Books for the library screen, most recently opened first (never-opened last)."""
        sql = (
            "SELECT id, file_hash, title, page_count, file_path, last_opened_at, last_page, "
            "created_at FROM books"
        )
        args: tuple[object, ...] = ()
        if book_id is not None:
            sql += " WHERE id = ?"
            args = (book_id,)
        sql += " ORDER BY last_opened_at IS NULL, last_opened_at DESC, created_at DESC, id DESC"
        return [
            LibraryRow(
                book=self._book(r),
                last_opened_at=r["last_opened_at"],
                last_page=r["last_page"],
                created_at=r["created_at"],
            )
            for r in self._c.execute(sql, args)
        ]

    @staticmethod
    def _book(row: sqlite3.Row) -> Book:
        return Book(
            id=row["id"],
            file_hash=row["file_hash"],
            title=row["title"] or "",
            page_count=row["page_count"],
            file_path=row["file_path"],
        )

    def set_meta(
        self, book_id: int, typography_json: str | None, furniture_json: str | None
    ) -> None:
        with self._c:
            self._c.execute(
                "UPDATE books SET typography_json = ?, furniture_json = ? WHERE id = ?",
                (typography_json, furniture_json, book_id),
            )

    def get_meta(self, book_id: int) -> tuple[str | None, str | None]:
        row = self._c.execute(
            "SELECT typography_json, furniture_json FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        if row is None:
            return None, None
        return row["typography_json"], row["furniture_json"]


class BlockRepo(_Repo):
    def page_version(self, book_id: int, page_no: int) -> int | None:
        row = self._c.execute(
            "SELECT extractor_version FROM pages WHERE book_id = ? AND page_no = ?",
            (book_id, page_no),
        ).fetchone()
        return None if row is None else int(row[0])

    def replace_page(self, book_id: int, page: PageBlocks, extractor_version: int) -> None:
        with self._c:
            self._c.execute(
                "DELETE FROM blocks WHERE book_id = ? AND page_no = ?", (book_id, page.page_no)
            )
            self._c.execute(
                "INSERT INTO pages(book_id, page_no, extractor_version, extracted_at, "
                "has_text_layer, continues_on_next_page, width, height) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(book_id, page_no) DO UPDATE SET "
                "extractor_version = excluded.extractor_version, "
                "extracted_at = excluded.extracted_at, "
                "has_text_layer = excluded.has_text_layer, "
                "continues_on_next_page = excluded.continues_on_next_page, "
                "width = excluded.width, height = excluded.height",
                (
                    book_id,
                    page.page_no,
                    extractor_version,
                    self._now(),
                    int(page.has_text_layer),
                    int(page.continues_on_next_page),
                    page.width,
                    page.height,
                ),
            )
            self._c.executemany(
                "INSERT INTO blocks(book_id, page_no, ord, type, bbox_json, font, size, bold, "
                "italic, heading_level, text, sentences_json, text_hash, family, aside, "
                "list_marker) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        book_id,
                        page.page_no,
                        b.order,
                        b.type.value,
                        json.dumps(list(b.bbox)),
                        b.font,
                        b.size,
                        int(b.bold),
                        int(b.italic),
                        b.heading_level,
                        b.text,
                        json.dumps(b.sentences, ensure_ascii=False),
                        b.text_hash,
                        b.family,
                        int(b.aside),
                        b.list_marker,
                    )
                    for b in page.blocks
                ],
            )

    def get_page(self, book_id: int, page_no: int) -> PageBlocks | None:
        page = self._c.execute(
            "SELECT has_text_layer, continues_on_next_page, width, height FROM pages "
            "WHERE book_id = ? AND page_no = ?",
            (book_id, page_no),
        ).fetchone()
        if page is None:
            return None
        rows = self._c.execute(
            "SELECT * FROM blocks WHERE book_id = ? AND page_no = ? ORDER BY ord",
            (book_id, page_no),
        ).fetchall()
        blocks = [
            Block(
                page_no=page_no,
                order=r["ord"],
                type=BlockType(r["type"]),
                bbox=tuple(json.loads(r["bbox_json"])),
                font=r["font"] or "",
                size=r["size"] or 0.0,
                bold=bool(r["bold"]),
                italic=bool(r["italic"]),
                family=r["family"],
                heading_level=r["heading_level"],
                aside=bool(r["aside"]),
                list_marker=r["list_marker"],
                text=r["text"],
                sentences=json.loads(r["sentences_json"]),
                text_hash=r["text_hash"],
            )
            for r in rows
        ]
        return PageBlocks(
            page_no=page_no,
            width=page["width"],
            height=page["height"],
            has_text_layer=bool(page["has_text_layer"]),
            continues_on_next_page=bool(page["continues_on_next_page"]),
            blocks=blocks,
        )

    def overview(self, book_id: int) -> dict[int, tuple[bool, int]]:
        """Extracted pages only: 0-based page → (has_text_layer, translatable non-blank blocks).

        Read from the DB; nothing is extracted here."""
        out: dict[int, tuple[bool, int]] = {
            int(r["page_no"]): (bool(r["has_text_layer"]), 0)
            for r in self._c.execute(
                "SELECT page_no, has_text_layer FROM pages WHERE book_id = ?", (book_id,)
            )
        }
        kinds = tuple(t.value for t in TRANSLATABLE)
        marks = ", ".join("?" for _ in kinds)
        for r in self._c.execute(
            f"SELECT page_no, COUNT(*) AS n FROM blocks WHERE book_id = ? AND type IN ({marks}) "
            "AND trim(text) <> '' GROUP BY page_no",
            (book_id, *kinds),
        ):
            page = int(r["page_no"])
            if page in out:
                out[page] = (out[page][0], int(r["n"]))
        return out


def _translation(row: sqlite3.Row) -> Translation:
    return Translation(
        page_no=row["page_no"],
        text_hash=row["text_hash"],
        sentences=json.loads(row["sentences_json"]),
        text=row["text"],
        sentence_aligned=bool(row["sentence_aligned"]),
        unit_hash=row["unit_hash"],
        unit_role=row["unit_role"],
    )


class TranslationRepo(_Repo):
    def get_many(self, book_id: int, keys: Sequence[CacheKey]) -> dict[CacheKey, Translation]:
        """One query per (page, lang, provider, model) group instead of one per block."""
        groups: dict[tuple[int, str, str, str], list[CacheKey]] = {}
        for key in dict.fromkeys(keys):
            groups.setdefault((key.page_no, key.lang, key.provider, key.model), []).append(key)
        out: dict[CacheKey, Translation] = {}
        for (page_no, lang, provider, model), group in groups.items():
            page = self.for_page(book_id, page_no, lang, provider, model)
            for key in group:
                hit = page.get(key.text_hash)
                if hit is not None:
                    out[key] = hit
        return out

    def for_page(
        self, book_id: int, page_no: int, lang: str, provider: str, model: str
    ) -> dict[str, Translation]:
        rows = self._c.execute(
            "SELECT page_no, text_hash, text, sentences_json, sentence_aligned, unit_hash, "
            "unit_role FROM translations WHERE book_id = ? AND page_no = ? AND lang = ? "
            "AND provider = ? AND model = ?",
            (book_id, page_no, lang, provider, model),
        ).fetchall()
        return {r["text_hash"]: _translation(r) for r in rows}

    def translated_pages(self, book_id: int, lang: str, provider: str, model: str) -> list[int]:
        """0-based pages with at least one cached translation for lang/provider/model."""
        rows = self._c.execute(
            "SELECT DISTINCT page_no FROM translations WHERE book_id = ? AND lang = ? "
            "AND provider = ? AND model = ? ORDER BY page_no",
            (book_id, lang, provider, model),
        ).fetchall()
        return [int(r["page_no"]) for r in rows]

    def pairs_for_book(self, book_id: int, lang: str, provider: str, model: str) -> list[PairRow]:
        """Every cached translation of the book with its source block, in reading order.

        Repeated blocks (same text_hash twice on a page) yield one row per occurrence."""
        rows = self._c.execute(
            "SELECT t.page_no, t.text_hash, t.text, t.sentences_json, t.sentence_aligned, "
            "t.unit_hash, t.unit_role, b.ord, b.type, b.text AS en_text, "
            "b.sentences_json AS en_sentences FROM translations t JOIN blocks b "
            "ON b.book_id = t.book_id AND b.page_no = t.page_no AND b.text_hash = t.text_hash "
            "WHERE t.book_id = ? AND t.lang = ? AND t.provider = ? AND t.model = ? "
            "ORDER BY t.page_no, b.ord",
            (book_id, lang, provider, model),
        ).fetchall()
        return [
            PairRow(
                page_no=int(r["page_no"]),
                block_ord=int(r["ord"]),
                block_type=r["type"],
                text_hash=r["text_hash"],
                en_text=r["en_text"],
                en_sentences=json.loads(r["en_sentences"]),
                tr_text=r["text"],
                tr_sentences=json.loads(r["sentences_json"]),
                sentence_aligned=bool(r["sentence_aligned"]),
                unit_hash=r["unit_hash"],
                unit_role=r["unit_role"],
            )
            for r in rows
        ]

    def put_rows(self, rows: Sequence[TranslationRow], *, overwrite: bool = False) -> None:
        """Cache translated blocks right away (paid work is never lost). No page status."""
        with self._c:
            _insert_translations(self._c, rows, self._now(), overwrite)

    def put_page(
        self, rows: Sequence[TranslationRow], status: PageStatusRow, *, overwrite: bool = False
    ) -> None:
        """Write translations and the page status atomically.

        ``overwrite=False`` never replaces an existing translation (cache rule);
        ``overwrite=True`` is ``--force``: rows are replaced only once the new ones exist.
        """
        now = self._now()
        with self._c:
            _insert_translations(self._c, rows, now, overwrite)
            _upsert_status(self._c, status, now)


_INSERT_TRANSLATION = (
    "INSERT INTO translations(book_id, page_no, text_hash, lang, provider, model, "
    "text, sentences_json, sentence_aligned, prompt_version, created_at, unit_hash, unit_role) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
)
_ON_CONFLICT_REPLACE = (
    "ON CONFLICT(book_id, page_no, text_hash, lang, provider, model) DO UPDATE SET "
    "text = excluded.text, sentences_json = excluded.sentences_json, "
    "sentence_aligned = excluded.sentence_aligned, prompt_version = excluded.prompt_version, "
    "created_at = excluded.created_at, unit_hash = excluded.unit_hash, "
    "unit_role = excluded.unit_role"
)


def _insert_translations(
    conn: sqlite3.Connection, rows: Sequence[TranslationRow], now: str, overwrite: bool
) -> None:
    conflict = _ON_CONFLICT_REPLACE if overwrite else "ON CONFLICT DO NOTHING"
    conn.executemany(
        _INSERT_TRANSLATION + conflict,
        [
            (
                r.book_id,
                r.page_no,
                r.text_hash,
                r.lang,
                r.provider,
                r.model,
                r.text,
                json.dumps(r.sentences, ensure_ascii=False),
                int(r.sentence_aligned),
                r.prompt_version,
                now,
                r.unit_hash,
                r.unit_role,
            )
            for r in rows
        ],
    )


def _upsert_status(conn: sqlite3.Connection, s: PageStatusRow, now: str) -> None:
    conn.execute(
        "INSERT INTO page_status(book_id, page_no, lang, provider, model, status, error, "
        "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(book_id, page_no, lang, provider, model) DO UPDATE SET "
        "status = excluded.status, error = excluded.error, updated_at = excluded.updated_at",
        (s.book_id, s.page_no, s.lang, s.provider, s.model, s.status, s.error, now),
    )


class PageStatusRepo(_Repo):
    def set(self, row: PageStatusRow) -> None:
        with self._c:
            _upsert_status(self._c, row, self._now())

    def get(
        self, book_id: int, page_no: int, lang: str, provider: str, model: str
    ) -> PageStatusRow | None:
        r = self._c.execute(
            "SELECT status, error FROM page_status WHERE book_id = ? AND page_no = ? "
            "AND lang = ? AND provider = ? AND model = ?",
            (book_id, page_no, lang, provider, model),
        ).fetchone()
        if r is None:
            return None
        return PageStatusRow(book_id, page_no, lang, provider, model, r["status"], r["error"])

    def done_pages(self, book_id: int, lang: str, provider: str, model: str) -> frozenset[int]:
        """0-based pages fully translated ('done') for lang/provider/model."""
        rows = self._c.execute(
            "SELECT page_no FROM page_status WHERE book_id = ? AND lang = ? AND provider = ? "
            "AND model = ? AND status = 'done'",
            (book_id, lang, provider, model),
        )
        return frozenset(int(r["page_no"]) for r in rows)

    def done_count(self, book_id: int, lang: str, provider: str, model: str) -> int:
        return len(self.done_pages(book_id, lang, provider, model))


class UsageRepo(_Repo):
    def add(self, row: UsageRow) -> None:
        with self._c:
            self._c.execute(
                "INSERT INTO usage(ts, book_id, provider, model, operation, input_tokens, "
                "output_tokens, cache_read_tokens, est_input_tokens, est_output_tokens, "
                "cost_usd, ok, calibrate) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._now(),
                    row.book_id,
                    row.provider,
                    row.model,
                    row.operation,
                    row.input_tokens,
                    row.output_tokens,
                    row.cache_read_tokens,
                    row.est_input_tokens,
                    row.est_output_tokens,
                    row.cost_usd,
                    int(row.ok),
                    int(row.calibrate),
                ),
            )

    def total(self, book_id: int | None = None) -> UsageTotals:
        sql = (
            "SELECT COUNT(*), COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0), "
            "COALESCE(SUM(cost_usd), 0.0) FROM usage"
        )
        params: tuple[int, ...] = ()
        if book_id is not None:
            sql += " WHERE book_id = ?"
            params = (book_id,)
        calls, tin, tout, usd = self._c.execute(sql, params).fetchone()
        return UsageTotals(calls=calls, input_tokens=tin, output_tokens=tout, cost_usd=usd)

    def recent_ok(
        self, provider: str, model: str, limit: int = 20
    ) -> list[tuple[int, int, int, int]]:
        """(est_in, actual_in, est_out, actual_out) of the latest successful estimated calls."""
        rows = self._c.execute(
            "SELECT est_input_tokens, input_tokens, est_output_tokens, output_tokens FROM usage "
            "WHERE provider = ? AND model = ? AND ok = 1 AND calibrate = 1 "
            "AND est_input_tokens IS NOT NULL "
            "AND est_output_tokens IS NOT NULL ORDER BY id DESC LIMIT ?",
            (provider, model, limit),
        ).fetchall()
        return [(r[0], r[1], r[2], r[3]) for r in rows]

    def exclude_from_calibration(self, before_ts: str) -> int:
        """Stop rows recorded before ``before_ts`` (UTC ISO-8601) from calibrating estimates."""
        with self._c:
            cur = self._c.execute(
                "UPDATE usage SET calibrate = 0 WHERE ts < ? AND calibrate = 1", (before_ts,)
            )
        return cur.rowcount


class ProfileRepo(_Repo):
    def get(self, book_id: int) -> BookProfile | None:
        row = self._c.execute("SELECT json FROM profiles WHERE book_id = ?", (book_id,)).fetchone()
        return None if row is None else BookProfile.model_validate_json(row["json"])

    def put(self, book_id: int, profile: BookProfile) -> None:
        with self._c:
            self._c.execute(
                "INSERT INTO profiles(book_id, json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(book_id) DO UPDATE SET json = excluded.json, "
                "updated_at = excluded.updated_at",
                (book_id, profile.model_dump_json(), self._now()),
            )


class TermIgnoreRepo(_Repo):
    """Terms the user chose to ignore in the consistency report (per book + language)."""

    def list(self, book_id: int, lang: str) -> set[str]:
        rows = self._c.execute(
            "SELECT term FROM term_ignores WHERE book_id = ? AND lang = ?", (book_id, lang)
        ).fetchall()
        return {str(r["term"]) for r in rows}

    def add(self, book_id: int, lang: str, term: str) -> None:
        with self._c:
            self._c.execute(
                "INSERT INTO term_ignores(book_id, lang, term, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(book_id, lang, term) DO NOTHING",
                (book_id, lang, term, self._now()),
            )

    def remove(self, book_id: int, lang: str, term: str) -> None:
        with self._c:
            self._c.execute(
                "DELETE FROM term_ignores WHERE book_id = ? AND lang = ? AND term = ?",
                (book_id, lang, term),
            )


JobStatus = Literal["pending", "running", "paused", "done", "failed", "cancelled"]


@dataclass(frozen=True)
class JobRow:
    id: int
    book_id: int
    type: str
    lang: str
    provider: str
    model: str
    page_spec: str
    pages: list[int]  # 0-based
    status: JobStatus
    budget_usd: float | None
    spent_usd: float
    done_pages: list[int]
    failed: dict[int, str]  # page_no -> reason
    stop_reason: str | None
    pause_requested: bool
    created_at: str
    updated_at: str

    @property
    def remaining(self) -> list[int]:
        """Pages neither done nor failed."""
        finished = set(self.done_pages) | set(self.failed)
        return [p for p in self.pages if p not in finished]


class JobRepo(_Repo):
    def create(
        self,
        book_id: int,
        lang: str,
        provider: str,
        model: str,
        page_spec: str,
        pages: Sequence[int],
        budget_usd: float | None = None,
    ) -> JobRow:
        now = self._now()
        with self._c:
            cur = self._c.execute(
                "INSERT INTO jobs(book_id, lang, provider, model, page_spec, pages_json, status, "
                "budget_usd, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)",
                (
                    book_id,
                    lang,
                    provider,
                    model,
                    page_spec,
                    json.dumps(list(pages)),
                    budget_usd,
                    now,
                    now,
                ),
            )
        job = self.get(int(cur.lastrowid or 0))
        assert job is not None
        return job

    def get(self, job_id: int) -> JobRow | None:
        row = self._c.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return None if row is None else self._row(row)

    def list_jobs(self, book_id: int | None = None) -> list[JobRow]:
        if book_id is None:
            rows = self._c.execute("SELECT * FROM jobs ORDER BY id DESC").fetchall()
        else:
            rows = self._c.execute(
                "SELECT * FROM jobs WHERE book_id = ? ORDER BY id DESC", (book_id,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def update_progress(
        self,
        job_id: int,
        *,
        done_pages: Sequence[int],
        failed: dict[int, str],
        spent_usd: float,
    ) -> None:
        with self._c:
            self._c.execute(
                "UPDATE jobs SET done_pages_json = ?, failed_json = ?, spent_usd = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    json.dumps(sorted(set(done_pages))),
                    json.dumps({str(k): v for k, v in sorted(failed.items())}),
                    spent_usd,
                    self._now(),
                    job_id,
                ),
            )

    def set_status(self, job_id: int, status: JobStatus, stop_reason: str | None = None) -> None:
        """Set the status; a cancelled job stays cancelled (only 'cancelled' may be re-set)."""
        with self._c:
            self._c.execute(
                "UPDATE jobs SET status = ?, stop_reason = ?, updated_at = ? "
                "WHERE id = ? AND (status != 'cancelled' OR ? = 'cancelled')",
                (status, stop_reason, self._now(), job_id, status),
            )

    def start_running(self, job_id: int) -> bool:
        """Atomically move a runnable job to 'running'. False when it was cancelled, finished
        or has a pending pause request — the caller must then not call the provider."""
        with self._c:
            cur = self._c.execute(
                "UPDATE jobs SET status = 'running', stop_reason = NULL, updated_at = ? "
                "WHERE id = ? AND status IN ('pending', 'paused', 'running', 'failed') "
                "AND pause_requested = 0",
                (self._now(), job_id),
            )
        return cur.rowcount == 1

    def request_pause(self, job_id: int) -> None:
        with self._c:
            self._c.execute(
                "UPDATE jobs SET pause_requested = 1, updated_at = ? WHERE id = ?",
                (self._now(), job_id),
            )

    def pause_requested(self, job_id: int) -> bool:
        row = self._c.execute("SELECT pause_requested FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return bool(row is not None and row[0])

    def clear_pause(self, job_id: int) -> None:
        with self._c:
            self._c.execute("UPDATE jobs SET pause_requested = 0 WHERE id = ?", (job_id,))

    @staticmethod
    def _row(r: sqlite3.Row) -> JobRow:
        return JobRow(
            id=r["id"],
            book_id=r["book_id"],
            type=r["type"],
            lang=r["lang"],
            provider=r["provider"],
            model=r["model"],
            page_spec=r["page_spec"],
            pages=[int(p) for p in json.loads(r["pages_json"])],
            status=r["status"],
            budget_usd=r["budget_usd"],
            spent_usd=float(r["spent_usd"]),
            done_pages=[int(p) for p in json.loads(r["done_pages_json"])],
            failed={int(k): str(v) for k, v in json.loads(r["failed_json"]).items()},
            stop_reason=r["stop_reason"],
            pause_requested=bool(r["pause_requested"]),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )


@dataclass(frozen=True)
class Repos:
    books: BookRepo
    blocks: BlockRepo
    translations: TranslationRepo
    page_status: PageStatusRepo
    usage: UsageRepo
    profiles: ProfileRepo
    jobs: JobRepo
    term_ignores: TermIgnoreRepo
    conn: sqlite3.Connection = field(repr=False, compare=False)

    @classmethod
    def from_conn(cls, conn: sqlite3.Connection, clock: Clock = utc_now) -> Repos:
        return cls(
            books=BookRepo(conn, clock),
            blocks=BlockRepo(conn, clock),
            translations=TranslationRepo(conn, clock),
            page_status=PageStatusRepo(conn, clock),
            usage=UsageRepo(conn, clock),
            profiles=ProfileRepo(conn, clock),
            jobs=JobRepo(conn, clock),
            term_ignores=TermIgnoreRepo(conn, clock),
            conn=conn,
        )

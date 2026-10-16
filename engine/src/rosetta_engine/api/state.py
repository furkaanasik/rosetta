"""Shared server state: settings, open PDFs, per-request SQLite, background jobs.

SQLite connections are opened per request inside the handler (sync handlers run in a worker
thread; the connection never crosses threads). PyMuPDF documents are cached per book and every
use of a document happens under that book's lock, because PyMuPDF objects are not thread-safe.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from rosetta_engine import config
from rosetta_engine.api.confirm import ConfirmStore
from rosetta_engine.api.errors import ApiError, bad_request, not_found
from rosetta_engine.extract.extractor import BookMeta
from rosetta_engine.models import Book, PageBlocks
from rosetta_engine.store.db import connect, migrate
from rosetta_engine.store.repo import Repos
from rosetta_engine.translate.base import Translator
from rosetta_engine.translate.claude_cli import Completion, complete
from rosetta_engine.translate.fake import FakeTranslator
from rosetta_engine.translate.providers import make_translator
from rosetta_engine.translate.service import PageTranslationService

log = logging.getLogger(__name__)

TranslatorFactory = Callable[[str, str | None, config.Settings], Translator]
CompleteFn = Callable[..., Completion]


@dataclass
class OpenBook:
    book: Book
    doc: pymupdf.Document
    meta: BookMeta
    path: Path
    lock: threading.RLock = field(default_factory=threading.RLock)


@dataclass(frozen=True)
class Session:
    repos: Repos
    settings: config.Settings

    @property
    def conn(self) -> sqlite3.Connection:
        return self.repos.conn


class EngineState:
    def __init__(
        self,
        settings: config.Settings,
        *,
        translator_factory: TranslatorFactory = make_translator,
        complete_fn: CompleteFn = complete,
        confirm: ConfirmStore | None = None,
    ) -> None:
        self.settings = settings
        self.translator_factory = translator_factory
        self.complete_fn = complete_fn
        self.confirm = confirm or ConfirmStore()
        self._books: dict[int, OpenBook] = {}
        self._books_lock = threading.Lock()
        self._job_threads: dict[int, threading.Thread] = {}
        self._jobs_lock = threading.Lock()
        self._migrated = False
        self._migrate_lock = threading.Lock()

    # --- database ---------------------------------------------------------------------------

    @contextmanager
    def db(self) -> Iterator[Session]:
        conn = connect(config.db_path())
        try:
            if not self._migrated:
                with self._migrate_lock:
                    if not self._migrated:
                        migrate(conn)
                        self._migrated = True
            yield Session(Repos.from_conn(conn), self.settings)
        finally:
            conn.close()

    def extraction_service(self, s: Session) -> PageTranslationService:
        """A service used only for extraction/reading; its fake translator is never called."""
        return PageTranslationService(FakeTranslator(), s.repos, self.settings)

    def default_translator(self) -> Translator:
        """Translator whose cache key (name, model) the read endpoints show by default."""
        try:
            return self.translator_factory(self.settings.provider, None, self.settings)
        except Exception:  # e.g. a provider that needs credentials at construction
            return FakeTranslator(model=self.settings.model)

    # --- books --------------------------------------------------------------------------------

    def open_book(self, s: Session, path: Path) -> OpenBook:
        if not path.is_file():
            raise bad_request(f"Dosya bulunamadı: {path}")
        if path.suffix.lower() != ".pdf":
            raise bad_request("Yalnızca PDF dosyaları açılabilir")
        book, doc, meta = self.extraction_service(s).open_book(path)
        with self._books_lock:
            old = self._books.get(book.id)
            if old is not None:
                doc.close()  # type: ignore[no-untyped-call]
                return old
            ob = OpenBook(book, doc, meta, path)
            self._books[book.id] = ob
            return ob

    def book(self, s: Session, book_id: int) -> OpenBook:
        """The open book, reopened from its stored path after a restart."""
        with self._books_lock:
            ob = self._books.get(book_id)
        if ob is not None:
            return ob
        stored = s.repos.books.get(book_id)
        if stored is None:
            raise not_found(f"Kitap bulunamadı: #{book_id}")
        if not stored.file_path or not Path(stored.file_path).is_file():
            raise bad_request(f"Kitabın PDF dosyası yok: {stored.file_path}; yeniden aç")
        return self.open_book(s, Path(stored.file_path))

    def pages(self, s: Session, ob: OpenBook, pages: list[int]) -> dict[int, PageBlocks]:
        """0-based pages extracted (or from the DB), under the book's document lock."""
        with ob.lock:
            return self.extraction_service(s).ensure_pages(ob.book, ob.doc, ob.meta, pages)

    def check_pages(self, ob: OpenBook, pages_1based: list[int]) -> list[int]:
        if not pages_1based:
            raise bad_request("Sayfa listesi boş")
        bad = [p for p in pages_1based if not 1 <= p <= ob.book.page_count]
        if bad:
            raise bad_request(f"Sayfa aralık dışında: {bad[0]} (1-{ob.book.page_count})")
        return sorted({p - 1 for p in pages_1based})

    def close(self) -> None:
        with self._books_lock:
            for ob in self._books.values():
                ob.doc.close()  # type: ignore[no-untyped-call]
            self._books.clear()

    # --- background jobs ----------------------------------------------------------------------

    def start_job_thread(self, job_id: int, target: Callable[[], None]) -> None:
        with self._jobs_lock:
            running = [j for j, t in self._job_threads.items() if t.is_alive()]
            if running:
                raise ApiError(
                    "unavailable", f"Başka bir toplu iş çalışıyor (#{running[0]}); önce duraklat"
                )
            t = threading.Thread(target=target, name=f"rosetta-job-{job_id}", daemon=True)
            self._job_threads[job_id] = t
            t.start()

    def job_thread(self, job_id: int) -> threading.Thread | None:
        with self._jobs_lock:
            return self._job_threads.get(job_id)

"""Run a translation job batch by batch, persisting progress after every batch.

A job is a list of pages. Progress (done pages, failed pages + reasons, spent $) is written
to the ``jobs`` table after each batch, so a crash, Ctrl-C or a usage limit never loses work:
``resume`` plans only the remaining pages (cached translations make finished pages free) and
``retry_failed`` re-runs only the failed ones. A pause can be requested from another process
(CLI or API) through the ``pause_requested`` flag, which is polled before every batch.
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from types import FrameType

import pymupdf

from rosetta_engine.errors import RosettaError
from rosetta_engine.extract.extractor import BookMeta
from rosetta_engine.models import Book, BookProfile, TranslationPlan, TranslationReport
from rosetta_engine.store.repo import JobRow, Repos
from rosetta_engine.translate.service import PageTranslationService

log = logging.getLogger(__name__)

# stop_kind of the service → (job status, exit category)
PAUSING_STOPS = frozenset({"usage_limit", "budget", "auth", "unavailable", "paused"})
FINISHED = frozenset({"done", "failed", "cancelled"})

JobCallback = Callable[[JobRow], None]

BUDGET_NO_PRICE = (
    "Model fiyatı bilinmiyor: bütçe önceden uygulanamaz; iş yalnızca gerçek harcama "
    "bütçeye ulaşınca duraklar."
)


class JobError(RosettaError):
    """Invalid job operation (unknown id, finished job, …)."""


class JobNotStarted(JobError):
    """The job was cancelled, finished or paused before it could start; nothing was called."""


class JobRunner:
    def __init__(self, service: PageTranslationService | None, repos: Repos) -> None:
        """``service`` may be None for repo-only operations (pause, cancel, status)."""
        self._svc_or_none = service
        self._r = repos
        self._interrupted = False

    @property
    def _svc(self) -> PageTranslationService:
        if self._svc_or_none is None:
            raise JobError("bu işlem için çeviri servisi gerekli")
        return self._svc_or_none

    # --- lifecycle ---------------------------------------------------------------------

    def create(
        self,
        book: Book,
        pages: Sequence[int],
        page_spec: str,
        lang: str,
        provider: str,
        model: str,
        budget_usd: float | None = None,
    ) -> JobRow:
        return self._r.jobs.create(
            book.id, lang, provider, model, page_spec, sorted(set(pages)), budget_usd
        )

    def get(self, job_id: int) -> JobRow:
        job = self._r.jobs.get(job_id)
        if job is None:
            raise JobError(f"iş bulunamadı: #{job_id}")
        return job

    def request_pause(self, job_id: int) -> JobRow:
        """Ask a running job to pause before its next batch; a waiting job pauses at once."""
        job = self.get(job_id)
        if job.status in FINISHED:
            raise JobError(f"iş #{job_id} zaten bitti ({job.status})")
        self._r.jobs.request_pause(job_id)
        if job.status == "pending":
            self._r.jobs.set_status(job_id, "paused", "pause requested")
        return self.get(job_id)

    def cancel(self, job_id: int) -> JobRow:
        job = self.get(job_id)
        if job.status in FINISHED:
            raise JobError(f"iş #{job_id} zaten bitti ({job.status})")
        self._r.jobs.request_pause(job_id)  # a running process stops before its next batch
        self._r.jobs.set_status(job_id, "cancelled", "cancelled by user")
        return self.get(job_id)

    def prepare_continue(self, job_id: int) -> JobRow:
        """After the user confirmed a resume/retry: drop a stale pause request (e.g. from
        pausing a waiting job) so the job can start. A pause requested after this call is
        still honoured, because ``run`` starts atomically only without a pending request."""
        job = self.get(job_id)
        if job.status in FINISHED and job.status != "failed":
            raise JobError(f"iş #{job_id} zaten bitti ({job.status})")
        self._r.jobs.clear_pause(job_id)
        return self.get(job_id)

    def reset_failed(self, job_id: int) -> JobRow:
        """Move failed pages back to the remaining set (for ``retry-failed``)."""
        job = self.get(job_id)
        if not job.failed:
            raise JobError(f"iş #{job_id}: hatalı sayfa yok")
        if job.status == "cancelled":
            raise JobError(f"iş #{job_id} iptal edilmiş")
        self._r.jobs.update_progress(
            job_id, done_pages=job.done_pages, failed={}, spent_usd=job.spent_usd
        )
        self._r.jobs.set_status(job_id, "paused", "retry failed pages")
        return self.get(job_id)

    # --- planning (no AI) --------------------------------------------------------------

    def plan(
        self,
        job: JobRow,
        doc: pymupdf.Document,
        meta: BookMeta,
        book: Book,
        *,
        profile: BookProfile | None = None,
        only: Sequence[int] | None = None,
    ) -> TranslationPlan:
        """Plan the job's remaining pages (or ``only`` these). Never calls the provider."""
        pages = list(only) if only is not None else job.remaining
        return self._svc.plan(book, doc, meta, pages, job.lang, profile=profile)

    # --- execution ---------------------------------------------------------------------

    def run(
        self,
        job: JobRow,
        plan: TranslationPlan,
        *,
        profile: BookProfile | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        on_update: JobCallback | None = None,
    ) -> tuple[JobRow, TranslationReport]:
        """Execute ``plan`` for ``job``. Call only after the user approved the estimate.

        Starts with an atomic transition to 'running' that fails if the job was cancelled or a
        pause was requested meanwhile; then raises ``JobNotStarted`` without any provider call.
        """
        jid = job.id
        if not self._r.jobs.start_running(jid):
            current = self.get(jid)
            if current.status not in FINISHED and current.pause_requested:
                self._r.jobs.set_status(jid, "paused", "pause requested")
                self._r.jobs.clear_pause(jid)
            raise JobNotStarted(f"iş #{jid} başlatılmadı ({self.get(jid).status})")
        job = self.get(jid)  # fresh progress: another process may have advanced it
        base_done = set(job.done_pages)
        base_failed = dict(job.failed)
        base_spent = job.spent_usd
        remaining_budget = None if job.budget_usd is None else max(job.budget_usd - base_spent, 0.0)

        def merge(report: TranslationReport) -> tuple[list[int], dict[int, str], float]:
            done = base_done | set(report.done_pages)
            failed = {p: r for p, r in base_failed.items() if p not in done}
            failed.update(report.failed_pages)
            return sorted(done), failed, base_spent + report.usage.cost_usd

        def persist(report: TranslationReport) -> None:
            done, failed, spent = merge(report)
            self._r.jobs.update_progress(jid, done_pages=done, failed=failed, spent_usd=spent)
            if on_update is not None:
                on_update(self.get(jid))

        def should_stop() -> bool:
            return self._interrupted or self._r.jobs.pause_requested(jid)

        self._interrupted = False
        with self._sigint_pauses():
            try:
                report = self._svc.execute(
                    plan,
                    profile=profile,
                    on_progress=on_progress,
                    should_stop=should_stop,
                    budget_usd=remaining_budget,
                    on_batch=persist,
                )
            except BaseException as e:
                # Progress up to the last finished batch is already persisted.
                self._r.jobs.set_status(jid, "paused", f"interrupted: {e!r}")
                log.warning("job %d interrupted: %r", jid, e)
                raise

        persist(report)
        current = self.get(jid)
        if current.status == "cancelled":
            return current, report
        if report.stop_kind in PAUSING_STOPS:
            reason = report.stopped_reason or report.stop_kind or "paused"
            if self._interrupted:
                reason = "interrupted (Ctrl-C)"
            self._r.jobs.set_status(jid, "paused", reason)
        elif current.remaining:
            # Pages left that this plan did not cover (should not happen) → stay resumable.
            self._r.jobs.set_status(jid, "paused", "pages remaining")
        elif current.failed:
            self._r.jobs.set_status(jid, "failed", f"{len(current.failed)} sayfa hatalı")
        else:
            self._r.jobs.set_status(jid, "done")
        self._r.jobs.clear_pause(jid)
        return self.get(jid), report

    @contextmanager
    def _sigint_pauses(self) -> Iterator[None]:
        """While running, Ctrl-C requests a clean pause instead of killing a paid call."""
        if threading.current_thread() is not threading.main_thread():
            yield
            return

        def handler(signum: int, frame: FrameType | None) -> None:
            if self._interrupted:  # second Ctrl-C: give up immediately
                raise KeyboardInterrupt
            self._interrupted = True
            log.warning("Ctrl-C: pausing after the current batch (press again to abort)")

        previous = signal.signal(signal.SIGINT, handler)
        try:
            yield
        finally:
            signal.signal(signal.SIGINT, previous)

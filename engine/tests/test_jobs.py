"""Faz 4: JobRunner (FakeTranslator + in-memory DB) and the ``rosetta job`` CLI."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from rosetta_engine import cli
from rosetta_engine.config import Price, Settings
from rosetta_engine.jobs.runner import JobError, JobRunner
from rosetta_engine.store import db
from rosetta_engine.store.repo import JobRow, Repos
from rosetta_engine.translate.base import ProviderResult, TranslationRequest
from rosetta_engine.translate.fake import FailMode, FakeTranslator
from rosetta_engine.translate.service import PageTranslationService

ALL = [0, 1, 2]


@pytest.fixture
def repos() -> Iterator[Repos]:
    conn = db.connect(":memory:")
    db.migrate(conn)
    yield Repos.from_conn(conn)
    conn.close()


def _runner(
    repos: Repos,
    translator: FakeTranslator | None = None,
    **settings: Any,
) -> tuple[JobRunner, PageTranslationService, FakeTranslator]:
    fake = translator or FakeTranslator()
    settings.setdefault("batch_max_pages", 1)  # one page per batch → one call per page
    svc = PageTranslationService(fake, repos, Settings(**settings))
    return JobRunner(svc, repos), svc, fake


def _start(
    runner: JobRunner, svc: PageTranslationService, pdf: Path, budget: float | None = None
) -> tuple[JobRow, Any]:
    book, doc, meta = svc.open_book(pdf)
    job = runner.create(book, ALL, "1-3", "tr", "fake", "fake", budget)
    return job, (book, doc, meta)


def _run(runner: JobRunner, job: JobRow, ctx: Any, **kw: Any) -> tuple[JobRow, Any]:
    book, doc, meta = ctx
    plan = runner.plan(job, doc, meta, book)
    return runner.run(job, plan, **kw)


def _failing(mode: FailMode, after: int) -> FakeTranslator:
    return FakeTranslator(fail_mode=mode, fail_after=after)


def test_job_runs_to_done_and_persists_progress_per_batch(repos: Repos, book_pdf: Path) -> None:
    runner, svc, fake = _runner(repos)
    job, ctx = _start(runner, svc, book_pdf)
    updates: list[JobRow] = []

    final, report = _run(runner, job, ctx, on_update=updates.append)

    assert final.status == "done"
    assert final.done_pages == ALL
    assert final.remaining == []
    assert len(fake.calls) == 3
    assert [len(u.done_pages) for u in updates][:3] == [1, 2, 3]  # saved after every batch
    assert report.usage.calls == 3


def test_plan_never_calls_provider(repos: Repos, book_pdf: Path) -> None:
    runner, svc, fake = _runner(repos)
    job, (book, doc, meta) = _start(runner, svc, book_pdf)

    plan = runner.plan(job, doc, meta, book)

    assert plan.batches
    assert fake.calls == []


def test_usage_limit_pauses_and_keeps_done_pages(repos: Repos, book_pdf: Path) -> None:
    runner, svc, _ = _runner(repos, _failing("limit", 1))
    job, ctx = _start(runner, svc, book_pdf)

    final, report = _run(runner, job, ctx)

    assert report.stop_kind == "usage_limit"
    assert final.status == "paused"
    assert final.stop_reason
    assert final.done_pages == [0]
    assert final.remaining == [1, 2]


def test_resume_translates_only_remaining_pages(repos: Repos, book_pdf: Path) -> None:
    runner, svc, _ = _runner(repos, _failing("limit", 1))
    job, ctx = _start(runner, svc, book_pdf)
    paused, _ = _run(runner, job, ctx)

    healthy = FakeTranslator()
    runner2, svc2, _ = _runner(repos, healthy)
    book, doc, meta = svc2.open_book(book_pdf)
    plan = runner2.plan(paused, doc, meta, book)
    final, _ = runner2.run(paused, plan)

    assert plan.pages == [1, 2]
    sent_pages = {item_page for req, _ in healthy.calls for item_page in _pages_of(req, plan)}
    assert sent_pages == {1, 2}
    assert len(healthy.calls) == 2
    assert final.status == "done"
    assert final.done_pages == ALL


def _pages_of(req: TranslationRequest, plan: Any) -> set[int]:
    texts = {" ".join(i.sentences) for i in req.items}
    return {b.page_no for batch in plan.batches for b in batch.blocks if b.text in texts}


def test_budget_pauses_before_an_unaffordable_batch(repos: Repos, book_pdf: Path) -> None:
    pricey = {"fake": Price(input=1000.0, output=1000.0)}
    runner, svc, fake = _runner(repos, pricing=pricey)
    job, ctx = _start(runner, svc, book_pdf, budget=0.0001)

    final, report = _run(runner, job, ctx)

    assert fake.calls == []
    assert report.stop_kind == "budget"
    assert final.status == "paused"
    assert "budget" in (final.stop_reason or "")


def test_failed_pages_then_retry_only_failed(repos: Repos, book_pdf: Path) -> None:
    runner, svc, _ = _runner(repos, _failing("error", 1))
    job, ctx = _start(runner, svc, book_pdf)
    first, _ = _run(runner, job, ctx)

    assert first.status == "failed"
    assert first.done_pages == [0]
    assert sorted(first.failed) == [1, 2]

    healthy = FakeTranslator()
    runner2, svc2, _ = _runner(repos, healthy)
    reset = runner2.reset_failed(first.id)
    book, doc, meta = svc2.open_book(book_pdf)
    plan = runner2.plan(reset, doc, meta, book)
    final, _ = runner2.run(reset, plan)

    assert plan.pages == [1, 2]
    assert len(healthy.calls) == 2
    assert final.status == "done"
    assert final.failed == {}


class _PausingFake(FakeTranslator):
    """Requests a pause (like another process would) after its first call."""

    def __init__(self, repos: Repos) -> None:
        super().__init__()
        self.repos = repos
        self.job_id = 0

    def translate(self, request: TranslationRequest, *, strict: bool = False) -> ProviderResult:
        result = super().translate(request, strict=strict)
        self.repos.jobs.request_pause(self.job_id)
        return result


def test_external_pause_flag_stops_before_next_batch(repos: Repos, book_pdf: Path) -> None:
    pausing = _PausingFake(repos)
    runner, svc, _ = _runner(repos, pausing)
    job, ctx = _start(runner, svc, book_pdf)
    pausing.job_id = job.id

    final, report = _run(runner, job, ctx)

    assert len(pausing.calls) == 1
    assert report.stop_kind == "paused"
    assert final.status == "paused"
    assert final.done_pages == [0]
    assert final.pause_requested is False  # cleared so resume can run


def test_pause_and_cancel_without_service(repos: Repos, book_pdf: Path) -> None:
    runner, svc, _ = _runner(repos)
    job, _ = _start(runner, svc, book_pdf)
    repo_only = JobRunner(None, repos)

    paused = repo_only.request_pause(job.id)
    cancelled = repo_only.cancel(job.id)

    assert paused.status == "paused"
    assert cancelled.status == "cancelled"
    with pytest.raises(JobError):
        repo_only.cancel(job.id)
    with pytest.raises(JobError):
        repo_only.get(999)


def test_auth_and_unavailable_pause(repos: Repos, book_pdf: Path) -> None:
    for mode in ("auth", "unavailable"):
        runner, svc, _ = _runner(repos, _failing(mode, 0))
        job, ctx = _start(runner, svc, book_pdf)
        final, report = _run(runner, job, ctx)
        assert final.status == "paused", mode
        assert report.stop_kind in {"auth", "unavailable"}


def test_job_repo_roundtrip(repos: Repos, book_pdf: Path) -> None:
    runner, svc, _ = _runner(repos)
    job, _ = _start(runner, svc, book_pdf, budget=2.5)

    repos.jobs.update_progress(job.id, done_pages=[2, 0], failed={1: "boom"}, spent_usd=0.12)
    got = repos.jobs.get(job.id)

    assert got is not None
    assert got.budget_usd == 2.5
    assert got.done_pages == [0, 2]
    assert got.failed == {1: "boom"}
    assert got.remaining == []
    assert got.spent_usd == pytest.approx(0.12)
    assert [j.id for j in repos.jobs.list_jobs(job.book_id)] == [job.id]
    assert repos.jobs.list_jobs(job.book_id + 99) == []


# --- CLI ---------------------------------------------------------------------------------

runner_cli = CliRunner()


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path / "cfg"))
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "config.toml").write_text("batch_max_pages = 1\n")
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)


def _use(monkeypatch: pytest.MonkeyPatch, t: FakeTranslator) -> None:
    monkeypatch.setattr(cli, "_translator", lambda provider, model, settings: t)


def _job_rows() -> list[JobRow]:
    from rosetta_engine import config

    conn = db.connect(config.db_path())
    db.migrate(conn)
    try:
        return Repos.from_conn(conn).jobs.list_jobs()
    finally:
        conn.close()


@pytest.mark.usefixtures("cli_env")
def test_cli_start_declined_makes_no_calls_and_no_job(
    book_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeTranslator()
    _use(monkeypatch, fake)

    result = runner_cli.invoke(cli.app, ["job", "start", str(book_pdf), "--all"], input="n\n")

    assert result.exit_code == cli.EXIT_CANCELLED
    assert fake.calls == []
    assert _job_rows() == []


@pytest.mark.usefixtures("cli_env")
def test_cli_requires_pages_or_all(book_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, FakeTranslator())

    neither = runner_cli.invoke(cli.app, ["job", "start", str(book_pdf)])
    both = runner_cli.invoke(cli.app, ["job", "start", str(book_pdf), "-p", "1", "--all"])

    assert neither.exit_code != 0
    assert both.exit_code != 0


@pytest.mark.usefixtures("cli_env")
def test_cli_limit_pause_then_resume(book_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, _failing("limit", 1))
    first = runner_cli.invoke(cli.app, ["job", "start", str(book_pdf), "-p", "1-3", "--yes"])

    assert first.exit_code == cli.EXIT_USAGE_LIMIT, first.output
    (job,) = _job_rows()
    assert job.status == "paused"
    assert "rosetta job resume" in first.output

    healthy = FakeTranslator()
    _use(monkeypatch, healthy)
    declined = runner_cli.invoke(cli.app, ["job", "resume", str(job.id)], input="n\n")
    assert declined.exit_code == cli.EXIT_CANCELLED
    assert healthy.calls == []

    resumed = runner_cli.invoke(cli.app, ["job", "resume", str(job.id), "--yes"])

    assert resumed.exit_code == 0, resumed.output
    assert len(healthy.calls) == 2
    (done,) = _job_rows()
    assert done.status == "done"
    listing = runner_cli.invoke(cli.app, ["job", "list"])
    assert "bitti" in listing.output
    status = runner_cli.invoke(cli.app, ["job", "status", str(job.id)])
    assert "3/3" in status.output


@pytest.mark.usefixtures("cli_env")
def test_cli_failed_pages_exit_3_and_retry_failed(
    book_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, _failing("error", 1))
    first = runner_cli.invoke(cli.app, ["job", "start", str(book_pdf), "-p", "1-3", "--yes"])
    (job,) = _job_rows()

    assert first.exit_code == cli.EXIT_PARTIAL, first.output
    assert sorted(job.failed) == [1, 2]

    healthy = FakeTranslator()
    _use(monkeypatch, healthy)
    retry = runner_cli.invoke(cli.app, ["job", "retry-failed", str(job.id), "--yes"])

    assert retry.exit_code == 0, retry.output
    assert len(healthy.calls) == 2
    (done,) = _job_rows()
    assert done.status == "done"


@pytest.mark.usefixtures("cli_env")
def test_cli_pause_cancel_and_unknown_job(book_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _use(monkeypatch, _failing("limit", 0))
    runner_cli.invoke(cli.app, ["job", "start", str(book_pdf), "-p", "1-2", "--yes"])
    (job,) = _job_rows()

    paused = runner_cli.invoke(cli.app, ["job", "pause", str(job.id)])
    cancelled = runner_cli.invoke(cli.app, ["job", "cancel", str(job.id)])
    missing = runner_cli.invoke(cli.app, ["job", "status", "999"])

    assert paused.exit_code == 0
    assert cancelled.exit_code == 0
    (row,) = _job_rows()
    assert row.status == "cancelled"
    assert missing.exit_code == 1


@pytest.mark.usefixtures("cli_env")
def test_cli_non_tty_without_yes_refuses(book_pdf: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTranslator()
    _use(monkeypatch, fake)
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)

    result = runner_cli.invoke(cli.app, ["job", "start", str(book_pdf), "-p", "1"])

    assert result.exit_code == cli.EXIT_CANCELLED
    assert fake.calls == []

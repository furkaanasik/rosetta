"""``rosetta job …``: batch translation of a page range or the whole book (Faz 4).

Same rules as ``translate``: estimate first, confirm (``--yes`` only for non-interactive use),
every call cached. Progress is saved after each batch, so ``resume`` continues where a pause,
usage limit, budget stop or crash left off.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn
from rich.table import Table

from rosetta_engine import config
from rosetta_engine.errors import ExtractionError, RosettaError
from rosetta_engine.jobs.runner import BUDGET_NO_PRICE, JobError, JobRunner
from rosetta_engine.models import BookProfile, TranslationReport
from rosetta_engine.store.db import connect, migrate
from rosetta_engine.store.repo import JobRow, Repos

job_app = typer.Typer(no_args_is_help=True, help="Toplu çeviri işleri (aralık / tüm kitap)")

JobId = Annotated[int, typer.Argument(help="İş numarası")]
YesOpt = Annotated[bool, typer.Option("--yes", "-y", help="Onay sorma")]
ProfileOpt = Annotated[
    Path | None, typer.Option("--profile", exists=True, dir_okay=False, help="profile.json")
]

_STATUS_TR = {
    "pending": "bekliyor",
    "running": "çalışıyor",
    "paused": "duraklatıldı",
    "done": "bitti",
    "failed": "hatalı sayfa var",
    "cancelled": "iptal",
}


def _cli() -> Any:
    """The CLI module, imported lazily: it loads this plugin while being initialised."""
    from rosetta_engine import cli

    return cli


@contextmanager
def _repos() -> Iterator[Repos]:
    conn: sqlite3.Connection = connect(config.db_path())
    try:
        migrate(conn)
        yield Repos.from_conn(conn)
    finally:
        conn.close()


def _fail(e: RosettaError) -> typer.Exit:
    exit_: typer.Exit = _cli()._fail(e)
    return exit_


def _summary(job: JobRow) -> str:
    budget = "" if job.budget_usd is None else f" / bütçe ${job.budget_usd:.2f}"
    return (
        f"İş #{job.id}: {_STATUS_TR.get(job.status, job.status)} — "
        f"{len(job.done_pages)}/{len(job.pages)} sayfa bitti, {len(job.failed)} hatalı, "
        f"harcanan ≈ ${job.spent_usd:.3f}{budget}"
    )


def _confirm(yes: bool) -> None:
    c = _cli()
    if yes:
        return
    if not c._stdin_is_tty():
        c.err.print("stdin bir terminal değil; onay için --yes kullan.")
        raise typer.Exit(c.EXIT_CANCELLED)
    if not typer.confirm("Onaylıyor musun?", default=False):
        c.console.print("İptal edildi; AI çağrısı yapılmadı.")
        raise typer.Exit(c.EXIT_CANCELLED)


def _execute(
    s: Any,  # cli._Session
    runner: JobRunner,
    job: JobRow,
    profile: BookProfile | None,
    *,
    yes: bool,
    only: list[int] | None = None,
    continuing: bool = False,
) -> None:
    """Plan the job's remaining pages, confirm, run, write HTML and exit with a status code.

    Nothing about the job changes before the user confirms (a declined retry keeps its failed
    pages); ``continuing`` clears a stale pause request only after confirmation."""
    c = _cli()
    plan = runner.plan(job, s.doc, s.meta, s.book, profile=profile, only=only)
    c._print_plan(plan, s)
    if job.budget_usd is not None:
        c.console.print(
            f"Bütçe: ${job.budget_usd:.2f} (harcanan ≈ ${job.spent_usd:.3f}); "
            "aşılacaksa iş duraklar."
        )
        if not plan.estimate.price_known:
            c.err.print(f"[yellow]{BUDGET_NO_PRICE}[/]")
    report: TranslationReport
    if plan.batches:
        _confirm(yes)
    if continuing:
        job = runner.prepare_continue(job.id)
    if plan.batches:
        with Progress(
            TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(),
            console=c.console, transient=True,
        ) as bar:  # fmt: skip
            task = bar.add_task(f"iş #{job.id}", total=len(plan.batches))
            job, report = runner.run(
                job,
                plan,
                profile=profile,
                on_progress=lambda n, total: bar.update(task, completed=n, total=total),
            )
    else:
        c.console.print("0 çağrı — tümü cache'te.")
        job, report = runner.run(job, plan, profile=profile)

    out_dir = config.output_dir(s.book.file_hash)
    for p in report.done_pages:
        page, translations = s.service.page_view(s.book, p, job.lang)
        for mode in ("tr", "review"):
            c.write_page(s.book, page, translations, mode, out_dir, doc=s.doc, lang=job.lang)
    if report.done_pages:
        c._write_index(s.book, out_dir)
        c.console.print(f"Çıktı: {out_dir}")

    u = report.usage
    c.console.print(
        f"Bu çalıştırma: {u.calls} çağrı, in {c._num(u.input_tokens)} / "
        f"out {c._num(u.output_tokens)} tok, ${u.cost_usd:.3f}"
    )
    c.console.print(_summary(job))
    for p, reason in sorted(job.failed.items()):
        c.err.print(f"[red]Sayfa {p + 1} başarısız:[/] {reason}")

    if job.status == "paused":
        c.err.print(f"[yellow]Duraklatıldı:[/] {job.stop_reason}")
        c.console.print(f"Devam etmek için: rosetta job resume {job.id}")
        codes = {
            "usage_limit": c.EXIT_USAGE_LIMIT,
            "budget": c.EXIT_BUDGET,
            "auth": c.EXIT_AUTH,
            "unavailable": c.EXIT_UNAVAILABLE,
        }
        code = codes.get(report.stop_kind or "", c.EXIT_OK)
        if code != c.EXIT_OK:
            raise typer.Exit(code)
        return
    if job.status == "failed":
        c.console.print(f"Sadece hatalıları tekrar denemek için: rosetta job retry-failed {job.id}")
        raise typer.Exit(c.EXIT_PARTIAL)


@job_app.command("start")
def start(
    pdf: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="PDF")],
    pages: Annotated[
        str | None, typer.Option("--pages", "-p", help="1-based: 120-140 | 41,43,50-52")
    ] = None,
    all_: Annotated[bool, typer.Option("--all", help="Tüm kitap")] = False,
    budget: Annotated[
        float | None, typer.Option("--budget", min=0.0, help="İş bütçesi (≈ liste fiyatı $)")
    ] = None,
    yes: YesOpt = False,
    lang: Annotated[str | None, typer.Option("--lang")] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", help="claude-cli | fake | deepl | ollama")
    ] = None,
    model: Annotated[str | None, typer.Option("--model")] = None,
    profile: ProfileOpt = None,
) -> None:
    """Yeni iş: tahmin → onay → batch batch çeviri (ilerleme her batch'te kaydedilir)."""
    c = _cli()
    if (pages is None) == (not all_):
        raise typer.BadParameter("--pages veya --all (yalnızca biri) gerekli")
    book_profile = c._load_profile(profile)
    try:
        with c._session(pdf, None if all_ else pages, provider, model) as s:
            book_profile = c._resolve_profile(book_profile, s)
            target = lang or s.settings.default_lang
            runner = JobRunner(s.service, s.repos)
            # Plan once before creating the job so a declined estimate leaves no trace.
            plan = s.service.plan(s.book, s.doc, s.meta, s.pages, target, profile=book_profile)
            c._print_plan(plan, s)
            if budget is not None:
                c.console.print(f"Bütçe: ${budget:.2f}; aşılacaksa iş duraklar.")
                if not plan.estimate.price_known:
                    c.err.print(f"[yellow]{BUDGET_NO_PRICE}[/]")
            if plan.batches:
                _confirm(yes)
            job = runner.create(
                s.book, s.pages, pages or "all", target, plan.provider, plan.model, budget
            )
            c.console.print(f"İş #{job.id} oluşturuldu ({len(job.pages)} sayfa).")
            _execute(s, runner, job, book_profile, yes=True)
    except (ExtractionError, JobError) as e:
        raise _fail(e) from e


def _continue(job_id: int, yes: bool, profile: Path | None, *, retry: bool) -> None:
    c = _cli()
    book_profile = c._load_profile(profile)
    with _repos() as repos:
        job_row = repos.jobs.get(job_id)
        if job_row is None:
            raise _fail(JobError(f"iş bulunamadı: #{job_id}"))
        if retry:
            if not job_row.failed:
                raise _fail(JobError(f"iş #{job_id}: hatalı sayfa yok"))
            only = sorted(job_row.failed)
        else:
            if job_row.status in ("done", "cancelled"):
                raise _fail(JobError(f"iş #{job_id} zaten bitti ({job_row.status})"))
            if job_row.status == "running":
                c.err.print(
                    f"[yellow]Uyarı:[/] iş #{job_id} 'çalışıyor' görünüyor; başka bir süreçte "
                    "çalışmıyorsa (ör. çökme sonrası) devam ediliyor."
                )
            only = job_row.remaining
        path = _book_path(repos, job_row)
    if not only:
        c.console.print(_summary(job_row))
        c.console.print("Yapılacak sayfa yok.")
        return
    try:
        with c._session(path, c.format_pages(only), job_row.provider, job_row.model) as s:
            book_profile = c._resolve_profile(book_profile, s)
            runner = JobRunner(s.service, s.repos)
            fresh = runner.get(job_id)
            _execute(s, runner, fresh, book_profile, yes=yes, only=only, continuing=True)
    except (ExtractionError, JobError) as e:
        raise _fail(e) from e


def _book_path(repos: Repos, job: JobRow) -> Path:
    row = repos.conn.execute("SELECT file_path FROM books WHERE id = ?", (job.book_id,)).fetchone()
    if row is None or not row[0] or not Path(row[0]).is_file():
        raise _fail(
            JobError(
                f"iş #{job.id}: kitabın PDF dosyası bulunamadı "
                f"({row[0] if row is not None else '?'}); aynı PDF ile 'rosetta extract' "
                "çalıştırıp yolu güncelleyin"
            )
        )
    return Path(row[0])


@job_app.command("resume")
def resume(job_id: JobId, yes: YesOpt = False, profile: ProfileOpt = None) -> None:
    """Kalan sayfalara devam et (kalanlar yeniden tahmin edilir, onay sorulur)."""
    _continue(job_id, yes, profile, retry=False)


@job_app.command("retry-failed")
def retry_failed(job_id: JobId, yes: YesOpt = False, profile: ProfileOpt = None) -> None:
    """Sadece hatalı sayfaları tekrar dene."""
    _continue(job_id, yes, profile, retry=True)


@job_app.command("list")
def list_jobs(
    book: Annotated[Path | None, typer.Option("--book", exists=True, dir_okay=False)] = None,
) -> None:
    """İşleri listele."""
    c = _cli()
    with _repos() as repos:
        book_id: int | None = None
        if book is not None:
            found = repos.books.get_by_hash(c.file_hash(book))
            if found is None:
                c.console.print("Bu kitap için kayıt yok.")
                return
            book_id = found.id
        jobs = repos.jobs.list_jobs(book_id)
        if not jobs:
            c.console.print("İş yok.")
            return
        titles = {r["id"]: r["title"] for r in repos.conn.execute("SELECT id, title FROM books")}
        table = Table("#", "kitap", "sayfalar", "durum", "bitti", "hatalı", "harcanan", "bütçe")
        for j in jobs:
            table.add_row(
                str(j.id),
                str(titles.get(j.book_id, j.book_id))[:30],
                j.page_spec,
                _STATUS_TR.get(j.status, j.status),
                f"{len(j.done_pages)}/{len(j.pages)}",
                str(len(j.failed)),
                f"${j.spent_usd:.3f}",
                "-" if j.budget_usd is None else f"${j.budget_usd:.2f}",
            )
        c.console.print(table)


@job_app.command("status")
def status(job_id: JobId) -> None:
    """İşin ayrıntıları ve hatalı sayfalar."""
    c = _cli()
    with _repos() as repos:
        job = repos.jobs.get(job_id)
        if job is None:
            raise _fail(JobError(f"iş bulunamadı: #{job_id}"))
    c.console.print(_summary(job))
    c.console.print(f"Sayfalar: {job.page_spec}  dil: {job.lang}  {job.provider}/{job.model}")
    if job.stop_reason:
        c.console.print(f"Son durma nedeni: {job.stop_reason}")
    if job.remaining:
        c.console.print(f"Kalan: {c.format_pages(job.remaining)}")
    for p, reason in sorted(job.failed.items()):
        c.console.print(f"  [red]sayfa {p + 1}[/]: {reason}")


@job_app.command("pause")
def pause(job_id: JobId) -> None:
    """Çalışan işi bir sonraki batch'ten önce duraklat."""
    c = _cli()
    with _repos() as repos:
        try:
            job = JobRunner(None, repos).request_pause(job_id)
        except JobError as e:
            raise _fail(e) from e
    c.console.print(f"Duraklatma istendi. {_summary(job)}")


@job_app.command("cancel")
def cancel(job_id: JobId) -> None:
    """İşi iptal et (çevrilen sayfalar cache'te kalır)."""
    c = _cli()
    with _repos() as repos:
        try:
            job = JobRunner(None, repos).cancel(job_id)
        except JobError as e:
            raise _fail(e) from e
    c.console.print(_summary(job))


def register(app: typer.Typer) -> None:
    app.add_typer(job_app, name="job")

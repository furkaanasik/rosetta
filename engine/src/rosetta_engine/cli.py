"""Typer CLI: extract, estimate, translate, usage. The only module that prints to the user."""

from __future__ import annotations

import logging
import re
import shutil
import sys
import webbrowser
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import pymupdf
import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn
from rich.table import Table

from rosetta_engine import config
from rosetta_engine.errors import (
    ConfigError,
    ExtractionError,
    ProviderUnavailableError,
    RosettaError,
)
from rosetta_engine.extract.extractor import BookMeta
from rosetta_engine.extract.pdf_reader import file_hash
from rosetta_engine.models import BlockType, Book, BookProfile, TranslationPlan
from rosetta_engine.render.html_builder import write_index, write_page
from rosetta_engine.store.db import connect, migrate
from rosetta_engine.store.repo import Repos
from rosetta_engine.translate.base import Translator
from rosetta_engine.translate.claude_cli import CLAUDE_BIN
from rosetta_engine.translate.providers import (
    UnknownProviderError,
    make_translator,
    supports_profile,
)
from rosetta_engine.translate.service import PageTranslationService

EXIT_OK = 0
EXIT_CANCELLED = 2
EXIT_PARTIAL = 3
EXIT_USAGE_LIMIT = 4
EXIT_AUTH = 5
EXIT_BUDGET = 6
EXIT_UNAVAILABLE = 7

_TYPE_LABELS = {
    BlockType.HEADING: "başlık",
    BlockType.PARAGRAPH: "parag",
    BlockType.LIST_ITEM: "liste",
    BlockType.CODE: "kod",
    BlockType.IMAGE: "görsel",
    BlockType.TABLE: "tablo",
    BlockType.CAPTION: "alt yazı",
    BlockType.FOOTNOTE: "dipnot",
    BlockType.FURNITURE: "h/f",
}
_PAGE_FILE = re.compile(r"^p(\d{3,})\.(tr|review|learn|debug)\.html$")

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Rosetta PDF translation engine")
console = Console()
err = Console(stderr=True)

PdfArg = Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="PDF")]
PagesOpt = Annotated[str, typer.Option("--pages", "-p", help="1-based: 41 | 41-44 | 41,43,50-52")]
LangOpt = Annotated[str | None, typer.Option("--lang", help="Target language (default: config)")]
ProviderOpt = Annotated[
    str | None, typer.Option("--provider", help="claude-cli | fake | deepl | ollama")
]
ModelOpt = Annotated[str | None, typer.Option("--model", help="Model (default: config)")]


class Think(StrEnum):
    OFF = "off"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


ThinkOpt = Annotated[
    Think | None,
    typer.Option(
        "--think",
        case_sensitive=False,
        help="claude-cli thinking: off (fast draft) | low | medium (default) | high",
    ),
]
BudgetOpt = Annotated[
    float | None,
    typer.Option("--max-budget-usd", min=0.0, help="claude-cli: per-call cap (≈ list-price $)"),
]


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


def parse_pages(spec: str, page_count: int) -> list[int]:
    """Parse a 1-based page spec into sorted, unique 0-based page numbers."""
    pages: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if m is None:
            raise typer.BadParameter(f"invalid page spec: {part!r}", param_hint="--pages")
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if start < 1 or end < start:
            raise typer.BadParameter(f"invalid page range: {part!r}", param_hint="--pages")
        if end > page_count:
            raise typer.BadParameter(
                f"page {end} out of range (book has {page_count} pages)", param_hint="--pages"
            )
        pages.update(range(start - 1, end))
    if not pages:
        raise typer.BadParameter("no pages given", param_hint="--pages")
    return sorted(pages)


def format_pages(pages: list[int]) -> str:
    """0-based list → compact 1-based ranges: [40, 41, 42, 49] → '41-43,50'."""
    out: list[str] = []
    start = prev = pages[0]
    for p in [*pages[1:], None]:
        if p is not None and p == prev + 1:
            prev = p
            continue
        out.append(f"{start + 1}" if start == prev else f"{start + 1}-{prev + 1}")
        if p is not None:
            start = prev = p
    return ",".join(out)


def _translator(provider: str, model: str | None, settings: config.Settings) -> Translator:
    if provider == "claude-cli" and shutil.which(CLAUDE_BIN) is None:
        raise _fail(
            ProviderUnavailableError("claude CLI bulunamadı; Claude Code kurulu ve PATH'te mi?")
        )
    try:
        return make_translator(provider, model, settings)
    except UnknownProviderError as e:
        raise typer.BadParameter(str(e), param_hint="--provider") from e


def apply_think(settings: config.Settings, think: Think | None) -> config.Settings:
    """Map ``--think`` onto settings; None keeps the configured thinking."""
    if think is None:
        return settings
    if think is Think.OFF:
        return settings.model_copy(update={"claude_effort": "low", "claude_max_thinking_tokens": 0})
    return settings.model_copy(
        update={"claude_effort": think.value, "claude_max_thinking_tokens": None}
    )


@dataclass
class _Session:
    service: PageTranslationService
    settings: config.Settings
    provider: str
    thinking_level: str | None
    thinking_extra: int
    book: Book
    doc: pymupdf.Document
    meta: BookMeta
    pages: list[int]
    repos: Repos


@contextmanager
def _session(
    pdf: Path,
    pages: str | None,
    provider: str | None = None,
    model: str | None = None,
    max_budget_usd: float | None = None,
    think: Think | None = None,
) -> Iterator[_Session]:
    try:
        settings = config.load_settings()
    except ConfigError as e:
        raise _fail(e) from e
    provider = provider or settings.provider
    if max_budget_usd is not None:
        if provider == "claude-cli":
            settings = settings.model_copy(update={"claude_max_budget_usd": max_budget_usd})
        else:
            console.print(f"Not: --max-budget-usd yalnızca claude-cli için; {provider} yok sayar.")
    if think is not None and provider != "claude-cli":
        console.print(f"Not: --think yalnızca claude-cli için; {provider} yok sayar.")
    level: str | None = None
    extra = 0
    if provider == "claude-cli":
        settings = apply_think(settings, think)
        level = settings.thinking_level
        extra = settings.thinking_extra_output(model or settings.model)
    translator = _translator(provider, model, settings)
    if not supports_profile(translator):
        console.print(f"Not: Bu sağlayıcı ({provider}) kitap profilini/bağlamı kullanmaz.")
    conn = connect(config.db_path())
    try:
        migrate(conn)
        repos = Repos.from_conn(conn)
        service = PageTranslationService(
            translator, repos, settings, thinking_output_per_call=extra
        )
        book, doc, meta = service.open_book(pdf)
        try:
            page_list = parse_pages(pages or f"1-{book.page_count}", book.page_count)
            console.print(
                f"Kitap: [bold]{book.title}[/] (hash {book.file_hash[:4]}…)  "
                f"sayfa {format_pages(page_list)}"
            )
            yield _Session(
                service, settings, provider, level, extra, book, doc, meta, page_list, repos
            )
        finally:
            doc.close()  # type: ignore[no-untyped-call]
    finally:
        conn.close()


def _resolve_profile(explicit: BookProfile | None, s: _Session) -> BookProfile | None:
    """``--profile`` wins; otherwise the book's stored profile (Faz 2), if any."""
    if explicit is not None:
        console.print(f"Profil: dosya ({len(explicit.glossary)} terim)")
        return explicit
    stored = s.repos.profiles.get(s.book.id)
    if stored is None:
        console.print("Profil: yok")
        return None
    console.print(f"Profil: DB ({len(stored.glossary)} terim)")
    return stored


def _load_profile(path: Path | None) -> BookProfile | None:
    if path is None:
        return None
    try:
        return BookProfile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise typer.BadParameter(f"cannot read profile: {e}", param_hint="--profile") from e


def _num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def _print_plan(plan: TranslationPlan, s: _Session) -> None:
    e = plan.estimate
    if plan.no_text_pages:
        console.print(
            "[yellow]Metin katmanı yok, atlanıyor:[/] sayfa "
            + format_pages(plan.no_text_pages)
            + " (taranmış sayfa; OCR desteklenmiyor)"
        )
    console.print(f"Cache: {plan.cached_blocks}/{plan.total_blocks} block hazır")
    console.print(f"Tahmin ({s.provider} / {plan.model}):")
    thinking = ""
    if s.thinking_level is not None:
        thinking = (
            f"   (düşünme: {s.thinking_level}, değişken: çağrı başı +~{_num(s.thinking_extra)} tok,"
            " gerçek ±%40 olabilir)"
        )
    if s.provider == "claude-cli" and not e.price_known:
        section = escape(f"[pricing.{plan.model}]")
        cost = f"[yellow]fiyat bilinmiyor — config.toml {section} ekleyin[/]"
    else:
        cost = f"≈ ${e.usd:.3f} (liste fiyatı eşdeğeri)"
    console.print(
        f"  çağrı: {e.calls}   input ≈ {_num(e.input_tokens)} tok   "
        f"output ≈ {_num(e.output_tokens)} tok   {cost}" + thinking,
        highlight=False,
    )


def _write_index(book: Book, out_dir: Path) -> Path:
    modes: dict[int, list[str]] = {}
    for f in sorted(out_dir.glob("p*.html")):
        m = _PAGE_FILE.match(f.name)
        if m:
            modes.setdefault(int(m.group(1)) - 1, []).append(m.group(2))
    return write_index(book, out_dir, sorted(modes.items()))


def _fail(e: RosettaError) -> typer.Exit:
    err.print(f"[red]Hata:[/] {e}")
    return typer.Exit(1)


@app.callback()
def _main(
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging")] = False,
) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command()
def extract(
    pdf: PdfArg,
    pages: PagesOpt,
    debug: Annotated[bool, typer.Option("--debug", help="Write pNNN.debug.html")] = False,
) -> None:
    """Extract blocks into the DB (no AI call)."""
    try:
        with _session(pdf, pages, provider="fake") as s:
            extracted = s.service.ensure_pages(s.book, s.doc, s.meta, s.pages)
            table = Table("sayfa", "block", *_TYPE_LABELS.values(), "devam")
            out_dir = config.output_dir(s.book.file_hash)
            for p, page in sorted(extracted.items()):
                counts = Counter(b.type for b in page.blocks)
                table.add_row(
                    str(p + 1),
                    str(len(page.blocks)),
                    *[str(counts.get(t, "")) for t in _TYPE_LABELS],
                    "→" if page.continues_on_next_page else "",
                )
                if debug:
                    write_page(s.book, page, {}, "debug", out_dir, doc=s.doc, lang="en")
            console.print(table)
            if debug:
                index = _write_index(s.book, out_dir)
                console.print(f"Debug çıktısı: {out_dir} ({index.name})")
    except ExtractionError as e:
        raise _fail(e) from e


@app.command()
def estimate(
    pdf: PdfArg,
    pages: PagesOpt,
    lang: LangOpt = None,
    provider: ProviderOpt = None,
    model: ModelOpt = None,
    max_budget_usd: BudgetOpt = None,
    think: ThinkOpt = None,
    force: Annotated[
        bool, typer.Option("--force", help="Count cached blocks as if re-translating")
    ] = False,
    profile: Annotated[
        Path | None, typer.Option("--profile", exists=True, dir_okay=False, help="profile.json")
    ] = None,
) -> None:
    """Plan + cost estimate (no AI call). Never deletes cached translations."""
    book_profile = _load_profile(profile)
    try:
        with _session(pdf, pages, provider, model, max_budget_usd, think) as s:
            book_profile = _resolve_profile(book_profile, s)
            plan = s.service.plan(
                s.book,
                s.doc,
                s.meta,
                s.pages,
                lang or s.settings.default_lang,
                profile=book_profile,
                force=force,
            )
            _print_plan(plan, s)
    except ExtractionError as e:
        raise _fail(e) from e


@app.command()
def translate(
    pdf: PdfArg,
    pages: PagesOpt,
    lang: LangOpt = None,
    provider: ProviderOpt = None,
    model: ModelOpt = None,
    profile: Annotated[
        Path | None, typer.Option("--profile", exists=True, dir_okay=False, help="profile.json")
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
    force: Annotated[bool, typer.Option("--force", help="Re-translate cached pages")] = False,
    open_: Annotated[bool, typer.Option("--open", help="Open index.html when done")] = False,
    max_budget_usd: BudgetOpt = None,
    think: ThinkOpt = None,
) -> None:
    """Plan → estimate → confirm → translate → HTML."""
    book_profile = _load_profile(profile)
    try:
        with _session(pdf, pages, provider, model, max_budget_usd, think) as s:
            book_profile = _resolve_profile(book_profile, s)
            target = lang or s.settings.default_lang
            plan = s.service.plan(
                s.book, s.doc, s.meta, s.pages, target, profile=book_profile, force=force
            )
            _print_plan(plan, s)

            if plan.batches:
                if not yes:
                    if not _stdin_is_tty():
                        err.print("stdin bir terminal değil; onay için --yes kullan.")
                        raise typer.Exit(EXIT_CANCELLED)
                    if not typer.confirm("Onaylıyor musun?", default=False):
                        console.print("İptal edildi; AI çağrısı yapılmadı.")
                        raise typer.Exit(EXIT_CANCELLED)
                with Progress(
                    TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(),
                    console=console, transient=True,
                ) as bar:  # fmt: skip
                    task = bar.add_task("çeviri", total=len(plan.batches))
                    report = s.service.execute(
                        plan,
                        profile=book_profile,
                        on_progress=lambda n, total: bar.update(task, completed=n, total=total),
                    )
            else:
                console.print("0 çağrı — tümü cache'te.")
                report = s.service.execute(plan, profile=book_profile)

            u = report.usage
            console.print(
                f"Gerçek: {u.calls} çağrı, in {_num(u.input_tokens)} / "
                f"out {_num(u.output_tokens)} tok, ${u.cost_usd:.3f}"
            )

            out_dir = config.output_dir(s.book.file_hash)
            for p in s.pages:
                page, translations = s.service.page_view(s.book, p, target)
                for mode in ("tr", "review"):
                    write_page(s.book, page, translations, mode, out_dir, doc=s.doc, lang=target)
            index = _write_index(s.book, out_dir)
            console.print(f"Çıktı: {out_dir}")

            for p, reason in sorted(report.failed_pages.items()):
                err.print(f"[red]Sayfa {p + 1} başarısız:[/] {reason}")
            if open_:
                webbrowser.open(index.as_uri())

            if report.stop_kind == "usage_limit":
                err.print(f"[yellow]Kullanım limiti — durdu:[/] {report.stopped_reason}")
                raise typer.Exit(EXIT_USAGE_LIMIT)
            if report.stop_kind == "budget":
                err.print(f"[yellow]Bütçe sınırı aşıldı — durdu:[/] {report.stopped_reason}")
                raise typer.Exit(EXIT_BUDGET)
            if report.stop_kind == "auth":
                err.print(f"[red]Kimlik doğrulama:[/] {report.stopped_reason}")
                raise typer.Exit(EXIT_AUTH)
            if report.stop_kind == "unavailable":
                err.print(f"[red]Sağlayıcı kullanılamıyor — durdu:[/] {report.stopped_reason}")
                raise typer.Exit(EXIT_UNAVAILABLE)
            if report.failed_pages:
                raise typer.Exit(EXIT_PARTIAL)
    except ExtractionError as e:
        raise _fail(e) from e


@app.command()
def usage(
    book: Annotated[
        Path | None, typer.Option("--book", exists=True, dir_okay=False, help="PDF")
    ] = None,
) -> None:
    """Show recorded token usage (≈ list-price equivalent $)."""
    conn = connect(config.db_path())
    try:
        migrate(conn)
        repos = Repos.from_conn(conn)
        book_id: int | None = None
        if book is not None:
            found = repos.books.get_by_hash(file_hash(book))
            if found is None:
                console.print("Bu kitap için kayıt yok.")
                return
            book_id = found.id
        t = repos.usage.total(book_id)
        console.print(
            f"çağrı: {t.calls}   input: {_num(t.input_tokens)} tok   "
            f"output: {_num(t.output_tokens)} tok   ≈ ${t.cost_usd:.4f} (liste fiyatı eşdeğeri)"
        )
    finally:
        conn.close()


from rosetta_engine.commands import register_all  # noqa: E402

register_all(app)

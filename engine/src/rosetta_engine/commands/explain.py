"""`rosetta explain "SENTENCE"`: "Bunu açıkla" — one AI call after confirmation, cached."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.markdown import Markdown
from rich.markup import escape

from rosetta_engine import config
from rosetta_engine.errors import (
    BudgetExceededError,
    ConfigError,
    ExtractionError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    UsageLimitError,
)
from rosetta_engine.explain.explainer import Explainer, normalize, render_text
from rosetta_engine.models import BlockType
from rosetta_engine.store.db import connect, migrate
from rosetta_engine.store.repo import Repos
from rosetta_engine.textsafe import strip_controls
from rosetta_engine.translate.claude_cli import CLAUDE_BIN, complete
from rosetta_engine.translate.fake import FakeTranslator
from rosetta_engine.translate.service import PageTranslationService

# Injection points for tests (never call the real CLI in tests).
_complete_fn = complete
_which = shutil.which


def _context(
    repos: Repos, settings: config.Settings, pdf: Path, page: int, sentence: str
) -> tuple[int, str | None]:
    """(book_id, paragraph containing the sentence, or the page's first paragraphs). No AI."""
    from rosetta_engine import cli

    # The service is only used for extraction here; the fake translator is never called.
    service = PageTranslationService(FakeTranslator(), repos, settings)
    try:
        book, doc, meta = service.open_book(pdf)
    except ExtractionError as e:
        raise cli._fail(e) from e
    try:
        if not 1 <= page <= book.page_count:
            raise cli._fail(ExtractionError(f"page {page} out of range (1-{book.page_count})"))
        try:
            blocks = service.ensure_pages(book, doc, meta, [page - 1])[page - 1].blocks
        except ExtractionError as e:
            raise cli._fail(e) from e
    finally:
        doc.close()  # type: ignore[no-untyped-call]
    paragraphs = [
        b.text for b in blocks if b.type is not BlockType.FURNITURE and b.translatable and b.text
    ]
    target = normalize(sentence).lower()
    for text in paragraphs:
        if target and target in normalize(text).lower():
            return book.id, text
    return book.id, "\n\n".join(paragraphs[:2]) or None


def explain(
    sentence: Annotated[str, typer.Argument(help="English sentence to explain")],
    book: Annotated[
        Path | None,
        typer.Option("--book", exists=True, dir_okay=False, readable=True, help="PDF (context)"),
    ] = None,
    page: Annotated[int | None, typer.Option("--page", help="1-based page (with --book)")] = None,
    lang: Annotated[str | None, typer.Option("--lang", help="Explanation language")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model (default: haiku)")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
) -> None:
    """Explain a sentence's grammar, idioms and vocabulary (cached; AI only after confirmation)."""
    from rosetta_engine import cli

    if (book is None) != (page is None):
        cli.err.print("--book ve --page birlikte verilmeli.")
        raise typer.Exit(cli.EXIT_CANCELLED)
    try:
        settings = config.load_settings()
    except ConfigError as ce:
        raise cli._fail(ce) from ce
    conn = connect(config.db_path())
    try:
        migrate(conn)
        book_id: int | None = None
        context: str | None = None
        if book is not None and page is not None:
            book_id, context = _context(Repos.from_conn(conn), settings, book, page, sentence)
        explainer = Explainer(conn, settings, complete_fn=_complete_fn, model=model)
        try:
            plan = explainer.plan(sentence, context=context, book_id=book_id, lang=lang)
        except ValueError as ve:
            cli.err.print(f"[red]Hata:[/] {escape(strip_controls(str(ve)))}")
            raise typer.Exit(1) from ve

        if plan.cached is not None:
            cli.console.print(f"Cache'ten (claude-cli / {plan.model}) — AI çağrısı yok.")
            cli.console.print(Markdown(strip_controls(render_text(plan.cached))))
            return

        if _which(CLAUDE_BIN) is None:
            cli.err.print("claude CLI bulunamadı; Claude Code kurulu ve PATH'te mi?")
            raise typer.Exit(1)
        e = plan.estimate
        assert e is not None
        cost = f"≈ ${e.usd:.4f} (liste fiyatı eşdeğeri)" if e.price_known else "fiyat bilinmiyor"
        cli.console.print(
            f"Tahmin (claude-cli / {plan.model}): çağrı: 1   input ≈ {cli._num(e.input_tokens)} tok"
            f"   output ≈ {cli._num(e.output_tokens)} tok   {cost}"
        )
        if not yes:
            if not cli._stdin_is_tty():
                cli.err.print("stdin bir terminal değil; onay için --yes kullan.")
                raise typer.Exit(cli.EXIT_CANCELLED)
            if not typer.confirm("Onaylıyor musun?", default=False):
                cli.console.print("İptal edildi; AI çağrısı yapılmadı.")
                raise typer.Exit(cli.EXIT_CANCELLED)
        try:
            result = explainer.run(plan)
        except UsageLimitError as ex:
            cli.err.print(f"[yellow]Kullanım limiti:[/] {escape(strip_controls(str(ex)))}")
            raise typer.Exit(cli.EXIT_USAGE_LIMIT) from ex
        except ProviderAuthError as ex:
            cli.err.print(f"[red]Kimlik doğrulama:[/] {escape(strip_controls(str(ex)))}")
            raise typer.Exit(cli.EXIT_AUTH) from ex
        except BudgetExceededError as ex:
            cli.err.print(f"[yellow]Bütçe sınırı aşıldı:[/] {escape(strip_controls(str(ex)))}")
            raise typer.Exit(cli.EXIT_BUDGET) from ex
        except ProviderUnavailableError as ex:
            cli.err.print(f"[red]Sağlayıcı kullanılamıyor:[/] {escape(strip_controls(str(ex)))}")
            raise typer.Exit(cli.EXIT_UNAVAILABLE) from ex
        except ProviderError as ex:
            cli.err.print(f"[red]Açıklama alınamadı:[/] {escape(strip_controls(str(ex)))}")
            raise typer.Exit(1) from ex
        cli.console.print(Markdown(strip_controls(render_text(result))))
    finally:
        conn.close()


def register(app: typer.Typer) -> None:
    app.command("explain")(explain)

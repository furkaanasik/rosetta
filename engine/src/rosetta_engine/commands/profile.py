"""`rosetta profile …`: analyze (button-triggered AI), show, export, import, set."""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import pymupdf
import typer
from pydantic import ValidationError
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
from rosetta_engine.extract.extractor import BookMeta
from rosetta_engine.models import Book, BookProfile
from rosetta_engine.profile.profiler import Profiler
from rosetta_engine.store.db import connect, migrate
from rosetta_engine.store.repo import Repos
from rosetta_engine.translate.claude_cli import CLAUDE_BIN, complete
from rosetta_engine.translate.fake import FakeTranslator
from rosetta_engine.translate.service import PageTranslationService

# Injection points for tests (never call the real CLI in tests).
_complete_fn = complete
_which = shutil.which

profile_app = typer.Typer(
    no_args_is_help=True, help="Book profile: glossary, do-not-translate, tone"
)

PdfArg = Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="PDF")]


@dataclass
class _Book:
    repos: Repos
    settings: config.Settings
    service: PageTranslationService
    book: Book
    doc: pymupdf.Document
    meta: BookMeta


@contextmanager
def _open(pdf: Path) -> Iterator[_Book]:
    from rosetta_engine import cli

    try:
        settings = config.load_settings()
    except ConfigError as e:
        raise cli._fail(e) from e
    conn = connect(config.db_path())
    try:
        migrate(conn)
        repos = Repos.from_conn(conn)
        # The service is only used for extraction here; the fake translator is never called.
        service = PageTranslationService(FakeTranslator(), repos, settings)
        try:
            book, doc, meta = service.open_book(pdf)
        except ExtractionError as e:
            raise cli._fail(e) from e
        try:
            yield _Book(repos, settings, service, book, doc, meta)
        finally:
            doc.close()  # type: ignore[no-untyped-call]
    finally:
        conn.close()


def _print_profile(p: BookProfile) -> None:
    from rosetta_engine.cli import console

    console.print_json(json.dumps(p.model_dump(by_alias=True), ensure_ascii=False))


def _stored(b: _Book) -> BookProfile:
    from rosetta_engine.cli import err

    stored = b.repos.profiles.get(b.book.id)
    if stored is None:
        err.print("Bu kitap için profil yok. `rosetta profile analyze` ya da `import` kullan.")
        raise typer.Exit(1)
    return stored


@profile_app.command()
def analyze(
    pdf: PdfArg,
    lang: Annotated[str | None, typer.Option("--lang", help="Target language")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Model (default: config)")] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation")] = False,
) -> None:
    """Draft the profile from the TOC + sample pages (one AI call, after confirmation)."""
    from rosetta_engine import cli

    if _which(CLAUDE_BIN) is None:
        cli.err.print("claude CLI bulunamadı; Claude Code kurulu ve PATH'te mi?")
        raise typer.Exit(1)
    with _open(pdf) as b:
        target = lang or b.settings.default_lang
        profiler = Profiler(b.repos, b.settings, complete_fn=_complete_fn, model=model)

        plan = profiler.plan(
            b.book,
            b.meta,
            lambda pages: b.service.ensure_pages(b.book, b.doc, b.meta, pages),
            target,
        )
        e = plan.estimate
        cli.console.print(
            f"Kitap: [bold]{escape(b.book.title)}[/]  içindekiler: {plan.toc_entries} girdi, "
            f"örnek sayfalar: {cli.format_pages(plan.pages) if plan.pages else '—'}"
        )
        cost = f"≈ ${e.usd:.3f} (liste fiyatı eşdeğeri)" if e.price_known else "fiyat bilinmiyor"
        cli.console.print(
            f"Tahmin (claude-cli / {plan.model}): çağrı: 1   input ≈ {cli._num(e.input_tokens)} tok"
            f"   output ≈ {cli._num(e.output_tokens)} tok   {cost}"
        )
        if b.repos.profiles.get(b.book.id) is not None:
            cli.console.print(
                "Not: mevcut profil yeni taslakla değiştirilecek (çeviri cache'i aynen kalır)."
            )
        if not yes:
            if not cli._stdin_is_tty():
                cli.err.print("stdin bir terminal değil; onay için --yes kullan.")
                raise typer.Exit(cli.EXIT_CANCELLED)
            if not typer.confirm("Onaylıyor musun?", default=False):
                cli.console.print("İptal edildi; AI çağrısı yapılmadı.")
                raise typer.Exit(cli.EXIT_CANCELLED)
        try:
            profile = profiler.run(plan)
        except UsageLimitError as ex:
            cli.err.print(f"[yellow]Kullanım limiti:[/] {escape(str(ex))}")
            raise typer.Exit(cli.EXIT_USAGE_LIMIT) from ex
        except ProviderAuthError as ex:
            cli.err.print(f"[red]Kimlik doğrulama:[/] {escape(str(ex))}")
            raise typer.Exit(cli.EXIT_AUTH) from ex
        except BudgetExceededError as ex:
            cli.err.print(f"[yellow]Bütçe sınırı aşıldı:[/] {escape(str(ex))}")
            raise typer.Exit(cli.EXIT_BUDGET) from ex
        except ProviderUnavailableError as ex:
            cli.err.print(f"[red]Sağlayıcı kullanılamıyor:[/] {escape(str(ex))}")
            raise typer.Exit(cli.EXIT_UNAVAILABLE) from ex
        except ProviderError as ex:
            cli.err.print(f"[red]Profil çıkarılamadı:[/] {escape(str(ex))}")
            raise typer.Exit(1) from ex
        cli.console.print(
            f"Profil kaydedildi: {len(profile.glossary)} terim, "
            f"{len(profile.do_not_translate)} çevrilmeyecek."
        )
        _print_profile(profile)


@profile_app.command()
def show(pdf: PdfArg) -> None:
    """Print the stored profile."""
    with _open(pdf) as b:
        _print_profile(_stored(b))


@profile_app.command("export")
def export_(
    pdf: PdfArg,
    out: Annotated[Path, typer.Argument(dir_okay=False, help="Output JSON file")],
) -> None:
    """Write the stored profile as JSON (Turkish keys)."""
    from rosetta_engine.cli import console

    with _open(pdf) as b:
        p = _stored(b)
        out.write_text(
            json.dumps(p.model_dump(by_alias=True), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        console.print(f"Yazıldı: {out}")


@profile_app.command("import")
def import_(
    pdf: PdfArg,
    src: Annotated[Path, typer.Argument(exists=True, dir_okay=False, help="Profile JSON")],
) -> None:
    """Replace the stored profile with a JSON file (validated; cache stays valid)."""
    from rosetta_engine.cli import console, err

    try:
        p = BookProfile.model_validate_json(src.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as e:
        err.print(f"[red]Geçersiz profil dosyası:[/] {e}")
        raise typer.Exit(1) from e
    with _open(pdf) as b:
        b.repos.profiles.put(b.book.id, p)
    console.print(f"Profil içe aktarıldı: {len(p.glossary)} terim.")


@profile_app.command("set")
def set_(
    pdf: PdfArg,
    term: Annotated[
        list[str] | None, typer.Option("--term", help='Glossary entry "english=çeviri"')
    ] = None,
    remove_term: Annotated[
        list[str] | None, typer.Option("--remove-term", help="Remove a glossary entry")
    ] = None,
    dnt: Annotated[
        list[str] | None, typer.Option("--dnt", help="Add a do-not-translate term")
    ] = None,
    remove_dnt: Annotated[
        list[str] | None, typer.Option("--remove-dnt", help="Remove a do-not-translate term")
    ] = None,
    genre: Annotated[str | None, typer.Option("--tur", help="Genre")] = None,
    tone: Annotated[str | None, typer.Option("--ton", help="Tone")] = None,
) -> None:
    """Edit the stored profile (creates an empty one if missing). Cache stays valid."""
    from rosetta_engine.cli import console, err

    with _open(pdf) as b:
        current = b.repos.profiles.get(b.book.id) or BookProfile(
            target_lang=b.settings.default_lang
        )
        glossary = dict(current.glossary)
        for entry in term or []:
            key, sep, value = entry.partition("=")
            if not sep or not key.strip() or not value.strip():
                err.print(f'[red]Geçersiz --term:[/] {entry!r} (biçim: "english=çeviri")')
                raise typer.Exit(1)
            glossary[key.strip()] = value.strip()
        for key in remove_term or []:
            glossary.pop(key.strip(), None)
        do_not = [t for t in current.do_not_translate if t not in set(remove_dnt or [])]
        for t in dnt or []:
            if t.strip() and t.strip() not in do_not:
                do_not.append(t.strip())
        updated = current.model_copy(
            update={
                "glossary": glossary,
                "do_not_translate": do_not,
                **({"genre": genre} if genre is not None else {}),
                **({"tone": tone} if tone is not None else {}),
            }
        )
        b.repos.profiles.put(b.book.id, updated)
    console.print(
        f"Profil güncellendi: {len(updated.glossary)} terim, "
        f"{len(updated.do_not_translate)} çevrilmeyecek."
    )


def register(app: typer.Typer) -> None:
    app.add_typer(profile_app, name="profile")

"""`rosetta consistency PDF`: term consistency of the cached translations (local, no AI)."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from rosetta_engine import config
from rosetta_engine.commands.profile import PdfArg, _open
from rosetta_engine.models import BookProfile
from rosetta_engine.quality.terms import MIN_OCC, analyze, sentence_pairs
from rosetta_engine.textsafe import strip_controls
from rosetta_engine.translate.base import Translator
from rosetta_engine.translate.fake import FakeTranslator
from rosetta_engine.translate.providers import make_translator


def _cache_owner(provider: str, model: str | None, settings: config.Settings) -> Translator:
    """Whose cached rows to analyze (only name/model are used; nothing is ever called)."""
    try:
        return make_translator(provider, model, settings)
    except Exception:  # e.g. a provider that needs credentials at construction
        return FakeTranslator(model=model or settings.model)


def consistency(
    pdf: PdfArg,
    lang: Annotated[str | None, typer.Option("--lang", help="Target language")] = None,
    provider: Annotated[str | None, typer.Option("--provider", help="Cache of provider")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Cache of model")] = None,
    min_occ: Annotated[
        int, typer.Option("--min-occ", min=1, help="Mined phrase: minimum sentences")
    ] = MIN_OCC,
    accept: Annotated[
        list[str] | None,
        typer.Option("--accept", help='Add to the glossary: "english=çeviri" (no AI)'),
    ] = None,
    ignore: Annotated[
        list[str] | None, typer.Option("--ignore", help="Ignore a term in the report")
    ] = None,
) -> None:
    """Find terms translated in different ways across the book. Local only; never calls AI.

    Re-translating affected paragraphs is up to you: ``rosetta translate --pages … --force``
    (with its cost estimate and confirmation)."""
    from rosetta_engine.cli import console, err

    with _open(pdf) as b:
        target = lang or b.settings.default_lang
        t = _cache_owner(provider or b.settings.provider, model, b.settings)
        repos, book_id = b.repos, b.book.id
        profile = repos.profiles.get(book_id) or BookProfile(target_lang=target)
        if accept:
            glossary = dict(profile.glossary)
            for entry in accept:
                key, sep, value = entry.partition("=")
                if not sep or not key.strip() or not value.strip():
                    err.print(f'[red]Geçersiz --accept:[/] {entry!r} (biçim: "english=çeviri")')
                    raise typer.Exit(1)
                key = key.strip()
                glossary = {k: v for k, v in glossary.items() if k.casefold() != key.casefold()}
                glossary[key] = value.strip()
                repos.term_ignores.remove(book_id, target, key)
            profile = profile.model_copy(update={"glossary": glossary})
            repos.profiles.put(book_id, profile)
            console.print(f"Sözlüğe eklendi: {len(accept)} terim.")
        for term in ignore or []:
            if term.strip():
                repos.term_ignores.add(book_id, target, term.strip())
        ignored = repos.term_ignores.list(book_id, target)
        rows = repos.translations.pairs_for_book(book_id, target, t.name, t.model)

    if not rows:
        console.print(f"Henüz çevrilmiş sayfa yok ({t.name}/{t.model}, {target}).")
        return
    issues = analyze(sentence_pairs(rows), profile, ignored, min_occ=min_occ)
    console.print(
        f"{len(issues)} olası tutarsızlık · {len(rows)} çevrilmiş paragraf tarandı "
        f"({t.name}/{t.model}, {target})"
    )
    if not issues:
        return
    table = Table(show_lines=False)
    table.add_column("terim")
    table.add_column("kaynak")
    table.add_column("karşılıklar")
    table.add_column("uyumsuz", justify="right")
    for i in issues:
        variants = ", ".join(f"{v.label} ×{v.count}" for v in i.variants)
        source = f"sözlük: {i.preferred}" if i.preferred is not None else "keşif"
        pages = sorted({o.page_no + 1 for o in i.affected})
        affected = f"{len(i.affected)} (s. {', '.join(map(str, pages[:8]))})" if pages else "-"
        table.add_row(*(escape(strip_controls(c)) for c in (i.term, source, variants, affected)))
    console.print(table)


def register(app: typer.Typer) -> None:
    app.command("consistency")(consistency)

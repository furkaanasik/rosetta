"""`rosetta export`: translated pages → one PDF (Turkish-only or bilingual), no AI calls."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

PdfArg = Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="PDF")]


class ModeChoice(StrEnum):
    tr = "tr"
    bilingual = "bilingual"


class PaperChoice(StrEnum):
    a4 = "a4"
    letter = "letter"


def register(app: typer.Typer) -> None:
    @app.command("export")
    def export(
        pdf: PdfArg,
        pages: Annotated[
            str | None,
            typer.Option("--pages", "-p", help="1-based (varsayılan: çevirisi olan tüm sayfalar)"),
        ] = None,
        mode: Annotated[
            ModeChoice, typer.Option("--mode", case_sensitive=False, help="tr | bilingual")
        ] = ModeChoice.tr,
        lang: Annotated[str | None, typer.Option("--lang", help="Dil (varsayılan: config)")] = None,
        provider: Annotated[
            str | None,
            typer.Option(
                "--provider", help="Hangi sağlayıcının çevirisi: claude-cli | fake | deepl | ollama"
            ),
        ] = None,
        model: Annotated[str | None, typer.Option("--model", help="Hangi modelin çevirisi")] = None,
        out: Annotated[
            Path | None, typer.Option("--out", "-o", dir_okay=False, help="Çıktı PDF yolu")
        ] = None,
        paper: Annotated[
            PaperChoice, typer.Option("--paper", case_sensitive=False, help="a4 | letter")
        ] = PaperChoice.a4,
        toc_page: Annotated[
            bool, typer.Option("--toc-page/--no-toc-page", help="Başa İçindekiler sayfası")
        ] = True,
    ) -> None:
        """Çevrilmiş sayfaları PDF olarak dışa aktar (AI çağrısı yok)."""
        # Lazy imports: rosetta_engine.cli imports this module while it is being built.
        from rosetta_engine import config
        from rosetta_engine.cli import console, err, format_pages, parse_pages
        from rosetta_engine.errors import RosettaError
        from rosetta_engine.export.exporter import ExportOptions, export_book
        from rosetta_engine.store.db import connect, migrate
        from rosetta_engine.store.repo import Repos
        from rosetta_engine.translate.fake import FakeTranslator
        from rosetta_engine.translate.providers import UnknownProviderError, make_translator
        from rosetta_engine.translate.service import PageTranslationService

        try:
            settings = config.load_settings()
            target_lang = lang or settings.default_lang
            # Same (provider, model) cache key the translation was stored under, e.g.
            # deepl → ("deepl", "deepl"), ollama → ("ollama", "ollama/<name>"). No AI call.
            try:
                keyed = make_translator(provider or settings.provider, model, settings)
            except UnknownProviderError as e:
                raise typer.BadParameter(str(e), param_hint="--provider") from e
            opts_provider, opts_model = keyed.name, keyed.model
            conn = connect(config.db_path())
            try:
                migrate(conn)
                repos = Repos.from_conn(conn)
                # The fake translator is only used for extraction (ensure_pages): no AI.
                service = PageTranslationService(FakeTranslator(), repos, settings)
                book, doc, meta = service.open_book(pdf)
                try:
                    page_list = parse_pages(pages, book.page_count) if pages else None
                    out_dir = config.output_dir(book.file_hash)
                    suffix = target_lang if mode is ModeChoice.tr else f"en-{target_lang}"
                    target = out or out_dir / f"{Path(pdf).stem}.{suffix}.pdf"
                    console.print(
                        f"Kitap: [bold]{book.title}[/]  mod: {mode.value}  "
                        f"çeviri: {opts_provider}/{opts_model} ({target_lang})"
                    )
                    result = export_book(
                        book,
                        doc,
                        meta.toc,
                        repos,
                        lambda ps: service.ensure_pages(book, doc, meta, ps),
                        ExportOptions(
                            provider=opts_provider,
                            model=opts_model,
                            lang=target_lang,
                            mode=mode.value,
                            paper=paper.value,
                            toc_page=toc_page,
                            pages=page_list,
                        ),
                        Path(target),
                        out_dir,
                    )
                finally:
                    doc.close()  # type: ignore[no-untyped-call]
            finally:
                conn.close()
        except RosettaError as e:
            err.print(f"[red]Hata:[/] {e}")
            raise typer.Exit(1) from e

        console.print(f"Sayfalar: {format_pages(result.pages)} ({len(result.pages)} sayfa)")
        if result.untranslated_blocks:
            err.print(
                f"[yellow]Uyarı:[/] {result.untranslated_blocks}/{result.total_blocks} block "
                f"çevrilmemiş ({len(result.untranslated_pages)} sayfada: "
                f"{format_pages(result.untranslated_pages)}); orijinal metinle basıldı."
            )
        console.print(f"Yer imleri: {result.bookmarks}")
        console.print(f"PDF: {result.pdf}")

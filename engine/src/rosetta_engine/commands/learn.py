"""Learning commands (Faz 6, no AI): lookup, vocab, review, terms, stats, learn-html, dict."""

from __future__ import annotations

import sqlite3
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import pymupdf
import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from rosetta_engine import config
from rosetta_engine.errors import ExtractionError
from rosetta_engine.extract.extractor import BookMeta
from rosetta_engine.extract.pdf_reader import file_hash
from rosetta_engine.learn.dictionary import (
    KAIKKI_URL,
    BuildStats,
    Dictionary,
    build,
    dictionary_path,
)
from rosetta_engine.learn.notebook import Notebook, add_terms, technical_terms
from rosetta_engine.learn.srs import Grade, ReviewService, stats
from rosetta_engine.models import Book, PageBlocks
from rosetta_engine.render.html_builder import LearnOptions, write_page
from rosetta_engine.store.db import connect, migrate
from rosetta_engine.store.learn_repo import ReviewRepo, VocabRepo
from rosetta_engine.store.repo import Repos
from rosetta_engine.translate.fake import FakeTranslator
from rosetta_engine.translate.service import PageTranslationService

console = Console()
err = Console(stderr=True)

PdfArg = Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True, help="PDF")]
BookOpt = Annotated[
    Path | None, typer.Option("--book", exists=True, dir_okay=False, help="PDF the word is from")
]

vocab_app = typer.Typer(no_args_is_help=True, help="Kelime defteri")
dict_app = typer.Typer(no_args_is_help=True, help="Offline EN→TR sözlük")


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


@dataclass
class _Learn:
    conn: sqlite3.Connection
    repos: Repos
    vocab: VocabRepo
    srs: ReviewService
    dictionary: Dictionary
    notebook: Notebook


@contextmanager
def _learn() -> Iterator[_Learn]:
    settings = config.load_settings()
    conn = connect(config.db_path())
    dictionary = Dictionary()
    try:
        migrate(conn)
        vocab = VocabRepo(conn)
        srs = ReviewService(vocab, ReviewRepo(conn), lang=settings.default_lang)
        yield _Learn(
            conn=conn,
            repos=Repos.from_conn(conn),
            vocab=vocab,
            srs=srs,
            dictionary=dictionary,
            notebook=Notebook(vocab, srs, dictionary),
        )
    finally:
        dictionary.close()
        conn.close()


@dataclass
class _OpenBook:
    service: PageTranslationService
    book: Book
    doc: pymupdf.Document
    meta: BookMeta

    def pages(self, pages: list[int]) -> dict[int, PageBlocks]:
        return self.service.ensure_pages(self.book, self.doc, self.meta, pages)


@contextmanager
def _book(lr: _Learn, pdf: Path) -> Iterator[_OpenBook]:
    """Open (and register) a book; extraction only, no provider is ever called."""
    service = PageTranslationService(FakeTranslator(), lr.repos, config.load_settings())
    book, doc, meta = service.open_book(pdf)
    try:
        yield _OpenBook(service, book, doc, meta)
    finally:
        doc.close()  # type: ignore[no-untyped-call]


def _book_id(lr: _Learn, pdf: Path | None) -> int | None:
    if pdf is None:
        return None
    found = lr.repos.books.get_by_hash(file_hash(pdf))
    if found is None:
        raise typer.BadParameter(
            "bu kitap henüz açılmamış (önce `rosetta extract`)", param_hint="--book"
        )
    return found.id


def _no_dictionary_note(lr: _Learn) -> None:
    if not lr.dictionary.available:
        err.print(f"[yellow]Sözlük yok:[/] {dictionary_path()} — `rosetta dict build` ile oluştur.")


# --- commands -------------------------------------------------------------------------------


def lookup(word: Annotated[str, typer.Argument(help="Kelime veya ifade")]) -> None:
    """Sözlükte ara (lemma ile: replicated → replicate)."""
    with _learn() as lr:
        _no_dictionary_note(lr)
        r = lr.dictionary.lookup(word)
        saved = lr.vocab.by_lemma(r.lemma)
        console.print(f"[bold]{escape(r.query)}[/] → {escape(r.lemma)}"
                      + (" · [green]defterde[/]" if saved else ""))  # fmt: skip
        if not r.found:
            console.print("Bulunamadı.")
            raise typer.Exit(1)
        if r.tr:
            console.print("TR: " + escape(", ".join(r.tr[:8])))
        for d in r.definitions[:4]:
            console.print(f"  • {escape(d)}")


@vocab_app.command("add")
def vocab_add(
    word: Annotated[str, typer.Argument(help="Kelime veya ifade")],
    book: BookOpt = None,
    page: Annotated[int | None, typer.Option("--page", min=1, help="1-based sayfa")] = None,
    sentence: Annotated[str | None, typer.Option("--sentence", help="Geçtiği cümle")] = None,
    meaning: Annotated[str | None, typer.Option("--meaning", help="Kendi karşılığın")] = None,
    unknown: Annotated[bool, typer.Option("--unknown/--known", help="Bilmiyorum işareti")] = True,
) -> None:
    """Kelimeyi bağlamıyla deftere kaydet ve kart oluştur."""
    if page is not None and book is None:
        raise typer.BadParameter("--page için --book gerekli", param_hint="--page")
    with _learn() as lr:
        _no_dictionary_note(lr)
        if book is None:
            saved = lr.notebook.save(word, sentence=sentence, meaning=meaning, unknown=unknown)
        else:
            try:
                with _book(lr, book) as ob:
                    pb = None
                    if page is not None:
                        if page > ob.book.page_count:
                            raise typer.BadParameter(
                                f"sayfa {page} kitapta yok ({ob.book.page_count})",
                                param_hint="--page",
                            )
                        pb = ob.pages([page - 1])[page - 1]
                    profile = lr.repos.profiles.get(ob.book.id)
                    saved = lr.notebook.save(
                        word, book_id=ob.book.id, page=pb, sentence=sentence, meaning=meaning,
                        unknown=unknown, glossary=profile.glossary if profile else None,
                    )  # fmt: skip
            except ExtractionError as e:
                err.print(f"[red]Hata:[/] {e}")
                raise typer.Exit(1) from e
        v = saved.vocab
        state = "eklendi" if saved.created else "zaten defterde"
        console.print(f"[bold]{escape(v.lemma)}[/] {state} — {escape(v.meaning or '-')}")
        if v.sentence:
            console.print(f"  “{escape(v.sentence)}”")


@vocab_app.command("list")
def vocab_list(
    book: BookOpt = None,
    search: Annotated[str | None, typer.Option("--search", "-s", help="Ara")] = None,
    since: Annotated[str | None, typer.Option("--since", help="YYYY-MM-DD'den beri")] = None,
) -> None:
    """Kelime defterini listele (kitaba, aramaya, tarihe göre)."""
    with _learn() as lr:
        rows = lr.vocab.query(book_id=_book_id(lr, book), search=search, since=since)
        table = Table("kelime", "lemma", "anlam", "durum", "sayfa", "eklendi")
        for v in rows:
            table.add_row(
                escape(v.word),
                escape(v.lemma),
                escape(v.meaning),
                "bilmiyorum" if v.unknown else "biliyorum",
                str(v.page_no + 1) if v.page_no is not None else "",
                v.created_at[:10],
            )
        console.print(table)
        console.print(f"{len(rows)} kelime")


@vocab_app.command("mark")
def vocab_mark(
    word: Annotated[str, typer.Argument(help="Kelime")],
    unknown: Annotated[
        bool, typer.Option("--unknown/--known", help="Bilmiyorum / biliyorum")
    ] = True,
) -> None:
    """Kelimeyi kitabın tamamında bilinmiyor/biliniyor işaretle."""
    with _learn() as lr:
        lemma = lr.dictionary.lemma_of(word)
        if not lr.notebook.mark(word, unknown):
            console.print(f"{escape(lemma)} defterde değil.")
            raise typer.Exit(1)
        console.print(f"{escape(lemma)}: {'bilmiyorum' if unknown else 'biliyorum'}")


def review(
    limit: Annotated[int, typer.Option("--limit", "-n", min=1, help="En fazla kart")] = 20,
) -> None:
    """Sırası gelen kartları çalış (Again / Hard / Good / Easy)."""
    with _learn() as lr:
        due = lr.srs.due(limit)
        if not due:
            console.print("Bugün sırası gelen kart yok.")
            return
        if not _stdin_is_tty():
            for row in due:
                card = lr.srs.flashcard(row.vocab_id)
                console.print(f"{escape(card.back_word)} — due {row.due_at[:16]}")
            console.print(f"{len(due)} kart (etkileşimli çalışma için terminalden çalıştır)")
            return
        for i, row in enumerate(due, 1):
            card = lr.srs.flashcard(row.vocab_id)
            console.rule(f"{i}/{len(due)}")
            console.print(escape(card.front))
            typer.prompt("Cevabı görmek için Enter", default="", show_default=False)
            console.print(f"[bold]{escape(card.back_word)}[/] — {escape(card.back_meaning or '-')}")
            if card.back_sentence_tr:
                console.print(f"[italic]{escape(card.back_sentence_tr)}[/]")
            while True:
                answer = typer.prompt("again / hard / good / easy (1-4)", default="good")
                try:
                    grade = Grade.parse(answer)
                    break
                except ValueError as e:
                    err.print(str(e))
            new = lr.srs.review(row.vocab_id, grade)
            console.print(f"sonraki: {new.due_at[:16]}")


def terms(
    pdf: PdfArg,
    add_all: Annotated[bool, typer.Option("--add-all", help="Hepsini deftere ekle")] = False,
) -> None:
    """Kitap profilindeki sözlükten teknik terim listesi."""
    with _learn() as lr:
        _no_dictionary_note(lr)
        found = lr.repos.books.get_by_hash(file_hash(pdf))
        profile = lr.repos.profiles.get(found.id) if found else None
        if found is None or profile is None or not profile.glossary:
            console.print("Bu kitabın profilinde sözlük yok (Faz 2: `rosetta profile …`).")
            raise typer.Exit(1)
        items = technical_terms(profile, lr.dictionary, lr.vocab)
        table = Table("terim", "kitap sözlüğü", "sözlük", "tanım", "defter")
        for t in items:
            table.add_row(
                escape(t.term),
                escape(t.glossary_tr),
                escape(", ".join(t.dictionary_tr)),
                escape(t.definition[:60]),
                "✓" if t.saved else "",
            )
        console.print(table)
        if add_all:
            saved = add_terms(lr.notebook, lr.vocab, found.id, [t for t in items if not t.saved])
            console.print(f"{sum(1 for s in saved if s.created)} terim deftere eklendi.")


def stats_cmd() -> None:
    """Toplam / öğrenilmiş kelime, bugünkü tekrar, seri."""
    with _learn() as lr:
        s = stats(lr.vocab, ReviewRepo(lr.conn))
        console.print(
            f"kelime: {s.total_words} (bilmiyorum: {s.unknown_words}) · öğrenilmiş: "
            f"{s.mature_words} · bugün sırası gelen: {s.due_today} · bugün çalışılan: "
            f"{s.reviewed_today} · seri: {s.streak_days} gün"
        )


def learn_html(
    pdf: PdfArg,
    pages: Annotated[str, typer.Option("--pages", "-p", help="1-based: 41 | 41-44 | 41,43")],
) -> None:
    """Öğrenme görünümü: orijinal metin, bilinmeyen kelimelerin üstünde Türkçe karşılık."""
    from rosetta_engine.cli import parse_pages

    with _learn() as lr:
        _no_dictionary_note(lr)
        try:
            with _book(lr, pdf) as ob:
                page_list = parse_pages(pages, ob.book.page_count)
                extracted = ob.pages(page_list)
                opts = LearnOptions(
                    unknown=lr.vocab.unknown_meanings(), lemma_of=lr.dictionary.lemma_of
                )
                out_dir = config.output_dir(ob.book.file_hash)
                for p in page_list:
                    write_page(ob.book, extracted[p], {}, "learn", out_dir, doc=ob.doc, learn=opts)
        except ExtractionError as e:
            err.print(f"[red]Hata:[/] {e}")
            raise typer.Exit(1) from e
        console.print(f"Öğrenme sayfaları: {out_dir} (pNNN.learn.html)")


@dict_app.command("build")
def dict_build(
    source: Annotated[
        str, typer.Option("--source", help="URL veya yerel .jsonl(.gz)")
    ] = KAIKKI_URL,
) -> None:
    """Sözlüğü Wiktionary (kaikki.org) verisinden indirip kur (~520 MB akış, ~3 dk)."""
    started = time.monotonic()

    def progress(s: BuildStats) -> None:
        console.print(f"{s.lines:>9} satır · {s.entries} madde · {s.translations} TR", end="\r")

    stats_ = build(source=source, progress=progress)
    took = time.monotonic() - started
    size = dictionary_path().stat().st_size / 1e6
    console.print(
        f"Sözlük hazır: {stats_.entries} madde, {stats_.translations} TR karşılık, "
        f"{size:.0f} MB, {took:.0f} sn → {dictionary_path()}"
    )


@dict_app.command("info")
def dict_info() -> None:
    """Sözlük kaynağı, lisansı ve boyutu."""
    with Dictionary() as d:
        if not d.available:
            console.print(f"Sözlük yok: {d.path}")
            raise typer.Exit(1)
        for k, v in sorted(d.meta().items()):
            console.print(f"{k}: {escape(v)}")


def register(app: typer.Typer) -> None:
    app.command("lookup")(lookup)
    app.add_typer(vocab_app, name="vocab")
    app.command("review")(review)
    app.command("terms")(terms)
    app.command("stats")(stats_cmd)
    app.command("learn-html")(learn_html)
    app.add_typer(dict_app, name="dict")

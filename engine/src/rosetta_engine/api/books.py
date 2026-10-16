"""Books, pages, HTML fragments, assets, usage and PDF export (no AI)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from rosetta_engine import __version__, config
from rosetta_engine.api.deps import Engine
from rosetta_engine.api.errors import ApiError, bad_request, not_found
from rosetta_engine.api.schemas import ExportBody, OpenBookBody, book_info
from rosetta_engine.errors import ExtractionError
from rosetta_engine.export.chromium import ExportError, find_chromium
from rosetta_engine.export.exporter import (
    ExportOptions,
    check_output_path,
    prepare_export,
    print_export,
)
from rosetta_engine.learn.dictionary import Dictionary
from rosetta_engine.render.html_builder import LearnOptions, build_page_html
from rosetta_engine.store.learn_repo import VocabRepo

router = APIRouter(prefix="/api")

_MAIN = re.compile(r"<main\b.*?</main>", re.DOTALL)
_SCRIPT = re.compile(r"<script\b.*?</script>", re.DOTALL | re.IGNORECASE)
_ASSET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.(png|jpe?g|svg)$")


def fragment(document: str) -> str:
    """The ``<main>`` element of a rendered page, without any script."""
    m = _MAIN.search(document)
    return _SCRIPT.sub("", m.group(0) if m else "")


@router.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "version": __version__}


@router.post("/books/open")
def open_book(body: OpenBookBody, eng: Engine) -> dict[str, Any]:
    path = Path(body.path).expanduser()
    with eng.db() as s:
        try:
            ob = eng.open_book(s, path)
        except ExtractionError as e:
            raise bad_request(f"PDF açılamadı: {e}") from e
        return book_info(ob.book, str(ob.path))


@router.get("/books/{book_id}")
def get_book(book_id: int, eng: Engine) -> dict[str, Any]:
    with eng.db() as s:
        ob = eng.book(s, book_id)
        return book_info(ob.book, str(ob.path))


@router.get("/books/{book_id}/toc")
def toc(book_id: int, eng: Engine) -> list[dict[str, Any]]:
    with eng.db() as s:
        ob = eng.book(s, book_id)
        return [{"level": e.level, "title": e.title, "page": e.page} for e in ob.meta.toc]


@router.get("/books/{book_id}/pages/{page}/blocks")
def page_blocks(book_id: int, page: int, eng: Engine) -> dict[str, Any]:
    with eng.db() as s:
        ob = eng.book(s, book_id)
        (p,) = eng.check_pages(ob, [page])
        try:
            pb = eng.pages(s, ob, [p])[p]
        except ExtractionError:
            with ob.lock:
                rect = ob.doc[p].rect
            return {
                "page": page,
                "width": rect.width,
                "height": rect.height,
                "has_text_layer": False,
                "blocks": [],
            }
        t = eng.default_translator()
        done = s.repos.translations.for_page(book_id, p, eng.settings.default_lang, t.name, t.model)
        return {
            "page": page,
            "width": pb.width,
            "height": pb.height,
            "has_text_layer": pb.has_text_layer,
            "blocks": [
                {
                    "key": f"{b.page_no}-{b.order}",
                    "order": b.order,
                    "type": b.type.value,
                    "bbox": list(b.bbox),
                    "translatable": b.translatable and bool(b.text.strip()),
                    "translated": b.text_hash in done,
                }
                for b in sorted(pb.blocks, key=lambda b: b.order)
            ],
        }


@router.get("/books/{book_id}/pages/{page}/html")
def page_html(
    book_id: int,
    page: int,
    eng: Engine,
    mode: Literal["tr", "review", "learn"] = "tr",
    lang: str | None = None,
) -> dict[str, Any]:
    target = lang or eng.settings.default_lang
    with eng.db() as s:
        ob = eng.book(s, book_id)
        (p,) = eng.check_pages(ob, [page])
        pb = eng.pages(s, ob, [p])[p]
        t = eng.default_translator()
        translations = s.repos.translations.for_page(book_id, p, target, t.name, t.model)
        learn: LearnOptions | None = None
        dictionary = Dictionary()
        try:
            if mode == "learn":
                learn = LearnOptions(
                    unknown=VocabRepo(s.conn).unknown_meanings(), lemma_of=dictionary.lemma_of
                )
            with ob.lock:
                document = build_page_html(
                    ob.book,
                    pb,
                    translations,
                    mode,
                    config.output_dir(ob.book.file_hash),
                    doc=ob.doc,
                    lang=target,
                    learn=learn,
                )
        finally:
            dictionary.close()
        todo = [b for b in pb.blocks if b.translatable and b.text.strip()]
        return {
            "page": page,
            "mode": mode,
            "html": fragment(document),
            "translated_blocks": sum(1 for b in todo if b.text_hash in translations),
            "translatable_blocks": len(todo),
        }


@router.get("/books/{book_id}/assets/{name:path}")
def asset(book_id: int, name: str, eng: Engine) -> FileResponse:
    name = name.removeprefix("assets/")
    if not _ASSET.match(name):
        raise not_found("Dosya bulunamadı")
    with eng.db() as s:
        stored = s.repos.books.get(book_id)
    if stored is None:
        raise not_found(f"Kitap bulunamadı: #{book_id}")
    base = (config.output_dir(stored.file_hash) / "assets").resolve()
    target = (base / name).resolve()
    if target.parent != base or not target.is_file():
        raise not_found("Dosya bulunamadı")
    return FileResponse(target)


@router.get("/books/{book_id}/file")
def book_file(book_id: int, eng: Engine) -> FileResponse:
    """The opened PDF itself (Bearer only), for PDF.js when the app runs in a plain browser."""
    with eng.db() as s:
        stored = s.repos.books.get(book_id)
    if stored is None or not stored.file_path:
        raise not_found(f"Kitap bulunamadı: #{book_id}")
    path = Path(stored.file_path)
    if not path.is_file():
        raise not_found("Kitap dosyası artık yok")
    return FileResponse(path, media_type="application/pdf")


@router.get("/usage")
def usage(eng: Engine, book_id: int | None = Query(default=None)) -> dict[str, Any]:
    with eng.db() as s:
        return s.repos.usage.total(book_id).model_dump()


def _safe_title(title: str) -> str:
    cleaned = re.sub(r"[^\w .,()-]+", "_", title).strip(" ._")
    return cleaned[:120] or "kitap"


@router.post("/books/{book_id}/export")
def export(book_id: int, body: ExportBody, eng: Engine) -> dict[str, Any]:
    try:
        find_chromium()
    except ExportError as e:
        raise ApiError("unavailable", str(e)) from e
    lang = body.lang or eng.settings.default_lang
    t = eng.default_translator()
    with eng.db() as s:
        ob = eng.book(s, book_id)
        pages = eng.check_pages(ob, body.pages) if body.pages else None
        out_dir = config.output_dir(ob.book.file_hash)
        out = (
            Path(body.out_path).expanduser()
            if body.out_path
            else out_dir / f"{_safe_title(ob.book.title)}.{body.mode}.pdf"
        )
        try:
            check_output_path(out, ob.book, s.repos)
        except ExportError as e:
            raise bad_request(str(e)) from e
        opts = ExportOptions(
            provider=t.name, model=t.model, lang=lang, mode=body.mode, paper=body.paper, pages=pages
        )
        with ob.lock:  # only the document work; printing happens outside the lock
            prepared = prepare_export(
                ob.book,
                ob.doc,
                ob.meta.toc,
                s.repos,
                lambda ps: eng.extraction_service(s).ensure_pages(ob.book, ob.doc, ob.meta, ps),
                opts,
                out_dir,
            )
        result = print_export(prepared, out)
        return {
            "path": str(result.pdf),
            "pages": len(result.pages),
            "untranslated_blocks": result.untranslated_blocks,
        }

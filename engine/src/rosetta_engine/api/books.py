"""Books, pages, HTML fragments, assets, usage and PDF export (no AI)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import pymupdf
from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from rosetta_engine import __version__, config
from rosetta_engine.api.deps import Engine
from rosetta_engine.api.errors import ApiError, bad_request, not_found
from rosetta_engine.api.schemas import (
    ExportBody,
    OpenBookBody,
    ProgressBody,
    book_info,
    library_item,
)
from rosetta_engine.api.state import EngineState, OpenBook, Session
from rosetta_engine.errors import ExtractionError
from rosetta_engine.export.chromium import ExportError, find_chromium
from rosetta_engine.export.exporter import (
    ExportOptions,
    check_output_path,
    prepare_export,
    print_export,
)
from rosetta_engine.learn.dictionary import Dictionary
from rosetta_engine.models import BlockType, PageBlocks
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
        s.repos.books.touch_opened(ob.book.id)
        return book_info(ob.book, str(ob.path))


@router.get("/books")
def library(eng: Engine, lang: str | None = None) -> list[dict[str, Any]]:
    """Library screen: known books, most recently opened first. Never opens a PDF."""
    target = lang or eng.settings.default_lang
    t = eng.default_translator()
    with eng.db() as s:
        return [
            library_item(row, s.repos.page_status.done_count(row.book.id, target, t.name, t.model))
            for row in s.repos.books.library()
        ]


@router.put("/books/{book_id}/progress")
def progress(book_id: int, body: ProgressBody, eng: Engine) -> dict[str, Any]:
    """Remember the reader's page (1-based). No AI, no PDF access."""
    with eng.db() as s:
        stored = s.repos.books.get(book_id)
        if stored is None:
            raise not_found(f"Kitap bulunamadı: #{book_id}")
        if not 1 <= body.page <= stored.page_count:
            raise bad_request(f"Sayfa aralık dışında: {body.page} (1-{stored.page_count})")
        row = s.repos.books.set_progress(book_id, body.page - 1)
        assert row is not None
        return {
            "book_id": book_id,
            "last_page": body.page,
            "last_opened_at": row.last_opened_at,
        }


COVER_MIN_W, COVER_MAX_W = 64, 1024


def _cover_page(doc: Any) -> int:
    """Page 1, unless it is blank; then the first of the next few with text or images."""
    for i in range(min(len(doc), 4)):
        page = doc[i]
        if page.get_images() or page.get_text("text").strip():
            return i
    return 0


@router.get("/books/{book_id}/cover")
def cover(
    book_id: int,
    eng: Engine,
    w: int = Query(default=240, ge=COVER_MIN_W, le=COVER_MAX_W),
) -> FileResponse:
    """PNG thumbnail of the cover (Bearer only), cached per width in the book's out dir."""
    with eng.db() as s:
        stored = s.repos.books.get(book_id)
        if stored is None:
            raise not_found(f"Kitap bulunamadı: #{book_id}")
        target = config.output_dir(stored.file_hash) / f"cover_w{w}.png"
        if target.is_file():
            return FileResponse(target, media_type="image/png")
        ob = eng.book(s, book_id)
        with ob.lock:
            d: Any = ob.doc
            page = d[_cover_page(d)]
            zoom = w / max(page.rect.width, 1.0)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)  # type: ignore[no-untyped-call]
            tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
            try:
                pix.save(str(tmp), output="png")
                os.replace(tmp, target)
            finally:
                tmp.unlink(missing_ok=True)
    return FileResponse(target, media_type="image/png")


@router.get("/books/{book_id}/pages")
def pages_overview(book_id: int, eng: Engine, lang: str | None = None) -> list[dict[str, Any]]:
    """Every page's size and status for the virtual reader list. Never extracts:
    ``has_text_layer`` comes from the DB for extracted pages, else from whether the page uses
    any font; ``translatable_blocks`` is null until the page is extracted."""
    target = lang or eng.settings.default_lang
    t = eng.default_translator()
    with eng.db() as s:
        ob = eng.book(s, book_id)
        with ob.lock:
            geometry = ob.page_geometry()
        overview = s.repos.blocks.overview(book_id)
        done = s.repos.page_status.done_pages(book_id, target, t.name, t.model)
    out: list[dict[str, Any]] = []
    for i, (width, height, has_fonts) in enumerate(geometry):
        known = overview.get(i)
        out.append(
            {
                "page": i + 1,
                "width": round(width, 2),
                "height": round(height, 2),
                "has_text_layer": known[0] if known else has_fonts,
                "translatable_blocks": known[1] if known else None,
                "translated": i in done,
            }
        )
    return out


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


def content_box(pb: PageBlocks) -> list[float] | None:
    """Union of the page's body blocks (furniture excluded) as ``[x0, y0, x1, y1]`` pt, the
    same shape as block ``bbox`` — the sheet's inner margins. None for an empty page."""
    boxes = [b.bbox for b in pb.blocks if b.type is not BlockType.FURNITURE]
    if not boxes:
        return None
    return [
        round(min(b[0] for b in boxes), 2),
        round(min(b[1] for b in boxes), 2),
        round(max(b[2] for b in boxes), 2),
        round(max(b[3] for b in boxes), 2),
    ]


HtmlMode = Literal["tr", "review", "learn"]
MAX_BATCH_PAGES = 10


def _render_pages(
    eng: EngineState, s: Session, ob: OpenBook, pages: list[int], mode: HtmlMode, target: str
) -> list[dict[str, Any]]:
    """0-based pages → HTML fragment payloads (one dictionary open for the whole batch)."""
    extracted = eng.pages(s, ob, pages)
    t = eng.default_translator()
    dictionary = Dictionary()
    try:
        learn: LearnOptions | None = None
        if mode == "learn":
            learn = LearnOptions(
                unknown=VocabRepo(s.conn).unknown_meanings(), lemma_of=dictionary.lemma_of
            )
        out: list[dict[str, Any]] = []
        for p in pages:
            pb = extracted[p]
            translations = s.repos.translations.for_page(ob.book.id, p, target, t.name, t.model)
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
            todo = [b for b in pb.blocks if b.translatable and b.text.strip()]
            out.append(
                {
                    "page": p + 1,
                    "mode": mode,
                    "html": fragment(document),
                    "translated_blocks": sum(1 for b in todo if b.text_hash in translations),
                    "translatable_blocks": len(todo),
                    "width": round(pb.width, 2),
                    "height": round(pb.height, 2),
                    "has_text_layer": pb.has_text_layer,
                    "content_box": content_box(pb),
                }
            )
        return out
    finally:
        dictionary.close()


@router.get("/books/{book_id}/pages/{page}/html")
def page_html(
    book_id: int,
    page: int,
    eng: Engine,
    mode: HtmlMode = "tr",
    lang: str | None = None,
) -> dict[str, Any]:
    target = lang or eng.settings.default_lang
    with eng.db() as s:
        ob = eng.book(s, book_id)
        (p,) = eng.check_pages(ob, [page])
        return _render_pages(eng, s, ob, [p], mode, target)[0]


def parse_page_spec(spec: str) -> list[int]:
    """``"59-61"``, ``"59,60"`` or ``"59"`` → sorted unique 1-based pages (≤ MAX_BATCH_PAGES)."""
    pages: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if m is None:
            raise bad_request(f"Geçersiz sayfa listesi: {spec!r}")
        start = int(m.group(1))
        end = int(m.group(2) or start)
        if end < start or end - start >= MAX_BATCH_PAGES:
            raise bad_request(
                f"Geçersiz ya da çok uzun aralık: {part!r} (en çok {MAX_BATCH_PAGES})"
            )
        pages.update(range(start, end + 1))
    if len(pages) > MAX_BATCH_PAGES:
        raise bad_request(f"Tek istekte en çok {MAX_BATCH_PAGES} sayfa")
    return sorted(pages)


@router.get("/books/{book_id}/html")
def pages_html(
    book_id: int,
    eng: Engine,
    pages: str = Query(min_length=1),
    mode: HtmlMode = "tr",
    lang: str | None = None,
) -> dict[str, Any]:
    """Batch of page fragments (same items as the single-page endpoint), for scrolling."""
    target = lang or eng.settings.default_lang
    wanted = parse_page_spec(pages)
    with eng.db() as s:
        ob = eng.book(s, book_id)
        zero_based = eng.check_pages(ob, wanted)
        return {"pages": _render_pages(eng, s, ob, zero_based, mode, target)}


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

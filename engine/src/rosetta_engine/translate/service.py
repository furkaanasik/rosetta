"""Orchestration: extract -> cache lookup -> plan/estimate -> (user approval) -> translate -> cache.

``plan`` never touches the provider; ``execute`` must only run after the user approved the plan.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import pymupdf

from rosetta_engine.config import Settings
from rosetta_engine.errors import (
    BudgetExceededError,
    ExtractionError,
    InvalidTranslationError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    RosettaError,
    UsageLimitError,
)
from rosetta_engine.extract.extractor import (
    EXTRACTOR_VERSION,
    BookMeta,
    extract_book_meta,
    extract_page,
)
from rosetta_engine.extract.pdf_reader import file_hash, open_book
from rosetta_engine.models import (
    Batch,
    Block,
    BlockType,
    Book,
    BookProfile,
    CostEstimate,
    JoinedUnit,
    PageBlocks,
    Translation,
    TranslationPlan,
    TranslationReport,
    UsageTotals,
)
from rosetta_engine.store.repo import (
    CacheKey,
    Clock,
    PageStatusRow,
    Repos,
    TranslationRow,
    UsageRow,
    utc_now,
)
from rosetta_engine.translate.base import (
    ProviderResult,
    TranslationItem,
    TranslationRequest,
    Translator,
)
from rosetta_engine.translate.estimator import (
    apply_calibration,
    calibration_factors,
    estimate_request,
    usd,
)
from rosetta_engine.translate.joins import find_link, merged_block, split_translation
from rosetta_engine.translate.prompt import PROMPT_VERSION

log = logging.getLogger(__name__)

CONTEXT_PARAGRAPHS = 2
NO_TEXT_REASON = "metin katmanı yok (taranmış sayfa?); OCR desteklenmiyor"
OUTPUT_SANITY_FACTOR = 2
MAX_CONSECUTIVE_ERRORS = 3
Progress = Callable[[int, int], None]
StopKind = Literal["usage_limit", "auth", "budget", "unavailable", "paused"]
BatchCallback = Callable[[TranslationReport], None]
BlockRef = tuple[int, str]  # (0-based page, source text_hash)
Joins = dict[str, JoinedUnit]  # merged text_hash -> unit


@dataclass
class _Tally:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def totals(self) -> UsageTotals:
        return UsageTotals(
            calls=self.calls,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            cost_usd=self.cost_usd,
        )


def _stop_kind(e: ProviderError) -> StopKind:
    if isinstance(e, UsageLimitError):
        return "usage_limit"
    if isinstance(e, BudgetExceededError):
        return "budget"
    if isinstance(e, ProviderUnavailableError):
        return "unavailable"
    return "auth"


def _needs_translation(block: Block) -> bool:
    return block.translatable and bool(block.text.strip())


def _unit_of(block: Block, joins: Joins) -> JoinedUnit | None:
    """The joined unit ``block`` stands for (a merged block), else None."""
    unit = joins.get(block.text_hash)
    if unit is None or block.page_no != unit.head_page or block.order != unit.head_order:
        return None
    return unit


def _parts(block: Block, joins: Joins) -> list[BlockRef]:
    """Source rows a planned block writes: both halves of a joined unit, else the block."""
    unit = _unit_of(block, joins)
    if unit is None:
        return [(block.page_no, block.text_hash)]
    return [(unit.head_page, unit.head_hash), (unit.tail_page, unit.tail_hash)]


class PageTranslationService:
    def __init__(
        self,
        translator: Translator,
        repos: Repos,
        settings: Settings,
        clock: Clock = utc_now,
        *,
        thinking_output_per_call: int = 0,
    ) -> None:
        """``thinking_output_per_call`` > 0: thinking is on; it is added to every output
        estimate and such calls are kept out of the (no-thinking) calibration."""
        self._t = translator
        self._thinking = thinking_output_per_call
        self._r = repos
        self._s = settings
        self._clock: Callable[[], datetime] = clock

    # --- books and pages (no AI) ---------------------------------------------------------

    def open_book(self, path: Path | str) -> tuple[Book, pymupdf.Document, BookMeta]:
        """Open a PDF; the book is identified by content hash, BookMeta cached in the DB."""
        path = Path(path)
        doc = open_book(path)
        try:
            return self._identify(path, doc)
        except BaseException:
            doc.close()  # type: ignore[no-untyped-call]
            raise

    def _identify(
        self, path: Path, doc: pymupdf.Document
    ) -> tuple[Book, pymupdf.Document, BookMeta]:
        h = file_hash(path)
        meta: BookMeta | None = None
        existing = self._r.books.get_by_hash(h)
        if existing is not None:
            cached, _ = self._r.books.get_meta(existing.id)
            if cached:
                candidate = BookMeta.model_validate_json(cached)
                if candidate.extractor_version == EXTRACTOR_VERSION:
                    meta = candidate
        fresh = meta is None
        if meta is None:
            meta = extract_book_meta(doc)
        book = self._r.books.get_or_create(
            h, meta.title or path.stem, meta.page_count, str(path.resolve())
        )
        if fresh:
            self._r.books.set_meta(book.id, meta.model_dump_json(), None)
        return book, doc, meta

    def ensure_pages(
        self, book: Book, doc: pymupdf.Document, meta: BookMeta, pages: Sequence[int]
    ) -> dict[int, PageBlocks]:
        """Extracted blocks for 0-based ``pages`` (from DB, or extracted and stored).

        Pages without a text layer (scanned) come back with ``has_text_layer=False`` and no
        blocks; callers skip them instead of aborting a whole range.
        """
        out: dict[int, PageBlocks] = {}
        for p in pages:
            if not 0 <= p < book.page_count:
                raise ExtractionError(f"page {p + 1} out of range (1-{book.page_count})")
            out[p] = self._load_page(book, doc, meta, p)
        return out

    def _load_page(
        self, book: Book, doc: pymupdf.Document, meta: BookMeta, page_no: int
    ) -> PageBlocks:
        if self._r.blocks.page_version(book.id, page_no) == EXTRACTOR_VERSION:
            stored = self._r.blocks.get_page(book.id, page_no)
            if stored is not None:
                return stored
        page = extract_page(doc, page_no, meta)
        self._r.blocks.replace_page(book.id, page, EXTRACTOR_VERSION)
        return page

    # --- plan (no AI) --------------------------------------------------------------------

    def _key(self, block: Block, lang: str) -> CacheKey:
        return CacheKey(block.page_no, block.text_hash, lang, self._t.name, self._t.model)

    def _part_key(self, ref: BlockRef, lang: str) -> CacheKey:
        return CacheKey(ref[0], ref[1], lang, self._t.name, self._t.model)

    def _uncached(
        self,
        book: Book,
        blocks: Sequence[Block],
        lang: str,
        force: bool,
        joins: Joins | None = None,
    ) -> list[Block]:
        """Blocks without a cached translation. A joined unit is cached when both of its rows
        exist and were written by that unit, or both were translated alone earlier (legacy
        pair, never re-translated automatically). One half only → the unit is re-translated."""
        if force:
            return list(blocks)
        joins = joins or {}
        keys = [self._part_key(ref, lang) for b in blocks for ref in _parts(b, joins)]
        cached = self._r.translations.get_many(book.id, keys)
        out: list[Block] = []
        for b in blocks:
            unit = _unit_of(b, joins)
            if unit is None:
                if self._key(b, lang) not in cached:
                    out.append(b)
                continue
            head, tail = (cached.get(self._part_key(r, lang)) for r in _parts(b, joins))
            ok = (
                head is not None
                and tail is not None
                and (
                    head.unit_hash == tail.unit_hash == unit.unit_hash
                    or (head.unit_hash is None and tail.unit_hash is None)
                )
            )
            if not ok:
                out.append(b)
        return out

    def _links(
        self,
        book: Book,
        doc: pymupdf.Document,
        meta: BookMeta,
        extracted: dict[int, PageBlocks],
        pages: Sequence[int],
    ) -> list[JoinedUnit]:
        """Paragraphs split by a page break that touch ``pages``. Neighbour pages are only
        extracted (no AI) and not added to ``extracted``."""
        loaded: dict[int, PageBlocks] = {}

        def get(p: int) -> PageBlocks:
            if p in extracted:
                return extracted[p]
            if p not in loaded:
                loaded[p] = self._load_page(book, doc, meta, p)
            return loaded[p]

        pairs = sorted(
            {(p - 1, p) for p in pages if p > 0}
            | {(p, p + 1) for p in pages if p + 1 < book.page_count}
        )
        units: list[JoinedUnit] = []
        for n, n1 in pairs:
            before = get(n - 1) if n > 0 else None
            unit = find_link(before, get(n), get(n1), meta.soft_hyphen)
            if unit is not None:
                units.append(unit)
            elif before is not None and find_link(None, get(n), get(n1), meta.soft_hyphen):
                log.info("not chaining page-break paragraph %d→%d (head is a tail)", n + 1, n1 + 1)
        return units

    def _apply_links(
        self,
        book: Book,
        doc: pymupdf.Document,
        meta: BookMeta,
        extracted: dict[int, PageBlocks],
        translatable: dict[int, list[Block]],
        units: Sequence[JoinedUnit],
    ) -> Joins:
        """Replace each unit's halves in ``translatable`` by one merged block: in the head's
        place, or first on the tail page when the head page is out of scope."""
        joins: Joins = {}
        for unit in units:
            head_page = extracted.get(unit.head_page) or self._load_page(
                book, doc, meta, unit.head_page
            )
            head = next(b for b in head_page.blocks if b.order == unit.head_order)
            merged = merged_block(unit, head)
            tail_bucket = translatable.get(unit.tail_page)
            if tail_bucket is not None:
                translatable[unit.tail_page] = [
                    b for b in tail_bucket if b.order != unit.tail_order
                ]
            head_bucket = translatable.get(unit.head_page)
            if head_bucket is not None:
                translatable[unit.head_page] = [
                    merged if b.order == unit.head_order else b for b in head_bucket
                ]
            else:
                translatable[unit.tail_page].insert(0, merged)
            joins[merged.text_hash] = unit
        return joins

    def plan(
        self,
        book: Book,
        doc: pymupdf.Document,
        meta: BookMeta,
        pages: Sequence[int],
        lang: str,
        *,
        profile: BookProfile | None = None,
        force: bool = False,
        only_blocks: frozenset[BlockRef] | None = None,
    ) -> TranslationPlan:
        """Find untranslated blocks, batch them and estimate cost. Never calls the provider.

        A paragraph split by a page break becomes one item (its neighbour-page half is pulled
        in; the neighbour page itself is not added to the plan). ``only_blocks`` = targeted
        re-translation of these (page, text_hash) blocks: they are planned even if cached and
        executing the plan never writes a page status."""
        profile = profile or BookProfile()
        targeted = only_blocks is not None
        if only_blocks is not None:
            pages = sorted({p for p, _ in only_blocks})
        pages = sorted(set(pages))
        extracted = self.ensure_pages(book, doc, meta, pages)
        no_text = [p for p in pages if not extracted[p].has_text_layer]
        if no_text:
            log.warning("skipping pages without a text layer: %s", [p + 1 for p in no_text])
        translatable = {p: [b for b in extracted[p].blocks if _needs_translation(b)] for p in pages}
        units = self._links(book, doc, meta, extracted, pages)
        joins = self._apply_links(book, doc, meta, extracted, translatable, units)
        if only_blocks is not None:
            translatable = {
                p: [b for b in blocks if any(r in only_blocks for r in _parts(b, joins))]
                for p, blocks in translatable.items()
            }
        planned = [b for blocks in translatable.values() for b in blocks]
        joins = {k: u for k, u in joins.items() if any(_unit_of(b, {k: u}) for b in planned)}
        total = len(planned)
        todo = {
            p: self._uncached(book, translatable[p], lang, force or targeted, joins) for p in pages
        }
        cached = total - sum(len(v) for v in todo.values())

        batches = self._batch(book, doc, meta, extracted, todo, lang, profile, joins)
        f = calibration_factors(self._r.usage.recent_ok(self._t.name, self._t.model))
        price = self._s.price_for(self._t.model)
        if price is None:
            log.warning("no price configured for model %s; cost shown as 0", self._t.model)
        est_in = est_out = 0
        for b in batches:
            i, o = apply_calibration(b.est_input_tokens, b.est_output_tokens, f)
            est_in += i
            est_out += o + self._thinking
        estimate = CostEstimate(
            calls=len(batches),
            input_tokens=est_in,
            output_tokens=est_out,
            usd=usd(est_in, est_out, price) if price is not None else 0.0,
            price_known=price is not None,
        )
        return TranslationPlan(
            book=book,
            lang=lang,
            provider=self._t.name,
            model=self._t.model,
            pages=pages,
            force=force,
            total_blocks=total,
            cached_blocks=cached,
            batches=batches,
            estimate=estimate,
            no_text_pages=no_text,
            targeted=targeted,
            joined_units=len(joins),
        )

    def _batch(
        self,
        book: Book,
        doc: pymupdf.Document,
        meta: BookMeta,
        extracted: dict[int, PageBlocks],
        todo: dict[int, list[Block]],
        lang: str,
        profile: BookProfile,
        joins: Joins | None = None,
    ) -> list[Batch]:
        """Greedy: <= batch_max_pages pages and <= batch_max_input_tokens estimated input."""
        joins = joins or {}
        max_pages = self._s.batch_max_pages
        max_tokens = self._s.batch_max_input_tokens
        batches: list[Batch] = []
        current: list[Block] = []
        context: list[str] = []

        def close() -> None:
            if current:
                batches.append(self._make_batch(list(current), context, lang, profile, joins))
                current.clear()

        for p in sorted(todo):
            for block in todo[p]:
                if not current:
                    context = self._context(book, doc, meta, extracted, block)
                    current.append(block)
                    continue
                pages = {b.page_no for b in current} | {block.page_no}
                candidate = self._request([*current, block], context, lang, profile)
                if len(pages) > max_pages or estimate_request(candidate)[0] > max_tokens:
                    close()
                    context = self._context(book, doc, meta, extracted, block)
                current.append(block)
        close()
        return batches

    def _context(
        self,
        book: Book,
        doc: pymupdf.Document,
        meta: BookMeta,
        extracted: dict[int, PageBlocks],
        first: Block,
    ) -> list[str]:
        """Last paragraphs before ``first``: same page if the batch starts mid-page,
        otherwise the preceding page."""
        page = extracted.get(first.page_no) or self._load_page(book, doc, meta, first.page_no)
        before = [b for b in page.blocks if b.order < first.order and b.translatable]
        if not before:
            prev_no = first.page_no - 1
            if prev_no < 0:
                return []
            prev = extracted.get(prev_no) or self._load_page(book, doc, meta, prev_no)
            before = list(prev.blocks)
        paras = [b.text for b in before if b.type == BlockType.PARAGRAPH]
        return paras[-CONTEXT_PARAGRAPHS:]

    def _request(
        self, blocks: Sequence[Block], context: list[str], lang: str, profile: BookProfile
    ) -> TranslationRequest:
        items = [
            TranslationItem(
                id=i,
                sentences=b.sentences or [b.text],
                kind="h" if b.type == BlockType.HEADING else "p",
            )
            for i, b in enumerate(blocks, start=1)
        ]
        return TranslationRequest(lang=lang, items=items, profile=profile, context=context)

    def _make_batch(
        self,
        blocks: list[Block],
        context: list[str],
        lang: str,
        profile: BookProfile,
        joins: Joins | None = None,
    ) -> Batch:
        est_in, est_out = estimate_request(self._request(blocks, context, lang, profile))
        joins = joins or {}
        mine = {b.text_hash: u for b in blocks if (u := _unit_of(b, joins)) is not None}
        return Batch(
            pages=sorted({b.page_no for b in blocks}),
            blocks=blocks,
            context=context,
            est_input_tokens=est_in,
            est_output_tokens=est_out,
            joins=mine,
        )

    # --- execute (AI; only after approval) -----------------------------------------------

    def execute(
        self,
        plan: TranslationPlan,
        *,
        profile: BookProfile | None = None,
        on_progress: Progress | None = None,
        should_stop: Callable[[], bool] | None = None,
        budget_usd: float | None = None,
        on_batch: BatchCallback | None = None,
    ) -> TranslationReport:
        """Translate the planned batches.

        ``should_stop`` is polled before every batch (True → stop_kind "paused");
        ``budget_usd`` stops (stop_kind "budget") before a batch whose estimated cost would push
        this run's spend over it; ``on_batch`` receives a progress snapshot after every batch.

        Each successful batch is cached immediately; a page
        is marked done only once all its blocks are translated. ``--force`` replaces old rows
        only when the new ones exist, so a stopped run never loses earlier translations."""
        profile = profile or BookProfile()
        book, lang, force = plan.book, plan.lang, plan.force
        for batch in plan.batches:
            bad = [b for b in batch.blocks if not _needs_translation(b)]
            if bad:
                raise RosettaError(
                    f"plan contains non-translatable or blank blocks: {bad[0].type} "
                    f"on page {bad[0].page_no + 1}"
                )

        # Re-check the cache: another run may have filled it since planning (not with
        # --force, where cache hits are expected and replaced; a targeted plan acts like it).
        replace = force or plan.targeted
        batches = [
            self._uncached(book, batch.blocks, lang, replace, batch.joins) for batch in plan.batches
        ]
        needed: dict[int, set[str]] = {p: set() for p in plan.pages}
        for batch, blocks in zip(plan.batches, batches, strict=True):
            for b in blocks:
                for p, h in _parts(b, batch.joins):
                    if p in needed:
                        needed[p].add(h)

        translated: dict[int, set[str]] = {p: set() for p in plan.pages}
        done: list[int] = []
        failed: dict[int, str] = {}
        tally = _Tally()
        stopped: str | None = None
        stop_kind: StopKind | None = None
        consecutive_errors = 0

        if not plan.targeted:
            # A targeted plan never writes page status: a partly translated page must not
            # become "done" (nor a done page "failed") because a few blocks were redone.
            for p in plan.no_text_pages:
                failed[p] = NO_TEXT_REASON
                self._fail_page(book, p, lang, NO_TEXT_REASON)
            for p in plan.pages:
                if not needed[p] and p not in failed:
                    self._save_page(book, p, lang, [], overwrite=force)
                    done.append(p)

        def plan_pages(blocks: Sequence[Block], joins: Joins) -> list[int]:
            pages = {p for b in blocks for p, _ in _parts(b, joins)}
            return sorted(p for p in pages if p in needed)

        def snapshot() -> TranslationReport:
            return TranslationReport(
                done_pages=sorted(done),
                failed_pages=dict(failed),
                stopped_reason=stopped,
                stop_kind=stop_kind,
                usage=tally.totals(),
            )

        price = self._s.price_for(self._t.model)
        total_batches = len(batches)
        for n, (batch, blocks) in enumerate(zip(plan.batches, batches, strict=True), start=1):
            blocks = [
                b for b in blocks if not any(p in failed for p in plan_pages([b], batch.joins))
            ]
            if blocks and should_stop is not None and should_stop():
                stopped, stop_kind = "pause requested", "paused"
                log.info("translation paused before batch %d/%d", n, total_batches)
                break
            if blocks and budget_usd is not None:
                if price is not None:
                    batch_usd = usd(
                        batch.est_input_tokens, batch.est_output_tokens + self._thinking, price
                    )
                    over = tally.cost_usd + batch_usd > budget_usd
                    stopped = (
                        f"budget ${budget_usd:.4f} would be exceeded "
                        f"(spent ${tally.cost_usd:.4f} + next batch ≈ ${batch_usd:.4f})"
                    )
                else:
                    # No price to estimate with: enforce on the cost the provider reported.
                    over = tally.cost_usd >= budget_usd
                    stopped = (
                        f"budget ${budget_usd:.4f} reached (spent ${tally.cost_usd:.4f}; "
                        "model price unknown)"
                    )
                if over:
                    stop_kind = "budget"
                    log.warning("translation stopped: %s", stopped)
                    break
                stopped = None
            if blocks and not replace:
                # Re-check right before paying: a concurrent run may have cached these blocks.
                fresh = self._uncached(book, blocks, lang, False, batch.joins)
                if len(fresh) < len(blocks):
                    keep = {(b.page_no, b.order) for b in fresh}
                    for b in blocks:
                        if (b.page_no, b.order) not in keep:
                            for p, h in _parts(b, batch.joins):
                                if p in translated:
                                    translated[p].add(h)
                    for p in plan_pages(blocks, batch.joins):
                        if p not in done and needed[p] <= translated[p]:
                            self._save_page(book, p, lang, [])
                            done.append(p)
                    blocks = fresh
            if blocks:
                request = self._request(blocks, batch.context, lang, profile)
                try:
                    result = self._call(book, request, tally)
                except (
                    UsageLimitError,
                    ProviderAuthError,
                    BudgetExceededError,
                    ProviderUnavailableError,
                ) as e:
                    stopped = str(e)
                    stop_kind = _stop_kind(e)
                    log.warning("translation stopped (%s): %s", stop_kind, e)
                    break
                except ProviderError as e:
                    for p in plan_pages(blocks, batch.joins):
                        failed[p] = str(e)
                        if not plan.targeted:
                            self._fail_page(book, p, lang, str(e))
                    consecutive_errors += 1
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        stopped = f"{consecutive_errors} consecutive provider errors; last: {e}"
                        stop_kind = "unavailable"
                        log.warning("translation stopped: %s", stopped)
                        break
                else:
                    consecutive_errors = 0
                    self._store_batch(
                        book,
                        lang,
                        blocks,
                        result,
                        needed,
                        translated,
                        done,
                        force,
                        joins=batch.joins,
                        targeted=plan.targeted,
                    )
            if on_progress is not None:
                on_progress(n, total_batches)
            if on_batch is not None:
                on_batch(snapshot())
            if stop_kind is not None:
                break

        return snapshot()

    def _store_batch(
        self,
        book: Book,
        lang: str,
        blocks: Sequence[Block],
        result: ProviderResult,
        needed: dict[int, set[str]],
        translated: dict[int, set[str]],
        done: list[int],
        force: bool,
        *,
        joins: Joins | None = None,
        targeted: bool = False,
    ) -> None:
        """Cache a batch's rows now; pages it completes are saved with status 'done'.

        A joined unit is split back into a head row and a tail row, written with overwrite
        (it replaces halves translated alone) and without status for out-of-plan pages. A
        targeted batch only replaces rows; the touched pages are reported, never saved."""
        joins = joins or {}
        by_page: dict[int, list[TranslationRow]] = {}
        unit_rows: list[TranslationRow] = []

        def row(
            page_no: int,
            h: str,
            sentences: list[str],
            aligned: bool,
            unit: JoinedUnit | None = None,
            role: str | None = None,
        ) -> TranslationRow:
            return TranslationRow(
                book_id=book.id,
                page_no=page_no,
                text_hash=h,
                lang=lang,
                provider=self._t.name,
                model=self._t.model,
                text=" ".join(sentences),
                sentences=sentences,
                sentence_aligned=aligned,
                prompt_version=PROMPT_VERSION,
                unit_hash=unit.unit_hash if unit else None,
                unit_role=role,
            )

        touched: set[int] = set()
        for i, b in enumerate(blocks, start=1):
            item = result.items[i]
            unit = _unit_of(b, joins)
            if unit is None:
                by_page.setdefault(b.page_no, []).append(
                    row(b.page_no, b.text_hash, list(item.sentences), item.aligned)
                )
                touched.add(b.page_no)
                continue
            head_s, tail_s, ok = split_translation(unit, list(item.sentences), item.aligned)
            unit_rows.append(row(unit.head_page, unit.head_hash, head_s, ok, unit, "head"))
            unit_rows.append(row(unit.tail_page, unit.tail_hash, tail_s, ok, unit, "tail"))
            for p, h in _parts(b, joins):
                if p in translated:
                    translated[p].add(h)
                    touched.add(p)
        if unit_rows:
            self._r.translations.put_rows(unit_rows, overwrite=True)
        if targeted:
            self._r.translations.put_rows(
                [r for rows in by_page.values() for r in rows], overwrite=True
            )
            done.extend(p for p in sorted(touched) if p not in done)
            return
        for p in sorted(touched):
            rows = by_page.get(p, [])
            translated[p].update(r.text_hash for r in rows)
            if p not in done and needed[p] <= translated[p]:
                self._save_page(book, p, lang, rows, overwrite=force)
                done.append(p)
            elif rows:
                self._r.translations.put_rows(rows, overwrite=force)

    def _call(self, book: Book, request: TranslationRequest, tally: _Tally) -> ProviderResult:
        """One provider call, plus one strict retry on an invalid payload. Logs every call."""
        est_in, est_out = estimate_request(request)
        est_out += self._thinking
        strict = False
        while True:
            try:
                result = self._t.translate(request, strict=strict)
            except InvalidTranslationError as e:
                spent = (e.input_tokens, e.output_tokens, e.cost_usd)
                self._record(book, est_in, est_out, None, tally, spent=spent)
                if strict:
                    raise
                log.info("invalid translation, retrying strict: %s", e.reason)
                strict = True
                continue
            except ProviderUnavailableError:
                raise  # nothing ran, nothing to record
            except ProviderError as e:
                spent = (e.input_tokens, e.output_tokens, e.cost_usd)
                self._record(book, est_in, est_out, None, tally, spent=spent)
                raise
            self._record(book, est_in, est_out, result, tally)
            log.info(
                "translated batch (book %s): in %d / out %d tok",
                book.file_hash[:8],
                result.input_tokens,
                result.output_tokens,
            )
            return result

    def _record(
        self,
        book: Book,
        est_in: int,
        est_out: int,
        result: ProviderResult | None,
        tally: _Tally,
        *,
        spent: tuple[int, int, float] | None = None,
    ) -> None:
        """``spent`` = (input, output, usd) reported by a failed call that still cost tokens."""
        tin = result.input_tokens if result else (spent[0] if spent else 0)
        tout = result.output_tokens if result else (spent[1] if spent else 0)
        if result is not None and est_out > 0 and tout > OUTPUT_SANITY_FACTOR * est_out:
            log.warning(
                "output tokens %d exceed %dx the estimate %d; thinking may be enabled",
                tout,
                OUTPUT_SANITY_FACTOR,
                est_out,
            )
        cost = result.cost_usd if result else (spent[2] if spent else 0.0)
        self._r.usage.add(
            UsageRow(
                book_id=book.id,
                provider=self._t.name,
                model=self._t.model,
                operation="translate",
                input_tokens=tin,
                output_tokens=tout,
                cost_usd=cost,
                ok=result is not None,
                est_input_tokens=est_in,
                est_output_tokens=est_out,
                calibrate=self._thinking == 0,
            )
        )
        tally.calls += 1
        tally.input_tokens += tin
        tally.output_tokens += tout
        tally.cost_usd += cost

    def _status(self, book: Book, page_no: int, lang: str, error: str | None) -> PageStatusRow:
        return PageStatusRow(
            book_id=book.id,
            page_no=page_no,
            lang=lang,
            provider=self._t.name,
            model=self._t.model,
            status="failed" if error else "done",
            error=error,
        )

    def _save_page(
        self,
        book: Book,
        page_no: int,
        lang: str,
        rows: list[TranslationRow],
        *,
        overwrite: bool = False,
    ) -> None:
        status = self._status(book, page_no, lang, None)
        self._r.translations.put_page(rows, status, overwrite=overwrite)

    def _fail_page(self, book: Book, page_no: int, lang: str, error: str) -> None:
        self._r.page_status.set(self._status(book, page_no, lang, error))

    # --- read side -----------------------------------------------------------------------

    def page_view(
        self, book: Book, page_no: int, lang: str
    ) -> tuple[PageBlocks, dict[str, Translation]]:
        """Stored blocks of a page plus its translations keyed by source text_hash."""
        page = self._r.blocks.get_page(book.id, page_no)
        if page is None:
            raise ExtractionError(f"page {page_no + 1} has not been extracted")
        translations = self._r.translations.for_page(
            book.id, page_no, lang, self._t.name, self._t.model
        )
        return page, translations

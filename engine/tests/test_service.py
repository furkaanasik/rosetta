"""PageTranslationService with FakeTranslator and an in-memory DB."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from rosetta_engine.config import Settings
from rosetta_engine.errors import ExtractionError, RosettaError
from rosetta_engine.models import TRANSLATABLE, Batch, BlockType
from rosetta_engine.store import db
from rosetta_engine.store.repo import Repos
from rosetta_engine.translate import service as service_mod
from rosetta_engine.translate.fake import FailMode, FakeTranslator
from rosetta_engine.translate.service import PageTranslationService

ALL = [0, 1, 2]
SKIPPED = {BlockType.CODE, BlockType.IMAGE, BlockType.TABLE, BlockType.FURNITURE}


@pytest.fixture
def repos() -> Iterator[Repos]:
    conn = db.connect(":memory:")
    db.migrate(conn)
    yield Repos.from_conn(conn)
    conn.close()


def _service(
    repos: Repos,
    fail_mode: FailMode | None = None,
    fail_after: int = 0,
    **settings: Any,
) -> tuple[PageTranslationService, FakeTranslator]:
    fake = FakeTranslator(fail_mode=fail_mode, fail_after=fail_after)
    return PageTranslationService(fake, repos, Settings(**settings)), fake


def _plan(svc: PageTranslationService, pdf: Path, pages: list[int], **kw: Any) -> Any:
    book, doc, meta = svc.open_book(pdf)
    return svc.plan(book, doc, meta, pages, "tr", **kw)


def test_plan_does_not_call_provider(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos)

    plan = _plan(svc, book_pdf, ALL)

    assert fake.calls == []
    assert plan.batches
    assert plan.estimate.calls == len(plan.batches)
    assert plan.estimate.input_tokens > 0
    assert plan.cached_blocks == 0
    assert plan.total_blocks == sum(len(b.blocks) for b in plan.batches)


def test_execute_translates_and_second_run_is_free(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos)
    report = svc.execute(_plan(svc, book_pdf, ALL))

    assert report.done_pages == ALL
    assert report.failed_pages == {}
    assert report.usage.calls == len(fake.calls) > 0

    fake.calls.clear()
    plan2 = _plan(svc, book_pdf, ALL)
    report2 = svc.execute(plan2)

    assert plan2.batches == []
    assert plan2.cached_blocks == plan2.total_blocks > 0
    assert fake.calls == []
    assert report2.done_pages == ALL
    assert report2.usage.calls == 0


def test_page_view_returns_translations(repos: Repos, book_pdf: Path) -> None:
    svc, _ = _service(repos)
    plan = _plan(svc, book_pdf, [0])
    svc.execute(plan)

    page, tr = svc.page_view(plan.book, 0, "tr")

    for b in page.blocks:
        if b.translatable:
            assert tr[b.text_hash].text.startswith("[TR] ")
        else:
            assert b.text_hash not in tr


def test_untranslatable_blocks_never_sent(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos)
    plan = _plan(svc, book_pdf, ALL)
    svc.execute(plan)

    sent = {s for req, _ in fake.calls for item in req.items for s in item.sentences}
    book, _, _ = svc.open_book(book_pdf)
    for p in ALL:
        page, _ = svc.page_view(book, p, "tr")
        for b in page.blocks:
            if b.type not in TRANSLATABLE:
                assert b.type in {
                    BlockType.CODE,
                    BlockType.IMAGE,
                    BlockType.TABLE,
                    BlockType.FURNITURE,
                }
                assert not any(b.text and b.text in s for s in sent if b.text.strip())
    assert all(b.translatable for batch in plan.batches for b in batch.blocks)


def test_invalid_twice_retries_strict_then_fails(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos, fail_mode="invalid")

    report = svc.execute(_plan(svc, book_pdf, [0]))

    assert [strict for _, strict in fake.calls] == [False, True]
    assert report.failed_pages.keys() == {0}
    assert report.done_pages == []
    status = repos.page_status.get(report_book_id(repos), 0, "tr", "fake", "fake")
    assert status is not None and status.status == "failed"
    assert repos.usage.total().calls == 2


def report_book_id(repos: Repos) -> int:
    return int(repos.conn.execute("SELECT id FROM books").fetchone()[0])


def test_invalid_once_succeeds_on_strict_retry(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos, fail_mode="invalid_once")

    report = svc.execute(_plan(svc, book_pdf, [0]))

    assert [strict for _, strict in fake.calls] == [False, True]
    assert report.done_pages == [0]


def test_usage_limit_stops_and_keeps_finished(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos, fail_mode="limit", fail_after=1, batch_max_pages=1)
    plan = _plan(svc, book_pdf, ALL)
    assert len(plan.batches) == 3

    report = svc.execute(plan)

    assert report.stop_kind == "usage_limit"
    assert report.stopped_reason
    assert report.done_pages == [0]
    assert len(fake.calls) == 2  # third batch never attempted
    _, tr = svc.page_view(plan.book, 0, "tr")
    assert tr
    _, tr1 = svc.page_view(plan.book, 1, "tr")
    assert tr1 == {}


def test_auth_error_stops(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos, fail_mode="auth")

    report = svc.execute(_plan(svc, book_pdf, ALL))

    assert report.stop_kind == "auth"
    assert report.done_pages == []
    assert len(fake.calls) == 1


def test_budget_exceeded_stops_and_records_usage(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos, fail_mode="budget", batch_max_pages=1)
    plan = _plan(svc, book_pdf, ALL)

    report = svc.execute(plan)

    assert report.stop_kind == "budget"
    assert report.stopped_reason
    assert report.done_pages == []
    assert len(fake.calls) == 1  # no retry, remaining batches skipped
    assert report.usage.calls == 1
    assert report.usage.cost_usd == 0.02
    assert repos.usage.total().output_tokens == 50


def test_dense_page_respects_token_limit(repos: Repos, book_pdf: Path) -> None:
    svc, _ = _service(repos, batch_max_input_tokens=450)

    plan = _plan(svc, book_pdf, [0])

    assert len(plan.batches) > 1
    for b in plan.batches:
        assert b.est_input_tokens <= 450 or len(b.blocks) == 1
    report = svc.execute(plan)
    assert report.done_pages == [0]  # page split across batches still saved


def test_force_retranslates(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos)
    svc.execute(_plan(svc, book_pdf, [0]))
    fake.calls.clear()

    plan = _plan(svc, book_pdf, [0], force=True)
    report = svc.execute(plan)

    assert plan.cached_blocks == 0
    assert fake.calls
    assert report.done_pages == [0]


def test_same_pdf_other_path_is_same_book(repos: Repos, book_pdf: Path, tmp_path: Path) -> None:
    svc, _ = _service(repos)
    copy = tmp_path / "elsewhere.pdf"
    shutil.copy(book_pdf, copy)

    a, _, _ = svc.open_book(book_pdf)
    b, _, _ = svc.open_book(copy)

    assert a.id == b.id
    assert b.file_path == str(copy.resolve())


def test_page_without_text_layer_raises(
    repos: Repos, make_pdf: Callable[[Callable[[Any], None], str], Path]
) -> None:
    def fill(doc: Any) -> None:
        page = doc.new_page()
        page.draw_rect(pymupdf.Rect(50, 50, 200, 200), fill=(0.5, 0.5, 0.5))

    svc, fake = _service(repos)
    book, doc, meta = svc.open_book(make_pdf(fill, "scan.pdf"))

    with pytest.raises(ExtractionError, match="no text layer"):
        svc.plan(book, doc, meta, [0], "tr")
    assert fake.calls == []


def test_out_of_range_page_raises(repos: Repos, book_pdf: Path) -> None:
    svc, _ = _service(repos)

    with pytest.raises(ExtractionError, match="out of range"):
        _plan(svc, book_pdf, [99])


def test_context_comes_from_previous_page(repos: Repos, book_pdf: Path) -> None:
    svc, _ = _service(repos, batch_max_pages=1)

    plan = _plan(svc, book_pdf, [1])

    assert plan.batches[0].context
    assert len(plan.batches[0].context) <= 2


class _ThinkingFake(FakeTranslator):
    """Returns 10x the estimated output tokens, like a call with thinking enabled."""

    def translate(self, request: Any, *, strict: bool = False) -> Any:
        res = super().translate(request, strict=strict)
        return res.model_copy(update={"output_tokens": res.output_tokens * 10})


def test_inflated_output_logs_warning(
    repos: Repos, book_pdf: Path, caplog: pytest.LogCaptureFixture
) -> None:
    svc = PageTranslationService(_ThinkingFake(), repos, Settings())
    plan = _plan(svc, book_pdf, [0])

    with caplog.at_level("WARNING", logger="rosetta_engine.translate.service"):
        svc.execute(plan)

    assert any("thinking may be enabled" in r.getMessage() for r in caplog.records)


def test_normal_output_no_warning(
    repos: Repos, book_pdf: Path, caplog: pytest.LogCaptureFixture
) -> None:
    svc, _ = _service(repos)
    plan = _plan(svc, book_pdf, [0])

    with caplog.at_level("WARNING", logger="rosetta_engine.translate.service"):
        svc.execute(plan)

    assert not any("thinking may be enabled" in r.getMessage() for r in caplog.records)


def test_thinking_adds_output_estimate_and_skips_calibration(repos: Repos, book_pdf: Path) -> None:
    plain, _ = _service(repos)
    base = _plan(plain, book_pdf, [0])
    fake = FakeTranslator()
    thinking = PageTranslationService(fake, repos, Settings(), thinking_output_per_call=9000)

    plan = _plan(thinking, book_pdf, [0])
    thinking.execute(plan)

    assert plan.estimate.output_tokens == base.estimate.output_tokens + 9000 * plan.estimate.calls
    assert repos.usage.total(None).calls == len(fake.calls) > 0
    assert repos.usage.recent_ok(fake.name, fake.model) == []
    flags = repos.conn.execute("SELECT DISTINCT calibrate FROM usage").fetchall()
    assert [tuple(r) for r in flags] == [(0,)]


def test_no_thinking_usage_rows_are_calibrated(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos)

    svc.execute(_plan(svc, book_pdf, [0]))

    assert len(repos.usage.recent_ok(fake.name, fake.model)) == len(fake.calls) > 0


def _texts(svc: PageTranslationService, book: Any, page: int) -> list[str]:
    _, tr = svc.page_view(book, page, "tr")
    return [t.text for t in tr.values()]


def test_force_stopped_run_keeps_old_translations(repos: Repos, book_pdf: Path) -> None:
    svc, _ = _service(repos)
    svc.execute(_plan(svc, book_pdf, ALL))
    new = FakeTranslator(fail_mode="limit", fail_after=1, prefix="[NEW] ")
    svc2 = PageTranslationService(new, repos, Settings(batch_max_pages=1))

    plan = _plan(svc2, book_pdf, ALL, force=True)
    report = svc2.execute(plan)

    assert report.stop_kind == "usage_limit"
    assert report.done_pages == [0]
    assert all(t.startswith("[NEW] ") for t in _texts(svc2, plan.book, 0))
    for page in (1, 2):  # never reached: the old translations survive
        old = _texts(svc2, plan.book, page)
        assert old and all(t.startswith("[TR] ") for t in old)


def test_force_completed_run_replaces_rows(repos: Repos, book_pdf: Path) -> None:
    svc, _ = _service(repos)
    svc.execute(_plan(svc, book_pdf, [0]))
    count = len(_texts(svc, _plan(svc, book_pdf, [0]).book, 0))
    svc2 = PageTranslationService(FakeTranslator(prefix="[NEW] "), repos, Settings())

    plan = _plan(svc2, book_pdf, [0], force=True)
    report = svc2.execute(plan)

    texts = _texts(svc2, plan.book, 0)
    assert report.done_pages == [0]
    assert len(texts) == count
    assert all(t.startswith("[NEW] ") for t in texts)


def test_partial_page_rows_survive_a_stop(repos: Repos, book_pdf: Path) -> None:
    svc, _ = _service(repos, fail_mode="limit", fail_after=1, batch_max_input_tokens=450)
    plan = _plan(svc, book_pdf, [0])
    assert len(plan.batches) > 1  # page 0 is split across batches
    first = len(plan.batches[0].blocks)

    report = svc.execute(plan)

    assert report.stop_kind == "usage_limit"
    assert report.done_pages == []
    assert repos.page_status.get(plan.book.id, 0, "tr", "fake", "fake") is None
    svc2, _ = _service(repos, batch_max_input_tokens=450)
    rerun = _plan(svc2, book_pdf, [0])
    assert rerun.cached_blocks == first  # paid work kept; only the rest is planned
    assert sum(len(b.blocks) for b in rerun.batches) == plan.total_blocks - first
    assert svc2.execute(rerun).done_pages == [0]


def test_failed_calls_record_spent_tokens(repos: Repos, book_pdf: Path) -> None:
    svc, _ = _service(repos, fail_mode="invalid")

    report = svc.execute(_plan(svc, book_pdf, [0]))

    assert report.failed_pages
    assert report.usage.calls == 2  # original + strict retry
    assert report.usage.input_tokens == 200
    assert repos.usage.total().output_tokens == 80


def test_unavailable_stops_without_recording(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos, fail_mode="unavailable", batch_max_pages=1)

    report = svc.execute(_plan(svc, book_pdf, ALL))

    assert report.stop_kind == "unavailable"
    assert len(fake.calls) == 1
    assert report.failed_pages == {}
    assert repos.usage.total().calls == 0


def test_consecutive_errors_stop_the_run(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos, fail_mode="error", batch_max_pages=1)

    report = svc.execute(_plan(svc, book_pdf, ALL))

    assert len(fake.calls) == 3
    assert report.stop_kind == "unavailable"
    assert report.stopped_reason and "3 consecutive" in report.stopped_reason
    assert sorted(report.failed_pages) == ALL
    assert report.usage.cost_usd == pytest.approx(0.003)


def test_two_errors_do_not_stop(repos: Repos, book_pdf: Path) -> None:
    svc, _ = _service(repos, fail_mode="error", batch_max_pages=1)

    report = svc.execute(_plan(svc, book_pdf, [0, 1]))

    assert report.stop_kind is None
    assert sorted(report.failed_pages) == [0, 1]


def test_blank_translatable_block_is_not_planned(repos: Repos, book_pdf: Path) -> None:
    svc, _ = _service(repos)
    book, doc, meta = svc.open_book(book_pdf)
    page = svc.ensure_pages(book, doc, meta, [0])[0]
    target = next(b for b in page.blocks if b.type == BlockType.PARAGRAPH)
    blank = target.model_copy(update={"text": "   ", "sentences": [], "text_hash": "blank"})
    blocks = [blank if b is target else b for b in page.blocks]
    repos.blocks.replace_page(book.id, page.model_copy(update={"blocks": blocks}), 1)

    plan = svc.plan(book, doc, meta, [0], "tr")
    report = svc.execute(plan)

    assert all(b.text.strip() for batch in plan.batches for b in batch.blocks)
    assert report.done_pages == [0]


def test_execute_rejects_untranslatable_or_blank_blocks(repos: Repos, book_pdf: Path) -> None:
    svc, fake = _service(repos)
    plan = _plan(svc, book_pdf, [0])
    page, _ = svc.page_view(plan.book, 0, "tr")
    code = next(b for b in page.blocks if b.type == BlockType.CODE)
    para = next(b for b in page.blocks if b.type == BlockType.PARAGRAPH)

    for bad in (code, para.model_copy(update={"text": " "})):
        forged = plan.model_copy(update={"batches": [Batch(pages=[0], blocks=[bad])]})
        with pytest.raises(RosettaError):
            svc.execute(forged)
    assert fake.calls == []


def test_unknown_price_flags_estimate(repos: Repos, book_pdf: Path) -> None:
    svc, _ = _service(repos, pricing={})

    plan = _plan(svc, book_pdf, [0])

    assert plan.estimate.price_known is False
    assert plan.estimate.usd == 0.0


def test_open_book_closes_doc_on_error(
    repos: Repos, book_pdf: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc, _ = _service(repos)
    closed: list[bool] = []
    real_open = service_mod.open_book

    def tracking_open(path: Path) -> Any:
        doc = real_open(path)
        real_close = doc.close
        doc.close = lambda: (closed.append(True), real_close())  # type: ignore[method-assign]
        return doc

    def boom(path: Path) -> str:
        raise RuntimeError("hash failed")

    monkeypatch.setattr(service_mod, "open_book", tracking_open)
    monkeypatch.setattr(service_mod, "file_hash", boom)

    with pytest.raises(RuntimeError):
        svc.open_book(book_pdf)
    assert closed == [True]

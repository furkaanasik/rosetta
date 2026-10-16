"""AI endpoints. Every one is two-step: a free ``…/estimate`` issues a one-shot confirm token
bound to the exact plan; the run endpoint only executes a plan presented with its token."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Query

from rosetta_engine.api.deps import Engine
from rosetta_engine.api.errors import ApiError, bad_request, not_found
from rosetta_engine.api.schemas import (
    ConfirmBody,
    ExplainEstimateBody,
    JobEstimateBody,
    Operation,
    TranslateEstimateBody,
    estimate,
    job,
    report,
)
from rosetta_engine.api.state import EngineState, OpenBook, Session
from rosetta_engine.explain.explainer import Explainer, ExplainPlan, Explanation, render_text
from rosetta_engine.jobs.runner import BUDGET_NO_PRICE, FINISHED, JobError, JobRunner
from rosetta_engine.models import BookProfile, TranslationPlan
from rosetta_engine.profile.profiler import ProfilePlan, Profiler
from rosetta_engine.store.repo import JobRow
from rosetta_engine.translate.base import Translator
from rosetta_engine.translate.claude_cli import unavailable_message
from rosetta_engine.translate.claude_locate import resolve_claude
from rosetta_engine.translate.providers import (
    UnknownProviderError,
    make_translator,
    supports_profile,
)
from rosetta_engine.translate.service import PageTranslationService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


# --- translator setup (mirrors the CLI) ------------------------------------------------------


@dataclass(frozen=True)
class _Provider:
    name: str
    model: str | None  # as requested (None = provider default)
    thinking: str | None
    extra: int


def _provider(eng: EngineState, provider: str | None, model: str | None) -> _Provider:
    name = provider or eng.settings.provider
    if name == "claude-cli":
        level = eng.settings.thinking_level
        extra = eng.settings.thinking_extra_output(model or eng.settings.model)
        return _Provider(name, model, level, extra)
    return _Provider(name, model, None, 0)


def _translator(eng: EngineState, p: _Provider) -> Translator:
    try:
        return eng.translator_factory(p.name, p.model, eng.settings)
    except UnknownProviderError as e:
        raise bad_request(str(e)) from e


def _service(
    eng: EngineState, s: Session, p: _Provider
) -> tuple[PageTranslationService, Translator]:
    t = _translator(eng, p)
    svc = PageTranslationService(t, s.repos, eng.settings, thinking_output_per_call=p.extra)
    return svc, t


def _profile(s: Session, book_id: int, t: Translator) -> BookProfile | None:
    return s.repos.profiles.get(book_id) if supports_profile(t) else None


def _plan_estimate(
    eng: EngineState,
    token: str,
    operation: str,
    plan: TranslationPlan,
    p: _Provider,
    t: Translator,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    op: Operation = "translate" if operation == "translate" else "job"
    warnings = [*(warnings or []), *provider_warnings(eng, t.name)]
    return estimate(
        token,
        op,
        provider=t.name,
        model=t.model,
        cost=plan.estimate,
        thinking=p.thinking,
        thinking_extra=p.extra,
        pages=plan.pages,
        expires_in=eng.confirm.ttl_s,
        total_blocks=plan.total_blocks,
        cached_blocks=plan.cached_blocks,
        supports_profile=supports_profile(t),
        warnings=warnings or None,
    )


def provider_warnings(eng: EngineState, provider: str) -> list[str]:
    """Problems the user can fix before confirming (shown in the cost dialog). No AI."""
    real = eng.translator_factory is make_translator
    if real and provider == "claude-cli" and resolve_claude(eng.settings.claude_path) is None:
        return [unavailable_message(eng.settings.claude_path)]
    return []


# --- single translation -----------------------------------------------------------------------


@dataclass(frozen=True)
class _TranslatePayload:
    plan: TranslationPlan
    provider: _Provider
    profile: BookProfile | None


@router.post("/books/{book_id}/estimate")
def translate_estimate(book_id: int, body: TranslateEstimateBody, eng: Engine) -> dict[str, Any]:
    p = _provider(eng, body.provider, body.model)
    with eng.db() as s:
        ob = eng.book(s, book_id)
        pages = eng.check_pages(ob, body.pages)
        svc, t = _service(eng, s, p)
        profile = _profile(s, book_id, t)
        lang = body.lang or eng.settings.default_lang
        with ob.lock:
            plan = svc.plan(
                ob.book, ob.doc, ob.meta, pages, lang, profile=profile, force=body.force
            )
    token = eng.confirm.issue("translate", f"book:{book_id}", _TranslatePayload(plan, p, profile))
    return _plan_estimate(eng, token, "translate", plan, p, t)


def _seconds_hint(calls: int, output_tokens: int) -> int:
    """Very rough wall-clock guess for display only (≈70 output tok/s + call overhead)."""
    return 0 if calls == 0 else round(calls * 4 + output_tokens / 70)


@router.get("/books/{book_id}/pages/{page}/estimate_hint")
def estimate_hint(book_id: int, page: int, eng: Engine, lang: str | None = None) -> dict[str, Any]:
    """Display-only cost hint for an untranslated page sheet.

    Same ``plan()`` as ``/estimate`` (extraction + cache lookup, never the provider), but it
    issues **no confirm token**: translating still requires ``/estimate`` → user confirmation.
    """
    p = _provider(eng, None, None)
    with eng.db() as s:
        ob = eng.book(s, book_id)
        pages = eng.check_pages(ob, [page])
        svc, t = _service(eng, s, p)
        profile = _profile(s, book_id, t)
        target = lang or eng.settings.default_lang
        with ob.lock:
            plan = svc.plan(ob.book, ob.doc, ob.meta, pages, target, profile=profile)
    cost = plan.estimate
    return {
        "page": page,
        "provider": t.name,
        "model": t.model,
        "calls": cost.calls,
        "input_tokens": cost.input_tokens,
        "output_tokens": cost.output_tokens,
        "usd": round(cost.usd, 6),
        "price_known": cost.price_known,
        "thinking": p.thinking,
        "total_blocks": plan.total_blocks,
        "cached_blocks": plan.cached_blocks,
        "has_text_layer": not plan.no_text_pages,
        "seconds_hint": _seconds_hint(cost.calls, cost.output_tokens),
    }


@router.post("/books/{book_id}/translate")
def translate(book_id: int, body: ConfirmBody, eng: Engine) -> dict[str, Any]:
    scope = f"book:{book_id}"
    with eng.ai_call():
        payload: _TranslatePayload = eng.confirm.take(body.confirm_token, "translate", scope)
        with eng.db() as s:
            svc, _ = _service(eng, s, payload.provider)
            result = svc.execute(payload.plan, profile=payload.profile)
    return report(result)


# --- batch jobs ------------------------------------------------------------------------------


@dataclass(frozen=True)
class _JobPayload:
    book_id: int
    pages: list[int]
    lang: str
    provider: _Provider
    budget_usd: float | None


def _format_pages(pages: list[int]) -> str:
    from rosetta_engine.cli import format_pages

    return format_pages(pages)


def _job_model(job_provider: str, job_model: str) -> str | None:
    if job_provider == "ollama":
        return job_model.removeprefix("ollama/")
    if job_provider == "deepl":
        return None
    return job_model


def _run_job(eng: EngineState, job_id: int, p: _Provider, only: list[int] | None = None) -> None:
    """Background thread body: own SQLite connection; plan under the book lock, then run.

    ``only`` = exactly the pages the user confirmed (resume/retry); None for a new job, whose
    confirmed page set is the job itself."""
    try:
        with eng.db() as s:
            svc, t = _service(eng, s, p)
            runner = JobRunner(svc, s.repos)
            current = runner.get(job_id)
            ob = eng.book(s, current.book_id)
            profile = _profile(s, current.book_id, t)
            try:
                with ob.lock:
                    plan = runner.plan(
                        current, ob.doc, ob.meta, ob.book, profile=profile, only=only
                    )
            except Exception as e:
                s.repos.jobs.set_status(job_id, "paused", f"planlama hatası: {e}")
                raise
            runner.run(current, plan, profile=profile)
    except JobError as e:
        log.info("job %d not run: %s", job_id, e)
    except Exception:
        log.exception("job %d failed", job_id)


def _job_or_404(s: Session, job_id: int) -> JobRow:
    found = s.repos.jobs.get(job_id)
    if found is None:
        raise not_found(f"İş bulunamadı: #{job_id}")
    return found


def _job_provider(eng: EngineState, provider: str, model: str) -> _Provider:
    return _provider(eng, provider, _job_model(provider, model))


@router.post("/books/{book_id}/jobs/estimate")
def job_estimate(book_id: int, body: JobEstimateBody, eng: Engine) -> dict[str, Any]:
    p = _provider(eng, body.provider, body.model)
    with eng.db() as s:
        ob = eng.book(s, book_id)
        pages = list(range(ob.book.page_count)) if body.all else eng.check_pages(ob, body.pages)
        svc, t = _service(eng, s, p)
        lang = body.lang or eng.settings.default_lang
        with ob.lock:
            plan = svc.plan(ob.book, ob.doc, ob.meta, pages, lang, profile=_profile(s, book_id, t))
    payload = _JobPayload(book_id, pages, lang, p, body.budget_usd)
    token = eng.confirm.issue("job", "new", payload)
    warnings = (
        [BUDGET_NO_PRICE] if body.budget_usd is not None and not plan.estimate.price_known else []
    )
    return _plan_estimate(eng, token, "job", plan, p, t, warnings)


@router.post("/jobs")
def job_start(body: ConfirmBody, eng: Engine) -> dict[str, Any]:
    with eng.job_slot() as start:  # busy → 503 before the token is consumed or a row exists
        payload: _JobPayload = eng.confirm.take(body.confirm_token, "job", "new")
        with eng.db() as s:
            ob = eng.book(s, payload.book_id)
            t = _translator(eng, payload.provider)
            created = JobRunner(None, s.repos).create(
                ob.book,
                payload.pages,
                _format_pages(payload.pages),
                payload.lang,
                t.name,
                t.model,
                payload.budget_usd,
            )
        start(created.id, lambda: _run_job(eng, created.id, payload.provider))
    with eng.db() as s:
        return job(_job_or_404(s, created.id))


@router.get("/jobs")
def job_list(eng: Engine, book_id: int | None = Query(default=None)) -> list[dict[str, Any]]:
    with eng.db() as s:
        return [job(j) for j in s.repos.jobs.list_jobs(book_id)]


@router.get("/jobs/{job_id}")
def job_get(job_id: int, eng: Engine) -> dict[str, Any]:
    with eng.db() as s:
        return job(_job_or_404(s, job_id))


@router.post("/jobs/{job_id}/pause")
def job_pause(job_id: int, eng: Engine) -> dict[str, Any]:
    with eng.db() as s:
        _job_or_404(s, job_id)
        try:
            return job(JobRunner(None, s.repos).request_pause(job_id))
        except JobError as e:
            raise bad_request(str(e)) from e


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: int, eng: Engine) -> dict[str, Any]:
    with eng.db() as s:
        _job_or_404(s, job_id)
        try:
            return job(JobRunner(None, s.repos).cancel(job_id))
        except JobError as e:
            raise bad_request(str(e)) from e


def _resumable(eng: EngineState, job_id: int) -> None:
    thread = eng.job_thread(job_id)
    if thread is not None and thread.is_alive():
        raise bad_request(f"İş #{job_id} zaten çalışıyor")


@dataclass(frozen=True)
class _ContinuePayload:
    provider: _Provider
    pages: tuple[int, ...]  # exactly the pages the estimate covered (0-based)


def _continue_pages(current: JobRow, failed_only: bool) -> list[int]:
    return sorted(current.failed) if failed_only else current.remaining


def _job_plan_estimate(
    eng: EngineState, job_id: int, operation: str, *, failed_only: bool
) -> dict[str, Any]:
    _resumable(eng, job_id)
    with eng.db() as s:
        current = _job_or_404(s, job_id)
        if current.status in FINISHED and current.status != "failed":
            raise bad_request(f"İş #{job_id} zaten bitti ({current.status})")
        only = _continue_pages(current, failed_only)
        if not only:
            what = "hatalı sayfa" if failed_only else "kalan sayfa"
            raise bad_request(f"İş #{job_id}: {what} yok")
        p = _job_provider(eng, current.provider, current.model)
        svc, t = _service(eng, s, p)
        ob = eng.book(s, current.book_id)
        with ob.lock:
            plan = JobRunner(svc, s.repos).plan(
                current, ob.doc, ob.meta, ob.book, profile=_profile(s, ob.book.id, t), only=only
            )
    token = eng.confirm.issue(operation, f"job:{job_id}", _ContinuePayload(p, tuple(only)))
    warnings = (
        [BUDGET_NO_PRICE]
        if current.budget_usd is not None and not plan.estimate.price_known
        else []
    )
    return _plan_estimate(eng, token, operation, plan, p, t, warnings)


def _job_continue(
    eng: EngineState, job_id: int, token: str | None, operation: str, *, failed_only: bool
) -> dict[str, Any]:
    """Run exactly the confirmed pages; refuse if the job's page set changed since the
    estimate (409 expired_token → the app asks for a new estimate)."""
    _resumable(eng, job_id)
    with eng.job_slot() as start:
        payload: _ContinuePayload = eng.confirm.take(token, operation, f"job:{job_id}")
        with eng.db() as s:
            current = _job_or_404(s, job_id)
            if tuple(_continue_pages(current, failed_only)) != payload.pages:
                raise ApiError(
                    "expired_token", "İşin sayfaları tahminden sonra değişti; yeniden tahmin al"
                )
            try:
                JobRunner(None, s.repos).prepare_continue(job_id)
            except JobError as e:
                raise bad_request(str(e)) from e
        only = list(payload.pages)
        start(job_id, lambda: _run_job(eng, job_id, payload.provider, only))
    with eng.db() as s:
        return job(_job_or_404(s, job_id))


@router.post("/jobs/{job_id}/resume/estimate")
def job_resume_estimate(job_id: int, eng: Engine) -> dict[str, Any]:
    return _job_plan_estimate(eng, job_id, "resume", failed_only=False)


@router.post("/jobs/{job_id}/resume")
def job_resume(job_id: int, body: ConfirmBody, eng: Engine) -> dict[str, Any]:
    return _job_continue(eng, job_id, body.confirm_token, "resume", failed_only=False)


@router.post("/jobs/{job_id}/retry-failed/estimate")
def job_retry_estimate(job_id: int, eng: Engine) -> dict[str, Any]:
    return _job_plan_estimate(eng, job_id, "retry", failed_only=True)


@router.post("/jobs/{job_id}/retry-failed")
def job_retry(job_id: int, body: ConfirmBody, eng: Engine) -> dict[str, Any]:
    return _job_continue(eng, job_id, body.confirm_token, "retry", failed_only=True)


# --- book profile ------------------------------------------------------------------------------


def _profile_json(profile: BookProfile) -> dict[str, Any]:
    return profile.model_dump(by_alias=True)


@router.get("/books/{book_id}/profile")
def profile_get(book_id: int, eng: Engine) -> dict[str, Any] | None:
    with eng.db() as s:
        if s.repos.books.get(book_id) is None:
            raise not_found(f"Kitap bulunamadı: #{book_id}")
        stored = s.repos.profiles.get(book_id)
        return _profile_json(stored) if stored is not None else None


@router.put("/books/{book_id}/profile")
def profile_put(book_id: int, body: dict[str, Any], eng: Engine) -> dict[str, Any]:
    try:
        profile = BookProfile.model_validate(body)
    except ValueError as e:
        raise bad_request(f"Geçersiz profil: {e}") from e
    with eng.db() as s:
        if s.repos.books.get(book_id) is None:
            raise not_found(f"Kitap bulunamadı: #{book_id}")
        s.repos.profiles.put(book_id, profile)  # never touches the translation cache
        stored = s.repos.profiles.get(book_id)
        assert stored is not None
        return _profile_json(stored)


def _profiler(eng: EngineState, s: Session) -> Profiler:
    return Profiler(s.repos, eng.settings, complete_fn=eng.complete_fn)


@router.post("/books/{book_id}/profile/analyze/estimate")
def profile_estimate(book_id: int, eng: Engine) -> dict[str, Any]:
    with eng.db() as s:
        ob: OpenBook = eng.book(s, book_id)
        plan = _profiler(eng, s).plan(
            ob.book, ob.meta, lambda pages: eng.pages(s, ob, list(pages)), eng.settings.default_lang
        )
    token = eng.confirm.issue("profile", f"book:{book_id}", plan)
    return estimate(
        token,
        "profile",
        provider="claude-cli",
        model=plan.model,
        cost=plan.estimate,
        thinking=eng.settings.thinking_level,
        thinking_extra=eng.settings.thinking_extra_output(plan.model),
        pages=plan.pages,
        expires_in=eng.confirm.ttl_s,
    )


@router.post("/books/{book_id}/profile/analyze")
def profile_analyze(book_id: int, body: ConfirmBody, eng: Engine) -> dict[str, Any]:
    with eng.ai_call():
        plan: ProfilePlan = eng.confirm.take(body.confirm_token, "profile", f"book:{book_id}")
        with eng.db() as s:
            return _profile_json(_profiler(eng, s).run(plan))


# --- "Bunu açıkla" ------------------------------------------------------------------------------


def _explanation(e: Explanation) -> dict[str, Any]:
    return {"text": e.text, "explanation": render_text(e), "model": e.model, "cached": e.cached}


def _explainer(eng: EngineState, s: Session) -> Explainer:
    return Explainer(s.conn, eng.settings, complete_fn=eng.complete_fn)


def _context(eng: EngineState, s: Session, body: ExplainEstimateBody) -> str | None:
    if body.book_id is None or body.page is None:
        return None
    ob = eng.book(s, body.book_id)
    (p,) = eng.check_pages(ob, [body.page])
    needle = " ".join(body.text.split()).casefold()
    for b in eng.pages(s, ob, [p])[p].blocks:
        if b.translatable and needle and needle in " ".join(b.text.split()).casefold():
            return b.text
    return None


@router.post("/explain/estimate")
def explain_estimate(body: ExplainEstimateBody, eng: Engine) -> dict[str, Any]:
    with eng.db() as s:
        try:
            plan = _explainer(eng, s).plan(body.text, _context(eng, s, body), body.book_id)
        except ValueError as e:
            raise bad_request(str(e)) from e
    if plan.cached is not None:
        return _explanation(plan.cached)
    assert plan.estimate is not None
    token = eng.confirm.issue("explain", "explain", plan)
    return estimate(
        token,
        "explain",
        provider="claude-cli",
        model=plan.model,
        cost=plan.estimate,
        thinking=eng.settings.thinking_level,
        thinking_extra=eng.settings.thinking_extra_output(plan.model),
        pages=[body.page - 1] if body.page else [],
        expires_in=eng.confirm.ttl_s,
    )


@router.post("/explain")
def explain(body: ConfirmBody, eng: Engine) -> dict[str, Any]:
    with eng.ai_call():
        plan: ExplainPlan = eng.confirm.take(body.confirm_token, "explain", "explain")
        with eng.db() as s:
            return _explanation(_explainer(eng, s).run(plan))

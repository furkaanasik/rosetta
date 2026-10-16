""" "Bunu açıkla": one ``claude -p`` call explains a sentence (grammar, idioms, vocabulary), cached.

Rule 1/2: ``plan`` never calls the model; ``run`` is only invoked after the user approved the
plan's estimate. A cache hit (same normalized sentence + lang + model + prompt version) is
returned by ``plan`` itself and never re-asked.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rosetta_engine.config import Settings
from rosetta_engine.errors import ProviderError
from rosetta_engine.models import CostEstimate
from rosetta_engine.store.repo import Clock, UsageRepo, UsageRow, utc_now
from rosetta_engine.translate.claude_cli import Completion, complete
from rosetta_engine.translate.estimator import estimate_tokens, usd

log = logging.getLogger(__name__)

PROVIDER = "claude-cli"
OPERATION = "explain"
PROMPT_VERSION = 1
OUTPUT_TOKENS = 700  # typical JSON answer for one sentence
MAX_CONTEXT_CHARS = 1500

LANG_NAMES = {"tr": "Turkish", "en": "English", "de": "German", "fr": "French", "es": "Spanish"}

SYSTEM_PROMPT = """\
You are an English teacher for a {target}-speaking reader of a technical book.
Explain the given English SENTENCE so the reader learns from it. Write every explanation in \
{target}; quote English words exactly as they appear. CONTEXT (if given) is only for \
understanding; do not explain it.
Answer ONLY with one JSON object:
{"ceviri": str, "yapi": str, "deyimler": [{"ifade": str, "anlam": str}], \
"kelimeler": [{"kelime": str, "anlam": str}], "notlar": str}
- ceviri: a natural {target} translation of the sentence.
- yapi: its grammatical structure (clauses, tense, voice, why it is built this way), \
3-6 short sentences.
- deyimler: idioms, phrasal verbs and fixed expressions in the sentence (empty if none).
- kelimeler: 3-8 key words with their meaning in this sentence.
- notlar: one or two learning tips, or "".
No markdown, no text outside the JSON."""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ceviri": {"type": "string"},
        "yapi": {"type": "string"},
        "deyimler": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"ifade": {"type": "string"}, "anlam": {"type": "string"}},
                "required": ["ifade", "anlam"],
            },
        },
        "kelimeler": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"kelime": {"type": "string"}, "anlam": {"type": "string"}},
                "required": ["kelime", "anlam"],
            },
        },
        "notlar": {"type": "string"},
    },
    "required": ["ceviri", "yapi", "deyimler", "kelimeler", "notlar"],
}

CompleteFn = Callable[..., Completion]


class InvalidExplanationError(ProviderError):
    """The model answered, but not with a usable explanation JSON."""


class Phrase(BaseModel):
    model_config = ConfigDict(frozen=True)

    ifade: str
    anlam: str


class Word(BaseModel):
    model_config = ConfigDict(frozen=True)

    kelime: str
    anlam: str


class ExplanationContent(BaseModel):
    """The model's answer (Turkish keys, as in the prompt)."""

    model_config = ConfigDict(frozen=True)

    ceviri: str
    yapi: str
    deyimler: list[Phrase] = Field(default_factory=list)
    kelimeler: list[Word] = Field(default_factory=list)
    notlar: str = ""


class Explanation(BaseModel):
    model_config = ConfigDict(frozen=True)

    hash: str
    text: str
    lang: str
    model: str
    explanation: ExplanationContent
    cached: bool = False
    created_at: str = ""


@dataclass(frozen=True)
class ExplainPlan:
    text: str  # normalized sentence
    context: str | None
    lang: str
    model: str
    book_id: int | None
    hash: str
    cached: Explanation | None
    estimate: CostEstimate | None  # None on a cache hit (nothing to pay)
    system_prompt: str
    user_message: str


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def explanation_hash(text: str, lang: str, model: str) -> str:
    key = "\x1f".join((normalize(text), lang, model, str(PROMPT_VERSION)))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def build_system_prompt(lang: str) -> str:
    return SYSTEM_PROMPT.replace("{target}", LANG_NAMES.get(lang, lang))


def build_user_message(text: str, context: str | None) -> str:
    parts = []
    if context:
        parts.append(f"CONTEXT:\n{context[:MAX_CONTEXT_CHARS]}")
    parts.append(f"SENTENCE:\n{text}")
    return "\n\n".join(parts)


def parse_explanation(raw: str | dict[str, Any]) -> ExplanationContent:
    """Validate the model's JSON. Raises InvalidExplanationError."""
    data: Any = raw
    if isinstance(raw, str):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw.strip())
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise InvalidExplanationError("açıklama yanıtında JSON yok")
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise InvalidExplanationError(f"açıklama JSON'u geçersiz: {e}") from e
    if not isinstance(data, dict):
        raise InvalidExplanationError("açıklama yanıtı bir JSON nesnesi değil")
    try:
        content = ExplanationContent.model_validate(data)
    except ValidationError as e:
        raise InvalidExplanationError(f"açıklama alanları geçersiz: {e.error_count()} hata") from e
    if not content.ceviri.strip() or not content.yapi.strip():
        raise InvalidExplanationError("açıklamada çeviri ya da yapı boş")
    return content


class ExplanationRepo:
    """SQL for the ``explanations`` table (migration 005)."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock = utc_now) -> None:
        self._c = conn
        self._clock = clock

    def get(self, key: str) -> Explanation | None:
        row = self._c.execute(
            "SELECT hash, text, lang, model, explanation_json, created_at "
            "FROM explanations WHERE hash = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return Explanation(
            hash=row[0],
            text=row[1],
            lang=row[2],
            model=row[3],
            explanation=ExplanationContent.model_validate_json(row[4]),
            cached=True,
            created_at=row[5],
        )

    def put(self, plan: ExplainPlan, content: ExplanationContent, done: Completion) -> str:
        now = self._clock().isoformat()
        with self._c:
            self._c.execute(
                "INSERT INTO explanations(hash, text, context, lang, model, explanation_json, "
                "input_tokens, output_tokens, cost_usd, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(hash) DO NOTHING",
                (
                    plan.hash,
                    plan.text,
                    plan.context,
                    plan.lang,
                    plan.model,
                    content.model_dump_json(),
                    done.input_tokens,
                    done.output_tokens,
                    done.cost_usd,
                    now,
                ),
            )
        return now


class Explainer:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        complete_fn: CompleteFn = complete,
        model: str | None = None,
        clock: Clock = utc_now,
    ) -> None:
        self._repo = ExplanationRepo(conn, clock)
        self._usage = UsageRepo(conn, clock)
        self._s = settings
        self._complete = complete_fn
        self.model = model or settings.explain_model

    def plan(
        self,
        sentence: str,
        context: str | None = None,
        book_id: int | None = None,
        lang: str | None = None,
    ) -> ExplainPlan:
        """Cache lookup + estimate. Never calls the model."""
        text = normalize(sentence)
        if not text:
            raise ValueError("açıklanacak cümle boş")
        target = lang or self._s.default_lang
        key = explanation_hash(text, target, self.model)
        system = build_system_prompt(target)
        message = build_user_message(text, normalize(context) if context else None)
        cached = self._repo.get(key)
        estimate: CostEstimate | None = None
        if cached is None:
            in_tok = estimate_tokens(system) + estimate_tokens(message)
            out_tok = OUTPUT_TOKENS + self._s.thinking_extra_output(self.model)
            price = self._s.price_for(self.model)
            estimate = CostEstimate(
                calls=1,
                input_tokens=in_tok,
                output_tokens=out_tok,
                usd=usd(in_tok, out_tok, price) if price is not None else 0.0,
                price_known=price is not None,
            )
        return ExplainPlan(
            text=text,
            context=normalize(context) if context else None,
            lang=target,
            model=self.model,
            book_id=book_id,
            hash=key,
            cached=cached,
            estimate=estimate,
            system_prompt=system,
            user_message=message,
        )

    def run(self, plan: ExplainPlan) -> Explanation:
        """Return the cached answer, or call the model once (+1 strict retry), validate, store."""
        if plan.cached is not None:
            return plan.cached
        again = self._repo.get(plan.hash)  # filled by another run since planning
        if again is not None:
            return again
        for strict in (False, True):
            try:
                done = self._complete(
                    plan.system_prompt,
                    plan.user_message,
                    model=plan.model,
                    settings=self._s,
                    json_schema=RESPONSE_SCHEMA if strict else None,
                )
            except ProviderError as e:
                self._record(plan, e.input_tokens, e.output_tokens, e.cost_usd, ok=False)
                raise
            try:
                raw: str | dict[str, Any] = (
                    done.structured if done.structured is not None else done.text
                )
                content = parse_explanation(raw)
            except InvalidExplanationError as e:
                self._record(plan, done.input_tokens, done.output_tokens, done.cost_usd, ok=False)
                if strict:
                    raise
                log.warning("invalid explanation JSON, retrying strict: %s", e)
                continue
            self._record(plan, done.input_tokens, done.output_tokens, done.cost_usd, ok=True)
            created = self._repo.put(plan, content, done)
            return Explanation(
                hash=plan.hash,
                text=plan.text,
                lang=plan.lang,
                model=plan.model,
                explanation=content,
                cached=False,
                created_at=created,
            )
        raise AssertionError("unreachable")  # pragma: no cover

    def _record(self, plan: ExplainPlan, i: int, o: int, cost: float, *, ok: bool) -> None:
        est = plan.estimate
        self._usage.add(
            UsageRow(
                book_id=plan.book_id,
                provider=PROVIDER,
                model=plan.model,
                operation=OPERATION,
                input_tokens=i,
                output_tokens=o,
                cost_usd=cost,
                ok=ok,
                est_input_tokens=est.input_tokens if est else None,
                est_output_tokens=est.output_tokens if est else None,
                calibrate=False,  # explain calls must not skew translation calibration
            )
        )


def render_text(e: Explanation) -> str:
    """Plain-text/markdown rendering for the CLI."""
    c = e.explanation
    lines = [f"**Cümle:** {e.text}", "", f"**Çeviri:** {c.ceviri}", "", f"**Yapı:** {c.yapi}"]
    if c.deyimler:
        lines += ["", "**Deyimler / kalıplar:**"]
        lines += [f"- {p.ifade}: {p.anlam}" for p in c.deyimler]
    if c.kelimeler:
        lines += ["", "**Kelimeler:**"]
        lines += [f"- {w.kelime}: {w.anlam}" for w in c.kelimeler]
    if c.notlar.strip():
        lines += ["", f"**Not:** {c.notlar}"]
    return "\n".join(lines)

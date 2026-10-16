"""Book profiler: TOC + a few body pages → one ``claude -p`` call → editable BookProfile.

Rule 1/2: ``plan`` never calls the model; ``run`` is only invoked after the user approved the
plan's estimate. The profile is stored per book and used by translation by default; changing it
never invalidates cached translations (user decision 4).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from rosetta_engine.config import Settings
from rosetta_engine.errors import ExtractionError, ProviderError
from rosetta_engine.extract.extractor import BookMeta
from rosetta_engine.models import Book, BookProfile, CostEstimate, PageBlocks
from rosetta_engine.store.repo import Repos, UsageRow
from rosetta_engine.translate.claude_cli import Completion, complete
from rosetta_engine.translate.estimator import estimate_tokens, usd

log = logging.getLogger(__name__)

PROVIDER = "claude-cli"
OPERATION = "profile"
MAX_SAMPLE_PAGES = 5
MIN_PAGE_CHARS = 1200  # a "meaningful" body page has at least this much translatable text
SCAN_LIMIT = 40  # pages scanned after the start page to find meaningful ones
SAMPLE_TOKEN_CAP = 6000  # page text budget
TOC_TOKEN_CAP = 1500
OUTPUT_TOKENS = 1200  # JSON with ~60 glossary terms
MAX_GLOSSARY = 120
MAX_DNT = 120

_FRONT_MATTER = re.compile(
    r"^(cover|title|copyright|praise|dedication|table of contents|contents|foreword|preface|"
    r"acknowledg|about (the|this)|how to (use|read)|who should|conventions|o'reilly|"
    r"safari|errata|index|colophon)",
    re.I,
)

SYSTEM_PROMPT = """\
You analyze a book before it is translated, to keep its terminology consistent.
You get the table of contents and sample pages. Answer ONLY with one JSON object:
{"tur": str, "ton": str, "hedef_dil": str, "cevrilmeyecek": [str], "sozluk": {str: str}, \
"kod_dili": [str]}
- tur: genre/topic in {target}, short (e.g. "yazılım / dağıtık sistemler").
- ton: tone/register to use in {target}, short.
- hedef_dil: "{lang}".
- cevrilmeyecek: product, tool, protocol and proper names that must stay in English \
(e.g. Kafka, PostgreSQL, JSON). Only names that occur in the book.
- sozluk: 20-60 recurring technical terms from the book (English, lowercase unless a proper \
noun) mapped to the established {target} equivalent used in the field.
- kod_dili: programming/query languages that appear in code samples.
No explanations, no markdown."""

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tur": {"type": "string"},
        "ton": {"type": "string"},
        "hedef_dil": {"type": "string"},
        "cevrilmeyecek": {"type": "array", "items": {"type": "string"}},
        "sozluk": {"type": "object", "additionalProperties": {"type": "string"}},
        "kod_dili": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["tur", "ton", "hedef_dil", "cevrilmeyecek", "sozluk", "kod_dili"],
}

LANG_NAMES = {"tr": "Turkish", "en": "English", "de": "German", "fr": "French", "es": "Spanish"}

CompleteFn = Callable[..., Completion]
LoadPages = Callable[[Sequence[int]], dict[int, PageBlocks]]


class InvalidProfileError(ProviderError):
    """The model answered, but not with a usable profile JSON."""


@dataclass(frozen=True)
class ProfilePlan:
    book: Book
    lang: str
    model: str
    pages: list[int]  # 0-based sample pages
    toc_entries: int
    system_prompt: str
    user_message: str
    estimate: CostEstimate


def _is_front_matter(title: str) -> bool:
    return bool(_FRONT_MATTER.match(title.strip()))


def start_page(meta: BookMeta) -> int:
    """0-based page where the body starts: first top-level TOC entry that isn't front matter."""
    tops = [e for e in meta.toc if e.level == min((t.level for t in meta.toc), default=1)]
    for entry in tops:
        if not _is_front_matter(entry.title) and entry.page >= 1:
            return entry.page - 1
    return max(0, meta.page_count // 20)  # no usable TOC: skip ~5% front matter


def page_text(page: PageBlocks) -> str:
    return "\n\n".join(b.text for b in page.blocks if b.translatable and b.text.strip())


def toc_text(meta: BookMeta) -> str:
    lines: list[str] = []
    used = 0
    for e in meta.toc:
        if e.level > 2:
            continue
        line = f"{'  ' * (e.level - 1)}{e.title}"
        used += estimate_tokens(line) + 1
        if used > TOC_TOKEN_CAP:
            lines.append("…")
            break
        lines.append(line)
    return "\n".join(lines)


def select_pages(meta: BookMeta, load_pages: LoadPages) -> dict[int, str]:
    """Up to MAX_SAMPLE_PAGES meaningful body pages (0-based → text), within the token cap."""
    first = start_page(meta)
    out: dict[int, str] = {}
    used = 0
    for p in range(first, min(meta.page_count, first + SCAN_LIMIT)):
        try:
            page = load_pages([p])[p]
        except ExtractionError:
            continue  # scanned/blank page: skip
        text = page_text(page)
        if len(text) < MIN_PAGE_CHARS:
            continue
        tok = estimate_tokens(text)
        if out and used + tok > SAMPLE_TOKEN_CAP:
            break
        out[p] = text
        used += tok
        if len(out) >= MAX_SAMPLE_PAGES:
            break
    return out


def build_system_prompt(lang: str) -> str:
    return SYSTEM_PROMPT.replace("{target}", LANG_NAMES.get(lang, lang)).replace("{lang}", lang)


def build_user_message(title: str, toc: str, samples: dict[int, str]) -> str:
    parts = [f"TITLE: {title}"]
    if toc:
        parts.append(f"TABLE OF CONTENTS:\n{toc}")
    for p, text in sorted(samples.items()):
        parts.append(f"SAMPLE PAGE {p + 1}:\n{text}")
    return "\n\n".join(parts)


def parse_profile(raw: str | dict[str, Any], lang: str) -> BookProfile:
    """Validate the model's JSON into a BookProfile (Turkish keys). Raises InvalidProfileError."""
    data: Any = raw
    if isinstance(raw, str):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw.strip())
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise InvalidProfileError("profil yanıtında JSON yok")
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as e:
            raise InvalidProfileError(f"profil JSON'u geçersiz: {e}") from e
    if not isinstance(data, dict):
        raise InvalidProfileError("profil yanıtı bir JSON nesnesi değil")
    glossary = data.get("sozluk", {})
    dnt = data.get("cevrilmeyecek", [])
    if not isinstance(glossary, dict) or not isinstance(dnt, list):
        raise InvalidProfileError("sozluk bir nesne, cevrilmeyecek bir liste olmalı")
    cleaned = {
        "tur": data.get("tur", ""),
        "ton": data.get("ton", ""),
        "hedef_dil": lang,
        "cevrilmeyecek": [t.strip() for t in dnt if isinstance(t, str) and t.strip()][:MAX_DNT],
        "sozluk": {
            k.strip(): v.strip()
            for k, v in list(glossary.items())[:MAX_GLOSSARY]
            if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip()
        },
        "kod_dili": data.get("kod_dili", []),
    }
    try:
        return BookProfile.model_validate(cleaned)
    except ValidationError as e:
        raise InvalidProfileError(f"profil alanları geçersiz: {e.error_count()} hata") from e


class Profiler:
    def __init__(
        self,
        repos: Repos,
        settings: Settings,
        complete_fn: CompleteFn = complete,
        model: str | None = None,
    ) -> None:
        self._r = repos
        self._s = settings
        self._complete = complete_fn
        self.model = model or settings.model

    def plan(self, book: Book, meta: BookMeta, load_pages: LoadPages, lang: str) -> ProfilePlan:
        """Pick input pages and estimate the call. Never calls the model."""
        samples = select_pages(meta, load_pages)
        system = build_system_prompt(lang)
        message = build_user_message(book.title, toc_text(meta), samples)
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
        return ProfilePlan(
            book=book,
            lang=lang,
            model=self.model,
            pages=sorted(samples),
            toc_entries=len(meta.toc),
            system_prompt=system,
            user_message=message,
            estimate=estimate,
        )

    def run(self, plan: ProfilePlan) -> BookProfile:
        """Call the model once (plus one strict retry on invalid JSON), validate, store."""
        profile: BookProfile | None = None
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
                profile = parse_profile(raw, plan.lang)
            except InvalidProfileError as e:
                self._record(plan, done.input_tokens, done.output_tokens, done.cost_usd, ok=False)
                if strict:
                    raise
                log.warning("invalid profile JSON, retrying strict: %s", e)
                continue
            self._record(plan, done.input_tokens, done.output_tokens, done.cost_usd, ok=True)
            break
        assert profile is not None
        self._r.profiles.put(plan.book.id, profile)
        return profile

    def _record(self, plan: ProfilePlan, i: int, o: int, cost: float, *, ok: bool) -> None:
        self._r.usage.add(
            UsageRow(
                book_id=plan.book.id,
                provider=PROVIDER,
                model=plan.model,
                operation=OPERATION,
                input_tokens=i,
                output_tokens=o,
                cost_usd=cost,
                ok=ok,
                est_input_tokens=plan.estimate.input_tokens,
                est_output_tokens=plan.estimate.output_tokens,
                calibrate=False,  # profile calls must not skew translation calibration
            )
        )

"""System prompt and user message for the translation call."""

from __future__ import annotations

import json
import re
from typing import Any

from rosetta_engine.models import BookProfile
from rosetta_engine.translate.base import TranslationItem, TranslationRequest

PROMPT_VERSION = 4

LANG_NAMES = {"tr": "Turkish", "en": "English", "de": "German", "fr": "French", "es": "Spanish"}

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "s": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                },
                "required": ["id", "s"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}
RESPONSE_SCHEMA_JSON = json.dumps(RESPONSE_SCHEMA, separators=(",", ":"))


def build_system_prompt(lang: str) -> str:
    target = LANG_NAMES.get(lang, lang)
    return (
        f"You translate English book text into {target}. Rules:\n"
        "- Preserve meaning, tone and technical precision. Write natural, fluent prose with "
        f"natural {target} word order; avoid word-for-word calques.\n"
        "- Preserve meaning precisely: never invert or alter sentiment or negation; when "
        "unsure, stay closer to the source. Do not add English glosses in parentheses "
        "unless the source has them.\n"
        "- When the source spells out an abbreviation (e.g. 'software as a service (SaaS)'), "
        "translate the expansion and keep the abbreviation in parentheses; never drop either.\n"
        "- Translate everything else too, including epigraphs and attribution lines "
        '(e.g. "—Name, interview with X (2005)"): only proper names, titles of works, '
        "citations and code stay as-is.\n"
        "- Use the GLOSSARY renderings when given. Keep DO_NOT_TRANSLATE terms, text inside "
        "`backticks`, class/method names, URLs, numbers and bracketed citations like [6] "
        "exactly as written.\n"
        '- Each item has "s", a list of sentences. Return the same number of sentences, '
        "translated one-to-one, in order. Never merge or split sentences.\n"
        '- Items with "k":"h" are headings: translate them in heading style.\n'
        "- CONTEXT is for reference only: do not translate it or include it.\n"
        'Output ONLY JSON, no prose or code fences: {"items":[{"id":<int>,"s":[<str>,...]}]} '
        "with every input id exactly once."
    )


def _batch_text(request: TranslationRequest) -> str:
    return "\n".join(s for item in request.items for s in item.sentences).lower()


def _mentions(term: str, batch_text: str) -> bool:
    """Whole-word/phrase, case-insensitive: "set" does not match "dataset"."""
    return re.search(rf"(?<!\w){re.escape(term.lower())}(?!\w)", batch_text) is not None


def _profile_section(profile: BookProfile, batch_text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if profile.genre:
        out["genre"] = profile.genre
    if profile.tone:
        out["tone"] = profile.tone
    if profile.code_languages:
        out["code_languages"] = profile.code_languages
    dnt = [t for t in profile.do_not_translate if t and _mentions(t, batch_text)]
    if dnt:
        out["DO_NOT_TRANSLATE"] = dnt
    glossary = {k: v for k, v in profile.glossary.items() if k and _mentions(k, batch_text)}
    if glossary:
        out["GLOSSARY"] = glossary
    return out


def _item_json(item: TranslationItem) -> dict[str, Any]:
    d: dict[str, Any] = {"id": item.id, "s": item.sentences}
    if item.kind == "h":
        d["k"] = "h"
    return d


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def build_user_message(request: TranslationRequest) -> str:
    parts: list[str] = []
    profile = _profile_section(request.profile, _batch_text(request))
    if profile:
        parts.append("PROFILE:\n" + _dumps(profile))
    if request.context:
        parts.append("CONTEXT (do not translate):\n" + "\n".join(request.context))
    parts.append("ITEMS:\n" + _dumps([_item_json(i) for i in request.items]))
    return "\n\n".join(parts)

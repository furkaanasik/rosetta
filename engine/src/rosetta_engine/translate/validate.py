"""Parse and validate the model's JSON answer; anything else is rejected."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from rosetta_engine.errors import InvalidTranslationError
from rosetta_engine.translate.base import ParsedItem

log = logging.getLogger(__name__)

_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_BACKTICK = re.compile(r"(`+)(.+?)\1")


def _load(raw: str) -> Any:
    text = _FENCE.sub("", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise InvalidTranslationError("no JSON object in response", raw)
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise InvalidTranslationError(f"invalid JSON: {e.msg}", raw) from e


def backtick_spans(text: str) -> list[str]:
    return [m.group(2) for m in _BACKTICK.finditer(text)]


def parse_response(
    raw: str | dict[str, Any],
    expected: dict[int, int],
    sources: dict[int, list[str]] | None = None,
) -> dict[int, ParsedItem]:
    """``expected`` maps item id → source sentence count."""
    raw_text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    data = _load(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise InvalidTranslationError("missing 'items' list", raw_text)

    out: dict[int, ParsedItem] = {}
    for entry in data["items"]:
        if not isinstance(entry, dict):
            raise InvalidTranslationError("item is not an object", raw_text)
        item_id, sents = entry.get("id"), entry.get("s")
        if not isinstance(item_id, int) or isinstance(item_id, bool):
            raise InvalidTranslationError("item id is not an int", raw_text)
        if item_id in out:
            raise InvalidTranslationError(f"duplicate id {item_id}", raw_text)
        if item_id not in expected:
            raise InvalidTranslationError(f"unexpected id {item_id}", raw_text)
        if (
            not isinstance(sents, list)
            or not sents
            or not all(isinstance(s, str) and s.strip() for s in sents)
        ):
            raise InvalidTranslationError(f"id {item_id}: 's' must be non-empty strings", raw_text)
        out[item_id] = ParsedItem(
            id=item_id, sentences=list(sents), aligned=len(sents) == expected[item_id]
        )

    missing = sorted(set(expected) - set(out))
    if missing:
        raise InvalidTranslationError(f"missing ids {missing}", raw_text)

    if sources:
        for item_id, src in sources.items():
            if item_id not in out:
                continue
            joined = " ".join(out[item_id].sentences)
            lost = [c for c in backtick_spans(" ".join(src)) if c not in joined]
            if lost:
                log.warning("item %d: inline code not preserved: %s", item_id, lost)
    return out

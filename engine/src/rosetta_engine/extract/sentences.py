"""Rule-based English sentence splitter (no pysbd). Never splits inside `code`."""

from __future__ import annotations

import re

ABBREVIATIONS = frozenset(
    a.lower()
    for a in (
        "e.g.", "i.e.", "etc.", "vs.", "cf.", "Fig.", "Figs.", "Eq.", "Ch.", "Sec.", "No.",
        "Vol.", "al.", "Mr.", "Ms.", "Dr.", "Inc.", "Ltd.", "approx.",
    )
)  # fmt: skip

_CODE = re.compile(r"``.+?``|`[^`]+`")
_BOUNDARY = re.compile(r"[.!?][\"”’)\]]*\s+(?=[A-Z0-9“\"‘'`(\[\x00])")
_CITATION = re.compile(r"^(\[\d+(?:\s*[,–-]\s*\d+)*\]\s*)+")
_LABEL = re.compile(r"^(Figure|Fig\.|Table|Listing|Example)\s+[\dA-Z]+[-.\d]*\.?$")
_INITIALS = re.compile(r"^(?:[A-Za-z]\.)+$")
_PLACEHOLDER = "\x00{}\x01"


def _protect(text: str) -> tuple[str, list[str]]:
    saved: list[str] = []

    def repl(m: re.Match[str]) -> str:
        saved.append(m.group(0))
        return _PLACEHOLDER.format(len(saved) - 1)

    return _CODE.sub(repl, text), saved


def _restore(text: str, saved: list[str]) -> str:
    for i, s in enumerate(saved):
        text = text.replace(_PLACEHOLDER.format(i), s)
    return text


def _is_abbreviation(before: str) -> bool:
    words = before.split()
    if not words:
        return False
    last = words[-1].lstrip("(“\"'")
    return last.lower() in ABBREVIATIONS or bool(_INITIALS.match(last))


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    protected, saved = _protect(text)
    out: list[str] = []
    start = 0
    for m in _BOUNDARY.finditer(protected):
        end = m.end()
        chunk = protected[start:end]
        if _is_abbreviation(protected[start : m.start() + 1]):
            continue
        out.append(chunk.strip())
        start = end
    out.append(protected[start:].strip())
    out = [s for s in out if s]

    merged: list[str] = []
    for s in out:
        if merged and _LABEL.match(_restore(merged[-1], saved)):  # "Figure 3-1." + caption
            merged[-1] = f"{merged[-1]} {s}"
            continue
        cit = _CITATION.match(s)
        if merged and cit:  # "[12]" belongs to the previous sentence
            merged[-1] = f"{merged[-1]} {cit.group(0).strip()}"
            s = s[cit.end() :].strip()
            if not s:
                continue
        merged.append(s)
    return [_restore(s, saved) for s in merged]

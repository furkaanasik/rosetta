"""Text normalization: line joining with conservative de-hyphenation, ligatures, whitespace,
inline code backticks and superscript footnote markers."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}
HYPHENS = ("-", "\u2010")  # ASCII hyphen-minus, Unicode hyphen
UNICODE_HYPHEN = "\u2010"
ASCII_HYPHEN = "-"
SOFT_HYPHEN = "\u00ad"
NBSP = "\u00a0"

_SPACE = re.compile(r"[ \t\r\n\f\v]+")
_HYPHEN_WORD = re.compile(r"([^\W\d_]+)[-\u2010]$")


@dataclass(frozen=True)
class Seg:
    """A run of text inside one line."""

    text: str
    mono: bool = False
    superscript: bool = False


def normalize_chars(s: str) -> str:
    for k, v in LIGATURES.items():
        s = s.replace(k, v)
    return s.replace(SOFT_HYPHEN, "").replace(NBSP, " ")


def clean_text(s: str) -> str:
    return _SPACE.sub(" ", normalize_chars(s)).strip()


def _joiner(prev: str, nxt: str, soft: str = ASCII_HYPHEN) -> tuple[str, str]:
    """Return (prev adjusted, separator) for joining two lines.

    ``soft`` is the character the book uses for line-break hyphenation. Books that typeset
    breaks with U+2010 keep ASCII hyphens at line ends (real compounds: "analysis-friendly").
    """
    prev = prev.rstrip()
    nxt = nxt.lstrip()
    if prev.endswith(HYPHENS):
        m = _HYPHEN_WORD.search(prev)
        breakable = prev.endswith(UNICODE_HYPHEN) or soft == ASCII_HYPHEN
        if breakable and m and len(m.group(1)) >= 3 and nxt[:1].islower():
            return prev[:-1], ""
        return prev, ""
    return prev, " "


def join_lines(lines: Sequence[str], soft: str = ASCII_HYPHEN) -> str:
    out = ""
    for line in lines:
        if not line.strip():
            continue
        if not out:
            out = line.strip()
            continue
        out, sep = _joiner(out, line, soft)
        out = out + sep + line.strip()
    return clean_text(out)


def _wrap_code(code: str) -> str:
    if "`" in code:
        pad = " " if code.startswith("`") or code.endswith("`") else ""
        return f"``{pad}{code}{pad}``"
    return f"`{code}`"


def inline_text(lines: Sequence[Sequence[Seg]], soft: str = ASCII_HYPHEN) -> str:
    """Join lines of segments into one paragraph string; monospace runs become `code`,
    superscript digits become ``[^n]``."""
    segs: list[Seg] = []
    for line in lines:
        line = [s for s in line if s.text]
        if not line or not "".join(s.text for s in line).strip():
            continue
        line = [Seg(line[0].text.lstrip(), line[0].mono, line[0].superscript), *line[1:]]
        if segs:
            last = segs[-1]
            prev, sep = _joiner(last.text, line[0].text, soft)
            segs[-1] = Seg(prev, last.mono, last.superscript)
            if sep:
                segs.append(Seg(sep, mono=last.mono and line[0].mono))
        segs.extend(line)

    # merge runs with the same style
    runs: list[Seg] = []
    for s in segs:
        if runs and runs[-1].mono == s.mono and runs[-1].superscript == s.superscript:
            runs[-1] = Seg(runs[-1].text + s.text, s.mono, s.superscript)
        else:
            runs.append(s)

    parts: list[str] = []
    for r in runs:
        if r.superscript and r.text.strip().isdigit():
            parts.append(f"[^{r.text.strip()}]")
        elif r.mono and r.text.strip():
            text = normalize_chars(r.text)
            lead = text[: len(text) - len(text.lstrip())]
            trail = text[len(text.rstrip()) :]
            parts.append(f"{' ' if lead else ''}{_wrap_code(text.strip())}{' ' if trail else ''}")
        else:
            parts.append(_SPACE.sub(" ", normalize_chars(r.text)))
    return _SPACE.sub(" ", "".join(parts)).strip() if not _has_code(parts) else _squeeze(parts)


def _has_code(parts: Sequence[str]) -> bool:
    return any(p.lstrip().startswith("`") for p in parts)


def _squeeze(parts: Sequence[str]) -> str:
    """Collapse whitespace outside code spans only."""
    out: list[str] = []
    for p in parts:
        stripped = p.strip()
        if stripped.startswith("`") and stripped.endswith("`"):
            out.append(p)
        else:
            out.append(_SPACE.sub(" ", p))
    joined = "".join(out)
    return re.sub(r" {2,}(?=`)|(?<=`) {2,}", " ", joined).strip()


def detect_soft_hyphen(line_ends: Sequence[tuple[str, str]]) -> str:
    """Pick the line-break hyphen from (line end char, next line first char) samples."""
    uni = sum(1 for e, n in line_ends if e == UNICODE_HYPHEN and n.islower())
    asc = sum(1 for e, n in line_ends if e == ASCII_HYPHEN and n.islower())
    return UNICODE_HYPHEN if uni > asc else ASCII_HYPHEN


def code_text(lines: Sequence[tuple[float, str]], left: float, char_width: float) -> str:
    """Rebuild a code block. ``lines`` are (x0, raw text); missing leading whitespace is
    reconstructed from the x offset relative to ``left``."""
    out: list[str] = []
    for x0, raw in lines:
        text = normalize_chars(raw).rstrip()
        if text and not text[0].isspace() and char_width > 0:
            indent = round((x0 - left) / char_width)
            if indent > 0:
                text = " " * indent + text
        out.append(text)
    return "\n".join(out)

"""Font name heuristics: monospace, bold, italic and family detection."""

from __future__ import annotations

import re

from rosetta_engine.models import FontFamily

FLAG_SUPERSCRIPT = 1
FLAG_ITALIC = 2
FLAG_SERIF = 4
FLAG_MONO = 8
FLAG_BOLD = 16

MONO_PATTERNS = re.compile(
    r"(mono|courier|consolas|menlo|monaco|inconsolata|source ?code|fira ?code|jetbrains"
    r"|lucida ?console|andale|cmtt|lmmono|sfmono|letter ?gothic)",
    re.I,
)
BOLD_PATTERNS = re.compile(r"(bold|black|heavy|semibold|demi)", re.I)
ITALIC_PATTERNS = re.compile(r"(italic|oblique|It$)")
SANS_PATTERNS = re.compile(
    r"(sans|myriad|helvetica|arial|gilroy|frutiger|futura|verdana|segoe|roboto|lato|calibri"
    r"|gill|univers|\bdin|guardian|tahoma|trebuchet|avenir|proxima|inter\b|ubuntu(?!mono))",
    re.I,
)

_SUBSET = re.compile(r"^[A-Z]{6}\+")


def strip_subset(font: str) -> str:
    """``"ABCDEF+Courier-Bold"`` -> ``"Courier-Bold"``."""
    return _SUBSET.sub("", font)


def is_monospace(font: str, flags: int = 0) -> bool:
    return bool(flags & FLAG_MONO) or bool(MONO_PATTERNS.search(strip_subset(font)))


def is_bold(font: str, flags: int = 0) -> bool:
    return bool(flags & FLAG_BOLD) or bool(BOLD_PATTERNS.search(strip_subset(font)))


def is_italic(font: str, flags: int = 0) -> bool:
    return bool(flags & FLAG_ITALIC) or bool(ITALIC_PATTERNS.search(strip_subset(font)))


def font_family(font: str, flags: int = 0) -> FontFamily:
    """serif/sans/mono by name. The PDF serif flag is unreliable (Myriad sets it)."""
    if is_monospace(font, flags):
        return "mono"
    if SANS_PATTERNS.search(strip_subset(font)):
        return "sans"
    return "serif"

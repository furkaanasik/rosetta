"""Book-level typography: body font size and heading size levels (one page is misleading)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

from rosetta_engine.extract.fonts import font_family, is_monospace
from rosetta_engine.extract.pdf_reader import RawPage
from rosetta_engine.models import FontFamily

MAX_SAMPLE_PAGES = 40
HEADING_RATIO = 1.15  # sizes above body*ratio are heading candidates
HEADING_MAX_SHARE = 0.05  # ...if they hold < 5% of all characters
MAX_LEVEL = 4


class TypographyStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    body_size: float
    heading_sizes: dict[float, int]  # size -> heading level (1 = largest)
    body_font_family: FontFamily = "serif"
    body_font: str = ""

    def level_for_size(self, size: float) -> int | None:
        return self.heading_sizes.get(round_size(size))


def round_size(size: float) -> float:
    return round(size * 2) / 2


def sample_pages(page_count: int, k: int = MAX_SAMPLE_PAGES) -> list[int]:
    """Evenly spaced 0-based page numbers, skipping the first 5% (cover, front matter)."""
    start = int(page_count * 0.05)
    span = page_count - start
    if span <= 0:
        return list(range(page_count))
    if span <= k:
        return list(range(start, page_count))
    step = span / k
    return sorted({start + int(i * step) for i in range(k)})


def compute_stats(pages: Iterable[RawPage]) -> TypographyStats:
    sizes: Counter[float] = Counter()
    fonts: Counter[str] = Counter()
    for page in pages:
        for block in page.text_blocks:
            for line in block.lines:
                for span in line.spans:
                    if is_monospace(span.font, span.flags):
                        continue
                    n = len(span.text.strip())
                    if n:
                        sizes[round_size(span.size)] += n
                        fonts[span.font] += n
    if not sizes:
        return TypographyStats(body_size=10.0, heading_sizes={})
    body = sizes.most_common(1)[0][0]
    total = sum(sizes.values())
    candidates = sorted(
        (s for s, n in sizes.items() if s > body * HEADING_RATIO and n / total < HEADING_MAX_SHARE),
        reverse=True,
    )
    headings = {s: min(i + 1, MAX_LEVEL) for i, s in enumerate(candidates)}
    body_font = fonts.most_common(1)[0][0]
    return TypographyStats(
        body_size=body,
        heading_sizes=headings,
        body_font_family=font_family(body_font),
        body_font=body_font,
    )

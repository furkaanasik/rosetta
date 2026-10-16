"""Token and cost estimates, calibrated against real usage."""

from __future__ import annotations

import math
from collections.abc import Sequence

from rosetta_engine.config import Price
from rosetta_engine.translate.base import TranslationRequest
from rosetta_engine.translate.prompt import build_system_prompt, build_user_message

CHARS_PER_TOKEN = 3.6
OUTPUT_RATIO = 1.35  # Turkish tokenizes more expensively than English
PER_SENTENCE_TOKENS = 4
OUTPUT_OVERHEAD_TOKENS = 10
CALIBRATION_MIN_SAMPLES = 3
CALIBRATION_WINDOW = 20
CALIBRATION_CLAMP = (0.5, 2.0)


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


SYSTEM_PROMPT_TOKENS = estimate_tokens(build_system_prompt("tr"))


def estimate_request(request: TranslationRequest) -> tuple[int, int]:
    """(input_tokens, output_tokens) for one provider call."""
    if not request.items:
        return 0, 0
    n_sent = sum(len(i.sentences) for i in request.items)
    items_tok = sum(estimate_tokens(s) for i in request.items for s in i.sentences)
    message_tok = estimate_tokens(build_user_message(request))
    input_tok = SYSTEM_PROMPT_TOKENS + max(message_tok, items_tok) + PER_SENTENCE_TOKENS * n_sent
    output_tok = (
        math.ceil(items_tok * OUTPUT_RATIO) + PER_SENTENCE_TOKENS * n_sent + OUTPUT_OVERHEAD_TOKENS
    )
    return input_tok, output_tok


def usd(input_tokens: int, output_tokens: int, price: Price) -> float:
    return input_tokens / 1e6 * price.input + output_tokens / 1e6 * price.output


def _clamp(x: float) -> float:
    lo, hi = CALIBRATION_CLAMP
    return min(max(x, lo), hi)


def calibration_factors(samples: Sequence[tuple[int, int, int, int]]) -> tuple[float, float]:
    """samples: (est_in, actual_in, est_out, actual_out), newest first. Returns (f_in, f_out)."""
    recent = [s for s in samples[:CALIBRATION_WINDOW] if s[0] > 0 and s[2] > 0]
    if len(recent) < CALIBRATION_MIN_SAMPLES:
        return 1.0, 1.0
    f_in = sum(a / e for e, a, _, _ in recent) / len(recent)
    f_out = sum(a / e for _, _, e, a in recent) / len(recent)
    return _clamp(f_in), _clamp(f_out)


def apply_calibration(
    input_tokens: int, output_tokens: int, factors: tuple[float, float]
) -> tuple[int, int]:
    return math.ceil(input_tokens * factors[0]), math.ceil(output_tokens * factors[1])

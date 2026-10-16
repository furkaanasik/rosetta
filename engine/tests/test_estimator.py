import pytest

from rosetta_engine.config import Price
from rosetta_engine.translate.base import TranslationItem, TranslationRequest
from rosetta_engine.translate.estimator import (
    SYSTEM_PROMPT_TOKENS,
    apply_calibration,
    calibration_factors,
    estimate_request,
    estimate_tokens,
    usd,
)


def test_estimate_tokens() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 36) == 10
    assert estimate_tokens("a" * 37) == 11


def test_empty_request_is_zero() -> None:
    assert estimate_request(TranslationRequest(lang="tr", items=[])) == (0, 0)


def test_known_text_in_expected_range() -> None:
    sentence = "Replication means keeping a copy of the same data on multiple machines. " * 2
    items = [TranslationItem(id=i, sentences=[sentence.strip()] * 3) for i in range(1, 11)]

    in_tok, out_tok = estimate_request(TranslationRequest(lang="tr", items=items))

    text_tok = 30 * estimate_tokens(sentence.strip())  # ~40 tok each
    assert SYSTEM_PROMPT_TOKENS < 400
    assert text_tok + SYSTEM_PROMPT_TOKENS < in_tok < text_tok * 1.4 + SYSTEM_PROMPT_TOKENS + 200
    assert text_tok * 1.35 < out_tok < text_tok * 1.35 + 200


def test_usd() -> None:
    assert usd(1_000_000, 200_000, Price(input=1.0, output=5.0)) == pytest.approx(2.0)


def test_calibration_needs_three_samples() -> None:
    assert calibration_factors([(100, 200, 100, 50), (100, 200, 100, 50)]) == (1.0, 1.0)


def test_calibration_factor_applied() -> None:
    samples = [(100, 120, 200, 180)] * 3

    f = calibration_factors(samples)

    assert f == pytest.approx((1.2, 0.9))
    assert apply_calibration(1000, 1000, f) == (1200, 900)


def test_calibration_clamped_and_windowed() -> None:
    samples = [(100, 1000, 100, 10)] * 20 + [(100, 100, 100, 100)] * 30

    assert calibration_factors(samples) == (2.0, 0.5)
    assert calibration_factors([(100, 100, 100, 100)] * 20 + [(100, 1000, 100, 10)] * 5) == (
        1.0,
        1.0,
    )

import pytest

from rosetta_engine.errors import (
    InvalidTranslationError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    UsageLimitError,
)
from rosetta_engine.translate.base import TranslationItem, TranslationRequest
from rosetta_engine.translate.fake import FakeTranslator


def _req() -> TranslationRequest:
    return TranslationRequest(
        lang="tr",
        items=[
            TranslationItem(id=1, sentences=["One.", "Two."]),
            TranslationItem(id=2, sentences=["Hi"], kind="h"),
        ],
    )


def test_prefixes_each_sentence_and_records_call() -> None:
    fake = FakeTranslator()

    res = fake.translate(_req())

    assert res.items[1].sentences == ["[TR] One.", "[TR] Two."]
    assert res.items[2].sentences == ["[TR] Hi"]
    assert res.items[1].aligned
    assert res.cost_usd == 0.0
    assert res.input_tokens > 0 and res.output_tokens > 0
    assert fake.calls == [(_req(), False)]


@pytest.mark.parametrize(
    ("mode", "exc"),
    [
        ("limit", UsageLimitError),
        ("auth", ProviderAuthError),
        ("invalid", InvalidTranslationError),
        ("unavailable", ProviderUnavailableError),
        ("error", ProviderError),
    ],
)
def test_fail_modes(mode: str, exc: type[Exception]) -> None:
    fake = FakeTranslator(fail_mode=mode)  # type: ignore[arg-type]

    with pytest.raises(exc):
        fake.translate(_req())


def test_invalid_once_then_succeeds() -> None:
    fake = FakeTranslator(fail_mode="invalid_once")

    with pytest.raises(InvalidTranslationError):
        fake.translate(_req())
    assert fake.translate(_req(), strict=True).items[1].sentences[0] == "[TR] One."


def test_fail_after_lets_first_calls_succeed() -> None:
    fake = FakeTranslator(fail_mode="limit", fail_after=1)

    fake.translate(_req())
    with pytest.raises(UsageLimitError):
        fake.translate(_req())


def test_custom_prefix() -> None:
    res = FakeTranslator(prefix="[NEW] ").translate(_req())

    assert res.items[2].sentences == ["[NEW] Hi"]


def test_invalid_reports_spent_tokens() -> None:
    with pytest.raises(InvalidTranslationError) as exc:
        FakeTranslator(fail_mode="invalid").translate(_req())

    assert exc.value.input_tokens == 100
    assert exc.value.output_tokens == 40

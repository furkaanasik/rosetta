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


def test_fake_complete_returns_profile_and_explanation_shapes() -> None:
    from rosetta_engine.explain.explainer import build_system_prompt as explain_prompt
    from rosetta_engine.profile.profiler import build_system_prompt as profile_prompt
    from rosetta_engine.translate.fake import fake_complete

    prof = fake_complete(profile_prompt("tr"), "TOC ...")
    expl = fake_complete(explain_prompt("tr"), "SENTENCE:\nData is central.", json_schema={})

    assert {"tur", "ton", "hedef_dil", "cevrilmeyecek", "sozluk", "kod_dili"} <= set(
        __import__("json").loads(prof.text)
    )
    assert expl.structured is not None and "ceviri" in expl.structured
    assert prof.cost_usd == 0.0


def test_dev_fake_translator_fails_marker_once() -> None:
    from rosetta_engine.errors import ProviderError
    from rosetta_engine.translate.base import TranslationItem, TranslationRequest
    from rosetta_engine.translate.fake import FAIL_ONCE_MARKER, DevFakeTranslator

    DevFakeTranslator._failed_marker = False
    req = TranslationRequest(
        lang="tr", items=[TranslationItem(id=1, sentences=[f"x {FAIL_ONCE_MARKER}."])]
    )
    t = DevFakeTranslator()

    with __import__("pytest").raises(ProviderError):
        t.translate(req)
    assert t.translate(req).items[1].sentences == [f"[TR] x {FAIL_ONCE_MARKER}."]


def test_dev_fake_translator_with_real_provider_name_is_read_only() -> None:
    from rosetta_engine.errors import ProviderUnavailableError
    from rosetta_engine.translate.base import TranslationItem, TranslationRequest
    from rosetta_engine.translate.fake import DevFakeTranslator

    t = DevFakeTranslator(model="sonnet", provider="claude-cli")
    req = TranslationRequest(lang="tr", items=[TranslationItem(id=1, sentences=["x."])])

    assert t.name == "claude-cli"
    with __import__("pytest").raises(ProviderUnavailableError):
        t.translate(req)

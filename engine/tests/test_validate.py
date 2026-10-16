import logging

import pytest

from rosetta_engine.errors import InvalidTranslationError
from rosetta_engine.translate.validate import backtick_spans, parse_response

EXPECTED = {1: 1, 2: 2}
VALID = '{"items":[{"id":1,"s":["Replikasyon"]},{"id":2,"s":["Bir.","İki."]}]}'


def test_valid() -> None:
    out = parse_response(VALID, EXPECTED)

    assert out[1].sentences == ["Replikasyon"]
    assert out[2].aligned


def test_code_fenced_with_prose() -> None:
    out = parse_response(f"Here you go:\n```json\n{VALID}\n```", EXPECTED)

    assert set(out) == {1, 2}


def test_dict_input() -> None:
    out = parse_response({"items": [{"id": 1, "s": ["a"]}, {"id": 2, "s": ["b", "c"]}]}, EXPECTED)

    assert out[2].sentences == ["b", "c"]


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        ('{"items":[{"id":1,"s":["a"]}]}', "missing ids"),
        ('{"items":[{"id":1,"s":["a"]},{"id":2,"s":["b"]},{"id":3,"s":["c"]}]}', "unexpected"),
        ('{"items":[{"id":1,"s":["a"]},{"id":1,"s":["a"]},{"id":2,"s":["b"]}]}', "duplicate"),
        ('{"items":[{"id":1,"s":["a"]},{"id":2,"s":"b"}]}', "non-empty"),
        ('{"items":[{"id":1,"s":["a"]},{"id":2,"s":[]}]}', "non-empty"),
        ('{"items":[{"id":1,"s":["a"]},{"id":2,"s":[3]}]}', "non-empty"),
        ('{"items":[{"id":"1","s":["a"]}]}', "not an int"),
        ('{"items": [ {"id":1,', "no JSON"),
        ('{"items":[{"id":1 "s":["a"]}]}', "invalid JSON"),
        ('{"result":"x"}', "items"),
        ("sorry, I can't", "no JSON"),
    ],
)
def test_invalid(raw: str, reason: str) -> None:
    with pytest.raises(InvalidTranslationError) as e:
        parse_response(raw, EXPECTED)

    assert reason in e.value.reason
    assert e.value.raw == raw


def test_sentence_count_mismatch_is_not_error() -> None:
    out = parse_response('{"items":[{"id":1,"s":["a"]},{"id":2,"s":["b c"]}]}', EXPECTED)

    assert out[1].aligned
    assert not out[2].aligned


def test_lost_backtick_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        parse_response(
            '{"items":[{"id":1,"s":["çağır"]}]}', {1: 1}, sources={1: ["Call `a.b()` now."]}
        )

    assert "inline code" in caplog.text


def test_kept_backtick_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        parse_response(
            '{"items":[{"id":1,"s":["`a.b()` çağır"]}]}', {1: 1}, sources={1: ["Call `a.b()`."]}
        )

    assert caplog.text == ""


def test_backtick_spans_double() -> None:
    assert backtick_spans("x `a` and ``b`c``") == ["a", "b`c"]

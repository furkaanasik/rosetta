import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from rosetta_engine import cli, config
from rosetta_engine.commands import explain as explain_cmd
from rosetta_engine.config import Settings
from rosetta_engine.errors import ProviderError, UsageLimitError
from rosetta_engine.explain.explainer import (
    Explainer,
    InvalidExplanationError,
    explanation_hash,
    parse_explanation,
    render_text,
)
from rosetta_engine.store.db import connect, migrate
from rosetta_engine.translate.claude_cli import Completion

SENTENCE = "Replication means keeping a copy of the same data on multiple machines."

ANSWER: dict[str, Any] = {
    "ceviri": "Replikasyon, aynı verinin bir kopyasını birden fazla makinede tutmak demektir.",
    "yapi": "Özne 'Replication', fiil 'means'; ardından gerund 'keeping' ile isim cümlesi gelir.",
    "deyimler": [{"ifade": "keep a copy of", "anlam": "bir kopyasını tutmak"}],
    "kelimeler": [{"kelime": "replication", "anlam": "çoğaltma, replikasyon"}],
    "notlar": "'means + -ing' kalıbı 'demektir' diye çevrilir.",
}

runner = CliRunner()


class FakeComplete:
    def __init__(self, answers: list[Any]) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, system: str, message: str, **kw: Any) -> Completion:
        self.calls.append({"system": system, "message": message, **kw})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        text = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return Completion(
            text=text, structured=None, input_tokens=500, output_tokens=400, cost_usd=0.002
        )


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    c = connect(":memory:")
    migrate(c)
    yield c
    c.close()


def _usage(conn: sqlite3.Connection) -> list[tuple[Any, ...]]:
    rows = conn.execute(
        "SELECT operation, model, ok, calibrate, input_tokens FROM usage ORDER BY id"
    ).fetchall()
    return [tuple(r) for r in rows]


# --- pure helpers -----------------------------------------------------------------------------


def test_hash_ignores_whitespace_but_not_lang_or_model() -> None:
    base = explanation_hash(SENTENCE, "tr", "haiku")

    assert explanation_hash("  " + SENTENCE.replace(" ", "\n  "), "tr", "haiku") == base
    assert explanation_hash(SENTENCE, "de", "haiku") != base
    assert explanation_hash(SENTENCE, "tr", "sonnet") != base
    assert len(base) == 32


def test_parse_accepts_fenced_json() -> None:
    c = parse_explanation("```json\n" + json.dumps(ANSWER) + "\n```")

    assert c.ceviri.startswith("Replikasyon")
    assert c.deyimler[0].ifade == "keep a copy of"


@pytest.mark.parametrize(
    "raw",
    ["no json here", "{broken", "[1, 2]", json.dumps({**ANSWER, "ceviri": " "}), '{"yapi": "x"}'],
)
def test_parse_rejects(raw: str) -> None:
    with pytest.raises(InvalidExplanationError):
        parse_explanation(raw)


def test_render_text_lists_sections() -> None:
    from rosetta_engine.explain.explainer import Explanation, ExplanationContent

    e = Explanation(
        hash="h",
        text=SENTENCE,
        lang="tr",
        model="haiku",
        explanation=ExplanationContent.model_validate(ANSWER),
    )

    out = render_text(e)

    assert "**Çeviri:**" in out
    assert "- keep a copy of: bir kopyasını tutmak" in out
    assert "**Not:**" in out


# --- Explainer ---------------------------------------------------------------------------------


def test_default_model_is_haiku(conn: sqlite3.Connection) -> None:
    assert Explainer(conn, Settings(), complete_fn=FakeComplete([])).model == "haiku"
    assert Explainer(conn, Settings(), complete_fn=FakeComplete([]), model="sonnet").model == (
        "sonnet"
    )


def test_plan_estimates_without_calling(conn: sqlite3.Connection) -> None:
    fake = FakeComplete([])
    ex = Explainer(conn, Settings(), complete_fn=fake)

    plan = ex.plan(SENTENCE, context="Some context paragraph.")

    assert fake.calls == []
    assert plan.cached is None
    assert plan.estimate is not None
    assert plan.estimate.calls == 1
    assert plan.estimate.input_tokens > 0
    assert plan.estimate.price_known
    # haiku medium thinking extra is included
    assert plan.estimate.output_tokens > Settings().thinking_extra_output("haiku")
    assert "CONTEXT:" in plan.user_message
    assert plan.user_message.endswith(SENTENCE)


def test_plan_rejects_blank(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError):
        Explainer(conn, Settings(), complete_fn=FakeComplete([])).plan("   ")


def test_run_stores_and_second_plan_is_cache_hit(conn: sqlite3.Connection) -> None:
    fake = FakeComplete([ANSWER])
    ex = Explainer(conn, Settings(), complete_fn=fake)

    first = ex.run(ex.plan(SENTENCE, book_id=None))
    again = ex.plan("  " + SENTENCE + " ")

    assert first.cached is False
    assert first.explanation.ceviri.startswith("Replikasyon")
    assert len(fake.calls) == 1
    assert fake.calls[0]["model"] == "haiku"
    assert fake.calls[0]["json_schema"] is None
    assert again.cached is not None
    assert again.cached.cached is True
    assert again.estimate is None
    assert ex.run(again) == again.cached
    assert len(fake.calls) == 1  # never re-asked


def test_usage_row_operation_explain(conn: sqlite3.Connection) -> None:
    ex = Explainer(conn, Settings(), complete_fn=FakeComplete([ANSWER]))

    ex.run(ex.plan(SENTENCE))

    assert _usage(conn) == [("explain", "haiku", 1, 0, 500)]


def test_invalid_json_retries_strict_once_then_errors(conn: sqlite3.Connection) -> None:
    fake = FakeComplete(["not json", "{still bad"])
    ex = Explainer(conn, Settings(), complete_fn=fake)

    with pytest.raises(InvalidExplanationError):
        ex.run(ex.plan(SENTENCE))

    assert [c["json_schema"] is not None for c in fake.calls] == [False, True]
    assert [r[2] for r in _usage(conn)] == [0, 0]
    assert conn.execute("SELECT COUNT(*) FROM explanations").fetchone()[0] == 0


def test_invalid_then_valid_succeeds(conn: sqlite3.Connection) -> None:
    fake = FakeComplete(["oops", ANSWER])
    ex = Explainer(conn, Settings(), complete_fn=fake)

    result = ex.run(ex.plan(SENTENCE))

    assert result.explanation.yapi
    assert [r[2] for r in _usage(conn)] == [0, 1]


def test_provider_error_records_spent_usage(conn: sqlite3.Connection) -> None:
    err = UsageLimitError("limit reached", input_tokens=50, output_tokens=0, cost_usd=0.0001)
    ex = Explainer(conn, Settings(), complete_fn=FakeComplete([err]))

    with pytest.raises(UsageLimitError):
        ex.run(ex.plan(SENTENCE))

    assert _usage(conn) == [("explain", "haiku", 0, 0, 50)]


def test_explanations_never_affect_translation_calibration(conn: sqlite3.Connection) -> None:
    from rosetta_engine.store.repo import UsageRepo

    ex = Explainer(conn, Settings(), complete_fn=FakeComplete([ANSWER]))
    ex.run(ex.plan(SENTENCE))

    assert UsageRepo(conn).recent_ok("claude-cli", "haiku") == []


# --- CLI ---------------------------------------------------------------------------------------


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(explain_cmd, "_which", lambda _name: "/usr/bin/claude")
    return tmp_path


def _fake(monkeypatch: pytest.MonkeyPatch, answers: list[Any]) -> FakeComplete:
    fake = FakeComplete(answers)
    monkeypatch.setattr(explain_cmd, "_complete_fn", fake)
    return fake


def _db_usage() -> list[tuple[Any, ...]]:
    c = connect(config.db_path())
    try:
        return _usage(c)
    finally:
        c.close()


def test_cli_decline_makes_no_call(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake(monkeypatch, [ANSWER])

    result = runner.invoke(cli.app, ["explain", SENTENCE], input="n\n")

    assert result.exit_code == cli.EXIT_CANCELLED
    assert "Tahmin (claude-cli / haiku)" in result.output
    assert fake.calls == []


def test_cli_non_tty_without_yes_refuses(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake(monkeypatch, [ANSWER])
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)

    result = runner.invoke(cli.app, ["explain", SENTENCE])

    assert result.exit_code == cli.EXIT_CANCELLED
    assert fake.calls == []


def test_cli_confirm_then_cache_hit(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake(monkeypatch, [ANSWER])

    first = runner.invoke(cli.app, ["explain", SENTENCE], input="y\n")
    second = runner.invoke(cli.app, ["explain", SENTENCE])  # no input needed: cached

    assert first.exit_code == 0, first.output
    assert "Replikasyon" in first.output
    assert second.exit_code == 0, second.output
    assert "Cache'ten" in second.output
    assert "Tahmin" not in second.output
    assert len(fake.calls) == 1
    assert [r[0] for r in _db_usage()] == ["explain"]


def test_cli_model_override(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake(monkeypatch, [ANSWER])

    result = runner.invoke(cli.app, ["explain", SENTENCE, "--model", "sonnet", "--yes"])

    assert result.exit_code == 0, result.output
    assert fake.calls[0]["model"] == "sonnet"


def test_cli_missing_claude_exits_before_call(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake(monkeypatch, [ANSWER])
    monkeypatch.setattr(explain_cmd, "_which", lambda _name: None)

    result = runner.invoke(cli.app, ["explain", SENTENCE, "--yes"])

    assert result.exit_code == 1
    assert "claude CLI bulunamadı" in result.output
    assert fake.calls == []


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (UsageLimitError("usage limit reached"), cli.EXIT_USAGE_LIMIT),
        (ProviderError("boom"), 1),
    ],
)
def test_cli_provider_errors_map_to_exit_codes(
    env: Path, monkeypatch: pytest.MonkeyPatch, error: Exception, code: int
) -> None:
    _fake(monkeypatch, [error])

    result = runner.invoke(cli.app, ["explain", SENTENCE, "--yes"])

    assert result.exit_code == code


def test_cli_other_exit_codes(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from rosetta_engine.errors import (
        BudgetExceededError,
        ProviderAuthError,
        ProviderUnavailableError,
    )

    for error, code in (
        (ProviderAuthError("not logged in"), cli.EXIT_AUTH),
        (BudgetExceededError("budget"), cli.EXIT_BUDGET),
        (ProviderUnavailableError("gone"), cli.EXIT_UNAVAILABLE),
    ):
        _fake(monkeypatch, [error])
        result = runner.invoke(cli.app, ["explain", SENTENCE, "--yes"])
        assert result.exit_code == code, (error, result.output)


def test_cli_invalid_json_twice_exits_1(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _fake(monkeypatch, ["bad", "bad"])

    result = runner.invoke(cli.app, ["explain", SENTENCE, "--yes"])

    assert result.exit_code == 1
    assert len(fake.calls) == 2


def test_cli_book_context(env: Path, monkeypatch: pytest.MonkeyPatch, book_pdf: Path) -> None:
    fake = _fake(monkeypatch, [ANSWER])
    sentence = "There are several reasons why you might want to replicate data."

    result = runner.invoke(
        cli.app, ["explain", sentence, "--book", str(book_pdf), "--page", "1", "--yes"]
    )

    assert result.exit_code == 0, result.output
    message = fake.calls[0]["message"]
    assert message.startswith("CONTEXT:\nReplication means keeping a copy")
    assert message.endswith(sentence)
    db = connect(config.db_path())
    try:
        rows = db.execute("SELECT book_id FROM usage").fetchall()
    finally:
        db.close()
    assert rows[0][0] is not None


def test_cli_book_requires_page(env: Path, monkeypatch: pytest.MonkeyPatch, book_pdf: Path) -> None:
    fake = _fake(monkeypatch, [ANSWER])

    result = runner.invoke(cli.app, ["explain", SENTENCE, "--book", str(book_pdf), "--yes"])

    assert result.exit_code == cli.EXIT_CANCELLED
    assert fake.calls == []


def test_cli_page_out_of_range(env: Path, monkeypatch: pytest.MonkeyPatch, book_pdf: Path) -> None:
    fake = _fake(monkeypatch, [ANSWER])

    result = runner.invoke(
        cli.app, ["explain", SENTENCE, "--book", str(book_pdf), "--page", "99", "--yes"]
    )

    assert result.exit_code == 1
    assert "out of range" in result.output
    assert fake.calls == []


def test_strip_controls_removes_terminal_escapes() -> None:
    from rosetta_engine.textsafe import strip_controls

    raw = "ok\x1b[2J\x1b]0;pwned\x07 line\r\nnext\ttab\x9b31m"

    assert strip_controls(raw) == "ok[2J]0;pwned line\nnext\ttab31m"


def test_cli_never_prints_escape_sequences_from_the_model(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evil = dict(ANSWER, ceviri="Çeviri\x1b]0;pwned\x07\x1b[2J bitti")
    _fake(monkeypatch, [evil])

    result = runner.invoke(cli.app, ["explain", SENTENCE, "--yes"])

    assert result.exit_code == 0, result.output
    assert "\x1b]0;" not in result.output and "\x1b[2J" not in result.output
    assert "bitti" in result.output

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

import pytest

from rosetta_engine.config import Settings
from rosetta_engine.errors import (
    BudgetExceededError,
    InvalidTranslationError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    UsageLimitError,
)
from rosetta_engine.translate.base import TranslationItem, TranslationRequest
from rosetta_engine.translate.claude_cli import (
    ClaudeCliTranslator,
    RunResult,
    RunTimeout,
    run_subprocess,
)
from rosetta_engine.translate.prompt import RESPONSE_SCHEMA_JSON, build_system_prompt

# Shape taken from a real `claude -p --output-format json` run (claude 2.1.284).
SUCCESS = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "api_error_status": None,
    "duration_ms": 1830,
    "num_turns": 1,
    "result": '{"items":[{"id":1,"s":["Replikasyon önemlidir."]}]}',
    "session_id": "00000000-0000-0000-0000-000000000000",
    "total_cost_usd": 0.00063,
    "usage": {
        "input_tokens": 386,
        "cache_creation_input_tokens": 10,
        "cache_read_input_tokens": 4,
        "output_tokens": 25,
    },
    "modelUsage": {"claude-haiku-4-5-20251001": {"costUSD": 0.00063}},
    "terminal_reason": "completed",
}

WHICH = "rosetta_engine.translate.claude_cli.shutil.which"

REQ = TranslationRequest(
    lang="tr", items=[TranslationItem(id=1, sentences=["Replication matters."])]
)


class FakeRunner:
    def __init__(self, result: RunResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[list[str], str, float, Path, dict[str, str]]] = []

    def __call__(
        self, argv: list[str], stdin: str, timeout: float, cwd: Path, env: dict[str, str]
    ) -> RunResult:
        self.calls.append((argv, stdin, timeout, cwd, env))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture(autouse=True)
def _env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(WHICH, lambda _: "/usr/bin/claude")


def _ok(payload: dict[str, object] | None = None, rc: int = 0, stderr: str = "") -> RunResult:
    return RunResult(rc, json.dumps(payload or SUCCESS), stderr)


def _translator(runner: FakeRunner) -> ClaudeCliTranslator:
    t = ClaudeCliTranslator(runner=runner, settings=Settings(claude_timeout_s=99))
    assert t._runner is runner
    assert t._runner is not run_subprocess
    return t


def test_argv_matches_verified_command() -> None:
    runner = FakeRunner(_ok())

    _translator(runner).translate(REQ)

    argv = runner.calls[0][0]
    assert argv == [
        "claude", "-p", "--model", "sonnet", "--output-format", "json", "--tools", "",
        "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands",
        "--setting-sources", "", "--system-prompt", build_system_prompt("tr"),
        "--effort", "medium", "--max-budget-usd", "0.2500",
    ]  # fmt: skip
    assert "--bare" not in argv


def test_effort_omitted_when_unset() -> None:
    runner = FakeRunner(_ok())
    t = ClaudeCliTranslator(runner=runner, settings=Settings(claude_effort=None))

    t.translate(REQ)

    assert "--effort" not in runner.calls[0][0]


def test_effort_from_settings() -> None:
    runner = FakeRunner(_ok())
    t = ClaudeCliTranslator(runner=runner, settings=Settings(claude_effort="medium"))

    t.translate(REQ)

    argv = runner.calls[0][0]
    assert argv[argv.index("--effort") + 1] == "medium"


def test_strict_adds_json_schema() -> None:
    runner = FakeRunner(_ok())

    _translator(runner).translate(REQ, strict=True)

    assert runner.calls[0][0][-2:] == ["--json-schema", RESPONSE_SCHEMA_JSON]


def test_message_goes_to_stdin_with_timeout_and_cwd(tmp_path: Path) -> None:
    runner = FakeRunner(_ok())

    _translator(runner).translate(REQ)

    _, stdin, timeout, cwd, _ = runner.calls[0]
    assert '"Replication matters."' in stdin
    assert timeout == 99
    assert cwd == tmp_path / "data"
    assert cwd.is_dir()


def test_api_key_removed_oauth_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth")
    runner = FakeRunner(_ok())

    _translator(runner).translate(REQ)

    env = runner.calls[0][4]
    assert "ANTHROPIC_API_KEY" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth"


def test_parent_session_env_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("CLAUDE_EFFORT", "CLAUDECODE", "AI_AGENT", "CLAUDE_CODE_SESSION_ID",
                "CLAUDE_CODE_ENTRYPOINT"):  # fmt: skip
        monkeypatch.setenv(key, "x")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth")
    monkeypatch.setenv("HOME_MARKER", "kept")
    runner = FakeRunner(_ok())

    _translator(runner).translate(REQ)

    env = runner.calls[0][4]
    assert not [k for k in env if k.startswith("CLAUDE_CODE_") and k != "CLAUDE_CODE_OAUTH_TOKEN"]
    assert "CLAUDE_EFFORT" not in env
    assert "CLAUDECODE" not in env
    assert "AI_AGENT" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth"
    assert env["HOME_MARKER"] == "kept"


def test_thinking_medium_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_EFFORT", "low")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    monkeypatch.delenv("MAX_THINKING_TOKENS", raising=False)
    runner = FakeRunner(_ok())

    ClaudeCliTranslator(runner=runner, settings=Settings()).translate(REQ)

    argv, env = runner.calls[0][0], runner.calls[0][4]
    assert argv[argv.index("--effort") + 1] == "medium"
    assert "MAX_THINKING_TOKENS" not in env
    for key in ("CLAUDE_EFFORT", "CLAUDECODE", "AI_AGENT", "ANTHROPIC_API_KEY"):
        assert key not in env


def test_max_thinking_tokens_unset_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAX_THINKING_TOKENS", raising=False)
    runner = FakeRunner(_ok())

    ClaudeCliTranslator(
        runner=runner, settings=Settings(claude_max_thinking_tokens=None)
    ).translate(REQ)

    assert "MAX_THINKING_TOKENS" not in runner.calls[0][4]


def test_success_parsed() -> None:
    res = _translator(FakeRunner(_ok())).translate(REQ)

    assert res.items[1].sentences == ["Replikasyon önemlidir."]
    assert res.items[1].aligned
    assert res.input_tokens == 400
    assert res.output_tokens == 25
    assert res.cost_usd == pytest.approx(0.00063)


def test_structured_output_preferred() -> None:
    payload = {**SUCCESS, "result": "", "structured_output": {"items": [{"id": 1, "s": ["X."]}]}}

    res = _translator(FakeRunner(_ok(payload))).translate(REQ, strict=True)

    assert res.items[1].sentences == ["X."]


def test_status_429_is_usage_limit() -> None:
    payload = {**SUCCESS, "is_error": True, "api_error_status": 429, "result": "API Error"}

    with pytest.raises(UsageLimitError):
        _translator(FakeRunner(_ok(payload, rc=1))).translate(REQ)


def test_usage_limit_message() -> None:
    payload = {**SUCCESS, "is_error": True, "result": "Claude usage limit reached. resets 5pm"}

    with pytest.raises(UsageLimitError):
        _translator(FakeRunner(_ok(payload))).translate(REQ)


def test_usage_limit_in_plain_stderr() -> None:
    runner = FakeRunner(RunResult(1, "", "5-hour limit reached ∙ resets 5pm"))

    with pytest.raises(UsageLimitError):
        _translator(runner).translate(REQ)


def test_not_logged_in_is_auth_error() -> None:
    runner = FakeRunner(RunResult(1, "", "Not logged in · Please run /login"))

    with pytest.raises(ProviderAuthError, match="CLAUDE_CODE_OAUTH_TOKEN"):
        _translator(runner).translate(REQ)


def test_status_401_is_auth_error() -> None:
    payload = {**SUCCESS, "is_error": True, "api_error_status": 401, "result": "API Error"}

    with pytest.raises(ProviderAuthError):
        _translator(FakeRunner(_ok(payload, rc=1))).translate(REQ)


def test_timeout_is_provider_error() -> None:
    with pytest.raises(ProviderError, match="zaman aşımı"):
        _translator(FakeRunner(RunTimeout("t"))).translate(REQ)


def test_is_error_with_exit_zero_is_provider_error() -> None:
    payload = {**SUCCESS, "is_error": True, "subtype": "error_during_execution", "result": "boom"}

    with pytest.raises(ProviderError) as e:
        _translator(FakeRunner(_ok(payload))).translate(REQ)

    assert type(e.value) is ProviderError


def test_nonzero_exit_non_json_is_provider_error() -> None:
    with pytest.raises(ProviderError, match="JSON değil"):
        _translator(FakeRunner(RunResult(2, "garbage", "unknown option"))).translate(REQ)


def test_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WHICH, lambda _: None)
    runner = FakeRunner(_ok())

    with pytest.raises(ProviderUnavailableError, match="bulunamadı"):
        _translator(runner).translate(REQ)
    assert runner.calls == []


def test_budget_default_cap() -> None:
    runner = FakeRunner(_ok())

    _translator(runner).translate(REQ)

    argv = runner.calls[0][0]
    assert argv[argv.index("--max-budget-usd") + 1] == "0.2500"


def test_budget_absent_when_unset() -> None:
    runner = FakeRunner(_ok())
    t = ClaudeCliTranslator(runner=runner, settings=Settings(claude_max_budget_usd=None))

    t.translate(REQ)

    assert "--max-budget-usd" not in runner.calls[0][0]


def test_thinking_off_sets_zero() -> None:
    runner = FakeRunner(_ok())
    s = Settings(claude_effort="low", claude_max_thinking_tokens=0)

    ClaudeCliTranslator(runner=runner, settings=s).translate(REQ)

    assert runner.calls[0][4]["MAX_THINKING_TOKENS"] == "0"


def test_budget_from_settings() -> None:
    runner = FakeRunner(_ok())
    t = ClaudeCliTranslator(runner=runner, settings=Settings(claude_max_budget_usd=0.02))

    t.translate(REQ, strict=True)

    argv = runner.calls[0][0]
    i = argv.index("--max-budget-usd")
    assert argv[i + 1] == "0.0200"
    assert i < argv.index("--json-schema")


def test_budget_constructor_overrides_settings() -> None:
    runner = FakeRunner(_ok())
    t = ClaudeCliTranslator(
        runner=runner, settings=Settings(claude_max_budget_usd=1.0), max_budget_usd=0.005
    )

    t.translate(REQ)

    argv = runner.calls[0][0]
    assert argv[argv.index("--max-budget-usd") + 1] == "0.0050"


def test_budget_subtype_is_budget_error() -> None:
    payload = {
        **SUCCESS,
        "subtype": "error_max_budget_usd",
        "is_error": True,
        "result": "",
        "total_cost_usd": 0.021,
    }
    runner = FakeRunner(_ok(payload, rc=1))

    with pytest.raises(BudgetExceededError) as e:
        _translator(runner).translate(REQ)

    assert e.value.cost_usd == 0.021
    assert e.value.output_tokens == 25
    assert e.value.input_tokens == 400


def test_budget_word_only_in_stderr_is_not_budget_error() -> None:
    payload = {**SUCCESS, "is_error": True, "subtype": "error_during_execution", "result": "boom"}
    runner = FakeRunner(_ok(payload, stderr="warning: budget tracking unavailable"))

    with pytest.raises(ProviderError) as e:
        _translator(runner).translate(REQ)

    assert type(e.value) is ProviderError


def test_budget_message_is_budget_error() -> None:
    payload = {**SUCCESS, "is_error": True, "subtype": "error", "result": "Exceeded max budget"}
    runner = FakeRunner(_ok(payload))

    with pytest.raises(BudgetExceededError):
        _translator(runner).translate(REQ)


def test_budget_word_in_successful_translation_is_not_error() -> None:
    payload = {**SUCCESS, "result": '{"items":[{"id":1,"s":["Bütçe (budget) önemlidir."]}]}'}
    runner = FakeRunner(_ok(payload))

    result = _translator(runner).translate(REQ)

    assert result.items[1].sentences == ["Bütçe (budget) önemlidir."]


@pytest.mark.live
def test_live_single_item(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()  # real PATH lookup and default data dir
    t = ClaudeCliTranslator(model="haiku")

    res = t.translate(REQ)

    assert set(res.items) == {1}
    assert res.items[1].sentences[0].strip()
    assert res.input_tokens > 0


def test_model_defaults_to_settings_model() -> None:
    assert ClaudeCliTranslator(runner=FakeRunner(_ok()), settings=Settings()).model == "sonnet"
    haiku = ClaudeCliTranslator(runner=FakeRunner(_ok()), settings=Settings(model="haiku"))
    assert haiku.model == "haiku"


def test_debug_logging_does_not_crash_and_shows_stderr(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="rosetta_engine")
    runner = FakeRunner(_ok(stderr="note: rate hints here"))

    result = _translator(runner).translate(REQ)

    assert result.items[1].sentences == ["Replikasyon önemlidir."]
    text = caplog.text
    assert "Replication matters." in text  # request body is visible at DEBUG
    assert "note: rate hints here" in text  # stderr is in the message, not hidden in extra=


def test_all_anthropic_vars_and_inherited_thinking_stripped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                "ANTHROPIC_MODEL"):  # fmt: skip
        monkeypatch.setenv(key, "x")
    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth")
    runner = FakeRunner(_ok())

    ClaudeCliTranslator(
        runner=runner, settings=Settings(claude_max_thinking_tokens=None)
    ).translate(REQ)

    env = runner.calls[0][4]
    assert not [k for k in env if k.startswith("ANTHROPIC_")]
    assert "MAX_THINKING_TOKENS" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth"


def test_own_thinking_setting_replaces_inherited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_THINKING_TOKENS", "32000")
    runner = FakeRunner(_ok())

    ClaudeCliTranslator(runner=runner, settings=Settings(claude_max_thinking_tokens=0)).translate(
        REQ
    )

    assert runner.calls[0][4]["MAX_THINKING_TOKENS"] == "0"


def test_is_error_carries_reported_usage() -> None:
    payload = {**SUCCESS, "is_error": True, "subtype": "error_during_execution", "result": "boom"}

    with pytest.raises(ProviderError) as e:
        _translator(FakeRunner(_ok(payload))).translate(REQ)

    assert (e.value.input_tokens, e.value.output_tokens) == (400, 25)
    assert e.value.cost_usd == pytest.approx(0.00063)


def test_invalid_payload_carries_reported_usage() -> None:
    payload = {**SUCCESS, "result": "not json at all"}

    with pytest.raises(InvalidTranslationError) as e:
        _translator(FakeRunner(_ok(payload))).translate(REQ)

    assert e.value.input_tokens == 400
    assert e.value.output_tokens == 25
    assert e.value.cost_usd == pytest.approx(0.00063)


def test_usage_limit_carries_reported_usage() -> None:
    payload = {**SUCCESS, "is_error": True, "api_error_status": 429, "result": "x"}

    with pytest.raises(UsageLimitError) as e:
        _translator(FakeRunner(_ok(payload))).translate(REQ)

    assert e.value.output_tokens == 25


def test_null_usage_fields_are_zero() -> None:
    payload = {
        **SUCCESS,
        "total_cost_usd": None,
        "usage": {"input_tokens": None, "output_tokens": 7, "cache_read_input_tokens": None},
    }

    result = _translator(FakeRunner(_ok(payload))).translate(REQ)

    assert (result.input_tokens, result.output_tokens, result.cost_usd) == (0, 7, 0.0)


def test_run_subprocess_forces_utf8(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "{}", "")

    monkeypatch.setattr(subprocess, "run", fake_run)

    run_subprocess(["claude"], "ğüş", 5.0, tmp_path, {})

    assert seen["encoding"] == "utf-8"
    assert seen["errors"] == "replace"

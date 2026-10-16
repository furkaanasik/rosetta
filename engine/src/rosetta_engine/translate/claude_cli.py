"""Translator backed by the local ``claude -p`` CLI (subscription auth, never ANTHROPIC_API_KEY)."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rosetta_engine.config import Settings, data_dir, ensure_dir, load_settings
from rosetta_engine.errors import (
    BudgetExceededError,
    InvalidTranslationError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    UsageLimitError,
)
from rosetta_engine.translate.base import ProviderResult, TranslationRequest
from rosetta_engine.translate.prompt import (
    RESPONSE_SCHEMA_JSON,
    build_system_prompt,
    build_user_message,
)
from rosetta_engine.translate.validate import parse_response

log = logging.getLogger(__name__)

CLAUDE_BIN = "claude"
# Never bill the API (any ANTHROPIC_* can redirect auth/billing), and never inherit a parent
# Claude Code session's behaviour (effort, nesting, thinking budget).
STRIPPED_ENV = ("CLAUDE_EFFORT", "CLAUDECODE", "AI_AGENT", "MAX_THINKING_TOKENS")
STRIPPED_ENV_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_")
KEPT_ENV = frozenset({"CLAUDE_CODE_OAUTH_TOKEN"})

_LIMIT_RE = re.compile(r"usage limit|rate limit|limit reached|resets (at|in)|quota", re.I)
_BUDGET_RE = re.compile(r"budget", re.I)
_AUTH_RE = re.compile(r"not logged in|please run .*login|invalid api key|oauth token", re.I)
AUTH_HINT = "`claude` ile giriş yap veya `CLAUDE_CODE_OAUTH_TOKEN` ayarla"


@dataclass(frozen=True)
class RunResult:
    returncode: int
    stdout: str
    stderr: str


class RunTimeout(Exception):
    """Raised by a runner when the child process exceeds its timeout."""


# (argv, stdin, timeout_s, cwd, env) -> RunResult
Runner = Callable[[list[str], str, float, Path, dict[str, str]], RunResult]


def run_subprocess(
    argv: list[str], stdin: str, timeout_s: float, cwd: Path, env: dict[str, str]
) -> RunResult:
    try:
        proc = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
            cwd=cwd,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise RunTimeout(str(e)) from e
    return RunResult(proc.returncode, proc.stdout, proc.stderr)


def child_env(
    base: dict[str, str] | None = None, *, max_thinking_tokens: int | None = None
) -> dict[str, str]:
    env = {
        k: v
        for k, v in (os.environ if base is None else base).items()
        if k in KEPT_ENV or (k not in STRIPPED_ENV and not k.startswith(STRIPPED_ENV_PREFIXES))
    }
    if max_thinking_tokens is not None:
        env["MAX_THINKING_TOKENS"] = str(max_thinking_tokens)
    return env


def build_argv(
    model: str,
    system_prompt: str,
    *,
    strict: bool,
    effort: str | None = None,
    max_budget_usd: float | None = None,
) -> list[str]:
    argv = [
        CLAUDE_BIN, "-p",
        "--model", model,
        "--output-format", "json",
        "--tools", "",
        "--no-session-persistence",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--setting-sources", "",
        "--system-prompt", system_prompt,
    ]  # fmt: skip
    if effort:
        argv += ["--effort", effort]
    if max_budget_usd is not None:
        argv += ["--max-budget-usd", f"{max_budget_usd:.4f}"]
    if strict:
        argv += ["--json-schema", RESPONSE_SCHEMA_JSON]
    return argv


def claude_version() -> str | None:
    if shutil.which(CLAUDE_BIN) is None:
        return None
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "--version"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() or None


@dataclass(frozen=True)
class _Spent:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def kw(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _spent(payload: dict[str, Any] | None) -> _Spent:
    """Usage reported by the CLI; zeros for missing/null fields."""
    if not payload:
        return _Spent()
    usage = payload.get("usage")
    usage = usage if isinstance(usage, dict) else {}
    try:
        cost = float(payload.get("total_cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    return _Spent(
        input_tokens=_int(usage.get("input_tokens"))
        + _int(usage.get("cache_read_input_tokens"))
        + _int(usage.get("cache_creation_input_tokens")),
        output_tokens=_int(usage.get("output_tokens")),
        cost_usd=cost,
    )


def _classify(status: Any, text: str, spent: _Spent) -> None:
    """Raise the specific error for limit/auth failures; return if neither matches."""
    if status == 429 or _LIMIT_RE.search(text):
        raise UsageLimitError(f"kullanım limiti: {text.strip()[:300]}", **spent.kw())
    if status in (401, 403) or _AUTH_RE.search(text):
        raise ProviderAuthError(f"kimlik doğrulama hatası — {AUTH_HINT}", **spent.kw())


def _check_budget(payload: dict[str, Any], result_text: str, spent: _Spent) -> None:
    """Raise BudgetExceededError when the ``--max-budget-usd`` cap stopped the call.

    Only the subtype and the result text count: an unrelated stderr warning mentioning
    "budget" must not turn a different failure into a budget stop.
    """
    subtype = str(payload.get("subtype") or "")
    failed = bool(payload.get("is_error")) or subtype.startswith("error")
    if "budget" not in subtype.lower() and not (failed and _BUDGET_RE.search(result_text)):
        return
    raise BudgetExceededError(f"bütçe sınırı aşıldı ({subtype or 'budget'})", **spent.kw())


class ClaudeCliTranslator:
    name = "claude-cli"

    def __init__(
        self,
        model: str | None = None,
        runner: Runner = run_subprocess,
        settings: Settings | None = None,
        max_budget_usd: float | None = None,
    ) -> None:
        self._settings = settings or load_settings()
        self.model = model or self._settings.model
        self._runner = runner
        self._max_budget_usd = (
            max_budget_usd if max_budget_usd is not None else self._settings.claude_max_budget_usd
        )

    def translate(self, request: TranslationRequest, *, strict: bool = False) -> ProviderResult:
        if shutil.which(CLAUDE_BIN) is None:
            raise ProviderUnavailableError("claude CLI bulunamadı (PATH'te `claude` yok)")
        argv = build_argv(
            self.model,
            build_system_prompt(request.lang),
            strict=strict,
            effort=self._settings.claude_effort,
            max_budget_usd=self._max_budget_usd,
        )
        message = build_user_message(request)
        log.debug("claude request (model=%s, strict=%s):\n%s", self.model, strict, message)
        try:
            run = self._runner(
                argv,
                message,
                float(self._settings.claude_timeout_s),
                ensure_dir(data_dir()),
                child_env(max_thinking_tokens=self._settings.claude_max_thinking_tokens),
            )
        except RunTimeout as e:
            raise ProviderError(f"claude zaman aşımı ({self._settings.claude_timeout_s}s)") from e
        except OSError as e:
            raise ProviderError(f"claude çalıştırılamadı: {e}") from e

        if run.stderr.strip():
            log.warning("claude stderr: %s", run.stderr.strip()[:2000])

        try:
            payload = json.loads(run.stdout)
        except json.JSONDecodeError:
            payload = None
        if not isinstance(payload, dict):
            _classify(None, run.stdout + "\n" + run.stderr, _Spent())
            raise ProviderError(
                f"claude çıktısı JSON değil (exit {run.returncode}): {run.stderr.strip()[:300]}"
            )

        spent = _spent(payload)
        result_text = payload.get("result")
        result_str = result_text if isinstance(result_text, str) else ""
        _check_budget(payload, result_str, spent)
        if payload.get("is_error") or run.returncode != 0:
            _classify(payload.get("api_error_status"), result_str + "\n" + run.stderr, spent)
            raise ProviderError(
                f"claude hata döndü (exit {run.returncode}, "
                f"{payload.get('subtype')}): {result_str[:300]}",
                **spent.kw(),
            )
        log.debug("claude response:\n%s", result_str)

        expected = {i.id: len(i.sentences) for i in request.items}
        sources = {i.id: i.sentences for i in request.items}
        structured = payload.get("structured_output")
        raw: str | dict[str, Any] = structured if isinstance(structured, dict) else result_str
        try:
            items = parse_response(raw, expected, sources)
        except InvalidTranslationError as e:
            # The call was made and paid for; carry its usage so the service can record it.
            raise InvalidTranslationError(e.reason, e.raw, **spent.kw()) from e

        return ProviderResult(
            items=items,
            input_tokens=spent.input_tokens,
            output_tokens=spent.output_tokens,
            cost_usd=spent.cost_usd,
        )

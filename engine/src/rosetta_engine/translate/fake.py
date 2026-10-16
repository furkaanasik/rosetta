"""Free, deterministic translator for tests and end-to-end dry runs."""

from __future__ import annotations

from typing import Literal

from rosetta_engine.errors import (
    BudgetExceededError,
    InvalidTranslationError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    UsageLimitError,
)
from rosetta_engine.translate.base import (
    ParsedItem,
    ProviderResult,
    TranslationRequest,
)
from rosetta_engine.translate.estimator import estimate_request

FailMode = Literal["invalid", "invalid_once", "limit", "auth", "budget", "unavailable", "error"]


class FakeTranslator:
    """Prefixes every sentence with ``prefix``. ``fail_mode`` simulates provider failures.

    ``fail_after`` successful calls happen before ``fail_mode`` kicks in.
    """

    name = "fake"

    def __init__(
        self,
        model: str = "fake",
        fail_mode: FailMode | None = None,
        fail_after: int = 0,
        prefix: str = "[TR] ",
    ) -> None:
        self.model = model
        self.prefix = prefix
        self.fail_mode = fail_mode
        self.fail_after = fail_after
        self.calls: list[tuple[TranslationRequest, bool]] = []
        self._invalid_raised = False

    def translate(self, request: TranslationRequest, *, strict: bool = False) -> ProviderResult:
        self.calls.append((request, strict))
        if self.fail_mode is not None and len(self.calls) > self.fail_after:
            self._maybe_fail(strict)
        input_tokens, output_tokens = estimate_request(request)
        items = {
            item.id: ParsedItem(
                id=item.id, sentences=[f"{self.prefix}{s}" for s in item.sentences], aligned=True
            )
            for item in request.items
        }
        return ProviderResult(
            items=items, input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=0.0
        )

    def _maybe_fail(self, strict: bool) -> None:
        match self.fail_mode:
            case "limit":
                raise UsageLimitError("usage limit reached (fake)")
            case "budget":
                raise BudgetExceededError(
                    "budget exceeded (fake)", input_tokens=100, output_tokens=50, cost_usd=0.02
                )
            case "auth":
                raise ProviderAuthError("not logged in (fake)")
            case "unavailable":
                raise ProviderUnavailableError("claude CLI not found (fake)")
            case "error":
                raise ProviderError("provider failed (fake)", input_tokens=10, cost_usd=0.001)
            case "invalid":
                raise InvalidTranslationError(
                    "missing ids (fake)", raw="{}", input_tokens=100, output_tokens=40
                )
            case "invalid_once" if not self._invalid_raised:
                self._invalid_raised = True
                raise InvalidTranslationError(
                    "missing ids (fake)", raw="{}", input_tokens=100, output_tokens=40
                )
            case _:
                return

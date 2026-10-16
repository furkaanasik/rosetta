"""Free, deterministic translator for tests and end-to-end dry runs."""

from __future__ import annotations

import json
import time
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
from rosetta_engine.translate.claude_cli import Completion
from rosetta_engine.translate.estimator import estimate_request, estimate_tokens

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


def fake_complete(
    system_prompt: str,
    user_message: str,
    *,
    model: str | None = None,
    settings: object | None = None,
    json_schema: dict[str, object] | None = None,
    **_: object,
) -> Completion:
    """Free stand-in for ``claude_cli.complete`` (dev/E2E only): canned profile or explanation.

    Recognises the profiler and explainer system prompts; anything else gets an empty object.
    """
    if "analyze a book" in system_prompt:
        payload: dict[str, object] = {
            "tur": "yazılım / veri sistemleri",
            "ton": "teknik ama akıcı",
            "hedef_dil": "tr",
            "cevrilmeyecek": ["SQL", "JSON"],
            "sozluk": {"replication": "replikasyon", "throughput": "işlem hacmi"},
            "kod_dili": ["SQL"],
        }
    elif "English teacher" in system_prompt:
        sentence = user_message.strip().splitlines()[-1][:200]
        payload = {
            "ceviri": f"[TR] {sentence}",
            "yapi": "Sahte açıklama: ana cümle ve yan cümle.",
            "deyimler": [],
            "kelimeler": [{"kelime": "data", "anlam": "veri"}],
            "notlar": "",
        }
    else:
        payload = {}
    text = json.dumps(payload, ensure_ascii=False)
    return Completion(
        text=text,
        structured=payload if json_schema is not None else None,
        input_tokens=estimate_tokens(system_prompt + user_message),
        output_tokens=estimate_tokens(text),
        cost_usd=0.0,
    )


FAIL_ONCE_MARKER = "ROSETTA_E2E_FAIL_ONCE"


class DevFakeTranslator(FakeTranslator):
    """``rosetta serve --dev-fake-ai`` translator: optional per-call delay (to pause jobs in E2E)
    and one simulated provider error per process for any batch containing FAIL_ONCE_MARKER
    (to exercise "retry failed pages")."""

    _failed_marker = False  # process-wide: the marker fails exactly once

    def __init__(self, model: str = "fake", delay_s: float = 0.0, provider: str = "fake") -> None:
        super().__init__(model=model)
        self.delay_s = delay_s
        # Reads (page HTML, cache lookups) use the configured provider's name so existing
        # translations show; only provider "fake" may actually translate.
        self.name = provider

    def translate(self, request: TranslationRequest, *, strict: bool = False) -> ProviderResult:
        if self.name != "fake":
            raise ProviderUnavailableError(
                f"--dev-fake-ai: '{self.name}' sağlayıcısı bu modda çeviri yapamaz (yalnızca okuma)"
            )
        if self.delay_s > 0:
            time.sleep(self.delay_s)
        has_marker = any(FAIL_ONCE_MARKER in s for item in request.items for s in item.sentences)
        if has_marker and not DevFakeTranslator._failed_marker:
            DevFakeTranslator._failed_marker = True
            self.calls.append((request, strict))
            raise ProviderError("simulated provider error (dev)", input_tokens=10)
        return super().translate(request, strict=strict)

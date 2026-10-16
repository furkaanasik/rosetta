"""Translator factory: provider name → Translator."""

from __future__ import annotations

from rosetta_engine.config import Settings
from rosetta_engine.translate.base import Translator
from rosetta_engine.translate.claude_cli import ClaudeCliTranslator
from rosetta_engine.translate.deepl import DeepLTranslator
from rosetta_engine.translate.fake import FakeTranslator
from rosetta_engine.translate.ollama import OllamaTranslator

PROVIDERS = ("claude-cli", "fake", "deepl", "ollama")


class UnknownProviderError(ValueError):
    pass


def make_translator(provider: str, model: str | None, settings: Settings) -> Translator:
    if provider == "claude-cli":
        return ClaudeCliTranslator(model=model or settings.model, settings=settings)
    if provider == "fake":
        return FakeTranslator(model=model or "fake")
    if provider == "deepl":
        return DeepLTranslator(settings)
    if provider == "ollama":
        return OllamaTranslator(model, settings)
    raise UnknownProviderError(f"unknown provider {provider!r} (choices: {', '.join(PROVIDERS)})")


def supports_profile(translator: Translator) -> bool:
    """False for providers that ignore the book profile and context (e.g. DeepL)."""
    return bool(getattr(translator, "supports_profile", True))

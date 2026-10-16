"""Provider contract: a Translator turns a TranslationRequest into validated items."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from rosetta_engine.models import BookProfile

ItemKind = Literal["p", "h"]  # paragraph-like / heading


class TranslationItem(BaseModel):
    """One block sent to the LLM under a short batch-local id (1..N)."""

    model_config = ConfigDict(frozen=True)

    id: int
    sentences: list[str]
    kind: ItemKind = "p"


class TranslationRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    lang: str
    items: list[TranslationItem]
    profile: BookProfile = Field(default_factory=BookProfile)
    context: list[str] = Field(default_factory=list)  # shown to the model, never translated


class ParsedItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: int
    sentences: list[str]
    aligned: bool  # same sentence count as the source


class ProviderResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: dict[int, ParsedItem]
    input_tokens: int
    output_tokens: int
    cost_usd: float


class Translator(Protocol):
    name: str
    model: str

    def translate(self, request: TranslationRequest, *, strict: bool = False) -> ProviderResult:
        """Translate all items. ``strict=True`` is the retry mode (e.g. ``--json-schema``).

        Raises UsageLimitError, ProviderAuthError, InvalidTranslationError, ProviderError.
        """
        ...

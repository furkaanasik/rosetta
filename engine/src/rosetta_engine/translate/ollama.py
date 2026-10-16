"""Ollama provider (optional): a local model, free. Same prompt and validation as claude."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from rosetta_engine.config import Settings, load_settings
from rosetta_engine.errors import InvalidTranslationError, ProviderError, ProviderUnavailableError
from rosetta_engine.translate.base import ProviderResult, TranslationRequest
from rosetta_engine.translate.estimator import estimate_request
from rosetta_engine.translate.prompt import (
    RESPONSE_SCHEMA,
    build_system_prompt,
    build_user_message,
)
from rosetta_engine.translate.validate import parse_response

log = logging.getLogger(__name__)

MODEL_PREFIX = "ollama/"


class OllamaTranslator:
    """``model`` is stored as ``ollama/<name>`` so cache keys and pricing stay distinct."""

    name = "ollama"
    supports_profile = True

    def __init__(
        self,
        model: str | None = None,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._s = settings or load_settings()
        raw = model or self._s.ollama_model
        self.ollama_model = raw.removeprefix(MODEL_PREFIX)
        self.model = MODEL_PREFIX + self.ollama_model
        self._client = client or httpx.Client(timeout=self._s.ollama_timeout_s)

    def translate(self, request: TranslationRequest, *, strict: bool = False) -> ProviderResult:
        body: dict[str, Any] = {
            "model": self.ollama_model,
            "stream": False,
            # strict retry: full JSON schema (structured outputs); first try: plain JSON mode
            "format": RESPONSE_SCHEMA if strict else "json",
            "options": {"temperature": 0.2},
            "messages": [
                {"role": "system", "content": build_system_prompt(request.lang)},
                {"role": "user", "content": build_user_message(request)},
            ],
        }
        url = self._s.ollama_url.rstrip("/") + "/api/chat"
        try:
            r = self._client.post(url, json=body)
        except httpx.ConnectError as e:
            raise ProviderUnavailableError(
                f"Ollama'ya bağlanılamadı ({self._s.ollama_url}); `ollama serve` çalışıyor mu?"
            ) from e
        except httpx.HTTPError as e:
            raise ProviderError(f"Ollama hatası: {e}") from e
        if r.status_code == 404:
            raise ProviderUnavailableError(
                f"Ollama modeli yok: {self.ollama_model} (`ollama pull {self.ollama_model}`)"
            )
        if r.status_code >= 400:
            raise ProviderError(f"Ollama hatası {r.status_code}: {r.text[:200]}")
        data = r.json()
        content = (data.get("message") or {}).get("content", "")
        log.debug("ollama response:\n%s", content)
        est_in, est_out = estimate_request(request)
        in_tok = int(data.get("prompt_eval_count") or est_in)
        out_tok = int(data.get("eval_count") or est_out)
        expected = {i.id: len(i.sentences) for i in request.items}
        sources = {i.id: i.sentences for i in request.items}
        try:
            items = parse_response(content, expected, sources)
        except InvalidTranslationError as e:
            raise InvalidTranslationError(
                e.reason, e.raw, input_tokens=in_tok, output_tokens=out_tok
            ) from e
        return ProviderResult(items=items, input_tokens=in_tok, output_tokens=out_tok, cost_usd=0.0)

"""DeepL provider (optional). Sentence-by-sentence, so sentence alignment always holds.

DeepL has no notion of the book profile or the preceding-page context: ``supports_profile``
is False and the CLI/UI say so. Inline code (`backticks`) is replaced by ``<x id="n"/>``
placeholders (``tag_handling=xml``) and restored afterwards, so it is never translated.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable
from html import escape, unescape
from typing import Any

import httpx

from rosetta_engine.config import Settings, load_settings
from rosetta_engine.errors import (
    ProviderAuthError,
    ProviderError,
    UsageLimitError,
)
from rosetta_engine.translate.base import ParsedItem, ProviderResult, TranslationRequest
from rosetta_engine.translate.estimator import estimate_tokens, usd

log = logging.getLogger(__name__)

FREE_URL = "https://api-free.deepl.com"
PRO_URL = "https://api.deepl.com"
MAX_TEXTS_PER_CALL = 50
RETRIES_429 = 3

_CODE = re.compile(r"(`+)(.+?)\1")
_PLACEHOLDER = re.compile(r'<x id="(\d+)"\s*/>')


def protect(text: str) -> tuple[str, list[str]]:
    """Escape ``text`` for DeepL's XML mode and swap inline code for placeholders."""
    codes: list[str] = []
    out: list[str] = []
    last = 0
    for m in _CODE.finditer(text):
        out.append(escape(text[last : m.start()], quote=False))
        out.append(f'<x id="{len(codes)}"/>')
        codes.append(m.group(0))
        last = m.end()
    out.append(escape(text[last:], quote=False))
    return "".join(out), codes


def restore(text: str, codes: list[str]) -> str:
    def put(m: re.Match[str]) -> str:
        i = int(m.group(1))
        return codes[i] if i < len(codes) else ""

    return unescape(_PLACEHOLDER.sub(put, text))


class DeepLTranslator:
    name = "deepl"
    supports_profile = False

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.model = "deepl"
        self._s = settings or load_settings()
        self._client = client or httpx.Client(timeout=self._s.deepl_timeout_s)
        self._sleep = sleep

    def _key(self) -> str:
        key = os.environ.get(self._s.deepl_auth_key_env, "").strip()
        if not key:
            raise ProviderAuthError(
                f"DeepL anahtarı yok: {self._s.deepl_auth_key_env} ortam değişkenini ayarla"
            )
        return key

    def translate(self, request: TranslationRequest, *, strict: bool = False) -> ProviderResult:
        del strict  # no JSON to validate: DeepL returns one text per input text
        key = self._key()
        base = FREE_URL if key.endswith(":fx") else PRO_URL
        flat: list[tuple[int, str, list[str]]] = []
        for item in request.items:
            for sentence in item.sentences:
                protected, codes = protect(sentence)
                flat.append((item.id, protected, codes))

        out_texts: list[str] = []
        for i in range(0, len(flat), MAX_TEXTS_PER_CALL):
            chunk = [t for _, t, _ in flat[i : i + MAX_TEXTS_PER_CALL]]
            out_texts.extend(self._post(base, key, chunk, request.lang))

        items: dict[int, list[str]] = {item.id: [] for item in request.items}
        for (item_id, _, codes), text in zip(flat, out_texts, strict=True):
            items[item_id].append(restore(text, codes))

        chars = sum(len(s) for item in request.items for s in item.sentences)
        out_chars = sum(len(t) for t in out_texts)
        in_tok, out_tok = estimate_tokens("x" * chars), estimate_tokens("x" * out_chars)
        price = self._s.price_for("deepl")
        return ProviderResult(
            items={i: ParsedItem(id=i, sentences=s, aligned=True) for i, s in items.items()},
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=usd(in_tok, 0, price) if price is not None else 0.0,
        )

    def _post(self, base: str, key: str, texts: list[str], lang: str) -> list[str]:
        body: dict[str, Any] = {
            "text": texts,
            "source_lang": "EN",
            "target_lang": lang.upper(),
            "tag_handling": "xml",
            "ignore_tags": ["x"],
        }
        headers = {"Authorization": f"DeepL-Auth-Key {key}"}
        for attempt in range(RETRIES_429 + 1):
            try:
                r = self._client.post(f"{base}/v2/translate", json=body, headers=headers)
            except httpx.HTTPError as e:
                raise ProviderError(f"DeepL bağlantı hatası: {e}") from e
            if r.status_code == 429 and attempt < RETRIES_429:
                self._sleep(2.0**attempt)
                continue
            self._check(r)
            data = r.json()
            texts_out = [t["text"] for t in data.get("translations", [])]
            if len(texts_out) != len(texts):
                raise ProviderError(
                    f"DeepL {len(texts)} metin yerine {len(texts_out)} çeviri döndürdü"
                )
            return texts_out
        raise UsageLimitError("DeepL istek sınırı (429) — sonra tekrar dene")  # pragma: no cover

    @staticmethod
    def _check(r: httpx.Response) -> None:
        if r.status_code < 400:
            return
        detail = r.text[:200]
        if r.status_code in (401, 403):
            raise ProviderAuthError(f"DeepL anahtarı geçersiz ({r.status_code})")
        if r.status_code == 456:
            raise UsageLimitError("DeepL karakter kotası doldu (456)")
        if r.status_code == 429:
            raise UsageLimitError("DeepL istek sınırı (429) — sonra tekrar dene")
        raise ProviderError(f"DeepL hatası {r.status_code}: {detail}")

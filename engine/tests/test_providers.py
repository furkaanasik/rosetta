import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from rosetta_engine import cli
from rosetta_engine.config import Settings
from rosetta_engine.errors import (
    InvalidTranslationError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    UsageLimitError,
)
from rosetta_engine.translate.base import TranslationItem, TranslationRequest
from rosetta_engine.translate.claude_cli import ClaudeCliTranslator
from rosetta_engine.translate.deepl import FREE_URL, PRO_URL, DeepLTranslator, protect, restore
from rosetta_engine.translate.fake import FakeTranslator
from rosetta_engine.translate.ollama import OllamaTranslator
from rosetta_engine.translate.prompt import RESPONSE_SCHEMA
from rosetta_engine.translate.providers import (
    UnknownProviderError,
    make_translator,
    supports_profile,
)

REQ = TranslationRequest(
    lang="tr",
    items=[
        TranslationItem(id=1, sentences=["Use `a<b` here.", "Second one."]),
        TranslationItem(id=2, sentences=["Replication & sharding."], kind="h"),
    ],
)


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- factory ---------------------------------------------------------------------------


def test_factory_builds_each_provider() -> None:
    s = Settings()

    assert isinstance(make_translator("claude-cli", None, s), ClaudeCliTranslator)
    assert isinstance(make_translator("fake", None, s), FakeTranslator)
    assert isinstance(make_translator("deepl", None, s), DeepLTranslator)
    o = make_translator("ollama", "llama3", s)
    assert isinstance(o, OllamaTranslator)
    assert o.model == "ollama/llama3"


def test_factory_rejects_unknown() -> None:
    with pytest.raises(UnknownProviderError):
        make_translator("nope", None, Settings())


def test_supports_profile_flags() -> None:
    s = Settings()

    assert supports_profile(make_translator("claude-cli", None, s))
    assert supports_profile(make_translator("ollama", None, s))
    assert not supports_profile(make_translator("deepl", None, s))


def test_prices_known_for_optional_providers() -> None:
    s = Settings()

    assert s.price_for("deepl") is not None
    p = s.price_for("ollama/qwen2.5:7b")
    assert p is not None and p.input == 0.0


# --- DeepL -----------------------------------------------------------------------------


def test_protect_and_restore_roundtrip() -> None:
    text, codes = protect("Call `a<b` and ``x`y`` & go")

    assert '<x id="0"/>' in text and '<x id="1"/>' in text
    assert "&amp;" in text and "a<b" not in text
    assert restore(text, codes) == "Call `a<b` and ``x`y`` & go"


def _deepl_ok(seen: list[httpx.Request]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        return httpx.Response(
            200, json={"translations": [{"text": "TR:" + t} for t in body["text"]]}
        )

    return handler


def test_deepl_request_shape_and_alignment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPL_AUTH_KEY", "abc:fx")
    seen: list[httpx.Request] = []
    t = DeepLTranslator(Settings(), client=_client(_deepl_ok(seen)))

    res = t.translate(REQ)

    req = seen[0]
    body = json.loads(req.content)
    assert str(req.url) == f"{FREE_URL}/v2/translate"
    assert req.headers["Authorization"] == "DeepL-Auth-Key abc:fx"
    assert body["target_lang"] == "TR" and body["tag_handling"] == "xml"
    assert len(body["text"]) == 3  # one text per sentence
    assert res.items[1].sentences == ["TR:Use `a<b` here.", "TR:Second one."]
    assert res.items[2].sentences == ["TR:Replication & sharding."]
    assert all(i.aligned for i in res.items.values())
    assert res.cost_usd > 0


def test_deepl_pro_endpoint_and_chunking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPL_AUTH_KEY", "pro-key")
    seen: list[httpx.Request] = []
    t = DeepLTranslator(Settings(), client=_client(_deepl_ok(seen)))
    big = TranslationRequest(
        lang="tr", items=[TranslationItem(id=i, sentences=[f"S{i}."]) for i in range(1, 61)]
    )

    res = t.translate(big)

    assert all(str(r.url).startswith(PRO_URL) for r in seen)
    assert len(seen) == 2
    assert res.items[60].sentences == ["TR:S60."]


def test_deepl_missing_key_is_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPL_AUTH_KEY", raising=False)
    t = DeepLTranslator(Settings(), client=_client(_deepl_ok([])))

    with pytest.raises(ProviderAuthError):
        t.translate(REQ)


@pytest.mark.parametrize(
    ("status", "exc"),
    [(403, ProviderAuthError), (456, UsageLimitError), (500, ProviderError)],
)
def test_deepl_error_mapping(
    status: int, exc: type[Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPL_AUTH_KEY", "k")
    t = DeepLTranslator(Settings(), client=_client(lambda r: httpx.Response(status, text="x")))

    with pytest.raises(exc):
        t.translate(REQ)


def test_deepl_429_retries_then_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPL_AUTH_KEY", "k")
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429)

    t = DeepLTranslator(Settings(), client=_client(handler), sleep=sleeps.append)

    with pytest.raises(UsageLimitError):
        t.translate(REQ)
    assert len(calls) == 4 and sleeps == [1.0, 2.0, 4.0]


def test_deepl_429_then_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPL_AUTH_KEY", "k")
    state = {"n": 0}
    ok = _deepl_ok([])

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(429) if state["n"] == 1 else ok(request)

    t = DeepLTranslator(Settings(), client=_client(handler), sleep=lambda s: None)

    assert t.translate(REQ).items[1].sentences[1] == "TR:Second one."


def test_deepl_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPL_AUTH_KEY", "k")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    with pytest.raises(ProviderError):
        DeepLTranslator(Settings(), client=_client(handler)).translate(REQ)


def test_deepl_count_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPL_AUTH_KEY", "k")
    t = DeepLTranslator(
        Settings(),
        client=_client(lambda r: httpx.Response(200, json={"translations": [{"text": "x"}]})),
    )

    with pytest.raises(ProviderError):
        t.translate(REQ)


# --- Ollama ----------------------------------------------------------------------------


def _ollama(content: str, seen: list[httpx.Request] | None = None, **extra: Any) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json={"message": {"content": content}, **extra})

    return handler


GOOD = json.dumps(
    {"items": [{"id": 1, "s": ["`a<b` kullan.", "İkincisi."]}, {"id": 2, "s": ["Replikasyon."]}]}
)


def test_ollama_request_and_parse() -> None:
    seen: list[httpx.Request] = []
    t = OllamaTranslator(
        "qwen", Settings(), client=_client(_ollama(GOOD, seen, prompt_eval_count=50, eval_count=9))
    )

    res = t.translate(REQ)

    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "http://localhost:11434/api/chat"
    assert body["model"] == "qwen" and body["stream"] is False and body["format"] == "json"
    assert body["messages"][0]["role"] == "system"
    assert res.items[1].sentences[0] == "`a<b` kullan."
    assert (res.input_tokens, res.output_tokens, res.cost_usd) == (50, 9, 0.0)


def test_ollama_strict_uses_schema() -> None:
    seen: list[httpx.Request] = []
    t = OllamaTranslator(None, Settings(), client=_client(_ollama(GOOD, seen)))

    t.translate(REQ, strict=True)

    assert json.loads(seen[0].content)["format"] == RESPONSE_SCHEMA


def test_ollama_invalid_json() -> None:
    t = OllamaTranslator(None, Settings(), client=_client(_ollama("not json", eval_count=7)))

    with pytest.raises(InvalidTranslationError) as e:
        t.translate(REQ)
    assert e.value.output_tokens == 7


def test_ollama_connection_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderUnavailableError):
        OllamaTranslator(None, Settings(), client=_client(handler)).translate(REQ)


def test_ollama_missing_model_and_server_error() -> None:
    with pytest.raises(ProviderUnavailableError):
        OllamaTranslator(None, Settings(), client=_client(lambda r: httpx.Response(404))).translate(
            REQ
        )
    with pytest.raises(ProviderError):
        OllamaTranslator(
            None, Settings(), client=_client(lambda r: httpx.Response(500, text="boom"))
        ).translate(REQ)


# --- CLI -------------------------------------------------------------------------------

runner = CliRunner()


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path / "cfg"))


def test_cli_deepl_notes_missing_profile_support(
    book_pdf: Path, isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPL_AUTH_KEY", "k:fx")
    seen: list[httpx.Request] = []

    def factory(provider: str, model: str | None, settings: Settings) -> DeepLTranslator:
        assert provider == "deepl"
        return DeepLTranslator(settings, client=_client(_deepl_ok(seen)))

    monkeypatch.setattr(cli, "make_translator", factory)

    est = runner.invoke(cli.app, ["estimate", str(book_pdf), "--pages", "1", "--provider", "deepl"])
    tr = runner.invoke(
        cli.app, ["translate", str(book_pdf), "--pages", "1", "--provider", "deepl", "--yes"]
    )

    assert est.exit_code == 0, est.output
    assert "profilini/bağlamı kullanmaz" in est.output
    assert tr.exit_code == 0, tr.output
    assert seen


def test_cli_ollama_translate(
    book_pdf: Path, isolated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        items = json.loads(body["messages"][1]["content"].split("ITEMS:", 1)[1])
        out = {"items": [{"id": i["id"], "s": ["TR " + s for s in i["s"]]} for i in items]}
        return httpx.Response(200, json={"message": {"content": json.dumps(out)}})

    monkeypatch.setattr(
        cli,
        "make_translator",
        lambda provider, model, settings: OllamaTranslator(
            model, settings, client=_client(handler)
        ),
    )

    tr = runner.invoke(
        cli.app, ["translate", str(book_pdf), "--pages", "1", "--provider", "ollama", "--yes"]
    )

    assert tr.exit_code == 0, tr.output
    assert "kullanmaz" not in tr.output


def test_cli_unknown_provider(book_pdf: Path, isolated: None) -> None:
    r = runner.invoke(cli.app, ["estimate", str(book_pdf), "--pages", "1", "--provider", "nope"])

    assert r.exit_code == 2


# --- review fixes ----------------------------------------------------------------------


def test_restore_never_unescapes_inline_code() -> None:
    text, codes = protect("Compare `&lt;` and `a &amp;&amp; b` with x < y")

    assert restore(text, codes) == "Compare `&lt;` and `a &amp;&amp; b` with x < y"


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"nope": []}',
        b'{"translations": [{"x": 1}]}',
        b'{"translations": [{"text": 5}]}',
    ],
)
def test_deepl_malformed_response_is_provider_error(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    monkeypatch.setenv("DEEPL_AUTH_KEY", "abc:fx")
    t = DeepLTranslator(Settings(), client=_client(lambda r: httpx.Response(200, content=payload)))

    with pytest.raises(ProviderError, match="bozuk"):
        t.translate(TranslationRequest(lang="tr", items=[TranslationItem(id=1, sentences=["A."])]))


def test_deepl_failed_second_chunk_reports_billed_first_chunk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEEPL_AUTH_KEY", "pro-key")
    seen: list[httpx.Request] = []
    ok = _deepl_ok(seen)

    def handler(request: httpx.Request) -> httpx.Response:
        if seen:
            return httpx.Response(500, text="boom")
        return ok(request)

    t = DeepLTranslator(Settings(), client=_client(handler))
    big = TranslationRequest(
        lang="tr", items=[TranslationItem(id=i, sentences=[f"S{i}."]) for i in range(1, 61)]
    )

    with pytest.raises(ProviderError) as info:
        t.translate(big)

    assert info.value.input_tokens > 0 and info.value.cost_usd > 0


def test_http_clients_are_created_lazily() -> None:
    d = DeepLTranslator(Settings())
    o = OllamaTranslator(None, Settings())

    assert d._client_or_none is None and o._client_or_none is None
    d.close()
    o.close()


def test_ollama_malformed_response_is_provider_error() -> None:
    t = OllamaTranslator(
        "m", Settings(), client=_client(lambda r: httpx.Response(200, content=b"<html>"))
    )

    with pytest.raises(ProviderError, match="bozuk"):
        t.translate(REQ)

"""Settings + diagnostics API and the in-place config.toml editor (no AI)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from rosetta_engine.api import create_app
from rosetta_engine.api import settings as settings_api
from rosetta_engine.config import Settings, load_settings
from rosetta_engine.config_edit import apply_changes, update_config
from rosetta_engine.errors import ConfigError
from rosetta_engine.translate import claude_locate

TOKEN = "t0k"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def cfg_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path / "cfg"


@pytest.fixture
def client(cfg_dir: Path) -> TestClient:
    return TestClient(create_app(Settings(), token=TOKEN))


def test_apply_changes_keeps_comments_tables_and_unknown_keys() -> None:
    text = (
        "# my config\n"
        'model = "haiku"  # cheap\n'
        "custom_thing = 1\n"
        "\n"
        "[pricing.sonnet]\n"
        "in = 2.0\n"
        "out = 10.0\n"
    )

    out = apply_changes(text, {"model": "sonnet", "claude_path": "/opt/c", "custom_thing": None})

    assert out.startswith("# my config\n")
    assert 'model = "sonnet"' in out
    assert "custom_thing" not in out
    assert out.index('claude_path = "/opt/c"') < out.index("[pricing.sonnet]")
    assert tomllib.loads(out)["pricing"]["sonnet"] == {"in": 2.0, "out": 10.0}


def test_update_config_validates_before_writing(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('model = "haiku"\n')

    with pytest.raises(ConfigError):
        update_config(path, {"batch_max_pages": "many"})
    with pytest.raises(ConfigError, match="değiştirilemez"):
        update_config(path, {"pricing": 1})

    assert path.read_text() == 'model = "haiku"\n'


def test_update_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "config.toml"

    s = update_config(path, {"claude_max_thinking_tokens": 0, "claude_max_budget_usd": 0.1})

    assert s.thinking_level is None
    assert load_settings(path).claude_max_budget_usd == 0.1


def test_get_settings_reports_defaults_and_file_keys(client: TestClient, cfg_dir: Path) -> None:
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text('model = "haiku"\n')

    body = client.get("/api/settings", headers=AUTH).json()

    assert body["defaults"]["model"] == "sonnet"
    assert body["from_file"] == ["model"]
    assert "pricing" not in body["values"]
    assert body["config_path"].endswith("config.toml")


def test_put_settings_writes_file_and_applies_live(client: TestClient, cfg_dir: Path) -> None:
    r = client.put("/api/settings", json={"values": {"model": "haiku"}}, headers=AUTH)

    assert r.status_code == 200
    assert r.json()["values"]["model"] == "haiku"
    assert 'model = "haiku"' in (cfg_dir / "config.toml").read_text()
    hint = client.get("/api/settings", headers=AUTH).json()
    assert hint["from_file"] == ["model"]

    r = client.put("/api/settings", json={"values": {"model": None}}, headers=AUTH)
    assert r.json()["values"]["model"] == "sonnet"


def test_put_settings_rejects_bad_values(client: TestClient) -> None:
    bad = client.put("/api/settings", json={"values": {"ollama_url": "file:///etc"}}, headers=AUTH)
    locked = client.put("/api/settings", json={"values": {"pricing": {}}}, headers=AUTH)

    assert bad.status_code == 400
    assert locked.status_code == 400
    assert bad.json()["error"]["kind"] == "bad_request"


def test_settings_require_token(client: TestClient) -> None:
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/diagnostics").status_code == 401


def test_diagnostics_reports_claude_and_never_calls_ai(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "bin" / "claude"
    exe.parent.mkdir()
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    calls: list[str | None] = []

    def version(path: str | None = None, *, timeout_s: float = 15) -> str:
        calls.append(path)
        return "2.1.284 (Claude Code)"

    monkeypatch.setattr("rosetta_engine.translate.claude_locate.shutil.which", lambda _: None)
    monkeypatch.setattr(claude_locate, "fallback_candidates", lambda: [exe])
    monkeypatch.setattr(settings_api, "claude_version", version)
    monkeypatch.setattr(settings_api, "_ollama_info", lambda s: {"reachable": False})

    d = client.get("/api/diagnostics", headers=AUTH).json()

    assert d["claude"] == {
        "configured": None,
        "path": str(exe),
        "source": "fallback",
        "version": "2.1.284 (Claude Code)",
    }
    assert calls == [str(exe)]
    assert d["paths"]["db"].endswith("rosetta.db")
    assert d["dictionary"]["present"] is False
    assert d["deepl"]["key_set"] is False


def test_diagnostics_missing_claude(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rosetta_engine.translate.claude_locate.shutil.which", lambda _: None)
    monkeypatch.setattr(settings_api, "_ollama_info", lambda s: {"reachable": False})

    d = client.get("/api/diagnostics", headers=AUTH).json()

    assert d["claude"]["path"] is None
    assert d["claude"]["source"] == "missing"


def test_detect_lists_candidates(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exe = tmp_path / "claude"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setattr("rosetta_engine.translate.claude_locate.shutil.which", lambda _: "/u/c")
    monkeypatch.setattr(claude_locate, "fallback_candidates", lambda: [exe, tmp_path / "missing"])
    monkeypatch.setattr(settings_api, "claude_version", lambda p, **_: f"v-{Path(p).name}")

    body = client.get("/api/diagnostics/claude", headers=AUTH).json()

    assert [c["path"] for c in body["candidates"]] == ["/u/c", str(exe)]


def test_ollama_probe_only_for_local_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b"}]})

    real_client = httpx.Client

    def fake_client(**kw: Any) -> httpx.Client:
        return real_client(transport=httpx.MockTransport(handler), **kw)

    monkeypatch.setattr(settings_api.httpx, "Client", fake_client)

    local = settings_api._ollama_info(Settings(ollama_url="http://localhost:11434"))
    remote = settings_api._ollama_info(Settings(ollama_url="http://example.com:11434"))

    assert local["reachable"] is True and local["has_model"] is True
    assert remote["reachable"] is None
    assert seen == ["http://localhost:11434/api/tags"]

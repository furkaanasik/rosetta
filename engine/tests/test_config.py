from pathlib import Path

import pytest

from rosetta_engine import config
from rosetta_engine.errors import ConfigError


def test_env_override_changes_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path / "cfg"))

    assert config.data_dir() == tmp_path / "data"
    assert config.config_dir() == tmp_path / "cfg"
    assert config.db_path() == tmp_path / "data" / "rosetta.db"
    assert config.output_dir("3f9a" * 8) == tmp_path / "data" / "out" / ("3f9a" * 3)


def test_missing_config_gives_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path))

    s = config.load_settings()

    assert s.default_lang == "tr"
    assert s.provider == "claude-cli"
    assert s.model == "sonnet"
    assert s.batch_max_pages == 5
    assert s.batch_max_input_tokens == 6000
    assert s.price_for("sonnet").input == 2.0
    assert s.price_for("sonnet").output == 10.0
    assert s.price_for("claude-sonnet-5-5").output == 10.0
    assert s.price_for("haiku").input == 1.0
    assert s.price_for("haiku").output == 5.0


def test_toml_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text(
        'model = "haiku"\nbatch_max_pages = 3\n[pricing.haiku]\nin = 2.0\nout = 8.0\n'
    )

    s = config.load_settings()

    assert s.batch_max_pages == 3
    assert s.price_for("haiku").output == 8.0
    assert s.price_for("unknown") is None
    assert not s.has_price("unknown")
    assert s.has_price("claude-haiku-4-5")


def test_dirs_not_created_on_import(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROSETTA_DATA_DIR", str(tmp_path / "lazy"))

    config.data_dir()

    assert not (tmp_path / "lazy").exists()


def test_thinking_derived_from_effective_settings() -> None:
    default = config.Settings()
    off = config.Settings(claude_effort="low", claude_max_thinking_tokens=0)
    capped = config.Settings(claude_effort="high", claude_max_thinking_tokens=5000)

    assert (default.thinking_level, default.thinking_extra_output("sonnet")) == ("medium", 1500)
    assert default.thinking_extra_output("haiku") == 18000
    assert default.thinking_extra_output("claude-haiku-4-5") == 18000
    assert default.thinking_extra_output("unknown-model") == 18000  # largest known
    assert (off.thinking_level, off.thinking_extra_output("sonnet")) == (None, 0)
    assert (capped.thinking_level, capped.thinking_extra_output("haiku")) == ("high", 24000)
    assert default.claude_max_budget_usd == 0.25


def test_malformed_toml_is_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text("model = \n")

    with pytest.raises(ConfigError, match=r"config\.toml"):
        config.load_settings()


def test_invalid_value_is_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROSETTA_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.toml").write_text('batch_max_pages = "many"\n')

    with pytest.raises(ConfigError, match="batch_max_pages"):
        config.load_settings()

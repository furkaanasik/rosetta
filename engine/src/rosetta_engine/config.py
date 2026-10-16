"""Filesystem locations and user settings (``~/.config/rosetta/config.toml``)."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import platformdirs
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rosetta_engine.errors import ConfigError

APP_NAME = "rosetta"
CONFIG_FILE = "config.toml"
DB_FILE = "rosetta.db"


class Price(BaseModel):
    """USD per million tokens."""

    input: float = Field(alias="in")
    output: float = Field(alias="out")

    model_config = ConfigDict(populate_by_name=True, frozen=True)


def _default_pricing() -> dict[str, Price]:
    # List prices from the claude-api skill model table (cached 2026-09-25):
    # Claude Sonnet 5.5 $2.00 / $10.00, Claude Haiku 4.5 $1.00 / $5.00 per million tokens.
    # DeepL bills characters ($25 / 1M chars on Pro); expressed per estimated input token
    # (≈3.6 chars/token → ≈$90 / 1M tokens). Free keys: set [pricing.deepl] in = 0.
    # Ollama runs locally: free.
    return {
        "sonnet": Price(input=2.0, output=10.0),
        "haiku": Price(input=1.0, output=5.0),
        "deepl": Price(input=90.0, output=0.0),
        "ollama": Price(input=0.0, output=0.0),
    }


def _model_family(model: str) -> str:
    """Map an alias or full model id ("claude-sonnet-5-5") to its family key ("sonnet")."""
    for family in ("deepl", "ollama", "sonnet", "haiku", "opus", "fable"):
        if family in model.lower():
            return family
    return model


def _default_thinking_output() -> dict[str, dict[str, int]]:
    return {
        # haiku: measured 9k-18k hidden tokens per call at medium (DDIA p25/p30-115)
        "haiku": {"low": 13000, "medium": 18000, "high": 24000},
        # sonnet: medium measured ~0 hidden on DDIA p30; low/high are guesses (high unmeasured)
        "sonnet": {"low": 500, "medium": 1500, "high": 6000},
    }


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    default_lang: str = "tr"
    provider: str = "claude-cli"
    model: str = "sonnet"
    explain_model: str = "haiku"  # "Bunu açıkla" (Faz 7); requirements §3.6 ask for Haiku
    batch_max_pages: int = 5
    job_default_budget_usd: float | None = None  # pre-filled budget for new batch jobs (app)
    batch_max_input_tokens: int = 6000
    claude_timeout_s: int = 240
    # Absolute path of the claude CLI; None = auto-detect (PATH, then common install dirs)
    claude_path: str | None = None
    claude_effort: str | None = "medium"  # passed as `claude --effort`; None = CLI default
    # MAX_THINKING_TOKENS for the child; None = CLI default (thinking on), 0 = thinking off
    claude_max_thinking_tokens: int | None = None
    claude_max_budget_usd: float | None = 0.25  # per call safety cap, `claude --max-budget-usd`
    # Hidden thinking output tokens per call while thinking is on, per model family and level
    thinking_output_tokens_per_call: dict[str, dict[str, int]] = Field(
        default_factory=_default_thinking_output
    )
    pricing: dict[str, Price] = Field(default_factory=_default_pricing)
    prefetch: bool = False
    # Optional providers (Faz 8)
    deepl_auth_key_env: str = "DEEPL_AUTH_KEY"  # env var holding the DeepL key (never in config)
    deepl_timeout_s: int = 60
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_s: int = 600

    @property
    def thinking_level(self) -> str | None:
        """Effective thinking level, or None when thinking is off (MAX_THINKING_TOKENS=0)."""
        if self.claude_max_thinking_tokens is not None and self.claude_max_thinking_tokens <= 0:
            return None
        return self.claude_effort or "medium"

    def thinking_extra_output(self, model: str) -> int:
        """Expected hidden thinking output tokens per call for ``model`` (0 when thinking is off).

        Unknown models fall back to the largest known value for the level (never underestimate).
        """
        level = self.thinking_level
        if level is None:
            return 0
        table = self.thinking_output_tokens_per_call
        known = table.get(model) or table.get(_model_family(model))
        if known is not None:
            return known.get(level, 0)
        return max((levels.get(level, 0) for levels in table.values()), default=0)

    def price_for(self, model: str) -> Price | None:
        """List price for ``model`` (alias or full id); None when no price is configured."""
        return self.pricing.get(model) or self.pricing.get(_model_family(model))

    def has_price(self, model: str) -> bool:
        return self.price_for(model) is not None


def data_dir() -> Path:
    override = os.environ.get("ROSETTA_DATA_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))


def config_dir() -> Path:
    override = os.environ.get("ROSETTA_CONFIG_DIR")
    if override:
        return Path(override)
    return Path(platformdirs.user_config_dir(APP_NAME, appauthor=False))


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return ensure_dir(data_dir()) / DB_FILE


def output_dir(book_hash: str) -> Path:
    return ensure_dir(data_dir() / "out" / book_hash[:12])


def load_settings(path: Path | None = None) -> Settings:
    path = path or config_dir() / CONFIG_FILE
    if not path.is_file():
        return Settings()
    try:
        with path.open("rb") as f:
            raw = tomllib.load(f)
        return Settings.model_validate(raw)
    except (tomllib.TOMLDecodeError, ValidationError) as e:
        raise ConfigError(f"{path}: geçersiz ayar dosyası: {e}") from e

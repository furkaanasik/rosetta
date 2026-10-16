"""Edit top-level scalar keys of ``config.toml`` in place.

Comments, unknown keys and tables (``[pricing.*]`` …) are kept as written: only the lines of
the changed keys are replaced, inserted (before the first table header) or removed. The file is
validated as a whole before it is atomically replaced, so a bad value never reaches disk.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from rosetta_engine.config import Settings
from rosetta_engine.errors import ConfigError

# Keys the settings screen may change. Everything else is file-only (pricing, thinking tables…).
EDITABLE_KEYS: frozenset[str] = frozenset(
    {
        "default_lang",
        "provider",
        "model",
        "explain_model",
        "claude_path",
        "claude_effort",
        "claude_max_thinking_tokens",
        "claude_max_budget_usd",
        "claude_timeout_s",
        "job_default_budget_usd",
        "batch_max_pages",
        "deepl_auth_key_env",
        "ollama_url",
        "ollama_model",
    }
)

_TABLE_RE = re.compile(r"^\s*\[")


def _key_re(key: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(key)}\s*=")


def toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # a valid TOML basic string
    raise ConfigError(f"desteklenmeyen ayar değeri: {value!r}")


def apply_changes(text: str, changes: Mapping[str, Any]) -> str:
    """Return ``text`` with top-level ``key = value`` lines set (``None`` → line removed)."""
    lines = text.splitlines()
    first_table = next((i for i, line in enumerate(lines) if _TABLE_RE.match(line)), len(lines))
    head, tail = lines[:first_table], lines[first_table:]
    for key, value in changes.items():
        pattern = _key_re(key)
        idx = next((i for i, line in enumerate(head) if pattern.match(line)), None)
        if value is None:
            if idx is not None:
                del head[idx]
            continue
        line = f"{key} = {toml_value(value)}"
        if idx is not None:
            head[idx] = line
        else:
            while head and not head[-1].strip():
                head.pop()
            head.append(line)
    if tail and head and head[-1].strip():
        head.append("")
    out = "\n".join(head + tail)
    return out + "\n" if out else ""


def update_config(path: Path, changes: Mapping[str, Any]) -> Settings:
    """Validate and write ``changes`` to ``path``; returns the resulting settings."""
    unknown = sorted(set(changes) - EDITABLE_KEYS)
    if unknown:
        raise ConfigError(f"bu ayar buradan değiştirilemez: {', '.join(unknown)}")
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    new_text = apply_changes(text, changes)
    try:
        settings = Settings.model_validate(tomllib.loads(new_text))
    except (tomllib.TOMLDecodeError, ValidationError) as e:
        raise ConfigError(f"geçersiz ayar: {e}") from e
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".config.", suffix=".toml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return settings


def keys_in_file(path: Path) -> list[str]:
    """Top-level keys explicitly set in ``path`` (for "varsayılan / dosyadan" badges)."""
    if not path.is_file():
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return []
    return sorted(raw)

"""Settings and diagnostics endpoints (no AI): the app's "Ayarlar" screen."""

from __future__ import annotations

import os
import platform
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import pymupdf
from fastapi import APIRouter
from pydantic import BaseModel

from rosetta_engine import __version__, config
from rosetta_engine.api.deps import Engine
from rosetta_engine.api.errors import ApiError
from rosetta_engine.config_edit import EDITABLE_KEYS, keys_in_file, update_config
from rosetta_engine.errors import ConfigError
from rosetta_engine.export.chromium import ExportError, find_chromium
from rosetta_engine.learn.dictionary import dictionary_path
from rosetta_engine.translate import claude_locate
from rosetta_engine.translate.claude_cli import claude_version

router = APIRouter(prefix="/api")

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
CLAUDE_VERSION_TIMEOUT_S = 5.0
OLLAMA_TIMEOUT_S = 1.0


class SettingsBody(BaseModel):
    """Partial update; a ``null`` value removes the key from config.toml (→ default)."""

    values: dict[str, Any]


def _config_file() -> Path:
    return config.config_dir() / config.CONFIG_FILE


def _settings_view(settings: config.Settings) -> dict[str, Any]:
    path = _config_file()
    data = settings.model_dump(include=set(EDITABLE_KEYS))
    return {
        "values": data,
        "defaults": config.Settings().model_dump(include=set(EDITABLE_KEYS)),
        "from_file": [k for k in keys_in_file(path) if k in EDITABLE_KEYS],
        "editable": sorted(EDITABLE_KEYS),
        "config_path": str(path),
    }


@router.get("/settings")
def get_settings(eng: Engine) -> dict[str, Any]:
    return _settings_view(eng.settings)


@router.put("/settings")
def put_settings(body: SettingsBody, eng: Engine) -> dict[str, Any]:
    if "ollama_url" in body.values and body.values["ollama_url"] is not None:
        url = urlparse(str(body.values["ollama_url"]))
        if url.scheme not in ("http", "https") or not url.hostname:
            raise ApiError("bad_request", "Ollama adresi http(s)://sunucu:port biçiminde olmalı")
    try:
        new = update_config(_config_file(), body.values)
    except ConfigError as e:
        raise ApiError("bad_request", str(e)) from e
    eng.settings = new
    return _settings_view(new)


def _claude_source(settings: config.Settings, resolved: str | None) -> str:
    if resolved is None:
        return "missing"
    if settings.claude_path:
        return "settings"
    return "path" if shutil.which(claude_locate.CLAUDE_BIN) == resolved else "fallback"


def _dictionary_info() -> dict[str, Any]:
    path = dictionary_path()
    info: dict[str, Any] = {"path": str(path), "present": path.is_file(), "entries": None}
    if path.is_file():
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
                info["entries"] = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        except sqlite3.Error:
            info["present"] = False
    return info


def _ollama_info(settings: config.Settings) -> dict[str, Any]:
    url = settings.ollama_url.rstrip("/")
    info: dict[str, Any] = {"url": url, "model": settings.ollama_model, "reachable": None}
    host = urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS:
        info["note"] = "yalnızca yerel adresler sınanır"
        return info
    try:
        with httpx.Client(timeout=OLLAMA_TIMEOUT_S) as client:
            r = client.get(f"{url}/api/tags")
        r.raise_for_status()
        models = [m.get("name", "") for m in r.json().get("models", [])]
        info |= {"reachable": True, "models": models, "has_model": settings.ollama_model in models}
    except (httpx.HTTPError, ValueError):
        info["reachable"] = False
    return info


def _chromium() -> str | None:
    try:
        return str(find_chromium())
    except ExportError:
        return None


@router.get("/diagnostics")
def diagnostics(eng: Engine) -> dict[str, Any]:
    """Everything the app needs to explain why something can't run. Never calls AI."""
    s = eng.settings
    resolved = claude_locate.resolve_claude(s.claude_path)
    db = config.data_dir() / config.DB_FILE
    return {
        "engine": {
            "version": __version__,
            "python": platform.python_version(),
            "pymupdf": pymupdf.VersionBind,
            "frozen": bool(getattr(sys, "frozen", False)),
        },
        "paths": {
            "data_dir": str(config.data_dir()),
            "config_dir": str(config.config_dir()),
            "config_file": str(_config_file()),
            "config_exists": _config_file().is_file(),
            "db": str(db),
            "db_bytes": db.stat().st_size if db.is_file() else 0,
        },
        "dictionary": _dictionary_info(),
        "claude": {
            "configured": s.claude_path,
            "path": resolved,
            "source": _claude_source(s, resolved),
            "version": claude_version(resolved, timeout_s=CLAUDE_VERSION_TIMEOUT_S)
            if resolved
            else None,
        },
        "chromium": _chromium(),
        "deepl": {
            "env": s.deepl_auth_key_env,
            "key_set": bool(os.environ.get(s.deepl_auth_key_env)),
        },
        "ollama": _ollama_info(s),
    }


@router.get("/diagnostics/claude")
def detect_claude() -> dict[str, Any]:
    """Candidate claude binaries for the "Bul" button (PATH first, then known locations)."""
    seen: list[str] = []
    on_path = shutil.which(claude_locate.CLAUDE_BIN)
    if on_path:
        seen.append(on_path)
    for cand in claude_locate.fallback_candidates():
        if cand.is_file() and os.access(cand, os.X_OK) and str(cand) not in seen:
            seen.append(str(cand))
    return {
        "candidates": [
            {"path": p, "version": claude_version(p, timeout_s=CLAUDE_VERSION_TIMEOUT_S)}
            for p in seen
        ]
    }

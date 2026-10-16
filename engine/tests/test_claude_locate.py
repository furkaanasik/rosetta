import os
from pathlib import Path

import pytest

from rosetta_engine.translate import claude_locate
from rosetta_engine.translate.claude_cli import child_env
from rosetta_engine.translate.claude_locate import fallback_candidates, resolve_claude

WHICH = "rosetta_engine.translate.claude_locate.shutil.which"


def _exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_configured_path_wins_over_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mine = _exe(tmp_path / "bin" / "claude")
    monkeypatch.setattr(WHICH, lambda _: "/usr/bin/claude")

    assert resolve_claude(str(mine)) == str(mine)


def test_invalid_configured_path_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(WHICH, lambda _: "/usr/bin/claude")

    assert resolve_claude(str(tmp_path / "nope")) is None


def test_path_lookup_before_fallbacks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = _exe(tmp_path / "fb" / "claude")
    monkeypatch.setattr(WHICH, lambda _: "/opt/x/claude")
    monkeypatch.setattr(claude_locate, "fallback_candidates", lambda: [fallback])

    assert resolve_claude() == "/opt/x/claude"


def test_fallback_used_when_not_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "a" / "claude"
    not_exec = tmp_path / "b" / "claude"
    not_exec.parent.mkdir()
    not_exec.write_text("x")
    good = _exe(tmp_path / "c" / "claude")
    monkeypatch.setattr(WHICH, lambda _: None)
    monkeypatch.setattr(claude_locate, "fallback_candidates", lambda: [missing, not_exec, good])

    assert resolve_claude() == str(good)


def test_nothing_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(WHICH, lambda _: None)

    assert resolve_claude() is None


def test_fallback_order_prefers_newest_mise_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    base = tmp_path / ".local/share/mise/installs/claude"
    for version in ("2.1.9", "2.1.284", "latest"):
        _exe(base / version / "claude")

    cands = fallback_candidates()

    mise = [c for c in cands if "installs" in str(c)]
    assert [c.parent.name for c in mise] == ["latest", "2.1.284", "2.1.9"]
    assert cands[0] == tmp_path / ".local/bin/claude"
    assert cands.index(tmp_path / ".local/share/mise/shims/claude") > cands.index(mise[-1])


def test_frozen_build_restores_original_library_path() -> None:
    env = child_env(
        {
            "PATH": "/usr/bin",
            "LD_LIBRARY_PATH": "/tmp/_MEI123:/usr/local/lib",
            "LD_LIBRARY_PATH_ORIG": "/usr/local/lib",
        },
        frozen=True,
    )

    assert env["LD_LIBRARY_PATH"] == "/usr/local/lib"
    assert "LD_LIBRARY_PATH_ORIG" not in env


def test_frozen_build_without_original_drops_library_path() -> None:
    env = child_env({"LD_LIBRARY_PATH": "/tmp/_MEI123"}, frozen=True)

    assert "LD_LIBRARY_PATH" not in env


def test_appimage_libraries_never_reach_claude() -> None:
    appdir = "/tmp/appimage_extracted_abc"
    env = child_env(
        {
            "APPDIR": appdir,
            "LD_LIBRARY_PATH": f"/tmp/_MEI1:{appdir}/usr/lib/:/opt/mine",
            "LD_LIBRARY_PATH_ORIG": f"{appdir}/usr/lib/:{appdir}/lib/:/opt/mine",
        },
        frozen=True,
    )

    assert env["LD_LIBRARY_PATH"] == "/opt/mine"


def test_source_run_keeps_library_path_and_stripping_rules() -> None:
    env = child_env(
        {
            "LD_LIBRARY_PATH": "/opt/lib",
            "ANTHROPIC_API_KEY": "x",
            "ANTHROPIC_BASE_URL": "y",
            "CLAUDE_CODE_OAUTH_TOKEN": "keep",
            "CLAUDE_CODE_SESSION_ID": "drop",
            "MAX_THINKING_TOKENS": "32000",
        },
        frozen=False,
        max_thinking_tokens=0,
    )

    assert env["LD_LIBRARY_PATH"] == "/opt/lib"
    assert not any(k.startswith("ANTHROPIC_") for k in env)
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "keep"
    assert "CLAUDE_CODE_SESSION_ID" not in env
    assert env["MAX_THINKING_TOKENS"] == "0"


def test_real_environment_default_is_not_frozen() -> None:
    env = child_env({"LD_LIBRARY_PATH": "/opt/lib"})

    assert env.get("LD_LIBRARY_PATH") == "/opt/lib"
    assert os.environ is not env


def test_autodetect_can_be_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    _exe(tmp_path / ".local/bin/claude")
    assert fallback_candidates()  # the module-level import is the real function

    monkeypatch.setenv("ROSETTA_CLAUDE_AUTODETECT", "0")

    assert fallback_candidates() == []

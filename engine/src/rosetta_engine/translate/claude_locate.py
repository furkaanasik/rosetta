"""Find the ``claude`` CLI even when the app was started from a desktop launcher.

Desktop sessions often have a shorter PATH than an interactive shell (mise/asdf/nvm/npm
installs are added by shell rc files), so a plain ``shutil.which`` can miss a working CLI.

Resolution order (first executable file wins):

1. ``Settings.claude_path`` (config.toml / Ayarlar), used as-is; no fallback when it is set
   but invalid, so a wrong path is reported instead of silently using another binary.
2. ``shutil.which("claude")`` on the current PATH.
3. Well-known install locations (:func:`fallback_candidates`).
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

CLAUDE_BIN = "claude"


def _version_key(path: Path) -> tuple[int, ...]:
    """Sort key for mise install dirs: "2.1.284" > "2.1.9"; "latest" sorts first."""
    name = path.parent.name
    if name == "latest":
        return (1_000_000,)
    return tuple(int(n) for n in re.findall(r"\d+", name)) or (0,)


def fallback_candidates() -> list[Path]:
    """Common per-user and system install locations, in priority order.

    ``ROSETTA_CLAUDE_AUTODETECT=0`` disables the search (E2E runs keep `claude` unreachable).
    """
    if os.environ.get("ROSETTA_CLAUDE_AUTODETECT") == "0":
        return []
    home = Path.home()
    mise = sorted(
        (home / ".local/share/mise/installs/claude").glob(f"*/{CLAUDE_BIN}"),
        key=_version_key,
        reverse=True,
    )
    return [
        home / ".local/bin" / CLAUDE_BIN,
        home / ".claude/local" / CLAUDE_BIN,
        *mise,
        home / ".local/share/mise/shims" / CLAUDE_BIN,
        home / ".npm-global/bin" / CLAUDE_BIN,
        home / ".bun/bin" / CLAUDE_BIN,
        Path("/usr/local/bin") / CLAUDE_BIN,
        Path("/usr/bin") / CLAUDE_BIN,
    ]


def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def resolve_claude(configured: str | None = None) -> str | None:
    """Absolute path of the claude CLI, or None when it can't be found."""
    if configured:
        p = Path(configured).expanduser()
        return str(p) if _executable(p) else None
    found = shutil.which(CLAUDE_BIN)
    if found:
        return found
    for candidate in fallback_candidates():
        if _executable(candidate):
            return str(candidate)
    return None


def which_claude(_name: str = CLAUDE_BIN) -> str | None:
    """Drop-in for ``shutil.which("claude")`` that honours settings and fallbacks."""
    from rosetta_engine.config import load_settings  # local: config must not import translate

    return resolve_claude(load_settings().claude_path)

"""Print HTML to PDF with a headless Chromium found on the system (no Python browser deps)."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from rosetta_engine.errors import RosettaError

log = logging.getLogger(__name__)

CHROMIUM_ENV = "ROSETTA_CHROMIUM"
CANDIDATES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")
PLAYWRIGHT_CACHE = Path.home() / ".cache" / "ms-playwright"
DEFAULT_TIMEOUT_S = 600.0


class ExportError(RosettaError):
    """PDF export failed (no browser, print error, missing output)."""


@dataclass(frozen=True)
class PrintRun:
    returncode: int
    stderr: str


PrintRunner = Callable[[Sequence[str], float], PrintRun]


def run_print(argv: Sequence[str], timeout_s: float) -> PrintRun:
    """Run Chromium in its own process group; on timeout the whole group is killed (Chromium
    spawns renderer/GPU helpers that would otherwise outlive it)."""
    try:
        proc = subprocess.Popen(
            list(argv),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
    except OSError as e:
        raise ExportError(f"Chromium çalıştırılamadı: {e}") from e
    try:
        _, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        _kill_group(proc)
        raise ExportError(f"Chromium {timeout_s:.0f} sn içinde bitmedi") from e
    return PrintRun(proc.returncode, stderr or "")


def _kill_group(proc: subprocess.Popen[str]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    proc.communicate()


def _playwright_chromium(cache: Path) -> Path | None:
    patterns = ("chromium-*/chrome-linux*/chrome", "chromium_headless_shell-*/*/headless_shell")
    found = sorted((p for pat in patterns for p in cache.glob(pat)), reverse=True)
    return next((p for p in found if os.access(p, os.X_OK)), None)


def find_chromium(
    env: dict[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    playwright_cache: Path = PLAYWRIGHT_CACHE,
) -> Path:
    """``$ROSETTA_CHROMIUM`` → chromium/chrome on PATH → Playwright's cached Chromium."""
    env = dict(os.environ) if env is None else env
    override = env.get(CHROMIUM_ENV)
    if override:
        path = Path(override)
        if path.is_file() and os.access(path, os.X_OK):
            return path
        raise ExportError(f"{CHROMIUM_ENV}={override} çalıştırılabilir bir dosya değil")
    for name in CANDIDATES:
        hit = which(name)
        if hit:
            return Path(hit)
    pw = _playwright_chromium(playwright_cache)
    if pw is not None:
        return pw
    raise ExportError(
        "Chromium bulunamadı. Kur (ör. Arch: `pacman -S chromium`, Debian: `apt install chromium`) "
        f"ya da {CHROMIUM_ENV} ile yolunu ver."
    )


def print_argv(browser: Path, html: Path, pdf: Path, profile_dir: Path) -> list[str]:
    return [
        str(browser),
        "--headless",
        "--disable-gpu",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        f"--user-data-dir={profile_dir}",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf}",
        html.resolve().as_uri(),
    ]


def print_to_pdf(
    html: Path,
    pdf: Path,
    *,
    browser: Path | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    runner: PrintRunner = run_print,
) -> Path:
    """Print ``html`` (local file) to ``pdf``. Page size and margins come from CSS ``@page``."""
    browser = browser or find_chromium()
    pdf.parent.mkdir(parents=True, exist_ok=True)
    if pdf.exists():
        pdf.unlink()
    # A throwaway profile: never collides with a running browser's profile lock.
    with tempfile.TemporaryDirectory(prefix="rosetta-chromium-") as profile:
        run = runner(print_argv(browser, html, pdf, Path(profile)), timeout_s)
    if run.returncode != 0 or not pdf.is_file() or pdf.stat().st_size == 0:
        detail = run.stderr.strip().splitlines()[-3:] if run.stderr else []
        raise ExportError(f"Chromium PDF üretemedi (exit {run.returncode}): " + " | ".join(detail))
    if run.stderr:
        log.debug("chromium stderr: %s", run.stderr)
    return pdf

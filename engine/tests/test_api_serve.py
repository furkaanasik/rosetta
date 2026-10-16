"""`rosetta serve` sidecar protocol: one JSON line on stdout, then the API on 127.0.0.1."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from rosetta_engine import cli

LAUNCH = "from rosetta_engine.cli import app; app()"


def _env(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["ROSETTA_DATA_DIR"] = str(tmp_path / "data")
    env["ROSETTA_CONFIG_DIR"] = str(tmp_path / "cfg")
    return env


def test_serve_prints_port_and_token_then_serves(tmp_path: Path, book_pdf: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", LAUNCH, "serve", "--port", "0", "--token", "t0k"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(tmp_path),
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        info = json.loads(line)
        assert info["token"] == "t0k" and info["port"] > 0
        base = f"http://127.0.0.1:{info['port']}/api"
        auth = {"Authorization": "Bearer t0k"}
        with httpx.Client(timeout=10) as http:
            assert http.get(f"{base}/health").status_code == 401
            assert http.get(f"{base}/health", headers=auth).json()["ok"] is True
            book = http.post(f"{base}/books/open", json={"path": str(book_pdf)}, headers=auth)
            assert book.status_code == 200 and book.json()["page_count"] == 3
    finally:
        proc.terminate()
        proc.wait(10)
    assert proc.stdout is not None
    assert proc.stdout.read() == ""  # nothing but the handshake line ever goes to stdout


def test_serve_random_token_when_not_given(tmp_path: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", LAUNCH, "serve"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=_env(tmp_path),
    )
    try:
        assert proc.stdout is not None
        info = json.loads(proc.stdout.readline())
        assert len(info["token"]) == 64
    finally:
        proc.terminate()
        proc.wait(10)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5"])
def test_serve_refuses_non_local_host(host: str) -> None:
    result = CliRunner().invoke(cli.app, ["serve", "--host", host])
    assert result.exit_code == 2


def test_dev_fake_ai_flag_is_hidden_from_help() -> None:
    from typer.testing import CliRunner

    from rosetta_engine.cli import app

    out = CliRunner().invoke(app, ["serve", "--help"]).output
    assert "--dev-fake-ai" not in out


def test_serve_takes_token_from_env_not_argv(tmp_path: Path) -> None:
    env = _env(tmp_path) | {"ROSETTA_SERVE_TOKEN": "env-secret-123"}
    proc = subprocess.Popen(
        [sys.executable, "-c", LAUNCH, "serve", "--port", "0"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    try:
        assert proc.stdout is not None
        info = json.loads(proc.stdout.readline())
        assert info["token"] == "env-secret-123"
        cmdline = Path(f"/proc/{proc.pid}/cmdline").read_bytes()
        assert b"env-secret-123" not in cmdline
        with httpx.Client(timeout=10) as http:
            ok = http.get(
                f"http://127.0.0.1:{info['port']}/api/health",
                headers={"Authorization": "Bearer env-secret-123"},
            )
            assert ok.status_code == 200
    finally:
        proc.terminate()
        proc.wait(10)


def test_take_token_removes_env_var_so_children_never_inherit_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rosetta_engine.commands import serve

    monkeypatch.setenv(serve.TOKEN_ENV, "abc")

    assert serve._take_token(None) == "abc"
    assert serve.TOKEN_ENV not in os.environ
    assert serve._take_token("cli") == "cli"
    assert len(serve._take_token(None)) == 64


def test_serve_exits_when_stdin_pipe_closes(tmp_path: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", LAUNCH, "serve", "--port", "0", "--token", "t"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=_env(tmp_path),
    )
    try:
        assert proc.stdout is not None and proc.stdin is not None
        json.loads(proc.stdout.readline())
        assert proc.poll() is None  # still serving while the pipe is open
        proc.stdin.close()  # the app went away
        assert proc.wait(15) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(10)


def test_serve_handles_sigterm_gracefully(tmp_path: Path) -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", LAUNCH, "serve", "--port", "0", "--token", "t"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=_env(tmp_path),
    )
    assert proc.stdout is not None
    json.loads(proc.stdout.readline())
    proc.terminate()
    assert proc.wait(15) == 0


def test_dev_fake_ai_refused_without_temp_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROSETTA_DATA_DIR", raising=False)

    result = CliRunner().invoke(cli.app, ["serve", "--dev-fake-ai"])

    assert result.exit_code == 2

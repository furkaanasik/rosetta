"""`rosetta serve`: the HTTP API for the desktop app (Tauri sidecar protocol)."""

from __future__ import annotations

import ctypes
import json
import logging
import os
import secrets
import signal
import socket
import stat
import sys
import threading
from typing import Annotated, Any

import typer

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
TOKEN_ENV = "ROSETTA_SERVE_TOKEN"
PR_SET_PDEATHSIG = 1
SHUTDOWN_GRACE_S = 5.0

log = logging.getLogger(__name__)


def _take_token(cli_token: str | None) -> str:
    """``--token`` (dev; visible in ps) → ``$ROSETTA_SERVE_TOKEN`` (the app's way; environ is
    owner-only) → random. The env var is removed so no child process (claude, chromium)
    inherits it."""
    from_env = os.environ.pop(TOKEN_ENV, "").strip()
    return cli_token or from_env or secrets.token_hex(32)


def _die_with_parent() -> None:
    """Linux: get SIGTERM when the parent dies (best effort; e.g. the PyInstaller bootloader
    killed by the app)."""
    if not sys.platform.startswith("linux"):
        return
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
    except (OSError, AttributeError):
        log.debug("prctl(PR_SET_PDEATHSIG) unavailable")


def _stdin_is_pipe() -> bool:
    try:
        return stat.S_ISFIFO(os.fstat(sys.stdin.fileno()).st_mode)
    except (OSError, ValueError):
        return False


def _watch_stdin(server: Any) -> None:
    """When started with a pipe on stdin (the desktop app), its EOF means the app is gone:
    shut down gracefully, and hard-exit if that takes too long. A terminal or /dev/null stdin
    is not watched, so manual and test runs are unaffected."""
    if not _stdin_is_pipe():
        return

    def watch() -> None:
        try:
            while sys.stdin.buffer.read(65536):
                pass
        except (OSError, ValueError):
            pass
        log.warning("stdin closed (parent gone); shutting down")
        server.should_exit = True
        killer = threading.Timer(SHUTDOWN_GRACE_S, os._exit, args=(0,))
        killer.daemon = True
        killer.start()

    threading.Thread(target=watch, name="rosetta-stdin-watch", daemon=True).start()


def register(app: typer.Typer) -> None:
    @app.command("serve")
    def serve(
        port: Annotated[int, typer.Option("--port", min=0, max=65535, help="0 = boş port")] = 0,
        token: Annotated[
            str | None,
            typer.Option(
                "--token",
                help=f"İstek belirteci (geliştirme; ps'te görünür). Uygulama ${TOKEN_ENV} "
                "kullanır; ikisi de yoksa rastgele",
            ),
        ] = None,
        host: Annotated[str, typer.Option("--host", help="Yalnızca 127.0.0.1")] = "127.0.0.1",
        dev_fake_ai: Annotated[
            bool,
            typer.Option(
                "--dev-fake-ai",
                hidden=True,
                help="Yalnızca geliştirme/E2E: tüm AI çağrıları sahte (claude çağrılmaz)",
            ),
        ] = False,
        dev_fake_delay: Annotated[
            float,
            typer.Option("--dev-fake-delay", hidden=True, help="Sahte AI: çağrı başı gecikme (sn)"),
        ] = 0.0,
    ) -> None:
        """API sunucusu: hazır olunca stdout'a tek satır {"port", "token"} JSON basar."""
        import uvicorn

        from rosetta_engine import config
        from rosetta_engine.api import create_app
        from rosetta_engine.errors import ConfigError

        if host not in LOCAL_HOSTS:
            typer.echo("Hata: yalnızca yerel adres (127.0.0.1) dinlenebilir", err=True)
            raise typer.Exit(2)
        try:
            settings = config.load_settings()
        except ConfigError as e:
            typer.echo(f"Hata: {e}", err=True)
            raise typer.Exit(1) from e
        if dev_fake_ai and not os.environ.get("ROSETTA_DATA_DIR"):
            typer.echo(
                "Hata: --dev-fake-ai yalnızca ROSETTA_DATA_DIR ile (geçici bir veri dizini) "
                "çalışır; gerçek veritabanına sahte AI sonuçları yazılmaz",
                err=True,
            )
            raise typer.Exit(2)
        secret = _take_token(token)
        _die_with_parent()
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("::1" if family == socket.AF_INET6 else "127.0.0.1", port))
        sock.listen(128)
        sock.set_inheritable(True)
        bound = sock.getsockname()[1]
        if dev_fake_ai:
            from rosetta_engine.translate.fake import DevFakeTranslator, fake_complete

            typer.echo("UYARI: --dev-fake-ai açık — AI çağrıları sahte (geliştirme modu)", err=True)

            def fake_factory(
                provider: str, model: str | None, settings: config.Settings
            ) -> DevFakeTranslator:
                return DevFakeTranslator(
                    model=model or settings.model, delay_s=dev_fake_delay, provider=provider
                )

            api = create_app(
                settings, token=secret, translator_factory=fake_factory, complete_fn=fake_complete
            )
        else:
            api = create_app(settings, token=secret)
        server = uvicorn.Server(
            uvicorn.Config(api, log_level="warning", access_log=False, lifespan="on")
        )
        # A SIGTERM right after the handshake (before uvicorn installs its own handlers) is a
        # graceful shutdown too, not an abrupt kill.
        signal.signal(signal.SIGTERM, lambda signum, frame: setattr(server, "should_exit", True))
        # The socket already accepts connections (they queue until uvicorn runs), so the app
        # can connect as soon as it reads this line. Nothing else ever goes to stdout.
        sys.stdout.write(json.dumps({"port": bound, "token": secret}) + "\n")
        sys.stdout.flush()
        _watch_stdin(server)
        server.run(sockets=[sock])  # uvicorn handles SIGTERM/SIGINT as a graceful shutdown

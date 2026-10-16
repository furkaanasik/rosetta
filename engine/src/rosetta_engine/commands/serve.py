"""`rosetta serve`: the HTTP API for the desktop app (Tauri sidecar protocol)."""

from __future__ import annotations

import json
import secrets
import socket
import sys
from typing import Annotated

import typer

LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def register(app: typer.Typer) -> None:
    @app.command("serve")
    def serve(
        port: Annotated[int, typer.Option("--port", min=0, max=65535, help="0 = boş port")] = 0,
        token: Annotated[
            str | None, typer.Option("--token", help="İstek belirteci (varsayılan: rastgele)")
        ] = None,
        host: Annotated[str, typer.Option("--host", help="Yalnızca 127.0.0.1")] = "127.0.0.1",
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
        secret = token or secrets.token_hex(32)
        family = socket.AF_INET6 if ":" in host else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("::1" if family == socket.AF_INET6 else "127.0.0.1", port))
        sock.listen(128)
        sock.set_inheritable(True)
        bound = sock.getsockname()[1]
        api = create_app(settings, token=secret)
        server = uvicorn.Server(
            uvicorn.Config(api, log_level="warning", access_log=False, lifespan="on")
        )
        # The socket already accepts connections (they queue until uvicorn runs), so the app
        # can connect as soon as it reads this line. Nothing else ever goes to stdout.
        sys.stdout.write(json.dumps({"port": bound, "token": secret}) + "\n")
        sys.stdout.flush()
        server.run(sockets=[sock])

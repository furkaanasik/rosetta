"""CLI command plugins: every module here exposing ``register(app)`` is added to the CLI."""

from __future__ import annotations

import importlib
import pkgutil

import typer


def register_all(app: typer.Typer) -> None:
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda m: m.name):
        module = importlib.import_module(f"{__name__}.{info.name}")
        register = getattr(module, "register", None)
        if callable(register):
            register(app)

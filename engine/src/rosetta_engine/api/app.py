"""FastAPI app factory for the Tauri sidecar (contract: app/API_CONTRACT.md)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from rosetta_engine import __version__, config
from rosetta_engine.api import ai, books, errors, learn
from rosetta_engine.api import settings as settings_api
from rosetta_engine.api.confirm import ConfirmStore
from rosetta_engine.api.deps import require_token
from rosetta_engine.api.state import CompleteFn, EngineState, TranslatorFactory
from rosetta_engine.translate.claude_cli import complete
from rosetta_engine.translate.providers import make_translator

ALLOWED_ORIGINS = ["tauri://localhost", "http://tauri.localhost", "http://localhost:1420"]


def create_app(
    settings: config.Settings | None = None,
    *,
    token: str,
    translator_factory: TranslatorFactory = make_translator,
    complete_fn: CompleteFn = complete,
    confirm: ConfirmStore | None = None,
) -> FastAPI:
    """Build the API. ``token`` is required on every request (Bearer, or ``?token=`` for assets)."""
    if not token:
        raise ValueError("API token must not be empty")
    state = EngineState(
        settings or config.load_settings(),
        translator_factory=translator_factory,
        complete_fn=complete_fn,
        confirm=confirm,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        state.close()

    app = FastAPI(
        lifespan=lifespan,
        title="Rosetta engine",
        version=__version__,
        dependencies=[Depends(require_token)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.token = token
    app.state.engine = state
    errors.install(app)
    for module in (books, ai, learn, settings_api):
        app.include_router(module.router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    return app

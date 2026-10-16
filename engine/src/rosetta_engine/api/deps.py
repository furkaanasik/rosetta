"""FastAPI dependencies: engine state and bearer-token auth."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, Request

from rosetta_engine.api.errors import ApiError
from rosetta_engine.api.state import EngineState


def engine(request: Request) -> EngineState:
    state: EngineState = request.app.state.engine
    return state


Engine = Annotated[EngineState, Depends(engine)]


def _matches(given: str | None, expected: str) -> bool:
    return given is not None and hmac.compare_digest(given.encode(), expected.encode())


def require_token(request: Request) -> None:
    """``Authorization: Bearer <token>``; asset images may pass ``?token=`` instead."""
    expected: str = request.app.state.token
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and _matches(value.strip(), expected):
        return
    if "/assets/" in request.url.path and _matches(request.query_params.get("token"), expected):
        return
    raise ApiError("unauthorized", "Yetkisiz istek (geçersiz ya da eksik belirteç)")

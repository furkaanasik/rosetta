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


ASSET_ROUTE = "asset"  # the only route that accepts ``?token=`` (for <img src>)


def _is_asset_route(request: Request) -> bool:
    route = request.scope.get("route")
    return getattr(route, "name", None) == ASSET_ROUTE


def require_token(request: Request) -> None:
    """``Authorization: Bearer <token>``; only the asset image route may pass ``?token=``
    (matched by route, not by a substring of the URL)."""
    expected: str = request.app.state.token
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() == "bearer" and _matches(value.strip(), expected):
        return
    if _is_asset_route(request) and _matches(request.query_params.get("token"), expected):
        return
    raise ApiError("unauthorized", "Yetkisiz istek (geçersiz ya da eksik belirteç)")

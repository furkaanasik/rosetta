"""API error model: every failure is ``{"error": {"kind", "message"}}`` with a fixed status."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from rosetta_engine.errors import (
    BudgetExceededError,
    ExtractionError,
    InvalidTranslationError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    RosettaError,
    UsageLimitError,
)

log = logging.getLogger(__name__)

ErrorKind = Literal[
    "bad_request",
    "unauthorized",
    "not_found",
    "expired_token",
    "conflict",
    "busy",
    "invalid",
    "usage_limit",
    "budget",
    "auth",
    "unavailable",
    "internal",
]

STATUS: dict[ErrorKind, int] = {
    "bad_request": 400,
    "unauthorized": 401,
    "not_found": 404,
    "expired_token": 409,
    "conflict": 409,
    "busy": 409,  # another AI operation / job holds the single AI slot; retry later
    "invalid": 422,
    "usage_limit": 429,
    "budget": 402,
    "auth": 401,
    "unavailable": 503,
    "internal": 500,
}


class ApiError(Exception):
    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind: ErrorKind = kind
        self.message = message

    @property
    def status(self) -> int:
        return STATUS[self.kind]


def bad_request(message: str) -> ApiError:
    return ApiError("bad_request", message)


def not_found(message: str) -> ApiError:
    return ApiError("not_found", message)


def body(kind: ErrorKind, message: str) -> JSONResponse:
    return JSONResponse({"error": {"kind": kind, "message": message}}, status_code=STATUS[kind])


def classify(e: BaseException) -> ApiError:
    """Map an engine exception onto the API's error kinds."""
    if isinstance(e, ApiError):
        return e
    if isinstance(e, UsageLimitError):
        return ApiError("usage_limit", f"Claude kullanım limiti: {e}")
    if isinstance(e, BudgetExceededError):
        return ApiError("budget", f"Bütçe sınırı aşıldı: {e}")
    if isinstance(e, ProviderAuthError):
        return ApiError("auth", f"Kimlik doğrulama gerekli: {e}")
    if isinstance(e, ProviderUnavailableError):
        return ApiError("unavailable", f"Sağlayıcı kullanılamıyor: {e}")
    if isinstance(e, InvalidTranslationError) or type(e).__name__.startswith("Invalid"):
        return ApiError("invalid", f"Geçersiz model çıktısı: {e}")
    if isinstance(e, ProviderError):
        return ApiError("unavailable", f"Sağlayıcı hatası: {e}")
    if isinstance(e, ExtractionError):
        return ApiError("bad_request", str(e))
    if isinstance(e, RosettaError):
        return ApiError("bad_request", str(e))
    return ApiError("internal", "Beklenmeyen bir hata oluştu")


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, e: ApiError) -> JSONResponse:
        return body(e.kind, e.message)

    @app.exception_handler(RosettaError)
    async def _engine(_: Request, e: RosettaError) -> JSONResponse:
        err = classify(e)
        return body(err.kind, err.message)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError) -> JSONResponse:
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()))
        return body("bad_request", f"Geçersiz istek: {where} {first.get('msg', '')}".strip())

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException) -> JSONResponse:
        if e.status_code == 404:
            return body("not_found", "Bulunamadı")
        if e.status_code == 405:
            return body("bad_request", "Yöntem desteklenmiyor")
        return body("internal", str(e.detail))

    @app.exception_handler(Exception)
    async def _other(_: Request, e: Exception) -> JSONResponse:
        log.exception("unhandled API error")
        return body("internal", "Beklenmeyen bir hata oluştu")

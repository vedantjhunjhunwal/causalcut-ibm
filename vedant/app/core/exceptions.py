"""Uniform error envelope. Every failure looks the same to the operator UI."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import correlation_id_ctx, get_logger

log = get_logger(__name__)


class CausalCutError(Exception):
    status_code = 500
    error_code = "internal_error"

    def __init__(self, detail: str = "") -> None:
        self.detail = detail
        super().__init__(detail)


class ValidationRejected(CausalCutError):
    status_code = 422
    error_code = "validation_rejected"


class BackpressureError(CausalCutError):
    status_code = 503
    error_code = "backpressure"


class NotFoundError(CausalCutError):
    status_code = 404
    error_code = "not_found"


class UnauthorizedError(CausalCutError):
    status_code = 401
    error_code = "unauthorized"


def _envelope(error: str, detail, status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": error,
            "detail": detail,
            "correlation_id": correlation_id_ctx.get(),
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(CausalCutError)
    async def _domain(_: Request, exc: CausalCutError):
        return _envelope(exc.error_code, exc.detail, exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        # Schema rejection is a safety signal, not noise: a malformed sensor
        # event means an upstream producer is misconfigured.
        log.warning("schema validation failed", extra={"errors": exc.errors()})
        return _envelope("schema_validation_failed", exc.errors(), 422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        return _envelope("http_error", exc.detail, exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("unhandled exception")
        return _envelope("internal_error", "unexpected server error", 500)

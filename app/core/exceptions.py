"""Application-wide exceptions and FastAPI exception handlers.

All custom errors inherit from :class:`AppError`, which carries a stable
``code`` (machine-friendly) and an HTTP status. This lets the API return
a consistent error envelope regardless of where the error is raised.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .logging import get_logger

_log = get_logger(__name__)


class AppError(Exception):
    """Base class for all application errors."""

    code: str = "APP_ERROR"
    status_code: int = 500

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code

    def to_envelope(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
            },
        }


# ---- Concrete error types ---------------------------------------------------
class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422


class FileFormatError(AppError):
    code = "FILE_FORMAT_ERROR"
    status_code = 400


class IngestError(AppError):
    code = "INGEST_ERROR"
    status_code = 500


class ApprovalRequiredError(AppError):
    """Raised when Gold is requested before any relationship is approved."""

    code = "APPROVAL_REQUIRED"
    status_code = 409


class DatabaseError(AppError):
    code = "DATABASE_ERROR"
    status_code = 500


# ---- FastAPI integration ----------------------------------------------------
def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers that translate :class:`AppError` to JSON envelopes."""

    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        _log.warning(
            "AppError code=%s status=%d message=%s details=%s",
            exc.code, exc.status_code, exc.message, exc.details,
        )
        return JSONResponse(status_code=exc.status_code, content=exc.to_envelope())

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        _log.exception("Unhandled exception: %s", exc)
        envelope = {
            "ok": False,
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "details": {"type": type(exc).__name__},
            },
        }
        return JSONResponse(status_code=500, content=envelope)

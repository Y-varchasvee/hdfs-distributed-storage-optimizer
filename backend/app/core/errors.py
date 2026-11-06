"""Application errors and their mapping onto HTTP responses."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailure(AppError):
    status_code = 422
    code = "validation_failed"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"


class IntegrityFailure(AppError):
    """Stored bytes do not match the recorded cryptographic hash, or are missing."""

    status_code = 500
    code = "integrity_failure"


class HdfsError(AppError):
    status_code = 502
    code = "hdfs_error"


class HdfsUnavailable(HdfsError):
    status_code = 503
    code = "hdfs_unavailable"


class HdfsFileNotFound(HdfsError):
    status_code = 404
    code = "hdfs_file_not_found"


class HdfsAlreadyExists(HdfsError):
    status_code = 409
    code = "hdfs_already_exists"


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(HdfsError)
    async def handle_hdfs_error(request: Request, exc: HdfsError) -> JSONResponse:
        # A storage failure on a request that changes state belongs in the audit trail, in its own
        # transaction, because the operation itself has been rolled back.
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            from app.services.audit import record_failure

            try:
                record_failure(
                    request.app.state.ctx.session_factory,
                    "request.failed",
                    f"{request.method} {request.url.path} failed: {exc.message}",
                    details={"code": exc.code, "status": exc.status_code},
                )
            except Exception:  # noqa: BLE001 - failing to log must not hide the original error from the client
                logging.getLogger("hdfs_optimizer").exception("could not record failed request")
        return await handle_app_error(request, exc)

"""Shared API dependencies."""

from __future__ import annotations

from fastapi import Request

from app.core.errors import UnauthorizedError
from app.services.context import AppContext


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def require_token(request: Request) -> None:
    """Local access control. When a token is configured, requests that change state must present it."""
    expected = request.app.state.ctx.settings.api_token
    if expected and request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("x-api-key") != expected:
        raise UnauthorizedError("This action requires a valid X-API-Key header.")

"""Runtime settings persisted in the metadata database, with environment defaults."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.errors import ValidationFailure
from app.models.entities import AppSetting
from app.services.context import AppContext

INGEST_MODES = ("raw", "file", "chunk")


def _defaults(ctx: AppContext) -> dict:
    return {
        "default_ingest_mode": ctx.settings.default_ingest_mode,
        "default_chunk_size": ctx.settings.default_chunk_size,
        "verify_on_write": ctx.settings.verify_on_write,
        # None means "use the cluster's dfs.replication".
        "target_replication": None,
    }


def get_all(ctx: AppContext, session: Session) -> dict:
    values = _defaults(ctx)
    for row in session.query(AppSetting).all():
        if row.key in values:
            values[row.key] = row.value
    return values


def get_value(ctx: AppContext, session: Session, key: str):
    return get_all(ctx, session)[key]


def validate_chunk_size(ctx: AppContext, chunk_size: int) -> int:
    low, high = ctx.settings.min_chunk_size, ctx.settings.max_chunk_size
    if not low <= chunk_size <= high:
        raise ValidationFailure(f"Chunk size must be between {low} and {high} bytes, got {chunk_size}.")
    return chunk_size


def validate_mode(mode: str) -> str:
    if mode not in INGEST_MODES:
        raise ValidationFailure(f"Mode must be one of {', '.join(INGEST_MODES)}, got {mode!r}.")
    return mode


def update(ctx: AppContext, session: Session, changes: dict) -> dict:
    """Validate and save changes. These apply to future writes and never rewrite stored data."""
    if "default_ingest_mode" in changes:
        validate_mode(changes["default_ingest_mode"])
    if "default_chunk_size" in changes:
        validate_chunk_size(ctx, changes["default_chunk_size"])
    if "verify_on_write" in changes and not isinstance(changes["verify_on_write"], bool):
        raise ValidationFailure("verify_on_write must be true or false.")
    allowed = set(_defaults(ctx))
    for key, value in changes.items():
        if key not in allowed:
            raise ValidationFailure(f"Unknown setting: {key}")
        row = session.get(AppSetting, key)
        if row is None:
            session.add(AppSetting(key=key, value=value))
        else:
            row.value = value
    session.flush()
    return get_all(ctx, session)

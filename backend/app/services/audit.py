"""Append-only audit trail."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.core.db import session_scope
from app.models.entities import AuditEvent, PerformanceSample


def record(
    session: Session,
    event_type: str,
    message: str,
    *,
    severity: str = "info",
    entity_type: str | None = None,
    entity_id: str | None = None,
    details: dict | None = None,
) -> None:
    session.add(
        AuditEvent(
            event_type=event_type,
            severity=severity,
            entity_type=entity_type,
            entity_id=entity_id,
            message=message,
            details=details,
        )
    )


def record_failure(factory: sessionmaker[Session], event_type: str, message: str, **kwargs) -> None:
    """Record a failure in its own transaction, so it survives the rollback of the failed operation."""
    with session_scope(factory) as session:
        record(session, event_type, message, severity="error", **kwargs)


def record_sample(
    session: Session,
    operation: str,
    bytes_processed: int,
    duration_ms: float,
    *,
    mode: str | None = None,
    file_id: str | None = None,
) -> None:
    session.add(
        PerformanceSample(
            operation=operation,
            bytes_processed=bytes_processed,
            duration_ms=duration_ms,
            mode=mode,
            file_id=file_id,
        )
    )

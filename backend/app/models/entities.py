"""Relational metadata schema.

Logical files are kept separate from the content they point at. Whether a piece of content is still
needed is always derived from these relations with a query, never from a stored reference counter
that could drift from reality.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, utcnow


def new_id() -> str:
    return uuid.uuid4().hex


class StorageMode(StrEnum):
    RAW = "raw"  # stored as a private copy, with no deduplication (the baseline, and the optimizer's input)
    FILE = "file"  # points at one whole-file content object
    CHUNK = "chunk"  # points at a manifest of ordered shared chunks


class FileStatus(StrEnum):
    ACTIVE = "active"
    DELETED = "deleted"  # recoverable, and still holds its content
    PURGED = "purged"  # no longer holds content; the row remains for audit


class ContentState(StrEnum):
    ACTIVE = "active"
    GC_PENDING = "gc_pending"  # selected for removal; must not gain new references
    REMOVED = "removed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"  # finished, but some items failed
    FAILED = "failed"
    INTERRUPTED = "interrupted"  # the process stopped mid-run; safe to resume


class ContentObject(Base):
    """One unique whole-file blob stored at a content-addressed HDFS path."""

    __tablename__ = "objects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    hdfs_path: Mapped[str] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(16), default=ContentState.ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Chunk(Base):
    """One unique application-level chunk. This is not an HDFS block: each chunk is its own HDFS file."""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    hdfs_path: Mapped[str] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(16), default=ContentState.ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)


class FileManifest(Base):
    """An ordered recipe that rebuilds one distinct content value at one chunk size."""

    __tablename__ = "file_manifests"
    __table_args__ = (UniqueConstraint("file_sha256", "chunk_size", name="uq_manifest_content"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    file_size: Mapped[int] = mapped_column(BigInteger)
    chunk_size: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer)
    manifest_bytes: Mapped[int] = mapped_column(Integer, default=0)
    hdfs_path: Mapped[str] = mapped_column(String(512))
    state: Mapped[str] = mapped_column(String(16), default=ContentState.ACTIVE, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)

    entries: Mapped[list[FileChunk]] = relationship(
        back_populates="manifest",
        order_by="FileChunk.ordinal",
        cascade="all, delete-orphan",
    )


class FileChunk(Base):
    """One position in a manifest. These rows are the authoritative references to chunks."""

    __tablename__ = "file_chunks"
    __table_args__ = (
        UniqueConstraint("manifest_id", "ordinal", name="uq_manifest_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_ordinal_nonnegative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manifest_id: Mapped[str] = mapped_column(ForeignKey("file_manifests.id", ondelete="CASCADE"), index=True)
    chunk_id: Mapped[str] = mapped_column(ForeignKey("chunks.id", ondelete="RESTRICT"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    offset_bytes: Mapped[int] = mapped_column(BigInteger)

    manifest: Mapped[FileManifest] = relationship(back_populates="entries")
    chunk: Mapped[Chunk] = relationship()


class DatasetSource(Base):
    """Provenance for an authentic downloaded file, or for a workload file derived from one."""

    __tablename__ = "dataset_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str | None] = mapped_column(String(255))
    ebook_id: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str | None] = mapped_column(String(512))
    download_url: Mapped[str | None] = mapped_column(String(512))
    organization: Mapped[str | None] = mapped_column(String(255))
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    file_format: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # original | workload_copy | transformed
    derived_from_id: Mapped[str | None] = mapped_column(ForeignKey("dataset_sources.id", ondelete="SET NULL"))
    transformation: Mapped[str | None] = mapped_column(Text)
    local_path: Mapped[str] = mapped_column(String(512))
    license_note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("kind IN ('original','workload_copy','transformed')", name="ck_dataset_kind"),
        CheckConstraint(
            "kind = 'original' OR derived_from_id IS NOT NULL OR transformation IS NOT NULL",
            name="ck_dataset_derived_is_documented",
        ),
    )


class LogicalFile(Base):
    """What a user sees as a file: a name in a folder that resolves to stored content."""

    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint(
            "status = 'purged' OR "
            "(storage_mode = 'raw' AND raw_path IS NOT NULL AND object_id IS NULL AND manifest_id IS NULL) OR "
            "(storage_mode = 'file' AND raw_path IS NULL AND object_id IS NOT NULL AND manifest_id IS NULL) OR "
            "(storage_mode = 'chunk' AND raw_path IS NULL AND object_id IS NULL AND manifest_id IS NOT NULL)",
            name="ck_file_storage_pointer",
        ),
        CheckConstraint("size_bytes >= 0", name="ck_file_size"),
        Index(
            "uq_active_file_name",
            "folder",
            "name",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
        Index("ix_files_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255))
    folder: Mapped[str] = mapped_column(String(512), default="/", index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    extension: Mapped[str | None] = mapped_column(String(32))
    storage_mode: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(8), default=FileStatus.ACTIVE, index=True)

    raw_path: Mapped[str | None] = mapped_column(String(512))
    object_id: Mapped[str | None] = mapped_column(ForeignKey("objects.id", ondelete="RESTRICT"), index=True)
    manifest_id: Mapped[str | None] = mapped_column(ForeignKey("file_manifests.id", ondelete="RESTRICT"), index=True)

    provenance_label: Mapped[str] = mapped_column(String(24), default="user_upload")
    dataset_source_id: Mapped[str | None] = mapped_column(ForeignKey("dataset_sources.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_verified_ok: Mapped[bool | None] = mapped_column(Boolean)

    content_object: Mapped[ContentObject | None] = relationship()
    manifest: Mapped[FileManifest | None] = relationship()
    dataset_source: Mapped[DatasetSource | None] = relationship()


class DeduplicationJob(Base):
    """A tracked background operation."""

    __tablename__ = "deduplication_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(24), index=True)  # analyze | optimize | gc | replication | experiment | ...
    mode: Mapped[str | None] = mapped_column(String(8))
    chunk_size: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED, index=True)
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    resumed_from_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)


class OptimizationHistory(Base):
    """Verified before-and-after record of a completed optimization job."""

    __tablename__ = "optimization_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("deduplication_jobs.id", ondelete="CASCADE"), index=True)
    mode: Mapped[str] = mapped_column(String(8))
    chunk_size: Mapped[int | None] = mapped_column(Integer)
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    files_processed: Mapped[int] = mapped_column(Integer, default=0)
    files_failed: Mapped[int] = mapped_column(Integer, default=0)
    bytes_reclaimed_logical: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class StorageSnapshot(Base):
    """A point-in-time metadata measurement, recorded after each operation that changes storage."""

    __tablename__ = "storage_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    reason: Mapped[str] = mapped_column(String(48))
    logical_files: Mapped[int] = mapped_column(Integer)
    logical_bytes: Mapped[int] = mapped_column(BigInteger)
    stored_bytes: Mapped[int] = mapped_column(BigInteger)
    unique_files: Mapped[int] = mapped_column(Integer)


class PerformanceSample(Base):
    """One measured duration of a real operation."""

    __tablename__ = "performance_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operation: Mapped[str] = mapped_column(String(32), index=True)  # upload | hash | chunking | restore | verify ...
    mode: Mapped[str | None] = mapped_column(String(8))
    bytes_processed: Mapped[int] = mapped_column(BigInteger)
    duration_ms: Mapped[float] = mapped_column(Float)
    file_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class ReplicationOperation(Base):
    __tablename__ = "replication_operations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    previous_factor: Mapped[int | None] = mapped_column(Integer)
    requested_factor: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | applied | verified | timed_out | failed
    files_total: Mapped[int] = mapped_column(Integer, default=0)
    files_changed: Mapped[int] = mapped_column(Integer, default=0)
    space_consumed_before: Mapped[int | None] = mapped_column(BigInteger)
    space_consumed_after: Mapped[int | None] = mapped_column(BigInteger)
    details: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class IntegrityCheck(Base):
    __tablename__ = "integrity_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"), index=True)
    ok: Mapped[bool] = mapped_column(Boolean)
    expected_sha256: Mapped[str] = mapped_column(String(64))
    actual_sha256: Mapped[str | None] = mapped_column(String(64))
    bytes_read: Mapped[int] = mapped_column(BigInteger, default=0)
    chunks_checked: Mapped[int] = mapped_column(Integer, default=0)
    missing: Mapped[list | None] = mapped_column(JSON)
    corrupt: Mapped[list | None] = mapped_column(JSON)
    detail: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    severity: Mapped[str] = mapped_column(String(8), default="info", index=True)  # info | warning | error
    entity_type: Mapped[str | None] = mapped_column(String(24))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSON)


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    scenario: Mapped[str] = mapped_column(String(48), index=True)
    params: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="running")
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    job_id: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | int | str | bool | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

"""Request and response schemas for the REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    folder: str
    size_bytes: int
    sha256: str
    mime_type: str | None
    extension: str | None
    storage_mode: str
    status: str
    provenance_label: str
    created_at: datetime
    deleted_at: datetime | None
    last_verified_at: datetime | None
    last_verified_ok: bool | None
    logical_references: int = 0
    is_duplicate: bool = False


class FilePage(BaseModel):
    items: list[FileOut]
    total: int
    page: int
    page_size: int


class ChunkEntry(BaseModel):
    ordinal: int
    offset_bytes: int
    sha256: str
    size_bytes: int
    shared_by_manifests: int


class IntegrityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_id: str
    ok: bool
    expected_sha256: str
    actual_sha256: str | None
    bytes_read: int
    chunks_checked: int
    missing: list[str] | None
    corrupt: list[str] | None
    detail: str | None
    duration_ms: float
    checked_at: datetime


class FileDetail(FileOut):
    hdfs_paths: list[str]
    same_content_files: list[dict[str, Any]]
    chunk_size: int | None = None
    chunk_count: int | None = None
    chunks: list[ChunkEntry] = []
    integrity_history: list[IntegrityOut] = []
    block_locations: list[dict[str, Any]] | None = None
    dataset_source: dict[str, Any] | None = None


class UploadResult(BaseModel):
    file: FileOut
    outcome: str = Field(description="stored_new, duplicate_reference, chunks_shared or stored_raw")
    duplicate_of_existing: bool
    bytes_written: int
    chunks_total: int
    chunks_new: int
    chunks_reused: int
    hash_ms: float
    store_ms: float
    total_ms: float


class AnalyzeRequest(BaseModel):
    mode: str = Field(description="file or chunk")
    chunk_size: int | None = None


class OptimizeRequest(BaseModel):
    analysis_job_id: str = Field(description="A successful analysis of the current catalog")


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: str
    mode: str | None
    chunk_size: int | None
    status: str
    progress_done: int
    progress_total: int
    message: str | None
    params: dict[str, Any] | None
    result: dict[str, Any] | None
    error: str | None
    resumed_from_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    heartbeat_at: datetime | None


class JobAccepted(BaseModel):
    job_id: str


class ReplicationRequest(BaseModel):
    factor: int = Field(ge=1, le=16)
    acknowledge_reduced_protection: bool = False


class DatasetImportRequest(BaseModel):
    ebook_ids: list[int] | None = None


class DatasetIngestRequest(BaseModel):
    source_ids: list[str]
    copies: int = Field(default=0, ge=0, le=20, description="Exact workload copies per file, labelled as copies")
    mode: str | None = None
    chunk_size: int | None = None
    folder: str = "/datasets"


class ExperimentRequest(BaseModel):
    scenario: str
    options: dict[str, Any] | None = None


class SettingsUpdate(BaseModel):
    default_ingest_mode: str | None = None
    default_chunk_size: int | None = None
    verify_on_write: bool | None = None


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    event_type: str
    severity: str
    entity_type: str | None
    entity_id: str | None
    message: str
    details: dict[str, Any] | None


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int
    page: int
    page_size: int

"""Logical file endpoints: upload, list, inspect, download, delete, restore, verify."""

from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select

from app.api.deps import get_ctx
from app.core.db import session_scope
from app.core.errors import HdfsError, PayloadTooLarge
from app.models.entities import FileChunk, FileStatus, LogicalFile, StorageMode
from app.schemas.api import (
    FileDetail,
    FileOut,
    FilePage,
    IntegrityOut,
    JobAccepted,
    UploadResult,
)
from app.services import content_store, datasets, ingest, integrity, lifecycle
from app.services.context import AppContext

router = APIRouter(prefix="/api/v1/files", tags=["files"])

SORT_COLUMNS = {
    "name": LogicalFile.name,
    "size": LogicalFile.size_bytes,
    "created": LogicalFile.created_at,
    "mode": LogicalFile.storage_mode,
}
COPY_BUFFER = 1024 * 1024


def _reference_counts(session, hashes: list[str]) -> dict[str, int]:
    if not hashes:
        return {}
    return dict(
        session.execute(
            select(LogicalFile.sha256, func.count())
            .where(LogicalFile.sha256.in_(hashes), LogicalFile.status != FileStatus.PURGED)
            .group_by(LogicalFile.sha256)
        ).all()
    )


def _to_out(record: LogicalFile, references: int) -> FileOut:
    out = FileOut.model_validate(record)
    out.logical_references = references
    out.is_duplicate = references > 1
    return out


@router.post("/upload", response_model=UploadResult, status_code=201)
def upload_file(
    file: UploadFile = File(...),
    folder: str = Form("/"),
    mode: str | None = Form(None, description="raw, file or chunk; defaults to the configured mode"),
    chunk_size: int | None = Form(None),
    ctx: AppContext = Depends(get_ctx),
) -> UploadResult:
    """Spool to disk while hashing, so memory use does not grow with file size, then ingest."""
    name = ingest.validate_filename(file.filename)
    folder = ingest.normalize_folder(folder)
    ctx.settings.spool_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    hash_seconds = 0.0
    with tempfile.NamedTemporaryFile(dir=ctx.settings.spool_dir, prefix="upload-", delete=False) as spool:
        spool_path = Path(spool.name)
        try:
            while block := file.file.read(COPY_BUFFER):
                size += len(block)
                if size > ctx.settings.max_upload_bytes:
                    raise PayloadTooLarge(f"Upload exceeds the limit of {ctx.settings.max_upload_bytes} bytes.")
                started = time.perf_counter()
                digest.update(block)
                hash_seconds += time.perf_counter() - started
                spool.write(block)
        except Exception:
            spool_path.unlink(missing_ok=True)
            raise
    try:
        result = ingest.ingest_local_file(
            ctx,
            spool_path,
            name,
            folder=folder,
            mode=mode,
            chunk_size=chunk_size,
            known_hash=(digest.hexdigest(), size),
            known_hash_ms=hash_seconds * 1000,
        )
    finally:
        spool_path.unlink(missing_ok=True)
    with session_scope(ctx.session_factory) as session:
        counts = _reference_counts(session, [result.file.sha256])
        file_out = _to_out(session.get(LogicalFile, result.file.id), counts.get(result.file.sha256, 1))
    return UploadResult(
        file=file_out,
        outcome=result.outcome,
        duplicate_of_existing=result.duplicate_of_existing,
        bytes_written=result.bytes_written,
        chunks_total=result.chunks_total,
        chunks_new=result.chunks_new,
        chunks_reused=result.chunks_reused,
        hash_ms=result.hash_ms,
        store_ms=result.store_ms,
        total_ms=result.total_ms,
    )


@router.get("", response_model=FilePage)
def list_files(
    folder: str | None = None,
    recursive: bool = False,
    q: str | None = Query(None, description="Matches name or SHA-256 prefix"),
    status: str = Query("active", pattern="^(active|deleted)$"),
    mode: str | None = Query(None, pattern="^(raw|file|chunk)$"),
    extension: str | None = None,
    duplicates_only: bool = False,
    sort: str = Query("created", pattern="^(name|size|created|mode)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    ctx: AppContext = Depends(get_ctx),
) -> FilePage:
    with session_scope(ctx.session_factory) as session:
        query = select(LogicalFile).where(LogicalFile.status == status)
        if folder is not None:
            normalized = ingest.normalize_folder(folder)
            if recursive and normalized != "/":
                query = query.where(or_(LogicalFile.folder == normalized, LogicalFile.folder.like(f"{normalized}/%")))
            elif not recursive:
                query = query.where(LogicalFile.folder == normalized)
        if q:
            like = f"%{q.replace('%', '').replace('_', '')}%"
            query = query.where(or_(LogicalFile.name.ilike(like), LogicalFile.sha256.like(f"{q.lower()}%")))
        if mode:
            query = query.where(LogicalFile.storage_mode == mode)
        if extension:
            query = query.where(LogicalFile.extension == extension.lower())
        if duplicates_only:
            duplicated = (
                select(LogicalFile.sha256)
                .where(LogicalFile.status != FileStatus.PURGED)
                .group_by(LogicalFile.sha256)
                .having(func.count() > 1)
            )
            query = query.where(LogicalFile.sha256.in_(duplicated))
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        column = SORT_COLUMNS[sort]
        ordered = column.asc() if order == "asc" else column.desc()
        rows = list(session.scalars(query.order_by(ordered, LogicalFile.id).offset((page - 1) * page_size).limit(page_size)))
        counts = _reference_counts(session, list({r.sha256 for r in rows}))
        return FilePage(
            items=[_to_out(r, counts.get(r.sha256, 1)) for r in rows],
            total=total,
            page=page,
            page_size=page_size,
        )


@router.get("/folders")
def list_folders(ctx: AppContext = Depends(get_ctx)) -> dict:
    """Virtual folders with their direct file counts and sizes."""
    with session_scope(ctx.session_factory) as session:
        rows = session.execute(
            select(LogicalFile.folder, func.count(), func.coalesce(func.sum(LogicalFile.size_bytes), 0))
            .where(LogicalFile.status == FileStatus.ACTIVE)
            .group_by(LogicalFile.folder)
            .order_by(LogicalFile.folder)
        ).all()
    return {"folders": [{"path": path, "files": files, "bytes": size} for path, files, size in rows]}


@router.post("/verify-all", response_model=JobAccepted, status_code=202)
def verify_all(ctx: AppContext = Depends(get_ctx)) -> JobAccepted:
    """Read every active file back from HDFS and compare SHA-256, as a background job."""
    return JobAccepted(job_id=ctx.jobs.submit("verify_all"))


@router.get("/{file_id}", response_model=FileDetail)
def get_file(file_id: str, ctx: AppContext = Depends(get_ctx)) -> FileDetail:
    with session_scope(ctx.session_factory) as session:
        record = integrity.get_file(session, file_id)
        siblings = list(
            session.scalars(
                select(LogicalFile).where(LogicalFile.sha256 == record.sha256, LogicalFile.status != FileStatus.PURGED).order_by(LogicalFile.created_at)
            )
        )
        base = _to_out(record, len(siblings)).model_dump()
        chunks: list[dict] = []
        paths: list[str] = []
        chunk_size = chunk_count = None
        if record.storage_mode == StorageMode.CHUNK:
            manifest = record.manifest
            chunk_size, chunk_count = manifest.chunk_size, manifest.chunk_count
            paths.append(manifest.hdfs_path)
            ordered = content_store.manifest_chunks(session, manifest.id)
            usage = dict(
                session.execute(
                    select(FileChunk.chunk_id, func.count(func.distinct(FileChunk.manifest_id)))
                    .where(FileChunk.chunk_id.in_([c.id for c in ordered[:200]]))
                    .group_by(FileChunk.chunk_id)
                ).all()
            )
            offset = 0
            for index, chunk in enumerate(ordered[:200]):
                chunks.append(
                    {
                        "ordinal": index,
                        "offset_bytes": offset,
                        "sha256": chunk.sha256,
                        "size_bytes": chunk.size_bytes,
                        "shared_by_manifests": usage.get(chunk.id, 1),
                    }
                )
                offset += chunk.size_bytes
        elif record.storage_mode == StorageMode.FILE:
            paths.append(record.content_object.hdfs_path)
        elif record.raw_path:
            paths.append(record.raw_path)

        locations = None
        try:
            if paths and record.storage_mode != StorageMode.CHUNK:
                locations = [
                    {"block_id": b.block_id, "length": b.length, "hosts": list(b.hosts), "corrupt": b.corrupt}
                    for b in ctx.hdfs.block_locations(paths[0])
                ]
        except HdfsError:
            locations = None  # the detail view must still open when HDFS is down

        return FileDetail(
            **base,
            hdfs_paths=paths,
            same_content_files=[
                {"id": s.id, "name": s.name, "folder": s.folder, "status": s.status, "provenance_label": s.provenance_label}
                for s in siblings
                if s.id != record.id
            ],
            chunk_size=chunk_size,
            chunk_count=chunk_count,
            chunks=chunks,
            integrity_history=[IntegrityOut.model_validate(c) for c in integrity.latest_checks(session, file_id)],
            block_locations=locations,
            dataset_source=datasets.source_dict(record.dataset_source) if record.dataset_source else None,
        )


@router.get("/{file_id}/download")
def download_file(file_id: str, ctx: AppContext = Depends(get_ctx)) -> StreamingResponse:
    with session_scope(ctx.session_factory) as session:
        record = integrity.get_file(session, file_id)
        integrity.preflight(ctx, session, record)
        name, size, sha, mime = record.name, record.size_bytes, record.sha256, record.mime_type
    return StreamingResponse(
        integrity.stream_verified(ctx, file_id),
        media_type=mime or "application/octet-stream",
        headers={
            "Content-Length": str(size),
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
            "X-Content-SHA256": sha,
        },
    )


@router.delete("/{file_id}")
def delete_file(file_id: str, permanent: bool = False, ctx: AppContext = Depends(get_ctx)) -> dict:
    """Soft delete by default. ``permanent`` applies only to an already-deleted file."""
    if permanent:
        gc_report = lifecycle.purge(ctx, file_id)
        return {
            "status": "purged",
            "content_removed": {k: gc_report[k] for k in ("object_count", "manifest_count", "chunk_count", "reclaimable_bytes")},
        }
    record = lifecycle.soft_delete(ctx, file_id)
    return {"status": "deleted", "id": record.id, "recoverable": True}


@router.post("/{file_id}/restore")
def restore_file(file_id: str, ctx: AppContext = Depends(get_ctx)) -> dict:
    record = lifecycle.restore(ctx, file_id)
    return {"status": record.status, "id": record.id, "name": record.name}


@router.post("/{file_id}/verify", response_model=IntegrityOut)
def verify_file(file_id: str, ctx: AppContext = Depends(get_ctx)) -> IntegrityOut:
    check = integrity.verify_file(ctx, file_id)
    return IntegrityOut.model_validate(check)


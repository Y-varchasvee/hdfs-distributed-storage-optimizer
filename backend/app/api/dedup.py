"""Duplicate analysis, optimization jobs and garbage collection."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import get_ctx
from app.core.db import session_scope
from app.core.errors import ConflictError, NotFoundError
from app.models.entities import (
    Chunk,
    ContentState,
    DeduplicationJob,
    FileChunk,
    FileManifest,
    FileStatus,
    JobStatus,
    LogicalFile,
    StorageMode,
)
from app.schemas.api import AnalyzeRequest, JobAccepted, JobOut, OptimizeRequest
from app.services import lifecycle, optimizer
from app.services.context import AppContext

router = APIRouter(prefix="/api/v1/dedup", tags=["deduplication"])

CHUNK_MAP_CELLS = 240


def _groups(ctx: AppContext, limit: int) -> dict:
    """Exact duplicates: logical files with the same SHA-256, regardless of name."""
    with session_scope(ctx.session_factory) as session:
        grouped = session.execute(
            select(LogicalFile.sha256, func.count().label("copies"), func.max(LogicalFile.size_bytes).label("size"))
            .where(LogicalFile.status == FileStatus.ACTIVE)
            .group_by(LogicalFile.sha256)
            .having(func.count() > 1)
            .order_by((func.max(LogicalFile.size_bytes) * (func.count() - 1)).desc())
        ).all()
        groups = []
        for sha, copies, size in grouped[:limit]:
            members = list(
                session.scalars(
                    select(LogicalFile).where(LogicalFile.sha256 == sha, LogicalFile.status == FileStatus.ACTIVE).order_by(LogicalFile.created_at)
                )
            )
            raw_members = sum(1 for m in members if m.storage_mode == StorageMode.RAW)
            stored_forms = raw_members + (1 if raw_members < len(members) else 0)
            groups.append(
                {
                    "sha256": sha,
                    "copies": copies,
                    "size_bytes": size,
                    "logical_bytes": size * copies,
                    "redundant_logical_bytes": size * (copies - 1),
                    # Bytes optimization could still free. Zero once the group is already deduplicated.
                    "reclaimable_bytes": size * max(stored_forms - 1, 0),
                    "already_deduplicated": stored_forms <= 1,
                    "members": [
                        {
                            "id": m.id,
                            "name": m.name,
                            "folder": m.folder,
                            "storage_mode": m.storage_mode,
                            "provenance_label": m.provenance_label,
                            "created_at": m.created_at,
                        }
                        for m in members
                    ],
                }
            )
        return {
            "group_count": len(grouped),
            "duplicate_files": sum(copies - 1 for _, copies, _ in grouped),
            "redundant_logical_bytes": sum(size * (copies - 1) for _, copies, size in grouped),
            "groups": groups,
        }


@router.get("/groups")
def duplicate_groups(limit: int = Query(100, ge=1, le=500), ctx: AppContext = Depends(get_ctx)) -> dict:
    return _groups(ctx, limit)


@router.get("/duplicates")
def duplicates(limit: int = Query(100, ge=1, le=500), ctx: AppContext = Depends(get_ctx)) -> dict:
    data = _groups(ctx, limit)
    return {"duplicate_files": data["duplicate_files"], "groups": data["groups"]}


@router.get("/shared-chunks")
def shared_chunks(limit: int = Query(100, ge=1, le=500), ctx: AppContext = Depends(get_ctx)) -> dict:
    """Chunks used by more than one manifest: shared content inside files that are not identical overall."""
    with session_scope(ctx.session_factory) as session:
        shared = session.execute(
            select(Chunk.sha256, Chunk.size_bytes, func.count(func.distinct(FileChunk.manifest_id)).label("manifests"), func.count().label("references"))
            .join(FileChunk, FileChunk.chunk_id == Chunk.id)
            .join(FileManifest, FileManifest.id == FileChunk.manifest_id)
            .where(Chunk.state == ContentState.ACTIVE, FileManifest.state == ContentState.ACTIVE)
            .group_by(Chunk.id)
            .having(func.count() > 1)
            .order_by(func.count().desc())
        ).all()
        manifests = list(
            session.scalars(select(FileManifest).where(FileManifest.state == ContentState.ACTIVE).order_by(FileManifest.created_at))
        )
        usage = dict(
            session.execute(
                select(FileChunk.chunk_id, func.count(func.distinct(FileChunk.manifest_id)))
                .join(FileManifest, FileManifest.id == FileChunk.manifest_id)
                .where(FileManifest.state == ContentState.ACTIVE)
                .group_by(FileChunk.chunk_id)
            ).all()
        )
        map_rows = []
        for manifest in manifests[:limit]:
            names = list(
                session.scalars(
                    select(LogicalFile.name).where(LogicalFile.manifest_id == manifest.id, LogicalFile.status == FileStatus.ACTIVE)
                )
            )
            cells = list(
                session.scalars(
                    select(FileChunk.chunk_id)
                    .where(FileChunk.manifest_id == manifest.id)
                    .order_by(FileChunk.ordinal)
                    .limit(CHUNK_MAP_CELLS)
                )
            )
            map_rows.append(
                {
                    "id": manifest.id,
                    "file_sha256": manifest.file_sha256,
                    "file_size": manifest.file_size,
                    "chunk_size": manifest.chunk_size,
                    "chunk_count": manifest.chunk_count,
                    "logical_files": names,
                    # True where another distinct manifest also uses this chunk.
                    "chunk_map": [usage.get(chunk_id, 1) > 1 for chunk_id in cells],
                }
            )
        return {
            "shared_chunk_count": len(shared),
            "bytes_saved_by_sharing": sum(size * (references - 1) for _, size, _, references in shared),
            "chunks": [
                {"sha256": sha, "size_bytes": size, "manifests": count, "references": references}
                for sha, size, count, references in shared[:limit]
            ],
            "manifests": map_rows,
            "chunk_map_limit": CHUNK_MAP_CELLS,
        }


@router.post("/analyze", response_model=JobAccepted, status_code=202)
def analyze(body: AnalyzeRequest, ctx: AppContext = Depends(get_ctx)) -> JobAccepted:
    """Dry run. Reports estimated savings and changes nothing in HDFS."""
    mode, chunk_size = optimizer.validate_mode(ctx, body.mode, body.chunk_size)
    return JobAccepted(job_id=ctx.jobs.submit("analyze", mode=mode, chunk_size=chunk_size))


@router.post("/optimize", response_model=JobAccepted, status_code=202)
def optimize(body: OptimizeRequest, ctx: AppContext = Depends(get_ctx)) -> JobAccepted:
    """Start optimization. Requires a successful preview of the catalog exactly as it is now."""
    analysis = optimizer.validate_analysis_for_optimize(ctx, body.analysis_job_id)
    params = {"analysis_job_id": analysis.id}
    return JobAccepted(job_id=ctx.jobs.submit("optimize", mode=analysis.mode, chunk_size=analysis.chunk_size, params=params))


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    kind: str | None = None,
    limit: int = Query(30, ge=1, le=200),
    ctx: AppContext = Depends(get_ctx),
) -> list[JobOut]:
    with session_scope(ctx.session_factory) as session:
        query = select(DeduplicationJob)
        if kind:
            query = query.where(DeduplicationJob.kind == kind)
        rows = session.scalars(query.order_by(DeduplicationJob.created_at.desc()).limit(limit))
        return [JobOut.model_validate(row) for row in rows]


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, ctx: AppContext = Depends(get_ctx)) -> JobOut:
    with session_scope(ctx.session_factory) as session:
        job = session.get(DeduplicationJob, job_id)
        if job is None:
            raise NotFoundError(f"No job with id {job_id}.")
        return JobOut.model_validate(job)


@router.post("/jobs/{job_id}/resume", response_model=JobAccepted, status_code=202)
def resume_job(job_id: str, ctx: AppContext = Depends(get_ctx)) -> JobAccepted:
    """Run an interrupted or failed optimization again. Finished files are not eligible, so none repeat."""
    with session_scope(ctx.session_factory) as session:
        job = session.get(DeduplicationJob, job_id)
        if job is None or job.kind != "optimize":
            raise NotFoundError(f"No optimization job with id {job_id}.")
        if job.status not in (JobStatus.INTERRUPTED, JobStatus.FAILED, JobStatus.PARTIAL):
            raise ConflictError(f"Only an interrupted, failed or partial job can be resumed; this one is {job.status}.")
        mode, chunk_size = job.mode, job.chunk_size
    return JobAccepted(job_id=ctx.jobs.submit("optimize", mode=mode, chunk_size=chunk_size, resumed_from_id=job_id))


@router.get("/gc")
def preview_garbage(ctx: AppContext = Depends(get_ctx)) -> dict:
    return lifecycle.collect_garbage(ctx, dry_run=True)


@router.post("/gc")
def run_garbage_collection(ctx: AppContext = Depends(get_ctx)) -> dict:
    return lifecycle.collect_garbage(ctx)

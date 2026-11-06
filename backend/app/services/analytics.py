"""Storage metrics. Each number states whether the database derived it or HDFS measured it.

    Savings (%)          = (Original Logical Bytes - Stored Content Bytes) / Original Logical Bytes x 100
    Deduplication Ratio  = Original Logical Bytes / Stored Content Bytes

Both are undefined (None) when their denominator is zero.
"""

from __future__ import annotations

from sqlalchemy import case, distinct, func, select
from sqlalchemy.orm import Session

from app.core.errors import HdfsError
from app.models.entities import (
    Chunk,
    ContentObject,
    ContentState,
    FileChunk,
    FileManifest,
    FileStatus,
    IntegrityCheck,
    LogicalFile,
    OptimizationHistory,
    PerformanceSample,
    StorageMode,
    StorageSnapshot,
)
from app.services import settings_store
from app.services.context import AppContext


def savings_percent(logical: int, stored: int) -> float | None:
    return None if logical <= 0 else (logical - stored) / logical * 100


def dedup_ratio(logical: int, stored: int) -> float | None:
    return None if stored <= 0 else logical / stored


def storage_statistics(session: Session) -> dict:
    """Values derived from metadata relations, describing application-level content."""
    active = LogicalFile.status == FileStatus.ACTIVE
    logical_files, logical_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(LogicalFile.size_bytes), 0)).where(active)
    ).one()
    deleted_files, deleted_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(LogicalFile.size_bytes), 0)).where(
            LogicalFile.status == FileStatus.DELETED
        )
    ).one()

    distinct_contents = select(LogicalFile.sha256, func.max(LogicalFile.size_bytes).label("size")).where(active).group_by(LogicalFile.sha256).subquery()
    unique_files, unique_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(distinct_contents.c.size), 0))
    ).one()

    raw_files, raw_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(LogicalFile.size_bytes), 0)).where(
            LogicalFile.storage_mode == StorageMode.RAW, LogicalFile.status != FileStatus.PURGED
        )
    ).one()
    object_count, object_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(ContentObject.size_bytes), 0)).where(
            ContentObject.state == ContentState.ACTIVE
        )
    ).one()
    chunk_count, chunk_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(Chunk.size_bytes), 0)).where(Chunk.state == ContentState.ACTIVE)
    ).one()
    manifest_count, manifest_bytes = session.execute(
        select(func.count(), func.coalesce(func.sum(FileManifest.manifest_bytes), 0)).where(
            FileManifest.state == ContentState.ACTIVE
        )
    ).one()
    chunk_references = session.scalar(
        select(func.count())
        .select_from(FileChunk)
        .join(FileManifest, FileManifest.id == FileChunk.manifest_id)
        .where(FileManifest.state == ContentState.ACTIVE)
    )
    referenced_chunks = session.scalar(
        select(func.count(distinct(FileChunk.chunk_id)))
        .join(FileManifest, FileManifest.id == FileChunk.manifest_id)
        .where(FileManifest.state == ContentState.ACTIVE)
    )
    by_mode = dict(
        session.execute(select(LogicalFile.storage_mode, func.count()).where(active).group_by(LogicalFile.storage_mode)).all()
    )

    stored = raw_bytes + object_bytes + chunk_bytes
    return {
        "logical_files": logical_files,
        "logical_bytes": logical_bytes,
        "unique_files": unique_files,
        "unique_content_bytes": unique_bytes,
        "duplicate_files": logical_files - unique_files,
        "deleted_retained_files": deleted_files,
        "deleted_retained_bytes": deleted_bytes,
        "raw_files": raw_files,
        "raw_bytes": raw_bytes,
        "object_count": object_count,
        "object_bytes": object_bytes,
        "chunk_count": chunk_count,
        "chunk_bytes": chunk_bytes,
        "manifest_count": manifest_count,
        "manifest_bytes": manifest_bytes,
        "chunk_references": chunk_references,
        "duplicate_chunk_references": chunk_references - referenced_chunks,
        "stored_content_bytes": stored,
        "bytes_avoided": logical_bytes - stored,
        "savings_percent": savings_percent(logical_bytes, stored),
        "dedup_ratio": dedup_ratio(logical_bytes, stored),
        "files_by_mode": by_mode,
    }


def measured_hdfs(ctx: AppContext) -> dict:
    """Values the NameNode reports for the managed namespace. spaceConsumed includes replication."""
    try:
        summary = ctx.hdfs.content_summary(ctx.paths.root)
        areas = {}
        for name, path in (
            ("objects", ctx.paths.objects),
            ("chunks", ctx.paths.chunks),
            ("manifests", ctx.paths.manifests),
            ("raw", ctx.paths.raw),
            ("staging", ctx.paths.staging),
            ("recovery", ctx.paths.recovery),
        ):
            area = ctx.hdfs.content_summary(path)
            areas[name] = {
                "length": area.length,
                "space_consumed": area.space_consumed,
                "file_count": area.file_count,
            }
    except HdfsError as exc:
        return {"available": False, "error": exc.message}
    return {
        "available": True,
        "length": summary.length,
        "space_consumed": summary.space_consumed,
        "file_count": summary.file_count,
        "directory_count": summary.directory_count,
        "areas": areas,
    }


def full_statistics(ctx: AppContext, session: Session) -> dict:
    stats = storage_statistics(session)
    measured = measured_hdfs(ctx)
    target = settings_store.get_value(ctx, session, "target_replication")
    factor = target
    if factor is None:
        try:
            factor = ctx.hdfs.default_replication()
        except HdfsError:
            factor = None
    return {
        "derived": stats,
        "measured": measured,
        "estimated": {
            "replication_factor": factor,
            "replication_adjusted_bytes": None if factor is None else stats["stored_content_bytes"] * factor,
            "note": "Stored content multiplied by the replication factor. This excludes block checksums and "
            "filesystem overhead; see the measured values for what the cluster reports.",
        },
    }


def record_snapshot(session: Session, reason: str) -> None:
    session.flush()
    stats = storage_statistics(session)
    session.add(
        StorageSnapshot(
            reason=reason,
            logical_files=stats["logical_files"],
            logical_bytes=stats["logical_bytes"],
            stored_bytes=stats["stored_content_bytes"],
            unique_files=stats["unique_files"],
        )
    )


def history(session: Session, limit: int = 500) -> list[dict]:
    rows = list(session.scalars(select(StorageSnapshot).order_by(StorageSnapshot.taken_at.desc(), StorageSnapshot.id.desc()).limit(limit)))
    rows.reverse()
    return [
        {
            "taken_at": row.taken_at,
            "reason": row.reason,
            "logical_files": row.logical_files,
            "logical_bytes": row.logical_bytes,
            "stored_bytes": row.stored_bytes,
            "unique_files": row.unique_files,
            "saved_bytes": row.logical_bytes - row.stored_bytes,
            "savings_percent": savings_percent(row.logical_bytes, row.stored_bytes),
        }
        for row in rows
    ]


def distributions(session: Session) -> dict:
    active = LogicalFile.status == FileStatus.ACTIVE
    by_type = session.execute(
        select(
            func.coalesce(LogicalFile.extension, "none"),
            func.count(),
            func.coalesce(func.sum(LogicalFile.size_bytes), 0),
        )
        .where(active)
        .group_by(LogicalFile.extension)
        .order_by(func.sum(LogicalFile.size_bytes).desc())
    ).all()
    groups = session.execute(select(func.count()).where(active).group_by(LogicalFile.sha256)).all()
    histogram: dict[int, int] = {}
    for (copies,) in groups:
        histogram[copies] = histogram.get(copies, 0) + 1
    upload_day = func.date(LogicalFile.created_at)
    uploads = session.execute(
        select(upload_day, func.count(), func.coalesce(func.sum(LogicalFile.size_bytes), 0))
        .where(LogicalFile.status != FileStatus.PURGED)
        .group_by(upload_day)
        .order_by(upload_day)
    ).all()
    return {
        "file_types": [{"extension": ext, "files": files, "bytes": size} for ext, files, size in by_type],
        "duplicate_distribution": [{"copies": copies, "groups": histogram[copies]} for copies in sorted(histogram)],
        "upload_trend": [{"day": day, "files": files, "bytes": size} for day, files, size in uploads],
    }


def optimization_history(session: Session, limit: int = 50) -> list[dict]:
    rows = session.scalars(select(OptimizationHistory).order_by(OptimizationHistory.created_at.desc()).limit(limit))
    return [
        {
            "job_id": row.job_id,
            "mode": row.mode,
            "chunk_size": row.chunk_size,
            "before": row.before,
            "after": row.after,
            "files_processed": row.files_processed,
            "files_failed": row.files_failed,
            "bytes_reclaimed_logical": row.bytes_reclaimed_logical,
            "duration_ms": row.duration_ms,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def performance(session: Session) -> dict:
    """Aggregates over measured samples. Throughput is total bytes divided by total time."""
    rows = session.execute(
        select(
            PerformanceSample.operation,
            PerformanceSample.mode,
            func.count(),
            func.sum(PerformanceSample.bytes_processed),
            func.sum(PerformanceSample.duration_ms),
            func.min(PerformanceSample.duration_ms),
            func.max(PerformanceSample.duration_ms),
        ).group_by(PerformanceSample.operation, PerformanceSample.mode)
    ).all()
    operations = [
        {
            "operation": op,
            "mode": mode,
            "samples": count,
            "bytes": total_bytes,
            "total_ms": total_ms,
            "min_ms": low,
            "max_ms": high,
            "mean_ms": total_ms / count,
            "throughput_mib_s": (total_bytes / (1024 * 1024)) / (total_ms / 1000) if total_ms else None,
        }
        for op, mode, count, total_bytes, total_ms, low, high in rows
    ]
    return {"operations": operations, "integrity": integrity_summary(session)}


def integrity_summary(session: Session) -> dict:
    total, passed = session.execute(
        select(func.count(), func.coalesce(func.sum(case((IntegrityCheck.ok.is_(True), 1), else_=0)), 0))
    ).one()
    verified_files = session.scalar(
        select(func.count()).select_from(LogicalFile).where(
            LogicalFile.status == FileStatus.ACTIVE, LogicalFile.last_verified_ok.is_(True)
        )
    )
    failed_files = session.scalar(
        select(func.count()).select_from(LogicalFile).where(
            LogicalFile.status == FileStatus.ACTIVE, LogicalFile.last_verified_ok.is_(False)
        )
    )
    active_files = session.scalar(select(func.count()).select_from(LogicalFile).where(LogicalFile.status == FileStatus.ACTIVE))
    return {
        "checks_total": total,
        "checks_passed": passed,
        "checks_failed": total - passed,
        "files_verified_ok": verified_files,
        "files_verified_failed": failed_files,
        "files_never_verified": active_files - verified_files - failed_files,
    }

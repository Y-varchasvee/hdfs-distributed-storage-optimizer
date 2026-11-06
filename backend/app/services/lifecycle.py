"""Reference-aware deletion, restoration, garbage collection and crash recovery.

Deleting a logical file never touches shared content directly. Content is removed only by the
collector, and only when a query over the current relations proves nothing still refers to it.
A soft-deleted file keeps its content, because it can still be restored.
"""

from __future__ import annotations

import posixpath
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import session_scope, utcnow
from app.core.errors import ConflictError, HdfsError
from app.hdfs.base import walk_files
from app.models.entities import (
    Chunk,
    ContentObject,
    ContentState,
    DeduplicationJob,
    FileChunk,
    FileManifest,
    FileStatus,
    JobStatus,
    LogicalFile,
    StorageMode,
)
from app.services import analytics, audit
from app.services.content_store import parent_of
from app.services.context import AppContext
from app.services.ingest import unique_name
from app.services.integrity import get_file


def soft_delete(ctx: AppContext, file_id: str) -> LogicalFile:
    """Recoverable delete. A private raw copy moves to the recovery area; shared content stays in place."""
    with ctx.content_lock, session_scope(ctx.session_factory) as session:
        record = get_file(session, file_id)
        if record.status == FileStatus.DELETED:
            raise ConflictError(f"{record.name} is already deleted.")
        if record.storage_mode == StorageMode.RAW:
            target = ctx.paths.recovery_raw_path(record.id)
            ctx.hdfs.mkdirs(parent_of(target))
            if not ctx.hdfs.rename(record.raw_path, target):
                raise HdfsError(f"Could not move {record.raw_path} to the recovery area.")
            record.raw_path = target
        record.status = FileStatus.DELETED
        record.deleted_at = utcnow()
        audit.record(session, "file.deleted", f"Deleted {record.name} (recoverable).", entity_type="file", entity_id=record.id)
        analytics.record_snapshot(session, "delete")
    return record


def restore(ctx: AppContext, file_id: str) -> LogicalFile:
    with ctx.content_lock, session_scope(ctx.session_factory) as session:
        record = get_file(session, file_id)
        if record.status != FileStatus.DELETED:
            raise ConflictError(f"{record.name} is not deleted.")
        if record.storage_mode == StorageMode.RAW:
            target = ctx.paths.raw_path(record.id)
            ctx.hdfs.mkdirs(parent_of(target))
            if not ctx.hdfs.rename(record.raw_path, target):
                raise HdfsError(f"Could not restore {record.raw_path}.")
            record.raw_path = target
        original = record.name
        record.name = unique_name(session, record.folder, original)
        record.status = FileStatus.ACTIVE
        record.deleted_at = None
        audit.record(
            session,
            "file.restored",
            f"Restored {original}" + (f" as {record.name}." if record.name != original else "."),
            entity_type="file",
            entity_id=record.id,
        )
        analytics.record_snapshot(session, "restore")
    return record


def purge(ctx: AppContext, file_id: str) -> dict:
    """Permanently remove a soft-deleted file. Shared content stays while anything else refers to it."""
    with ctx.content_lock:
        with session_scope(ctx.session_factory) as session:
            record = get_file(session, file_id)
            if record.status != FileStatus.DELETED:
                raise ConflictError("Only a deleted file can be permanently removed. Delete it first.")
            raw_path = record.raw_path
            record.status = FileStatus.PURGED
            record.purged_at = utcnow()
            record.raw_path = None
            record.object_id = None
            record.manifest_id = None
            audit.record(session, "file.purged", f"Permanently removed {record.name}.", entity_type="file", entity_id=record.id)
        # The commit above came first, so a crash here leaves an orphan for reconciliation, never a dangling pointer.
        if raw_path:
            ctx.hdfs.delete(raw_path)
        return collect_garbage(ctx)


@dataclass
class GarbageReport:
    objects: list[str] = field(default_factory=list)
    manifests: list[str] = field(default_factory=list)
    chunks: list[str] = field(default_factory=list)
    reclaimable_bytes: int = 0
    removed: bool = False

    def as_dict(self) -> dict:
        data = asdict(self)
        data["object_count"] = len(self.objects)
        data["manifest_count"] = len(self.manifests)
        data["chunk_count"] = len(self.chunks)
        return data


def _find_garbage(session: Session) -> tuple[list[ContentObject], list[FileManifest], list[Chunk]]:
    holds_content = LogicalFile.status != FileStatus.PURGED
    objects = list(
        session.scalars(
            select(ContentObject).where(
                ContentObject.state == ContentState.ACTIVE,
                ContentObject.id.not_in(
                    select(LogicalFile.object_id).where(holds_content, LogicalFile.object_id.is_not(None))
                ),
            )
        )
    )
    referenced_manifests = select(LogicalFile.manifest_id).where(holds_content, LogicalFile.manifest_id.is_not(None))
    manifests = list(
        session.scalars(
            select(FileManifest).where(FileManifest.state == ContentState.ACTIVE, FileManifest.id.not_in(referenced_manifests))
        )
    )
    # A chunk is live while any manifest that survives this collection uses it.
    chunks = list(
        session.scalars(
            select(Chunk).where(
                Chunk.state == ContentState.ACTIVE,
                Chunk.id.not_in(
                    select(FileChunk.chunk_id)
                    .join(FileManifest, FileManifest.id == FileChunk.manifest_id)
                    .where(FileManifest.state == ContentState.ACTIVE, FileManifest.id.in_(referenced_manifests))
                ),
            )
        )
    )
    return objects, manifests, chunks


def collect_garbage(ctx: AppContext, *, dry_run: bool = False) -> dict:
    """Remove only content that no restorable file refers to. Dry-run reports without changing anything."""
    with ctx.content_lock:
        with session_scope(ctx.session_factory) as session:
            objects, manifests, chunks = _find_garbage(session)
            report = GarbageReport(
                objects=[o.sha256 for o in objects],
                manifests=[m.file_sha256 for m in manifests],
                chunks=[c.sha256 for c in chunks],
                reclaimable_bytes=sum(o.size_bytes for o in objects) + sum(c.size_bytes for c in chunks),
            )
            if dry_run or not (objects or manifests or chunks):
                return report.as_dict()
            # Mark first: from here, an interrupted run is finished by recover_on_startup.
            for row in [*objects, *manifests, *chunks]:
                row.state = ContentState.GC_PENDING
        _finish_pending_removals(ctx)
        with session_scope(ctx.session_factory) as session:
            audit.record(
                session,
                "storage.gc",
                f"Removed {len(report.objects)} objects, {len(report.manifests)} manifests and "
                f"{len(report.chunks)} chunks that nothing refers to ({report.reclaimable_bytes} bytes before replication).",
                details={k: len(getattr(report, k)) for k in ("objects", "manifests", "chunks")},
            )
            analytics.record_snapshot(session, "gc")
        report.removed = True
        return report.as_dict()


def _finish_pending_removals(ctx: AppContext) -> None:
    with session_scope(ctx.session_factory) as session:
        for model in (ContentObject, FileManifest, Chunk):
            for row in session.scalars(select(model).where(model.state == ContentState.GC_PENDING)):
                ctx.hdfs.delete(row.hdfs_path)
                row.state = ContentState.REMOVED
                row.removed_at = utcnow()
                if model is FileManifest:
                    row.entries.clear()


def recover_on_startup(ctx: AppContext) -> dict:
    """Bring metadata and HDFS back to a consistent state after an unclean stop."""
    summary = {"jobs_interrupted": 0, "staging_removed": 0, "pending_gc": "skipped", "hdfs_available": True}
    with session_scope(ctx.session_factory) as session:
        stale = session.scalars(
            select(DeduplicationJob).where(DeduplicationJob.status.in_([JobStatus.RUNNING, JobStatus.QUEUED]))
        )
        for job in stale:
            job.status = JobStatus.INTERRUPTED
            job.finished_at = utcnow()
            job.message = "The server stopped while this job was active. Completed files are safe; it can be resumed."
            summary["jobs_interrupted"] += 1
            audit.record(session, "job.interrupted", f"Job {job.id} ({job.kind}) was interrupted.", severity="warning", entity_type="job", entity_id=job.id)
    try:
        ctx.ensure_namespace()
        with ctx.content_lock:
            _finish_pending_removals(ctx)
            summary["pending_gc"] = "finished"
            for entry in ctx.hdfs.list_dir(ctx.paths.staging):
                ctx.hdfs.delete(entry.path, recursive=True)
                summary["staging_removed"] += 1
    except HdfsError as exc:
        # Starting without HDFS is allowed: the UI must be able to report that the cluster is down.
        summary["hdfs_available"] = False
        summary["error"] = exc.message
    return summary


def reconcile(ctx: AppContext, *, apply: bool = False) -> dict:
    """Compare HDFS with the metadata. Orphans are quarantined, never deleted, and only when apply=True."""
    with ctx.content_lock, session_scope(ctx.session_factory) as session:
        expected: set[str] = set()
        expected.update(session.scalars(select(ContentObject.hdfs_path).where(ContentObject.state == ContentState.ACTIVE)))
        expected.update(session.scalars(select(Chunk.hdfs_path).where(Chunk.state == ContentState.ACTIVE)))
        expected.update(session.scalars(select(FileManifest.hdfs_path).where(FileManifest.state == ContentState.ACTIVE)))
        expected.update(
            path
            for path in session.scalars(select(LogicalFile.raw_path).where(LogicalFile.status != FileStatus.PURGED, LogicalFile.raw_path.is_not(None)))
        )
        present: set[str] = set()
        for area in (ctx.paths.objects, ctx.paths.chunks, ctx.paths.manifests, ctx.paths.raw, f"{ctx.paths.recovery}/deleted"):
            present.update(status.path for status in walk_files(ctx.hdfs, area))
        orphans = sorted(present - expected)
        missing = sorted(expected - present)
        moved = 0
        if apply:
            for path in orphans:
                target = ctx.paths.recovery_orphan_path(posixpath.basename(path))
                ctx.hdfs.mkdirs(parent_of(target))
                if ctx.hdfs.rename(path, target):
                    moved += 1
            audit.record(session, "storage.reconciled", f"Quarantined {moved} orphaned HDFS files.", details={"missing": len(missing)})
        return {
            "paths_expected": len(expected),
            "paths_present": len(present),
            "orphans": orphans[:200],
            "orphan_count": len(orphans),
            "missing": missing[:200],
            "missing_count": len(missing),
            "orphans_quarantined": moved,
        }

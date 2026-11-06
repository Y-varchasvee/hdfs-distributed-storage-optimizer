"""Analysis (dry run) and safe optimization.

Analysis reads and changes nothing permanently: it reports estimated savings. Optimization converts one
file at a time, always in this order:

    1. make the deduplicated form durable in HDFS and verify it against the file's SHA-256
    2. commit the file's new pointer
    3. only then remove the old copy

Every file is its own unit of work, so an interrupted job loses nothing and can simply be run again.
"""

from __future__ import annotations

import hashlib
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.errors import (
    ConflictError,
    HdfsError,
    HdfsUnavailable,
    IntegrityFailure,
    NotFoundError,
    ValidationFailure,
)
from app.models.entities import (
    Chunk,
    ContentObject,
    ContentState,
    DeduplicationJob,
    FileStatus,
    JobStatus,
    LogicalFile,
    OptimizationHistory,
    StorageMode,
)
from app.services import analytics, audit, content_store, lifecycle, settings_store
from app.services.content_store import parent_of
from app.services.context import AppContext
from app.services.hashing import fixed_size_chunks, sha256_bytes, sha256_stream


def eligible_query(mode: str):
    sources = [StorageMode.RAW] if mode == StorageMode.FILE else [StorageMode.RAW, StorageMode.FILE]
    return select(LogicalFile).where(LogicalFile.status == FileStatus.ACTIVE, LogicalFile.storage_mode.in_(sources))


def catalog_fingerprint(session: Session) -> str:
    """Changes whenever the set of files or their storage changes, which invalidates an earlier preview."""
    count, total, latest = session.execute(
        select(func.count(), func.coalesce(func.sum(LogicalFile.size_bytes), 0), func.max(LogicalFile.updated_at)).where(
            LogicalFile.status != FileStatus.PURGED
        )
    ).one()
    return hashlib.sha256(f"{count}|{total}|{latest}".encode()).hexdigest()


def _source_path(file: LogicalFile) -> str:
    return file.raw_path if file.storage_mode == StorageMode.RAW else file.content_object.hdfs_path


def capture_metrics(ctx: AppContext) -> dict:
    with session_scope(ctx.session_factory) as session:
        return {"derived": analytics.storage_statistics(session), "measured": analytics.measured_hdfs(ctx)}


# -- analysis ---------------------------------------------------------------------------------------


def run_analysis(ctx: AppContext, job_id: str, params: dict, reporter) -> dict:
    mode = params["mode"]
    chunk_size = params.get("chunk_size")
    with session_scope(ctx.session_factory) as session:
        fingerprint = catalog_fingerprint(session)
        stats = analytics.storage_statistics(session)
        files = list(session.scalars(eligible_query(mode).order_by(LogicalFile.created_at)))
        rows = [
            {
                "id": f.id,
                "name": f.name,
                "folder": f.folder,
                "sha256": f.sha256,
                "size_bytes": f.size_bytes,
                "storage_mode": f.storage_mode,
                "source_path": _source_path(f),
            }
            for f in files
        ]
        stored_objects = set(session.scalars(select(ContentObject.sha256).where(ContentObject.state == ContentState.ACTIVE)))
        known_chunks = set(session.scalars(select(Chunk.sha256).where(Chunk.state == ContentState.ACTIVE)))
        manifests_exist = set()
        if mode == StorageMode.CHUNK:
            for sha in {r["sha256"] for r in rows}:
                if content_store.find_active_manifest(session, sha, chunk_size):
                    manifests_exist.add(sha)
        # An object can go away only if every file holding it would be converted by this job.
        holders = dict(
            session.execute(
                select(LogicalFile.object_id, func.count())
                .where(LogicalFile.status != FileStatus.PURGED, LogicalFile.object_id.is_not(None))
                .group_by(LogicalFile.object_id)
            ).all()
        )
        converting_holders = {}
        object_sizes = {}
        if mode == StorageMode.CHUNK:
            for f in files:
                if f.object_id:
                    converting_holders[f.object_id] = converting_holders.get(f.object_id, 0) + 1
                    object_sizes[f.object_id] = f.size_bytes

    reporter.progress(0, len(rows), "Analysing files")
    actions, new_bytes, new_chunks = [], 0, 0
    total_chunks, reused_chunks = 0, 0
    seen_chunks: set[str] = set()
    seen_contents: set[str] = set()
    for index, row in enumerate(rows, start=1):
        sha = row["sha256"]
        first_copy = sha not in seen_contents
        seen_contents.add(sha)
        if mode == StorageMode.FILE:
            already = sha in stored_objects
            if first_copy and not already:
                new_bytes += row["size_bytes"]
            action = "promote_to_object" if first_copy and not already else "reference_existing_object"
        else:
            action = "reference_existing_manifest" if sha in manifests_exist or not first_copy else "chunk"
            if action == "chunk":
                for block in fixed_size_chunks(ctx.hdfs.open(row["source_path"]), chunk_size):
                    digest = sha256_bytes(block)
                    total_chunks += 1
                    if digest in known_chunks or digest in seen_chunks:
                        reused_chunks += 1
                    else:
                        seen_chunks.add(digest)
                        new_bytes += len(block)
                        new_chunks += 1
        actions.append({k: row[k] for k in ("id", "name", "folder", "sha256", "size_bytes", "storage_mode")} | {"action": action})
        reporter.progress(index, len(rows), f"Analysed {index} of {len(rows)}")

    raw_removed = sum(r["size_bytes"] for r in rows if r["storage_mode"] == StorageMode.RAW)
    objects_removed = sum(
        object_sizes[oid] for oid, count in converting_holders.items() if holders.get(oid, 0) == count
    )
    predicted_stored = stats["stored_content_bytes"] - raw_removed - objects_removed + new_bytes
    return {
        "estimated": True,
        "catalog_fingerprint": fingerprint,
        "mode": mode,
        "chunk_size": chunk_size,
        "files_eligible": len(rows),
        "distinct_contents": len(seen_contents),
        "current_logical_bytes": stats["logical_bytes"],
        "current_stored_bytes": stats["stored_content_bytes"],
        "predicted_stored_bytes": predicted_stored,
        "predicted_reduction_bytes": stats["stored_content_bytes"] - predicted_stored,
        "predicted_savings_percent": analytics.savings_percent(stats["logical_bytes"], predicted_stored),
        "new_content_bytes": new_bytes,
        "chunks_examined": total_chunks,
        "chunks_new": new_chunks,
        "chunks_reused": reused_chunks,
        "actions": actions[:500],
        "actions_truncated": len(actions) > 500,
    }


# -- optimization -----------------------------------------------------------------------------------


def _check_source_hash(ctx: AppContext, path: str, file: LogicalFile) -> None:
    actual, length = sha256_stream(ctx.hdfs.open(path))
    if actual != file.sha256 or length != file.size_bytes:
        raise IntegrityFailure(
            f"{file.name}: bytes at {path} hash to {actual}, expected {file.sha256}. The file was left unchanged."
        )


def _convert_to_object(ctx: AppContext, session: Session, file: LogicalFile, verified: set[str]) -> str | None:
    """Returns a leftover raw path that may be deleted once the new pointer has committed."""
    sha = file.sha256
    raw_path = file.raw_path
    target = ctx.paths.object_path(sha)
    existing = content_store.find_active_object(session, sha)
    manifest = None if existing else content_store.find_active_manifest(session, sha)

    if existing is not None:
        if sha not in verified:
            _check_source_hash(ctx, existing.hdfs_path, file)
            verified.add(sha)
        file.content_object, file.storage_mode, file.raw_path = existing, StorageMode.FILE, None
        return raw_path
    if manifest is not None:
        if sha not in verified:
            actual, _ = sha256_stream(content_store.iter_file_bytes(ctx, session, _manifest_view(file, manifest)))
            if actual != sha:
                raise IntegrityFailure(f"{file.name}: existing manifest does not rebuild the file's hash.")
            verified.add(sha)
        file.manifest, file.storage_mode, file.raw_path = manifest, StorageMode.CHUNK, None
        return raw_path

    raw_exists = ctx.hdfs.status(raw_path) is not None
    target_exists = ctx.hdfs.status(target) is not None
    if target_exists:
        # Left by an earlier run that stopped between rename and commit. Adopt it only after proving it.
        _check_source_hash(ctx, target, file)
    elif raw_exists:
        _check_source_hash(ctx, raw_path, file)
        ctx.hdfs.mkdirs(parent_of(target))
        if not ctx.hdfs.rename(raw_path, target):
            raise IntegrityFailure(f"{file.name}: HDFS refused the rename to {target}.")
        raw_exists = False
    else:
        raise IntegrityFailure(f"{file.name}: content is missing from HDFS at {raw_path}.")
    verified.add(sha)
    file.content_object = content_store.register_object(session, sha, file.size_bytes, target)
    file.storage_mode, file.raw_path = StorageMode.FILE, None
    return raw_path if raw_exists else None


class _manifest_view:  # noqa: N801 - a small read-only stand-in for iter_file_bytes
    def __init__(self, file: LogicalFile, manifest):
        self.storage_mode = StorageMode.CHUNK
        self.manifest_id = manifest.id
        self.id = file.id


def _convert_to_chunks(
    ctx: AppContext, session: Session, file: LogicalFile, chunk_size: int, verified: set[str], replication: int | None
) -> tuple[str | None, int]:
    sha = file.sha256
    raw_path = file.raw_path if file.storage_mode == StorageMode.RAW else None
    build = content_store.build_manifest(
        ctx, session, ctx.hdfs.open(_source_path(file)), sha, file.size_bytes, chunk_size, replication=replication
    )
    session.flush()
    key = f"{sha}:{chunk_size}"
    if key not in verified:
        actual, length = sha256_stream(content_store.iter_file_bytes(ctx, session, _manifest_view(file, build.manifest)))
        if actual != sha or length != file.size_bytes:
            raise IntegrityFailure(f"{file.name}: rebuilding from chunks gave {actual}, expected {sha}.")
        verified.add(key)
    file.manifest = build.manifest
    file.storage_mode = StorageMode.CHUNK
    file.raw_path = None
    file.content_object = None
    return raw_path, build.chunks_new


def run_optimization(ctx: AppContext, job_id: str, params: dict, reporter) -> dict:
    mode = params["mode"]
    chunk_size = params.get("chunk_size")
    started = time.perf_counter()
    before = capture_metrics(ctx)
    with session_scope(ctx.session_factory) as session:
        file_ids = list(session.scalars(select(LogicalFile.id).where(eligible_query(mode).whereclause).order_by(LogicalFile.created_at)))
        replication = settings_store.get_value(ctx, session, "target_replication")

    processed, errors = 0, []
    orphans_left: list[str] = []
    verified: set[str] = set()
    chunks_new = 0
    reporter.progress(0, len(file_ids), "Optimizing files")
    for index, file_id in enumerate(file_ids, start=1):
        try:
            with ctx.content_lock:
                leftover = None
                with session_scope(ctx.session_factory) as session:
                    file = session.get(LogicalFile, file_id)
                    if file is None or file.status != FileStatus.ACTIVE:
                        continue
                    if mode == StorageMode.FILE:
                        leftover = _convert_to_object(ctx, session, file, verified)
                    else:
                        leftover, new = _convert_to_chunks(ctx, session, file, chunk_size, verified, replication)
                        chunks_new += new
                    file.last_verified_ok = True
                    audit.record(session, "optimize.file_converted", f"{file.name} now stored as {file.storage_mode}.", entity_type="file", entity_id=file.id)
                    analytics.record_snapshot(session, "optimize")
                if leftover:
                    # The pointer has committed, so this copy is redundant. Failing to remove it leaves an
                    # orphan for reconciliation to find; the file itself converted successfully.
                    try:
                        ctx.hdfs.delete(leftover)
                    except HdfsError as exc:
                        orphans_left.append(leftover)
                        audit.record_failure(
                            ctx.session_factory, "optimize.leftover_not_removed", f"{leftover}: {exc.message}", entity_type="file", entity_id=file_id
                        )
            processed += 1
        except HdfsUnavailable:
            raise  # the cluster is gone, so continuing would only record misleading per-file failures
        except Exception as exc:  # noqa: BLE001 - per-file isolation: report it and continue with the rest
            message = getattr(exc, "message", str(exc))
            errors.append({"file_id": file_id, "error": message})
            audit.record_failure(ctx.session_factory, "optimize.file_failed", message, entity_type="file", entity_id=file_id)
        reporter.progress(index, len(file_ids), f"Processed {index} of {len(file_ids)}")

    reporter.progress(len(file_ids), len(file_ids), "Collecting content nothing refers to")
    gc_report = lifecycle.collect_garbage(ctx)
    after = capture_metrics(ctx)
    duration_ms = (time.perf_counter() - started) * 1000
    reclaimed = before["derived"]["stored_content_bytes"] - after["derived"]["stored_content_bytes"]
    with session_scope(ctx.session_factory) as session:
        session.add(
            OptimizationHistory(
                job_id=job_id,
                mode=mode,
                chunk_size=chunk_size,
                before=before,
                after=after,
                files_processed=processed,
                files_failed=len(errors),
                bytes_reclaimed_logical=reclaimed,
                duration_ms=duration_ms,
            )
        )
        audit.record_sample(session, "optimize", before["derived"]["logical_bytes"], duration_ms, mode=mode)
        audit.record(
            session,
            "optimize.completed",
            f"{mode}-level optimization: {processed} files converted, {len(errors)} failed, {reclaimed} bytes of stored content reclaimed.",
            severity="warning" if errors else "info",
            entity_type="job",
            entity_id=job_id,
        )
    return {
        "estimated": False,
        "files_processed": processed,
        "files_failed": len(errors),
        "errors": errors,
        "orphans_left": orphans_left,
        "chunks_new": chunks_new,
        "before": before,
        "after": after,
        "bytes_reclaimed": reclaimed,
        "garbage_collected": {k: gc_report[k] for k in ("object_count", "manifest_count", "chunk_count", "reclaimable_bytes")},
        "duration_ms": duration_ms,
    }


def validate_analysis_for_optimize(ctx: AppContext, analysis_job_id: str) -> DeduplicationJob:
    """Optimization must follow a successful preview of the same, unchanged catalog."""
    with session_scope(ctx.session_factory) as session:
        job = session.get(DeduplicationJob, analysis_job_id)
        if job is None or job.kind != "analyze":
            raise NotFoundError(f"No analysis job with id {analysis_job_id}.")
        if job.status != JobStatus.SUCCEEDED:
            raise ConflictError("That analysis has not completed successfully, so there is no preview to act on.")
        if job.result["catalog_fingerprint"] != catalog_fingerprint(session):
            raise ConflictError("Files have changed since this preview. Run the analysis again and review the new estimate.")
        return job


def validate_mode(ctx: AppContext, mode: str, chunk_size: int | None) -> tuple[str, int | None]:
    if mode not in (StorageMode.FILE, StorageMode.CHUNK):
        raise ValidationFailure("Optimization mode must be 'file' or 'chunk'.")
    if mode == StorageMode.CHUNK:
        with session_scope(ctx.session_factory) as session:
            chunk_size = chunk_size or settings_store.get_value(ctx, session, "default_chunk_size")
        settings_store.validate_chunk_size(ctx, chunk_size)
        return mode, chunk_size
    return mode, None

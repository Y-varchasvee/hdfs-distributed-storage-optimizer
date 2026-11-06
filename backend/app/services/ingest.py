"""Upload pipeline: hash, look up, store only what is new, then commit the logical reference."""

from __future__ import annotations

import mimetypes
import posixpath
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.errors import ValidationFailure
from app.models.entities import (
    FileManifest,
    FileStatus,
    LogicalFile,
    StorageMode,
    new_id,
)
from app.services import analytics, audit, content_store, settings_store
from app.services.context import AppContext
from app.services.hashing import read_file_blocks, sha256_file


def normalize_folder(folder: str | None) -> str:
    """Canonical virtual folder path. Folders exist only in metadata, never as user-named HDFS paths."""
    raw = (folder or "/").strip().replace("\\", "/")
    if any(ord(ch) < 32 for ch in raw):
        raise ValidationFailure("Folder path contains control characters.")
    parts = [part for part in raw.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        raise ValidationFailure("Folder path may not contain '.' or '..' segments.")
    normalized = "/" + "/".join(parts)
    if len(normalized) > 512:
        raise ValidationFailure("Folder path is too long.")
    return normalized


def validate_filename(name: str | None) -> str:
    cleaned = posixpath.basename((name or "").replace("\\", "/")).strip()
    if not cleaned or cleaned in {".", ".."}:
        raise ValidationFailure("A file name is required.")
    if any(ord(ch) < 32 for ch in cleaned):
        raise ValidationFailure("File name contains control characters.")
    if len(cleaned) > 255:
        raise ValidationFailure("File name is too long.")
    return cleaned


def unique_name(session: Session, folder: str, name: str) -> str:
    """Identity comes from content, so a repeated name is simply a different logical file: 'a (1).txt'."""
    stem, extension = posixpath.splitext(name)
    candidate, counter = name, 0
    while session.scalar(
        select(func.count())
        .select_from(LogicalFile)
        .where(LogicalFile.folder == folder, LogicalFile.name == candidate, LogicalFile.status == FileStatus.ACTIVE)
    ):
        counter += 1
        candidate = f"{stem} ({counter}){extension}"
    return candidate


@dataclass
class IngestResult:
    file: LogicalFile
    outcome: str  # stored_new | duplicate_reference | chunks_shared | stored_raw
    duplicate_of_existing: bool
    bytes_written: int
    chunks_total: int
    chunks_new: int
    chunks_reused: int
    hash_ms: float
    store_ms: float
    total_ms: float


def ingest_local_file(
    ctx: AppContext,
    local_path: Path,
    name: str,
    *,
    folder: str = "/",
    mode: str | None = None,
    chunk_size: int | None = None,
    provenance_label: str = "user_upload",
    dataset_source_id: str | None = None,
    known_hash: tuple[str, int] | None = None,
    known_hash_ms: float | None = None,
) -> IngestResult:
    """Store one already-spooled local file. Identical bytes under any name yield one stored copy."""
    started = time.perf_counter()
    name = validate_filename(name)
    folder = normalize_folder(folder)

    with session_scope(ctx.session_factory) as session:
        options = settings_store.get_all(ctx, session)
    mode = settings_store.validate_mode(mode or options["default_ingest_mode"])
    chunk_size = settings_store.validate_chunk_size(ctx, chunk_size or options["default_chunk_size"])
    verify = options["verify_on_write"]
    replication = options["target_replication"]

    # A caller that already hashed the bytes passes its own measured time. Without one, no hashing happened
    # here, so no sample is recorded: timing nothing would report an absurd throughput.
    hash_ms = known_hash_ms
    if known_hash is None:
        hash_started = time.perf_counter()
        file_sha256, size = sha256_file(local_path)
        hash_ms = (time.perf_counter() - hash_started) * 1000
    else:
        file_sha256, size = known_hash

    with ctx.content_lock, session_scope(ctx.session_factory) as session:
        store_started = time.perf_counter()
        duplicate_of_existing = bool(
            session.scalar(
                select(func.count())
                .select_from(LogicalFile)
                .where(LogicalFile.sha256 == file_sha256, LogicalFile.status != FileStatus.PURGED)
            )
        )
        record = LogicalFile(
            id=new_id(),
            name=unique_name(session, folder, name),
            folder=folder,
            size_bytes=size,
            sha256=file_sha256,
            mime_type=mimetypes.guess_type(name)[0],
            extension=(posixpath.splitext(name)[1].lstrip(".").lower() or None),
            storage_mode=mode,
            provenance_label=provenance_label,
            dataset_source_id=dataset_source_id,
        )
        bytes_written, chunks_total, chunks_new, chunks_reused = 0, 0, 0, 0
        chunking_ms = 0.0

        if mode == StorageMode.RAW:
            # The deliberate baseline: a private copy, as a plain HDFS upload would produce.
            record.raw_path = ctx.paths.raw_path(record.id)
            content_store.put_content(
                ctx,
                record.raw_path,
                lambda: read_file_blocks(local_path),
                file_sha256,
                size,
                verify=verify,
                replication=replication,
            )
            bytes_written, outcome = size, "stored_raw"
        else:
            reused = _reference_existing_content(ctx, session, record, file_sha256, size, mode, chunk_size, local_path, verify, replication)
            if reused is not None:
                bytes_written = reused
                outcome = "duplicate_reference"
                chunks_total = record.manifest.chunk_count if record.manifest else 0
                chunks_reused = chunks_total
            elif mode == StorageMode.FILE:
                path = ctx.paths.object_path(file_sha256)
                content_store.put_content(
                    ctx,
                    path,
                    lambda: read_file_blocks(local_path),
                    file_sha256,
                    size,
                    verify=verify,
                    replication=replication,
                )
                record.content_object = content_store.register_object(session, file_sha256, size, path)
                bytes_written, outcome = size, "stored_new"
            else:
                build = content_store.build_manifest(
                    ctx,
                    session,
                    read_file_blocks(local_path),
                    file_sha256,
                    size,
                    chunk_size,
                    replication=replication,
                )
                record.manifest = build.manifest
                bytes_written = build.bytes_written
                chunks_total, chunks_new, chunks_reused = build.chunks_total, build.chunks_new, build.chunks_reused
                chunking_ms = build.chunking_ms
                outcome = "chunks_shared" if chunks_reused else "stored_new"

        session.add(record)
        session.flush()
        store_ms = (time.perf_counter() - store_started) * 1000
        total_ms = (time.perf_counter() - started) * 1000

        if hash_ms is not None:
            audit.record_sample(session, "hash", size, hash_ms, mode=mode, file_id=record.id)
        audit.record_sample(session, "upload", size, total_ms, mode=record.storage_mode, file_id=record.id)
        if chunking_ms:
            audit.record_sample(session, "chunking", size, chunking_ms, mode=mode, file_id=record.id)
        audit.record(
            session,
            "file.uploaded",
            f"Uploaded {record.name} ({size} bytes): {outcome}, {bytes_written} bytes written to HDFS.",
            entity_type="file",
            entity_id=record.id,
            details={"sha256": file_sha256, "outcome": outcome, "bytes_written": bytes_written, "mode": record.storage_mode},
        )
        if duplicate_of_existing:
            audit.record(
                session,
                "dedup.duplicate_detected",
                f"{record.name} is byte-identical to content already managed (SHA-256 {file_sha256[:12]}...).",
                entity_type="file",
                entity_id=record.id,
                details={"sha256": file_sha256, "stored_again": outcome == "stored_raw"},
            )
        analytics.record_snapshot(session, "upload")
        session.flush()

    return IngestResult(
        file=record,
        outcome=outcome,
        duplicate_of_existing=duplicate_of_existing,
        bytes_written=bytes_written,
        chunks_total=chunks_total,
        chunks_new=chunks_new,
        chunks_reused=chunks_reused,
        hash_ms=hash_ms or 0.0,
        store_ms=store_ms,
        total_ms=total_ms,
    )


def _reference_existing_content(
    ctx: AppContext,
    session: Session,
    record: LogicalFile,
    file_sha256: str,
    size: int,
    mode: str,
    chunk_size: int,
    local_path: Path,
    verify: bool,
    replication: int | None,
) -> int | None:
    """Point at an already-stored form of this content. Returns repair bytes, or None if nothing is stored."""
    manifest: FileManifest | None = content_store.find_active_manifest(
        session, file_sha256, chunk_size if mode == StorageMode.CHUNK else None
    )
    obj = content_store.find_active_object(session, file_sha256)

    # Prefer the requested representation, then fall back to the other, so nothing is stored twice.
    if obj is not None and (mode == StorageMode.FILE or manifest is None):
        status = ctx.hdfs.status(obj.hdfs_path)
        repaired = 0
        if status is None or status.length != size or obj.size_bytes != size:
            # Metadata says present but HDFS disagrees. Hash equality means the upload can repair it.
            if status is not None:
                ctx.hdfs.delete(obj.hdfs_path)
            content_store.put_content(
                ctx, obj.hdfs_path, lambda: read_file_blocks(local_path), file_sha256, size, verify=verify, replication=replication
            )
            repaired = size
            audit.record(
                session,
                "storage.object_repaired",
                f"Stored object {file_sha256[:12]}... was missing or truncated and was rewritten from an upload.",
                severity="warning",
                entity_type="object",
                entity_id=obj.id,
            )
        record.storage_mode = StorageMode.FILE
        record.content_object = obj
        return repaired

    fallback = manifest or content_store.find_active_manifest(session, file_sha256)
    if fallback is not None:
        chunks = content_store.manifest_chunks(session, fallback.id)
        if _all_chunks_present(ctx, chunks):
            record.storage_mode = StorageMode.CHUNK
            record.manifest = fallback
            return 0
        # A damaged manifest must not gain references. Rewriting its chunks from this upload heals it.
        repaired = content_store.repair_manifest(ctx, session, fallback, local_path, replication)
        audit.record(
            session,
            "storage.manifest_repaired",
            f"Manifest for {file_sha256[:12]}... had missing chunks that were rewritten from an upload.",
            severity="warning",
            entity_type="manifest",
            entity_id=fallback.id,
        )
        record.storage_mode = StorageMode.CHUNK
        record.manifest = fallback
        return repaired
    return None


def _all_chunks_present(ctx: AppContext, chunks: list) -> bool:
    for chunk in chunks:
        status = ctx.hdfs.status(chunk.hdfs_path)
        if status is None or status.length != chunk.size_bytes:
            return False
    return True

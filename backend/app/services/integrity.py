"""Integrity verification and verified restoration: rebuild the original bytes, then compare SHA-256."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import session_scope, utcnow
from app.core.errors import HdfsFileNotFound, IntegrityFailure, NotFoundError
from app.models.entities import FileStatus, IntegrityCheck, LogicalFile, StorageMode
from app.services import audit, content_store
from app.services.context import AppContext
from app.services.hashing import sha256_bytes


def get_file(session: Session, file_id: str) -> LogicalFile:
    record = session.get(LogicalFile, file_id)
    if record is None or record.status == FileStatus.PURGED:
        raise NotFoundError(f"No file with id {file_id}.")
    return record


def verify_file(ctx: AppContext, file_id: str) -> IntegrityCheck:
    """Read every byte back from HDFS and compare. HDFS being down is an error, not a failed check."""
    started = time.perf_counter()
    with session_scope(ctx.session_factory) as session:
        record = get_file(session, file_id)
        digest = hashlib.sha256()
        missing: list[str] = []
        corrupt: list[str] = []
        bytes_read = 0
        chunks_checked = 0
        detail = None

        if record.storage_mode == StorageMode.CHUNK:
            chunks = content_store.manifest_chunks(session, record.manifest_id)
            for chunk in chunks:
                chunks_checked += 1
                try:
                    data = b"".join(ctx.hdfs.open(chunk.hdfs_path))
                except HdfsFileNotFound:
                    missing.append(chunk.sha256)
                    continue
                if sha256_bytes(data) != chunk.sha256:
                    corrupt.append(chunk.sha256)
                digest.update(data)
                bytes_read += len(data)
            detail = _compare_durable_manifest(ctx, record, [c.sha256 for c in chunks])
        else:
            path = record.raw_path if record.storage_mode == StorageMode.RAW else record.content_object.hdfs_path
            try:
                for block in ctx.hdfs.open(path):
                    digest.update(block)
                    bytes_read += len(block)
            except HdfsFileNotFound:
                missing.append(path)

        actual = None if missing else digest.hexdigest()
        ok = not missing and not corrupt and actual == record.sha256 and bytes_read == record.size_bytes and detail is None
        duration_ms = (time.perf_counter() - started) * 1000
        check = IntegrityCheck(
            file_id=record.id,
            ok=ok,
            expected_sha256=record.sha256,
            actual_sha256=actual,
            bytes_read=bytes_read,
            chunks_checked=chunks_checked,
            missing=missing or None,
            corrupt=corrupt or None,
            detail=detail,
            duration_ms=duration_ms,
        )
        session.add(check)
        record.last_verified_at = utcnow()
        record.last_verified_ok = ok
        audit.record_sample(session, "verify", bytes_read, duration_ms, mode=record.storage_mode, file_id=record.id)
        audit.record(
            session,
            "integrity.passed" if ok else "integrity.failed",
            f"{record.name}: SHA-256 {'matches' if ok else 'does NOT match'} "
            f"({bytes_read} bytes, {len(missing)} missing, {len(corrupt)} corrupt).",
            severity="info" if ok else "error",
            entity_type="file",
            entity_id=record.id,
        )
        session.flush()
    return check


def _compare_durable_manifest(ctx: AppContext, record: LogicalFile, expected_hashes: list[str]) -> str | None:
    """The manifest in HDFS is the durable recipe. It must agree with the copy in the database."""
    try:
        document = json.loads(b"".join(ctx.hdfs.open(record.manifest.hdfs_path)))
    except HdfsFileNotFound:
        return f"Manifest file is missing from HDFS: {record.manifest.hdfs_path}"
    except ValueError:
        return "Manifest file in HDFS is not valid JSON."
    if [entry["sha256"] for entry in document.get("chunks", [])] != expected_hashes:
        return "Manifest file in HDFS disagrees with the metadata database."
    return None


def preflight(ctx: AppContext, session: Session, record: LogicalFile) -> None:
    """Fail before any response headers are sent if the start of the content is not readable."""
    if record.storage_mode == StorageMode.CHUNK:
        return  # chunks are checked one by one as they are streamed
    path = record.raw_path if record.storage_mode == StorageMode.RAW else record.content_object.hdfs_path
    if ctx.hdfs.status(path) is None:
        raise IntegrityFailure(f"Stored content for {record.name} is missing from HDFS.")


def stream_verified(ctx: AppContext, file_id: str) -> Iterator[bytes]:
    """Stream a file and compare its whole hash at the end.

    A failure raises mid-stream, which aborts the HTTP response, so a client can never mistake
    damaged data for a complete download.
    """
    started = time.perf_counter()
    digest = hashlib.sha256()
    total = 0
    with session_scope(ctx.session_factory) as session:
        record = get_file(session, file_id)
        mode, expected = record.storage_mode, record.sha256
        for block in content_store.iter_file_bytes(ctx, session, record):
            digest.update(block)
            total += len(block)
            yield block
    if digest.hexdigest() != expected:
        audit.record_failure(
            ctx.session_factory,
            "file.restore_failed",
            f"Download of {file_id} failed: read {digest.hexdigest()}, expected {expected}.",
            entity_type="file",
            entity_id=file_id,
        )
        raise IntegrityFailure(f"Reconstructed file {file_id} failed SHA-256 verification.")
    with session_scope(ctx.session_factory) as session:
        audit.record_sample(session, "restore", total, (time.perf_counter() - started) * 1000, mode=mode, file_id=file_id)
        audit.record(session, "file.downloaded", f"Restored {total} bytes; SHA-256 verified.", entity_type="file", entity_id=file_id)


def restore_to_path(ctx: AppContext, file_id: str, destination: Path) -> str:
    """Rebuild a file on the local filesystem through the verified stream. Returns its digest."""
    digest = hashlib.sha256()
    with open(destination, "wb") as handle:
        for block in stream_verified(ctx, file_id):
            digest.update(block)
            handle.write(block)
    return digest.hexdigest()


def latest_checks(session: Session, file_id: str, limit: int = 10) -> list[IntegrityCheck]:
    return list(
        session.scalars(
            select(IntegrityCheck)
            .where(IntegrityCheck.file_id == file_id)
            .order_by(IntegrityCheck.checked_at.desc(), IntegrityCheck.id.desc())
            .limit(limit)
        )
    )


def run_verify_all(ctx: AppContext, job_id: str, params: dict, reporter) -> dict:
    with session_scope(ctx.session_factory) as session:
        ids = list(session.scalars(select(LogicalFile.id).where(LogicalFile.status == FileStatus.ACTIVE)))
    passed, failed = 0, []
    reporter.progress(0, len(ids), "Verifying files")
    for index, file_id in enumerate(ids, start=1):
        check = verify_file(ctx, file_id)
        if check.ok:
            passed += 1
        else:
            failed.append(file_id)
        reporter.progress(index, len(ids), f"Verified {index} of {len(ids)}")
    return {"files_checked": len(ids), "passed": passed, "failed": failed, "errors": [f"{f}: verification failed" for f in failed]}

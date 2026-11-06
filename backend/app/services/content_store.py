"""Content-addressable storage primitives.

HDFS and SQLite cannot share a transaction, so every write follows the same order:

    1. write to /staging/<random>       (a crash here leaves only an unreferenced staging file)
    2. check length and, optionally, the SHA-256 of what HDFS now holds
    3. atomically rename into the content-addressed path
    4. commit the metadata row          (a crash before this leaves a detectable, unreferenced orphan)

Metadata therefore never points at bytes that are not fully stored and checked.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import HdfsError, IntegrityFailure
from app.models.entities import (
    Chunk,
    ContentObject,
    ContentState,
    FileChunk,
    FileManifest,
    LogicalFile,
    StorageMode,
)
from app.services import settings_store
from app.services.context import AppContext
from app.services.hashing import (
    fixed_size_chunks,
    read_file_blocks,
    sha256_bytes,
    sha256_stream,
)


def parent_of(path: str) -> str:
    return path.rsplit("/", 1)[0] or "/"


def target_replication(ctx: AppContext, session: Session) -> int | None:
    return settings_store.get_value(ctx, session, "target_replication")


def put_content(
    ctx: AppContext,
    final_path: str,
    data_factory: Callable[[], bytes | Iterable[bytes]],
    expected_sha256: str,
    size: int,
    *,
    verify: bool,
    replication: int | None = None,
) -> bool:
    """Store bytes at ``final_path`` following the staged protocol. Returns True if new bytes were written."""
    hdfs = ctx.hdfs
    existing = hdfs.status(final_path)
    if existing is not None:
        # Possibly left by a crash between rename and commit. Adopt it only if it proves correct.
        actual, length = sha256_stream(hdfs.open(final_path))
        if actual == expected_sha256 and length == size:
            return False
        quarantine = ctx.paths.recovery_orphan_path(f"corrupt-{uuid.uuid4().hex}")
        hdfs.mkdirs(parent_of(quarantine))
        hdfs.rename(final_path, quarantine)

    staging = ctx.paths.staging_path(uuid.uuid4().hex)
    try:
        hdfs.create(staging, data_factory(), length=size, overwrite=False, replication=replication)
        status = hdfs.status(staging)
        if status is None or status.length != size:
            found = None if status is None else status.length
            raise IntegrityFailure(f"Staged write to {staging} has length {found}, expected {size}.")
        if verify:
            actual, _ = sha256_stream(hdfs.open(staging))
            if actual != expected_sha256:
                raise IntegrityFailure(f"Staged write has SHA-256 {actual}, expected {expected_sha256}.")
        hdfs.mkdirs(parent_of(final_path))
        if not hdfs.rename(staging, final_path):
            # HDFS refuses to rename onto an existing path, so another writer got there first.
            if hdfs.status(final_path) is None:
                raise HdfsError(f"HDFS refused the rename to {final_path}.")
            hdfs.delete(staging)
            return False
        return True
    except Exception:
        _delete_quietly(ctx, staging)
        raise


def _delete_quietly(ctx: AppContext, path: str) -> None:
    try:
        ctx.hdfs.delete(path)
    except HdfsError:
        pass  # staging is swept by recovery, so this must not mask the original error


def find_active_object(session: Session, sha256: str) -> ContentObject | None:
    return session.scalar(
        select(ContentObject).where(ContentObject.sha256 == sha256, ContentObject.state == ContentState.ACTIVE)
    )


def find_active_manifest(session: Session, sha256: str, chunk_size: int | None = None) -> FileManifest | None:
    query = select(FileManifest).where(FileManifest.file_sha256 == sha256, FileManifest.state == ContentState.ACTIVE)
    if chunk_size is not None:
        query = query.where(FileManifest.chunk_size == chunk_size)
    return session.scalars(query.order_by(FileManifest.created_at)).first()


def register_object(session: Session, sha256: str, size: int, hdfs_path: str) -> ContentObject:
    """Create or reactivate the row for a content value. Removed rows are reused, keeping one per hash."""
    row = session.scalar(select(ContentObject).where(ContentObject.sha256 == sha256))
    if row is None:
        row = ContentObject(sha256=sha256, size_bytes=size, hdfs_path=hdfs_path)
        session.add(row)
    else:
        row.state = ContentState.ACTIVE
        row.removed_at = None
        row.hdfs_path = hdfs_path
    session.flush()
    return row


@dataclass
class ManifestBuild:
    manifest: FileManifest
    reused_manifest: bool = False
    chunks_total: int = 0
    chunks_new: int = 0
    chunks_reused: int = 0
    bytes_written: int = 0
    chunking_ms: float = 0.0
    new_chunk_hashes: list[str] = field(default_factory=list)


def build_manifest(
    ctx: AppContext,
    session: Session,
    source: Iterable[bytes],
    file_sha256: str,
    file_size: int,
    chunk_size: int,
    *,
    replication: int | None = None,
) -> ManifestBuild:
    """Chunk a stream, store only unseen chunks, and record the ordered recipe.

    Rows are added only after all HDFS writes finish, so the SQLite write lock is held briefly.
    The caller must hold ``ctx.content_lock`` so garbage collection cannot remove a chunk being reused.
    """
    existing = find_active_manifest(session, file_sha256, chunk_size)
    if existing is not None:
        return ManifestBuild(manifest=existing, reused_manifest=True, chunks_total=existing.chunk_count)

    whole = hashlib.sha256()
    plan: list[tuple[str, int, int]] = []  # (sha256, length, offset)
    seen: dict[str, Chunk | None] = {}  # chunks settled in this run; None means written but no row yet
    build = ManifestBuild(manifest=None)  # type: ignore[arg-type]
    offset = 0
    started = time.perf_counter()

    for block in fixed_size_chunks(source, chunk_size):
        digest = sha256_bytes(block)
        whole.update(block)
        plan.append((digest, len(block), offset))
        offset += len(block)
        build.chunks_total += 1

        if digest in seen:
            build.chunks_reused += 1
            continue
        path = ctx.paths.chunk_path(digest)
        row = session.scalar(select(Chunk).where(Chunk.sha256 == digest))
        if row is not None and row.state == ContentState.ACTIVE:
            status = ctx.hdfs.status(row.hdfs_path)
            if status is not None and status.length == len(block):
                seen[digest] = row
                build.chunks_reused += 1
                continue
            # The metadata says it exists but HDFS disagrees. These bytes are at hand, so repair it.
            ctx.hdfs.delete(row.hdfs_path)
        written = put_content(ctx, path, lambda b=block: b, digest, len(block), verify=False, replication=replication)
        seen[digest] = row
        if written:
            build.chunks_new += 1
            build.bytes_written += len(block)
            build.new_chunk_hashes.append(digest)
        else:
            build.chunks_reused += 1

    if whole.hexdigest() != file_sha256 or offset != file_size:
        raise IntegrityFailure(
            f"Source changed while chunking: expected {file_sha256} ({file_size} bytes), "
            f"read {whole.hexdigest()} ({offset} bytes)."
        )

    manifest_path = ctx.paths.manifest_path(file_sha256, chunk_size)
    document = json.dumps(
        {
            "version": 1,
            "algorithm": "sha256",
            "file_sha256": file_sha256,
            "file_size": file_size,
            "chunk_size": chunk_size,
            "chunks": [{"sha256": sha, "length": length, "offset": off} for sha, length, off in plan],
        },
        separators=(",", ":"),
    ).encode()
    put_content(
        ctx, manifest_path, lambda: document, sha256_bytes(document), len(document), verify=False, replication=replication
    )
    build.bytes_written += len(document)

    # All bytes are durable in HDFS, so metadata can now be written in one short transaction.
    rows: dict[str, Chunk] = {}
    for digest, length, _ in plan:
        if digest in rows:
            continue
        row = seen.get(digest) or session.scalar(select(Chunk).where(Chunk.sha256 == digest))
        if row is None:
            row = Chunk(sha256=digest, size_bytes=length, hdfs_path=ctx.paths.chunk_path(digest))
            session.add(row)
        else:
            row.state = ContentState.ACTIVE
            row.removed_at = None
        rows[digest] = row

    manifest = session.scalar(
        select(FileManifest).where(FileManifest.file_sha256 == file_sha256, FileManifest.chunk_size == chunk_size)
    )
    if manifest is None:
        manifest = FileManifest(file_sha256=file_sha256, chunk_size=chunk_size, file_size=file_size, chunk_count=0, hdfs_path=manifest_path)
        session.add(manifest)
    manifest.file_size = file_size
    manifest.chunk_count = len(plan)
    manifest.manifest_bytes = len(document)
    manifest.hdfs_path = manifest_path
    manifest.state = ContentState.ACTIVE
    manifest.removed_at = None
    session.flush()  # assigns chunk and manifest primary keys
    manifest.entries = [
        FileChunk(chunk_id=rows[digest].id, ordinal=index, offset_bytes=off)
        for index, (digest, _, off) in enumerate(plan)
    ]
    session.flush()
    build.manifest = manifest
    build.chunking_ms = (time.perf_counter() - started) * 1000
    return build


def repair_manifest(
    ctx: AppContext, session: Session, manifest: FileManifest, local_path: Path, replication: int | None
) -> int:
    """Rewrite any missing or truncated chunks of a manifest from a byte-identical local copy."""
    written = 0
    chunks = manifest_chunks(session, manifest.id)
    for chunk, block in zip(chunks, fixed_size_chunks(read_file_blocks(local_path), manifest.chunk_size), strict=True):
        status = ctx.hdfs.status(chunk.hdfs_path)
        if status is not None and status.length == chunk.size_bytes:
            continue
        if status is not None:
            ctx.hdfs.delete(chunk.hdfs_path)
        put_content(ctx, chunk.hdfs_path, lambda b=block: b, chunk.sha256, len(block), verify=False, replication=replication)
        written += len(block)
    return written


def manifest_chunks(session: Session, manifest_id: str) -> list[Chunk]:
    return list(
        session.scalars(
            select(Chunk)
            .join(FileChunk, FileChunk.chunk_id == Chunk.id)
            .where(FileChunk.manifest_id == manifest_id)
            .order_by(FileChunk.ordinal)
        )
    )


def iter_file_bytes(ctx: AppContext, session: Session, file: LogicalFile) -> Iterator[bytes]:
    """Yield a logical file's original bytes. In chunk mode, every chunk is checked as it is read."""
    if file.storage_mode == StorageMode.RAW:
        yield from ctx.hdfs.open(file.raw_path)
    elif file.storage_mode == StorageMode.FILE:
        yield from ctx.hdfs.open(file.content_object.hdfs_path)
    elif file.storage_mode == StorageMode.CHUNK:
        for chunk in manifest_chunks(session, file.manifest_id):
            data = b"".join(ctx.hdfs.open(chunk.hdfs_path))
            actual = sha256_bytes(data)
            if actual != chunk.sha256:
                raise IntegrityFailure(f"Chunk {chunk.sha256} is corrupt in HDFS (read {actual}).")
            yield data
    else:
        raise IntegrityFailure(f"File {file.id} has no stored content (mode {file.storage_mode}).")

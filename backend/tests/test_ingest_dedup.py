"""Whole-file and chunk-level deduplication behaviour."""

import pytest
from app.core.db import session_scope
from app.core.errors import ValidationFailure
from app.models.entities import (
    Chunk,
    ContentObject,
    FileChunk,
    FileManifest,
    LogicalFile,
)
from app.services import analytics, integrity
from app.services.hashing import sha256_bytes
from app.services.ingest import ingest_local_file, normalize_folder, validate_filename
from conftest import pattern
from sqlalchemy import func, select


def count(ctx, model) -> int:
    with session_scope(ctx.session_factory) as session:
        return session.scalar(select(func.count()).select_from(model))


def read_back(ctx, file_id) -> bytes:
    return b"".join(integrity.stream_verified(ctx, file_id))


def test_upload_stores_one_object_at_a_content_addressed_path(ctx, write_file):
    data = pattern(1, 10_000)
    result = ingest_local_file(ctx, write_file(data), "a.txt", mode="file")
    sha = sha256_bytes(data)
    assert result.outcome == "stored_new"
    assert result.file.sha256 == sha
    assert result.bytes_written == len(data)
    assert ctx.hdfs.status(ctx.paths.object_path(sha)).length == len(data)
    assert read_back(ctx, result.file.id) == data


def test_identical_bytes_under_different_names_are_stored_once(ctx, write_file):
    data = pattern(2, 10_000)
    first = ingest_local_file(ctx, write_file(data), "report.txt", mode="file")
    second = ingest_local_file(ctx, write_file(data), "completely-different-name.pdf", mode="file")
    assert second.outcome == "duplicate_reference"
    assert second.duplicate_of_existing is True
    assert second.bytes_written == 0
    assert first.file.id != second.file.id
    assert count(ctx, ContentObject) == 1
    assert count(ctx, LogicalFile) == 2
    assert read_back(ctx, second.file.id) == data


def test_different_content_with_same_filename_stays_distinct(ctx, write_file):
    one, two = pattern(3, 5_000), pattern(4, 5_000)
    first = ingest_local_file(ctx, write_file(one), "same.txt", mode="file")
    second = ingest_local_file(ctx, write_file(two), "same.txt", mode="file")
    assert second.outcome == "stored_new"
    assert second.duplicate_of_existing is False
    assert second.file.name == "same (1).txt"
    assert count(ctx, ContentObject) == 2
    assert read_back(ctx, first.file.id) == one
    assert read_back(ctx, second.file.id) == two


def test_raw_mode_deliberately_keeps_every_copy(ctx, write_file):
    data = pattern(5, 2_000)
    first = ingest_local_file(ctx, write_file(data), "a.bin", mode="raw")
    second = ingest_local_file(ctx, write_file(data), "b.bin", mode="raw")
    assert (first.outcome, second.outcome) == ("stored_raw", "stored_raw")
    assert first.file.raw_path != second.file.raw_path
    assert count(ctx, ContentObject) == 0
    with session_scope(ctx.session_factory) as session:
        stats = analytics.storage_statistics(session)
    assert stats["stored_content_bytes"] == 4_000
    assert stats["duplicate_files"] == 1


def test_chunk_mode_shares_identical_chunks_between_different_files(ctx, write_file):
    size = ctx.settings.default_chunk_size
    shared = pattern(6, size * 3)
    file_a = shared + pattern(7, size)
    file_b = shared + pattern(8, size)
    first = ingest_local_file(ctx, write_file(file_a), "a.bin", mode="chunk")
    second = ingest_local_file(ctx, write_file(file_b), "b.bin", mode="chunk")
    assert (first.chunks_total, first.chunks_new) == (4, 4)
    assert (second.chunks_total, second.chunks_new, second.chunks_reused) == (4, 1, 3)
    assert second.outcome == "chunks_shared"
    assert count(ctx, Chunk) == 5
    assert count(ctx, FileChunk) == 8
    assert read_back(ctx, first.file.id) == file_a
    assert read_back(ctx, second.file.id) == file_b


def test_repeated_chunks_within_one_file_are_stored_once(ctx, write_file):
    size = ctx.settings.default_chunk_size
    block = pattern(9, size)
    data = block * 5
    result = ingest_local_file(ctx, write_file(data), "repeat.bin", mode="chunk")
    assert (result.chunks_total, result.chunks_new, result.chunks_reused) == (5, 1, 4)
    assert read_back(ctx, result.file.id) == data


def test_identical_file_in_chunk_mode_reuses_the_manifest(ctx, write_file):
    data = pattern(10, 20_000)
    ingest_local_file(ctx, write_file(data), "a.bin", mode="chunk")
    second = ingest_local_file(ctx, write_file(data), "b.bin", mode="chunk")
    assert second.outcome == "duplicate_reference"
    assert second.bytes_written == 0
    assert count(ctx, FileManifest) == 1


def test_chunk_upload_of_content_already_stored_whole_writes_nothing(ctx, write_file):
    data = pattern(11, 20_000)
    ingest_local_file(ctx, write_file(data), "a.bin", mode="file")
    second = ingest_local_file(ctx, write_file(data), "b.bin", mode="chunk")
    assert second.bytes_written == 0
    assert second.file.storage_mode == "file"
    assert count(ctx, Chunk) == 0


def test_file_upload_of_content_already_chunked_writes_nothing(ctx, write_file):
    data = pattern(12, 20_000)
    ingest_local_file(ctx, write_file(data), "a.bin", mode="chunk")
    second = ingest_local_file(ctx, write_file(data), "b.bin", mode="file")
    assert second.bytes_written == 0
    assert second.file.storage_mode == "chunk"
    assert count(ctx, ContentObject) == 0


def test_empty_file_round_trip_in_every_mode(ctx, write_file):
    for index, mode in enumerate(("raw", "file", "chunk")):
        result = ingest_local_file(ctx, write_file(b""), f"empty{index}", mode=mode)
        assert result.file.size_bytes == 0
        assert read_back(ctx, result.file.id) == b""
        assert integrity.verify_file(ctx, result.file.id).ok


def test_upload_repairs_an_object_missing_from_hdfs(ctx, write_file):
    data = pattern(13, 3_000)
    first = ingest_local_file(ctx, write_file(data), "a.bin", mode="file")
    ctx.hdfs.delete(ctx.paths.object_path(first.file.sha256))
    second = ingest_local_file(ctx, write_file(data), "b.bin", mode="file")
    assert second.outcome == "duplicate_reference"
    assert second.bytes_written == len(data)
    assert read_back(ctx, first.file.id) == data


def test_upload_repairs_a_chunk_missing_from_hdfs(ctx, write_file):
    data = pattern(14, 20_000)
    first = ingest_local_file(ctx, write_file(data), "a.bin", mode="chunk")
    with session_scope(ctx.session_factory) as session:
        victim = session.scalars(select(Chunk)).first().hdfs_path
    ctx.hdfs.delete(victim)
    ingest_local_file(ctx, write_file(data), "b.bin", mode="chunk")
    assert read_back(ctx, first.file.id) == data


def test_failed_hdfs_write_leaves_no_metadata_and_no_staging(ctx, write_file):
    from support.local_fs_adapter import FaultInjector

    ctx.hdfs = FaultInjector(ctx.hdfs, method="rename")
    with pytest.raises(Exception, match="Injected outage"):
        ingest_local_file(ctx, write_file(pattern(15, 1_000)), "a.bin", mode="file")
    assert count(ctx, LogicalFile) == 0
    assert count(ctx, ContentObject) == 0
    assert ctx.hdfs.list_dir(ctx.paths.staging) == []


def test_partial_write_detected_by_length_check(ctx, write_file):
    """HDFS accepting fewer bytes than sent must never produce a metadata row."""
    inner_create = ctx.hdfs.create

    def truncating_create(path, data, **kwargs):
        blocks = b"".join([data] if isinstance(data, bytes) else data)
        inner_create(path, blocks[:-1], **kwargs)

    ctx.hdfs.create = truncating_create
    with pytest.raises(Exception, match="expected 1000"):
        ingest_local_file(ctx, write_file(pattern(16, 1_000)), "a.bin", mode="file")
    assert count(ctx, LogicalFile) == 0


def test_corruption_during_staging_detected_by_hash_check(ctx, write_file):
    inner_create = ctx.hdfs.create

    def flipping_create(path, data, **kwargs):
        blocks = bytearray(b"".join([data] if isinstance(data, bytes) else data))
        blocks[0] ^= 0xFF
        inner_create(path, bytes(blocks), **kwargs)

    ctx.hdfs.create = flipping_create
    with pytest.raises(Exception, match="SHA-256"):
        ingest_local_file(ctx, write_file(pattern(17, 1_000)), "a.bin", mode="file")
    assert count(ctx, ContentObject) == 0


@pytest.mark.parametrize("bad", ["", "..", ".", "bad\x00name", "x" * 256])
def test_invalid_file_names_are_rejected(bad):
    with pytest.raises(ValidationFailure):
        validate_filename(bad)


def test_file_name_cannot_escape_through_path_segments():
    assert validate_filename("../../etc/passwd") == "passwd"
    assert validate_filename("..\\..\\secret.txt") == "secret.txt"


@pytest.mark.parametrize("bad", ["/a/../b", "..", "/./x", "/a\x01b"])
def test_invalid_folders_are_rejected(bad):
    with pytest.raises(ValidationFailure):
        normalize_folder(bad)


def test_folders_are_normalized():
    assert normalize_folder(None) == "/"
    assert normalize_folder("reports//2026/") == "/reports/2026"

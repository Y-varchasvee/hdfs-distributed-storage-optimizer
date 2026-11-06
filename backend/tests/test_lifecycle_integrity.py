"""Deletion, restoration, garbage collection, integrity checks and crash recovery."""

import pytest
from app.core.db import session_scope
from app.core.errors import ConflictError, IntegrityFailure, NotFoundError
from app.models.entities import (
    Chunk,
    ContentObject,
    ContentState,
    DeduplicationJob,
    FileManifest,
    IntegrityCheck,
    JobStatus,
    LogicalFile,
)
from app.services import analytics, integrity, lifecycle
from app.services.ingest import ingest_local_file
from conftest import pattern
from sqlalchemy import func, select
from support.local_fs_adapter import FaultInjector


def get_stats(ctx):
    with session_scope(ctx.session_factory) as session:
        return analytics.storage_statistics(session)


def content_state(ctx, model, sha_column, sha):
    with session_scope(ctx.session_factory) as session:
        return session.scalar(select(model.state).where(sha_column == sha))


@pytest.mark.parametrize("mode", ["file", "chunk"])
def test_deleting_one_reference_keeps_content_for_the_other(ctx, write_file, mode):
    data = pattern(1, 20_000)
    first = ingest_local_file(ctx, write_file(data), "a.bin", mode=mode)
    second = ingest_local_file(ctx, write_file(data), "b.bin", mode=mode)
    lifecycle.soft_delete(ctx, first.file.id)
    lifecycle.purge(ctx, first.file.id)
    assert integrity.verify_file(ctx, second.file.id).ok
    assert b"".join(integrity.stream_verified(ctx, second.file.id)) == data


@pytest.mark.parametrize("mode", ["file", "chunk"])
def test_soft_deleted_file_keeps_content_and_can_be_restored(ctx, write_file, mode):
    data = pattern(2, 20_000)
    result = ingest_local_file(ctx, write_file(data), "a.bin", mode=mode)
    lifecycle.soft_delete(ctx, result.file.id)
    report = lifecycle.collect_garbage(ctx)
    assert report["object_count"] == report["chunk_count"] == 0  # deleted but restorable: must not collect
    restored = lifecycle.restore(ctx, result.file.id)
    assert restored.status == "active"
    assert b"".join(integrity.stream_verified(ctx, result.file.id)) == data


def test_raw_soft_delete_moves_to_recovery_and_restore_moves_back(ctx, write_file):
    data = pattern(3, 5_000)
    result = ingest_local_file(ctx, write_file(data), "a.bin", mode="raw")
    original_path = result.file.raw_path
    lifecycle.soft_delete(ctx, result.file.id)
    assert ctx.hdfs.status(original_path) is None
    assert ctx.hdfs.status(ctx.paths.recovery_raw_path(result.file.id)) is not None
    lifecycle.restore(ctx, result.file.id)
    assert ctx.hdfs.status(original_path).length == len(data)


def test_restore_avoids_a_name_taken_since_deletion(ctx, write_file):
    first = ingest_local_file(ctx, write_file(pattern(4, 100)), "a.bin", mode="file")
    lifecycle.soft_delete(ctx, first.file.id)
    ingest_local_file(ctx, write_file(pattern(5, 100)), "a.bin", mode="file")
    assert lifecycle.restore(ctx, first.file.id).name == "a (1).bin"


def test_purging_the_last_reference_removes_content_from_hdfs(ctx, write_file):
    data = pattern(6, 5_000)
    result = ingest_local_file(ctx, write_file(data), "a.bin", mode="file")
    path = ctx.paths.object_path(result.file.sha256)
    lifecycle.soft_delete(ctx, result.file.id)
    report = lifecycle.purge(ctx, result.file.id)
    assert report["object_count"] == 1
    assert ctx.hdfs.status(path) is None
    assert get_stats(ctx)["stored_content_bytes"] == 0


def test_gc_keeps_chunks_still_used_by_another_manifest(ctx, write_file):
    size = ctx.settings.default_chunk_size
    shared = pattern(7, size * 2)
    file_a = shared + pattern(8, size)
    file_b = shared + pattern(9, size)
    first = ingest_local_file(ctx, write_file(file_a), "a.bin", mode="chunk")
    second = ingest_local_file(ctx, write_file(file_b), "b.bin", mode="chunk")
    lifecycle.soft_delete(ctx, first.file.id)
    report = lifecycle.purge(ctx, first.file.id)
    assert report["chunk_count"] == 1  # only the chunk unique to file A
    assert report["manifest_count"] == 1
    assert b"".join(integrity.stream_verified(ctx, second.file.id)) == file_b
    lifecycle.soft_delete(ctx, second.file.id)
    report = lifecycle.purge(ctx, second.file.id)
    assert report["chunk_count"] == 3
    assert get_stats(ctx)["chunk_count"] == 0


def test_gc_dry_run_changes_nothing(ctx, write_file):
    result = ingest_local_file(ctx, write_file(pattern(10, 1_000)), "a.bin", mode="file")
    with session_scope(ctx.session_factory) as session:
        file = session.get(LogicalFile, result.file.id)
        file.status = "purged"
        file.object_id = None
    report = lifecycle.collect_garbage(ctx, dry_run=True)
    assert report["object_count"] == 1 and report["removed"] is False
    assert ctx.hdfs.status(ctx.paths.object_path(result.file.sha256)) is not None
    assert content_state(ctx, ContentObject, ContentObject.sha256, result.file.sha256) == ContentState.ACTIVE


def test_reuploading_collected_content_reactivates_the_row(ctx, write_file):
    data = pattern(11, 1_000)
    result = ingest_local_file(ctx, write_file(data), "a.bin", mode="file")
    lifecycle.soft_delete(ctx, result.file.id)
    lifecycle.purge(ctx, result.file.id)
    again = ingest_local_file(ctx, write_file(data), "b.bin", mode="file")
    assert again.outcome == "stored_new"
    assert b"".join(integrity.stream_verified(ctx, again.file.id)) == data
    with session_scope(ctx.session_factory) as session:
        assert session.scalar(select(func.count()).select_from(ContentObject)) == 1


def test_gc_interrupted_after_marking_is_finished_at_startup(ctx, write_file):
    result = ingest_local_file(ctx, write_file(pattern(12, 1_000)), "a.bin", mode="file")
    lifecycle.soft_delete(ctx, result.file.id)
    real = ctx.hdfs
    ctx.hdfs = FaultInjector(real, method="delete")
    with pytest.raises(Exception, match="Injected"):
        lifecycle.purge(ctx, result.file.id)
    assert content_state(ctx, ContentObject, ContentObject.sha256, result.file.sha256) == ContentState.GC_PENDING
    ctx.hdfs = real
    summary = lifecycle.recover_on_startup(ctx)
    assert summary["pending_gc"] == "finished"
    assert content_state(ctx, ContentObject, ContentObject.sha256, result.file.sha256) == ContentState.REMOVED
    assert ctx.hdfs.status(ctx.paths.object_path(result.file.sha256)) is None


def test_purge_requires_soft_delete_first(ctx, write_file):
    result = ingest_local_file(ctx, write_file(pattern(13, 100)), "a.bin", mode="file")
    with pytest.raises(ConflictError):
        lifecycle.purge(ctx, result.file.id)


def test_double_delete_and_restore_of_active_are_rejected(ctx, write_file):
    result = ingest_local_file(ctx, write_file(pattern(14, 100)), "a.bin", mode="file")
    with pytest.raises(ConflictError):
        lifecycle.restore(ctx, result.file.id)
    lifecycle.soft_delete(ctx, result.file.id)
    with pytest.raises(ConflictError):
        lifecycle.soft_delete(ctx, result.file.id)


def test_purged_file_is_gone(ctx, write_file):
    result = ingest_local_file(ctx, write_file(pattern(15, 100)), "a.bin", mode="file")
    lifecycle.soft_delete(ctx, result.file.id)
    lifecycle.purge(ctx, result.file.id)
    with pytest.raises(NotFoundError):
        integrity.verify_file(ctx, result.file.id)


# -- integrity ------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["raw", "file", "chunk"])
def test_verification_passes_on_intact_data_and_records_a_row(ctx, write_file, mode):
    data = pattern(20, 20_000)
    result = ingest_local_file(ctx, write_file(data), "a.bin", mode=mode)
    check = integrity.verify_file(ctx, result.file.id)
    assert check.ok and check.actual_sha256 == result.file.sha256 and check.bytes_read == len(data)
    with session_scope(ctx.session_factory) as session:
        assert session.scalar(select(func.count()).select_from(IntegrityCheck)) == 1
        assert session.get(LogicalFile, result.file.id).last_verified_ok is True


def test_verification_detects_a_corrupted_object(ctx, write_file):
    result = ingest_local_file(ctx, write_file(pattern(21, 1_000)), "a.bin", mode="file")
    path = ctx.paths.object_path(result.file.sha256)
    ctx.hdfs.delete(path)
    ctx.hdfs.create(path, pattern(22, 1_000))
    check = integrity.verify_file(ctx, result.file.id)
    assert not check.ok and check.actual_sha256 != result.file.sha256
    with pytest.raises(IntegrityFailure):
        b"".join(integrity.stream_verified(ctx, result.file.id)) and None


def test_verification_reports_a_missing_object(ctx, write_file):
    result = ingest_local_file(ctx, write_file(pattern(23, 1_000)), "a.bin", mode="file")
    ctx.hdfs.delete(ctx.paths.object_path(result.file.sha256))
    check = integrity.verify_file(ctx, result.file.id)
    assert not check.ok and check.missing and check.actual_sha256 is None


def test_verification_lists_each_missing_and_corrupt_chunk(ctx, write_file):
    size = ctx.settings.default_chunk_size
    result = ingest_local_file(ctx, write_file(pattern(24, size * 4)), "a.bin", mode="chunk")
    with session_scope(ctx.session_factory) as session:
        chunks = list(session.scalars(select(Chunk)))
    ctx.hdfs.delete(chunks[0].hdfs_path)
    ctx.hdfs.delete(chunks[1].hdfs_path)
    ctx.hdfs.create(chunks[1].hdfs_path, pattern(25, size))
    check = integrity.verify_file(ctx, result.file.id)
    assert not check.ok
    assert check.missing == [chunks[0].sha256]
    assert check.corrupt == [chunks[1].sha256]
    assert check.chunks_checked == 4


def test_verification_detects_a_tampered_durable_manifest(ctx, write_file):
    result = ingest_local_file(ctx, write_file(pattern(26, 10_000)), "a.bin", mode="chunk")
    with session_scope(ctx.session_factory) as session:
        path = session.scalars(select(FileManifest)).first().hdfs_path
    ctx.hdfs.delete(path)
    ctx.hdfs.create(path, b'{"chunks": []}')
    check = integrity.verify_file(ctx, result.file.id)
    assert not check.ok and "disagrees" in check.detail


def test_download_aborts_rather_than_serving_a_corrupt_chunk(ctx, write_file):
    size = ctx.settings.default_chunk_size
    result = ingest_local_file(ctx, write_file(pattern(27, size * 3)), "a.bin", mode="chunk")
    with session_scope(ctx.session_factory) as session:
        path = session.scalars(select(Chunk)).first().hdfs_path
    ctx.hdfs.delete(path)
    ctx.hdfs.create(path, pattern(28, size))
    with pytest.raises(IntegrityFailure):
        list(integrity.stream_verified(ctx, result.file.id))


def test_hdfs_outage_during_verify_is_an_error_not_a_failed_check(ctx, write_file):
    from app.core.errors import HdfsUnavailable

    result = ingest_local_file(ctx, write_file(pattern(29, 100)), "a.bin", mode="file")
    ctx.hdfs = FaultInjector(ctx.hdfs, method="open")
    with pytest.raises(HdfsUnavailable):
        integrity.verify_file(ctx, result.file.id)
    with session_scope(ctx.session_factory) as session:
        assert session.scalar(select(func.count()).select_from(IntegrityCheck)) == 0


# -- crash recovery -------------------------------------------------------------------------------


def test_startup_marks_running_jobs_interrupted_and_clears_staging(ctx):
    with session_scope(ctx.session_factory) as session:
        session.add(DeduplicationJob(id="j" * 32, kind="optimize", status=JobStatus.RUNNING))
    ctx.hdfs.create(ctx.paths.staging_path("leftover"), b"partial")
    summary = lifecycle.recover_on_startup(ctx)
    assert summary["jobs_interrupted"] == 1 and summary["staging_removed"] == 1
    with session_scope(ctx.session_factory) as session:
        assert session.get(DeduplicationJob, "j" * 32).status == JobStatus.INTERRUPTED
    assert ctx.hdfs.list_dir(ctx.paths.staging) == []


def test_startup_survives_hdfs_being_down(ctx):
    ctx.hdfs = FaultInjector(ctx.hdfs, method="mkdirs")
    summary = lifecycle.recover_on_startup(ctx)
    assert summary["hdfs_available"] is False


def test_reconcile_finds_orphans_and_missing_without_deleting(ctx, write_file):
    keep = ingest_local_file(ctx, write_file(pattern(30, 100)), "a.bin", mode="file")
    lost = ingest_local_file(ctx, write_file(pattern(31, 100)), "b.bin", mode="file")
    ctx.hdfs.delete(ctx.paths.object_path(lost.file.sha256))
    orphan = ctx.paths.object_path("f" * 64)
    ctx.hdfs.create(orphan, b"orphan bytes")

    report = lifecycle.reconcile(ctx)
    assert report["orphan_count"] == 1 and report["missing_count"] == 1
    assert ctx.hdfs.status(orphan) is not None  # report-only by default

    applied = lifecycle.reconcile(ctx, apply=True)
    assert applied["orphans_quarantined"] == 1
    assert ctx.hdfs.status(orphan) is None
    assert ctx.hdfs.status(ctx.paths.recovery_orphan_path("f" * 64)) is not None
    assert ctx.hdfs.status(ctx.paths.object_path(keep.file.sha256)) is not None


def test_database_rejects_inconsistent_storage_pointers(ctx, write_file):
    from sqlalchemy.exc import IntegrityError

    result = ingest_local_file(ctx, write_file(pattern(32, 100)), "a.bin", mode="file")
    with pytest.raises(IntegrityError), session_scope(ctx.session_factory) as session:
        session.get(LogicalFile, result.file.id).object_id = None


def test_database_rejects_deleting_a_referenced_object(ctx, write_file):
    from sqlalchemy.exc import IntegrityError

    result = ingest_local_file(ctx, write_file(pattern(33, 100)), "a.bin", mode="file")
    with pytest.raises(IntegrityError), session_scope(ctx.session_factory) as session:
        session.delete(session.scalar(select(ContentObject).where(ContentObject.sha256 == result.file.sha256)))

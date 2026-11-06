"""Analysis, optimization, metrics definitions and replication validation."""

import pytest
from app.core.db import session_scope
from app.core.errors import ConflictError, ValidationFailure
from app.models.entities import (
    DeduplicationJob,
    JobStatus,
    OptimizationHistory,
    ReplicationOperation,
)
from app.services import analytics, integrity, lifecycle, optimizer, replication
from app.services.analytics import dedup_ratio, savings_percent
from app.services.ingest import ingest_local_file
from conftest import pattern
from sqlalchemy import select
from support.local_fs_adapter import FaultInjector


def job(ctx, job_id) -> DeduplicationJob:
    with session_scope(ctx.session_factory) as session:
        return session.get(DeduplicationJob, job_id)


def stats(ctx) -> dict:
    with session_scope(ctx.session_factory) as session:
        return analytics.storage_statistics(session)


def upload_duplicates(ctx, write_file, copies=3, size=20_000, seed=1):
    data = pattern(seed, size)
    return data, [ingest_local_file(ctx, write_file(data), f"copy{i}.bin", mode="raw") for i in range(copies)]


# -- formula definitions --------------------------------------------------------------------------


def test_savings_formula():
    assert savings_percent(1000, 250) == 75.0
    assert savings_percent(1000, 1000) == 0.0


def test_ratio_formula():
    assert dedup_ratio(1000, 250) == 4.0


def test_metrics_are_undefined_rather_than_dividing_by_zero():
    assert savings_percent(0, 0) is None
    assert dedup_ratio(0, 0) is None


def test_empty_system_reports_undefined_metrics(ctx):
    current = stats(ctx)
    assert current["logical_files"] == 0
    assert current["savings_percent"] is None and current["dedup_ratio"] is None


def test_statistics_on_a_known_mix(ctx, write_file):
    one, two = pattern(1, 1000), pattern(2, 3000)
    ingest_local_file(ctx, write_file(one), "a", mode="file")
    ingest_local_file(ctx, write_file(one), "b", mode="file")
    ingest_local_file(ctx, write_file(two), "c", mode="raw")
    current = stats(ctx)
    assert current["logical_files"] == 3
    assert current["unique_files"] == 2
    assert current["duplicate_files"] == 1
    assert current["logical_bytes"] == 5000
    assert current["unique_content_bytes"] == 4000
    assert current["stored_content_bytes"] == 4000
    assert current["bytes_avoided"] == 1000
    assert current["savings_percent"] == 20.0
    assert current["dedup_ratio"] == 1.25


def test_measured_values_come_from_the_store_not_from_multiplication(ctx, write_file):
    ingest_local_file(ctx, write_file(pattern(3, 1000)), "a", mode="file")
    ctx.hdfs.set_replication(ctx.paths.object_path(stats_sha(ctx)), 2)
    with session_scope(ctx.session_factory) as session:
        full = analytics.full_statistics(ctx, session)
    assert full["measured"]["available"] is True
    assert full["measured"]["space_consumed"] == 2000  # what the store reports, despite the default of 3
    assert full["estimated"]["replication_adjusted_bytes"] == 3000


def stats_sha(ctx):
    from app.models.entities import ContentObject

    with session_scope(ctx.session_factory) as session:
        return session.scalars(select(ContentObject.sha256)).first()


def test_measured_values_report_an_outage_rather_than_a_guess(ctx):
    ctx.hdfs = FaultInjector(ctx.hdfs, method="content_summary")
    measured = analytics.measured_hdfs(ctx)
    assert measured["available"] is False and "Injected" in measured["error"]


# -- analysis -------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode,chunk_size", [("file", None), ("chunk", 4096)])
def test_analysis_changes_nothing_and_predicts_the_real_outcome(ctx, write_file, mode, chunk_size):
    upload_duplicates(ctx, write_file)
    before = stats(ctx)
    before_paths = ctx.hdfs.content_summary(ctx.paths.root)

    analysis_id = ctx.jobs.submit("analyze", mode=mode, chunk_size=chunk_size)
    preview = job(ctx, analysis_id).result
    assert preview["estimated"] is True
    assert preview["files_eligible"] == 3
    assert stats(ctx) == before
    assert ctx.hdfs.content_summary(ctx.paths.root) == before_paths

    run_id = ctx.jobs.submit("optimize", mode=mode, chunk_size=chunk_size)
    assert job(ctx, run_id).status == JobStatus.SUCCEEDED
    assert stats(ctx)["stored_content_bytes"] == preview["predicted_stored_bytes"]


def test_chunk_analysis_counts_shared_chunks_across_files(ctx, write_file):
    size = ctx.settings.default_chunk_size
    shared = pattern(4, size * 2)
    ingest_local_file(ctx, write_file(shared + pattern(5, size)), "a", mode="raw")
    ingest_local_file(ctx, write_file(shared + pattern(6, size)), "b", mode="raw")
    preview = job(ctx, ctx.jobs.submit("analyze", mode="chunk", chunk_size=size)).result
    assert preview["chunks_examined"] == 6
    assert preview["chunks_new"] == 4
    assert preview["chunks_reused"] == 2


def test_optimization_requires_a_successful_current_preview(ctx, write_file):
    upload_duplicates(ctx, write_file)
    with pytest.raises(Exception, match="No analysis job"):
        optimizer.validate_analysis_for_optimize(ctx, "does-not-exist")
    analysis_id = ctx.jobs.submit("analyze", mode="file")
    assert optimizer.validate_analysis_for_optimize(ctx, analysis_id).id == analysis_id


def test_preview_goes_stale_when_files_change(ctx, write_file):
    upload_duplicates(ctx, write_file)
    analysis_id = ctx.jobs.submit("analyze", mode="file")
    ingest_local_file(ctx, write_file(pattern(7, 100)), "new", mode="raw")
    with pytest.raises(ConflictError, match="changed"):
        optimizer.validate_analysis_for_optimize(ctx, analysis_id)


# -- optimization ---------------------------------------------------------------------------------


def test_file_level_optimization_keeps_one_copy_and_preserves_bytes(ctx, write_file):
    data, uploads = upload_duplicates(ctx, write_file)
    assert ctx.hdfs.content_summary(ctx.paths.raw).file_count == 3
    run_id = ctx.jobs.submit("optimize", mode="file")
    result = job(ctx, run_id).result
    assert result["files_processed"] == 3 and result["files_failed"] == 0
    assert result["bytes_reclaimed"] == 40_000
    assert ctx.hdfs.content_summary(ctx.paths.raw).file_count == 0
    assert ctx.hdfs.content_summary(ctx.paths.objects).file_count == 1
    for upload in uploads:
        assert b"".join(integrity.stream_verified(ctx, upload.file.id)) == data
        assert integrity.verify_file(ctx, upload.file.id).ok


def test_chunk_level_optimization_collects_replaced_objects(ctx, write_file):
    data = pattern(8, 20_000)
    uploads = [ingest_local_file(ctx, write_file(data), f"{i}", mode="file") for i in range(2)]
    run_id = ctx.jobs.submit("optimize", mode="chunk", chunk_size=4096)
    result = job(ctx, run_id).result
    assert result["garbage_collected"]["object_count"] == 1
    assert stats(ctx)["object_count"] == 0
    assert ctx.hdfs.content_summary(ctx.paths.objects).file_count == 0
    for upload in uploads:
        assert b"".join(integrity.stream_verified(ctx, upload.file.id)) == data


def test_optimization_is_recorded_with_verified_before_and_after(ctx, write_file):
    upload_duplicates(ctx, write_file)
    run_id = ctx.jobs.submit("optimize", mode="file")
    with session_scope(ctx.session_factory) as session:
        record = session.scalar(select(OptimizationHistory).where(OptimizationHistory.job_id == run_id))
        assert record.before["derived"]["stored_content_bytes"] == 60_000
        assert record.after["derived"]["stored_content_bytes"] == 20_000
        assert record.before["measured"]["length"] == 60_000
        assert record.after["measured"]["length"] == 20_000
    assert job(ctx, run_id).result["estimated"] is False


def test_corrupted_source_is_not_promoted_and_other_files_continue(ctx, write_file):
    good = ingest_local_file(ctx, write_file(pattern(9, 1000)), "good", mode="raw")
    bad = ingest_local_file(ctx, write_file(pattern(10, 1000)), "bad", mode="raw")
    ctx.hdfs.delete(bad.file.raw_path)
    ctx.hdfs.create(bad.file.raw_path, pattern(11, 1000))

    run = job(ctx, ctx.jobs.submit("optimize", mode="file"))
    assert run.status == JobStatus.PARTIAL
    assert run.result["files_processed"] == 1 and run.result["files_failed"] == 1
    assert run.result["errors"][0]["file_id"] == bad.file.id
    assert ctx.hdfs.status(bad.file.raw_path) is not None  # left exactly where it was
    assert integrity.verify_file(ctx, good.file.id).ok


def test_outage_mid_job_fails_visibly_and_a_resume_finishes_safely(ctx, write_file):
    data_a, uploads_a = upload_duplicates(ctx, write_file, copies=2, seed=20)
    data_b, uploads_b = upload_duplicates(ctx, write_file, copies=2, seed=21)
    real = ctx.hdfs
    # The first content converts, then HDFS "goes down" while reading the second content for verification.
    ctx.hdfs = FaultInjector(real, method="open", on_call=2)
    first = job(ctx, ctx.jobs.submit("optimize", mode="file"))
    assert first.status == JobStatus.FAILED and "Injected" in first.error
    ctx.hdfs = real
    assert stats(ctx)["files_by_mode"] == {"file": 2, "raw": 2}  # converted files stayed converted

    second = job(ctx, ctx.jobs.submit("optimize", mode="file", resumed_from_id=first.id))
    assert second.status == JobStatus.SUCCEEDED
    assert second.result["files_processed"] == 2  # only what was left
    assert stats(ctx)["stored_content_bytes"] == len(data_a) + len(data_b)
    for data, uploads in ((data_a, uploads_a), (data_b, uploads_b)):
        for upload in uploads:
            assert b"".join(integrity.stream_verified(ctx, upload.file.id)) == data


def test_crash_between_rename_and_commit_is_adopted_on_rerun(ctx, write_file):
    """The raw file reached its object path, but the process died before the metadata commit."""
    data, uploads = upload_duplicates(ctx, write_file, copies=1)
    file = uploads[0].file
    target = ctx.paths.object_path(file.sha256)
    ctx.hdfs.mkdirs(target.rsplit("/", 1)[0])
    assert ctx.hdfs.rename(file.raw_path, target)

    run = job(ctx, ctx.jobs.submit("optimize", mode="file"))
    assert run.status == JobStatus.SUCCEEDED
    assert b"".join(integrity.stream_verified(ctx, file.id)) == data


def test_failure_removing_old_copy_after_commit_leaves_a_detectable_orphan(ctx, write_file):
    from app.core.errors import HdfsError

    data, uploads = upload_duplicates(ctx, write_file, copies=2)
    real = ctx.hdfs
    ctx.hdfs = FaultInjector(real, method="delete", error=HdfsError("delete refused"))
    run = job(ctx, ctx.jobs.submit("optimize", mode="file"))
    ctx.hdfs = real
    assert run.status == JobStatus.SUCCEEDED, run.result["errors"]  # both files really did convert
    assert len(run.result["orphans_left"]) == 1
    for upload in uploads:
        assert b"".join(integrity.stream_verified(ctx, upload.file.id)) == data
    report = lifecycle.reconcile(ctx, apply=True)
    assert report["orphan_count"] == 1 and report["orphans_quarantined"] == 1
    assert ctx.hdfs.content_summary(ctx.paths.raw).file_count == 0


def test_rerunning_a_finished_optimization_is_a_no_op(ctx, write_file):
    upload_duplicates(ctx, write_file)
    ctx.jobs.submit("optimize", mode="file")
    again = job(ctx, ctx.jobs.submit("optimize", mode="file"))
    assert again.result["files_processed"] == 0
    assert again.result["bytes_reclaimed"] == 0


# -- replication ----------------------------------------------------------------------------------


def test_replication_above_live_datanodes_is_rejected(ctx):
    with pytest.raises(ValidationFailure, match="cannot be satisfied"):
        replication.request_change(ctx, 4)


def test_replication_three_is_rejected_when_only_two_datanodes_are_live(ctx):
    ctx.monitor.live = 2
    with pytest.raises(ValidationFailure):
        replication.request_change(ctx, 3)


def test_lowering_replication_requires_acknowledgement(ctx):
    with pytest.raises(ConflictError, match="reduces fault tolerance"):
        replication.request_change(ctx, 1)


def test_replication_change_applies_and_is_verified(ctx, write_file):
    result = ingest_local_file(ctx, write_file(pattern(12, 1000)), "a", mode="file")
    change = replication.request_change(ctx, 2, acknowledge_reduced_protection=True)
    path = ctx.paths.object_path(result.file.sha256)
    assert ctx.hdfs.status(path).replication == 2
    with session_scope(ctx.session_factory) as session:
        operation = session.get(ReplicationOperation, change["operation_id"])
        assert operation.status == "verified"
        assert (operation.space_consumed_before, operation.space_consumed_after) == (3000, 2000)


def test_new_writes_use_the_target_replication(ctx, write_file):
    replication.request_change(ctx, 2, acknowledge_reduced_protection=True)
    result = ingest_local_file(ctx, write_file(pattern(13, 100)), "a", mode="file")
    assert ctx.hdfs.status(ctx.paths.object_path(result.file.sha256)).replication == 2


def test_replication_cannot_change_while_namenode_is_down(ctx):
    from app.core.errors import HdfsUnavailable

    ctx.monitor.reachable = False
    with pytest.raises(HdfsUnavailable):
        replication.request_change(ctx, 2, acknowledge_reduced_protection=True)


def test_convergence_timeout_scales_with_the_namespace():
    assert replication.convergence_timeout(10, 3) == replication.MINIMUM_VERIFY_SECONDS
    # 274 blocks at 6 blocks per 3-second cycle needs 137 s at best; allow for that with a margin.
    assert replication.convergence_timeout(274, 3) > 137 * 2
    assert replication.convergence_timeout(10_000, 3) > replication.convergence_timeout(274, 3)


def test_deduplication_never_changes_replication(ctx, write_file):
    _, uploads = upload_duplicates(ctx, write_file)
    ctx.jobs.submit("optimize", mode="file")
    status = ctx.hdfs.status(ctx.paths.object_path(uploads[0].file.sha256))
    assert status.replication == ctx.hdfs.default_replication()

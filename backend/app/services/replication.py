"""HDFS replication management.

Replication is fault tolerance, not waste. Deduplication works on identical content; it never removes
a block replica. Changing the factor is a separate, explicit decision with its own safety checks.
"""

from __future__ import annotations

import time

from sqlalchemy import select

from app.core.db import session_scope, utcnow
from app.core.errors import ConflictError, HdfsError, HdfsUnavailable, ValidationFailure
from app.hdfs.base import walk_files
from app.models.entities import ReplicationOperation
from app.services import audit, settings_store
from app.services.context import AppContext

MINIMUM_VERIFY_SECONDS = 180.0
VERIFY_POLL_SECONDS = 3.0
# HDFS defaults: each 3-second cycle schedules about 2 x live DataNodes blocks for re-replication.
REDUNDANCY_INTERVAL_SECONDS = 3.0
WORK_MULTIPLIER_PER_ITERATION = 2


def convergence_timeout(blocks: int, live_datanodes: int, *, safety_factor: float = 3.0) -> float:
    """How long to wait for HDFS, scaled to its re-replication rate, so that a large namespace of small
    chunk files is not reported as a failure while HDFS is still correctly working through it."""
    per_cycle = max(1, WORK_MULTIPLIER_PER_ITERATION * live_datanodes)
    expected = blocks / per_cycle * REDUNDANCY_INTERVAL_SECONDS
    return max(MINIMUM_VERIFY_SECONDS, expected * safety_factor)


def replication_status(ctx: AppContext) -> dict:
    cluster = ctx.monitor.status()
    with session_scope(ctx.session_factory) as session:
        target = settings_store.get_value(ctx, session, "target_replication")
        operations = [_operation_dict(op) for op in session.scalars(select(ReplicationOperation).order_by(ReplicationOperation.requested_at.desc()).limit(20))]
    if not cluster["reachable"]:
        return {"reachable": False, "error": cluster.get("error"), "target_replication": target, "operations": operations}

    cluster_default = ctx.hdfs.default_replication()
    effective = target or cluster_default
    live = cluster["datanodes"]["live"]
    fsck = ctx.monitor.fsck(ctx.paths.root)
    summary = ctx.hdfs.content_summary(ctx.paths.root)
    warnings = []
    if effective > live:
        warnings.append(
            f"The target of {effective} replicas exceeds the {live} live DataNodes, so blocks cannot be fully replicated."
        )
    if fsck.get("under_replicated_blocks"):
        count = fsck["under_replicated_blocks"]
        warnings.append("1 managed block is under-replicated." if count == 1 else f"{count} managed blocks are under-replicated.")
    if effective == 1:
        warnings.append("With one replica, losing a single DataNode can lose data.")
    return {
        "reachable": True,
        "cluster_default_replication": cluster_default,
        "target_replication": target,
        "effective_replication": effective,
        "live_datanodes": live,
        "dead_datanodes": cluster["datanodes"]["dead"],
        "max_supported_replication": live,
        "fsck": fsck,
        "stored_length_bytes": summary.length,
        "space_consumed_bytes": summary.space_consumed,
        "measured_replication_multiplier": (summary.space_consumed / summary.length) if summary.length else None,
        "warnings": warnings,
        "operations": operations,
        "checked_at": cluster["checked_at"],
    }


def _operation_dict(op: ReplicationOperation) -> dict:
    return {
        "id": op.id,
        "previous_factor": op.previous_factor,
        "requested_factor": op.requested_factor,
        "status": op.status,
        "files_total": op.files_total,
        "files_changed": op.files_changed,
        "space_consumed_before": op.space_consumed_before,
        "space_consumed_after": op.space_consumed_after,
        "details": op.details,
        "error": op.error,
        "requested_at": op.requested_at,
        "completed_at": op.completed_at,
    }


def request_change(ctx: AppContext, factor: int, *, acknowledge_reduced_protection: bool = False) -> dict:
    """Validate against live cluster state, then apply and verify in a background job."""
    if factor < 1:
        raise ValidationFailure("Replication factor must be at least 1.")
    cluster = ctx.monitor.status()
    if not cluster["reachable"]:
        raise HdfsUnavailable(f"Cannot change replication while the NameNode is unreachable: {cluster.get('error')}")
    live = cluster["datanodes"]["live"]
    if factor > live:
        raise ValidationFailure(
            f"Replication factor {factor} cannot be satisfied by {live} live DataNodes. HDFS would leave "
            "blocks permanently under-replicated.",
            details={"live_datanodes": live},
        )
    with session_scope(ctx.session_factory) as session:
        current = settings_store.get_value(ctx, session, "target_replication") or ctx.hdfs.default_replication()
    if factor < current and not acknowledge_reduced_protection:
        raise ConflictError(
            f"Lowering replication from {current} to {factor} reduces fault tolerance. Confirm this explicitly to continue.",
            details={"current": current, "requested": factor},
        )
    with session_scope(ctx.session_factory) as session:
        operation = ReplicationOperation(previous_factor=current, requested_factor=factor)
        session.add(operation)
        session.flush()
        operation_id = operation.id
        audit.record(session, "replication.requested", f"Replication change requested: {current} to {factor}.", entity_type="replication", entity_id=operation_id)
    job_id = ctx.jobs.submit("replication", params={"operation_id": operation_id, "factor": factor})
    return {"operation_id": operation_id, "job_id": job_id, "previous_factor": current, "requested_factor": factor}


def run_replication_change(ctx: AppContext, job_id: str, params: dict, reporter) -> dict:
    operation_id, factor = params["operation_id"], params["factor"]
    try:
        before = ctx.hdfs.content_summary(ctx.paths.root)
        files = list(walk_files(ctx.hdfs, ctx.paths.root))
        reporter.progress(0, len(files), f"Requesting replication {factor} on {len(files)} files")
        changed = 0
        for index, entry in enumerate(files, start=1):
            if entry.replication != factor and ctx.hdfs.set_replication(entry.path, factor):
                changed += 1
            if index % 50 == 0 or index == len(files):
                reporter.progress(index, len(files), f"Requested on {index} of {len(files)} files")
        with session_scope(ctx.session_factory) as session:
            settings_store.update(ctx, session, {"target_replication": factor})
            operation = session.get(ReplicationOperation, operation_id)
            operation.status = "applied"
            operation.files_total, operation.files_changed = len(files), changed
            operation.space_consumed_before = before.space_consumed

        verified, fsck, block_sample = _wait_until_converged(ctx, factor, files, reporter)
        after = ctx.hdfs.content_summary(ctx.paths.root)
        with session_scope(ctx.session_factory) as session:
            operation = session.get(ReplicationOperation, operation_id)
            operation.status = "verified" if verified else "timed_out"
            operation.space_consumed_after = after.space_consumed
            operation.details = {"fsck": fsck, "block_sample": block_sample}
            operation.completed_at = utcnow()
            audit.record(
                session,
                "replication.verified" if verified else "replication.timed_out",
                f"Replication {factor}: "
                + ("every block has the requested number of replicas." if verified else "blocks did not converge before the timeout."),
                severity="info" if verified else "warning",
                entity_type="replication",
                entity_id=operation_id,
            )
        return {
            "verified": verified,
            "files_total": len(files),
            "files_changed": changed,
            "space_consumed_before": before.space_consumed,
            "space_consumed_after": after.space_consumed,
            "fsck": fsck,
        }
    except HdfsError as exc:
        with session_scope(ctx.session_factory) as session:
            operation = session.get(ReplicationOperation, operation_id)
            operation.status = "failed"
            operation.error = exc.message
            operation.completed_at = utcnow()
        raise


def _wait_until_converged(ctx: AppContext, factor: int, files: list, reporter) -> tuple[bool, dict, list]:
    """HDFS re-replicates asynchronously, so success is observed rather than assumed.

    fsck stops counting a replica as soon as it is marked excess, which is before the DataNode deletes it.
    Convergence therefore also requires the block locations themselves to show the requested count.
    """
    live = ctx.monitor.status().get("datanodes", {}).get("live", 1)
    deadline = time.monotonic() + convergence_timeout(len(files), live)
    fsck: dict = {}
    while True:
        fsck = ctx.monitor.fsck(ctx.paths.root)
        converged = (
            fsck.get("under_replicated_blocks") == 0
            and fsck.get("over_replicated_blocks") == 0
            and fsck.get("missing_blocks") == 0
            and (fsck.get("total_blocks") == 0 or fsck.get("average_block_replication") == float(factor))
        )
        sample = _sample_block_locations(ctx, files)
        if converged and all(len(block["hosts"]) == factor for block in sample):
            return True, fsck, sample
        if time.monotonic() >= deadline:
            return False, fsck, sample
        reporter.progress(len(files), len(files), f"Waiting for HDFS to reach {factor} replicas (average {fsck.get('average_block_replication')})")
        time.sleep(VERIFY_POLL_SECONDS)


def _sample_block_locations(ctx: AppContext, files: list, limit: int = 25) -> list[dict]:
    sample = []
    for entry in [f for f in files if f.length > 0][:limit]:
        for block in ctx.hdfs.block_locations(entry.path):
            sample.append({"path": entry.path, "block_id": block.block_id, "length": block.length, "hosts": list(block.hosts)})
    return sample

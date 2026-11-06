"""Reproducible experiments against the real cluster.

Each run uses its own HDFS directory and its own temporary metadata database, so it can never touch
managed user data. Every number returned is measured during the run.
"""

from __future__ import annotations

import csv
import hashlib
import io
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import select

from app.core.db import Base, make_engine, make_session_factory, session_scope, utcnow
from app.core.errors import ValidationFailure
from app.models.entities import ExperimentRun
from app.services import (
    audit,
    datasets,
    ingest,
    integrity,
    lifecycle,
    optimizer,
    replication,
)
from app.services.analytics import dedup_ratio, savings_percent, storage_statistics
from app.services.context import AppContext, StoragePaths
from app.services.jobs import JobManager

EXPERIMENT_ROOT = "/hdfs-optimizer-experiments"
KIB = 1024
MIB = 1024 * 1024
DEFAULT_CHUNK_SIZES = (16 * KIB, 64 * KIB, 256 * KIB, 1 * MIB, 4 * MIB)
JOB_HANDLERS = {
    "analyze": optimizer.run_analysis,
    "optimize": optimizer.run_optimization,
    "replication": replication.run_replication_change,
}


class IsolatedRun:
    """A throwaway copy of the application state, backed by the real HDFS cluster."""

    def __init__(self, ctx: AppContext):
        self.parent = ctx
        self.run_id = uuid.uuid4().hex
        self.root = f"{EXPERIMENT_ROOT}/{self.run_id}"
        self.workdir = Path(tempfile.mkdtemp(prefix="hdfsopt-exp-"))

    def __enter__(self) -> AppContext:
        engine = make_engine(self.workdir / "metadata.db")
        Base.metadata.create_all(engine)
        self.engine = engine
        self.ctx = AppContext(
            settings=self.parent.settings,
            session_factory=make_session_factory(engine),
            hdfs=self.parent.hdfs,
            paths=StoragePaths(root=self.root),
            monitor=self.parent.monitor,
        )
        self.ctx.jobs = JobManager(self.ctx, JOB_HANDLERS, synchronous=True)
        self.ctx.ensure_namespace()
        return self.ctx

    def __exit__(self, *_exc) -> None:
        if not self.root.startswith(f"{EXPERIMENT_ROOT}/") or len(self.root) <= len(EXPERIMENT_ROOT) + 8:
            raise RuntimeError(f"Refusing to clean unexpected path: {self.root}")
        try:
            self.parent.hdfs.delete(self.root, recursive=True)
        finally:
            self.engine.dispose()
            shutil.rmtree(self.workdir, ignore_errors=True)


def snapshot(ctx: AppContext) -> dict:
    """Metadata-derived and NameNode-measured values at this moment."""
    with session_scope(ctx.session_factory) as session:
        stats = storage_statistics(session)
    summary = ctx.hdfs.content_summary(ctx.paths.root)
    return {
        "logical_files": stats["logical_files"],
        "unique_files": stats["unique_files"],
        "duplicate_files": stats["duplicate_files"],
        "logical_bytes": stats["logical_bytes"],
        "stored_content_bytes": stats["stored_content_bytes"],
        "bytes_avoided": stats["bytes_avoided"],
        "savings_percent": stats["savings_percent"],
        "dedup_ratio": stats["dedup_ratio"],
        "chunk_count": stats["chunk_count"],
        "chunk_references": stats["chunk_references"],
        "duplicate_chunk_references": stats["duplicate_chunk_references"],
        "manifest_count": stats["manifest_count"],
        "manifest_bytes": stats["manifest_bytes"],
        "hdfs_length_bytes": summary.length,
        "hdfs_space_consumed_bytes": summary.space_consumed,
        "hdfs_file_count": summary.file_count,
        "hdfs_directory_count": summary.directory_count,
    }


def stable_disk(probe: Callable[[], int], *, interval: float = 3.0, needed: int = 3, timeout: float = 120.0) -> int:
    """Read disk usage once it stops changing.

    DataNodes delete blocks asynchronously after the NameNode's delete returns, so a single reading can
    still include blocks from earlier work. Raises rather than returning a value that never stabilised.
    """
    deadline = time.monotonic() + timeout
    previous, repeats = probe(), 1
    while repeats < needed:
        if time.monotonic() > deadline:
            raise RuntimeError(f"DataNode disk usage did not stabilise within {timeout} s.")
        time.sleep(interval)
        current = probe()
        repeats = repeats + 1 if current == previous else 1
        previous = current
    return previous


def namespace_cost(ctx: AppContext) -> dict:
    """Objects this run adds to the NameNode. Read from uncached sources for this run's directory only;
    NameNode JMX values such as FilesTotal are cached for about ten seconds and include the whole cluster."""
    summary = ctx.hdfs.content_summary(ctx.paths.root)
    fsck = ctx.monitor.fsck(ctx.paths.root)
    blocks = fsck["total_blocks"] or 0
    return {
        "namespace_files": summary.file_count,
        "namespace_directories": summary.directory_count,
        "namespace_blocks": blocks,
        "namespace_objects": summary.file_count + summary.directory_count + blocks,
    }


def _load_sources(ctx: AppContext, kinds: tuple[str, ...] = ("original",), formats: tuple[str, ...] = ("txt",)) -> list[dict]:
    manifest = datasets._read_manifest(ctx.settings.provenance_path)
    rows = [f for f in manifest["files"] if f["kind"] in kinds and f["file_format"] in formats]
    usable = []
    for row in rows:
        path = ctx.settings.dataset_dir / row["local_path"]
        if path.exists():
            usable.append({**row, "path": path})
    if not usable:
        raise ValidationFailure("No authentic dataset files are available. Import the dataset first.")
    usable.sort(key=lambda r: r["size_bytes"])
    return usable


def _verify_all(ctx: AppContext) -> dict:
    with session_scope(ctx.session_factory) as session:
        rows = session.execute(select(integrity.LogicalFile.id).where(integrity.LogicalFile.status == "active")).scalars().all()
    started = time.perf_counter()
    passed = 0
    total_bytes = 0
    for file_id in rows:
        check = integrity.verify_file(ctx, file_id)
        passed += int(check.ok)
        total_bytes += check.bytes_read
    return {
        "files_checked": len(rows),
        "files_passed": passed,
        "bytes_read": total_bytes,
        "duration_s": time.perf_counter() - started,
    }


def _throughput(total_bytes: int, seconds: float) -> float | None:
    return total_bytes / MIB / seconds if seconds > 0 else None


def _ingest_timed(ctx: AppContext, items: list[tuple[Path, str, str]], mode: str, chunk_size: int | None = None) -> dict:
    total_bytes, hash_ms = 0, 0.0
    started = time.perf_counter()
    for path, name, label in items:
        outcome = ingest.ingest_local_file(ctx, path, name, folder="/experiment", mode=mode, chunk_size=chunk_size, provenance_label=label)
        total_bytes += outcome.file.size_bytes
        hash_ms += outcome.hash_ms
    seconds = time.perf_counter() - started
    return {
        "upload_duration_s": seconds,
        "hash_duration_s": hash_ms / 1000,
        "upload_bytes": total_bytes,
        "upload_throughput_mib_s": _throughput(total_bytes, seconds),
    }


def _workload_copies(sources: list[dict], copies: int) -> list[tuple[Path, str, str]]:
    items = []
    for row in sources:
        path = row["path"]
        items.append((path, path.name, "dataset_original"))
        for index in range(1, copies + 1):
            items.append((path, f"{path.stem}__workload-copy-{index}{path.suffix}", "workload_copy"))
    return items


# -- scenarios --------------------------------------------------------------------------------------


def scenario_a_unique(ctx: AppContext, params: dict) -> dict:
    """A: only distinct originals. Deduplication has nothing to find; savings should be about zero."""
    sources = _load_sources(ctx)
    rows = []
    for mode in ("file", "chunk"):
        with IsolatedRun(ctx) as run:
            timing = _ingest_timed(run, _workload_copies(sources, 0), mode, MIB)
            rows.append({"mode": mode, **timing, **snapshot(run)})
    return {"description": "Distinct authentic files only.", "sources": len(sources), "rows": rows}


def scenario_b_exact_duplicates(ctx: AppContext, params: dict) -> dict:
    """B: originals plus N byte-identical workload copies, with and without deduplication."""
    sources = _load_sources(ctx)
    rows = []
    for copies in params.get("copies", [1, 3, 5]):
        for mode in ("raw", "file"):
            with IsolatedRun(ctx) as run:
                timing = _ingest_timed(run, _workload_copies(sources, copies), mode)
                rows.append({"copies": copies, "mode": mode, **timing, **snapshot(run)})
    return {"description": "Each original plus N exact workload copies.", "sources": len(sources), "rows": rows}


def scenario_c_many_names(ctx: AppContext, params: dict) -> dict:
    """C: one authentic file under many logical names must yield exactly one stored object."""
    source = _load_sources(ctx)[0]
    names = params.get("names", 20)
    items = [(source["path"], f"name-{i:03d}{source['path'].suffix}", "workload_copy") for i in range(names)]
    with IsolatedRun(ctx) as run:
        timing = _ingest_timed(run, items, "file")
        result = {**timing, **snapshot(run), "verification": _verify_all(run)}
    return {
        "description": "One authentic file referenced under many logical names.",
        "source": source["title"],
        "source_bytes": source["size_bytes"],
        "logical_names": names,
        "rows": [result],
    }


def scenario_d_chunk_sizes(ctx: AppContext, params: dict, physical_probe: Callable[[], int] | None = None) -> dict:
    """D: chunk-level deduplication on originals plus documented partial-overlap files, per chunk size."""
    originals = _load_sources(ctx)
    transformed = _load_sources(ctx, kinds=("transformed",))
    items = [(r["path"], r["path"].name, "dataset_original") for r in originals]
    items += [(r["path"], r["path"].name, "transformed") for r in transformed]

    def measure(run: AppContext, mode: str, chunk_size: int | None) -> dict:
        disk_before = stable_disk(physical_probe) if physical_probe else None
        timing = _ingest_timed(run, items, mode, chunk_size)
        disk_after = stable_disk(physical_probe) if physical_probe else None
        return {
            "mode": mode,
            "chunk_size": chunk_size,
            **timing,
            **snapshot(run),
            **namespace_cost(run),
            "disk_used_delta": None if physical_probe is None else disk_after - disk_before,
        }

    rows = []
    with IsolatedRun(ctx) as run:
        rows.append(measure(run, "file", None))
    for chunk_size in params.get("chunk_sizes", DEFAULT_CHUNK_SIZES):
        with IsolatedRun(ctx) as run:
            rows.append(measure(run, "chunk", chunk_size))
    return {
        "description": "Originals plus truncated, one-byte-shifted and one-byte-edited variants of one book.",
        "transformations": datasets.TRANSFORMATIONS,
        "rows": rows,
    }


def scenario_d2_boundary_shift(ctx: AppContext, params: dict) -> dict:
    """D2: isolates the known weakness of fixed-size chunking, one variant at a time."""
    original = next(r for r in _load_sources(ctx) if r["ebook_id"] == 1342)
    variants = _load_sources(ctx, kinds=("transformed",))
    chunk_size = params.get("chunk_size", 64 * KIB)
    rows = []
    for variant in variants:
        with IsolatedRun(ctx) as run:
            ingest.ingest_local_file(run, original["path"], original["path"].name, mode="chunk", chunk_size=chunk_size)
            outcome = ingest.ingest_local_file(run, variant["path"], variant["path"].name, mode="chunk", chunk_size=chunk_size)
            rows.append(
                {
                    "variant": variant["local_path"].split("/")[-1],
                    "transformation": variant["transformations"],
                    "chunk_size": chunk_size,
                    "chunks_total": outcome.chunks_total,
                    "chunks_reused": outcome.chunks_reused,
                    "chunks_new": outcome.chunks_new,
                    "reuse_percent": outcome.chunks_reused / outcome.chunks_total * 100 if outcome.chunks_total else None,
                    "bytes_written_including_manifest": outcome.bytes_written,
                    "variant_bytes": outcome.file.size_bytes,
                }
            )
    return {"description": "How much of each variant reuses the original's chunks.", "rows": rows}


def scenario_e_roundtrip(ctx: AppContext, params: dict) -> dict:
    """E: download every file in each mode and compare SHA-256 with the source on disk."""
    sources = _load_sources(ctx, formats=("txt", "html", "epub"))
    rows = []
    for mode in ("raw", "file", "chunk"):
        with IsolatedRun(ctx) as run:
            ids = {}
            for row in sources:
                outcome = ingest.ingest_local_file(run, row["path"], row["path"].name, mode=mode, chunk_size=256 * KIB)
                ids[outcome.file.id] = row
            matched, bytes_read = 0, 0
            started = time.perf_counter()
            for file_id, row in ids.items():
                digest = hashlib.sha256()
                for block in integrity.stream_verified(run, file_id):
                    digest.update(block)
                    bytes_read += len(block)
                matched += int(digest.hexdigest() == row["sha256"])
            seconds = time.perf_counter() - started
            rows.append(
                {
                    "mode": mode,
                    "files": len(ids),
                    "files_matching_source_sha256": matched,
                    "bytes_read": bytes_read,
                    "restore_duration_s": seconds,
                    "restore_throughput_mib_s": _throughput(bytes_read, seconds),
                }
            )
    return {"description": "Byte-for-byte restore compared with the publisher's bytes on disk.", "rows": rows}


def scenario_f_shared_deletion(ctx: AppContext, params: dict) -> dict:
    """F: deleting one logical file must leave shared content readable for the others."""
    source = _load_sources(ctx)[0]
    rows = []
    for mode in ("file", "chunk"):
        with IsolatedRun(ctx) as run:
            first = ingest.ingest_local_file(run, source["path"], "a.txt", mode=mode, chunk_size=64 * KIB)
            second = ingest.ingest_local_file(run, source["path"], "b.txt", mode=mode, chunk_size=64 * KIB)
            before = snapshot(run)
            lifecycle.soft_delete(run, first.file.id)
            lifecycle.purge(run, first.file.id)
            after_first = snapshot(run)
            survivor_ok = integrity.verify_file(run, second.file.id).ok
            lifecycle.soft_delete(run, second.file.id)
            restored = lifecycle.restore(run, second.file.id)
            restored_ok = integrity.verify_file(run, restored.id).ok
            lifecycle.soft_delete(run, second.file.id)
            lifecycle.purge(run, second.file.id)
            after_last = snapshot(run)
            rows.append(
                {
                    "mode": mode,
                    "stored_bytes_two_references": before["stored_content_bytes"],
                    "stored_bytes_after_purging_one": after_first["stored_content_bytes"],
                    "survivor_passes_sha256": survivor_ok,
                    "soft_delete_then_restore_passes_sha256": restored_ok,
                    "stored_bytes_after_purging_last": after_last["stored_content_bytes"],
                    "hdfs_files_after_purging_last": after_last["hdfs_file_count"],
                }
            )
    return {"description": "Reference-aware deletion of shared content.", "source": source["title"], "rows": rows}


def scenario_g_restore_after_optimize(ctx: AppContext, params: dict) -> dict:
    """G: upload without deduplication, optimize, then verify every restored file."""
    return scenario_i_before_after(ctx, {**params, "copies": params.get("copies", 2), "scenario": "G"})


def scenario_h_replication(ctx: AppContext, params: dict) -> dict:
    """H: real replication changes on an isolated directory, verified with fsck."""
    source = _load_sources(ctx)[0]
    factors = params.get("factors", [2, 3])
    live = ctx.monitor.status()["datanodes"]["live"]
    rows = []
    with IsolatedRun(ctx) as run:
        ingest.ingest_local_file(run, source["path"], source["path"].name, mode="file")
        rows.append({"step": "initial", "factor": run.hdfs.default_replication(), **_replication_measure(run)})
        for factor in factors:
            if factor > live:
                rows.append({"step": "skipped", "factor": factor, "reason": f"only {live} live DataNodes"})
                continue
            started = time.perf_counter()
            replication.request_change(run, factor, acknowledge_reduced_protection=True)
            rows.append(
                {"step": "changed", "factor": factor, "converged_in_s": time.perf_counter() - started, **_replication_measure(run)}
            )
        rejected = None
        try:
            replication.request_change(run, live + 1)
        except ValidationFailure as exc:
            rejected = exc.message
    return {"description": "Replication factor changes and measured effect.", "live_datanodes": live, "rows": rows, "rejected_over_limit": rejected}


def _replication_measure(run: AppContext) -> dict:
    summary = run.hdfs.content_summary(run.paths.root)
    fsck = run.monitor.fsck(run.paths.root)
    return {
        "length_bytes": summary.length,
        "space_consumed_bytes": summary.space_consumed,
        "multiplier": summary.space_consumed / summary.length if summary.length else None,
        "average_block_replication": fsck["average_block_replication"],
        "under_replicated_blocks": fsck["under_replicated_blocks"],
        "fsck_status": fsck["status"],
    }


def scenario_i_before_after(ctx: AppContext, params: dict, physical_probe: Callable[[], int] | None = None) -> dict:
    """I: identical data stored raw, then optimized in place, measured before and after by HDFS itself."""
    sources = _load_sources(ctx)
    copies = params.get("copies", 2)
    items = _workload_copies(sources, copies)
    rows = []
    for mode, chunk_size in (("file", None), ("chunk", 256 * KIB)):
        with IsolatedRun(ctx) as run:
            disk_baseline = stable_disk(physical_probe) if physical_probe else None
            timing = _ingest_timed(run, items, "raw")
            disk_before = stable_disk(physical_probe) if physical_probe else None
            before = snapshot(run)
            cost_before = namespace_cost(run)

            analysis_id = run.jobs.submit("analyze", mode=mode, chunk_size=chunk_size)
            preview = _job_result(run, analysis_id)
            started = time.perf_counter()
            job_id = run.jobs.submit("optimize", mode=mode, chunk_size=chunk_size)
            optimize_result = _job_result(run, job_id)
            optimize_seconds = time.perf_counter() - started
            disk_after = stable_disk(physical_probe) if physical_probe else None
            after = snapshot(run)
            cost_after = namespace_cost(run)
            verification = _verify_all(run)

            rows.append(
                {
                    "mode": mode,
                    "chunk_size": chunk_size,
                    "files": before["logical_files"],
                    "logical_bytes": before["logical_bytes"],
                    "stored_before": before["stored_content_bytes"],
                    "stored_after": after["stored_content_bytes"],
                    "predicted_stored_after": preview["predicted_stored_bytes"],
                    "hdfs_length_before": before["hdfs_length_bytes"],
                    "hdfs_length_after": after["hdfs_length_bytes"],
                    "hdfs_space_consumed_before": before["hdfs_space_consumed_bytes"],
                    "hdfs_space_consumed_after": after["hdfs_space_consumed_bytes"],
                    "hdfs_files_before": before["hdfs_file_count"],
                    "hdfs_files_after": after["hdfs_file_count"],
                    "namespace_objects_before": cost_before["namespace_objects"],
                    "namespace_objects_after": cost_after["namespace_objects"],
                    "disk_used_delta_before": None if physical_probe is None else disk_before - disk_baseline,
                    "disk_used_delta_after": None if physical_probe is None else disk_after - disk_baseline,
                    "savings_percent_after": savings_percent(after["logical_bytes"], after["stored_content_bytes"]),
                    "dedup_ratio_after": dedup_ratio(after["logical_bytes"], after["stored_content_bytes"]),
                    "upload_duration_s": timing["upload_duration_s"],
                    "optimize_duration_s": optimize_seconds,
                    "optimize_throughput_mib_s": _throughput(before["logical_bytes"], optimize_seconds),
                    "files_failed": optimize_result["files_failed"],
                    "verification": verification,
                }
            )
    return {"description": f"{copies} exact workload copies per original, stored raw, then optimized.", "sources": len(sources), "rows": rows}


def _job_result(run: AppContext, job_id: str) -> dict:
    with session_scope(run.session_factory) as session:
        job = session.get(optimizer.DeduplicationJob, job_id)
        if job.result is None:
            raise RuntimeError(f"Job {job.kind} failed: {job.error}")
        return job.result


SCENARIOS: dict[str, tuple[str, Callable[[AppContext, dict], dict]]] = {
    "A_unique_files": ("Unique authentic files", scenario_a_unique),
    "B_exact_duplicates": ("Exact duplicates of authentic files", scenario_b_exact_duplicates),
    "C_many_names": ("Many logical names, identical content", scenario_c_many_names),
    "D_chunk_sizes": ("Chunk-level deduplication by chunk size", scenario_d_chunk_sizes),
    "D2_boundary_shift": ("Fixed-size chunking boundary shift", scenario_d2_boundary_shift),
    "E_roundtrip": ("Download and checksum verification", scenario_e_roundtrip),
    "F_shared_deletion": ("Logical deletion with shared content", scenario_f_shared_deletion),
    "G_restore_after_optimize": ("Restoration after optimization", scenario_g_restore_after_optimize),
    "H_replication": ("Replication changes", scenario_h_replication),
    "I_before_after": ("Storage before and after optimization", scenario_i_before_after),
}


def run_scenario(ctx: AppContext, job_id: str, params: dict, reporter) -> dict:
    """Job: run one scenario and store its result in the main metadata database."""
    scenario = params["scenario"]
    title, function = SCENARIOS[scenario]
    with session_scope(ctx.session_factory) as session:
        row = ExperimentRun(scenario=scenario, params=params.get("options"), job_id=job_id)
        session.add(row)
        session.flush()
        run_id = row.id
    reporter.progress(0, 1, f"Running: {title}")
    started = time.perf_counter()
    try:
        result = function(ctx, params.get("options") or {})
    except Exception as exc:
        with session_scope(ctx.session_factory) as session:
            row = session.get(ExperimentRun, run_id)
            row.status, row.error, row.finished_at = "failed", getattr(exc, "message", str(exc)), utcnow()
        raise
    result["duration_s"] = time.perf_counter() - started
    with session_scope(ctx.session_factory) as session:
        row = session.get(ExperimentRun, run_id)
        row.status, row.result, row.finished_at = "succeeded", result, utcnow()
        audit.record(session, "experiment.completed", f"Experiment {scenario} completed in {result['duration_s']:.1f} s.", entity_type="experiment", entity_id=run_id)
    reporter.progress(1, 1, "Done")
    return {"experiment_run_id": run_id, "scenario": scenario}


def rows_to_csv(rows: list[dict]) -> str:
    """Flatten result rows to CSV. Nested values become dotted columns."""
    flat = []
    for row in rows:
        out: dict = {}
        for key, value in row.items():
            if isinstance(value, dict):
                out.update({f"{key}.{k}": v for k, v in value.items()})
            else:
                out[key] = value
        flat.append(out)
    columns: list[str] = []
    for row in flat:
        columns.extend(c for c in row if c not in columns)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns)
    writer.writeheader()
    writer.writerows(flat)
    return buffer.getvalue()


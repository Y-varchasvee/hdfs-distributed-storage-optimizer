"""Health, storage statistics, cluster state, analytics, datasets, experiments, audit and settings."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Body, Depends, Query, Response
from sqlalchemy import func, select, text

from app.api.deps import get_ctx
from app.core.db import session_scope
from app.core.errors import HdfsError, NotFoundError, ValidationFailure
from app.models.entities import (
    AuditEvent,
    Chunk,
    ContentObject,
    ContentState,
    DatasetSource,
    ExperimentRun,
    FileManifest,
)
from app.schemas.api import (
    AuditOut,
    AuditPage,
    DatasetImportRequest,
    DatasetIngestRequest,
    ExperimentRequest,
    JobAccepted,
    ReplicationRequest,
    SettingsUpdate,
)
from app.services import (
    analytics,
    audit,
    datasets,
    experiments,
    lifecycle,
    replication,
    settings_store,
)
from app.services.context import AppContext
from app.services.hashing import sha256_bytes

router = APIRouter(prefix="/api/v1")


# -- health ---------------------------------------------------------------------------------------


@router.get("/health", tags=["health"])
def health(ctx: AppContext = Depends(get_ctx)) -> dict:
    """The API is up. HDFS state is reported separately, so a cluster outage stays visible in the UI."""
    with session_scope(ctx.session_factory) as session:
        session.execute(text("SELECT 1"))
    cluster = ctx.monitor.status()
    return {"status": "ok", "database": "ok", "hdfs_reachable": cluster["reachable"], "hdfs_health": cluster.get("health")}


@router.get("/system/status", tags=["health"])
def system_status(ctx: AppContext = Depends(get_ctx)) -> dict:
    cluster = ctx.monitor.status()
    return {
        "api": "ok",
        "root_path": ctx.paths.root,
        "namenode_url": ctx.settings.namenode_url,
        "cluster": cluster,
    }


@router.get("/system/diagnostics", tags=["health"])
def diagnostics(ctx: AppContext = Depends(get_ctx)) -> dict:
    """Run real checks, including a write, read and delete cycle through a DataNode."""
    checks = []

    def check(name: str, function) -> None:
        started = time.perf_counter()
        try:
            detail = function()
            checks.append({"name": name, "ok": True, "detail": detail, "ms": (time.perf_counter() - started) * 1000})
        except Exception as exc:  # noqa: BLE001 - a diagnostic reports failures as data
            checks.append({"name": name, "ok": False, "detail": getattr(exc, "message", str(exc)), "ms": (time.perf_counter() - started) * 1000})

    def database() -> str:
        with session_scope(ctx.session_factory) as session:
            result = session.execute(text("PRAGMA integrity_check")).scalar_one()
        if result != "ok":
            raise ValidationFailure(result)
        return "SQLite integrity_check returned ok"

    def namenode() -> str:
        status = ctx.monitor.status()
        if not status["reachable"]:
            raise HdfsError(status["error"])
        return f"{status['namenode']['state']}, Hadoop {status['namenode']['software_version']}, {status['datanodes']['live']} live DataNodes"

    def write_cycle() -> str:
        payload = f"diagnostic {uuid.uuid4()}".encode()
        path = ctx.paths.staging_path(f"diagnostic-{uuid.uuid4().hex}")
        ctx.hdfs.create(path, payload, length=len(payload))
        try:
            data = b"".join(ctx.hdfs.open(path))
        finally:
            ctx.hdfs.delete(path)
        if sha256_bytes(data) != sha256_bytes(payload):
            raise HdfsError("Bytes read from HDFS differ from bytes written.")
        return f"Wrote, read back and deleted {len(payload)} bytes through WebHDFS"

    def spool() -> str:
        directory: Path = ctx.settings.spool_dir
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / f".probe-{uuid.uuid4().hex}"
        probe.write_bytes(b"ok")
        probe.unlink()
        return str(directory)

    check("Metadata database", database)
    check("NameNode connection", namenode)
    check("HDFS write, read and delete", write_cycle)
    check("Upload spool directory", spool)
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


# -- storage --------------------------------------------------------------------------------------


@router.get("/storage/statistics", tags=["storage"])
def storage_statistics(ctx: AppContext = Depends(get_ctx)) -> dict:
    with session_scope(ctx.session_factory) as session:
        return analytics.full_statistics(ctx, session)


@router.get("/storage/savings", tags=["storage"])
def storage_savings(ctx: AppContext = Depends(get_ctx)) -> dict:
    with session_scope(ctx.session_factory) as session:
        stats = analytics.storage_statistics(session)
        return {
            "logical_bytes": stats["logical_bytes"],
            "stored_content_bytes": stats["stored_content_bytes"],
            "bytes_avoided": stats["bytes_avoided"],
            "savings_percent": stats["savings_percent"],
            "dedup_ratio": stats["dedup_ratio"],
            "history": analytics.history(session),
        }


@router.get("/storage/objects", tags=["storage"])
def storage_objects(
    kind: str = Query("objects", pattern="^(objects|chunks|manifests)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    ctx: AppContext = Depends(get_ctx),
) -> dict:
    model = {"objects": ContentObject, "chunks": Chunk, "manifests": FileManifest}[kind]
    with session_scope(ctx.session_factory) as session:
        query = select(model).where(model.state == ContentState.ACTIVE)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.scalars(query.order_by(model.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
        items = [
            {
                "id": row.id,
                "sha256": row.sha256 if kind != "manifests" else row.file_sha256,
                "size_bytes": row.size_bytes if kind != "manifests" else row.manifest_bytes,
                "hdfs_path": row.hdfs_path,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/storage/reconcile", tags=["storage"])
def reconcile_report(ctx: AppContext = Depends(get_ctx)) -> dict:
    return lifecycle.reconcile(ctx)


@router.post("/storage/reconcile", tags=["storage"])
def reconcile_apply(ctx: AppContext = Depends(get_ctx)) -> dict:
    return lifecycle.reconcile(ctx, apply=True)


# -- cluster --------------------------------------------------------------------------------------


@router.get("/cluster/status", tags=["cluster"])
def cluster_status(ctx: AppContext = Depends(get_ctx)) -> dict:
    return ctx.monitor.status()


@router.get("/cluster/nodes", tags=["cluster"])
def cluster_nodes(ctx: AppContext = Depends(get_ctx)) -> dict:
    return ctx.monitor.nodes()


@router.get("/cluster/replication", tags=["cluster"])
def cluster_replication(ctx: AppContext = Depends(get_ctx)) -> dict:
    return replication.replication_status(ctx)


@router.post("/cluster/replication", tags=["cluster"], status_code=202)
def change_replication(body: ReplicationRequest, ctx: AppContext = Depends(get_ctx)) -> dict:
    return replication.request_change(ctx, body.factor, acknowledge_reduced_protection=body.acknowledge_reduced_protection)


# -- analytics ------------------------------------------------------------------------------------


@router.get("/analytics/overview", tags=["analytics"])
def analytics_overview(ctx: AppContext = Depends(get_ctx)) -> dict:
    with session_scope(ctx.session_factory) as session:
        return {
            **analytics.full_statistics(ctx, session),
            "distributions": analytics.distributions(session),
            "integrity": analytics.integrity_summary(session),
            "cluster": ctx.monitor.status(),
        }


@router.get("/analytics/history", tags=["analytics"])
def analytics_history(ctx: AppContext = Depends(get_ctx)) -> dict:
    with session_scope(ctx.session_factory) as session:
        return {"snapshots": analytics.history(session), "optimizations": analytics.optimization_history(session)}


@router.get("/analytics/performance", tags=["analytics"])
def analytics_performance(ctx: AppContext = Depends(get_ctx)) -> dict:
    with session_scope(ctx.session_factory) as session:
        return analytics.performance(session)


@router.get("/analytics/report.csv", tags=["analytics"])
def analytics_report(ctx: AppContext = Depends(get_ctx)) -> Response:
    with session_scope(ctx.session_factory) as session:
        stats = analytics.storage_statistics(session)
        perf = analytics.performance(session)
    rows = [{"section": "storage", "metric": k, "value": v} for k, v in stats.items() if not isinstance(v, dict)]
    for op in perf["operations"]:
        for key in ("samples", "bytes", "total_ms", "mean_ms", "throughput_mib_s"):
            rows.append({"section": f"performance.{op['operation']}.{op['mode'] or 'all'}", "metric": key, "value": op[key]})
    rows.extend({"section": "integrity", "metric": k, "value": v} for k, v in perf["integrity"].items())
    return Response(
        experiments.rows_to_csv(rows),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="hdfs-optimizer-report.csv"'},
    )


# -- datasets -------------------------------------------------------------------------------------


@router.get("/datasets", tags=["datasets"])
def list_datasets(ctx: AppContext = Depends(get_ctx)) -> dict:
    with session_scope(ctx.session_factory) as session:
        datasets.sync_provenance(ctx, session)
        rows = list(session.scalars(select(DatasetSource).order_by(DatasetSource.kind, DatasetSource.size_bytes)))
        items = [datasets.source_dict(r, local_present=(ctx.settings.dataset_dir / r.local_path).exists()) for r in rows]
    return {
        "items": items,
        "catalog": [
            {
                "ebook_id": entry.ebook_id,
                "title": entry.title,
                "author": entry.author,
                "formats": entry.formats,
                "source_url": datasets.source_page(entry.ebook_id),
            }
            for entry in datasets.CATALOG
        ],
        "transformations": datasets.TRANSFORMATIONS,
    }


@router.post("/datasets/import", tags=["datasets"], response_model=JobAccepted, status_code=202)
def import_dataset(body: DatasetImportRequest = Body(default=DatasetImportRequest()), ctx: AppContext = Depends(get_ctx)) -> JobAccepted:
    return JobAccepted(job_id=ctx.jobs.submit("dataset_import", params={"ebook_ids": body.ebook_ids}))


@router.post("/datasets/ingest", tags=["datasets"], response_model=JobAccepted, status_code=202)
def ingest_dataset(body: DatasetIngestRequest, ctx: AppContext = Depends(get_ctx)) -> JobAccepted:
    if not body.source_ids:
        raise ValidationFailure("Select at least one dataset file.")
    return JobAccepted(
        job_id=ctx.jobs.submit(
            "dataset_ingest",
            mode=body.mode,
            chunk_size=body.chunk_size,
            params={"source_ids": body.source_ids, "copies": body.copies, "folder": body.folder},
        )
    )


@router.get("/datasets/provenance", tags=["datasets"])
def provenance(ctx: AppContext = Depends(get_ctx)) -> dict:
    return datasets._read_manifest(ctx.settings.provenance_path)


# -- experiments ----------------------------------------------------------------------------------


@router.get("/experiments", tags=["experiments"])
def list_experiments(ctx: AppContext = Depends(get_ctx)) -> dict:
    with session_scope(ctx.session_factory) as session:
        runs = session.scalars(select(ExperimentRun).order_by(ExperimentRun.started_at.desc()).limit(50))
        items = [
            {
                "id": r.id,
                "scenario": r.scenario,
                "status": r.status,
                "result": r.result,
                "error": r.error,
                "job_id": r.job_id,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
            }
            for r in runs
        ]
    return {
        "scenarios": [{"id": key, "title": value[0], "description": value[1].__doc__} for key, value in experiments.SCENARIOS.items()],
        "runs": items,
    }


@router.post("/experiments/run", tags=["experiments"], response_model=JobAccepted, status_code=202)
def run_experiment(body: ExperimentRequest, ctx: AppContext = Depends(get_ctx)) -> JobAccepted:
    if body.scenario not in experiments.SCENARIOS:
        raise ValidationFailure(f"Unknown scenario: {body.scenario}")
    return JobAccepted(job_id=ctx.jobs.submit("experiment", params={"scenario": body.scenario, "options": body.options}))


@router.get("/experiments/{run_id}/export.csv", tags=["experiments"])
def export_experiment(run_id: str, ctx: AppContext = Depends(get_ctx)) -> Response:
    with session_scope(ctx.session_factory) as session:
        run = session.get(ExperimentRun, run_id)
        if run is None or not run.result:
            raise NotFoundError(f"No completed experiment run {run_id}.")
        csv_text = experiments.rows_to_csv(run.result.get("rows", []))
        scenario = run.scenario
    return Response(
        csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{scenario}-{run_id[:8]}.csv"'},
    )


# -- audit ----------------------------------------------------------------------------------------


@router.get("/audit/events", tags=["audit"], response_model=AuditPage)
def audit_events(
    event_type: str | None = Query(None, description="Exact type, or a prefix such as 'file.'"),
    severity: str | None = Query(None, pattern="^(info|warning|error)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    ctx: AppContext = Depends(get_ctx),
) -> AuditPage:
    with session_scope(ctx.session_factory) as session:
        query = select(AuditEvent)
        if event_type:
            prefix = event_type.replace("%", "").replace("_", r"\_")
            query = query.where(AuditEvent.event_type.like(f"{prefix}%", escape="\\"))
        if severity:
            query = query.where(AuditEvent.severity == severity)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        rows = session.scalars(query.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).offset((page - 1) * page_size).limit(page_size))
        return AuditPage(items=[AuditOut.model_validate(r) for r in rows], total=total, page=page, page_size=page_size)


# -- settings -------------------------------------------------------------------------------------


@router.get("/settings", tags=["settings"])
def get_settings_view(ctx: AppContext = Depends(get_ctx)) -> dict:
    with session_scope(ctx.session_factory) as session:
        values = settings_store.get_all(ctx, session)
    return {
        "values": values,
        "connection": {
            "namenode_url": ctx.settings.namenode_url,
            "hdfs_user": ctx.settings.hdfs_user,
            "root_path": ctx.paths.root,
            "datanode_host_map": ctx.settings.datanode_map,
            "source": "Read-only here. Set with HDFSOPT_* environment variables and restart the backend.",
        },
        "limits": {
            "min_chunk_size": ctx.settings.min_chunk_size,
            "max_chunk_size": ctx.settings.max_chunk_size,
            "max_upload_bytes": ctx.settings.max_upload_bytes,
        },
        "storage": {
            "database_path": str(ctx.settings.database_path),
            "database_bytes": ctx.settings.database_path.stat().st_size if ctx.settings.database_path.exists() else None,
        },
    }


@router.put("/settings", tags=["settings"])
def update_settings(body: SettingsUpdate, ctx: AppContext = Depends(get_ctx)) -> dict:
    changes = body.model_dump(exclude_none=True)
    with session_scope(ctx.session_factory) as session:
        values = settings_store.update(ctx, session, changes)
        audit.record(session, "settings.changed", f"Settings changed: {', '.join(sorted(changes)) or 'nothing'}.", details=changes)
    return {"values": values}


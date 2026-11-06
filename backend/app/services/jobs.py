"""Background job runner. Jobs run one at a time and persist their state in the database."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app.core.db import session_scope, utcnow
from app.core.errors import AppError
from app.models.entities import DeduplicationJob, JobStatus, new_id
from app.services import audit
from app.services.context import AppContext

log = logging.getLogger("hdfs_optimizer.jobs")

JobHandler = Callable[[AppContext, str, dict, "JobReporter"], dict]


class JobReporter:
    """Writes progress to the database so the API can report what is really happening."""

    def __init__(self, ctx: AppContext, job_id: str):
        self.ctx = ctx
        self.job_id = job_id

    def progress(self, done: int, total: int, message: str | None = None) -> None:
        with session_scope(self.ctx.session_factory) as session:
            job = session.get(DeduplicationJob, self.job_id)
            job.progress_done = done
            job.progress_total = total
            job.heartbeat_at = utcnow()
            if message:
                job.message = message


class JobManager:
    def __init__(self, ctx: AppContext, handlers: dict[str, JobHandler], *, synchronous: bool = False):
        self.ctx = ctx
        self.handlers = handlers
        self.synchronous = synchronous  # tests run jobs inline for determinism
        self.executor = None if synchronous else ThreadPoolExecutor(max_workers=1, thread_name_prefix="job")

    def submit(
        self,
        kind: str,
        *,
        mode: str | None = None,
        chunk_size: int | None = None,
        params: dict | None = None,
        resumed_from_id: str | None = None,
    ) -> str:
        if kind not in self.handlers:
            raise AppError(f"Unknown job kind: {kind}")
        job_id = new_id()
        merged = {**(params or {}), "mode": mode, "chunk_size": chunk_size}
        with session_scope(self.ctx.session_factory) as session:
            session.add(
                DeduplicationJob(
                    id=job_id,
                    kind=kind,
                    mode=mode,
                    chunk_size=chunk_size,
                    params=merged,
                    resumed_from_id=resumed_from_id,
                )
            )
        if self.synchronous:
            self._run(job_id, kind, merged)
        else:
            self.executor.submit(self._run, job_id, kind, merged)
        return job_id

    def _run(self, job_id: str, kind: str, params: dict) -> None:
        with session_scope(self.ctx.session_factory) as session:
            job = session.get(DeduplicationJob, job_id)
            job.status = JobStatus.RUNNING
            job.started_at = job.heartbeat_at = utcnow()
        try:
            result = self.handlers[kind](self.ctx, job_id, params, JobReporter(self.ctx, job_id))
            status = JobStatus.PARTIAL if result.get("errors") else JobStatus.SUCCEEDED
            error = None
        except Exception as exc:  # noqa: BLE001 - any failure becomes a visible job state
            log.exception("job %s failed", job_id)
            result, status = None, JobStatus.FAILED
            error = getattr(exc, "message", None) or f"{type(exc).__name__}: {exc}"
            audit.record_failure(
                self.ctx.session_factory, f"job.{kind}_failed", error, entity_type="job", entity_id=job_id
            )
        with session_scope(self.ctx.session_factory) as session:
            job = session.get(DeduplicationJob, job_id)
            job.status = status
            job.result = _json_safe(result)
            job.error = error
            job.finished_at = utcnow()
            if status == JobStatus.SUCCEEDED:
                job.message = "Completed"
            elif status == JobStatus.PARTIAL:
                job.message = "Completed with errors"
            else:
                job.message = error

    def shutdown(self) -> None:
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)


def _json_safe(value):
    """Job results hold plain data; convert any datetime values that metrics may contain."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value

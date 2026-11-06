"""Application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import dedup, files, system
from app.api.deps import require_token
from app.core.config import BACKEND_DIR, Settings, get_settings
from app.core.db import make_engine, make_session_factory
from app.core.errors import install_error_handlers
from app.hdfs.webhdfs import WebHdfsClient
from app.services import (
    datasets,
    experiments,
    integrity,
    lifecycle,
    optimizer,
    replication,
)
from app.services.context import AppContext, StoragePaths
from app.services.jobs import JobManager
from app.services.monitor import ClusterMonitor

log = logging.getLogger("hdfs_optimizer")

JOB_HANDLERS = {
    "analyze": optimizer.run_analysis,
    "optimize": optimizer.run_optimization,
    "replication": replication.run_replication_change,
    "verify_all": integrity.run_verify_all,
    "dataset_import": datasets.run_import,
    "dataset_ingest": datasets.run_ingest,
    "experiment": experiments.run_scenario,
}


def run_migrations(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")


def build_context(settings: Settings) -> AppContext:
    run_migrations(Path(settings.database_path))
    engine = make_engine(settings.database_path)
    hdfs = WebHdfsClient(
        settings.namenode_url,
        user=settings.hdfs_user,
        datanode_map=settings.datanode_map,
        timeout_seconds=settings.http_timeout_seconds,
        connect_timeout_seconds=settings.connect_timeout_seconds,
    )
    ctx = AppContext(
        settings=settings,
        session_factory=make_session_factory(engine),
        hdfs=hdfs,
        paths=StoragePaths(root=settings.root_path),
        monitor=ClusterMonitor(settings.namenode_url, user=settings.hdfs_user),
    )
    ctx.jobs = JobManager(ctx, JOB_HANDLERS)
    return ctx


def create_app(context: AppContext | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ctx = context or build_context(get_settings())
        app.state.ctx = ctx
        summary = lifecycle.recover_on_startup(ctx)
        log.info("startup recovery: %s", summary)
        yield
        if ctx.jobs:
            ctx.jobs.shutdown()

    app = FastAPI(
        title="HDFS Optimizer API",
        version="1.0.0",
        description="Application-managed deduplication and storage optimization on Apache Hadoop HDFS.",
        lifespan=lifespan,
        dependencies=[Depends(require_token)],
    )
    settings = context.settings if context else get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-API-Key"],
        expose_headers=["X-Content-SHA256", "Content-Disposition"],
    )
    install_error_handlers(app)
    app.include_router(files.router)
    app.include_router(dedup.router)
    app.include_router(system.router)
    return app


app = create_app()

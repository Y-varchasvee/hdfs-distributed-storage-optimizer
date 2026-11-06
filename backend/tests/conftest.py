from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.core.config import Settings  # noqa: E402
from app.core.db import Base, make_engine, make_session_factory  # noqa: E402
from app.main import JOB_HANDLERS, create_app  # noqa: E402
from app.services.context import AppContext, StoragePaths  # noqa: E402
from app.services.jobs import JobManager  # noqa: E402
from support.local_fs_adapter import FakeMonitor, LocalFsTestAdapter  # noqa: E402

KIB = 1024


def make_context(tmp_path: Path) -> AppContext:
    settings = Settings(
        namenode_url="http://test.invalid",
        database_path=tmp_path / "metadata.db",
        spool_dir=tmp_path / "spool",
        dataset_dir=tmp_path / "datasets",
        provenance_path=tmp_path / "datasets" / "manifest.json",
        default_chunk_size=4 * KIB,
        min_chunk_size=KIB,
        _env_file=None,
    )
    engine = make_engine(settings.database_path)
    Base.metadata.create_all(engine)
    hdfs = LocalFsTestAdapter(tmp_path / "fake-hdfs")
    ctx = AppContext(
        settings=settings,
        session_factory=make_session_factory(engine),
        hdfs=hdfs,
        paths=StoragePaths(root="/hdfs-optimizer"),
        monitor=FakeMonitor(hdfs),
    )
    ctx.ensure_namespace()
    ctx.jobs = JobManager(ctx, JOB_HANDLERS, synchronous=True)
    return ctx


@pytest.fixture
def ctx(tmp_path: Path) -> AppContext:
    return make_context(tmp_path)


@pytest.fixture
def client(ctx: AppContext):
    with TestClient(create_app(ctx)) as test_client:
        yield test_client


@pytest.fixture
def write_file(tmp_path: Path):
    """Write bytes to a spool file. Test bytes are deterministic and exist only to exercise the logic."""
    directory = tmp_path / "input"
    directory.mkdir(exist_ok=True)
    counter = {"n": 0}

    def _write(data: bytes) -> Path:
        counter["n"] += 1
        path = directory / f"input-{counter['n']}.bin"
        path.write_bytes(data)
        return path

    return _write


def pattern(seed: int, size: int) -> bytes:
    """Deterministic, non-repeating test bytes for unit tests. Never used as an evaluation dataset."""
    import hashlib

    out = bytearray()
    counter = 0
    while len(out) < size:
        out += hashlib.sha256(f"{seed}:{counter}".encode()).digest()
        counter += 1
    return bytes(out[:size])

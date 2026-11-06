"""Integration tests against the REAL HDFS cluster, using authentic Project Gutenberg files.

Run with:  pytest -m hdfs
Each test uses a private directory under /hdfs-optimizer-tests and removes it afterwards.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path

import httpx
import pytest
from app.core.config import PROJECT_DIR, Settings
from app.core.db import Base, make_engine, make_session_factory
from app.core.errors import HdfsFileNotFound
from app.hdfs.webhdfs import WebHdfsClient
from app.main import JOB_HANDLERS
from app.models.entities import DeduplicationJob as JOB_MODEL
from app.models.entities import ReplicationOperation as OPERATION_MODEL
from app.services import integrity, lifecycle, replication
from app.services.context import AppContext, StoragePaths
from app.services.ingest import ingest_local_file
from app.services.jobs import JobManager
from app.services.monitor import ClusterMonitor

pytestmark = pytest.mark.hdfs

NAMENODE = Settings(_env_file=None).namenode_url
ROOT = "/hdfs-optimizer-tests"
MANIFEST = PROJECT_DIR / "datasets" / "provenance" / "manifest.json"


def _cluster_up() -> bool:
    try:
        return httpx.get(f"{NAMENODE}/jmx?qry=Hadoop:service=NameNode,name=NameNodeStatus", timeout=3).is_success
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="module", autouse=True)
def require_cluster():
    if not _cluster_up():
        pytest.skip(f"No HDFS cluster at {NAMENODE}. Start it with: docker compose up -d --wait")


@pytest.fixture
def real_ctx(tmp_path: Path):
    settings = Settings(
        _env_file=None,
        database_path=tmp_path / "metadata.db",
        spool_dir=tmp_path / "spool",
        dataset_dir=PROJECT_DIR / "datasets" / "raw",
        provenance_path=MANIFEST,
    )
    engine = make_engine(settings.database_path)
    Base.metadata.create_all(engine)
    hdfs = WebHdfsClient(settings.namenode_url, datanode_map=settings.datanode_map)
    run_root = f"{ROOT}/{uuid.uuid4().hex}"
    ctx = AppContext(
        settings=settings,
        session_factory=make_session_factory(engine),
        hdfs=hdfs,
        paths=StoragePaths(root=run_root),
        monitor=ClusterMonitor(settings.namenode_url),
    )
    ctx.jobs = JobManager(ctx, JOB_HANDLERS, synchronous=True)
    ctx.ensure_namespace()
    yield ctx
    hdfs.delete(run_root, recursive=True)
    hdfs.close()
    engine.dispose()


def _source(ebook_id: int = 11, file_format: str = "txt") -> dict:
    if not MANIFEST.exists():
        pytest.skip("Dataset not downloaded. Run scripts/download_dataset.py")
    manifest = json.loads(MANIFEST.read_text())
    for record in manifest["files"]:
        if record["kind"] == "original" and record["ebook_id"] == ebook_id and record["file_format"] == file_format:
            path = PROJECT_DIR / "datasets" / "raw" / record["local_path"]
            if path.exists():
                return {**record, "path": path}
    pytest.skip(f"Authentic file for ebook {ebook_id} is not present.")


def test_authentic_file_matches_recorded_provenance():
    source = _source(1342)
    assert hashlib.sha256(source["path"].read_bytes()).hexdigest() == source["sha256"]
    assert source["source_url"] == "https://www.gutenberg.org/ebooks/1342"
    assert source["header_title_in_file"] == "Pride and Prejudice"


def test_webhdfs_primitives_on_the_real_cluster(real_ctx):
    client, base = real_ctx.hdfs, real_ctx.paths.staging
    path = f"{base}/probe with space.bin"
    client.create(path, b"hello hdfs", length=10)
    status = client.status(path)
    assert status.length == 10 and status.replication >= 1
    assert b"".join(client.open(path)) == b"hello hdfs"
    # A real HDFS rename refuses to replace an existing file; the staged-write protocol depends on this.
    client.create(f"{base}/other", b"x", length=1)
    assert client.rename(path, f"{base}/other") is False
    assert client.rename(path, f"{base}/renamed") is True
    assert client.status(path) is None
    assert client.delete(f"{base}/renamed") is True
    with pytest.raises(HdfsFileNotFound):
        list(client.open(f"{base}/renamed"))


def test_empty_file_can_be_stored_on_the_real_cluster(real_ctx, tmp_path):
    empty = tmp_path / "empty.txt"
    empty.write_bytes(b"")
    for mode in ("raw", "file", "chunk"):
        result = ingest_local_file(real_ctx, empty, f"empty-{mode}", mode=mode)
        assert b"".join(integrity.stream_verified(real_ctx, result.file.id)) == b""


@pytest.mark.parametrize("mode", ["raw", "file", "chunk"])
def test_authentic_file_round_trips_byte_for_byte(real_ctx, tmp_path, mode):
    source = _source()
    result = ingest_local_file(real_ctx, source["path"], source["path"].name, mode=mode, chunk_size=64 * 1024)
    target = tmp_path / "restored"
    digest = integrity.restore_to_path(real_ctx, result.file.id, target)
    assert digest == source["sha256"]
    assert target.read_bytes() == source["path"].read_bytes()
    assert integrity.verify_file(real_ctx, result.file.id).ok


def test_binary_authentic_file_round_trips_through_chunks(real_ctx, tmp_path):
    source = _source(11, "epub")
    result = ingest_local_file(real_ctx, source["path"], source["path"].name, mode="chunk", chunk_size=64 * 1024)
    target = tmp_path / "restored.epub"
    assert integrity.restore_to_path(real_ctx, result.file.id, target) == source["sha256"]


def test_exact_duplicate_consumes_no_additional_hdfs_space(real_ctx):
    source = _source()
    first = ingest_local_file(real_ctx, source["path"], "original.txt", mode="file")
    before = real_ctx.hdfs.content_summary(real_ctx.paths.root)
    second = ingest_local_file(real_ctx, source["path"], "workload-copy.txt", mode="file", provenance_label="workload_copy")
    after = real_ctx.hdfs.content_summary(real_ctx.paths.root)
    assert second.outcome == "duplicate_reference"
    assert after.length == before.length
    assert after.space_consumed == before.space_consumed
    assert first.file.id != second.file.id


def test_hdfs_replicates_stored_objects(real_ctx):
    source = _source()
    result = ingest_local_file(real_ctx, source["path"], source["path"].name, mode="file")
    path = real_ctx.paths.object_path(result.file.sha256)
    expected = real_ctx.hdfs.default_replication()
    assert real_ctx.hdfs.status(path).replication == expected
    # A write returns once the minimum replication is met. The NameNode learns of the remaining replicas
    # through asynchronous block reports, so the full set appears shortly afterwards.
    deadline = time.monotonic() + 20
    blocks = real_ctx.hdfs.block_locations(path)
    while len(blocks[0].hosts) < expected and time.monotonic() < deadline:
        time.sleep(0.5)
        blocks = real_ctx.hdfs.block_locations(path)
    assert len(blocks) == 1
    assert len(blocks[0].hosts) == expected
    assert len(set(blocks[0].hosts)) == expected  # replicas are on distinct DataNodes


def test_measured_space_includes_replication(real_ctx):
    source = _source()
    ingest_local_file(real_ctx, source["path"], source["path"].name, mode="file")
    summary = real_ctx.hdfs.content_summary(real_ctx.paths.objects)
    assert summary.length == source["size_bytes"]
    assert summary.space_consumed == source["size_bytes"] * real_ctx.hdfs.default_replication()


def test_optimization_reduces_hdfs_measured_space_and_preserves_bytes(real_ctx, tmp_path):
    source = _source()
    ids = [
        ingest_local_file(real_ctx, source["path"], f"copy-{i}.txt", mode="raw", provenance_label="workload_copy").file.id
        for i in range(3)
    ]
    before = real_ctx.hdfs.content_summary(real_ctx.paths.root)
    assert before.length == source["size_bytes"] * 3

    job_id = real_ctx.jobs.submit("optimize", mode="file")
    with real_ctx.session_factory() as session:
        job = session.get(JOB_MODEL, job_id)
        assert job.status == "succeeded", job.error

    after = real_ctx.hdfs.content_summary(real_ctx.paths.root)
    assert after.length == source["size_bytes"]
    assert after.space_consumed == before.space_consumed / 3
    for file_id in ids:
        target = tmp_path / f"{file_id}.txt"
        assert integrity.restore_to_path(real_ctx, file_id, target) == source["sha256"]


def test_chunk_optimization_on_real_hdfs(real_ctx, tmp_path):
    source = _source()
    ids = [ingest_local_file(real_ctx, source["path"], f"c{i}.txt", mode="file").file.id for i in range(2)]
    real_ctx.jobs.submit("optimize", mode="chunk", chunk_size=64 * 1024)
    assert real_ctx.hdfs.content_summary(real_ctx.paths.objects).file_count == 0
    expected_chunks = -(-source["size_bytes"] // (64 * 1024))
    assert real_ctx.hdfs.content_summary(real_ctx.paths.chunks).file_count == expected_chunks
    for file_id in ids:
        target = tmp_path / f"{file_id}.txt"
        assert integrity.restore_to_path(real_ctx, file_id, target) == source["sha256"]


def test_deleting_shared_reference_on_real_hdfs(real_ctx):
    source = _source()
    first = ingest_local_file(real_ctx, source["path"], "a.txt", mode="chunk", chunk_size=64 * 1024)
    second = ingest_local_file(real_ctx, source["path"], "b.txt", mode="chunk", chunk_size=64 * 1024)
    lifecycle.soft_delete(real_ctx, first.file.id)
    lifecycle.purge(real_ctx, first.file.id)
    assert integrity.verify_file(real_ctx, second.file.id).ok
    lifecycle.soft_delete(real_ctx, second.file.id)
    lifecycle.purge(real_ctx, second.file.id)
    assert real_ctx.hdfs.content_summary(real_ctx.paths.root).file_count == 0


def test_cluster_monitor_reads_real_namenode(real_ctx):
    status = real_ctx.monitor.status()
    assert status["reachable"] is True
    assert status["namenode"]["state"] == "active"
    assert status["namenode"]["software_version"].startswith("3.")
    assert status["datanodes"]["live"] >= 1
    nodes = real_ctx.monitor.nodes()["nodes"]
    assert len([n for n in nodes if n["state"] == "live"]) == status["datanodes"]["live"]
    assert all(n["capacity_bytes"] > 0 for n in nodes if n["state"] == "live")


def test_fsck_servlet_is_parsed(real_ctx):
    source = _source()
    ingest_local_file(real_ctx, source["path"], source["path"].name, mode="file")
    fsck = real_ctx.monitor.fsck(real_ctx.paths.root)
    assert fsck["status"] == "HEALTHY"
    assert fsck["total_blocks"] >= 1
    assert fsck["missing_blocks"] == 0


def test_replication_change_converges_on_real_cluster(real_ctx):
    live = real_ctx.monitor.status()["datanodes"]["live"]
    if live < 2:
        pytest.skip("Needs at least 2 live DataNodes.")
    source = _source()
    result = ingest_local_file(real_ctx, source["path"], source["path"].name, mode="file")
    path = real_ctx.paths.object_path(result.file.sha256)

    change = replication.request_change(real_ctx, 2, acknowledge_reduced_protection=True)
    assert real_ctx.hdfs.status(path).replication == 2
    summary = real_ctx.hdfs.content_summary(real_ctx.paths.objects)
    assert summary.space_consumed == source["size_bytes"] * 2
    with real_ctx.session_factory() as session:
        operation = session.get(OPERATION_MODEL, change["operation_id"])
        assert operation.status == "verified"
    assert len(real_ctx.hdfs.block_locations(path)[0].hosts) == 2


def test_replication_beyond_live_datanodes_is_refused_on_real_cluster(real_ctx):
    from app.core.errors import ValidationFailure

    live = real_ctx.monitor.status()["datanodes"]["live"]
    with pytest.raises(ValidationFailure):
        replication.request_change(real_ctx, live + 1)


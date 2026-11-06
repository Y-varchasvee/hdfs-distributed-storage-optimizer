"""REST API behaviour through the real FastAPI application."""

import hashlib

import httpx
import pytest
from app.core.errors import HdfsFileNotFound, HdfsUnavailable
from app.hdfs.webhdfs import WebHdfsClient
from app.main import create_app, run_migrations
from app.services.monitor import ClusterMonitor, parse_fsck
from conftest import make_context, pattern
from fastapi.testclient import TestClient


def upload(client, data: bytes, name="a.txt", **form):
    return client.post("/api/v1/files/upload", files={"file": (name, data)}, data=form)


def test_health_reports_api_and_cluster_separately(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok" and body["hdfs_reachable"] is True


def test_openapi_documents_the_api(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in ("/api/v1/files/upload", "/api/v1/dedup/analyze", "/api/v1/cluster/replication", "/api/v1/audit/events"):
        assert path in paths


def test_upload_download_round_trip(client):
    data = pattern(1, 300_000)
    response = upload(client, data, "book.txt", mode="file")
    assert response.status_code == 201
    body = response.json()
    assert body["file"]["sha256"] == hashlib.sha256(data).hexdigest()
    download = client.get(f"/api/v1/files/{body['file']['id']}/download")
    assert download.status_code == 200
    assert download.content == data
    assert download.headers["x-content-sha256"] == body["file"]["sha256"]
    assert "book.txt" in download.headers["content-disposition"]


@pytest.mark.parametrize("mode", ["raw", "file", "chunk"])
def test_round_trip_in_every_mode(client, mode):
    data = pattern(2, 50_000)
    file_id = upload(client, data, mode=mode).json()["file"]["id"]
    assert client.get(f"/api/v1/files/{file_id}/download").content == data
    verified = client.post(f"/api/v1/files/{file_id}/verify").json()
    assert verified["ok"] is True


def test_duplicate_upload_is_reported(client):
    data = pattern(3, 1000)
    upload(client, data, "a.txt", mode="file")
    body = upload(client, data, "b.txt", mode="file").json()
    assert body["outcome"] == "duplicate_reference" and body["duplicate_of_existing"] is True
    assert body["file"]["logical_references"] == 2


def test_list_search_sort_filter_paginate(client):
    for index in range(5):
        upload(client, pattern(10 + index, 100 * (index + 1)), f"file{index}.txt", mode="file", folder="/reports")
    upload(client, pattern(99, 50), "other.log", mode="raw", folder="/logs")

    assert client.get("/api/v1/files").json()["total"] == 6
    page = client.get("/api/v1/files", params={"page_size": 2, "page": 2, "sort": "size", "order": "asc"}).json()
    assert [item["size_bytes"] for item in page["items"]] == [200, 300]
    assert client.get("/api/v1/files", params={"folder": "/logs"}).json()["total"] == 1
    assert client.get("/api/v1/files", params={"q": "file3"}).json()["total"] == 1
    assert client.get("/api/v1/files", params={"mode": "raw"}).json()["total"] == 1
    assert client.get("/api/v1/files", params={"extension": "log"}).json()["total"] == 1
    folders = client.get("/api/v1/files/folders").json()["folders"]
    assert {f["path"] for f in folders} == {"/reports", "/logs"}


def test_search_by_hash_prefix(client):
    data = pattern(20, 100)
    upload(client, data, mode="file")
    prefix = hashlib.sha256(data).hexdigest()[:12]
    assert client.get("/api/v1/files", params={"q": prefix}).json()["total"] == 1


def test_file_detail_shows_references_and_chunks(client):
    data = pattern(21, 20_000)
    first = upload(client, data, "a.bin", mode="chunk").json()["file"]["id"]
    upload(client, data, "b.bin", mode="chunk")
    detail = client.get(f"/api/v1/files/{first}").json()
    assert detail["logical_references"] == 2
    assert detail["same_content_files"][0]["name"] == "b.bin"
    assert detail["chunk_count"] == 5 and len(detail["chunks"]) == 5
    assert detail["chunk_size"] == 4096


def test_delete_restore_and_purge_flow(client):
    file_id = upload(client, pattern(22, 100), mode="file").json()["file"]["id"]
    assert client.post(f"/api/v1/files/{file_id}/restore").status_code == 409
    assert client.delete(f"/api/v1/files/{file_id}", params={"permanent": True}).status_code == 409
    assert client.delete(f"/api/v1/files/{file_id}").json()["recoverable"] is True
    assert client.get("/api/v1/files").json()["total"] == 0
    assert client.get("/api/v1/files", params={"status": "deleted"}).json()["total"] == 1
    assert client.post(f"/api/v1/files/{file_id}/restore").json()["status"] == "active"
    client.delete(f"/api/v1/files/{file_id}")
    purged = client.delete(f"/api/v1/files/{file_id}", params={"permanent": True}).json()
    assert purged["content_removed"]["object_count"] == 1
    assert client.get(f"/api/v1/files/{file_id}").status_code == 404


def test_duplicate_groups_and_reclaimable_estimate(client):
    data = pattern(23, 1000)
    upload(client, data, "a", mode="raw")
    upload(client, data, "b", mode="raw")
    upload(client, data, "c", mode="raw")
    upload(client, pattern(24, 500), "unique", mode="raw")
    body = client.get("/api/v1/dedup/groups").json()
    assert body["group_count"] == 1 and body["duplicate_files"] == 2
    group = body["groups"][0]
    assert group["copies"] == 3 and group["reclaimable_bytes"] == 2000
    assert group["already_deduplicated"] is False


def test_groups_show_nothing_reclaimable_once_deduplicated(client):
    data = pattern(25, 1000)
    upload(client, data, "a", mode="file")
    upload(client, data, "b", mode="file")
    group = client.get("/api/v1/dedup/groups").json()["groups"][0]
    assert group["reclaimable_bytes"] == 0 and group["already_deduplicated"] is True


def test_shared_chunks_endpoint(client, ctx):
    size = ctx.settings.default_chunk_size
    shared = pattern(26, size * 2)
    upload(client, shared + pattern(27, size), "a", mode="chunk")
    upload(client, shared + pattern(28, size), "b", mode="chunk")
    body = client.get("/api/v1/dedup/shared-chunks").json()
    assert body["shared_chunk_count"] == 2
    assert body["bytes_saved_by_sharing"] == size * 2


def test_analyze_optimize_flow_over_http(client):
    data = pattern(29, 8000)
    ids = [upload(client, data, f"{i}", mode="raw").json()["file"]["id"] for i in range(3)]
    assert client.post("/api/v1/dedup/optimize", json={"analysis_job_id": "missing"}).status_code == 404

    analysis = client.post("/api/v1/dedup/analyze", json={"mode": "file"})
    assert analysis.status_code == 202
    analysis_id = analysis.json()["job_id"]
    preview = client.get(f"/api/v1/dedup/jobs/{analysis_id}").json()
    assert preview["result"]["estimated"] is True

    optimize = client.post("/api/v1/dedup/optimize", json={"analysis_job_id": analysis_id})
    assert optimize.status_code == 202
    finished = client.get(f"/api/v1/dedup/jobs/{optimize.json()['job_id']}").json()
    assert finished["status"] == "succeeded" and finished["result"]["estimated"] is False
    assert finished["result"]["after"]["derived"]["stored_content_bytes"] == 8000
    for file_id in ids:
        assert client.get(f"/api/v1/files/{file_id}/download").content == data

    # The preview no longer describes the catalog, so it cannot be used again.
    assert client.post("/api/v1/dedup/optimize", json={"analysis_job_id": analysis_id}).status_code == 409


def test_invalid_inputs_are_rejected(client):
    assert upload(client, b"x", mode="nonsense").status_code == 422
    assert upload(client, b"x", mode="chunk", chunk_size=1).status_code == 422
    assert upload(client, b"x", folder="/a/../b").status_code == 422
    assert client.post("/api/v1/dedup/analyze", json={"mode": "raw"}).status_code == 422
    assert client.get("/api/v1/files", params={"sort": "evil"}).status_code == 422
    assert client.get("/api/v1/files", params={"page": 0}).status_code == 422
    assert client.post("/api/v1/cluster/replication", json={"factor": 0}).status_code == 422
    assert client.post("/api/v1/cluster/replication", json={"factor": 9}).status_code == 422
    assert client.post("/api/v1/experiments/run", json={"scenario": "nope"}).status_code == 422


def test_missing_file_returns_404_in_the_error_format(client):
    response = client.get("/api/v1/files/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_upload_limit_is_enforced(ctx):
    ctx.settings.max_upload_bytes = 1000
    with TestClient(create_app(ctx)) as limited:
        response = upload(limited, pattern(30, 5000), mode="file")
        assert response.status_code == 413
        assert limited.get("/api/v1/files").json()["total"] == 0
    assert list(ctx.settings.spool_dir.iterdir()) == []


def test_token_protects_only_mutating_requests(ctx):
    ctx.settings.api_token = "unit-test-token"
    with TestClient(create_app(ctx)) as guarded:
        assert guarded.get("/api/v1/files").status_code == 200
        assert upload(guarded, b"x", mode="file").status_code == 401
        allowed = guarded.post(
            "/api/v1/files/upload", files={"file": ("a", b"x")}, data={"mode": "file"}, headers={"X-API-Key": "unit-test-token"}
        )
        assert allowed.status_code == 201


def test_cors_allows_only_configured_origins(client):
    allowed = client.get("/api/v1/health", headers={"Origin": "http://localhost:3100"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3100"
    denied = client.get("/api/v1/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in denied.headers


def test_analytics_endpoints_use_backend_data(client):
    data = pattern(31, 1000)
    upload(client, data, "a.txt", mode="file")
    upload(client, data, "b.txt", mode="file")
    overview = client.get("/api/v1/analytics/overview").json()
    assert overview["derived"]["savings_percent"] == 50.0
    assert overview["distributions"]["file_types"][0]["extension"] == "txt"
    assert overview["distributions"]["duplicate_distribution"] == [{"copies": 2, "groups": 1}]
    assert len(client.get("/api/v1/analytics/history").json()["snapshots"]) == 2
    operations = client.get("/api/v1/analytics/performance").json()["operations"]
    assert {o["operation"] for o in operations} >= {"hash", "upload"}
    report = client.get("/api/v1/analytics/report.csv")
    assert report.headers["content-type"].startswith("text/csv") and "savings_percent" in report.text


def test_hash_timing_is_a_real_measurement(client):
    upload(client, pattern(40, 2_000_000), "a.bin", mode="file")
    hash_ops = [o for o in client.get("/api/v1/analytics/performance").json()["operations"] if o["operation"] == "hash"]
    assert len(hash_ops) == 1
    # SHA-256 in software cannot approach this rate. A pre-supplied hash once reported millions of MiB/s.
    assert 0 < hash_ops[0]["throughput_mib_s"] < 50_000


def test_precomputed_hash_without_a_time_records_no_sample(ctx, write_file):
    from app.services import analytics
    from app.services.hashing import sha256_file
    from app.services.ingest import ingest_local_file

    path = write_file(pattern(41, 1000))
    ingest_local_file(ctx, path, "a.bin", mode="file", known_hash=sha256_file(path))
    from app.core.db import session_scope

    with session_scope(ctx.session_factory) as session:
        operations = {o["operation"] for o in analytics.performance(session)["operations"]}
    assert "hash" not in operations and "upload" in operations


def test_empty_system_has_genuine_empty_values(client):
    overview = client.get("/api/v1/analytics/overview").json()
    assert overview["derived"]["savings_percent"] is None
    assert overview["distributions"]["file_types"] == []
    assert client.get("/api/v1/analytics/history").json()["snapshots"] == []


def test_audit_trail_records_and_filters(client):
    data = pattern(32, 100)
    file_id = upload(client, data, "a", mode="file").json()["file"]["id"]
    upload(client, data, "b", mode="file")
    client.post(f"/api/v1/files/{file_id}/verify")
    client.delete(f"/api/v1/files/{file_id}")
    types = {e["event_type"] for e in client.get("/api/v1/audit/events").json()["items"]}
    assert {"file.uploaded", "dedup.duplicate_detected", "integrity.passed", "file.deleted"} <= types
    assert all(e["event_type"].startswith("file.") for e in client.get("/api/v1/audit/events", params={"event_type": "file."}).json()["items"])


def test_settings_validate_and_apply(client):
    assert client.put("/api/v1/settings", json={"default_chunk_size": 3}).status_code == 422
    assert client.put("/api/v1/settings", json={"default_ingest_mode": "nope"}).status_code == 422
    assert client.put("/api/v1/settings", json={"default_ingest_mode": "chunk"}).json()["values"]["default_ingest_mode"] == "chunk"
    assert upload(client, pattern(33, 100)).json()["file"]["storage_mode"] == "chunk"


def test_diagnostics_run_real_checks(client):
    body = client.get("/api/v1/system/diagnostics").json()
    assert body["ok"] is True and len(body["checks"]) == 4


def test_cluster_replication_endpoint_validates_against_live_nodes(client):
    response = client.post("/api/v1/cluster/replication", json={"factor": 5})
    assert response.status_code == 422 and response.json()["error"]["details"]["live_datanodes"] == 3


def test_hdfs_outage_returns_503_and_leaves_no_file(tmp_path):
    ctx = make_context(tmp_path)
    ctx.hdfs = WebHdfsClient("http://127.0.0.1:9", connect_timeout_seconds=0.2)
    with TestClient(create_app(ctx)) as test_client:
        response = upload(test_client, b"data", mode="file")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "hdfs_unavailable"
        assert test_client.get("/api/v1/files").json()["total"] == 0
        events = test_client.get("/api/v1/audit/events", params={"severity": "error"}).json()["items"]
        assert events[0]["event_type"] == "request.failed"
        assert "/api/v1/files/upload" in events[0]["message"]


# -- WebHDFS client and parser, using a mock transport (no network) ---------------------------------


def _client_with(handler) -> WebHdfsClient:
    client = WebHdfsClient("http://nn:9870", datanode_map={"datanode1": "127.0.0.1:19864"})
    client._http = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    return client


def test_webhdfs_create_follows_two_step_protocol_and_rewrites_datanode_host():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "nn":
            return httpx.Response(307, headers={"location": "http://datanode1:9864/webhdfs/v1/a?op=CREATE"})
        return httpx.Response(201)

    _client_with(handler).create("/a", b"hello", length=5)
    assert seen[0].url.params["op"] == "CREATE" and seen[0].url.params["overwrite"] == "false"
    assert (seen[1].url.host, seen[1].url.port) == ("127.0.0.1", 19864)
    assert seen[1].content == b"hello"


def test_webhdfs_maps_remote_exceptions():
    def not_found(_):
        return httpx.Response(404, json={"RemoteException": {"exception": "FileNotFoundException", "message": "no"}})

    with pytest.raises(HdfsFileNotFound):
        _client_with(not_found).content_summary("/x")
    assert _client_with(not_found).status("/x") is None

    def safemode(_):
        return httpx.Response(403, json={"RemoteException": {"exception": "SafeModeException", "message": "safe"}})

    with pytest.raises(HdfsUnavailable):
        _client_with(safemode).mkdirs("/x")


def test_webhdfs_connection_failure_is_unavailable():
    client = WebHdfsClient("http://127.0.0.1:9", connect_timeout_seconds=0.2)
    with pytest.raises(HdfsUnavailable):
        client.status("/x")


def test_webhdfs_encodes_paths():
    seen = []

    def handler(request):
        seen.append(request.url.raw_path)
        return httpx.Response(200, json={"boolean": True})

    _client_with(handler).delete("/a b/c")
    assert b"/webhdfs/v1/a%20b/c" in seen[0]


def test_monitor_reports_unreachable_namenode_as_data():
    status = ClusterMonitor("http://127.0.0.1:9", timeout_seconds=0.2).status()
    assert status["reachable"] is False and "Cannot reach" in status["error"]


def test_parse_fsck_summary():
    text = """
 Total size:	1000 B
 Total files:	2
 Total blocks (validated):	2 (avg. block size 500 B)
 Minimally replicated blocks:	2 (100.0 %)
 Over-replicated blocks:	0 (0.0 %)
 Under-replicated blocks:	1 (50.0 %)
 Mis-replicated blocks:		0 (0.0 %)
 Default replication factor:	3
 Average block replication:	2.5
 Missing blocks:		0
 Corrupt blocks:		0
 Missing replicas:		1 (16.6 %)
 Number of data-nodes:		2
The filesystem under path '/x' is HEALTHY
Status: HEALTHY
"""
    parsed = parse_fsck(text)
    assert parsed["status"] == "HEALTHY"
    assert parsed["total_blocks"] == 2 and parsed["under_replicated_blocks"] == 1
    assert parsed["average_block_replication"] == 2.5 and parsed["datanodes"] == 2


def test_migrations_build_the_same_tables_as_the_models(tmp_path):
    from app.core.db import Base
    from sqlalchemy import create_engine, inspect

    database = tmp_path / "migrated.db"
    run_migrations(database)
    tables = set(inspect(create_engine(f"sqlite:///{database}")).get_table_names()) - {"alembic_version"}
    assert tables == set(Base.metadata.tables)

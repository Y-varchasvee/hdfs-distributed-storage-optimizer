#!/usr/bin/env python3
"""Experiment J: real failures. Stops real containers and kills a real backend process.

Usage:  backend/.venv/bin/python scripts/run_failure_experiments.py

  J1  A DataNode stops: stored files stay readable, and HDFS re-replication behaviour is observed.
  J2  The NameNode stops: uploads fail cleanly with 503 and leave no metadata; service resumes after restart.
  J3  The backend is killed with SIGKILL during optimization: nothing is lost and the job can be resumed.

Only this project's containers and a backend process started by this script are affected.
Results go to benchmarks/results/J_failure_handling.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

PROJECT = Path(__file__).resolve().parent.parent
BACKEND = PROJECT / "backend"
DATASET = PROJECT / "datasets" / "raw" / "originals"
RESULTS = PROJECT / "benchmarks" / "results" / "J_failure_handling.json"
NAMENODE = "http://127.0.0.1:9870"
TEST_ROOT = f"/hdfs-optimizer-failure-tests/{uuid.uuid4().hex}"


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], cwd=PROJECT, check=True, capture_output=True, text=True)


def jmx() -> dict | None:
    try:
        response = httpx.get(f"{NAMENODE}/jmx?qry=Hadoop:service=NameNode,name=FSNamesystem", timeout=3)
        return response.json()["beans"][0]
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        return None


def fsck(path: str) -> str:
    return httpx.get(f"{NAMENODE}/fsck", params={"ugi": "hadoop", "path": path}, timeout=60).text


def under_replicated(path: str) -> int:
    match = re.search(r"Under-replicated blocks:\s+(\d+)", fsck(path))
    return int(match.group(1)) if match else 0


def wait_for(predicate, timeout: float, poll: float = 1.0):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        value = predicate()
        if value:
            return time.monotonic() - started, value
        time.sleep(poll)
    return None, None


class Backend:
    """A private backend process with its own database and HDFS directory."""

    def __init__(self, state: Path, port: int = 8198):
        self.port = port
        self.base = f"http://127.0.0.1:{port}/api/v1"
        self.env = {
            **os.environ,
            "HDFSOPT_ROOT_PATH": TEST_ROOT,
            "HDFSOPT_DATABASE_PATH": str(state / "metadata.db"),
            "HDFSOPT_SPOOL_DIR": str(state / "spool"),
        }
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        self.process = subprocess.Popen(
            [str(BACKEND / ".venv/bin/uvicorn"), "app.main:app", "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning"],
            cwd=BACKEND, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        elapsed, _ = wait_for(lambda: self._healthy(), 40, 0.5)
        if elapsed is None:
            raise RuntimeError("Backend did not start")

    def _healthy(self) -> bool:
        try:
            return httpx.get(f"{self.base}/health", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False

    def kill(self) -> None:
        self.process.send_signal(signal.SIGKILL)
        self.process.wait()

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=20)

    def upload(self, path: Path, name: str, mode: str) -> httpx.Response:
        with open(path, "rb") as handle:
            return httpx.post(f"{self.base}/files/upload", files={"file": (name, handle)}, data={"mode": mode}, timeout=120)

    def get(self, path: str, **kwargs) -> httpx.Response:
        return httpx.get(f"{self.base}{path}", timeout=120, **kwargs)

    def post(self, path: str, body=None) -> httpx.Response:
        return httpx.post(f"{self.base}{path}", json=body, timeout=120)

    def wait_job(self, job_id: str, timeout: float = 300) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.get(f"/dedup/jobs/{job_id}").json()
            if job["status"] not in ("queued", "running"):
                return job
            time.sleep(0.5)
        raise TimeoutError(job_id)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def j1_datanode_failure(api: Backend) -> dict:
    source = DATASET / "pg1661.txt"
    expected = sha256(source.read_bytes())
    file_mode = api.upload(source, "datanode-test-whole.txt", "file").json()["file"]["id"]
    chunk_mode = api.upload(DATASET / "pg84.txt", "datanode-test-chunk.txt", "chunk").json()["file"]["id"]
    chunk_expected = sha256((DATASET / "pg84.txt").read_bytes())
    time.sleep(5)

    compose("stop", "datanode3")
    stopped = time.monotonic()
    immediately = sha256(api.get(f"/files/{file_mode}/download").content) == expected

    elapsed, _ = wait_for(lambda: (jmx() or {}).get("NumDeadDataNodes") == 1, 200)
    dead_after = None if elapsed is None else time.monotonic() - stopped
    status = api.get("/cluster/status").json()
    # The "dead" flag is computed from timestamps; the NameNode's heartbeat checker removes the node's replicas
    # from the block map on its own cycle, so fsck reports the loss a little later. Measure that gap.
    under_at_dead = under_replicated(TEST_ROOT)
    elapsed, _ = wait_for(lambda: under_replicated(TEST_ROOT) > 0, 120)
    gap = elapsed
    report = fsck(TEST_ROOT)
    under = [line.strip() for line in report.splitlines() if "Under-replicated blocks" in line or "Missing blocks" in line or "Average block replication" in line]
    whole_ok = sha256(api.get(f"/files/{file_mode}/download").content) == expected
    chunk_ok = sha256(api.get(f"/files/{chunk_mode}/download").content) == chunk_expected
    over_limit = api.post("/cluster/replication", {"factor": 3})

    compose("start", "datanode3")
    elapsed, _ = wait_for(lambda: (jmx() or {}).get("NumLiveDataNodes") == 3, 120)
    recovered_after = elapsed
    elapsed, _ = wait_for(lambda: under_replicated(TEST_ROOT) == 0, 180)
    return {
        "readable_immediately_after_stop": immediately,
        "seconds_until_namenode_declared_dead": dead_after,
        "cluster_health_while_dead": status.get("health"),
        "live_datanodes_while_dead": status.get("datanodes", {}).get("live"),
        "under_replicated_blocks_when_first_declared_dead": under_at_dead,
        "further_seconds_until_fsck_reports_under_replication": gap,
        "fsck_while_dead": under,
        "whole_file_mode_readable_while_dead": whole_ok,
        "chunk_mode_readable_while_dead": chunk_ok,
        "replication_factor_3_request_while_two_live_http_status": over_limit.status_code,
        "replication_factor_3_request_message": over_limit.json()["error"]["message"],
        "seconds_until_datanode_live_again": recovered_after,
        "seconds_until_no_under_replicated_blocks": elapsed,
    }


def j2_namenode_failure(api: Backend) -> dict:
    source = DATASET / "pg11.txt"
    before = api.get("/files").json()["total"]
    compose("stop", "namenode")
    wait_for(lambda: jmx() is None, 40)

    started = time.perf_counter()
    response = api.upload(source, "during-outage.txt", "file")
    failed_in = time.perf_counter() - started
    files_during = api.get("/files").json()["total"]
    cluster = api.get("/cluster/status").json()
    health = api.get("/health").json()
    stats = api.get("/storage/statistics").json()
    events = [e["event_type"] for e in api.get("/audit/events?page_size=5").json()["items"]]

    compose("start", "namenode")
    restart_elapsed, _ = wait_for(lambda: (jmx() or {}).get("NumLiveDataNodes") == 3, 180)
    safemode_elapsed, _ = wait_for(lambda: _write_ok(api), 120, 2)
    retry = api.upload(source, "after-outage.txt", "file")
    return {
        "upload_http_status_during_outage": response.status_code,
        "upload_error_code": response.json()["error"]["code"],
        "upload_failed_in_seconds": failed_in,
        "logical_files_before": before,
        "logical_files_during_outage": files_during,
        "api_still_answers_health": health["status"],
        "health_reports_hdfs_reachable": health["hdfs_reachable"],
        "cluster_status_reachable": cluster["reachable"],
        "measured_statistics_available_during_outage": stats["measured"]["available"],
        "recent_audit_event_types": events,
        "seconds_until_namenode_had_3_datanodes": restart_elapsed,
        "seconds_until_writes_accepted": safemode_elapsed,
        "retry_after_restart_http_status": retry.status_code,
        "retry_outcome": retry.json().get("outcome"),
    }


def _write_ok(api: Backend) -> bool:
    try:
        return api.get("/system/diagnostics").json()["ok"]
    except httpx.HTTPError:
        return False


def j3_process_kill(api: Backend) -> dict:
    sources = sorted(p for p in DATASET.glob("*.txt"))
    ids: dict[str, str] = {}
    for copy in range(3):
        for path in sources:
            response = api.upload(path, f"kill-{copy}-{path.name}", "raw")
            ids[response.json()["file"]["id"]] = sha256(path.read_bytes())
    analysis = api.wait_job(api.post("/dedup/analyze", {"mode": "chunk", "chunk_size": 64 * 1024}).json()["job_id"])
    job_id = api.post("/dedup/optimize", {"analysis_job_id": analysis["id"]}).json()["job_id"]

    elapsed, job = wait_for(lambda: _progress(api, job_id), 120, 0.05)
    if elapsed is None:
        raise RuntimeError("Job never made progress")
    api.kill()
    killed_at_progress = f"{job['progress_done']} of {job['progress_total']}"

    api.start()
    after = api.get(f"/dedup/jobs/{job_id}").json()
    catalog = api.get("/files?page_size=200").json()["items"]
    modes: dict[str, int] = {}
    for item in catalog:
        if item["id"] in ids:
            modes[item["storage_mode"]] = modes.get(item["storage_mode"], 0) + 1
    mid_verify = [api.post(f"/files/{file_id}/verify").json()["ok"] for file_id in ids]
    reconcile_before = api.get("/storage/reconcile").json()
    orphan_areas = sorted({path.removeprefix(TEST_ROOT).split("/")[1] for path in reconcile_before["orphans"]})

    resumed_id = api.post(f"/dedup/jobs/{job_id}/resume").json()["job_id"]
    resumed = api.wait_job(resumed_id)
    restored_ok = 0
    for file_id, expected in ids.items():
        if sha256(api.get(f"/files/{file_id}/download").content) == expected:
            restored_ok += 1
    reconcile_after = api.get("/storage/reconcile").json()
    return {
        "files": len(ids),
        "killed_at_progress": killed_at_progress,
        "job_status_after_restart": after["status"],
        "job_message_after_restart": after["message"],
        "storage_modes_after_kill": modes,
        "files_passing_sha256_before_resume": sum(mid_verify),
        "orphans_found_before_resume": reconcile_before["orphan_count"],
        "orphan_areas_before_resume": orphan_areas,
        "missing_found_before_resume": reconcile_before["missing_count"],
        "resumed_job_status": resumed["status"],
        "resumed_job_files_processed": resumed["result"]["files_processed"],
        "files_restored_byte_identical_after_resume": restored_ok,
        "orphans_after_resume": reconcile_after["orphan_count"],
        "missing_after_resume": reconcile_after["missing_count"],
    }


def _progress(api: Backend, job_id: str):
    job = api.get(f"/dedup/jobs/{job_id}").json()
    if job["status"] != "running":
        raise RuntimeError(f"Job ended before it could be interrupted: {job['status']}")
    return job if 3 <= job["progress_done"] < job["progress_total"] - 3 else None


def main() -> int:
    state = Path(tempfile.mkdtemp(prefix="hdfsopt-failure-"))
    api = Backend(state)
    results: dict = {"started": datetime.now(UTC).isoformat(), "scenario": "J_failure_handling"}
    code = 0
    try:
        api.start()
        for name, function in (("J1_datanode_failure", j1_datanode_failure), ("J2_namenode_failure", j2_namenode_failure), ("J3_process_kill", j3_process_kill)):
            print(f"--- {name}", flush=True)
            try:
                results[name] = {"status": "completed", **function(api)}
            except Exception as exc:  # noqa: BLE001 - a failed experiment is recorded, never hidden
                results[name] = {"status": "failed", "error": repr(exc)}
                code = 1
            print(json.dumps(results[name], indent=2), flush=True)
    finally:
        api.stop()
        compose("start", "namenode", "datanode1", "datanode2", "datanode3")
        wait_for(lambda: (jmx() or {}).get("NumLiveDataNodes") == 3, 180)
        httpx.delete(f"{NAMENODE}/webhdfs/v1{TEST_ROOT.rsplit('/', 1)[0]}", params={"op": "DELETE", "recursive": "true", "user.name": "hadoop"}, timeout=60)
        shutil.rmtree(state, ignore_errors=True)
        RESULTS.parent.mkdir(parents=True, exist_ok=True)
        RESULTS.write_text(json.dumps(results, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())

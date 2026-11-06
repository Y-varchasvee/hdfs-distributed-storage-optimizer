#!/usr/bin/env python3
"""Final quality audit. Every line it prints comes from a check it just ran.

Usage: backend/.venv/bin/python scripts/final_audit.py
Needs HDFS, the backend and the frontend running. Output is also saved to evidence/11_final_audit.txt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import fitz
import httpx
from pptx import Presentation

PROJECT = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:8100/api/v1"
FRONTEND = "http://127.0.0.1:3100"
PDF = PROJECT / "reports/final/HDFS_Storage_Optimizer_Complete_Report.pdf"
PPTX = PROJECT / "presentation/final/HDFS_Storage_Optimizer_Presentation.pptx"
REQUIRED_SCREENSHOTS = [
    "01_dashboard", "02_file_upload", "03_file_explorer", "04_duplicate_analysis", "05_optimization_preview",
    "06_optimization_complete", "07_storage_analytics", "08_replication_management", "09_cluster_status",
    "10_namenode_interface", "11_datanode_status", "terminal_05_backend_execution", "terminal_03_hdfs_namespace",
    "terminal_08_integration_tests", "16a_file_details_verified", "terminal_06_restore_checksum", "17_dataset_provenance",
]
PAGES = ["/", "/files", "/duplicates", "/optimize", "/replication", "/cluster", "/analytics", "/activity", "/lab", "/settings"]

results: list[tuple[bool, str]] = []
lines: list[str] = []


def say(text: str) -> None:
    print(text, flush=True)
    lines.append(text)


def check(ok: bool, text: str) -> bool:
    results.append((bool(ok), text))
    say(f"[{'PASS' if ok else 'FAIL'}] {text}")
    return bool(ok)


def run(command: list[str], cwd: Path) -> tuple[int, str]:
    process = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    return process.returncode, process.stdout + process.stderr


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    say(f"Final audit, {datetime.now(UTC).isoformat()}")

    free = shutil.disk_usage(PROJECT).free / 1024**3
    check(free > 1.0, f"Free disk on the host: {free:.1f} GiB")

    say("\n-- Services")
    code, output = run(["docker", "compose", "ps", "--format", "{{.Service}} {{.State}} {{.Health}}"], PROJECT)
    healthy = [line for line in output.splitlines() if "running healthy" in line]
    check(len(healthy) == 4, f"HDFS containers healthy: {len(healthy)} of 4")
    health = httpx.get(f"{API}/health", timeout=20).json()
    check(health["status"] == "ok" and health["hdfs_reachable"], f"Backend health: {health}")
    diagnostics = httpx.get(f"{API}/system/diagnostics", timeout=60).json()
    check(diagnostics["ok"], "Backend diagnostics, including a real HDFS write, read and delete")
    statuses = {page: httpx.get(f"{FRONTEND}{page}", timeout=30).status_code for page in PAGES}
    check(all(s == 200 for s in statuses.values()), f"Frontend pages returning 200: {sum(s == 200 for s in statuses.values())} of {len(PAGES)}")
    openapi = httpx.get("http://127.0.0.1:8100/openapi.json", timeout=20).json()
    check(len(openapi["paths"]) > 30, f"API documentation: {len(openapi['paths'])} documented paths")

    say("\n-- Authentic file upload and SHA-256-matching download")
    source = PROJECT / "datasets/raw/originals/pg1661.epub"
    data = source.read_bytes()
    recorded = next(f["sha256"] for f in json.loads((PROJECT / "datasets/provenance/manifest.json").read_text())["files"] if f["local_path"] == "originals/pg1661.epub")
    check(sha256(data) == recorded, "Source file matches its recorded provenance hash")
    created = []
    for mode, chunk_size in (("file", None), ("chunk", 65536), ("raw", None)):
        form = {"mode": mode, "folder": "/final-audit"}
        if chunk_size:
            form["chunk_size"] = str(chunk_size)
        response = httpx.post(f"{API}/files/upload", files={"file": (f"audit-{mode}.epub", data)}, data=form, timeout=120)
        response.raise_for_status()
        file_id = response.json()["file"]["id"]
        created.append(file_id)
        restored = httpx.get(f"{API}/files/{file_id}/download", timeout=120).content
        check(sha256(restored) == recorded and restored == data, f"Mode {mode}: outcome {response.json()['outcome']}, download is byte-identical, SHA-256 {sha256(restored)[:16]}...")
        verified = httpx.post(f"{API}/files/{file_id}/verify", timeout=120).json()
        check(verified["ok"], f"Mode {mode}: integrity check reads the bytes back from HDFS and passes")
    for file_id in created:
        httpx.delete(f"{API}/files/{file_id}", timeout=60).raise_for_status()
        httpx.delete(f"{API}/files/{file_id}", params={"permanent": "true"}, timeout=60).raise_for_status()
    reconcile = httpx.get(f"{API}/storage/reconcile", timeout=120).json()
    check(reconcile["orphan_count"] == 0 and reconcile["missing_count"] == 0, f"Database and HDFS agree: {reconcile['orphan_count']} orphans, {reconcile['missing_count']} missing")
    stats = httpx.get(f"{API}/storage/statistics", timeout=60).json()
    say(f"Current system: {stats['derived']['logical_files']} files, {stats['derived']['savings_percent']:.1f}% savings (derived), {stats['measured']['space_consumed']} bytes consumed (measured)")
    job = httpx.post(f"{API}/files/verify-all", timeout=30).json()["job_id"]
    deadline = time.time() + 300
    while time.time() < deadline:
        state = httpx.get(f"{API}/dedup/jobs/{job}", timeout=30).json()
        if state["status"] not in ("queued", "running"):
            break
        time.sleep(1)
    check(state["status"] == "succeeded" and not state["result"]["failed"], f"Every managed file verified: {state['result']['passed']} of {state['result']['files_checked']}")

    say("\n-- Automated tests")
    python = str(PROJECT / "backend/.venv/bin/python")
    for label, args, cwd in (
        ("Unit and API", [python, "-m", "pytest", "-m", "not hdfs", "-q"], PROJECT / "backend"),
        ("Integration on real HDFS", [python, "-m", "pytest", "-m", "hdfs", "-q"], PROJECT / "backend"),
        ("Browser", ["npx", "playwright", "test"], PROJECT / "frontend"),
    ):
        code, output = run(args, cwd)
        passed = re.findall(r"(\d+) passed", output)
        failed = re.findall(r"(\d+) failed", output)
        check(code == 0 and passed and not failed, f"{label} tests: {passed[-1] if passed else 0} passed, {failed[-1] if failed else 0} failed")
    code, output = run(["npx", "tsc", "--noEmit"], PROJECT / "frontend")
    check(code == 0, "Frontend type check")
    code, output = run([str(PROJECT / "backend/.venv/bin/ruff"), "check", "backend/app", "backend/tests", "--select", "E,F,I,B,UP", "--ignore", "E501,B008,B017,B018"], PROJECT)
    check(code == 0, "Backend lint")

    say("\n-- Evidence")
    missing = [name for name in REQUIRED_SCREENSHOTS if not (PROJECT / "screenshots" / f"{name}.png").exists()]
    check(not missing, f"Required screenshots present: {len(REQUIRED_SCREENSHOTS) - len(missing)} of {len(REQUIRED_SCREENSHOTS)} {missing or ''}")
    say(f"All screenshots: {len(list((PROJECT / 'screenshots').glob('*.png')))}")
    benchmark_json = list((PROJECT / "benchmarks/results").glob("*.json"))
    documents = [d for d in (json.loads(p.read_text()) for p in benchmark_json) if isinstance(d, dict) and "scenario" in d]
    failed_runs = [d["scenario"] for d in documents if d.get("status") == "failed"]
    inconsistent = [d["scenario"] for d in documents if d.get("inconsistent_values")]
    check(not failed_runs, f"Benchmark result files: {len(benchmark_json)} JSON, {len(list((PROJECT / 'benchmarks/results').glob('*.csv')))} CSV, {len(failed_runs)} failed")
    check(not inconsistent, f"Byte counts identical across repetitions: {len(inconsistent)} scenarios differ")
    failures = json.loads((PROJECT / "benchmarks/results/J_failure_handling.json").read_text())
    check(all(failures[k]["status"] == "completed" for k in ("J1_datanode_failure", "J2_namenode_failure", "J3_process_kill")), "Failure experiments completed")
    check(failures["J3_process_kill"]["files_restored_byte_identical_after_resume"] == failures["J3_process_kill"]["files"], "Process kill: every file restored byte-identical after resume")

    say("\n-- Report PDF")
    document = fitz.open(PDF)
    check(len(document) > 200, f"PDF opens: {len(document)} pages, {PDF.stat().st_size / 1e6:.1f} MB")
    code, output = run([python, "scripts/audit_report.py"], PROJECT)
    for line in output.strip().splitlines():
        say(f"  {line}")
    check(code == 0, "Report audit: required sections, every source file, no stray output, nothing outside the page")

    say("\n-- Presentation PPTX")
    deck = Presentation(PPTX)
    slides = list(deck.slides)
    check(len(slides) == 20, f"PPTX opens: {len(slides)} slides, {PPTX.stat().st_size / 1e6:.1f} MB")
    with_notes = sum(1 for s in slides if s.has_notes_slide and s.notes_slide.notes_text_frame.text.strip())
    check(with_notes == 20, f"Slides with speaker notes: {with_notes}")
    charts = sum(1 for s in slides for shape in s.shapes if shape.has_chart)
    pictures = sum(1 for s in slides for shape in s.shapes if shape.shape_type == 13)
    say(f"Native editable charts: {charts}; real screenshots: {pictures}")
    check(charts >= 5 and pictures >= 8, "Deck uses native charts and real screenshots")
    deck_text = " ".join(shape.text_frame.text for s in slides for shape in s.shapes if shape.has_text_frame)
    expected = json.loads((PROJECT / "benchmarks/results/I_before_after.json").read_text())["rows"][0]
    check(f"{expected['hdfs_space_consumed_before'] / 1048576:.0f} MiB" in deck_text and f"{expected['hdfs_space_consumed_after'] / 1048576:.0f} MiB" in deck_text, "Deck figures match the benchmark results used by the report")

    say("\n-- Deliverables")
    for path in (PDF, PPTX, PPTX.with_suffix(".pdf"), PROJECT / "README.md", PROJECT / "PROJECT_STATUS.md", PROJECT / "documentation/VIVA_PREPARATION.md", PROJECT / "documentation/RESULTS_SUMMARY.md", PROJECT / "datasets/provenance/manifest.json", PROJECT / "docker-compose.yml", PROJECT / "docker-compose.light.yml", PROJECT / ".env.example"):
        check(path.exists() and path.stat().st_size > 0, f"{path.relative_to(PROJECT)}: {path.stat().st_size} bytes")

    failures_count = sum(1 for ok, _ in results if not ok)
    say(f"\nRESULT: {len(results) - failures_count} of {len(results)} checks passed")
    (PROJECT / "evidence/11_final_audit.txt").write_text("\n".join(lines) + "\n")
    return 1 if failures_count else 0


if __name__ == "__main__":
    os.environ.setdefault("DOCKER_CONFIG", str(PROJECT / ".docker-local"))
    sys.exit(main())

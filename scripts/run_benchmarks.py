#!/usr/bin/env python3
"""Run the storage experiments on the real cluster and write CSV and JSON results.

Usage:  backend/.venv/bin/python scripts/run_benchmarks.py [--iterations 3] [--only B_exact_duplicates]

Each scenario runs in private HDFS directories and never touches managed data. Durations and throughputs are
repeated and reported as mean, min and max. Byte counts must be identical in every iteration; if they are not,
the run is flagged, because that would mean the system is not deterministic.
"""

from __future__ import annotations

import argparse
import csv
import inspect
import json
import platform
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "backend"))

from app.core.config import Settings  # noqa: E402
from app.core.db import Base, make_engine, make_session_factory  # noqa: E402
from app.hdfs.webhdfs import WebHdfsClient  # noqa: E402
from app.services import experiments  # noqa: E402
from app.services.context import AppContext, StoragePaths  # noqa: E402
from app.services.monitor import ClusterMonitor  # noqa: E402

RESULTS = PROJECT / "benchmarks" / "results"
TIMING_SUFFIXES = ("_s", "_mib_s")
# Disk readings include background DataNode activity. Directory counts depend on randomly generated file
# ids, because raw paths are prefixed by them. Neither affects stored data, so both are reported as a range.
ALLOWED_TO_VARY = ("disk_used_delta", "directory_count", "namespace_directories", "namespace_objects")


def disk_used_on_datanodes() -> int:
    """Bytes actually allocated on DataNode volumes: block files, checksum files and filesystem rounding."""
    total = 0
    for node in ("datanode1", "datanode2", "datanode3"):
        output = subprocess.run(
            ["docker", "compose", "exec", "-T", node, "du", "-s", "--block-size=1", "/data/dn/current"],
            cwd=PROJECT, capture_output=True, text=True, check=True,
        ).stdout
        total += int(output.split()[0])
    return total


def build_context(tmp_db: Path) -> AppContext:
    settings = Settings(_env_file=None, database_path=tmp_db)
    engine = make_engine(tmp_db)
    Base.metadata.create_all(engine)
    return AppContext(
        settings=settings,
        session_factory=make_session_factory(engine),
        hdfs=WebHdfsClient(settings.namenode_url, datanode_map=settings.datanode_map, timeout_seconds=120),
        paths=StoragePaths(root="/hdfs-optimizer-experiments/bench-parent"),
        monitor=ClusterMonitor(settings.namenode_url),
    )


def flatten(row: dict) -> dict:
    flat: dict = {}
    for key, value in row.items():
        if isinstance(value, dict):
            flat.update({f"{key}.{inner}": val for inner, val in value.items()})
        else:
            flat[key] = value
    return flat


def is_timing(key: str) -> bool:
    return key.endswith(TIMING_SUFFIXES)


def aggregate(iterations: list[list[dict]]) -> tuple[list[dict], list[str]]:
    """Combine aligned rows. Timings become mean/min/max; everything else must not change."""
    aggregated, inconsistencies = [], []
    for rows in zip(*iterations, strict=True):
        rows = [flatten(r) for r in rows]
        out: dict = {}
        for key in rows[0]:
            values = [r.get(key) for r in rows]
            numeric = [v for v in values if isinstance(v, int | float) and not isinstance(v, bool)]
            if is_timing(key) and numeric:
                out[f"{key}.mean"] = statistics.mean(numeric)
                out[f"{key}.min"] = min(numeric)
                out[f"{key}.max"] = max(numeric)
            elif any(tag in key for tag in ALLOWED_TO_VARY) and numeric:
                out[f"{key}.mean"] = statistics.mean(numeric)
                out[f"{key}.min"] = min(numeric)
                out[f"{key}.max"] = max(numeric)
            else:
                out[key] = values[0]
                if any(v != values[0] for v in values):
                    inconsistencies.append(f"{key}: {values}")
        aggregated.append(out)
    return aggregated, inconsistencies


def write_csv(path: Path, rows: list[dict]) -> None:
    columns: list[str] = []
    for row in rows:
        columns.extend(c for c in row if c not in columns)
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--only", action="append", help="Scenario id; repeatable")
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    work = RESULTS / ".work"
    work.mkdir(exist_ok=True)
    ctx = build_context(work / "bench-parent.db")
    status = ctx.monitor.status()
    if not status["reachable"]:
        print(f"HDFS is not reachable: {status['error']}")
        return 1

    environment = {
        "run_started": datetime.now(UTC).isoformat(),
        "machine": platform.machine(),
        "os": platform.platform(),
        "python": platform.python_version(),
        "hadoop_version": status["namenode"]["software_version"],
        "live_datanodes": status["datanodes"]["live"],
        "default_replication": ctx.hdfs.default_replication(),
        "deployment": "All daemons in Docker containers inside one Colima VM on one laptop; the backend runs on the host.",
    }
    (RESULTS / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
    print(json.dumps(environment, indent=2))

    # Destructive-free, and repeated only where a timing is meaningful.
    plan = {
        "A_unique_files": args.iterations,
        "B_exact_duplicates": args.iterations,
        "C_many_names": args.iterations,
        "D_chunk_sizes": args.iterations,
        "D2_boundary_shift": 1,
        "E_roundtrip": args.iterations,
        "F_shared_deletion": 1,
        "G_restore_after_optimize": 1,
        "H_replication": 1,
        "I_before_after": args.iterations,
    }
    failures = 0
    for scenario, count in plan.items():
        if args.only and scenario not in args.only:
            continue
        _, function = experiments.SCENARIOS[scenario]
        wants_probe = "physical_probe" in inspect.signature(function).parameters
        iterations, last = [], {}
        started = time.perf_counter()
        print(f"--- {scenario}: {count} iteration(s)", flush=True)
        try:
            for index in range(count):
                result = function(ctx, {}, physical_probe=disk_used_on_datanodes) if wants_probe else function(ctx, {})
                iterations.append(result["rows"])
                last = result
                print(f"    iteration {index + 1} done at {time.perf_counter() - started:.1f} s", flush=True)
        except Exception as exc:  # noqa: BLE001 - recorded in the results; a failed experiment is never hidden
            failures += 1
            message = getattr(exc, "message", repr(exc))
            print(f"    FAILED: {message}", flush=True)
            (RESULTS / f"{scenario}.json").write_text(json.dumps({"scenario": scenario, "status": "failed", "error": message}, indent=2) + "\n")
            continue
        rows, inconsistencies = aggregate(iterations)
        for line in inconsistencies:
            print(f"    INCONSISTENT {line}", flush=True)
        document = {
            "scenario": scenario,
            "title": experiments.SCENARIOS[scenario][0],
            "status": "succeeded",
            "description": last.get("description"),
            "iterations": count,
            "inconsistent_values": inconsistencies,
            "extra": {k: v for k, v in last.items() if k not in {"rows", "description"}},
            "rows": rows,
            "environment": environment,
        }
        (RESULTS / f"{scenario}.json").write_text(json.dumps(document, indent=2, default=str) + "\n")
        write_csv(RESULTS / f"{scenario}.csv", rows)
    for leftover in work.iterdir():
        leftover.unlink()
    work.rmdir()
    print(f"finished; {failures} scenario(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

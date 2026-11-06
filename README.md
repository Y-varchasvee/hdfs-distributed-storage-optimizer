# HDFS Optimizer

**HDFS-Based Distributed File Replication, Deduplication and Storage Optimization System**

HDFS replicates blocks for safety, but if two people upload the same file, it stores both. HDFS Optimizer adds application-managed deduplication on top of an unmodified Apache Hadoop cluster: identical content is stored once, HDFS still replicates that copy, and every restored file is checked against its original SHA-256.

- **Whole-file deduplication:** content-addressed objects, with any number of logical names per object.
- **Chunk-level deduplication:** fixed-size chunks, shared across files, rebuilt from manifests.
- **Safe optimization:** a dry run first. Each file is verified before its old copy is removed.
- **Reference-aware deletion:** recoverable deletes, and garbage collection based on database relations.
- **Replication management:** real factor changes, verified with `fsck` and block locations.
- **Live monitoring:** NameNode and DataNode state from JMX; storage from the NameNode.
- **Honest numbers:** every headline value is labelled measured, derived or estimated.

Measured results are in [documentation/RESULTS_SUMMARY.md](documentation/RESULTS_SUMMARY.md). Current status is in [PROJECT_STATUS.md](PROJECT_STATUS.md), and every deliverable and limitation is listed in [FINAL_DELIVERY_CHECKLIST.md](FINAL_DELIVERY_CHECKLIST.md).

## Architecture

```
Browser (Next.js) -> REST API (FastAPI) -> Services -> WebHDFS -> HDFS (1 NameNode, 3 DataNodes)
                                              |
                                              +-> SQLite metadata database
```

HDFS and SQLite cannot share a transaction, so every write follows one order: stage the bytes in HDFS, check them, rename atomically, then commit the metadata. A crash can leave an unreferenced file, which reconciliation finds, but never metadata pointing at missing bytes.

Diagrams are in `diagrams/`. The full design is in the report.

## Requirements

| | Standard deployment | Light deployment |
|---|---|---|
| Memory for the Docker VM | 4 GB | 3 GB |
| Free disk | 6 GB (Hadoop image is about 2 GB), plus 5 GB to containerise the app | Same |
| DataNodes / replication | 3 / factor 3 | 2 / factor 2 |

Software: Docker with Compose (or Colima on macOS), Python 3.12, Node.js 22. Tested on an Apple M1 with 8 GB RAM running macOS 26. Pinned versions are in `backend/requirements.txt` and `frontend/package-lock.json`.

The official `apache/hadoop` images are amd64-only, so `infrastructure/docker/hadoop/Dockerfile` builds from the official Apache release tarball for your architecture and checks its SHA-512.

## Installation

On macOS without Docker Desktop:

```bash
brew install colima docker docker-compose
```

Then install dependencies, build the frontend and build the Hadoop image:

```bash
scripts/setup.sh
```

## Starting

```bash
scripts/start-all.sh
```

| What | Where |
|---|---|
| Application | <http://localhost:3100> |
| API documentation | <http://localhost:8100/docs> |
| NameNode interface | <http://localhost:9870> |
| DataNode interfaces | <http://localhost:19864>, `19865`, `19866` |

To run each part separately:

```bash
scripts/start-runtime.sh
```

```bash
source scripts/env.sh && docker compose up -d --wait
```

```bash
scripts/start-backend.sh
```

```bash
scripts/start-frontend.sh
```

For the low-memory cluster, stop the standard cluster first, since they use the same ports. Its data is kept in separate volumes:

```bash
docker compose stop && docker compose -f docker-compose.light.yml up -d --wait
```

To switch back:

```bash
docker compose -f docker-compose.light.yml stop && docker compose up -d --wait
```

To run the backend and frontend in containers too, first build the images. This script stops if free disk falls below a safety margin, because image builds grow the VM's disk on the host. Allow about 5 GB of free space:

```bash
scripts/build-app-images.sh
```

```bash
docker compose --profile app up -d
```

On the evaluation machine, the backend image was built and tested end to end. The frontend image could not be built with a safe disk margin, so its build steps and server command were tested directly on the host instead (`evidence/13_containerised_app.txt`).

### Stopping and data

```bash
scripts/stop-all.sh
```

Add `--vm` to also stop the Colima VM. HDFS data stays in named Docker volumes across restarts, and the NameNode formats its directory only when it is empty.

To delete disposable demo data, stop the backend first, then run the command below. It removes only this project's HDFS directories and metadata database, using fixed paths, and asks you to type `RESET`.

```bash
scripts/reset-demo.sh
```

## Using it

### Dataset

```bash
backend/.venv/bin/python scripts/download_dataset.py
```

This fetches authentic Project Gutenberg files and writes provenance to `datasets/provenance/manifest.json`. See [datasets/README.md](datasets/README.md). You can do the same from the **Dataset lab** page, which can also ingest files with labelled workload copies.

### Upload and deduplicate

On **Files**, drag files in and choose a mode. Upload the same file twice under different names: the second reports "Duplicate: no new data stored". To see optimization reclaim space, upload with **No dedup**, then go to **Optimization**: run the dry run, review it, and start.

### Replication

On **Replication**, change the factor. A factor above the number of live DataNodes is refused, and lowering it needs confirmation. Success is reported only after `fsck` and block locations agree.

## Tests

Unit tests use a clearly labelled local-filesystem stand-in in `backend/tests/support/`, which is not part of the application:

```bash
cd backend && .venv/bin/python -m pytest -m "not hdfs"
```

Integration tests use the real cluster and authentic files:

```bash
cd backend && .venv/bin/python -m pytest -m hdfs
```

Browser tests use a real browser and the real cluster, with an isolated backend. They need the production build and Google Chrome:

```bash
cd frontend && npx playwright test
```

## Benchmarks

These run in private HDFS directories and do not touch managed data. Results go to `benchmarks/results/` as CSV and JSON:

```bash
source scripts/env.sh && backend/.venv/bin/python scripts/run_benchmarks.py --iterations 3
```

The failure experiments really stop containers and kill a backend process, so do not run them during a demo:

```bash
source scripts/env.sh && backend/.venv/bin/python scripts/run_failure_experiments.py
```

Then regenerate the charts and summary:

```bash
backend/.venv/bin/python scripts/make_charts.py
```

## Regenerating deliverables

The screenshots come from a live system. Stop the backend, reset the demo data, start the backend again, then run:

```bash
scripts/capture_evidence.sh
```

Then build the report. It needs Typst, and includes the source code directly from the repository, so the two cannot diverge:

```bash
backend/.venv/bin/python scripts/build_report.py
```

Build the presentation:

```bash
cd presentation/source && ../../backend/.venv/bin/python prepare_crops.py && npm install --no-audit --no-fund && node build_deck.js
```

Outputs are `reports/final/HDFS_Storage_Optimizer_Complete_Report.pdf` and `presentation/final/HDFS_Storage_Optimizer_Presentation.pptx`.

## Project layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI app, services, models, migrations, tests |
| `frontend/` | Next.js app and browser tests |
| `infrastructure/` | Hadoop image and configuration |
| `datasets/` | Provenance and dataset notes; raw files are downloaded |
| `scripts/` | Setup, start and stop, benchmarks, evidence, report tools |
| `benchmarks/results/` | Measured CSV and JSON results and charts |
| `screenshots/`, `evidence/` | Real screenshots and terminal output |
| `diagrams/` | Generated architecture diagrams |
| `documentation/` | Viva preparation and results summary |
| `reports/`, `presentation/` | Report and deck, source and final |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `docker: unknown command: docker compose` | Compose plugin not found. Run `source scripts/env.sh`, which uses this project's Docker config. |
| Image pulls fail with a credential helper error | Your `~/.docker/config.json` refers to a removed Docker Desktop. `source scripts/env.sh` avoids it. |
| A port is already in use | Set `BACKEND_PORT` or `FRONTEND_PORT`. Port 3100 was chosen because 3000 is commonly taken. |
| Uploads fail with 503 after a restart | The NameNode stays in safe mode briefly after starting. Wait a few seconds and retry. |
| Monitoring seems a few seconds behind | NameNode JMX values are cached for about 10 seconds. |
| A DataNode stays "live" just after stopping it | Dead-node detection takes about 90 s in this configuration, and about 10.5 minutes with Hadoop defaults. |
| Replication shows "did not converge in time" | A factor above live DataNodes is refused, so check for a failed DataNode, then try again. |
| Download fails partway through | The file failed its integrity check, or HDFS went down. Check **Activity**, then use **Verify integrity**. |

## Known limitations

- One API process with a single job worker. Uploads are serialised while they store.
- SQLite is the index, so it does not scale to billions of chunks.
- Fixed-size chunking only: a one-byte insertion near the start defeats it. Content-defined chunking is future work.
- Each chunk is a separate HDFS file, so small chunks cost NameNode memory and much lower throughput. Chunk packing is future work.
- The test cluster runs on one machine with one disk, so it shows software behaviour, not hardware fault tolerance or production performance.
- Access control is an optional shared token for local use. No Kerberos, and no per-user permissions.
- The evaluation dataset is small, and its duplicates are created deliberately.

## Academic demonstration

The script and 36 prepared questions are in [documentation/VIVA_PREPARATION.md](documentation/VIVA_PREPARATION.md).

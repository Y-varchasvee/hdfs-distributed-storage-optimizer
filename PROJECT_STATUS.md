# HDFS Optimizer: Project Status

Durable checkpoint so another session can resume. Only claims backed by an executed command belong here.

## Current phase
All phases complete. Final audit: 42 of 42 checks passed (evidence/11_final_audit.txt). See FINAL_DELIVERY_CHECKLIST.md for every artifact and limitation.

## Environment (inspected 2026-11-05)
- macOS 26.6.2, Apple M1 (arm64), 8 GB RAM, 8 cores. Disk is tight: under 6 GB free at handoff.
- Docker Desktop was removed from this machine. Installed through Homebrew: colima 0.10.3, docker 29.9.2,
  docker-compose 5.6.1, typst 0.15.1, LibreOffice 26.8. A dedicated Colima profile `hdfsopt` runs the daemon.
- Scripts use a project-local Docker config (`.docker-local`) because `~/.docker/config.json` still references the
  removed Docker Desktop credential helper. Source `scripts/env.sh` (works in bash and zsh) before using docker.
- Port 3000 is taken by an unrelated local process, so the frontend uses 3100 and the backend uses 8100.
- The git root is the home directory with no commits. Nothing has been committed.

## Completed
- Phase 2 verified: 1 NameNode + 3 DataNodes on genuine Apache Hadoop 3.5.0 (native arm64 image built from the official
  tarball with SHA-512 verification). CLI put/cat, fsck HEALTHY at replication 3, WebHDFS redirects, JMX all checked.

- Phase 3 verified: FastAPI backend, SQLAlchemy models, Alembic migration, WebHDFS client, staged content store, file and
  chunk dedup, soft delete / purge / GC, integrity checks, optimizer, replication, monitor, datasets, experiments.
- Tests: `cd backend && .venv/bin/python -m pytest -m "not hdfs"` 126 passed; `-m hdfs` 17 passed against the real cluster
  (3 consecutive runs).
- Dataset: 15 authentic Project Gutenberg files + 3 documented transformed files; see datasets/provenance/manifest.json.

- Phase 4 verified: all 10 pages built; 13 Playwright browser tests pass on the real cluster.
- Phase 6 verified: benchmarks (`benchmarks/results/*.json`, `*.csv`, 0 failures, 0 inconsistent values, after correcting two
  measurement faults) and failure experiments (`J_failure_handling.json`, no data loss).

- Phases 7 to 10 verified: 43 real screenshots and terminal evidence, 250-page report, 20-slide deck, final audit.
- Tests: 129 unit, 17 real-cluster, 13 browser, all passing. Light cluster and backend container tested end to end.

## Open items (need the user)
1. Fill in placeholders in the report and slide 1, and complete the AI-assistance disclosure in the declaration.
2. Confirm transformed test files are allowed by the assignment.
3. Open the PPTX in PowerPoint once; it was inspected through LibreOffice only.

## Not verified
- The frontend container image was not built: not enough free disk. Its build and server command were run on the host.
  To finish this on a machine with 5 GB free: `scripts/build-app-images.sh`, then `docker compose --profile app up -d`.

## To resume or rebuild
- Start: `scripts/start-all.sh`. Stop: `scripts/stop-all.sh` (add --vm to stop the VM).
- Evidence: stop the backend, `scripts/reset-demo.sh --yes`, start it, `scripts/capture_evidence.sh`.
- Report: `backend/.venv/bin/python scripts/build_report.py`. Deck: see the README. Audit: `scripts/final_audit.py`.

## Findings from real HDFS worth keeping in the report
- JMX values are cached for about 10 s, so per-run counts come from GETCONTENTSUMMARY and fsck on the run's own directory.
- DataNodes delete asynchronously: disk readings wait for `du` to return the same value three times.
- "Dead" is computed from timestamps, and replicas leave the block map on the heartbeat cycle: fsck showed under-replication 8.4 s later.
- Re-replication is rate limited (about 2 x live nodes per 3 s), so a fixed 180 s timeout misreported large namespaces. It now scales.
- At 16 KiB chunks, logical savings are 8.9% while disk use is 14.6% higher than whole-file storage.
- Hash timing bug: a precomputed hash reported millions of MiB/s on the Analytics page. Fixed, with tests. Benchmarks were unaffected.
- The frontend image build filled the host disk to 117 MiB. HDFS was unharmed; `scripts/build-app-images.sh` now has a disk guard.
- fsck stops counting a replica once marked excess, before the DataNode deletes it, so verification also checks block locations.
- A write returns at minimum replication; full block locations appear shortly after, via asynchronous block reports.

## Disclosures
- Project Gutenberg's policy says automated tools should use mirrors. The dataset was fetched once from www.gutenberg.org at one
  request per 2 s before this was noticed; the manifest records those URLs. The tool now uses gutenberg.pglaf.org, and pg11.txt from
  that mirror has the recorded SHA-256.

## Known limitations so far
- Official `apache/hadoop` images are amd64-only, hence the custom image.
- All DataNodes share one VM disk, so configured capacity (88 GB) counts one disk three times.

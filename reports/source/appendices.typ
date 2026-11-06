#import "lib.typ": *

#let routes = json("generated/api_routes.json")
#let schema = json("generated/db_schema.json")
#let manifest = json("/datasets/provenance/manifest.json")
#let environment = json("/benchmarks/results/environment.json")

#set page(columns: 1, margin: (x: 18mm, top: 18mm, bottom: 18mm))

= Appendix A: Setup Commands

The commands below were used to build and run the system on the evaluation machine.

```bash
brew install colima docker docker-compose typst    # macOS without Docker Desktop
scripts/setup.sh                                   # dependencies, frontend build, Hadoop image
scripts/start-all.sh                               # HDFS, backend, frontend
backend/.venv/bin/python scripts/download_dataset.py
cd backend && .venv/bin/python -m pytest -m "not hdfs"
cd backend && .venv/bin/python -m pytest -m hdfs
cd frontend && npx playwright test
source scripts/env.sh && backend/.venv/bin/python scripts/run_benchmarks.py --iterations 3
source scripts/env.sh && backend/.venv/bin/python scripts/run_failure_experiments.py
backend/.venv/bin/python scripts/make_charts.py
scripts/capture_evidence.sh
backend/.venv/bin/python scripts/build_report.py
cd presentation/source && ../../backend/.venv/bin/python prepare_crops.py && npm install --no-audit --no-fund && node build_deck.js
```

Evaluation environment: #environment.machine, #environment.os, Python #environment.python, Hadoop #environment.hadoop_version, #environment.live_datanodes DataNodes, replication #environment.default_replication. #environment.deployment

= Appendix B: API Documentation

Generated from the application's OpenAPI schema. Interactive documentation is served at `http://localhost:8100/docs`.

#table(columns: (auto, auto, 1fr),
  table.header([*Method*], [*Path*], [*Purpose*]),
  ..routes.map(r => (r.method, raw(r.path), r.summary)).flatten(),
)

= Appendix C: Configuration

All settings use environment variables with the prefix `HDFSOPT_`. See `.env.example`, which is also listed in Chapter 11. HDFS settings are in `infrastructure/hadoop/hdfs-site.xml`. Values that differ from Hadoop defaults for demonstration:

#table(columns: (auto, auto, 1fr),
  table.header([*Property*], [*Value*], [*Reason*]),
  [`dfs.namenode.heartbeat.recheck-interval`], [30000 ms], [A stopped DataNode is declared dead after about 90 s instead of 10.5 minutes],
  [`dfs.namenode.safemode.extension`], [5000 ms], [Faster restart in demonstrations],
  [`dfs.client.block.write.replace-datanode-on-failure.best-effort`], [true], [Small clusters have no spare node for a failed write pipeline],
)

= Appendix D: Database Schema

Generated from the SQLAlchemy models.

#for table-info in schema [
  #block(above: 1em, below: 0.4em, sticky: true, text(weight: "bold", raw(table-info.name)))
  #table(columns: (auto, auto, auto, 1fr),
    table.header([*Column*], [*Type*], [*Null*], [*Key*]),
    ..table-info.columns.map(c => (raw(c.name), c.type, if c.nullable { "yes" } else { "no" }, c.key)).flatten(),
  )
  #if table-info.constraints.len() > 0 {
    text(size: 8.5pt, fill: muted)[Constraints and indexes: #table-info.constraints.join("; ").]
  }
]

= Appendix E: Test Results

Counts are parsed from the saved test output in `evidence/` when this report is built.

#table(columns: (1fr, auto, auto),
  table.header([*Suite*], [*Passed*], [*Failed*]),
  [Unit and API tests (stand-in storage, labelled test-only)], str(counts.unit.passed), str(counts.unit.failed),
  [Integration tests on the real HDFS cluster], str(counts.integration.passed), str(counts.integration.failed),
  [Browser tests in Chrome on the real cluster], str(counts.browser.passed), str(counts.browser.failed),
)

The tests cover file hashing, upload, exact duplicate detection, different names with identical contents, different contents with the same name, object creation, shared chunk references, reconstruction, SHA-256 integrity, logical deletion, shared content preservation, garbage collection safety, invalid input, HDFS connection errors, replication validation, API responses, database constraints, partial upload failure, interrupted jobs and metric correctness.

= Appendix F: Benchmark Records

Machine-readable records are in `benchmarks/results/`, as a CSV and a JSON file per scenario, and `documentation/RESULTS_SUMMARY.md` is generated from them. To reproduce them, run the benchmark commands in Appendix A. Timings will differ between machines; byte counts should not.

= Appendix G: Dataset Provenance

From `datasets/provenance/manifest.json`. Full SHA-256 values and URLs are in that file.

#table(columns: (auto, 1fr, auto, auto, auto),
  table.header([*Kind*], [*Title and source page*], [*Format*], [*Bytes*], [*SHA-256 prefix*]),
  ..manifest.files.map(f => (f.kind, [#f.title\ #link(f.source_url)], f.file_format, str(f.size_bytes), raw(f.sha256.slice(0, 16)))).flatten(),
)

Original files were downloaded from `www.gutenberg.org/cache/epub/` on #manifest.files.at(0).download_date.slice(0, 10). Organization: #manifest.files.at(0).source_organization. #manifest.files.at(0).license_note

= Appendix H: Troubleshooting

#table(columns: (auto, 1fr),
  table.header([*Symptom*], [*Cause and fix*]),
  [`docker compose` not found], [Run `source scripts/env.sh`, which uses the project's Docker configuration.],
  [Image pull fails on a credential helper], [The home Docker configuration refers to a removed Docker Desktop. The same command avoids it.],
  [Uploads return 503 just after a restart], [The NameNode is briefly in safe mode. Wait a few seconds and retry.],
  [Monitoring lags by a few seconds], [NameNode JMX values are cached for about 10 seconds.],
  [Replication shows "did not converge"], [Check for a dead DataNode, then try again.],
  [A download stops partway], [The file failed verification, or HDFS went down. Check the Activity page.],
)

# Final Delivery Checklist

**Project root:** `/Users/vvsiscold/Documents/prj/her`
**Last audit:** 5 November 2026, `scripts/final_audit.py`: 42 of 42 checks passed. Full output: `evidence/11_final_audit.txt`.

Status meanings: **Verified** means a command or inspection confirmed it. **Partly verified** says exactly what was and was not confirmed.

## Before you submit

These need you, and could not be done for you:

1. **Fill in the placeholders.** Name, roll number, department, university, session, supervisor and signatures are marked placeholders in the report (red, in brackets) and on slide 1. They are in `reports/source/main.typ` and `presentation/source/build_deck.js`. Rebuild afterwards, or edit the PPTX directly.
2. **Complete the Declaration of Originality honestly.** This project was built with AI assistance. The declaration contains a placeholder for you to state your own contribution and disclose that assistance. Check your institution's policy before signing.
3. **Confirm that transformed test files are allowed.** Your brief permits them only "if permitted by the assignment requirements". They are three documented byte-level edits of one book, used for partial-overlap experiments. If they are not allowed, remove experiments D and D2 and the shared-chunk evidence.
4. **Open the PPTX in PowerPoint once.** It passed schema validation and was inspected through LibreOffice, but no copy of PowerPoint was available.
5. **Practise the demo.** The script and 36 questions are in `documentation/VIVA_PREPARATION.md`.

## Deliverables

| Artifact | Path | Status | Evidence |
|---|---|---|---|
| IEEE-style report | `reports/final/HDFS_Storage_Optimizer_Complete_Report.pdf` | Verified | 250 pages, 23 MB. All 17 chapters, front matter and appendices A to H present. Pages inspected. |
| Report source | `reports/source/` | Verified | Rebuilds with `scripts/build_report.py`. |
| Presentation | `presentation/final/HDFS_Storage_Optimizer_Presentation.pptx` | Verified, except in PowerPoint | 20 slides, 5 native charts, 10 real screenshots, speaker notes on all. Schema valid. Every slide inspected through LibreOffice. |
| Presentation preview | `presentation/final/HDFS_Storage_Optimizer_Presentation.pdf` | Verified | Rendered by LibreOffice. |
| Viva guide | `documentation/VIVA_PREPARATION.md` | Verified | Timed demo script and 36 questions. |
| Results summary | `documentation/RESULTS_SUMMARY.md` | Verified | Generated from the result files. |
| Setup guide | `README.md` | Verified | All 20 requested topics. |
| Status file | `PROJECT_STATUS.md` | Verified | Current. |

## Software

| Component | Path | Status | Evidence |
|---|---|---|---|
| Backend | `backend/` | Verified | 129 unit and API tests, 17 real-cluster tests. |
| Frontend, 10 pages | `frontend/` | Verified | 13 browser tests in Chrome. All 10 pages viewed in screenshots. |
| Standard HDFS cluster: 1 NameNode, 3 DataNodes | `docker-compose.yml` | Verified | Hadoop 3.5.0, factor 3, `fsck` HEALTHY. |
| Light cluster: 2 DataNodes, factor 2 | `docker-compose.light.yml` | Verified | `evidence/12_light_cluster.txt` |
| Backend container | `backend/Dockerfile` | Verified | Upload and SHA-256-matched download against the real cluster. `evidence/13_containerised_app.txt` |
| **Frontend container** | `frontend/Dockerfile` | **Partly verified** | **The image was not built here: not enough free disk.** Its build and server command were run on the host and served all 10 pages. Therefore `docker compose --profile app up` has never run as a whole. |
| Reset and shutdown scripts | `scripts/reset-demo.sh`, `scripts/stop-all.sh` | Verified | Reset uses fixed paths, and refuses to run while the backend is up. |

## Evidence

| Requirement | Path | Status |
|---|---|---|
| Screenshots, 43 images | `screenshots/` | Verified: captured from a live system, unedited. All 18 required kinds covered. |
| Terminal output | `evidence/*.txt` | Verified: unedited; rendered as `screenshots/terminal_*.png` |
| Benchmark data | `benchmarks/results/` | Verified: 10 scenarios plus failures, CSV and JSON, no failed runs, byte counts identical across repeats |
| Charts | `benchmarks/charts/` | Verified: generated from the data |
| Failure experiments | `benchmarks/results/J_failure_handling.json` | Verified: real stops and a real `SIGKILL` |
| Dataset provenance | `datasets/provenance/manifest.json` | Verified: 15 originals and 3 transformed files |
| Diagrams, 10 | `diagrams/` | Verified: inspected, match the code |

## Test results

| Suite | Result |
|---|---|
| Unit and API (labelled test-only storage stand-in) | 129 passed, 0 failed |
| Integration on the real HDFS cluster | 17 passed, 0 failed |
| Browser, Chrome, real cluster | 13 passed, 0 failed |
| Type check and lint | Pass |
| Authentic file through all 3 modes, downloaded, SHA-256 compared | Identical |
| All 34 managed files re-read from HDFS | 34 of 34 match |
| Database compared with HDFS | 0 orphans, 0 missing |

## Key measured results

These come from controlled workloads with deliberately created, labelled duplicates. They verify the mechanism. **They do not predict savings on any real system.** Timings describe one laptop.

| Measurement | Result |
|---|---|
| Exact duplicates, N copies | Savings exactly (N-1)/N: 50%, 75%, 83.33% |
| 27 files, three copies of 9 books, NameNode space | 119.95 MiB to 39.98 MiB |
| Same, on DataNode disks (`du`) | 121.22 MiB to 40.41 MiB |
| Dry-run prediction of stored bytes | Exact in both modes |
| Fixed-size chunks at 64 KiB, chunks reused | 90.9% truncated, 91.7% one byte replaced, 0% one byte inserted |
| 16 KiB chunks | 8.91% logical savings, yet **14.64% more disk** than whole-file storage |
| Verified restore | About 154 MiB/s whole-file, about 35 MiB/s chunked |
| DataNode stopped | Files stayed readable; dead after about 88 s |
| NameNode stopped | HTTP 503 in 0.02 s; nothing recorded; retry succeeded after restart |
| Backend killed during a job | Marked interrupted; resumed; 27 of 27 byte-identical |

## Unresolved limitations

**Not verified or not done**

- The frontend container image was never built, as described above.
- The deck has not been opened in PowerPoint itself, and has **no slide transitions**. The brief asked for them "where supported"; the deck library does not offer them.
- There is no independent review of the report's prose or claims. Have your supervisor read it.

**Limits of the system** (all in Chapter 15 of the report)

- One laptop and one disk: this shows software behaviour under failure, not hardware fault tolerance. Configured capacity counts one disk three times.
- About 41 MiB of data, so nothing here speaks to production scale. Timing ranges are wide.
- Fixed-size chunking only. Content-defined chunking and chunk packing are future work.
- One API process, serial ingestion, and SQLite as the index.
- Access control is an optional shared token. Do not expose this to a network.
- NameNode JMX values lag by about 10 seconds, so monitoring can trail briefly.

## Things you should know

- **Project Gutenberg policy.** Its website is for human users, and its policy directs automated tools to mirrors. The dataset was fetched once from the main site, at one request every 2 seconds, before this was noticed. The report discloses this. The tool now uses the official mirror, and `pg11.txt` from that mirror matches the recorded hash.
- **Disk space.** Your disk has under 6 GB free. One image build filled it to 117 MiB, causing I/O errors in that build. HDFS was checked and was unharmed, and space was recovered. `scripts/build-app-images.sh` now aborts below a safety margin.
- **Installed on this machine through Homebrew:** colima, docker, docker-compose, typst and LibreOffice. LibreOffice uses about 1.7 GB; `brew uninstall --cask libreoffice` removes it once the deck is final.
- **Git.** Nothing was committed. Your Git root is your home directory, which has no commits, so consider running `git init` in this project before committing it.

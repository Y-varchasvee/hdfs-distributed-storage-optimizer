# Dataset

This is not a machine-learning project, so it needs no labelled dataset. It needs real files with realistic structure, so that hashing, chunking, transfer and restoration are exercised on authentic bytes.

## Source

All original files come from [Project Gutenberg](https://www.gutenberg.org/), downloaded exactly as served and never altered. Project Gutenberg's terms are at <https://www.gutenberg.org/policy/license.html>.

```bash
backend/.venv/bin/python scripts/download_dataset.py
```

The tool skips files whose bytes still match their recorded hash, and waits between requests.

### How files are fetched

Project Gutenberg's [robot access policy](https://www.gutenberg.org/policy/robot_access.html) says its website is for human users and directs automated tools to mirrors. The download tool therefore uses the mirror run by the Project Gutenberg Literary Archive Foundation (`gutenberg.pglaf.org`).

The files currently in `raw/` were fetched once, before this policy was noticed, from `www.gutenberg.org/cache/epub/...` with a 2-second delay between requests. The manifest records those exact URLs truthfully. As a spot check, `pg11.txt` from the mirror has the same SHA-256 as the recorded file.

## Provenance

`provenance/manifest.json` records, for every file: title, author, ebook id, source organization, source page, requested and final download URL, download date, format, size, SHA-256, kind and transformations.

The raw files live in `raw/` and are not committed, because they can be downloaded again. Compare a new download with the recorded hash: a difference means the publisher has regenerated that file.

## Three kinds of file

| Kind | What it is | Label in the application |
|---|---|---|
| **Original** | Bytes as published. Not edited. | `dataset_original` |
| **Workload copy** | The same bytes under another logical name, for duplicate tests. No new file is created on disk. | `workload_copy` |
| **Transformed** | A documented byte-level edit of one original, for partial-overlap tests. | `transformed` |

Workload copies and transformed files are test workloads, not separately published works. The report and the interface never present them as originals.

### Transformations

All three derive from *Pride and Prejudice* (ebook 1342). No text is invented; the only added bytes are one newline or one replaced byte.

| File | Edit | What it tests |
|---|---|---|
| `workload/pg1342.truncate_90.txt` | First 90% of the bytes | Shared prefix: every chunk except the last is reusable |
| `workload/pg1342.prefix_newline.txt` | One newline inserted at the start | Boundary shift: the known weakness of fixed-size chunking |
| `workload/pg1342.replace_mid_byte.txt` | One byte replaced at the midpoint | Local edit: exactly one chunk should change |

If your assignment forbids any transformed input, drop these files: the exact-duplicate experiments do not use them.

## What this dataset cannot show

- **Scale.** About 41 MB, far below production HDFS. Throughput figures describe this laptop setup, not a real cluster.
- **Real-world duplication rates.** Duplicates are created deliberately, so measured savings describe these workloads. They do not predict the savings of any real system.
- **Large-block behaviour.** Files are smaller than the 128 MiB HDFS block size, so each file here occupies one block.

#!/usr/bin/env python3
"""Download authentic source files from Project Gutenberg and write provenance.

Usage:  backend/.venv/bin/python scripts/download_dataset.py [--ebook 1342 --ebook 11]

Safe to re-run: files whose bytes still match their recorded SHA-256 are not requested again.
"""

import argparse
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "backend"))

from app.services.datasets import (  # noqa: E402
    build_transformed_workload,
    download_catalog,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ebook", type=int, action="append", help="Limit to these ebook ids (default: full catalog)")
    parser.add_argument("--no-workload", action="store_true", help="Skip the documented partial-overlap test files")
    args = parser.parse_args()

    dataset_dir = PROJECT / "datasets" / "raw"
    manifest = PROJECT / "datasets" / "provenance" / "manifest.json"
    summary = download_catalog(dataset_dir, manifest, ebook_ids=args.ebook)
    print(f"downloaded={summary['downloaded']} already_present={summary['already_present']} failed={len(summary['failed'])}")
    for failure in summary["failed"]:
        print(f"  FAILED {failure['url']}: {failure['error']}")
    if not args.no_workload and not summary["failed"] and (args.ebook is None or 1342 in args.ebook):
        for record in build_transformed_workload(dataset_dir, manifest):
            print(f"workload {record['local_path']}: {record['size_bytes']} bytes. {record['transformations']}")
    print(f"provenance: {manifest}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

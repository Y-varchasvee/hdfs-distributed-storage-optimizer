#!/usr/bin/env python3
"""Check the exported report PDF: required sections, source files, figures, references and stray output.

Usage: backend/.venv/bin/python scripts/audit_report.py [--render DIR]
With --render, also writes a contact sheet of the non-code pages for visual inspection.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import fitz

PROJECT = Path(__file__).resolve().parent.parent
PDF = PROJECT / "reports" / "final" / "HDFS_Storage_Optimizer_Complete_Report.pdf"

REQUIRED = [
    "Certificate", "Declaration of Originality", "Acknowledgements", "Abstract", "Keywords", "Table of Contents",
    "List of Figures", "List of Tables", "Abbreviations",
    "Chapter 1 — Introduction", "Chapter 2 — Problem Statement", "Chapter 3 — Objectives", "Chapter 4 — Literature Review",
    "Chapter 5 — Dataset Description", "Chapter 6 — Dataset Source", "Chapter 7 — Tools and Technologies",
    "Chapter 8 — System Requirements", "Chapter 9 — System Architecture", "Chapter 10 — Implementation and Methodology",
    "Chapter 11 — Complete Source Code", "Chapter 12 — Execution Screenshots", "Chapter 13 — Output and Result Screenshots",
    "Chapter 14 — Result Analysis", "Chapter 15 — Limitations", "Chapter 16 — Future Scope", "Chapter 17 — Conclusion",
    "References", "Appendix A", "Appendix B", "Appendix C", "Appendix D", "Appendix E", "Appendix F", "Appendix G", "Appendix H",
]
FORBIDDEN = [r"\bTODO\b", r"\bFIXME\b", r"lorem ipsum", r"\bNaN\b", r"\bundefined\b(?! when| metrics)", r"#let "]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render", type=Path)
    args = parser.parse_args()

    document = fitz.open(PDF)
    pages = [page.get_text() for page in document]
    text = "\n".join(pages)
    normalized = re.sub(r"\s+", " ", text)
    failures: list[str] = []

    print(f"pages: {len(pages)}, size: {PDF.stat().st_size / 1e6:.1f} MB")
    for section in REQUIRED:
        if section not in normalized:
            failures.append(f"missing section: {section}")

    groups = json.loads((PROJECT / "reports/source/generated/code_files.json").read_text())
    files = [f for group in groups for f in group["files"]]
    for file in files:
        if file["path"] not in normalized:
            failures.append(f"source file heading not found: {file['path']}")
    # Listings are complete if distinctive last lines of each file appear in the PDF.
    squeezed = re.sub(r"\s+", "", text)
    for file in files:
        lines = [line.strip() for line in (PROJECT / file["path"]).read_text().splitlines() if len(line.strip()) > 12]
        if lines and re.sub(r"\s+", "", lines[-1])[:50] not in squeezed:
            failures.append(f"source listing appears truncated: {file['path']}")
    print(f"source files checked: {len(files)}")

    figure_count = len(set(re.findall(r"Figure (\d+):", normalized)))
    table_count = len(set(re.findall(r"Table (\d+):", normalized)))
    images = sum(len(page.get_images()) for page in document)
    print(f"figures: {figure_count}, tables: {table_count}, embedded images: {images}")

    for pattern in FORBIDDEN:
        hits = [i + 1 for i, page in enumerate(pages) if re.search(pattern, page, flags=re.IGNORECASE) and not _is_code_page(page, files)]
        if hits:
            failures.append(f"pattern {pattern!r} on non-code pages {hits[:10]}")

    outside = []
    for number, page in enumerate(document, start=1):
        rect = page.rect
        for block in page.get_text("blocks"):
            if block[2] > rect.width + 1 or block[3] > rect.height + 1 or block[0] < -1:
                outside.append(number)
                break
    if outside:
        failures.append(f"text outside the page on pages {outside[:20]}")

    unnumbered = [i + 1 for i, page in enumerate(pages) if i > 4 and not re.search(r"(^|\n)\s*([ivxlc]+|\d+)\s*\n?\s*$", page)]
    print(f"pages without a trailing page number: {len(unnumbered)} {unnumbered[:10]}")

    blank = [i + 1 for i, page in enumerate(document) if len(pages[i].strip()) < 15 and not page.get_images()]
    if blank:
        failures.append(f"blank pages: {blank}")

    if args.render:
        args.render.mkdir(parents=True, exist_ok=True)
        code_start = next(i for i, page in enumerate(pages) if "Complete Source Code" in page and "This chapter contains" in page)
        code_end = next(i for i, page in enumerate(pages) if "Execution Screenshots" in page and "Every image in this chapter" in page)
        print(f"code pages: {code_start + 1} to {code_end}")
        contact_sheets(document, [i for i in range(len(pages)) if i < code_start + 2 or i >= code_end - 1], args.render)

    for failure in failures:
        print("FAIL", failure)
    print("result:", "PASS" if not failures else f"{len(failures)} problem(s)")
    return 1 if failures else 0


def _is_code_page(page_text: str, files: list[dict]) -> bool:
    return any(file["path"] in page_text for file in files) or "import " in page_text or "def " in page_text or "=>" in page_text


def contact_sheets(document, indexes: list[int], out: Path, per_sheet: int = 12, scale: float = 0.62) -> None:
    columns = 4
    for sheet, start in enumerate(range(0, len(indexes), per_sheet)):
        chunk = indexes[start : start + per_sheet]
        width = 595 * scale
        height = 842 * scale
        rows = (len(chunk) + columns - 1) // columns
        canvas = fitz.open()
        page = canvas.new_page(width=width * columns, height=height * rows)
        for position, index in enumerate(chunk):
            x = (position % columns) * width
            y = (position // columns) * height
            page.show_pdf_page(fitz.Rect(x + 3, y + 3, x + width - 3, y + height - 3), document, index)
        page.get_pixmap(dpi=110).save(out / f"sheet_{sheet:02d}.png")
        print(f"sheet_{sheet:02d}.png: pages {chunk[0] + 1} to {chunk[-1] + 1}")


if __name__ == "__main__":
    sys.exit(main())

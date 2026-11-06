#!/usr/bin/env python3
"""Crop real screenshots to the region a slide discusses, so that their text is readable when projected.

Cropping only: no pixel is altered. Regions are in screenshot pixels (left, top, right, bottom).
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "crops"

CROPS = {
    "dashboard": ("01_dashboard", (464, 180, 2820, 1490)),
    "upload": ("02_file_upload", (464, 195, 2820, 1170)),
    "file_details": ("16a_file_details_verified", (2115, 0, 2880, 1110)),
    "duplicates": ("04_duplicate_analysis", (464, 190, 2820, 1390)),
    "shared_chunks": ("04b_shared_chunks", (464, 665, 2820, 1650)),
    "optimization": ("06_optimization_complete", (590, 1430, 2800, 2170)),
    "replication": ("08_replication_management", (464, 235, 2820, 1560)),
    "cluster": ("09_cluster_status", (464, 195, 2820, 1350)),
    "provenance": ("17_dataset_provenance", (464, 530, 2820, 1980)),
    "namenode_datanodes": ("11_datanode_status", (150, 0, 2800, 1790)),
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, (source, box) in CROPS.items():
        with Image.open(ROOT / "screenshots" / f"{source}.png") as image:
            right, bottom = min(box[2], image.width), min(box[3], image.height)
            image.convert("RGB").crop((box[0], box[1], right, bottom)).save(OUT / f"{name}.png", optimize=True)
            print(name, image.size, "->", (right - box[0], bottom - box[1]))


if __name__ == "__main__":
    main()

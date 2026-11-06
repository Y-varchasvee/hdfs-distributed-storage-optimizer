#!/usr/bin/env python3
"""Generate the architecture diagrams as SVG files in diagrams/.

Each diagram describes the implemented system: module, table and path names match the source code.
A box refuses to render text that would not fit, so overflow fails the build rather than the page.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "diagrams"

INK = "#0b0b0b"
MUTED = "#52514e"
LINE = "#6f6d67"
NEUTRAL = ("#f7f7f4", "#c3c2b7")
HDFS = ("#e4effc", "#2a78d6")
META = ("#fdeee6", "#eb6834")
ACCENT = ("#2a78d6", "#2a78d6")
GOOD = ("#e3f5ec", "#1baf7a")
FONT = "Helvetica Neue, Helvetica, Arial, sans-serif"
MONO = "Menlo, Consolas, monospace"
CHAR = 0.53  # approximate glyph width as a fraction of font size


def text_width(value: str, size: float) -> float:
    return len(value) * size * CHAR


class Diagram:
    def __init__(self, name: str, width: int, height: int):
        self.name, self.width, self.height = name, width, height
        self.parts: list[str] = []

    def text(self, x, y, value, *, size=12, weight="normal", anchor="middle", color=INK, mono=False, halo=False):
        family = MONO if mono else FONT
        outline = ' paint-order="stroke" stroke="#ffffff" stroke-width="4" stroke-linejoin="round"' if halo else ""
        self.parts.append(
            f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'text-anchor="{anchor}" fill="{color}"{outline}>{escape(value)}</text>'
        )

    def box(self, x, y, w, h, title, lines=(), *, style=NEUTRAL, title_size=12.5, line_size=10.5, rx=6, title_color=INK, mono_lines=False):
        fill, stroke = style
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
        rows = [title] if isinstance(title, str) else list(title)
        total = len(rows) * (title_size + 3) + len(lines) * (line_size + 3.5)
        cursor = y + (h - total) / 2 + title_size
        for row in rows:
            self._fit(row, title_size, w, "title")
            self.text(x + w / 2, cursor, row, size=title_size, weight="600", color=title_color)
            cursor += title_size + 3
        for line in lines:
            self._fit(line, line_size * (1.1 if mono_lines else 1), w, "line")
            self.text(x + w / 2, cursor + 1, line, size=line_size, color=MUTED if style is not ACCENT else "#ffffff", mono=mono_lines)
            cursor += line_size + 3.5
        return (x, y, w, h)

    def _fit(self, value, size, width, kind):
        if text_width(value, size) > width - 8:
            raise ValueError(f"{self.name}: {kind} {value!r} does not fit in a box {width} wide")

    def group(self, x, y, w, h, label, *, style=NEUTRAL):
        fill, stroke = style
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="none" stroke="{stroke}" stroke-width="1" stroke-dasharray="5 4"/>')
        self.text(x + 10, y + 16, label, size=11, weight="600", anchor="start", color=MUTED)
        _ = fill

    def arrow(self, points, label=None, *, dashed=False, color=LINE, label_at=None, label_anchor="middle", both=False):
        path = " ".join(f"{px},{py}" for px, py in points)
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        start = ' marker-start="url(#arrow-start)"' if both else ""
        self.parts.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="1.3"{dash} marker-end="url(#arrow)"{start}/>')
        if label:
            (x1, y1), (x2, y2) = points[0], points[1]
            lx, ly = label_at or ((x1 + x2) / 2, (y1 + y2) / 2 - 5)
            self.text(lx, ly, label, size=10, color=MUTED, anchor=label_anchor, halo=True)

    def diamond(self, cx, cy, w, h, lines, style=NEUTRAL):
        fill, stroke = style
        pts = f"{cx},{cy - h / 2} {cx + w / 2},{cy} {cx},{cy + h / 2} {cx - w / 2},{cy}"
        self.parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
        top = cy - (len(lines) - 1) * 7 + 4
        for index, line in enumerate(lines):
            if text_width(line, 11) > w * 0.72:
                raise ValueError(f"{self.name}: decision text {line!r} does not fit")
            self.text(cx, top + index * 14, line, size=11, weight="600")

    def write(self):
        OUT.mkdir(exist_ok=True)
        defs = (
            '<defs>'
            f'<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="{LINE}"/></marker>'
            f'<marker id="arrow-start" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M10 0L0 5L10 10z" fill="{LINE}"/></marker>'
            '</defs>'
        )
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" width="{self.width}" height="{self.height}">{defs}<rect width="100%" height="100%" fill="#ffffff"/>{"".join(self.parts)}</svg>\n'
        (OUT / f"{self.name}.svg").write_text(svg)


def system_architecture():
    d = Diagram("01_system_architecture", 900, 620)
    d.box(40, 20, 820, 54, "Browser: Next.js + React + TanStack Query", ["10 pages · upload progress via XMLHttpRequest · charts from backend data"])
    d.arrow([(450, 74), (450, 104)], "REST /api/v1 (JSON, multipart, streamed download)", label_at=(460, 93), label_anchor="start", both=True)
    d.box(40, 104, 820, 42, "FastAPI: files · dedup · system routers", ["Validation, pagination, error mapping, CORS, optional X-API-Key"])
    d.arrow([(450, 146), (450, 170)])
    d.group(40, 170, 820, 232, "Services (backend/app/services)")
    row1 = [("ingest", "Hash, look up, store new"), ("content_store", "Staged CAS, manifests"), ("optimizer", "Dry run, safe conversion"), ("lifecycle", "Delete, GC, recovery")]
    row2 = [("integrity", "SHA-256 verification"), ("replication", "Set and verify factor"), ("monitor", "NameNode JMX, fsck"), ("analytics", "Derived and measured")]
    row3 = [("jobs", "Background job runner"), ("datasets", "Provenance, workloads"), ("experiments", "Isolated measured runs"), ("audit", "Append-only events")]
    for row_index, row in enumerate((row1, row2, row3)):
        for col, (title, line) in enumerate(row):
            d.box(56 + col * 200, 194 + row_index * 68, 188, 58, title, [line])
    d.arrow([(240, 402), (240, 440)], "SQLAlchemy", label_at=(248, 424), label_anchor="start", both=True)
    d.box(60, 440, 360, 62, "SQLite metadata database (WAL)", ["Files, objects, chunks, manifests, jobs, integrity, audit"], style=META)
    d.arrow([(660, 402), (660, 440)], "WebHdfsClient", label_at=(668, 424), label_anchor="start", both=True)
    d.box(480, 440, 360, 62, "WebHDFS REST (NameNode :9870, DataNode :9864)", ["Two-step create, open, rename, delete, setreplication"], style=HDFS, title_size=11.5)
    d.arrow([(660, 502), (660, 536)])
    d.box(420, 536, 440, 62, "Apache Hadoop 3.5.0 HDFS in Docker", ["1 NameNode + 3 DataNodes · replication factor 3 · persistent volumes"], style=HDFS)
    d.box(40, 536, 340, 62, "Authentic dataset (local)", ["Project Gutenberg files + provenance manifest"])
    d.write()


def hdfs_cluster():
    d = Diagram("02_hdfs_cluster", 900, 470)
    d.box(40, 170, 170, 80, "HDFS Optimizer", ["backend on host", "WebHDFS client"])
    d.group(250, 20, 620, 430, "Colima VM · Docker Compose network")
    d.box(430, 50, 260, 92, "NameNode (hostname: namenode)", ["Namespace and block map in memory", "RPC :8020 · HTTP :9870 (published)", "fsimage + edits on volume namenode-data"], style=HDFS, title_size=11.5)
    for index in range(3):
        x = 270 + index * 200
        d.box(x, 270, 180, 118, f"DataNode {index + 1} (datanode{index + 1})", ["HTTP :9864, published", f"on host port 1986{4 + index}", f"volume datanode{index + 1}-data", "Blocks + .meta checksums"], style=HDFS, title_size=11)
        d.arrow([(x + 90, 270), (x + 90 if index == 1 else 560 + (index - 1) * 60, 142)], None, dashed=True)
    d.text(758, 170, "Heartbeat every 3 s", size=10, color=MUTED, anchor="start")
    d.text(758, 184, "and block reports", size=10, color=MUTED, anchor="start")
    d.arrow([(210, 190), (430, 96)], "1. metadata, then 307 redirect", label_at=(305, 118))
    d.arrow([(210, 230), (270, 310)], "2. read / write bytes", label_at=(150, 288))
    d.arrow([(450, 345), (470, 345)], both=True)
    d.arrow([(650, 345), (670, 345)], both=True)
    d.text(560, 415, "Write pipeline: each block is copied to 3 DataNodes (dfs.replication = 3)", size=11, color=MUTED)
    d.text(560, 432, "Light profile: docker-compose.light.yml runs 2 DataNodes with factor 2", size=10.5, color=MUTED)
    d.write()


def upload_pipeline():
    d = Diagram("03_upload_pipeline", 900, 440)
    steps = [
        ("Receive", ["multipart upload", "validate name, folder"]),
        ("Spool + hash", ["streamed to disk", "SHA-256, size"]),
        ("Look up", ["objects, manifests", "by content hash"]),
    ]
    for i, (title, lines) in enumerate(steps):
        d.box(30 + i * 215, 30, 185, 76, title, lines)
        if i < 2:
            d.arrow([(215 + i * 215, 68), (245 + i * 215, 68)])
    d.arrow([(645, 68), (675, 68)])
    d.diamond(770, 68, 190, 92, ["Content", "already stored?"])
    d.arrow([(865, 68), (865, 180)], "yes", label_at=(855, 150), label_anchor="end")
    d.box(660, 180, 220, 76, "Reference only", ["Check it exists in HDFS", "Repair from upload if missing"], style=GOOD)
    d.arrow([(770, 114), (770, 150), (130, 150), (130, 180)], "no: write new bytes", label_at=(450, 143))
    labels = [
        ("1. Stage", ["CREATE", "/staging/<uuid>"]),
        ("2. Check", ["length and", "SHA-256 read-back"]),
        ("3. Publish", ["atomic RENAME to", "/objects/ab/cd/<sha>"]),
    ]
    for i, (title, lines) in enumerate(labels):
        d.box(30 + i * 190, 180, 165, 76, title, lines, style=HDFS)
        if i < 2:
            d.arrow([(195 + i * 190, 218), (220 + i * 190, 218)])
    d.arrow([(112 + 380, 256), (112 + 380, 320), (360, 320)])
    d.arrow([(770, 256), (770, 346), (560, 346)])
    d.box(160, 300, 400, 76, "4. Commit metadata in one SQLite transaction", ["LogicalFile row, object or manifest pointer", "Audit event, performance samples, storage snapshot"], style=META)
    d.text(450, 412, "Crash before step 4: only an unreferenced HDFS file remains, which reconciliation can find. Metadata never points at missing bytes.", size=11, color=MUTED)
    d.write()


def dedup_pipeline():
    d = Diagram("04_dedup_decision", 900, 500)
    d.box(350, 16, 200, 44, "Upload with SHA-256 = h")
    d.arrow([(450, 60), (450, 80)])
    d.diamond(450, 124, 200, 88, ["Mode =", "raw?"])
    d.arrow([(550, 124), (720, 124), (720, 170)], "yes", label_at=(620, 117))
    d.box(620, 170, 200, 62, "Store private copy", ["/raw/ab/<file id>", "Baseline: no dedup"])
    d.arrow([(450, 168), (450, 200)], "no", label_at=(460, 188), label_anchor="start")
    d.diamond(450, 244, 230, 88, ["Active form of h", "already stored?"])
    d.arrow([(335, 244), (170, 244), (170, 290)], "yes", label_at=(250, 237))
    d.box(50, 290, 240, 76, "Add a reference", ["New LogicalFile points at the", "existing object or manifest", "0 bytes written"], style=GOOD)
    d.arrow([(450, 288), (450, 320)], "no", label_at=(460, 308), label_anchor="start")
    d.diamond(450, 362, 180, 80, ["Mode?"])
    d.arrow([(360, 362), (325, 362), (325, 420)], "file", label_at=(344, 355))
    d.box(205, 420, 240, 62, "Store one object", ["/objects/ab/cd/<h>"], style=HDFS)
    d.arrow([(540, 362), (590, 362), (590, 420)], "chunk", label_at=(565, 355))
    d.box(470, 420, 400, 62, "Split at fixed size, hash each chunk", ["Store only unseen chunks, then a JSON manifest"], style=HDFS)
    d.write()


def chunk_model():
    d = Diagram("05_chunk_storage_model", 900, 400)
    d.text(90, 30, "Logical files", size=12, weight="600", color=MUTED)
    d.text(350, 30, "Manifests (ordered chunk lists)", size=12, weight="600", color=MUTED)
    d.text(730, 30, "Unique chunks in HDFS", size=12, weight="600", color=MUTED)
    d.box(20, 50, 150, 44, "pride.txt")
    d.box(20, 110, 150, 44, "pride-copy.txt")
    d.box(20, 240, 150, 44, "pride-edited.txt")
    colors = ["c1", "c2", "c3", "c4"]
    cell = 56
    def strip(y, labels, height=44):
        d.box(220, y, 300, height + 24, "", ())
        for i, label in enumerate(labels):
            style = META if label == "c5" else HDFS
            d.box(232 + i * (cell + 14), y + 14, cell, height - 4, label, style=style, title_size=11, rx=3)
    positions = {"c1": 60, "c2": 124, "c3": 188, "c4": 252, "c5": 316}
    # Links go first, so the boxes sit on top of them.
    for i, label in enumerate(colors):
        d.arrow([(232 + i * (cell + 14) + cell / 2, 100), (640, positions[label] + 25)], dashed=True, color="#b9b8ae")
    for i, label in enumerate(["c1", "c2", "c5", "c4"]):
        d.arrow([(232 + i * (cell + 14) + cell / 2, 260), (640, positions[label] + 25)], dashed=True, color="#b9b8ae")
    strip(68, colors)
    strip(226, ["c1", "c2", "c5", "c4"])
    d.arrow([(170, 72), (220, 95)])
    d.arrow([(170, 132), (220, 108)])
    d.arrow([(170, 262), (220, 260)])
    for label, y in positions.items():
        d.box(640, y, 230, 50, f"/chunks/ab/cd/<sha of {label}>", ["1 HDFS file, replicated separately"], style=META if label == "c5" else HDFS, title_size=10.5, line_size=9.5)
    d.text(370, 340, "Two identical files share one manifest. A file with", size=11, color=MUTED)
    d.text(370, 356, "one changed chunk adds one new chunk (c5).", size=11, color=MUTED)
    d.text(370, 380, "Chunks are application-level files, not HDFS blocks.", size=11, weight="600")
    d.write()


def reconstruction():
    d = Diagram("06_file_reconstruction", 900, 330)
    d.box(30, 40, 170, 70, "GET /files/{id}/download", ["Preflight: content exists"], title_size=11)
    d.arrow([(200, 75), (235, 75)])
    d.box(235, 40, 170, 70, "Load manifest", ["file_chunks in", "ordinal order"], style=META)
    d.arrow([(405, 75), (440, 75)])
    d.box(440, 40, 180, 70, "For each chunk", ["OPEN via WebHDFS", "from a live replica"], style=HDFS)
    d.arrow([(620, 75), (655, 75)])
    d.diamond(740, 75, 170, 92, ["Chunk hash", "correct?"])
    d.arrow([(740, 121), (740, 175)], "no", label_at=(750, 150), label_anchor="start")
    d.box(640, 175, 200, 62, "Abort the response", ["Client sees a failed download"], style=META)
    d.arrow([(740, 29), (740, 20), (530, 20), (530, 40)], "yes: next chunk", label_at=(635, 15))
    d.arrow([(530, 110), (530, 175)], "stream bytes, update hash", label_at=(520, 150), label_anchor="end")
    d.box(400, 175, 200, 62, "Whole-file SHA-256", ["computed while streaming"])
    d.arrow([(400, 206), (330, 206)])
    d.box(120, 175, 210, 62, "Compare with file hash", ["Mismatch aborts; match records", "a restore sample and audit event"], line_size=9.5)
    d.text(450, 280, "Whole-file and raw modes stream one HDFS file through the same final comparison.", size=11, color=MUTED)
    d.text(450, 298, "An HDFS outage is reported as an error, never as a failed integrity check.", size=11, color=MUTED)
    d.write()


def replication_flow():
    d = Diagram("07_replication_workflow", 900, 400)
    d.box(30, 30, 180, 60, "Request factor n", ["POST /cluster/replication"])
    d.arrow([(210, 60), (250, 60)])
    d.diamond(345, 60, 190, 92, ["n ≤ live", "DataNodes?"])
    d.arrow([(345, 106), (345, 156)], "no", label_at=(355, 134), label_anchor="start")
    d.box(250, 156, 190, 54, "Reject: 422", ["Would stay under-replicated"], style=META)
    d.arrow([(440, 60), (480, 60)], "yes", label_at=(458, 52))
    d.diamond(570, 60, 180, 92, ["Lowers", "protection?"])
    d.arrow([(570, 106), (570, 156)], "yes, not confirmed", label_at=(580, 134), label_anchor="start")
    d.box(475, 156, 190, 54, "Reject: 409", ["Ask for explicit confirmation"], style=META)
    d.arrow([(660, 60), (690, 60)], "ok", label_at=(675, 52))
    d.box(690, 30, 180, 60, "Background job", ["SETREPLICATION per file"], style=HDFS)
    d.arrow([(780, 90), (780, 250)])
    d.box(600, 250, 270, 60, "HDFS converges asynchronously", ["Copies new replicas or deletes excess ones"], style=HDFS)
    d.arrow([(600, 280), (530, 280)])
    d.diamond(430, 280, 200, 92, ["fsck and block", "locations = n?"])
    d.arrow([(430, 326), (430, 366), (620, 366), (720, 366), (720, 310)], "no: poll every 3 s; the time limit scales with blocks", label_at=(585, 360))
    d.arrow([(330, 280), (250, 280)], "yes", label_at=(290, 272))
    d.box(30, 250, 220, 60, "Verified", ["Record measured space", "before and after"], style=GOOD)
    d.text(160, 350, "Timeout: recorded as did not converge.", size=11, color=MUTED)
    d.write()


def er_diagram():
    d = Diagram("08_er_diagram", 900, 640)

    def entity(x, y, name, fields, style=NEUTRAL, width=210):
        height = 24 + len(fields) * 15 + 8
        fill, stroke = style
        d.parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="5" fill="#ffffff" stroke="{stroke}" stroke-width="1.2"/>')
        d.parts.append(f'<rect x="{x}" y="{y}" width="{width}" height="22" rx="5" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
        d.text(x + width / 2, y + 15, name, size=11.5, weight="600")
        for i, field in enumerate(fields):
            if text_width(field, 10) > width - 10:
                raise ValueError(f"field {field!r} does not fit")
            d.text(x + 8, y + 36 + i * 15, field, size=10, anchor="start", color=MUTED, mono=True)
        return x, y, width, height

    entity(340, 20, "files", ["id PK", "name, folder (unique if active)", "sha256, size_bytes", "storage_mode, status", "raw_path", "object_id FK", "manifest_id FK", "dataset_source_id FK", "provenance_label"], META, 230)
    entity(40, 40, "objects", ["id PK", "sha256 UNIQUE", "size_bytes, hdfs_path", "state"], HDFS)
    entity(650, 20, "file_manifests", ["id PK", "file_sha256, chunk_size UQ", "chunk_count, manifest_bytes", "hdfs_path, state"], HDFS)
    entity(650, 170, "file_chunks", ["id PK", "manifest_id FK", "chunk_id FK", "ordinal (unique per manifest)", "offset_bytes"], HDFS)
    entity(650, 320, "chunks", ["id PK", "sha256 UNIQUE", "size_bytes, hdfs_path", "state"], HDFS)
    entity(40, 190, "dataset_sources", ["id PK", "title, ebook_id, source_url", "download_url, downloaded_at", "sha256, kind", "derived_from_id FK", "transformation"], NEUTRAL, 230)
    entity(340, 230, "integrity_checks", ["id PK", "file_id FK", "ok, expected, actual sha256", "missing, corrupt, duration_ms"], NEUTRAL, 230)
    entity(340, 360, "deduplication_jobs", ["id PK", "kind, mode, chunk_size", "status, progress", "params, result, error", "resumed_from_id"], NEUTRAL, 230)
    entity(340, 510, "optimization_history", ["id PK", "job_id FK", "before, after (JSON)", "files_processed, duration_ms"], NEUTRAL, 230)
    entity(40, 340, "replication_operations", ["id PK", "previous_factor, requested", "status, files_changed", "space_consumed_before/after"], NEUTRAL, 230)
    entity(40, 470, "audit_events", ["id PK", "occurred_at, event_type", "severity, entity_id", "message, details"], NEUTRAL, 230)
    entity(650, 470, "Other supporting tables", ["storage_snapshots", "performance_samples", "experiment_runs", "app_settings"], NEUTRAL)

    d.arrow([(340, 85), (250, 85)], "0..1", label_at=(295, 78))
    d.arrow([(570, 70), (650, 60)], "0..1", label_at=(610, 58))
    d.arrow([(755, 112), (755, 170)], "1..n", label_at=(765, 145), label_anchor="start")
    d.arrow([(755, 277), (755, 320)], "n..1", label_at=(765, 302), label_anchor="start")
    d.arrow([(340, 150), (270, 195)], "0..1", label_at=(290, 165))
    d.arrow([(455, 187), (455, 230)], "1..n", label_at=(465, 212), label_anchor="start")
    d.arrow([(455, 467), (455, 510)], "1..n", label_at=(465, 492), label_anchor="start")
    d.text(450, 628, "A file's pointer is enforced by a CHECK constraint. Foreign keys to content use ON DELETE RESTRICT. References are counted by query, never stored.", size=10.5, color=MUTED)
    d.write()


def data_flow():
    d = Diagram("09_data_flow", 900, 460)
    d.box(30, 150, 130, 70, "User", ["via browser"])
    d.box(30, 365, 130, 60, "Project Gutenberg", ["mirror"], title_size=11)
    rows = ["P1 Ingest", "P2 Optimize", "P3 Restore and verify", "P4 Delete and GC", "P5 Analytics", "P6 Dataset import"]
    y = {name: 20 + index * 72 for index, name in enumerate(rows)}
    # Flows between processes and the two stores go first, so boxes sit on top of them.
    d1, d2 = (680, 110), (680, 300)
    links = {
        "P1 Ingest": ("both", "both"),
        "P2 Optimize": ("both", "both"),
        "P3 Restore and verify": ("read", "read"),
        "P4 Delete and GC": ("both", "both"),
        "P5 Analytics": ("read", "read"),
        "P6 Dataset import": ("write", None),
    }
    for name, (to_meta, to_hdfs) in links.items():
        start = (450, y[name] + 28)
        if to_meta == "read":
            d.arrow([d1, start])
        elif to_meta:
            d.arrow([start, d1], both=to_meta == "both")
        if to_hdfs == "read":
            d.arrow([d2, start])
        elif to_hdfs:
            d.arrow([start, d2], both=to_hdfs == "both")
    for name in rows:
        d.box(250, y[name], 200, 56, name, rx=28, title_size=11.5)
    d.box(680, 70, 190, 80, "D1 Metadata", ["SQLite: files, content,", "jobs, audit"], style=META)
    d.box(680, 260, 190, 80, "D2 HDFS", ["Objects, chunks,", "manifests, raw copies"], style=HDFS)
    for name, label in (("P1 Ingest", "files"), ("P2 Optimize", "start job"), ("P3 Restore and verify", "download"), ("P4 Delete and GC", "delete"), ("P5 Analytics", "reports")):
        target = y[name] + 28
        d.arrow([(160, 185), (250, target)], label, label_at=(222, 185 + (target - 185) * 0.72 - 3))
    d.arrow([(160, 395), (250, y["P6 Dataset import"] + 28)], "books", label_at=(205, 392))
    d.text(775, 372, "Writes follow a fixed order:", size=10.5, color=MUTED)
    d.text(775, 387, "bytes to D2, then metadata to D1", size=10.5, color=MUTED)
    d.text(775, 412, "P6 records provenance, then", size=10.5, color=MUTED)
    d.text(775, 427, "stores files through P1", size=10.5, color=MUTED)
    d.write()


def sequence():
    d = Diagram("10_sequence_upload", 900, 590)
    actors = [("Browser", 80), ("FastAPI", 250), ("SQLite", 420), ("NameNode", 610), ("DataNode", 810)]
    for name, x in actors:
        style = META if name == "SQLite" else HDFS if "Node" in name else NEUTRAL
        d.box(x - 60, 16, 120, 34, name, style=style)
        d.parts.append(f'<line x1="{x}" y1="50" x2="{x}" y2="552" stroke="#c3c2b7" stroke-width="1"/>')
    steps = [
        (80, 250, "POST /files/upload (multipart)", False),
        (250, 250, "spool to disk, compute SHA-256", False),
        (250, 420, "find active object by hash", False),
        (420, 250, "none found", True),
        (250, 610, "PUT CREATE /staging/<uuid>", False),
        (610, 250, "307 redirect to a DataNode", True),
        (250, 810, "PUT bytes", False),
        (810, 250, "201 after the write pipeline (3 replicas)", True),
        (250, 810, "GET staged bytes, check SHA-256", False),
        (250, 610, "PUT MKDIRS, then RENAME to /objects/ab/cd/<sha>", False),
        (610, 250, "true", True),
        (250, 420, "COMMIT file, object, audit, samples", False),
        (250, 80, "201 stored_new", True),
    ]
    y = 78
    for x1, x2, label, dashed in steps:
        if x1 == x2:
            d.parts.append(f'<rect x="{x1 - 5}" y="{y - 12}" width="10" height="20" fill="#f0efec" stroke="#c3c2b7"/>')
            d.text(x1 + 12, y + 2, label, size=10.5, anchor="start", color=MUTED, halo=True)
        else:
            d.arrow([(x1, y), (x2, y)], None, dashed=dashed)
            middle = (x1 + x2) / 2
            d.text(middle, y - 6, label, size=10.5, color=INK if not dashed else MUTED, halo=True)
        y += 37
    d.text(450, 574, "For a duplicate, the lookup finds an object, HDFS confirms its length, and only the COMMIT step runs: no bytes are written.", size=10.5, color=MUTED)
    d.write()


def main() -> None:
    for build in (system_architecture, hdfs_cluster, upload_pipeline, dedup_pipeline, chunk_model, reconstruction, replication_flow, er_diagram, data_flow, sequence):
        build()
    print(f"wrote {len(list(OUT.glob('*.svg')))} diagrams to {OUT}")


if __name__ == "__main__":
    main()

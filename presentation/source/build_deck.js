#!/usr/bin/env node
/**
 * Builds presentation/final/HDFS_Storage_Optimizer_Presentation.pptx.
 *
 * Text, shapes, diagrams and charts are native and editable. Images are real screenshots from screenshots/.
 * Every figure is read from benchmarks/results or evidence, so the deck cannot disagree with the report.
 */
const fs = require("node:fs");
const path = require("node:path");
const JSZip = require("jszip");
const pptxgen = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "../..");
const OUT = path.join(ROOT, "presentation/final/HDFS_Storage_Optimizer_Presentation.pptx");
const CROPS = path.join(__dirname, "crops");

const results = (name) => JSON.parse(fs.readFileSync(path.join(ROOT, "benchmarks/results", `${name}.json`), "utf8"));
const MIB = 1048576;
const mib = (b, d = 0) => `${(b / MIB).toFixed(d)} MiB`;
const A = results("A_unique_files").rows;
const B = results("B_exact_duplicates").rows;
const C_many = results("C_many_names").rows[0];
const D = results("D_chunk_sizes").rows;
const D2 = results("D2_boundary_shift").rows;
const E = results("E_roundtrip").rows;
const H = results("H_replication").rows;
const I = results("I_before_after").rows;
const J = results("J_failure_handling");
const provenance = JSON.parse(fs.readFileSync(path.join(ROOT, "datasets/provenance/manifest.json"), "utf8"));
const originals = provenance.files.filter((f) => f.kind === "original");
const counts = JSON.parse(fs.readFileSync(path.join(ROOT, "reports/source/generated/test_counts.json"), "utf8"));

const THEME = {
  name: "HDFS Optimizer",
  headFontFace: "Arial",
  bodyFontFace: "Arial",
  colors: {
    dk1: "0B0B0B", lt1: "FFFFFF", dk2: "12161D", lt2: "F0EFEC",
    accent1: "2A78D6", accent2: "EB6834", accent3: "1BAF7A", accent4: "B7D3F6", accent5: "52514E", accent6: "898781",
    hlink: "1C5CAB", folHlink: "52514E",
  },
};
const HEX = { grid: "E1E0D9", label: "52514E" };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "HDFS Optimizer";
pres.subject = "HDFS-Based Distributed File Replication, Deduplication and Storage Optimization System";
const C = pres.SchemeColor;

pres.defineSlideMaster({
  title: "TITLE_ONLY",
  background: { color: C.background1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.38, w: 12.13, h: 1.0, fontSize: 30, bold: true, color: C.text1, align: "left", valign: "top", margin: 0 }, text: "Slide title" } },
    { text: { text: "HDFS Optimizer", options: { x: 0.6, y: 7.05, w: 4, h: 0.25, fontSize: 10, color: C.accent6, margin: 0 } } },
  ],
  slideNumber: { x: 12.23, y: 7.05, w: 0.5, h: 0.25, fontSize: 10, color: C.accent6, align: "right" },
});
pres.defineSlideMaster({
  title: "DARK",
  background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 1.5, w: 7.3, h: 2.2, fontSize: 44, bold: true, color: C.background1, align: "left", valign: "top", margin: 0 }, text: "Title" } },
    { placeholder: { options: { name: "body", type: "body", x: 0.8, y: 3.85, w: 7.3, h: 1.1, fontSize: 18, color: C.accent4, align: "left", valign: "top", margin: 0 }, text: "Subtitle" } },
  ],
});

// -- composition helpers ------------------------------------------------------------------------------

function pngSize(file) {
  const data = fs.readFileSync(file);
  return { w: data.readUInt32BE(16), h: data.readUInt32BE(20) };
}

/** Place a real screenshot (cropped, never altered) at a given width, keeping its proportions. Returns its height. */
function screenshot(slide, name, x, y, w, alt) {
  const file = path.join(CROPS, `${name}.png`);
  const size = pngSize(file);
  const h = (size.h / size.w) * w;
  slide.addShape(pres.ShapeType.rect, { x: x - 0.02, y: y - 0.02, w: w + 0.04, h: h + 0.04, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: `${name} frame` });
  slide.addImage({ path: file, x, y, w, h, altText: alt, objectName: name });
  return h;
}

function text(slide, value, x, y, w, h, options = {}) {
  slide.addText(value, { x, y, w, h, margin: 0, isTextBox: true, fontSize: 14, color: C.text1, valign: "top", ...options });
}

function box(slide, label, x, y, w, h, { fill = C.background2, color = C.text1, size = 13, bold = true, line, sub } = {}) {
  const runs = sub
    ? [{ text: label, options: { bold, fontSize: size, color, breakLine: true } }, { text: sub, options: { fontSize: Math.max(size - 2, 10), color, bold: false } }]
    : [{ text: label, options: { bold, fontSize: size, color } }];
  slide.addText(runs, { shape: pres.ShapeType.roundRect, rectRadius: 0.05, x, y, w, h, fill: { color: fill }, line: { color: line ?? fill, width: 1 }, align: "center", valign: "middle", margin: 4, objectName: label });
}

function arrow(slide, x1, y1, x2, y2, color = C.accent6) {
  const flipH = x2 < x1;
  const flipV = y2 < y1;
  slide.addShape(pres.ShapeType.line, { x: Math.min(x1, x2), y: Math.min(y1, y2), w: Math.abs(x2 - x1), h: Math.abs(y2 - y1), flipH, flipV, line: { color, width: 1.5, endArrowType: "triangle" }, objectName: "arrow" });
}

function stat(slide, value, label, x, y, w, { size = 40, color = C.text1, labelColor = C.accent5 } = {}) {
  text(slide, value, x, y, w, 0.8, { fontSize: size, bold: true, color, valign: "bottom" });
  text(slide, label, x, y + 0.86, w, 0.8, { fontSize: 14, color: labelColor });
}

/** The deck's motif, which is also the product's main figure: one whole, split into kept and avoided bytes. */
function segmentBar(slide, x, y, w, kept, { h = 0.34, keptLabel, avoidedLabel, keptColor = C.accent1, avoidedColor = C.accent4 } = {}) {
  const keptW = w * kept;
  slide.addText(keptLabel ?? "", { shape: pres.ShapeType.roundRect, rectRadius: 0.04, x, y, w: keptW - 0.02, h, fill: { color: keptColor }, line: { color: keptColor }, fontSize: 12, color: C.background1, bold: true, margin: 4, align: "left", valign: "middle", objectName: "stored segment" });
  if (kept < 1) {
    slide.addText(avoidedLabel ?? "", { shape: pres.ShapeType.roundRect, rectRadius: 0.04, x: x + keptW + 0.02, y, w: w - keptW - 0.02, h, fill: { color: avoidedColor }, line: { color: avoidedColor }, fontSize: 12, color: C.text1, bold: true, margin: 4, align: "left", valign: "middle", objectName: "avoided segment" });
  }
}

const newSlide = (title, sectionTitle, notes) => {
  const slide = pres.addSlide({ masterName: "TITLE_ONLY", sectionTitle });
  slide.addText(title, { placeholder: "title" });
  if (notes) slide.addNotes(notes);
  return slide;
};

const chartOptions = (extra) => ({
  showLegend: false,
  catAxisLabelColor: HEX.label,
  valAxisLabelColor: HEX.label,
  catAxisLabelFontSize: 12,
  valAxisLabelFontSize: 12,
  dataLabelColor: HEX.label,
  dataLabelFontSize: 12,
  legendFontSize: 12,
  legendColor: HEX.label,
  catAxisLabelFontFace: "+mn-lt",
  valAxisLabelFontFace: "+mn-lt",
  dataLabelFontFace: "+mn-lt",
  legendFontFace: "+mn-lt",
  titleFontFace: "+mn-lt",
  titleColor: "0B0B0B",
  titleFontSize: 14,
  valGridLine: { color: HEX.grid, size: 0.75 },
  catGridLine: { style: "none" },
  showValue: true,
  dataLabelPosition: "outEnd",
  ...extra,
});

// -- slides ---------------------------------------------------------------------------------------------

// 1. Title
pres.addSection({ title: "Introduction" });
{
  const slide = pres.addSlide({ masterName: "DARK", sectionTitle: "Introduction" });
  slide.addText("HDFS Optimizer", { placeholder: "title" });
  slide.addText("Store it once. Replicate it safely. Prove every byte.", { placeholder: "body" });
  text(slide, "HDFS-Based Distributed File Replication, Deduplication and Storage Optimization System", 0.8, 3.0, 7.0, 0.7, { fontSize: 15, color: C.background2 });
  text(slide, "[Student name]  ·  [Roll number]  ·  [Department]  ·  [University]\nGuide: [Supervisor]  ·  Session: [Academic session]", 0.8, 5.9, 7.3, 0.7, { fontSize: 13, color: C.accent6 });
  // Hero: many logical files resolving to one stored object, drawn with native shapes.
  const rows = [1.4, 2.25, 3.1, 3.95, 4.8];
  ["report.pdf", "report-final.pdf", "report (1).pdf", "copy of report.pdf", "backup.pdf"].forEach((name, index) => {
    const y = rows[index];
    slide.addText(name, { shape: pres.ShapeType.roundRect, rectRadius: 0.05, x: 8.45, y, w: 1.75, h: 0.5, fill: { color: "232A35" }, line: { color: "3A4453", width: 1 }, color: C.accent4, fontSize: 11, align: "center", valign: "middle", margin: 2, objectName: `logical file ${index + 1}` });
    arrow(slide, 10.2, y + 0.25, 11.05, 3.35, "5B6677");
  });
  slide.addText("One stored copy", { shape: pres.ShapeType.roundRect, rectRadius: 0.08, x: 11.05, y: 2.75, w: 1.5, h: 1.2, fill: { color: C.accent1 }, line: { color: C.accent1 }, color: C.background1, fontSize: 13, bold: true, align: "center", valign: "middle", margin: 4, objectName: "one stored object" });
  slide.addNotes("Introduce the project in one sentence: an application layer over real, unmodified Apache Hadoop that stores identical content once, leaves HDFS replication alone, and proves every restored file is byte-identical. Replace the bracketed placeholders with your details before presenting.");
}

// 2. Problem
{
  const slide = newSlide("HDFS protects blocks, but it cannot see duplicate files", "Introduction", "HDFS copies each block for fault tolerance. That is deliberate. But when the same book is uploaded three times, HDFS treats those as three unrelated files, and replicates each one. This drawing shows what plain HDFS stores for three identical uploads at replication factor 3: nine block copies. Only three are needed for the same fault tolerance.");
  const cell = 0.46;
  const gap = 0.08;
  text(slide, "Plain HDFS: three uploads of one book", 0.6, 1.6, 6, 0.35, { fontSize: 16, bold: true });
  ["report.pdf", "report-final.pdf", "copy of report.pdf"].forEach((name, row) => {
    const y = 2.15 + row * 0.82;
    text(slide, name, 0.6, y + 0.08, 2.1, 0.35, { fontSize: 14, color: C.accent5 });
    [0, 1, 2].forEach((col) => slide.addShape(pres.ShapeType.roundRect, { x: 2.8 + col * (cell + gap), y, w: cell, h: cell, rectRadius: 0.04, fill: { color: row === 0 ? C.accent1 : C.accent2 }, line: { color: row === 0 ? C.accent1 : C.accent2 }, objectName: `replica ${row}-${col}` }));
  });
  text(slide, "9 block copies stored", 2.8, 4.7, 3.5, 0.4, { fontSize: 18, bold: true });
  text(slide, "With HDFS Optimizer", 7.4, 1.6, 5, 0.35, { fontSize: 16, bold: true });
  ["report.pdf", "report-final.pdf", "copy of report.pdf"].forEach((name, row) => {
    const y = 2.15 + row * 0.82;
    text(slide, name, 7.4, y + 0.08, 2.1, 0.35, { fontSize: 14, color: C.accent5 });
    arrow(slide, 9.45, y + 0.23, 10.15, 2.97);
  });
  [0, 1, 2].forEach((col) => slide.addShape(pres.ShapeType.roundRect, { x: 10.2 + col * (cell + gap), y: 2.75, w: cell, h: cell, rectRadius: 0.04, fill: { color: C.accent1 }, line: { color: C.accent1 }, objectName: `kept replica ${col}` }));
  text(slide, "3 block copies, same fault tolerance", 7.4, 4.7, 5.3, 0.4, { fontSize: 18, bold: true });
  text(slide, "Each square is one replica of one block. Blue copies provide safety. Orange copies come only from duplicate uploads.", 0.6, 5.55, 12, 0.6, { fontSize: 14, color: C.accent5 });
}

// 3. Why it matters
{
  const raw = B.find((r) => r.copies === 5 && r.mode === "raw");
  const dedup = B.find((r) => r.copies === 5 && r.mode === "file");
  const slide = newSlide("Every accidental copy is multiplied by the replication factor", "Introduction", `This is a measured example, not an estimate: nine authentic books with five extra copies each. Without deduplication the NameNode reports ${mib(raw.hdfs_space_consumed_bytes)} consumed; with whole-file deduplication, ${mib(dedup.hdfs_space_consumed_bytes)}. The duplicates were created for the experiment, so this shows the mechanism and does not predict savings on a real system.`);
  stat(slide, mib(raw.hdfs_space_consumed_bytes), "consumed by 9 books with 5 extra copies each, stored as plain uploads", 0.6, 1.75, 3.7, { color: C.accent2 });
  stat(slide, mib(dedup.hdfs_space_consumed_bytes), "for the same logical files, deduplicated, at the same replication factor", 4.8, 1.75, 3.7, { color: C.accent1 });
  stat(slide, "3 ×", "every stored byte is kept on three DataNodes, including accidental copies", 9.0, 1.75, 3.7);
  text(slide, "Why this is hard to fix by hand", 0.6, 4.2, 12, 0.4, { fontSize: 18, bold: true });
  [
    ["No visibility", "HDFS has no view of identical content across files."],
    ["Risky cleanup", "Deleting a \"duplicate\" by hand can remove what someone needs."],
    ["Confusing numbers", "Logical size, stored size and disk use are three different things."],
  ].forEach(([head, body], index) => {
    const x = 0.6 + index * 4.1;
    slide.addShape(pres.ShapeType.roundRect, { x, y: 4.75, w: 3.9, h: 1.7, rectRadius: 0.06, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: `${head} card` });
    text(slide, head, x + 0.2, 4.92, 3.5, 0.35, { fontSize: 16, bold: true });
    text(slide, body, x + 0.2, 5.32, 3.5, 1.0, { fontSize: 14, color: C.accent5 });
  });
  text(slide, "Measured with authentic files on the test cluster. Duplicates were created for the experiment.", 0.6, 6.6, 12, 0.3, { fontSize: 11, color: C.accent6 });
}

// 4. Solution
{
  const slide = newSlide("A layer above HDFS that stores each distinct content once", "Introduction", "HDFS is not modified at all. The application decides what is written, and HDFS still replicates it. Walk through the six capabilities briefly. The point to stress: each headline number in the interface states whether it is measured, derived or estimated.");
  const items = [
    ["Whole-file deduplication", "SHA-256 identity. Any number of names, one stored object."],
    ["Chunk-level deduplication", "Fixed-size chunks shared across different files."],
    ["Safe optimization", "Dry run first. Each file is verified before its old copy goes."],
    ["Reference-aware deletion", "Recoverable deletes. Shared content stays while it is needed."],
    ["Replication management", "Real factor changes, confirmed with fsck and block locations."],
    ["Honest metrics", "Every headline value says: measured, derived or estimated."],
  ];
  items.forEach(([head, body], index) => {
    const col = index % 3;
    const row = Math.floor(index / 3);
    const x = 0.6 + col * 4.1;
    const y = 1.7 + row * 2.45;
    slide.addShape(pres.ShapeType.roundRect, { x, y, w: 3.9, h: 2.2, rectRadius: 0.06, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: `${head} card` });
    slide.addText(String(index + 1), { shape: pres.ShapeType.ellipse, x: x + 0.2, y: y + 0.2, w: 0.42, h: 0.42, fill: { color: C.accent1 }, line: { color: C.accent1 }, color: C.background1, fontSize: 14, bold: true, align: "center", valign: "middle", margin: 0, objectName: `number ${index + 1}` });
    text(slide, head, x + 0.2, y + 0.75, 3.5, 0.4, { fontSize: 16, bold: true });
    text(slide, body, x + 0.2, y + 1.17, 3.5, 0.9, { fontSize: 14, color: C.accent5 });
  });
}

// 5. Objectives
{
  const slide = newSlide("What the project set out to achieve", "Introduction", "All of these are implemented and tested. Future work, such as content-defined chunking, is kept separate and is on a later slide.");
  const groups = [
    ["Reduce", ["Detect exact duplicates with SHA-256", "Find identical chunks across files", "Store unique data in content-addressed form"]],
    ["Protect", ["Reconstruct originals exactly", "Verify with cryptographic checksums", "Delete safely, and recover"]],
    ["Operate", ["Manage supported replication settings", "Monitor NameNode and DataNode health", "Show storage and savings clearly"]],
    ["Prove", ["Evaluate on authentic datasets", "Compare storage visually", "Document design and results"]],
  ];
  groups.forEach(([head, lines], index) => {
    const x = 0.6 + index * 3.07;
    slide.addShape(pres.ShapeType.roundRect, { x, y: 1.55, w: 2.92, h: 4.05, rectRadius: 0.05, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: `${head} card` });
    text(slide, head, x + 0.2, 1.72, 2.5, 0.55, { fontSize: 24, bold: true, color: "1C5CAB" });
    slide.addText(lines.map((line, i) => ({ text: line, options: { bullet: { indent: 14 }, breakLine: i < lines.length - 1, paraSpaceAfter: 12 } })), { x: x + 0.2, y: 2.38, w: 2.52, h: 3.1, margin: 0, fontSize: 15, color: C.text1, valign: "top", isTextBox: true });
  });
  text(slide, "Keep the redundancy that protects data. Remove the redundancy that only costs space.", 0.6, 5.85, 12.13, 0.8, { fontSize: 18, bold: true });
}

// 6. Technology stack
pres.addSection({ title: "Design" });
{
  const slide = newSlide("A deliberately ordinary, inspectable technology stack", "Design", "Everything here is free and open source. WebHDFS means the Python backend needs no Java client. SQLite keeps setup simple, and its limits are discussed on a later slide. The Hadoop image is built from the official Apache tarball because the official images are amd64-only and this laptop is arm64.");
  const rows = [
    ["Interface", ["Next.js 16", "React 19", "TypeScript", "Tailwind + shadcn/ui", "Recharts"], C.background2, C.text1],
    ["API and logic", ["Python 3.12", "FastAPI", "Pydantic", "HTTPX", "hashlib SHA-256"], C.background2, C.text1],
    ["Metadata", ["SQLite (WAL)", "SQLAlchemy 2", "Alembic migrations"], "FDEEE6", C.text1],
    ["Storage", ["Apache Hadoop 3.5.0", "HDFS", "WebHDFS REST", "JMX and fsck"], C.accent4, C.text1],
    ["Platform and tests", ["Docker Compose", "Colima", "Pytest", "Playwright", "Typst"], C.background2, C.text1],
  ];
  rows.forEach(([label, items, fill, color], index) => {
    const y = 1.65 + index * 1.03;
    text(slide, label, 0.6, y + 0.27, 2.2, 0.4, { fontSize: 15, bold: true });
    const width = (9.9 - (items.length - 1) * 0.12) / items.length;
    items.forEach((item, i) => box(slide, item, 2.83 + i * (width + 0.12), y, width, 0.85, { fill, color, size: 14 }));
  });
}

// 7. Architecture
{
  const slide = newSlide("Bytes reach HDFS first, and metadata commits afterwards", "Design", "HDFS and SQLite cannot share a transaction. So every write has a fixed order: stage in HDFS, check it, rename atomically, then commit metadata. A crash can leave an unreferenced file, which reconciliation finds. It can never leave metadata that points at missing bytes.");
  box(slide, "Browser", 0.6, 3.0, 1.9, 1.2, { sub: "Next.js dashboard" });
  arrow(slide, 2.5, 3.6, 3.1, 3.6);
  box(slide, "REST API", 3.1, 3.0, 1.9, 1.2, { sub: "FastAPI, /api/v1" });
  arrow(slide, 5.0, 3.6, 5.6, 3.6);
  slide.addShape(pres.ShapeType.roundRect, { x: 5.6, y: 1.7, w: 3.3, h: 3.8, rectRadius: 0.05, fill: { color: C.background1 }, line: { color: C.accent6, width: 1, dashType: "dash" }, objectName: "services group" });
  text(slide, "Services", 5.8, 1.82, 2.9, 0.3, { fontSize: 14, bold: true, color: C.accent5 });
  ["Ingest and content store", "Optimizer and lifecycle", "Integrity and replication", "Monitor, analytics, audit"].forEach((label, i) => box(slide, label, 5.8, 2.22 + i * 0.8, 2.9, 0.68, { size: 13 }));
  arrow(slide, 8.9, 2.75, 9.6, 2.45);
  arrow(slide, 8.9, 4.45, 9.6, 4.75);
  box(slide, "SQLite metadata", 9.6, 1.8, 3.13, 1.3, { fill: "FDEEE6", sub: "Files, objects, chunks, manifests, jobs, audit" });
  box(slide, "HDFS through WebHDFS", 9.6, 4.1, 3.13, 1.3, { fill: C.accent4, sub: "1 NameNode, 3 DataNodes, factor 3" });
  text(slide, "Write order:  1 stage in HDFS   2 check bytes   3 rename atomically   4 commit metadata", 0.6, 5.85, 12.1, 0.4, { fontSize: 18, bold: true });
  text(slide, "A crash can leave an unreferenced file, but never metadata pointing at missing bytes.", 0.6, 6.3, 12.1, 0.4, { fontSize: 14, color: C.accent5 });
}

// 8. Cluster
{
  const slide = newSlide("A real HDFS cluster: one NameNode and three DataNodes", "Design", "This is genuine Apache Hadoop 3.5.0, running in containers. The screenshot is Hadoop's own interface. It is honest to say this is all on one laptop: it shows the software's behaviour under failure, but the three DataNodes share one disk, so it gives no real hardware fault tolerance.");
  box(slide, "NameNode", 2.1, 1.75, 3.0, 1.0, { fill: C.accent4, size: 16, sub: "Namespace and block map" });
  ["DataNode 1", "DataNode 2", "DataNode 3"].forEach((name, i) => {
    const x = 0.6 + i * 2.05;
    box(slide, name, x, 3.75, 1.9, 1.0, { fill: C.accent4, size: 14, sub: "Blocks" });
    arrow(slide, x + 0.95, 3.75, 3.6, 2.75);
  });
  text(slide, "Heartbeats every 3 s, and block reports", 0.6, 1.85, 1.35, 0.9, { fontSize: 12, color: C.accent5 });
  text(slide, "Each block is stored on 3 DataNodes. Stopping a DataNode leaves files readable, which we tested for real.", 0.6, 5.0, 6.0, 0.8, { fontSize: 14 });
  text(slide, "Limit: all nodes share one laptop and one disk.", 0.6, 5.85, 6.0, 0.4, { fontSize: 14, color: C.accent5 });
  const shotHeight = screenshot(slide, "namenode_datanodes", 7.0, 1.65, 5.73, "Screenshot of DataNode list in Hadoop's own NameNode web interface");
  text(slide, "Hadoop's own NameNode interface, showing this cluster", 7.0, 1.65 + shotHeight + 0.1, 5.73, 0.35, { fontSize: 12, color: C.accent5 });
}

// 9. Whole-file
{
  const slide = newSlide("Whole-file deduplication: same hash, no new bytes", "Design", "Identity depends only on content. Two different names with the same bytes are duplicates. The same name with different bytes is not: the second file becomes name (1). Lookup is by a unique index on the hash.");
  box(slide, "Upload", 0.6, 2.2, 1.6, 1.0, { size: 15, sub: "Any file name" });
  arrow(slide, 2.2, 2.7, 2.7, 2.7);
  box(slide, "SHA-256", 2.7, 2.2, 1.6, 1.0, { size: 15, sub: "Streamed" });
  arrow(slide, 4.3, 2.7, 4.8, 2.7);
  slide.addText("Hash already stored?", { shape: pres.ShapeType.diamond, x: 4.8, y: 1.75, w: 2.7, h: 1.9, fill: { color: C.background1 }, line: { color: C.accent6, width: 1.2 }, fontSize: 14, bold: true, align: "center", valign: "middle", margin: 16, objectName: "decision" });
  arrow(slide, 7.5, 2.7, 8.5, 2.2);
  text(slide, "Yes", 7.65, 2.1, 0.6, 0.3, { fontSize: 13, bold: true });
  box(slide, "Add a reference", 8.5, 1.65, 4.23, 1.05, { fill: "E3F5EC", size: 15, sub: "New logical file, 0 bytes written" });
  arrow(slide, 7.5, 2.7, 8.5, 3.45);
  text(slide, "No", 7.65, 3.05, 0.6, 0.3, { fontSize: 13, bold: true });
  box(slide, "Stage, check, rename", 8.5, 2.95, 4.23, 1.05, { fill: C.accent4, size: 15, sub: "/objects/ab/cd/<sha256>" });
  const row = C_many;
  stat(slide, `${row.logical_files} names`, "of one authentic file, in a single test", 0.6, 4.35, 3.6);
  stat(slide, `${row.hdfs_file_count} HDFS file`, "stored for all of them", 4.6, 4.35, 3.6, { color: C.accent1 });
  stat(slide, `${row["verification.files_passed"]} of ${row["verification.files_checked"]}`, "names passed SHA-256 verification", 8.6, 4.35, 4.1);
}

// 10. Chunk-level
{
  const slide = newSlide("Chunks find overlap between different files", "Design", "Each file is split at fixed sizes, and each chunk hashed. A manifest lists the chunks in order. Reconstruction reads them in order, checks each hash, and compares the whole file hash at the end. Important: these are application-level chunks, each its own HDFS file. They are not HDFS blocks, which we cannot deduplicate from outside. The right side is a measured result showing the known weakness of fixed-size chunking.");
  const cell = 0.62;
  const draw = (label, y, cells) => {
    text(slide, label, 0.6, y + 0.12, 2.2, 0.4, { fontSize: 14, color: C.accent5 });
    cells.forEach(([name, shared], i) => slide.addText(name, { shape: pres.ShapeType.roundRect, rectRadius: 0.04, x: 2.8 + i * (cell + 0.07), y, w: cell, h: 0.55, fill: { color: shared ? C.accent1 : C.accent2 }, line: { color: shared ? C.accent1 : C.accent2 }, color: C.background1, fontSize: 13, bold: true, align: "center", valign: "middle", margin: 0, objectName: `chunk ${name}` }));
  };
  draw("Original file", 1.85, [["c1", true], ["c2", true], ["c3", true], ["c4", true]]);
  draw("Byte-identical file", 2.55, [["c1", true], ["c2", true], ["c3", true], ["c4", true]]);
  draw("One chunk changed", 3.25, [["c1", true], ["c2", true], ["c5", false], ["c4", true]]);
  text(slide, "Stored once each: c1, c2, c3, c4, c5. A manifest lists each file's chunks in order, and rebuilds it exactly.", 0.6, 4.1, 5.0, 0.95, { fontSize: 14 });
  text(slide, "Chunks are application-level HDFS files, not HDFS blocks.", 0.6, 5.1, 5.0, 0.6, { fontSize: 14, bold: true });
  const variantName = { "pg1342.truncate_90.txt": "Truncated to 90%", "pg1342.replace_mid_byte.txt": "One byte replaced", "pg1342.prefix_newline.txt": "One byte inserted at start" };
  slide.addChart(pres.charts.BAR, [{ name: "Chunks reused (%)", labels: D2.map((r) => variantName[r.variant]), values: D2.map((r) => Number(r.reuse_percent.toFixed(1))) }], {
    x: 6.3, y: 1.6, w: 6.43, h: 4.2, barDir: "bar", chartColors: [THEME.colors.accent1], barGapWidthPct: 80,
    ...chartOptions({ showTitle: true, title: "Measured: chunks reused, 64 KiB chunks (%)", valAxisMaxVal: 100, valAxisMinVal: 0, catAxisOrientation: "maxMin", valAxisHidden: true, valGridLine: { style: "none" }, dataLabelFormatCode: '0.0"%"' }),
  });
  text(slide, "One inserted byte shifts every boundary. Content-defined chunking would fix this; it is future work.", 6.3, 5.9, 6.43, 0.6, { fontSize: 14, color: C.accent5 });
}

// 11. Dashboard
pres.addSection({ title: "Product" });
{
  const slide = newSlide("The dashboard says how every number is known", "Product", "This is a real screenshot of the running system, cropped to the top of the page. Point out the storage reduction figure and bar, then the small labels: Derived values come from metadata, Measured values come from HDFS, and Estimated values are calculations. On an empty system, it shows N/A rather than a fake zero.");
  const w = 8.3;
  screenshot(slide, "dashboard", 0.6, 1.5, w, "Screenshot of HDFS Optimizer dashboard with savings and cluster health");
  const x = 0.6 + w + 0.35;
  const notes = [["Derived", "Exact, from the metadata database. Excludes replication."], ["Measured", "Reported by HDFS at the time shown."], ["Estimated", "A calculation or a prediction, and labelled as one."], ["N/A when undefined", "An empty system never shows a fake zero."]];
  notes.forEach(([head, body], i) => {
    const y = 1.55 + i * 1.18;
    text(slide, head, x, y, 12.73 - x, 0.35, { fontSize: 16, bold: true });
    text(slide, body, x, y + 0.36, 12.73 - x, 0.75, { fontSize: 14, color: C.accent5 });
  });
}

// 12. Files
{
  const slide = newSlide("Upload, browse and inspect files, down to replica locations", "Product", "Left: uploading the same bytes under a new name is reported as a duplicate, and no new data is written. Right: the detail panel shows the hash, the HDFS path, the DataNodes holding replicas and a passed SHA-256 check. Progress bars show the bytes the browser has really sent.");
  screenshot(slide, "upload", 0.6, 1.5, 8.5, "Screenshot of file upload showing a detected duplicate");
  screenshot(slide, "file_details", 9.4, 1.5, 3.33, "Screenshot of a file's details with block replicas and passed verification");
  text(slide, "A renamed copy is reported as a duplicate: no new data stored.", 0.6, 5.55, 8.5, 0.5, { fontSize: 15, bold: true });
  text(slide, "Replicas stay on three DataNodes, and the SHA-256 check passes.", 9.4, 6.4, 3.33, 0.55, { fontSize: 12, bold: true });
}

// 13. Duplicates
{
  const slide = newSlide("Duplicate detection shows how names map to stored bytes", "Product", "This group has one SHA-256 and several logical names. The diagram shows that each copy is still stored separately, in orange, so space can be reclaimed. After optimization the lines converge on one blue box. The tab on the right shows shared chunks: a truncated copy and a one-byte edit share almost everything, and a one-byte insertion at the start shares nothing.");
  screenshot(slide, "duplicates", 0.6, 1.5, 6.25, "Screenshot of duplicate groups and the relationship diagram");
  screenshot(slide, "shared_chunks", 7.05, 1.5, 5.68, "Screenshot of chunk map with shared chunks");
  text(slide, "Exact duplicates", 0.6, 4.85, 6.25, 0.35, { fontSize: 16, bold: true });
  text(slide, "Same SHA-256, different names. In orange, each copy is still stored separately, so its space can be reclaimed.", 0.6, 5.22, 6.25, 0.8, { fontSize: 14, color: C.accent5 });
  text(slide, "Shared chunks", 7.05, 4.85, 5.68, 0.35, { fontSize: 16, bold: true });
  text(slide, "Blue marks are shared with another file. Truncating or editing one byte shares almost everything. Inserting one byte at the start shares nothing.", 7.05, 5.22, 5.68, 1.1, { fontSize: 14, color: C.accent5 });
}

// 14. Optimization
{
  const file = I.find((r) => r.mode === "file");
  const chunk = I.find((r) => r.mode === "chunk");
  const slide = newSlide("Optimization reclaimed the copies and kept every byte", "Product", `Both runs started from ${file.files} files stored without deduplication: nine books with two exact copies each. Each is measured by the NameNode and includes replication. All ${file["verification.files_passed"]} files then passed SHA-256 verification. Chunk mode uses slightly more space than whole-file, because of its manifests. The chart and figures are from the repeated benchmark. The screenshot is from the demonstration session, which also holds two uploaded files, so its totals differ slightly.`);
  slide.addChart(pres.charts.BAR, [
    { name: "Before", labels: ["Whole-file", "Chunk, 256 KiB"], values: [file, chunk].map((r) => Number((r.hdfs_space_consumed_before / MIB).toFixed(1))) },
    { name: "After", labels: ["Whole-file", "Chunk, 256 KiB"], values: [file, chunk].map((r) => Number((r.hdfs_space_consumed_after / MIB).toFixed(1))) },
  ], { x: 0.6, y: 1.6, w: 6.3, h: 4.6, barDir: "col", chartColors: [THEME.colors.accent6, THEME.colors.accent1], barGapWidthPct: 70, ...chartOptions({ showLegend: true, legendPos: "b", showTitle: true, title: "NameNode-measured space consumed (MiB)", valAxisMinVal: 0, valAxisHidden: true, valGridLine: { style: "none" } }) });
  screenshot(slide, "optimization", 7.2, 1.6, 5.53, "Screenshot of completed optimization with before and after");
  stat(slide, `${file["verification.files_passed"]} of ${file["verification.files_checked"]}`, "files passed SHA-256 afterwards", 7.2, 3.45, 2.65, { size: 30 });
  stat(slide, `${file.hdfs_files_before} to ${file.hdfs_files_after}`, "HDFS files, whole-file mode", 10.1, 3.45, 2.63, { size: 30 });
  stat(slide, `${(file["disk_used_delta_before.mean"] / MIB).toFixed(0)} to ${(file["disk_used_delta_after.mean"] / MIB).toFixed(0)} MiB`, "on DataNode disks, measured with du", 7.2, 4.95, 5.5, { size: 30 });
}

// 15. Replication and monitoring
{
  const up = H.find((r) => r.step === "changed" && r.factor === 2);
  const slide = newSlide("Replication and cluster health come from HDFS itself", "Product", "A factor above the number of live DataNodes is refused, and lowering it needs confirmation. Success is reported only when fsck and the block locations agree. An interesting finding: fsck stops counting a replica as soon as it is marked excess, before it is deleted, so our first version reported success too early. A real test caught that.");
  screenshot(slide, "replication", 0.6, 1.5, 6.0, "Screenshot of replication manager");
  screenshot(slide, "cluster", 6.73, 1.5, 6.0, "Screenshot of cluster monitoring page");
  text(slide, `Measured at factor 2: space multiplier ${up.multiplier.toFixed(2)}, with ${up.under_replicated_blocks} under-replicated blocks. Success is reported only when fsck and block locations agree. A factor above the live DataNodes is refused.`, 0.6, 5.1, 12.13, 0.9, { fontSize: 15 });
}

// 16. Dataset
pres.addSection({ title: "Evaluation" });
{
  const total = originals.reduce((sum, f) => sum + f.size_bytes, 0);
  const slide = newSlide("Authentic files, with provenance for every byte", "Evaluation", "This project does not need a labelled machine-learning dataset, but it does need real files. The files are from Project Gutenberg, including the three suggested in the brief. Duplicates are clearly labelled test copies. Be ready to say what this cannot show: it is small, so it says nothing about production scale, and its duplicate rates are chosen, not observed.");
  stat(slide, String(originals.length), "original files from Project Gutenberg", 0.6, 1.5, 2.6, { size: 44, color: C.accent1 });
  stat(slide, mib(total), "of authentic data, as published", 3.4, 1.5, 3.0, { size: 44 });
  const rows = [
    ["Kind", "What it is", "Used for"],
    ["Original", "Bytes as published, with URL, date and SHA-256", "Everything"],
    ["Workload copy", "Same bytes, another logical name, labelled", "Duplicate tests"],
    ["Transformed", "One documented byte edit of one original", "Overlap tests"],
  ];
  slide.addTable(rows.map((row, r) => row.map((cell) => ({ text: cell, options: { bold: r === 0, fontSize: 14, color: C.text1, fill: { color: r === 0 ? C.background2 : C.background1 }, border: [{ type: "none" }, { type: "none" }, { type: "solid", color: HEX.grid, pt: 1 }, { type: "none" }], margin: [4, 6, 4, 6] } }))), { x: 0.6, y: 3.55, w: 6.2, colW: [1.5, 3.2, 1.5] });
  text(slide, "No data was invented. Savings verify the mechanism on chosen workloads; they do not predict real-world savings.", 0.6, 5.85, 6.2, 0.8, { fontSize: 14, color: C.accent5 });
  screenshot(slide, "provenance", 7.2, 1.6, 5.53, "Screenshot of dataset lab with provenance");
  text(slide, "Every file: source page, download URL, date, SHA-256 and kind.", 7.2, 5.15, 5.53, 0.6, { fontSize: 14, bold: true });
}

// 17. Benchmarks
{
  const chunked = D.filter((r) => r.mode === "chunk");
  const label = (b) => (b < MIB ? `${b / 1024} KiB` : `${b / MIB} MiB`);
  const slide = newSlide("Finer chunks find more overlap, at a steep cost", "Evaluation", "These are measured results for the same workload at each chunk size: originals plus three edited variants. Savings rise as chunks shrink, but throughput falls and the number of NameNode objects grows, because each chunk is its own HDFS file. Chunks larger than the book find nothing, since the variants are smaller than one chunk. Timings describe this laptop, not a production cluster. Each timing is the mean of three runs.");
  const common = { barDir: "col", chartColors: [THEME.colors.accent1], barGapWidthPct: 60 };
  const labels = chunked.map((r) => label(r.chunk_size));
  slide.addChart(pres.charts.BAR, [{ name: "Savings (%)", labels, values: chunked.map((r) => Number(r.savings_percent.toFixed(1))) }], { x: 0.6, y: 1.45, w: 4.0, h: 4.1, ...common, ...chartOptions({ showTitle: true, title: "Logical savings (%)", valAxisMinVal: 0, valAxisHidden: true, valGridLine: { style: "none" }, dataLabelFormatCode: "0.0" }) });
  slide.addChart(pres.charts.BAR, [{ name: "Upload MiB/s", labels, values: chunked.map((r) => Number(r["upload_throughput_mib_s.mean"].toFixed(1))) }], { x: 4.67, y: 1.45, w: 4.0, h: 4.1, ...common, ...chartOptions({ showTitle: true, title: "Upload throughput (MiB/s)", valAxisMinVal: 0, valAxisHidden: true, valGridLine: { style: "none" }, dataLabelFormatCode: "0.0" }) });
  slide.addChart(pres.charts.BAR, [{ name: "NameNode objects", labels, values: chunked.map((r) => Math.round(r["namespace_objects.mean"])) }], { x: 8.73, y: 1.45, w: 4.0, h: 4.1, ...common, ...chartOptions({ showTitle: true, title: "NameNode objects", valAxisMinVal: 0, valAxisHidden: true, valGridLine: { style: "none" }, dataLabelFormatCode: "#,##0" }) });
  const baseline = D.find((r) => r.mode === "file")["disk_used_delta.mean"];
  const smallest = chunked[0];
  const higher = ((smallest["disk_used_delta.mean"] - baseline) / baseline) * 100;
  text(slide, `Logical savings can mislead: at ${label(smallest.chunk_size)}, they read ${smallest.savings_percent.toFixed(1)}%, yet disk use measured with du is ${higher.toFixed(1)}% higher than whole-file storage.`, 0.6, 5.65, 12.13, 0.8, { fontSize: 18, bold: true });
  text(slide, "Timings: mean of three runs on one laptop. They show the trend, and do not predict a real cluster.", 0.6, 6.5, 12.13, 0.35, { fontSize: 12, color: C.accent5 });
}

// 18. Integrity and testing
{
  const j1 = J.J1_datanode_failure;
  const j2 = J.J2_namenode_failure;
  const j3 = J.J3_process_kill;
  const slide = newSlide("We broke it on purpose, and no data was lost", "Evaluation", `These failures were real: containers were stopped, and a process was killed with SIGKILL during a job. With a DataNode down, files stayed readable, and the NameNode declared it dead after about ${Math.round(j1.seconds_until_namenode_declared_dead)} seconds. With the NameNode down, uploads failed cleanly with HTTP ${j2.upload_http_status_during_outage} and recorded nothing. After the kill, the job was marked ${j3.job_status_after_restart}; resuming it finished the remaining files, and ${j3.files_restored_byte_identical_after_resume} of ${j3.files} files restored byte-identical. The test counts come from the saved test output.`);
  const failures = [
    ["DataNode stopped", `Files stayed readable. A request for factor 3 with two live nodes was refused (HTTP ${j1.replication_factor_3_request_while_two_live_http_status}).`],
    ["NameNode stopped", `Upload failed with HTTP ${j2.upload_http_status_during_outage}. No file recorded. The retry after restart succeeded (HTTP ${j2.retry_after_restart_http_status}).`],
    ["Backend killed mid-job", `Job marked ${j3.job_status_after_restart}. After resume, ${j3.files_restored_byte_identical_after_resume} of ${j3.files} files restored byte-identical.`],
  ];
  failures.forEach(([head, body], i) => {
    const y = 1.65 + i * 1.5;
    slide.addShape(pres.ShapeType.roundRect, { x: 0.6, y, w: 7.2, h: 1.33, rectRadius: 0.06, fill: { color: C.background2 }, line: { color: C.background2 }, objectName: `${head} card` });
    text(slide, head, 0.82, y + 0.14, 6.8, 0.35, { fontSize: 16, bold: true });
    text(slide, body, 0.82, y + 0.52, 6.8, 0.75, { fontSize: 14, color: C.accent5 });
  });
  text(slide, "Automated tests that passed", 8.2, 1.65, 4.53, 0.4, { fontSize: 16, bold: true });
  [[counts.unit.passed, "unit and API tests"], [counts.integration.passed, "on the real HDFS cluster"], [counts.browser.passed, "real-browser tests"]].forEach(([value, label], i) => {
    const y = 2.15 + i * 1.3;
    text(slide, String(value), 8.2, y, 1.6, 0.9, { fontSize: 40, bold: true, color: C.accent1, valign: "middle" });
    text(slide, label, 9.85, y, 2.88, 0.9, { fontSize: 15, valign: "middle" });
  });
  text(slide, "Corrupt or missing chunks are reported individually, and a corrupt download aborts.", 8.2, 6.05, 4.53, 0.6, { fontSize: 13, color: C.accent5 });
}

// 19. Limits and future
pres.addSection({ title: "Close" });
{
  const slide = newSlide("What we learned, what limits it, and what comes next", "Close", "Be open about limits; it counts for you. The biggest measured cost is that each chunk is an HDFS file, and packing would address that. Content-defined chunking fixes the shift weakness. Everything in the right column is future work, and none of it is implemented.");
  const columns = [
    ["Engineering challenges", ["No transaction spans HDFS and SQLite", "fsck reported success before replicas were deleted", "NameNode JMX values lag by about 10 s", "DataNode deletes are asynchronous, so disk readings need care"]],
    ["Current limits", ["Fixed-size chunks: a shift defeats them", "Each chunk is an HDFS file, which costs NameNode memory", "One process and SQLite limit scale", "One laptop: no real hardware fault tolerance"]],
    ["Future work", ["Content-defined chunking (FastCDC)", "Packing chunks into container files", "Distributed index; Spark background jobs", "Kerberos, HA and real multi-machine deployment"]],
  ];
  columns.forEach(([head, lines], index) => {
    const x = 0.6 + index * 4.1;
    slide.addShape(pres.ShapeType.roundRect, { x, y: 1.55, w: 3.9, h: 4.05, rectRadius: 0.05, fill: { color: index === 2 ? "E4EFFC" : C.background2 }, line: { color: index === 2 ? "E4EFFC" : C.background2 }, objectName: `${head} card` });
    text(slide, head, x + 0.2, 1.72, 3.5, 0.4, { fontSize: 18, bold: true });
    slide.addText(lines.map((line, i) => ({ text: line, options: { bullet: { indent: 14 }, breakLine: i < lines.length - 1, paraSpaceAfter: 10 } })), { x: x + 0.2, y: 2.25, w: 3.5, h: 3.25, margin: 0, fontSize: 15, color: C.text1, valign: "top", isTextBox: true });
  });
  text(slide, "The largest measured cost, small chunk files, points directly at the next step: packing chunks into containers.", 0.6, 5.85, 12.13, 0.8, { fontSize: 18, bold: true });
}

// 20. Conclusion
{
  const file = I.find((r) => r.mode === "file");
  const slide = pres.addSlide({ masterName: "DARK", sectionTitle: "Close" });
  slide.addText([{ text: "Duplicates gone.", options: { breakLine: true } }, { text: "Replicas intact.", options: { breakLine: true } }, { text: "Every byte verified." }], { placeholder: "title", fontSize: 40 });
  slide.addText("A working deduplication layer on real HDFS, evaluated with authentic data, including real failures.", { placeholder: "body" });
  text(slide, "Thank you. Questions?", 0.8, 5.5, 7.3, 0.6, { fontSize: 24, bold: true, color: C.background1 });
  text(slide, mib(file.hdfs_space_consumed_before), 8.9, 1.5, 3.9, 0.7, { fontSize: 36, bold: true, color: C.background1 });
  text(slide, "NameNode space consumed before optimization", 8.9, 2.2, 3.9, 0.6, { fontSize: 14, color: C.accent6 });
  text(slide, mib(file.hdfs_space_consumed_after), 8.9, 3.1, 3.9, 0.7, { fontSize: 36, bold: true, color: C.accent4 });
  text(slide, "after, same logical files, same replication", 8.9, 3.8, 3.9, 0.6, { fontSize: 14, color: C.accent6 });
  text(slide, `${file["verification.files_passed"]} of ${file["verification.files_checked"]}`, 8.9, 4.7, 3.9, 0.7, { fontSize: 36, bold: true, color: C.background1 });
  text(slide, "files passed SHA-256 afterwards", 8.9, 5.4, 3.9, 0.6, { fontSize: 14, color: C.accent6 });
  slide.addNotes("Close with the takeaway: we separated deliberate redundancy from accidental redundancy, removed only the second, and proved the bytes are intact. These figures are from a controlled workload with labelled copies. Thank the audience and invite questions.");
}

/** pptxgenjs cannot write theme colors, so set them in the saved file. All theme parts are updated. */
async function applyTheme(file, theme) {
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  const parts = Object.keys(zip.files).filter((name) => /^ppt\/theme\/theme\d+\.xml$/.test(name));
  for (const part of parts) {
    let xml = await zip.file(part).async("string");
    for (const [slot, value] of Object.entries(theme.colors)) {
      xml = xml.replace(new RegExp(`<a:${slot}>.*?</a:${slot}>`, "s"), `<a:${slot}><a:srgbClr val="${value}"/></a:${slot}>`);
    }
    xml = xml.replace(/<a:clrScheme name="[^"]*">/, `<a:clrScheme name="${theme.name}">`);
    zip.file(part, xml);
  }
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

(async () => {
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log(`wrote ${OUT}`);
})();

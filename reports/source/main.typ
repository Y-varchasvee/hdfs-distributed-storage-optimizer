// HDFS Optimizer: complete academic report.
// Build with scripts/build_report.py, which writes generated/ first and compiles with the project root as --root.
// Measured values are read from benchmark result files, so the text cannot drift from the data.

#import "lib.typ": *

#set document(title: "HDFS-Based Distributed File Replication, Deduplication and Storage Optimization System")
#set text(font: ("Times New Roman", "Libertinus Serif"), size: 10pt, lang: "en")
#set par(justify: true, leading: 0.56em, spacing: 0.72em)
#show raw: set text(font: "DejaVu Sans Mono", size: 8pt)
#show link: set text(fill: accent)
#set table(stroke: 0.5pt + rule-color, inset: 4pt)
#show table: set text(size: 8.5pt)
#show table: set par(justify: false)
#show figure.caption: set text(size: 8.5pt)
#show figure.caption: set par(justify: false)
#show figure: set block(breakable: false)
#show figure.where(kind: table): set figure.caption(position: top)
#set figure(gap: 0.6em)

// -- front matter ---------------------------------------------------------------------------------

#set page(paper: "a4", margin: (x: 18mm, top: 20mm, bottom: 20mm), numbering: none)

#page[
  #set align(center)
  #v(25mm)
  #text(size: 11pt, tracking: 1pt, fill: muted)[PROJECT REPORT]
  #v(8mm)
  #text(size: 23pt, weight: "bold", hyphenate: false)[HDFS-Based Distributed File Replication, Deduplication and Storage Optimization System]
  #v(6mm)
  #text(size: 13pt, fill: accent)[HDFS Optimizer]
  #v(22mm)
  #text(size: 11pt)[Submitted in partial fulfilment of the requirements for the degree of]
  #v(2mm)
  #placeholder("Degree and branch")
  #v(14mm)
  #grid(columns: (auto, auto), column-gutter: 8mm, row-gutter: 3mm, align: (right, left),
    [Submitted by], placeholder("Student name"),
    [Roll number], placeholder("Roll number"),
    [Under the guidance of], placeholder("Supervisor name and designation"),
  )
  #v(22mm)
  #placeholder("Department")\
  #placeholder("University or institute")\
  #v(2mm)
  Academic session #placeholder("Session")
]

#page[
  #align(center, text(size: 14pt, weight: "bold")[Certificate])
  #v(6mm)
  This is to certify that the project report titled _HDFS-Based Distributed File Replication, Deduplication and Storage Optimization System_ is the work of #placeholder("Student name"), roll number #placeholder("Roll number"), carried out under my supervision in partial fulfilment of the requirements for the degree of #placeholder("Degree and branch") at #placeholder("University or institute") during the academic session #placeholder("Session").
  #v(25mm)
  #grid(columns: (1fr, 1fr), [#placeholder("Supervisor signature")\ #placeholder("Supervisor name")\ #placeholder("Designation")], align(right)[#placeholder("Head of department signature")\ #placeholder("Name")\ #placeholder("Department")])
  #v(20mm)
  #align(center, text(size: 14pt, weight: "bold")[Declaration of Originality])
  #v(6mm)
  I declare that the source code and results presented are from the system described here, and that all external sources are acknowledged in the references. Experimental values are the output of the experiments described, and no dataset, screenshot or measurement has been fabricated. #placeholder("State your own contribution, and disclose the use of AI assistance in building this project and writing this report, as your institution's policy requires. Review this declaration before signing it.")
  #v(15mm)
  #placeholder("Student signature") #h(1fr) Date: #placeholder("Date")
  #v(20mm)
  #align(center, text(size: 14pt, weight: "bold")[Acknowledgements])
  #v(6mm)
  #placeholder("Acknowledge your supervisor, department and anyone else who helped.") This project relies on the open-source work of the Apache Hadoop community and on the public-domain library maintained by Project Gutenberg and its volunteers.
]

#let summary-i = results("I_before_after").rows.at(0)
#let summary-b = results("B_exact_duplicates").rows

#page[
  #align(center, text(size: 14pt, weight: "bold")[Abstract])
  #v(4mm)
  The Hadoop Distributed File System (HDFS) protects data by replicating blocks, but it has no notion of content: identical files uploaded independently are stored, and replicated, separately. This report presents HDFS Optimizer, an application layer on an unmodified Apache Hadoop 3.5.0 cluster that adds whole-file and fixed-size chunk-level deduplication through content-addressable storage, a relational metadata model, and a web dashboard.

  Because HDFS and the metadata database cannot share a transaction, all writes follow a staged protocol, and a file's old copy is removed only after its new form has been read back and verified with SHA-256. Unreferenced content is identified by query rather than by stored counters. HDFS replication is never reduced to obtain savings, and each reported value is labelled as measured, derived or estimated.

  The system was evaluated on a four-node containerised cluster, using 15 authentic files from Project Gutenberg with recorded provenance. In a workload of #summary-i.files files with two labelled exact copies of each book, whole-file optimization reduced NameNode-reported space consumption from #mib(summary-i.hdfs_space_consumed_before) to #mib(summary-i.hdfs_space_consumed_after), and all #summary-i.at("verification.files_passed") files passed SHA-256 verification afterwards. Savings tracked the expected $(N-1) slash N$ exactly for $N$ identical copies. Chunk-level deduplication additionally recovered overlap between different files, at a measured cost in throughput and NameNode objects, and it did not survive a one-byte shift, confirming the known weakness of fixed-size chunking. Real DataNode, NameNode and process-kill failures caused no data loss. These savings describe controlled workloads, and they do not predict savings on any production system.

  #v(3mm)
  *Keywords:* Hadoop, HDFS, data deduplication, content-addressable storage, replication, storage optimization, SHA-256, distributed file systems.
]

#set page(numbering: "i")
#counter(page).update(1)

#show outline.entry.where(level: 1): set text(weight: "bold")
#outline(title: [Table of Contents], depth: 2, indent: 1em)
#pagebreak()
#outline(title: [List of Figures], target: figure.where(kind: image))
#v(8mm)
#outline(title: [List of Tables], target: figure.where(kind: table))
#pagebreak()

#align(center, text(size: 14pt, weight: "bold")[Abbreviations])
#v(4mm)
#table(columns: (auto, 1fr), stroke: none, row-gutter: 2pt,
  [API], [Application Programming Interface],
  [CAS], [Content-Addressable Storage],
  [CDC], [Content-Defined Chunking],
  [CORS], [Cross-Origin Resource Sharing],
  [CRC], [Cyclic Redundancy Check],
  [CVD], [Color-Vision Deficiency],
  [DN], [DataNode],
  [ER], [Entity-Relationship],
  [FIPS], [Federal Information Processing Standards],
  [GC], [Garbage Collection],
  [HA], [High Availability],
  [HDFS], [Hadoop Distributed File System],
  [JMX], [Java Management Extensions],
  [NN], [NameNode],
  [REST], [Representational State Transfer],
  [RPC], [Remote Procedure Call],
  [SHA-256], [Secure Hash Algorithm, 256-bit],
  [SQL], [Structured Query Language],
  [UI], [User Interface],
  [VM], [Virtual Machine],
  [WAL], [Write-Ahead Logging],
)

// -- body settings --------------------------------------------------------------------------------

#set heading(numbering: (..n) => {
  let parts = n.pos()
  if parts.len() == 1 { "Chapter " + str(parts.at(0)) + " —" } else { parts.map(str).join(".") }
})
#show heading.where(level: 1): it => {
  pagebreak(weak: true)
  place(top, scope: "parent", float: true, clearance: 10pt, block(width: 100%, below: 0pt)[
    #set text(size: 15pt, weight: "bold", font: ("Helvetica Neue", "Arial", "Libertinus Serif"))
    #set par(justify: false)
    #it
    #v(-5pt)
    #line(length: 100%, stroke: 1pt + accent)
  ])
}
#show heading.where(level: 2): it => {
  set text(size: 10.5pt, weight: "bold", font: ("Helvetica Neue", "Arial", "Libertinus Serif"))
  set par(justify: false)
  block(above: 1.1em, below: 0.6em, sticky: true, it)
}
#show heading.where(level: 3): it => {
  set text(size: 10pt, weight: "bold", style: "italic")
  block(above: 0.9em, below: 0.5em, sticky: true, it)
}
#set math.equation(numbering: "(1)")

#set page(columns: 2, numbering: "1", number-align: center)
#set page(margin: (x: 16mm, top: 18mm, bottom: 18mm))
#counter(page).update(1)

= Introduction

== Background
Data volumes grow faster than the budgets that store them, and a large share of stored data is redundant. Distributed file systems make capacity scalable, but they add their own multiplier: each byte is stored several times for durability. Removing accidental redundancy, while keeping deliberate redundancy, is therefore worthwhile.

== Distributed storage
A distributed file system presents one namespace over many machines. Files are split into blocks spread across servers, so capacity and throughput grow by adding machines. Failure is treated as normal: at this scale some disk or machine is always failing, so the system must detect failure and recover automatically @ghemawat2003.

== The Hadoop ecosystem
Apache Hadoop began as an open-source implementation of ideas from Google's distributed systems, and it contains a storage layer (HDFS), a resource manager (YARN) and a batch engine (MapReduce). This project uses HDFS only.

== HDFS fundamentals
HDFS has a primary/worker design @shvachko2010 @hdfsdesign. A single active *NameNode* keeps the directory tree and the mapping from files to blocks in memory, and persists changes in an edit log. Many *DataNodes* store blocks as local files. Clients ask the NameNode where blocks are, and transfer data directly with DataNodes, so the NameNode stays out of the data path. Files are written once and then read many times. The default block size is 128 MiB.

== Replication
Each block is copied to several DataNodes, three by default. DataNodes send heartbeats, every 3 seconds by default, and regular block reports. When a DataNode stops reporting, the NameNode schedules new copies of its blocks @hdfsdesign. Replication is what makes commodity hardware safe, and it is intentional redundancy.

== Data redundancy
A different kind of redundancy comes from users and applications: the same dataset uploaded by two teams, repeated backups, or new versions of a large file. Studies of real systems find substantial duplicate content @meyer2012. HDFS does not detect any of this, since each upload is an unrelated file to it, so each copy is also replicated.

== Deduplication
Deduplication stores identical content once and keeps references to it @paulo2014 @xia2016survey. Whole-file deduplication compares files by a cryptographic hash. Chunk-level deduplication compares pieces of files, finding overlap between files that differ overall, at the cost of more metadata.

== Storage optimization
Storage optimization here means reducing the bytes retained for a given set of logical files without losing data or weakening fault tolerance. Reducing the replication factor would also save space, but it trades away durability, so this project keeps it as a separate, explicit decision.

== Motivation
A student or small team using HDFS has no easy way to see how much of their storage is redundant, or to reclaim it safely. Deleting duplicates by hand risks data loss. Existing academic work often reports savings by simulation or trace analysis; this project builds the mechanism on a real cluster and measures it.

== Project scope
The project delivers a working application: a backend service, a web dashboard, a real multi-node HDFS deployment, whole-file and fixed-size chunk deduplication, verified restoration, replication management, monitoring and reproducible experiments on authentic files. It does not modify HDFS, does not deduplicate internal HDFS blocks, and is not a production multi-tenant service.

= Problem Statement

== Existing storage inefficiencies
For $N$ identical copies of a file of size $S$ at replication factor $R$, plain HDFS consumes about $N dot S dot R$ bytes. Only $S dot R$ is needed to give the same fault tolerance. Nothing in HDFS reveals the difference.

== Redundancy problems
The project addresses ten specific problems: storage wasted by duplicate files; repeated content within different files; difficulty identifying redundant data across a distributed store; poor visibility into storage consumption; difficulty interpreting logical versus replicated physical consumption; the lack of a usable optimization dashboard; integrity risks during deduplication; safe restoration of logically distinct files; monitoring replication health; and measuring efficiency with reproducible experiments.

== Duplication versus replication
These terms are easily confused, so the project keeps them strictly separate. *Replication* is block-level copies that HDFS creates and manages for fault tolerance. *Duplication* is separate files with the same content, created by users. Deduplication removes the second and leaves the first intact: the single remaining copy is still replicated $R$ times.

== Operational limitations
Deduplicating above HDFS raises problems that a built-in feature would not have. HDFS and an external metadata store cannot share a transaction. Files are immutable, so content cannot be merged in place. Every extra file costs NameNode memory @smallfiles, which limits how finely data can be chunked. Deleting one logical file must never destroy content that another still uses.

== Need for the proposed system
A layer is needed that identifies duplicates by content, stores each distinct content once, keeps every logical file independently usable, proves that restored bytes are correct, keeps HDFS replication intact, and reports honest numbers. The system described here is that layer.

= Objectives

== Completed objectives
All of the following are implemented, and each is covered by automated tests or experiments described in this report.

#table(columns: (1fr, auto),
  table.header([*Objective*], [*Evidence*]),
  [HDFS-backed file management], [Ch. 12, 13],
  [Exact duplicate detection with SHA-256], [Exp. B, C],
  [Identical-chunk detection across files], [Exp. D, D2],
  [Content-addressable storage of unique data], [Ch. 10],
  [Logical references preserved], [Exp. C, F],
  [Storage optimized without data loss], [Exp. I],
  [Exact reconstruction of original files], [Exp. E, G],
  [Cryptographic integrity verification], [Exp. E, J3],
  [Supported replication settings managed], [Exp. H],
  [NameNode and DataNode health monitored], [Ch. 12],
  [Storage and deduplication metrics displayed], [Ch. 13],
  [Safe deletion and recovery], [Exp. F],
  [Evaluation on authentic files], [Ch. 5, 14],
  [Visual comparison of storage efficiency], [Ch. 13, 14],
  [Architecture and results documented], [This report],
)

== Proposed future enhancements
These are *not* implemented: content-defined chunking, chunk packing, a distributed index, background deduplication with Apache Spark, multi-user authorization, and deployment on separate physical machines. See Chapter 16.

= Literature Review

== Distributed file systems
The Google File System @ghemawat2003 established the design of a single metadata master with many chunkservers, large blocks and replication on commodity hardware. Shvachko et al. @shvachko2010 describe HDFS, which follows the same model, with a NameNode and DataNodes, and report on its operation at scale. The Apache documentation @hdfsdesign @webhdfs specifies the behaviour this project relies on, including replication, rename semantics and the REST interface. A Cloudera engineering article @smallfiles explains why many small files are a problem: each file, directory and block is an object in NameNode memory, at about 150 bytes each as a rule of thumb.

== Content-addressable storage
Venti @venti2002 is an early archival system that addresses blocks by the hash of their contents, so identical blocks coalesce automatically and stored data is never overwritten. The object store in this project uses the same principle, at a higher level and using SHA-256 @fips180 rather than SHA-1, for which practical collisions have since been demonstrated @stevens2017.

== Chunking
LBFS @lbfs2001 introduced content-defined chunking to deduplicated file transfer: it uses Rabin fingerprints to place chunk boundaries by content, so that an insertion affects only nearby chunks. FastCDC @fastcdc2016 reduces the CPU cost of this approach while achieving a similar deduplication ratio. This project uses fixed-size chunking, for simplicity and determinism, and measures the weakness these papers set out to solve.

== Deduplication systems
Zhu et al. @zhu2008 describe the Data Domain file system, which avoids an on-disk index lookup for most chunks by using a Bloom filter summary and locality-preserving layout. That is the problem of index scale, which this project's SQLite index does not address. Meyer and Bolosky @meyer2012 analyse real desktop file systems and find that whole-file deduplication achieves about three quarters of the savings of aggressive block-level deduplication. That result motivated offering both modes. Paulo and Pereira @paulo2014 and Xia et al. @xia2016survey survey the field and classify systems by granularity, locality, timing and scope.

== Contribution of this project
This project does not propose a new deduplication algorithm. It contributes a complete, inspectable implementation above an unmodified HDFS cluster, which combines staged writes to keep two independent stores consistent, verify-before-delete conversion of existing data, and query-based reference tracking. It also separates derived, measured and estimated values in both its evaluation and its interface, and it reports results from real experiments, including real failures.

= Dataset Description

== Nature of the input data
Deduplication is not machine learning, so no labelled dataset is required. The system needs real files: hashing, chunking and transfer should be exercised on authentic bytes with natural structure.

== Authentic source
All original files are public-domain books from Project Gutenberg @gutenberg, including the three suggested by the project brief: _Pride and Prejudice_ (ebook 1342), _Alice's Adventures in Wonderland_ (11) and _The Adventures of Sherlock Holmes_ (1661).

#let manifest = json("/datasets/provenance/manifest.json")
#let originals = manifest.files.filter(f => f.kind == "original")
#let transformed = manifest.files.filter(f => f.kind == "transformed")

== Format and size
The dataset contains #originals.len() original files totalling #mib(originals.map(f => f.size_bytes).sum()): plain text for all 9 works, plus HTML and EPUB versions of the three primary works. These give a realistic mix: highly compressible text, markup, and already-compressed archives. @tab-dataset lists every file.

#figure(
  table(columns: (1fr, auto, auto, auto),
    table.header([*Title*], [*ID*], [*Format*], [*Bytes*]),
    ..originals.map(f => (f.title, str(f.ebook_id), f.file_format, str(f.size_bytes))).flatten(),
  ),
  caption: [Original dataset files as downloaded],
) <tab-dataset>

== Download method and provenance
`scripts/download_dataset.py` fetches each file and writes `datasets/provenance/manifest.json`. For each file it records the title, author, ebook ID, source organization, source page, requested and final URLs, download date, format, size, SHA-256, kind and any transformation. For plain-text files, the title printed inside the file was also compared with the catalog, and all matched.

Project Gutenberg's policy states that its website is for human users and directs automated tools to mirrors @gutenbergrobots. This policy was noticed after the files in this report had been fetched once from `www.gutenberg.org`, at one request every two seconds. The manifest records those URLs truthfully. The tool was then changed to use the mirror operated by the Project Gutenberg Literary Archive Foundation. As a check, `pg11.txt` from that mirror has the same SHA-256 as the recorded file.

== Duplication test methodology
Natural duplicates are not available in a public book collection, so duplicates are created under control, in two labelled ways:

- *Workload copies* are the same bytes ingested under another logical name, labelled `workload_copy`.
- *Transformed files* are byte-level edits of _Pride and Prejudice_, labelled `transformed`, for partial-overlap tests. @tab-transform describes them.

#figure(
  table(columns: (auto, 1fr, auto),
    table.header([*File*], [*Transformation*], [*Bytes*]),
    ..transformed.map(f => (raw(f.local_path.split("/").at(1).replace("pg1342.", "").replace(".txt", "")), f.transformations, str(f.size_bytes))).flatten(),
  ),
  caption: [Documented partial-overlap workload files],
) <tab-transform>

No text was invented. The only bytes these edits add are one newline or one replaced byte. The originals are never altered.

== Restrictions and limitations
The dataset cannot show behaviour at production scale, because it is about 41 MiB. All files are smaller than one HDFS block, so each occupies a single block. Duplication is created deliberately, so measured savings verify the mechanism on known workloads, and they do not estimate the redundancy of any real system.

= Dataset Source

== Source links
- Project Gutenberg: https://www.gutenberg.org/
- _Pride and Prejudice_: https://www.gutenberg.org/ebooks/1342
- _Alice's Adventures in Wonderland_: https://www.gutenberg.org/ebooks/11
- _The Adventures of Sherlock Holmes_: https://www.gutenberg.org/ebooks/1661
- License: https://www.gutenberg.org/policy/license.html
- Robot access policy: https://www.gutenberg.org/policy/robot_access.html

The remaining works are linked in the provenance appendix.

== Citation and attribution
Files are cited as Project Gutenberg @gutenberg, and are used under the Project Gutenberg License @gutenberglicense. The system stores files as distributed, with the license header intact, and does not redistribute them with this report.

== Why generated data was not used
Generated data can be shaped to produce any desired result, and a reader cannot independently check it. Every original file here can be traced to a public URL and confirmed by its hash, and every derived file has a stated transformation. Unit tests do use small deterministic byte patterns, but these exercise program logic only, and no evaluation result in this report comes from them.

= Tools and Technologies

== Hadoop, HDFS and WebHDFS
Apache Hadoop 3.5.0 provides the distributed storage. WebHDFS @webhdfs is its REST interface, where a `CREATE` request first redirects to a DataNode, and the data is then sent there. It lets the Python backend work with no Java client. Monitoring uses the NameNode's JMX and fsck servlets.

== Python and FastAPI
The backend uses Python 3.12 and FastAPI @fastapi, which provides validation through Pydantic and generates OpenAPI documentation. HTTPX is the HTTP client. Uploads are spooled to disk and streamed, so memory use does not grow with file size.

== React and Next.js
The frontend uses Next.js 16 and React 19 with TypeScript and Tailwind CSS, components from shadcn/ui, Recharts for charts, TanStack Query for data fetching, and Motion for restrained transitions.

== Metadata database
SQLite, in write-ahead-logging mode with foreign keys enforced, is accessed through SQLAlchemy 2.0, with schema migrations managed by Alembic. It is a single file and needs no server, which suits a project of this scale, though not a large deployment.

== SHA-256
SHA-256 @fips180 produces a 256-bit digest. Content identity is defined entirely by this digest and the size. MD5 and SHA-1 were rejected because practical collisions are known @stevens2017, which would let a crafted file masquerade as another.

== Docker
HDFS runs in Docker Compose under a Colima VM. The official `apache/hadoop` images are amd64-only, so a Dockerfile builds a native arm64 image from the official Apache release tarball and verifies its SHA-512.

== Testing libraries
Pytest runs the unit and integration tests. Playwright drives real browser tests in Google Chrome.

== Visualization technologies
The dashboard uses Recharts, and the report's charts use Matplotlib, both generated from measured data. Colors come from a categorical palette checked for color-vision deficiency, and every interface chart has a table view. Diagrams are generated from a script as SVG files.

= System Requirements

== Functional requirements
#table(columns: (auto, 1fr),
  table.header([*ID*], [*Requirement*]),
  [FR1], [Upload files by streaming, with progress],
  [FR2], [Detect identical content regardless of name],
  [FR3], [Store whole-file objects and fixed-size chunks],
  [FR4], [Rebuild any file exactly, and verify it],
  [FR5], [Convert existing data safely, after a dry run],
  [FR6], [Delete recoverably; protect shared content],
  [FR7], [Change the replication factor, and verify it],
  [FR8], [Show cluster health and storage measurements],
  [FR9], [Record an audit trail of all operations],
  [FR10], [Import authentic data with provenance, and run experiments],
)

== Nonfunctional requirements
#table(columns: (auto, 1fr),
  table.header([*ID*], [*Requirement*]),
  [NF1], [No data loss from any single failure of a process or step],
  [NF2], [Memory use independent of file size, up to one chunk],
  [NF3], [Numbers must state how they are known],
  [NF4], [Responsive, accessible interface in light and dark modes],
  [NF5], [Reproducible through scripts and documented steps],
  [NF6], [Free to operate, using open-source software],
)

== Hardware requirements
The system was developed and evaluated on an Apple M1 laptop with 8 GB of RAM and 8 CPU cores. The Docker VM needs 4 GB of memory for the standard cluster, of which the four Hadoop daemons used about 700 MiB when idle. About 6 GB of free disk is needed, mostly for the Hadoop image.

== Software requirements
macOS or Linux; Docker with Compose, or Colima; Python 3.12; Node.js 22; Google Chrome for browser tests; Typst to rebuild this report. Exact versions are pinned in `requirements.txt` and `package-lock.json`.

== Constraints
- HDFS files are write-once, so content is immutable.
- WebHDFS offers no multi-file transaction.
- All "machines" share one host in this deployment.

== Assumptions
- One API process runs at a time. Internal locks depend on this.
- SHA-256 collisions are treated as impossible, and only the size is compared as well.
- Users are trusted. Access control is limited to an optional shared token.

= System Architecture

== High-level architecture
@fig-arch shows the layers. A browser calls a versioned REST API. Routers validate input and call services. Services use two stores: SQLite for metadata, and HDFS, through a small `HdfsClient` interface, for all content. Every service receives its dependencies through an explicit context object. That is what allows an experiment to run against a private directory and database without touching managed data.

#diagram("01_system_architecture.svg", [High-level system architecture], width: 88%) <fig-arch>

== HDFS cluster architecture
The cluster in @fig-cluster has one NameNode and three DataNodes in containers, with persistent volumes. The backend runs outside the Docker network in the standard setup. WebHDFS redirects name DataNodes by container hostname, so the client maps these to published ports. The NameNode formats its directory only if it is empty, so a restart cannot wipe metadata. Dead-node detection was shortened from the default 10.5 minutes to about 90 s, so failures can be observed in a demonstration.

#diagram("02_hdfs_cluster.svg", [HDFS cluster architecture as deployed], width: 88%) <fig-cluster>

== Upload pipeline
@fig-upload shows a whole-file upload. Staging and rename make publication atomic: HDFS rename refuses to overwrite an existing path, a behaviour the integration tests confirm on the real cluster.

#diagram("03_upload_pipeline.svg", [Upload pipeline: bytes are made durable before metadata is committed], width: 88%) <fig-upload>

== Deduplication pipeline
@fig-dedup shows how a storage decision is made. If any active form of the content already exists, the upload adds a reference, even if the existing form differs from the requested mode. This avoids storing the same content twice in two forms.

#diagram("04_dedup_decision.svg", [Deduplication decision for an uploaded file], width: 78%) <fig-dedup>

== Chunk-level storage model
In @fig-chunks, logical files point at manifests, and manifests list chunks in order. Identical files share a manifest. Two files that differ by one chunk share all the others. Each chunk is a separate HDFS file, not an HDFS block.

#diagram("05_chunk_storage_model.svg", [Chunk-level storage model], width: 88%) <fig-chunks>

== File reconstruction
@fig-restore shows a verified restore. Each chunk is checked as it is read, and the whole stream is compared at the end. Since the response is already streaming, a failure aborts the connection, so a client cannot mistake damaged data for a complete download.

#diagram("06_file_reconstruction.svg", [File reconstruction with verification], width: 88%) <fig-restore>

== Replication workflow
@fig-replication shows a replication change. HDFS applies changes asynchronously, so success is observed rather than assumed.

#diagram("07_replication_workflow.svg", [Replication change and verification], width: 88%) <fig-replication>

== Database design
@fig-er shows the schema. A `files` row has exactly one storage pointer, enforced by a `CHECK` constraint. Foreign keys to stored content use `ON DELETE RESTRICT`. `file_chunks` rows are the authoritative chunk references, and whether content is still needed is always a query. No counter is stored, so none can drift.

#diagram("08_er_diagram.svg", [Database entity-relationship diagram], width: 88%) <fig-er>

== Data flow
@fig-dfd shows how data moves between processes and the two stores.

#diagram("09_data_flow.svg", [Data flow diagram], width: 82%) <fig-dfd>

== Sequence of a new upload
@fig-seq shows the messages exchanged when new whole-file content is uploaded.

#diagram("10_sequence_upload.svg", [Sequence diagram for a new whole-file upload], width: 86%) <fig-seq>

= Implementation and Methodology

== Environment setup
`scripts/setup.sh` creates the Python environment, installs frontend dependencies, starts the container runtime and builds the Hadoop image. A project-local Docker configuration avoids a stale credential helper left behind by a removed Docker Desktop installation.

== HDFS initialization
Compose starts the NameNode, and it waits until a JMX health check passes before starting DataNodes. An entrypoint renders the configuration from templates, including the replication factor. On startup, the backend creates its namespace: `/hdfs-optimizer/{objects, chunks, manifests, staging, recovery, raw}`.

== Backend architecture
Routers contain no storage logic. `WebHdfsClient` maps WebHDFS errors onto typed exceptions, so an outage becomes HTTP 503. All HDFS paths come from hashes or generated IDs, never from user input, and folders are virtual and exist only in metadata. This rules out path traversal by construction, and it is also tested.

== Database initialization
Alembic migrations run at startup, and a test confirms that they build the same tables as the models. Each connection enables foreign keys, write-ahead logging and a 30-second busy timeout.

== Frontend integration
Pages fetch through TanStack Query, and jobs are polled until they finish. Uploads use `XMLHttpRequest`, because it reports the bytes sent, so upload progress is genuine. A browser test confirms that an empty system shows N/A rather than a fabricated value.

== File upload and SHA-256 computation
An upload is spooled to disk in 1 MiB buffers, hashing as it goes. Time is $O(n)$ in the file size, and memory is constant.

== Duplicate identification and content-addressable storage

#code[```text
Algorithm 1: INGEST(file, mode)
  h, n ← SHA256(file), SIZE(file)
  acquire content_lock
  if mode = raw:
      PUT_STAGED(/raw/<id>, file, h, n)
      pointer ← raw path
  else if an active object or manifest of h exists:
      check it exists in HDFS; repair from file if not
      pointer ← existing form             ▷ 0 bytes written
  else if mode = file:
      PUT_STAGED(/objects/h[0:2]/h[2:4]/h, file, h, n)
      pointer ← object
  else:
      pointer ← BUILD_MANIFEST(file, h, n, chunk_size)
  commit LogicalFile(pointer), audit, samples

Algorithm 2: PUT_STAGED(path, data, h, n)
  if path exists and SHA256(path) = h: return    ▷ adopt
  s ← /staging/<uuid>
  CREATE(s, data); assert LENGTH(s) = n
  if verify_on_write: assert SHA256(s) = h
  RENAME(s, path)                                ▷ atomic
```]

Lookup uses a unique index, so it is $O(log m)$ for $m$ stored contents.

== Chunk processing and file manifests

#code[```text
Algorithm 3: BUILD_MANIFEST(stream, h, n, c)
  for each block b of exactly c bytes in stream:
      d ← SHA256(b); append (d, |b|, offset) to plan
      if d is new in this run:
          if chunk d is active and intact: reuse
          else PUT_STAGED(/chunks/.../d, b, d, |b|)
  assert SHA256(stream) = h             ▷ source did not change
  PUT_STAGED(manifest JSON)
  commit chunk rows, manifest, file_chunks in one transaction
```]

Rows are added only after all HDFS writes finish, so the database write lock is held briefly. The manifest also exists as a JSON file in HDFS, and verification checks that it agrees with the database.

== Reference handling and safe deletion
Soft deletion marks the logical file only; its content remains, because the file can still be restored. Permanent removal clears the pointers, then runs collection:

#code[```text
Algorithm 4: COLLECT_GARBAGE()
  acquire content_lock
  O ← active objects no non-purged file points at
  M ← active manifests no non-purged file points at
  C ← active chunks in no surviving manifest
  mark O ∪ M ∪ C as gc_pending and commit
  for each: DELETE from HDFS, mark removed, commit
```]

The state written first means that an interrupted collection is finished at the next startup. The complexity is that of the anti-join, about $O(k log k)$ for $k$ references.

== Safe optimization

#code[```text
Algorithm 5: OPTIMIZE(mode)
  require a preview of the unchanged catalog
  for each eligible file f:             ▷ independent unit
      make the new form durable in HDFS
      read it back; assert SHA256 = f.sha256
      commit f's new pointer
      delete the old copy
  COLLECT_GARBAGE()
  record before and after measurements
```]

A corrupted source is detected and left untouched, and the other files continue. An HDFS outage stops the job, since per-file failures would be misleading. Because converted files are no longer eligible, re-running the job is safe and processes only what remains.

== Recovery
At startup, active jobs are marked interrupted, pending collections finish, and leftover staging files are removed. A reconciliation tool compares HDFS with the metadata, reporting missing files, and quarantines orphans in `/recovery/orphans` rather than deleting them.

== Replication management
A request above the number of live DataNodes is refused, since those blocks could never be fully replicated. Lowering the factor needs explicit confirmation. A job then calls `SETREPLICATION` on each file and waits for convergence.

Testing on the real cluster revealed that `fsck` stops counting a replica as soon as it is marked excess, which is before the DataNode deletes it. The first implementation therefore reported success early. Verification now also requires `GET_BLOCK_LOCATIONS` to show the requested count.

== Analytics calculation
Two formulas define the savings metrics:

$ "Savings (%)" = ("Logical" - "Stored") / "Logical" times 100 $
$ "Deduplication ratio" = "Logical" / "Stored" $

Each is undefined when its denominator is zero, and the interface then shows N/A. Stored bytes are the sum of private raw copies, active objects and active chunks, derived from metadata. Replication-adjusted storage is labelled an estimate. Measured space comes from the NameNode's `GETCONTENTSUMMARY`.

== Error management
Errors have typed classes and a uniform JSON format. HDFS unavailability is distinguished from content corruption: a verification that cannot reach HDFS raises an error rather than recording a failed check, so an outage cannot be mistaken for data damage. Failures are recorded in the audit trail in their own transaction, so they survive the rollback of the failed operation.

// -- chapter 11 is single column ----------------------------------------------------------------
#include "chapter11.typ"

#set page(columns: 1, margin: (x: 18mm, top: 18mm, bottom: 18mm))

= Execution Screenshots

Every image in this chapter and the next was captured from the running system by a Playwright script that used the application from an empty state. No image was edited or mocked. Terminal images show command output saved to `evidence/` and rendered as text, unedited. Long outputs are cut at a marked line, and the full text is in that folder.

#shot("terminal_01_docker_cluster.png", [HDFS cluster running in Docker, with Hadoop version output])
#shot("terminal_02_hdfs_report.png", [`hdfs dfsadmin -report`: live DataNodes and capacity. All DataNodes share one VM disk, so capacity is counted once per node.])
#shot("10_namenode_interface.png", [Apache Hadoop's own NameNode web interface])
#shot("11_datanode_status.png", [DataNode list in the NameNode interface])
#shot("11a_datanode_interface.png", [One DataNode's own web interface], width: 75%)
#shot("terminal_05_backend_execution.png", [Running backend: health check, live statistics and request log])
#shot("12b_api_documentation.png", [Generated OpenAPI documentation, served by the backend], width: 80%)
#shot("00_dashboard_empty.png", [Running frontend on an empty system. Undefined metrics show N/A, not 0%.])
#shot("17_dataset_provenance.png", [Dataset lab with recorded provenance])
#shot("12a_dataset_ingest_dialog.png", [Dataset ingestion with labelled workload copies], width: 80%)
#shot("02_file_upload.png", [File upload through the interface. The second upload of the same bytes under a new name is reported as a duplicate.])
#shot("03_file_explorer.png", [File explorer after ingestion])
#shot("05a_optimization_confirm.png", [Deduplication execution: confirmation after a reviewed preview], width: 80%)
#shot("terminal_03_hdfs_namespace.png", [HDFS command-line view of the managed namespace after optimization])
#shot("terminal_04_hdfs_fsck.png", [`hdfs fsck` on the managed namespace, and the replica locations of one object])
#shot("terminal_07_unit_tests.png", [Unit test execution])
#shot("terminal_08_integration_tests.png", [Integration tests on the real HDFS cluster])
#shot("terminal_09_browser_tests.png", [Browser tests in Chrome, on the real cluster])
#shot("09_cluster_status.png", [Cluster monitoring page with live NameNode and DataNode data])

= Output and Result Screenshots

#shot("04_duplicate_analysis.png", [Duplicates found: each group has one SHA-256 and shows how logical names map to stored copies. Here the copies were stored without deduplication.])
#shot("05_optimization_preview.png", [Dry-run preview. Figures are labelled as estimates, and nothing has changed yet.])
#shot("06_optimization_complete.png", [Completed whole-file optimization: measured before and after, and every file verified])
#shot("05b_chunk_preview.png", [Dry-run preview of chunk-level optimization])
#shot("06b_chunk_complete.png", [Completed chunk-level optimization])
#shot("04b_shared_chunks.png", [Chunk map: blue marks are chunks shared with another file. A truncated copy and a one-byte edit share almost everything; a one-byte insertion at the start shares nothing.])
#shot("01_dashboard.png", [Dashboard with unique content retained and storage savings])
#shot("07_storage_analytics.png", [Analytics page with performance measurements and integrity results])
#shot("08b_replication_factor_2.png", [Replication after a verified change to factor 2. Measured space fell accordingly.])
#shot("08_replication_management.png", [Replication restored to factor 3, with both changes recorded])
#shot("08a_replication_confirm.png", [Lowering replication requires explicit confirmation], width: 80%)
#shot("16a_file_details_verified.png", [File details: replica locations, and a passed SHA-256 verification])
#shot("terminal_06_restore_checksum.png", [Restored file compared with the publisher's bytes: identical SHA-256, and `cmp` reports no difference])
#shot("09c_cluster_datanode_dead.png", [Real failure: a stopped DataNode is reported as dead, and all managed blocks are under-replicated])
#shot("09d_replication_datanode_dead.png", [While a DataNode is dead, the maximum selectable factor falls to 2])
#shot("09e_cluster_namenode_down.png", [Real failure: the NameNode is stopped, and the interface reports it], width: 80%)
#shot("09f_upload_during_outage.png", [An upload during the NameNode outage fails with a clear error, and no file is recorded], width: 80%)
#shot("17a_experiment_lab.png", [Experiments run from the lab, showing measured results], width: 86%)
#shot("09a_activity_audit.png", [Audit trail of the session])
#shot("09b_settings_diagnostics.png", [Settings, with real diagnostics and a metadata-to-HDFS comparison])
#shot("01a_dashboard_dark.png", [Dashboard in dark mode], width: 85%)
#shot("01b_dashboard_phone.png", [Dashboard at phone width], width: 32%)

#set page(columns: 2, margin: (x: 16mm, top: 18mm, bottom: 18mm))

#include "chapter14.typ"

= Limitations

== Small-file overhead
Each chunk is an HDFS file, with its own block and replicas, and every file, directory and block is an object in NameNode memory. Chapter 14 measures this. Small chunks are expensive in a way that a block-level deduplicator inside a storage system would not be.

== Metadata costs
Manifests are stored in HDFS and in SQLite, which adds bytes and a row per chunk reference. At the scale tested this is negligible, but it grows linearly with the number of chunks.

== Docker resource limitations
All daemons share one 4 GB VM on one laptop. Measured throughput reflects that environment, and also includes a virtualised network and disk.

Deployment coverage differs by component. The standard cluster and the light two-DataNode profile were both run and tested. The backend image was built and tested in a container against the real cluster, including an upload and a SHA-256-matched download. The frontend image could *not* be built on the evaluation machine: its first build attempt exhausted the host's free disk, causing I/O errors in the build. HDFS was checked afterwards and was unharmed. The image was slimmed, and a build script was added that aborts below a free-disk margin, which it then did. Its build steps and server command were instead tested directly on the host, serving all ten pages, so the final image itself remains unverified. Evidence is in `evidence/12_light_cluster.txt` and `evidence/13_containerised_app.txt`.

== Single-machine versus multi-machine deployments
All DataNodes share one disk, so a disk or host failure would lose everything. Configured capacity counts that disk once per DataNode. Stopping a container shows HDFS's software behaviour under failure, but this deployment provides no real hardware fault tolerance. With three DataNodes at factor 3, there is also no spare node to re-replicate onto, so blocks stay under-replicated until the node returns.

== Chunking limitations
Fixed-size chunking is defeated by a shift, as measured. A chunk larger than a file also finds no overlap with its variants, so the best chunk size depends on the data.

== Hashing overhead
Each upload hashes all bytes, and whole-file writes are read back to verify. Chunk mode also hashes every chunk, so a verified restore costs CPU proportional to file size.

== Concurrency limitations
One process, one job worker, and a lock held during the storage step, mean ingestion is serial. Running several backend processes against one database is unsafe, because the content lock is in-process.

== Scalability considerations
SQLite is a single-writer database on one disk. A full index of chunk hashes becomes the bottleneck at scale, which is the problem addressed by Zhu et al. @zhu2008.

== HDFS-specific restrictions
The application cannot deduplicate HDFS blocks, since these are internal to HDFS. HDFS block checksums already catch disk corruption on read, so the SHA-256 checks here add end-to-end protection rather than replace them. JMX values are cached for about 10 seconds, so monitoring lags slightly. The NameNode remains a single point of failure, because HA is not configured.

== Security
Access control is an optional shared token, intended for local use, and the API binds to localhost. WebHDFS uses Hadoop's simple authentication, which trusts the stated user name. The system should not be exposed to a network as it stands.

= Future Scope

== Content-defined chunking
Replacing fixed boundaries with FastCDC @fastcdc2016 would make deduplication robust to insertions. The experiment here gives a baseline to compare against.

== Object packing
Writing chunks into large container files, with an offset index, would keep the savings of fine chunking while using few HDFS files and blocks. This addresses the largest measured cost.

== Large-scale distributed indexing
A distributed key-value store, with a Bloom filter in front as in Data Domain @zhu2008, would remove the SQLite limit.

== Apache Spark integration
A Spark job @spark2012 could scan an existing HDFS directory in parallel, computing hashes close to the data rather than moving it through one Python process.

== Stronger multi-user authorization
Per-user accounts and Kerberos would be needed. Deduplicating across users also raises an information leak, since a fast "duplicate" response reveals that someone else has the same file. That would need analysis.

== Incremental background deduplication
Ingest could accept data immediately and deduplicate it in the background, using continuous rather than manual jobs.

== More advanced monitoring
Time series of cluster metrics and alerts could be exported to a monitoring system such as Prometheus.

== Enterprise deployment
This includes separate machines, NameNode HA, TLS, and a server database with backup. Rack-aware placement could then be tested on real hardware.

#include "chapter17.typ"

#set heading(numbering: none)

= References
#bibliography("refs.yml", style: "ieee", title: none)

#include "appendices.typ"

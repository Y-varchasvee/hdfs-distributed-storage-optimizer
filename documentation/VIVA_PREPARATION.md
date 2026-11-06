# Viva preparation

Short answers you can say aloud. Figures come from `benchmarks/results/`; re-run the benchmarks and update them if the code changes. Questions marked with `[results]` are answered from that data in `documentation/RESULTS_SUMMARY.md`.

## Demonstration script (5 to 7 minutes)

Before you start: run `scripts/start-all.sh`, open <http://localhost:3100>, and keep <http://localhost:9870> in a second tab. Start from an empty system (`scripts/reset-demo.sh`) so the numbers visibly change.

| Time | Page | Do this | Say this |
|---|---|---|---|
| 0:00 | Terminal | Run `docker compose ps` | "One NameNode and three DataNodes running real Apache Hadoop 3.5.0." |
| 0:30 | NameNode UI, then Monitoring | Show the Datanodes tab, then the Monitoring page | "Our page reads the same state from the NameNode's JMX interface." |
| 1:00 | Dashboard | Point at the N/A values | "With nothing stored, savings are undefined, so we show N/A rather than 0%." |
| 1:20 | Dataset lab | Show the provenance table and a source link | "Real Project Gutenberg files, each with its URL, date and SHA-256." |
| 1:50 | Dataset lab | Select the three plain-text files. Ingest with 2 copies, mode No dedup | "Exact copies, labelled as workload copies. No dedup gives us a baseline." |
| 2:30 | Duplicates | Open the first group, show the diagram | "Different names, same SHA-256. Each copy is still stored separately." |
| 3:00 | Optimization | Choose File-level, run the dry run | "Nothing has changed. These are estimates, and the page says so." |
| 3:30 | Optimization | Start, then show before and after | "Each file was verified before its old copy was removed. These are measured." |
| 4:10 | Optimization | Click Verify all restored bytes | "Every byte is read back from HDFS and compared with the original hash." |
| 4:40 | Files | Open a file, show block hosts, download it | "Three replicas on three DataNodes. Deduplication did not remove replicas." |
| 5:10 | Files | Delete one duplicate, verify another, then restore the first | "Shared content stays while any file still refers to it." |
| 5:40 | Replication | Show that factor 4 cannot be selected | "We refuse a factor the cluster cannot satisfy." |
| 6:00 | Analytics | Show throughput and download the CSV | "These timings were measured by the operations themselves." |
| 6:30 | Close | Dashboard | "Summary: duplicates gone, replicas intact, every byte verified." |

If something fails during the demo, say so and show the Activity page: failures are recorded there. That honesty counts for you.

## Questions and answers

### HDFS basics

**1. What is HDFS?**
The Hadoop Distributed File System stores large files across many machines. It splits each file into blocks, 128 MiB by default, and keeps several copies of every block on different machines, so hardware failure does not lose data. It is optimised for large sequential reads, and files are write-once.

**2. What does the NameNode do?**
It holds the metadata: the directory tree, which blocks make up each file, and where each block's replicas live. It keeps this in memory. It stores no file data, and clients get block locations from it and then talk to DataNodes directly.

**3. What is a DataNode?**
A worker that stores block files on its local disk and serves reads and writes. It sends the NameNode a heartbeat every 3 seconds and regular block reports. We can see both on the Monitoring page.

**4. Why does HDFS use replication?**
For fault tolerance and read availability. With factor 3, a block survives two DataNodes failing. If a replica is lost, the NameNode schedules a new copy automatically. Replication trades disk space for durability on purpose.

**5. What is WebHDFS, and why use it?**
A REST API for HDFS. Creating a file takes two steps: the NameNode answers with a redirect to a DataNode, and the client sends the bytes there. We use it so that the Python backend needs no Java client, and every operation is a plain HTTP call.

### Replication versus deduplication

**6. What is the difference between replication and deduplication?**
Replication is deliberate copying of blocks for safety, managed by HDFS. Deduplication removes accidental copies of the same content that users uploaded separately. They operate at different levels and do not conflict: we store each unique content once, and HDFS still keeps three replicas of it.

**7. Does HDFS deduplicate on its own?**
No. If two users upload identical files, HDFS treats them as unrelated files and stores blocks for both. It has no content index. That gap is the reason for this project.

**8. Doesn't lowering replication also save space? Why not use that?**
It saves space by reducing safety. That is a different trade-off from removing redundant copies, so our system never does it to report savings. Changing the factor is a separate action, with its own warning and confirmation.

### Deduplication design

**9. What is file-level deduplication?**
We hash the whole file. If that hash is already stored, we add a new logical file that points at the existing object and write no data. If not, we store one object at a path derived from its hash. It is fast and simple, but it finds only files identical in every byte.

**10. What is chunk-level deduplication?**
We split each file into fixed-size pieces and hash each piece. Only unseen pieces are stored. A manifest records the ordered list of chunk hashes. This also finds overlap between files that differ overall.

**11. How is a file reconstructed?**
We read the manifest's chunk list in order, fetch each chunk from HDFS, check each chunk's hash, and stream the bytes out. At the end the whole stream's SHA-256 must equal the original file hash. If not, the download is aborted, so a client can never receive damaged data as if it were complete.

**12. Why SHA-256?**
It is a standard cryptographic hash from FIPS 180-4. Its 256-bit output makes an accidental collision negligible, and no practical attack on it is known. MD5 and SHA-1 have known collision attacks, so a malicious upload could fool a system that uses them.

**13. What if two different files did have the same SHA-256?**
They would be treated as the same content, which would be silent data corruption. No SHA-256 collision has ever been published, and for random data the probability is around 2^-128 even after 2^64 files. We also compare the size. We accept this residual risk, as do other content-addressed systems such as Git's SHA-256 mode.

**14. How is the hash index maintained?**
It is a table in SQLite with a unique index on the hash column, for objects and for chunks. A lookup is O(log n). A single SQLite file limits scale; a larger system would need a distributed index.

**15. How are duplicates identified?**
By grouping logical files on SHA-256. File identity depends only on content. Two files with different names and the same bytes are duplicates. Two files with the same name and different bytes are not; the second becomes `name (1).txt`.

**16. Are your chunks the same as HDFS blocks?**
No, and this distinction matters. HDFS blocks are internal to HDFS, and we cannot deduplicate them across files from outside. Our chunks are application-level pieces, each stored as its own small HDFS file, which HDFS then stores in its own blocks and replicates.

**17. What is wrong with fixed-size chunking?**
Boundary shift. Inserting one byte at the start moves every later byte, so no chunk matches any more. We measured this directly with the transformed test files `[results]`. Content-defined chunking, such as FastCDC, places boundaries based on the content, so an insertion affects only nearby chunks. It is listed as future work and not implemented.

**18. Why not use a very small chunk size?**
Each chunk is an HDFS file, and the NameNode keeps every file and block in memory. Small chunks find more overlap but cost more NameNode memory, more RPC calls and much lower throughput. We measured this trade-off across chunk sizes `[results]`. Packing chunks into container files would reduce the cost; that is future work.

### Safety and integrity

**19. How do you keep HDFS and SQLite consistent without a shared transaction?**
A strict order of operations. Bytes go to a staging path, get checked, are renamed atomically to the final path, and only then is the metadata committed. A crash at any point leaves at most an unreferenced file, never metadata pointing at missing data. A reconciliation tool finds and quarantines these orphans.

**20. How is shared content protected during deletion?**
Deleting a file only changes that logical file. Content is removed only by the garbage collector, and only if a query over the current tables proves that no non-purged file refers to it. We do not keep a counter that could drift. The database also has foreign keys that refuse to remove a referenced object.

**21. How are deleted files restored?**
Deletion is soft. The file row is marked deleted and its content stays, since soft-deleted files still count as references. Restore flips the state back. A private raw copy moves to a recovery directory and back. Only a permanent delete, which must be requested separately, can lead to content removal.

**22. How is data integrity verified?**
The verify action reads every byte from HDFS, recomputes SHA-256 and compares it with the recorded hash. In chunk mode it also checks each chunk and reports exactly which are missing or corrupt, and confirms the durable manifest in HDFS agrees with the database. Every result is recorded with a timestamp.

**23. What happens if the process dies during optimization?**
We tested this by sending SIGKILL during a real job `[results]`. On restart the job is marked interrupted. Every file is its own unit of work: the new form is verified, the pointer commits, and only then is the old copy removed. So each file is either fully converted or untouched. Resume processes only what is left.

### Failure behaviour

**24. What happens if a DataNode fails?**
Reads continue, using the other replicas. After missing heartbeats, the NameNode declares the node dead and re-replicates under-replicated blocks onto other nodes if any are available. On our three-node cluster at factor 3, there is no spare node, so blocks stay under-replicated until it returns. We stopped a real DataNode to test this `[results]`.

**25. What happens if the NameNode fails?**
All HDFS operations stop, since nothing can locate blocks. Our cluster has one NameNode, so this is a single point of failure. Production clusters use HA with a standby NameNode. Our API returns 503, writes no metadata, and the interface reports the outage. We tested this too `[results]`.

**26. What are the limits of a single-host cluster?**
All "DataNodes" share one machine and one disk, so a disk or host failure loses everything, and configured capacity counts the same disk three times. Network speed is not representative either. It demonstrates the software behaviour faithfully, but not hardware fault tolerance or production performance.

### Results and scope

**27. How does this reduce storage consumption?**
By storing each distinct content once, then letting HDFS replicate that one copy. For N identical files of size S at factor R, plain HDFS uses N·S·R and we use S·R, plus a small amount of metadata.

**28. What are the measured results?** `[results]`
See `documentation/RESULTS_SUMMARY.md` for the exact figures, and be ready to explain that savings depend entirely on how much duplication a workload contains. Unique files show zero savings, by design.

**29. Why is logical saving different from disk saving?**
Logical savings compare bytes of content. Disk usage also includes replicas, checksum files of about 0.8% of the data, and filesystem rounding. So we report three separate values: derived from metadata, measured by the NameNode, and measured on DataNode disks with `du`.

**30. What are the algorithmic complexities?**
Hashing a file of n bytes is O(n). Fixed-size chunking is O(n), with O(n/c) index lookups for chunk size c, each O(log m) for m stored chunks. Whole-file lookup is O(log m). Reconstruction is O(n) with O(n/c) HDFS reads. Garbage collection scans references, about O(k log k) for k references.

**31. Why authentic source files instead of generated data?**
Generated data can be made to show any result, and a reviewer cannot check it. Real files have real structure, and each is traceable to a public URL with a recorded hash. Any duplicates are explicitly labelled as test copies, so the method is open to inspection.

**32. Why do your savings depend on copies you created yourself?**
Because the goal is to verify the mechanism under controlled conditions: with N exact copies, the saving must be exactly (N-1)/N, and it is. These figures show correctness. They do not predict the duplication found in any real system. We say that in the report.

**33. How does this differ from native HDFS functionality?**
HDFS offers replication, erasure coding and snapshots, but no content-based deduplication between independent files. We add a layer above it: a content index, content-addressed storage, logical files, manifests, reference-aware garbage collection and verification. HDFS is unmodified.

**34. What are the limitations of the implementation?**
One API process, with one job at a time and serialised ingestion. SQLite as the index. Fixed-size chunking only. Each chunk is one small HDFS file. Simple authentication only. Single-host test cluster. A small dataset. All are listed in the report.

**35. How could the system be scaled?**
Replace SQLite with a distributed key-value index. Run deduplication as a background Spark job. Pack chunks into container files. Use content-defined chunking. Add real authentication such as Kerberos. Deploy on real, separate machines.

**36. Why is chunk-mode restore slower than whole-file restore?**
Each chunk needs its own NameNode lookup and DataNode connection, and it is hashed in memory. A whole-file read needs one lookup and streams one block. That per-chunk cost is the price of finer deduplication.

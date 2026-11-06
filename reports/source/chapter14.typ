#import "lib.typ": *

#let A = results("A_unique_files").rows
#let B = results("B_exact_duplicates").rows
#let C = results("C_many_names")
#let D = results("D_chunk_sizes").rows
#let D2 = results("D2_boundary_shift").rows
#let E = results("E_roundtrip").rows
#let F = results("F_shared_deletion").rows
#let H = results("H_replication")
#let I = results("I_before_after").rows
#let J = results("J_failure_handling")
#let environment = json("/benchmarks/results/environment.json")
#let replication-ops = json("/benchmarks/results/replication_operations.json")
#let range(row, key, digits: 1) = num(row.at(key + ".mean"), digits: digits) + " (" + num(row.at(key + ".min"), digits: digits) + "–" + num(row.at(key + ".max"), digits: digits) + ")"
#let mode-name = (raw: "No dedup", file: "Whole file", chunk: "Chunked")

= Result Analysis

== Experiment methodology
All experiments ran on the real cluster: Hadoop #environment.hadoop_version, #environment.live_datanodes DataNodes, replication #environment.default_replication. #environment.deployment Each run used a private HDFS directory and a temporary database. Runs with meaningful timings were repeated three times and report the mean with the observed range. Byte counts were required to be identical across iterations, and the benchmark tool flags any difference; no storage value differed. Directory counts do vary, because raw paths use random IDs, and are reported as means. `scripts/run_benchmarks.py` reproduces these runs.

The evaluation deliberately reports three separate quantities, because they answer different questions:

- *Derived (logical):* bytes of content, from the metadata database. Excludes replication and all overhead.
- *Measured by the NameNode:* `GETCONTENTSUMMARY`. `spaceConsumed` is the file length multiplied by replication. It excludes checksums and filesystem rounding.
- *Measured on disk:* `du` over each DataNode's data directory, summed. This includes block files, `.meta` checksum files and 4 KiB filesystem rounding.

Two measurement problems were found and corrected. The first benchmark run produced impossible negative values for files added. The cause was that NameNode JMX values are cached for about ten seconds, and also describe the whole cluster. These values were replaced by uncached queries for each run's own directory. Disk readings were also inconsistent, because DataNodes delete blocks asynchronously after the NameNode's delete returns, so a baseline could include earlier blocks. Each disk reading is now taken only after `du` returns the same value three times, three seconds apart. All results below come from the corrected run.

== Formulas
Savings and ratio follow Equations 1 and 2 in Chapter 10. For $N$ identical copies of each file, whole-file deduplication should give savings of exactly $(N-1) slash N$ and a ratio of $N$.

== Unique files (Experiment A)
With only distinct files, deduplication has nothing to find: savings were #pct(A.at(0).savings_percent) in whole-file mode and #pct(A.at(1).savings_percent) in chunk mode at 1 MiB. Chunk mode used #A.at(1).hdfs_file_count HDFS files where whole-file mode used #A.at(0).hdfs_file_count. This is the correct control result.

== Exact duplicates (Experiments B and C)

#figure(
  table(columns: (auto, auto, auto, auto, auto, auto, auto, auto),
    align: (right, left, right, right, right, right, right, right),
    table.header([*Copies*], [*Mode*], [*Logical*], [*Stored*], [*Savings*], [*Ratio*], [*NameNode space*], [*Upload MiB/s*]),
    ..B.map(r => (str(r.copies), mode-name.at(r.mode), mib(r.logical_bytes), mib(r.stored_content_bytes), pct(r.savings_percent), num(r.dedup_ratio), mib(r.hdfs_space_consumed_bytes), range(r, "upload_throughput_mib_s"))).flatten(),
  ),
  caption: [Nine authentic books with $N - 1$ labelled exact copies each. Upload shows the mean and observed range of three runs.],
  placement: auto,
  scope: "parent",
) <tab-exact>

@tab-exact shows that savings match theory exactly: with 1, 3 and 5 extra copies, $N$ is 2, 4 and 6, and savings are 50%, 75% and 83.33%. NameNode-reported space stays flat at #mib(B.at(1).hdfs_space_consumed_bytes) regardless of copies, while without deduplication it grows linearly. @fig-exact shows this. Replication stays at 3 throughout.

#chart("exact_duplicates_space.svg", [Measured HDFS space for exact duplicates], width: 100%, wide: false) <fig-exact>

Deduplication also made these uploads faster, since a duplicate only needs a lookup and a commit. That comes from the workload's high duplicate rate, and it should not be read as a general speed advantage.

In Experiment C, #C.extra.logical_names logical names for _#C.extra.source;_ produced #C.rows.at(0).hdfs_file_count HDFS file and savings of #pct(C.rows.at(0).savings_percent). All #C.rows.at(0).at("verification.files_passed") names passed SHA-256 verification.

== Chunk-level deduplication (Experiment D)
This workload contains the #D.at(0).logical_files files of the originals plus the three documented variants. @tab-chunks and @fig-tradeoff show results at each chunk size.

#let base = D.at(0).at("disk_used_delta.mean")
#figure(
  table(columns: (auto, auto, auto, auto, auto, auto, auto, auto),
    align: (left, right, right, right, right, right, right, right),
    table.header([*Chunk size*], [*Stored*], [*Logical savings*], [*HDFS files*], [*NameNode objects*], [*Disk used (du)*], [*Disk vs whole-file*], [*Upload MiB/s*]),
    ..D.map(r => (size-label(r.chunk_size), mib(r.stored_content_bytes), pct(r.savings_percent), str(r.hdfs_file_count), str(calc.round(r.at("namespace_objects.mean"))), mib(r.at("disk_used_delta.mean")), (if r.chunk_size == none { "baseline" } else { let c = (r.at("disk_used_delta.mean") - base) / base * 100; (if c > 0 { "+" } else { "" }) + num(c) + "%" }), range(r, "upload_throughput_mib_s"))).flatten(),
  ),
  caption: [The same files at each chunk size. Disk is `du` across three DataNodes, including replicas.],
  placement: auto,
  scope: "parent",
) <tab-chunks>

#chart("chunk_size_tradeoff.svg", [Chunk size trade-off, measured. Bars on throughput show the observed range across three runs.], width: 92%) <fig-tradeoff>

Three findings stand out. First, finer chunks find more overlap, but with diminishing returns. Second, chunks of 1 MiB and larger find nothing at all, because the book and its variants are smaller than one chunk, so each is a single differing chunk. Third, and most important, *logical savings overstate physical savings at small chunk sizes*. At 16 KiB, logical savings are #pct(D.at(1).savings_percent), but actual disk use is #num((D.at(1).at("disk_used_delta.mean") - base) / base * 100)% _higher_ than whole-file storage, because of filesystem rounding and a separate checksum file for every chunk replica. For this workload, 256 KiB gave the lowest disk use among the sizes tested. A system reporting only logical savings would recommend the wrong setting.

Upload throughput falls steeply, because each chunk costs several NameNode and DataNode round trips. The ranges at larger sizes are wide, so small differences between them should not be interpreted.

== Boundary shift (Experiment D2)
@fig-shift isolates fixed-size chunking's weakness at 64 KiB. Truncation reuses #pct(D2.at(0).reuse_percent, digits: 1) of chunks, and a one-byte replacement reuses #pct(D2.at(1).reuse_percent, digits: 1), as only one chunk changes. A single byte inserted at the start reuses #pct(D2.at(2).reuse_percent, digits: 1), since every boundary moves, even though the content is nearly identical. Content-defined chunking @lbfs2001 @fastcdc2016 exists to solve exactly this.

#chart("boundary_shift.svg", [Chunk reuse after three small edits], width: 100%, wide: false) <fig-shift>

== Before and after optimization (Experiment I)
Here, #I.at(0).files files (nine books with two labelled copies each) were first stored without deduplication, then optimized in place. @tab-before and @fig-before show the results.

#figure(
  table(columns: (auto, auto, auto, auto, auto, auto, auto),
    align: (left, right, right, right, right, right, right),
    table.header([*Mode*], [*Stored before / after*], [*Predicted after*], [*NameNode before / after*], [*Disk (du) before / after*], [*HDFS files before / after*], [*Optimize (s)*]),
    ..I.map(r => (if r.chunk_size == none { "Whole file" } else { "Chunk " + size-label(r.chunk_size) }, mib(r.stored_before) + " / " + mib(r.stored_after), mib(r.predicted_stored_after), mib(r.hdfs_space_consumed_before) + " / " + mib(r.hdfs_space_consumed_after), mib(r.at("disk_used_delta_before.mean")) + " / " + mib(r.at("disk_used_delta_after.mean")), str(r.hdfs_files_before) + " / " + str(r.hdfs_files_after), range(r, "optimize_duration_s", digits: 2))).flatten(),
  ),
  caption: [Optimization in place, measured three ways. Optimize shows the mean and range of three runs.],
  placement: auto,
  scope: "parent",
) <tab-before>

#chart("before_after_optimization.svg", [Before and after optimization, as measured by the NameNode and on DataNode disks], width: 80%) <fig-before>

Savings were #pct(I.at(0).savings_percent_after), the expected value for three copies. The dry run predicted stored bytes exactly in both modes. All #I.at(0).at("verification.files_passed") files passed SHA-256 verification afterwards in both modes. Disk use before optimization was #num((I.at(0).at("disk_used_delta_before.mean") / I.at(0).hdfs_space_consumed_before - 1) * 100)% above NameNode-reported space, consistent with HDFS checksums (4 bytes per 512 bytes, about 0.78%) plus rounding. Chunk mode needed #num(I.at(1).at("optimize_duration_s.mean") / I.at(0).at("optimize_duration_s.mean"), digits: 1) times as long as whole-file mode, and it used #I.at(1).hdfs_files_after HDFS files rather than #I.at(0).hdfs_files_after. Exact copies alone offer chunk mode no advantage.

== Restoration (Experiments E and G)
@fig-restore-rate shows restore throughput, with whole-file SHA-256 verification active. All #E.at(0).files files in each mode matched the publisher's bytes on disk: #E.map(r => str(r.files_matching_source_sha256)).join(", ") of #E.at(0).files. Chunked restore is slower, at #num(E.at(2).at("restore_throughput_mib_s.mean"), digits: 1) MiB/s, because each chunk needs its own lookup and connection. The two faster modes overlap within their ranges.

#chart("restore_throughput.svg", [Verified restore throughput], width: 88%, wide: false) <fig-restore-rate>

== Deletion with shared content (Experiment F)
In both modes, purging one of two references left stored bytes unchanged, at #mib(F.at(0).stored_bytes_after_purging_one), and the surviving file passed verification. A soft delete followed by a restore also passed. Purging the last reference left #F.at(0).hdfs_files_after_purging_last HDFS files, so no content leaked.

== Replication (Experiment H)
Changing the factor from 3 to 2 and back, on real data, gave measured multipliers of #H.rows.map(r => num(r.multiplier)).join(", "), with zero under-replicated blocks once converged. Requesting a factor of #(H.extra.live_datanodes + 1) with #H.extra.live_datanodes live DataNodes was refused.

Scale matters here. During the evidence capture, on a namespace of #replication-ops.at(0).files_total chunk files, lowering the factor took #num(replication-ops.at(1).duration_seconds, digits: 0) s, and raising it took #num(replication-ops.at(0).duration_seconds, digits: 0) s. The NameNode schedules about $2 times$ live DataNodes blocks every 3 seconds for re-replication, so every extra small file also lengthens recovery. An earlier fixed 180-second timeout reported this correct behaviour as a failure, so the timeout now scales with the number of blocks.

== Failure handling (Experiment J)
These were real failures, run with `scripts/run_failure_experiments.py`. Containers were stopped, and a process was killed with `SIGKILL`.

*DataNode failure.* After stopping a DataNode, files in both modes stayed readable and matched their hashes. The NameNode flagged it as dead after #num(J.J1_datanode_failure.seconds_until_namenode_declared_dead, digits: 0) s. `fsck` reported #J.J1_datanode_failure.fsck_while_dead.at(0).replace("\t", " ") only #num(J.J1_datanode_failure.further_seconds_until_fsck_reports_under_replication, digits: 1) s later, because replicas are removed from the block map on the heartbeat checker's own cycle. With no spare node, these blocks stayed under-replicated until the node returned. A request for factor 3 with two live nodes returned HTTP #J.J1_datanode_failure.replication_factor_3_request_while_two_live_http_status.

*NameNode failure.* An upload returned HTTP #J.J2_namenode_failure.upload_http_status_during_outage (#raw(J.J2_namenode_failure.upload_error_code)) in #num(J.J2_namenode_failure.upload_failed_in_seconds, digits: 3) s. The logical file count stayed at #J.J2_namenode_failure.logical_files_during_outage, the API kept answering, and the failure appeared in the audit trail. After a restart, a retry returned HTTP #J.J2_namenode_failure.retry_after_restart_http_status.

*Process killed during optimization.* The backend was killed with `SIGKILL` at progress #J.J3_process_kill.killed_at_progress. On restart the job was marked #J.J3_process_kill.job_status_after_restart. Before resuming, #J.J3_process_kill.files_passing_sha256_before_resume of #J.J3_process_kill.files test files passed SHA-256, and reconciliation found #J.J3_process_kill.missing_found_before_resume missing paths. The resumed job processed the remaining #J.J3_process_kill.resumed_job_files_processed files, and #J.J3_process_kill.files_restored_byte_identical_after_resume of #J.J3_process_kill.files then restored byte-identical, with #J.J3_process_kill.orphans_after_resume orphans left. The database and HDFS agreed afterwards.

== Small-file overhead
At 16 KiB, this #mib(D.at(0).logical_bytes) workload needed #str(calc.round(D.at(1).at("namespace_objects.mean"))) NameNode objects, against #str(calc.round(D.at(0).at("namespace_objects.mean"))) for whole files. Using the 150-byte rule of thumb @smallfiles as an *estimate*, 1 TiB of unique data at 64 KiB means about 16.8 million chunks, so about 33.6 million file and block objects and roughly 4.7 GiB of NameNode heap. That is an extrapolation and was not measured. It shows why packing chunks into containers is the most valuable next step.

== Logical savings versus physical usage
The values differ for four reasons, all observed here. Replication multiplies data ($times 3$ here). Checksums and rounding add to it, by about 1% for large files and much more for small ones. Deletion is asynchronous, so disk use falls some time after the metadata says it should. And metadata has its own cost in the NameNode, which `du` on DataNodes does not show at all.

== Timing validity
Timings come from one laptop running everything in a single VM, in an uncontrolled desktop environment, with three repetitions. The wide ranges in some rows reflect that. They support comparisons across large differences, such as chunk size, but not small ones, and they do not predict the performance of a real cluster.

== Summary of observations
- Exact-duplicate savings match theory exactly, and hold in space measured by HDFS and on disk.
- Dry-run predictions of stored bytes were exact.
- Every restored file, in every experiment, matched its original SHA-256.
- Replication was unaffected by deduplication.
- Small chunks can make physical use worse while logical savings look better.
- No data was lost in any failure tested.

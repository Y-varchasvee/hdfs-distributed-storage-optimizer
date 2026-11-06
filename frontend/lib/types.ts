// Shapes returned by the FastAPI backend. See http://localhost:8100/docs for the full API.

export type StorageMode = "raw" | "file" | "chunk";

export interface LogicalFile {
  id: string;
  name: string;
  folder: string;
  size_bytes: number;
  sha256: string;
  mime_type: string | null;
  extension: string | null;
  storage_mode: StorageMode;
  status: "active" | "deleted" | "purged";
  provenance_label: string;
  created_at: string;
  deleted_at: string | null;
  last_verified_at: string | null;
  last_verified_ok: boolean | null;
  logical_references: number;
  is_duplicate: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface IntegrityCheck {
  id: number;
  file_id: string;
  ok: boolean;
  expected_sha256: string;
  actual_sha256: string | null;
  bytes_read: number;
  chunks_checked: number;
  missing: string[] | null;
  corrupt: string[] | null;
  detail: string | null;
  duration_ms: number;
  checked_at: string;
}

export interface FileDetail extends LogicalFile {
  hdfs_paths: string[];
  same_content_files: { id: string; name: string; folder: string; status: string; provenance_label: string }[];
  chunk_size: number | null;
  chunk_count: number | null;
  chunks: { ordinal: number; offset_bytes: number; sha256: string; size_bytes: number; shared_by_manifests: number }[];
  integrity_history: IntegrityCheck[];
  block_locations: { block_id: number; length: number; hosts: string[]; corrupt: boolean }[] | null;
  dataset_source: DatasetSource | null;
}

export interface UploadResult {
  file: LogicalFile;
  outcome: "stored_new" | "duplicate_reference" | "chunks_shared" | "stored_raw";
  duplicate_of_existing: boolean;
  bytes_written: number;
  chunks_total: number;
  chunks_new: number;
  chunks_reused: number;
  hash_ms: number;
  store_ms: number;
  total_ms: number;
}

export interface DerivedStats {
  logical_files: number;
  logical_bytes: number;
  unique_files: number;
  unique_content_bytes: number;
  duplicate_files: number;
  deleted_retained_files: number;
  deleted_retained_bytes: number;
  raw_files: number;
  raw_bytes: number;
  object_count: number;
  object_bytes: number;
  chunk_count: number;
  chunk_bytes: number;
  manifest_count: number;
  manifest_bytes: number;
  chunk_references: number;
  duplicate_chunk_references: number;
  stored_content_bytes: number;
  bytes_avoided: number;
  savings_percent: number | null;
  dedup_ratio: number | null;
  files_by_mode: Partial<Record<StorageMode, number>>;
}

export interface MeasuredArea {
  length: number;
  space_consumed: number;
  file_count: number;
}

export type MeasuredStats =
  | { available: false; error: string }
  | {
      available: true;
      length: number;
      space_consumed: number;
      file_count: number;
      directory_count: number;
      areas: Record<"objects" | "chunks" | "manifests" | "raw" | "staging" | "recovery", MeasuredArea>;
    };

export interface FullStatistics {
  derived: DerivedStats;
  measured: MeasuredStats;
  estimated: { replication_factor: number | null; replication_adjusted_bytes: number | null; note: string };
}

export interface ClusterStatusUp {
  reachable: true;
  checked_at: string;
  namenode_url: string;
  health: "healthy" | "degraded" | "critical";
  problems: string[];
  namenode: {
    state: string;
    role: string;
    host_and_port: string;
    software_version: string;
    cluster_id: string;
    block_pool_id: string;
    fs_state: string;
    safemode: boolean;
    safemode_message: string | null;
  };
  capacity: { total_bytes: number; used_bytes: number; remaining_bytes: number; non_dfs_used_bytes: number };
  namespace: {
    files_total: number;
    blocks_total: number;
    under_replicated_blocks: number;
    missing_blocks: number;
    corrupt_blocks: number;
    pending_replication_blocks: number;
    pending_deletion_blocks: number;
    excess_blocks: number;
  };
  datanodes: { live: number; dead: number; stale: number; decommissioning: number };
}

export type ClusterStatus = ClusterStatusUp | { reachable: false; error: string; checked_at: string; namenode_url: string };

export interface DataNode {
  name: string;
  transfer_address: string;
  state: "live" | "dead";
  last_contact_seconds: number | null;
  capacity_bytes: number | null;
  used_bytes: number | null;
  remaining_bytes: number | null;
  non_dfs_used_bytes: number | null;
  blocks: number | null;
  version: string | null;
  admin_state: string | null;
  rack: string | null;
}

export interface Fsck {
  status: string | null;
  total_files: number | null;
  total_blocks: number | null;
  over_replicated_blocks: number | null;
  under_replicated_blocks: number | null;
  mis_replicated_blocks: number | null;
  default_replication: number | null;
  average_block_replication: number | null;
  missing_blocks: number | null;
  corrupt_blocks: number | null;
  missing_replicas: number | null;
  datanodes: number | null;
}

export interface ReplicationOperation {
  id: string;
  previous_factor: number | null;
  requested_factor: number;
  status: "pending" | "applied" | "verified" | "timed_out" | "failed";
  files_total: number;
  files_changed: number;
  space_consumed_before: number | null;
  space_consumed_after: number | null;
  error: string | null;
  requested_at: string;
  completed_at: string | null;
}

export type ReplicationStatus =
  | { reachable: false; error: string; target_replication: number | null; operations: ReplicationOperation[] }
  | {
      reachable: true;
      cluster_default_replication: number;
      target_replication: number | null;
      effective_replication: number;
      live_datanodes: number;
      dead_datanodes: number;
      max_supported_replication: number;
      fsck: Fsck;
      stored_length_bytes: number;
      space_consumed_bytes: number;
      measured_replication_multiplier: number | null;
      warnings: string[];
      operations: ReplicationOperation[];
      checked_at: string;
    };

export interface Job<R = Record<string, unknown>> {
  id: string;
  kind: string;
  mode: StorageMode | null;
  chunk_size: number | null;
  status: "queued" | "running" | "succeeded" | "partial" | "failed" | "interrupted";
  progress_done: number;
  progress_total: number;
  message: string | null;
  params: Record<string, unknown> | null;
  result: R | null;
  error: string | null;
  resumed_from_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface AnalysisResult {
  estimated: true;
  catalog_fingerprint: string;
  mode: StorageMode;
  chunk_size: number | null;
  files_eligible: number;
  distinct_contents: number;
  current_logical_bytes: number;
  current_stored_bytes: number;
  predicted_stored_bytes: number;
  predicted_reduction_bytes: number;
  predicted_savings_percent: number | null;
  new_content_bytes: number;
  chunks_examined: number;
  chunks_new: number;
  chunks_reused: number;
  actions: {
    id: string;
    name: string;
    folder: string;
    sha256: string;
    size_bytes: number;
    storage_mode: StorageMode;
    action: string;
  }[];
  actions_truncated: boolean;
}

export interface MetricsPair {
  derived: DerivedStats;
  measured: MeasuredStats;
}

export interface OptimizeResult {
  estimated: false;
  files_processed: number;
  files_failed: number;
  errors: { file_id: string; error: string }[];
  orphans_left: string[];
  chunks_new: number;
  before: MetricsPair;
  after: MetricsPair;
  bytes_reclaimed: number;
  garbage_collected: { object_count: number; manifest_count: number; chunk_count: number; reclaimable_bytes: number };
  duration_ms: number;
}

export interface DuplicateGroup {
  sha256: string;
  copies: number;
  size_bytes: number;
  logical_bytes: number;
  redundant_logical_bytes: number;
  reclaimable_bytes: number;
  already_deduplicated: boolean;
  members: {
    id: string;
    name: string;
    folder: string;
    storage_mode: StorageMode;
    provenance_label: string;
    created_at: string;
  }[];
}

export interface DuplicateGroups {
  group_count: number;
  duplicate_files: number;
  redundant_logical_bytes: number;
  groups: DuplicateGroup[];
}

export interface SharedChunks {
  shared_chunk_count: number;
  bytes_saved_by_sharing: number;
  chunks: { sha256: string; size_bytes: number; manifests: number; references: number }[];
  manifests: {
    id: string;
    file_sha256: string;
    file_size: number;
    chunk_size: number;
    chunk_count: number;
    logical_files: string[];
    chunk_map: boolean[];
  }[];
  chunk_map_limit: number;
}

export interface Snapshot {
  taken_at: string;
  reason: string;
  logical_files: number;
  logical_bytes: number;
  stored_bytes: number;
  unique_files: number;
  saved_bytes: number;
  savings_percent: number | null;
}

export interface OptimizationRecord {
  job_id: string;
  mode: StorageMode;
  chunk_size: number | null;
  before: MetricsPair;
  after: MetricsPair;
  files_processed: number;
  files_failed: number;
  bytes_reclaimed_logical: number;
  duration_ms: number;
  created_at: string;
}

export interface Overview extends FullStatistics {
  distributions: {
    file_types: { extension: string; files: number; bytes: number }[];
    duplicate_distribution: { copies: number; groups: number }[];
    upload_trend: { day: string; files: number; bytes: number }[];
  };
  integrity: IntegritySummary;
  cluster: ClusterStatus;
}

export interface IntegritySummary {
  checks_total: number;
  checks_passed: number;
  checks_failed: number;
  files_verified_ok: number;
  files_verified_failed: number;
  files_never_verified: number;
}

export interface PerformanceOp {
  operation: string;
  mode: StorageMode | null;
  samples: number;
  bytes: number;
  total_ms: number;
  min_ms: number;
  max_ms: number;
  mean_ms: number;
  throughput_mib_s: number | null;
}

export interface AuditEvent {
  id: number;
  occurred_at: string;
  event_type: string;
  severity: "info" | "warning" | "error";
  entity_type: string | null;
  entity_id: string | null;
  message: string;
  details: Record<string, unknown> | null;
}

export interface DatasetSource {
  id: string;
  title: string;
  author: string | null;
  ebook_id: number | null;
  source_url: string | null;
  download_url: string | null;
  organization: string | null;
  downloaded_at: string | null;
  file_format: string;
  size_bytes: number;
  sha256: string;
  kind: "original" | "workload_copy" | "transformed";
  derived_from_id: string | null;
  transformation: string | null;
  license_note: string | null;
  local_present: boolean | null;
}

export interface DatasetList {
  items: DatasetSource[];
  catalog: { ebook_id: number; title: string; author: string; formats: string[]; source_url: string }[];
  transformations: Record<string, string>;
}

export interface ExperimentRun {
  id: string;
  scenario: string;
  status: "running" | "succeeded" | "failed";
  result: ({ description?: string; rows?: Record<string, unknown>[]; duration_s?: number } & Record<string, unknown>) | null;
  error: string | null;
  job_id: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface Experiments {
  scenarios: { id: string; title: string; description: string }[];
  runs: ExperimentRun[];
}

export interface SettingsView {
  values: {
    default_ingest_mode: StorageMode;
    default_chunk_size: number;
    verify_on_write: boolean;
    target_replication: number | null;
  };
  connection: {
    namenode_url: string;
    hdfs_user: string;
    root_path: string;
    datanode_host_map: Record<string, string>;
    source: string;
  };
  limits: { min_chunk_size: number; max_chunk_size: number; max_upload_bytes: number };
  storage: { database_path: string; database_bytes: number | null };
}

export interface Diagnostics {
  ok: boolean;
  checks: { name: string; ok: boolean; detail: string; ms: number }[];
}

export interface GarbageReport {
  object_count: number;
  manifest_count: number;
  chunk_count: number;
  reclaimable_bytes: number;
  removed: boolean;
}

export interface ReconcileReport {
  paths_expected: number;
  paths_present: number;
  orphans: string[];
  orphan_count: number;
  missing: string[];
  missing_count: number;
  orphans_quarantined: number;
}

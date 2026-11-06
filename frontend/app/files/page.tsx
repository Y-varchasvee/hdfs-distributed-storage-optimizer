"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { keepPreviousData } from "@tanstack/react-query";
import {
  ArchiveRestore,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Folder,
  Loader2,
  OctagonAlert,
  Search,
  ShieldCheck,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { toast } from "sonner";

import { Choice, EmptyState, ErrorNotice, HashText, KeyValue, Notice, PageHeader, Panel, ProgressBar, RowsSkeleton, Status } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { API_URL, api, del, post, uploadFile } from "@/lib/api";
import { CHUNK_SIZES, chunkSizeLabel, formatBytes, formatDateTime, formatMs, MODE_LABEL, PROVENANCE_LABEL } from "@/lib/format";
import type { FileDetail, IntegrityCheck, LogicalFile, Page, SettingsView, StorageMode, UploadResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const OUTCOME_TEXT: Record<UploadResult["outcome"], string> = {
  stored_new: "New content stored",
  duplicate_reference: "Duplicate: no new data stored",
  chunks_shared: "Stored; shares chunks with existing files",
  stored_raw: "Stored without deduplication",
};

interface UploadItem {
  key: string;
  name: string;
  size: number;
  sent: number;
  state: "queued" | "sending" | "storing" | "done" | "failed";
  result?: UploadResult;
  error?: string;
}

function Uploader({ folder, onUploaded }: { folder: string; onUploaded: () => void }) {
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsView>("/api/v1/settings") });
  const [items, setItems] = useState<UploadItem[]>([]);
  const [mode, setMode] = useState<StorageMode | null>(null);
  const [chunkSize, setChunkSize] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const activeMode = mode ?? settings.data?.values.default_ingest_mode ?? "file";
  const activeChunk = chunkSize ?? settings.data?.values.default_chunk_size ?? 1024 * 1024;

  const update = (key: string, patch: Partial<UploadItem>) => setItems((list) => list.map((item) => (item.key === key ? { ...item, ...patch } : item)));

  const start = useCallback(
    async (files: File[]) => {
      const added = files.map((file, index) => ({ key: `${Date.now()}-${index}-${file.name}`, name: file.name, size: file.size, sent: 0, state: "queued" as const }));
      setItems((list) => [...added, ...list].slice(0, 30));
      // One at a time: the server stores uploads serially, and per-file progress stays meaningful.
      for (const [index, file] of files.entries()) {
        const key = added[index].key;
        update(key, { state: "sending" });
        try {
          const result = await uploadFile(file, {
            folder,
            mode: activeMode,
            chunkSize: activeMode === "chunk" ? activeChunk : undefined,
            onProgress: (fraction) => update(key, { sent: fraction, state: fraction >= 1 ? "storing" : "sending" }),
          });
          update(key, { state: "done", sent: 1, result });
        } catch (error) {
          update(key, { state: "failed", error: error instanceof Error ? error.message : "Upload failed" });
        }
        onUploaded();
      }
    },
    [folder, activeMode, activeChunk, onUploaded],
  );

  return (
    <Panel
      title="Upload"
      subtitle={`Into ${folder}`}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <Choice
            ariaLabel="Storage mode for new uploads"
            value={activeMode}
            onChange={setMode}
            options={[
              { value: "file", label: "Whole-file dedup" },
              { value: "chunk", label: "Chunk-level dedup" },
              { value: "raw", label: "No dedup (baseline)" },
            ]}
          />
          {activeMode === "chunk" && (
            <Choice
              ariaLabel="Chunk size"
              value={String(activeChunk)}
              onChange={(v) => setChunkSize(Number(v))}
              options={[...CHUNK_SIZES, ...(CHUNK_SIZES.some((c) => c.value === activeChunk) ? [] : [{ value: activeChunk, label: chunkSizeLabel(activeChunk) }])].map((c) => ({
                value: String(c.value),
                label: c.label,
              }))}
            />
          )}
        </div>
      }
    >
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length) start(Array.from(e.dataTransfer.files));
        }}
        className={cn("flex flex-col items-center justify-center rounded-md border border-dashed px-4 py-6 text-center transition-colors", dragging ? "border-series-1 bg-series-1/5" : "border-input")}
      >
        <Upload className="mb-2 size-5 text-muted-foreground" aria-hidden />
        <p className="text-[13px]">Drag files here, or</p>
        <Button size="sm" variant="outline" className="mt-2" onClick={() => input.current?.click()}>
          Choose files
        </Button>
        <input
          ref={input}
          data-testid="file-input"
          type="file"
          multiple
          className="sr-only"
          aria-label="Choose files to upload"
          onChange={(e) => {
            if (e.target.files?.length) start(Array.from(e.target.files));
            e.target.value = "";
          }}
        />
      </div>
      {items.length > 0 && (
        <ul className="mt-3 divide-y" aria-live="polite">
          {items.map((item) => (
            <li key={item.key} className="py-2 first:pt-0 last:pb-0">
              <div className="flex items-center justify-between gap-3 text-[13px]">
                <span className="min-w-0 truncate" title={item.name}>
                  {item.name}
                </span>
                <span className="tabular shrink-0 text-xs text-muted-foreground">{formatBytes(item.size)}</span>
              </div>
              {(item.state === "sending" || item.state === "queued") && <ProgressBar value={item.sent} className="mt-1.5" label={`Sending ${item.name}`} />}
              {item.state === "storing" && (
                <p className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="size-3 animate-spin" aria-hidden /> Received. Hashing and writing to HDFS.
                </p>
              )}
              {item.state === "done" && item.result && (
                <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                  <CheckCircle2 className="size-3 text-good" aria-hidden />
                  <span>{OUTCOME_TEXT[item.result.outcome]}</span>
                  <span className="tabular">
                    · {formatBytes(item.result.bytes_written)} written
                    {item.result.chunks_total > 0 && ` · ${item.result.chunks_reused} of ${item.result.chunks_total} chunks reused`} · {formatMs(item.result.total_ms)}
                  </span>
                </p>
              )}
              {item.state === "failed" && (
                <p className="mt-1 flex items-start gap-1.5 text-xs break-words text-muted-foreground">
                  <OctagonAlert className="mt-px size-3 shrink-0 text-critical" aria-hidden /> {item.error}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function VerifyResult({ check }: { check: IntegrityCheck }) {
  return (
    <div className="rounded-md border px-3 py-2 text-xs">
      <Status tone={check.ok ? "good" : "critical"} className="font-medium">
        {check.ok ? "SHA-256 matches" : "Verification failed"}
      </Status>
      <p className="mt-1 text-muted-foreground">
        {formatDateTime(check.checked_at)} · {formatBytes(check.bytes_read)} read · {formatMs(check.duration_ms)}
        {check.chunks_checked > 0 && ` · ${check.chunks_checked} chunks`}
      </p>
      {!check.ok && (
        <p className="mt-1 break-words text-muted-foreground">
          {check.missing && `${check.missing.length} missing. `}
          {check.corrupt && `${check.corrupt.length} corrupt. `}
          {check.detail}
        </p>
      )}
    </div>
  );
}

function FileDrawer({ fileId, onClose, onChanged }: { fileId: string | null; onClose: () => void; onChanged: () => void }) {
  const client = useQueryClient();
  const detail = useQuery({ queryKey: ["file", fileId], queryFn: () => api<FileDetail>(`/api/v1/files/${fileId}`), enabled: !!fileId });
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmPurge, setConfirmPurge] = useState(false);
  const file = detail.data;

  const run = async (name: string, action: () => Promise<unknown>, done?: string) => {
    setBusy(name);
    try {
      await action();
      if (done) toast.success(done);
      await client.invalidateQueries({ queryKey: ["file", fileId] });
      onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "That failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <Sheet open={!!fileId} onOpenChange={(open) => !open && onClose()}>
      <SheetContent side="right" className="w-full gap-0 overflow-y-auto sm:max-w-lg">
        <SheetHeader className="border-b">
          <SheetTitle className="truncate pr-6 text-sm" title={file?.name}>
            {file?.name ?? "File details"}
          </SheetTitle>
          <SheetDescription className="text-xs">{file ? `${file.folder} · ${formatBytes(file.size_bytes)}` : "Loading"}</SheetDescription>
        </SheetHeader>
        {detail.isError && (
          <div className="p-4">
            <ErrorNotice error={detail.error} />
          </div>
        )}
        {file && (
          <div className="space-y-5 p-4">
            <div className="flex flex-wrap gap-2">
              {file.status === "active" ? (
                <>
                  <Button size="sm" render={<a href={`${API_URL}/api/v1/files/${file.id}/download`} />}>
                    <Download /> Download
                  </Button>
                  <Button size="sm" variant="outline" disabled={!!busy} onClick={() => run("verify", () => post(`/api/v1/files/${file.id}/verify`))}>
                    {busy === "verify" ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Verify integrity
                  </Button>
                  <Button size="sm" variant="outline" disabled={!!busy} onClick={() => run("delete", () => del(`/api/v1/files/${file.id}`), "File deleted. It can be restored.").then(onClose)}>
                    <Trash2 /> Delete
                  </Button>
                </>
              ) : (
                <>
                  <Button size="sm" disabled={!!busy} onClick={() => run("restore", () => post(`/api/v1/files/${file.id}/restore`), "File restored.").then(onClose)}>
                    <ArchiveRestore /> Restore
                  </Button>
                  <Button size="sm" variant="destructive" disabled={!!busy} onClick={() => setConfirmPurge(true)}>
                    <Trash2 /> Delete permanently
                  </Button>
                </>
              )}
            </div>

            <KeyValue
              rows={[
                { label: "SHA-256", value: <HashText hash={file.sha256} length={16} /> },
                {
                  label: "Stored as",
                  value: `${MODE_LABEL[file.storage_mode]}${file.chunk_size ? `, ${file.chunk_count} chunks of ${chunkSizeLabel(file.chunk_size)}` : ""}`,
                },
                { label: "Logical references", value: `${file.logical_references}` },
                { label: "Origin", value: PROVENANCE_LABEL[file.provenance_label] ?? file.provenance_label },
                { label: "Uploaded", value: formatDateTime(file.created_at) },
                ...(file.deleted_at ? [{ label: "Deleted", value: formatDateTime(file.deleted_at) }] : []),
              ]}
            />

            <section>
              <h3 className="mb-1.5 text-xs font-medium">Location in HDFS</h3>
              {file.hdfs_paths.map((path) => (
                <p key={path} className="font-mono text-[11px] break-all text-muted-foreground">
                  {path}
                </p>
              ))}
              {file.block_locations?.map((block) => (
                <p key={block.block_id} className="mt-1 text-xs text-muted-foreground">
                  Block {block.block_id} ({formatBytes(block.length)}): replicas on {block.hosts.join(", ") || "no live DataNode"}
                </p>
              ))}
              {file.storage_mode === "chunk" && <p className="mt-1 text-xs text-muted-foreground">Each chunk below is its own HDFS file, with its own blocks and replicas.</p>}
            </section>

            {file.dataset_source && (
              <section>
                <h3 className="mb-1.5 text-xs font-medium">Dataset provenance</h3>
                <p className="text-xs text-muted-foreground">
                  {file.dataset_source.title}
                  {file.dataset_source.source_url && (
                    <>
                      {" · "}
                      <a className="underline underline-offset-2" href={file.dataset_source.source_url} target="_blank" rel="noreferrer">
                        source
                      </a>
                    </>
                  )}
                </p>
              </section>
            )}

            {file.same_content_files.length > 0 && (
              <section>
                <h3 className="mb-1.5 text-xs font-medium">Files with identical content</h3>
                <ul className="space-y-0.5 text-xs text-muted-foreground">
                  {file.same_content_files.slice(0, 12).map((other) => (
                    <li key={other.id} className="truncate">
                      {other.folder === "/" ? "/" : `${other.folder}/`}
                      {other.name}
                      {other.status === "deleted" && " (deleted, restorable)"}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {file.chunks.length > 0 && (
              <section>
                <h3 className="mb-1.5 text-xs font-medium">Chunks</h3>
                <div className="max-h-44 overflow-auto rounded-md border">
                  <table className="w-full text-[11px]">
                    <thead className="sticky top-0 bg-card text-muted-foreground">
                      <tr className="border-b text-left">
                        <th className="px-2 py-1 font-medium">#</th>
                        <th className="px-2 py-1 font-medium">SHA-256</th>
                        <th className="px-2 py-1 text-right font-medium">Size</th>
                        <th className="px-2 py-1 text-right font-medium">Used by</th>
                      </tr>
                    </thead>
                    <tbody className="tabular">
                      {file.chunks.map((chunk) => (
                        <tr key={chunk.ordinal} className="border-b last:border-0">
                          <td className="px-2 py-0.5">{chunk.ordinal}</td>
                          <td className="px-2 py-0.5 font-mono">{chunk.sha256.slice(0, 16)}</td>
                          <td className="px-2 py-0.5 text-right">{formatBytes(chunk.size_bytes)}</td>
                          <td className="px-2 py-0.5 text-right">
                            {chunk.shared_by_manifests} {chunk.shared_by_manifests === 1 ? "manifest" : "manifests"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            <section>
              <h3 className="mb-1.5 text-xs font-medium">Integrity history</h3>
              {file.integrity_history.length === 0 ? (
                <p className="text-xs text-muted-foreground">Not verified since upload. Verify reads every byte back from HDFS.</p>
              ) : (
                <div className="space-y-2">
                  {file.integrity_history.slice(0, 4).map((check) => (
                    <VerifyResult key={check.id} check={check} />
                  ))}
                </div>
              )}
            </section>
          </div>
        )}

        <Dialog open={confirmPurge} onOpenChange={setConfirmPurge}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete {file?.name} permanently?</DialogTitle>
              <DialogDescription>
                This cannot be undone. Shared content stays while other files use it{file && file.logical_references > 1 ? ` (${file.logical_references - 1} other reference${file.logical_references > 2 ? "s" : ""} exist)` : ""}. Content nothing else uses is removed from HDFS.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setConfirmPurge(false)}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={() => {
                  setConfirmPurge(false);
                  if (file) run("purge", () => del(`/api/v1/files/${file.id}?permanent=true`), "Permanently removed.").then(onClose);
                }}
              >
                Delete permanently
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </SheetContent>
    </Sheet>
  );
}

type SortKey = "name" | "size" | "created" | "mode";

function SortHeader({ label, column, sort, order, onSort, align }: { label: string; column: SortKey; sort: SortKey; order: "asc" | "desc"; onSort: (c: SortKey) => void; align?: "right" }) {
  const active = sort === column;
  return (
    <th className={cn("px-3 py-2 font-medium", align === "right" && "text-right")} aria-sort={active ? (order === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" onClick={() => onSort(column)} className={cn("inline-flex items-center gap-1 hover:text-foreground", active && "text-foreground")}>
        {label}
        {active && (order === "asc" ? <ArrowUp className="size-3" aria-hidden /> : <ArrowDown className="size-3" aria-hidden />)}
      </button>
    </th>
  );
}

export default function FilesPage() {
  const client = useQueryClient();
  const [folder, setFolder] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<"active" | "deleted">("active");
  const [mode, setMode] = useState("all");
  const [duplicatesOnly, setDuplicatesOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("created");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const pageSize = 25;

  const params = new URLSearchParams({ status, sort, order, page: String(page), page_size: String(pageSize) });
  if (folder) params.set("folder", folder);
  if (search) params.set("q", search);
  if (mode !== "all") params.set("mode", mode);
  if (duplicatesOnly) params.set("duplicates_only", "true");

  const files = useQuery({
    queryKey: ["files", params.toString()],
    queryFn: () => api<Page<LogicalFile>>(`/api/v1/files?${params}`),
    placeholderData: keepPreviousData,
  });
  const folders = useQuery({ queryKey: ["folders"], queryFn: () => api<{ folders: { path: string; files: number; bytes: number }[] }>("/api/v1/files/folders") });

  const refresh = useCallback(() => {
    client.invalidateQueries({ queryKey: ["files"] });
    client.invalidateQueries({ queryKey: ["folders"] });
    client.invalidateQueries({ queryKey: ["overview"] });
  }, [client]);

  const onSort = (column: SortKey) => {
    setPage(1);
    if (sort === column) setOrder(order === "asc" ? "desc" : "asc");
    else {
      setSort(column);
      setOrder(column === "name" ? "asc" : "desc");
    }
  };

  const totalPages = files.data ? Math.max(1, Math.ceil(files.data.total / pageSize)) : 1;
  const uploadFolder = folder ?? "/";
  const filtering = !!search || mode !== "all" || duplicatesOnly || status === "deleted";

  return (
    <>
      <PageHeader title="Files" description="Logical files. Each resolves to stored content in HDFS, so several files can share the same bytes." />

      <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
        <div className="space-y-4">
          <Panel title="Folders" flush>
            <ul className="px-2 pb-2">
              <li>
                <button
                  type="button"
                  onClick={() => {
                    setFolder(null);
                    setPage(1);
                  }}
                  className={cn("flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[13px] hover:bg-accent", folder === null && "bg-accent font-medium")}
                >
                  <Folder className="size-3.5 shrink-0 text-muted-foreground" aria-hidden /> All folders
                </button>
              </li>
              {folders.data?.folders.map((item) => (
                <li key={item.path}>
                  <button
                    type="button"
                    onClick={() => {
                      setFolder(item.path);
                      setPage(1);
                    }}
                    className={cn("flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-[13px] hover:bg-accent", folder === item.path && "bg-accent font-medium")}
                    style={{ paddingLeft: 8 + (item.path.split("/").filter(Boolean).length - 1) * 10 }}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <Folder className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      <span className="truncate">{item.path}</span>
                    </span>
                    <span className="tabular shrink-0 text-[11px] text-muted-foreground">{item.files}</span>
                  </button>
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        <div className="min-w-0 space-y-4">
          <Uploader folder={uploadFolder} onUploaded={refresh} />

          <Panel flush>
            <div className="flex flex-wrap items-center gap-2 border-b p-3">
              <div className="relative min-w-40 flex-1">
                <Search className="absolute top-2 left-2 size-4 text-muted-foreground" aria-hidden />
                <Input
                  value={search}
                  onChange={(e) => {
                    setSearch(e.target.value);
                    setPage(1);
                  }}
                  placeholder="Search by name or SHA-256 prefix"
                  aria-label="Search files"
                  className="h-8 pl-8 text-[13px]"
                />
                {search && (
                  <button type="button" aria-label="Clear search" className="absolute top-2 right-2 text-muted-foreground hover:text-foreground" onClick={() => setSearch("")}>
                    <X className="size-4" aria-hidden />
                  </button>
                )}
              </div>
              <Choice
                ariaLabel="Filter by storage mode"
                value={mode}
                onChange={(v) => {
                  setMode(v);
                  setPage(1);
                }}
                options={[
                  { value: "all", label: "All modes" },
                  { value: "raw", label: "No dedup" },
                  { value: "file", label: "Whole file" },
                  { value: "chunk", label: "Chunked" },
                ]}
              />
              <Choice
                ariaLabel="Active or deleted files"
                value={status}
                onChange={(v) => {
                  setStatus(v);
                  setPage(1);
                }}
                options={[
                  { value: "active", label: "Active" },
                  { value: "deleted", label: "Recently deleted" },
                ]}
              />
              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <Switch
                  checked={duplicatesOnly}
                  onCheckedChange={(v) => {
                    setDuplicatesOnly(v);
                    setPage(1);
                  }}
                  aria-label="Show only duplicates"
                />
                Duplicates only
              </label>
            </div>

            {files.isError ? (
              <div className="p-4">
                <ErrorNotice error={files.error} onRetry={() => files.refetch()} />
              </div>
            ) : !files.data ? (
              <RowsSkeleton />
            ) : files.data.items.length === 0 ? (
              <EmptyState icon={FileText} title={filtering ? "No files match these filters" : "No files here yet"}>
                {filtering ? "Change or clear the filters." : "Upload a file above, or import the authentic dataset from the Dataset lab."}
              </EmptyState>
            ) : (
              <div className={cn("overflow-x-auto transition-opacity", files.isPlaceholderData && "opacity-60")}>
                <table className="w-full text-[13px]">
                  <thead>
                    <tr className="border-b text-left text-xs text-muted-foreground">
                      <SortHeader label="Name" column="name" sort={sort} order={order} onSort={onSort} />
                      <SortHeader label="Size" column="size" sort={sort} order={order} onSort={onSort} align="right" />
                      <th className="px-3 py-2 font-medium">SHA-256</th>
                      <SortHeader label="Stored as" column="mode" sort={sort} order={order} onSort={onSort} />
                      <th className="px-3 py-2 font-medium">Duplicates</th>
                      <SortHeader label="Uploaded" column="created" sort={sort} order={order} onSort={onSort} />
                    </tr>
                  </thead>
                  <tbody>
                    {files.data.items.map((file) => (
                      <tr key={file.id} className="cursor-pointer border-b last:border-0 hover:bg-accent/50" onClick={() => setSelected(file.id)}>
                        <td className="max-w-72 px-3 py-1.5">
                          <button type="button" className="block max-w-full truncate text-left hover:underline" title={file.name} onClick={() => setSelected(file.id)}>
                            {file.name}
                          </button>
                          <span className="block truncate text-[11px] text-muted-foreground">
                            {file.folder}
                            {file.provenance_label === "workload_copy" && " · workload copy"}
                            {file.provenance_label === "transformed" && " · transformed test file"}
                          </span>
                        </td>
                        <td className="tabular px-3 py-1.5 text-right whitespace-nowrap">{formatBytes(file.size_bytes)}</td>
                        <td className="px-3 py-1.5">
                          <HashText hash={file.sha256} />
                        </td>
                        <td className="px-3 py-1.5 whitespace-nowrap">{MODE_LABEL[file.storage_mode]}</td>
                        <td className="px-3 py-1.5">
                          {file.is_duplicate ? <Badge variant="secondary">{file.logical_references} references</Badge> : <span className="text-xs text-muted-foreground">Unique</span>}
                        </td>
                        <td className="tabular px-3 py-1.5 text-xs whitespace-nowrap text-muted-foreground">{formatDateTime(file.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {files.data && files.data.total > 0 && (
              <div className="flex items-center justify-between border-t px-3 py-2 text-xs text-muted-foreground">
                <span className="tabular">
                  {files.data.total.toLocaleString("en-US")} file{files.data.total === 1 ? "" : "s"}
                </span>
                <div className="flex items-center gap-2">
                  <span className="tabular">
                    Page {page} of {totalPages}
                  </span>
                  <Button variant="outline" size="icon-sm" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                    <ChevronLeft />
                  </Button>
                  <Button variant="outline" size="icon-sm" aria-label="Next page" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
                    <ChevronRight />
                  </Button>
                </div>
              </div>
            )}
          </Panel>

          {status === "deleted" && <Notice>Deleted files keep their content, so they still count towards stored bytes until permanently removed.</Notice>}
        </div>
      </div>

      <FileDrawer fileId={selected} onClose={() => setSelected(null)} onChanged={refresh} />
    </>
  );
}

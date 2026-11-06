"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ArchiveX, Loader2, Recycle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Choice, ErrorNotice, KeyValue, Notice, PageHeader, Panel, RowsSkeleton, Status } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { api, post, put } from "@/lib/api";
import { CHUNK_SIZES, chunkSizeLabel, formatBytes, formatMs } from "@/lib/format";
import type { Diagnostics, GarbageReport, ReconcileReport, SettingsView, StorageMode } from "@/lib/types";

export default function SettingsPage() {
  const client = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingsView>("/api/v1/settings") });
  const [diagnostics, setDiagnostics] = useState<Diagnostics | null>(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const [garbage, setGarbage] = useState<GarbageReport | null>(null);
  const [reconcile, setReconcile] = useState<ReconcileReport | null>(null);
  const [confirm, setConfirm] = useState<null | "gc" | "reconcile">(null);

  const save = async (changes: Record<string, unknown>) => {
    try {
      await put("/api/v1/settings", changes);
      await client.invalidateQueries({ queryKey: ["settings"] });
      toast.success("Saved. This applies to future writes only; stored data is not rewritten.");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not save");
    }
  };

  const runDiagnostics = async () => {
    setDiagnosing(true);
    try {
      setDiagnostics(await api<Diagnostics>("/api/v1/system/diagnostics"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Diagnostics failed");
    } finally {
      setDiagnosing(false);
    }
  };

  const guarded = async <T,>(action: () => Promise<T>, onDone: (value: T) => void) => {
    try {
      onDone(await action());
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "That failed");
    }
  };

  if (settings.isError) {
    return (
      <>
        <PageHeader title="Settings" />
        <ErrorNotice error={settings.error} onRetry={() => settings.refetch()} />
      </>
    );
  }
  if (!settings.data) {
    return (
      <>
        <PageHeader title="Settings" />
        <RowsSkeleton rows={8} />
      </>
    );
  }

  const { values, connection, limits, storage } = settings.data;
  const chunkOptions = CHUNK_SIZES.some((c) => c.value === values.default_chunk_size) ? CHUNK_SIZES : [...CHUNK_SIZES, { value: values.default_chunk_size, label: chunkSizeLabel(values.default_chunk_size) }];

  return (
    <>
      <PageHeader title="Settings" description="Defaults for new data, connection details and maintenance tools." />

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Deduplication defaults" subtitle="Changes apply to future writes. Stored data is never rewritten by a setting.">
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-4">
              <Label className="text-[13px] font-normal">Default upload mode</Label>
              <Choice
                ariaLabel="Default upload mode"
                value={values.default_ingest_mode}
                onChange={(v: StorageMode) => save({ default_ingest_mode: v })}
                options={[
                  { value: "file", label: "Whole-file dedup" },
                  { value: "chunk", label: "Chunk-level dedup" },
                  { value: "raw", label: "No dedup" },
                ]}
              />
            </div>
            <div className="flex items-center justify-between gap-4">
              <div>
                <Label className="text-[13px] font-normal">Default chunk size</Label>
                <p className="mt-0.5 max-w-xs text-xs text-muted-foreground">Smaller finds more overlap but creates more HDFS files, which costs NameNode memory.</p>
              </div>
              <Choice ariaLabel="Default chunk size" value={String(values.default_chunk_size)} onChange={(v) => save({ default_chunk_size: Number(v) })} options={chunkOptions.map((c) => ({ value: String(c.value), label: c.label }))} />
            </div>
            <div className="flex items-center justify-between gap-4">
              <div>
                <Label className="text-[13px] font-normal" htmlFor="verify-on-write">
                  Verify objects on write
                </Label>
                <p className="mt-0.5 max-w-xs text-xs text-muted-foreground">Reads each whole-file object back and checks its SHA-256 before committing it. Slower, but safer.</p>
              </div>
              <Switch id="verify-on-write" checked={values.verify_on_write} onCheckedChange={(v) => save({ verify_on_write: v })} />
            </div>
          </div>
          <div className="mt-4 border-t pt-3">
            <KeyValue
              rows={[
                { label: "Replication target", value: values.target_replication ? `Factor ${values.target_replication}` : "Cluster default. Change it in Replication." },
                { label: "Allowed chunk sizes", value: `${chunkSizeLabel(limits.min_chunk_size)} to ${chunkSizeLabel(limits.max_chunk_size)}` },
                { label: "Upload limit", value: formatBytes(limits.max_upload_bytes) },
              ]}
            />
          </div>
        </Panel>

        <Panel title="HDFS connection" subtitle={connection.source}>
          <KeyValue
            rows={[
              { label: "NameNode", value: <span className="font-mono text-xs">{connection.namenode_url}</span> },
              { label: "HDFS user", value: <span className="font-mono text-xs">{connection.hdfs_user}</span> },
              { label: "Managed root", value: <span className="font-mono text-xs">{connection.root_path}</span> },
              {
                label: "DataNode address map",
                value: Object.keys(connection.datanode_host_map).length ? (
                  <span className="font-mono text-xs">
                    {Object.entries(connection.datanode_host_map).map(([name, target]) => (
                      <span key={name} className="block">
                        {name} → {target}
                      </span>
                    ))}
                  </span>
                ) : (
                  "None (inside the Docker network)"
                ),
              },
              { label: "Metadata database", value: <span className="font-mono text-xs break-all">{storage.database_path}</span> },
              { label: "Database size", value: formatBytes(storage.database_bytes) },
            ]}
          />
        </Panel>

        <Panel
          title="Health checks"
          subtitle="Runs real checks, including a write, read and delete through a DataNode."
          actions={
            <Button size="sm" variant="outline" onClick={runDiagnostics} disabled={diagnosing}>
              {diagnosing ? <Loader2 className="animate-spin" /> : <Activity />} Run diagnostics
            </Button>
          }
        >
          {diagnostics ? (
            <ul className="divide-y">
              {diagnostics.checks.map((check) => (
                <li key={check.name} className="py-2 first:pt-0 last:pb-0">
                  <div className="flex items-center justify-between gap-3">
                    <Status tone={check.ok ? "good" : "critical"}>{check.name}</Status>
                    <span className="tabular text-xs text-muted-foreground">{formatMs(check.ms)}</span>
                  </div>
                  <p className="mt-0.5 pl-5 text-xs break-words text-muted-foreground">{check.detail}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">Not run yet.</p>
          )}
        </Panel>

        <Panel title="Storage maintenance" subtitle="Each action shows what it would do before anything changes.">
          <div className="space-y-4">
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[13px]">Unreferenced content</p>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => guarded(() => api<GarbageReport>("/api/v1/dedup/gc"), setGarbage)}>
                    Preview
                  </Button>
                  <Button size="sm" variant="outline" disabled={!garbage || garbage.reclaimable_bytes + garbage.manifest_count === 0} onClick={() => setConfirm("gc")}>
                    <Recycle /> Collect
                  </Button>
                </div>
              </div>
              {garbage && (
                <p className="tabular mt-1 text-xs text-muted-foreground">
                  {garbage.removed ? "Removed" : "Would remove"} {garbage.object_count} objects, {garbage.manifest_count} manifests and {garbage.chunk_count} chunks ({formatBytes(garbage.reclaimable_bytes)}, before replication). Content a restorable file uses is never included.
                </p>
              )}
            </div>
            <div className="border-t pt-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-[13px]">Compare HDFS with metadata</p>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={() => guarded(() => api<ReconcileReport>("/api/v1/storage/reconcile"), setReconcile)}>
                    Check
                  </Button>
                  <Button size="sm" variant="outline" disabled={!reconcile || reconcile.orphan_count === 0} onClick={() => setConfirm("reconcile")}>
                    <ArchiveX /> Quarantine orphans
                  </Button>
                </div>
              </div>
              {reconcile && (
                <p className="tabular mt-1 text-xs text-muted-foreground">
                  {reconcile.paths_present} files in HDFS, {reconcile.paths_expected} expected. {reconcile.orphan_count} orphaned, {reconcile.missing_count} missing.
                  {reconcile.orphans_quarantined > 0 && ` Moved ${reconcile.orphans_quarantined} to the recovery area.`}
                </p>
              )}
              {reconcile && reconcile.missing_count > 0 && (
                <div className="mt-2">
                  <Notice tone="warning">Some stored content is missing from HDFS. Run integrity verification to see which files are affected.</Notice>
                </div>
              )}
            </div>
          </div>
        </Panel>
      </div>

      <Dialog open={confirm !== null} onOpenChange={(open) => !open && setConfirm(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{confirm === "gc" ? "Remove unreferenced content?" : "Quarantine orphaned files?"}</DialogTitle>
            <DialogDescription>
              {confirm === "gc"
                ? "Content that no file refers to, including no deleted-but-restorable file, is permanently removed from HDFS. The check is repeated at removal time."
                : "Files in HDFS with no matching metadata are moved to the recovery area. Nothing is deleted."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(null)}>
              Cancel
            </Button>
            <Button
              variant={confirm === "gc" ? "destructive" : "default"}
              onClick={() => {
                const action = confirm;
                setConfirm(null);
                if (action === "gc") guarded(() => post<GarbageReport>("/api/v1/dedup/gc"), setGarbage);
                if (action === "reconcile") guarded(() => post<ReconcileReport>("/api/v1/storage/reconcile"), setReconcile);
              }}
            >
              {confirm === "gc" ? "Remove content" : "Quarantine"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

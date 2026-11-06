"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Layers3, Loader2, Minus, Plus } from "lucide-react";
import { useState } from "react";

import { EmptyState, ErrorNotice, KeyValue, Notice, PageHeader, Panel, ProgressBar, ProvenanceTag, RowsSkeleton, Stat, Status } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, post } from "@/lib/api";
import { formatBytes, formatCount, formatDateTime } from "@/lib/format";
import { isFinished, useJob } from "@/lib/queries";
import type { Job, ReplicationStatus } from "@/lib/types";

const OP_TONE = { verified: "good", applied: "busy", pending: "busy", timed_out: "warning", failed: "critical" } as const;
const OP_TEXT = { verified: "Verified", applied: "Applied, converging", pending: "Pending", timed_out: "Did not converge in time", failed: "Failed" } as const;

export default function ReplicationPage() {
  const client = useQueryClient();
  const status = useQuery({ queryKey: ["replication"], queryFn: () => api<ReplicationStatus>("/api/v1/cluster/replication"), refetchInterval: 10_000 });
  const [requested, setRequested] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const job = useJob(jobId, () => client.invalidateQueries({ queryKey: ["replication"] }));
  const running = !!jobId && !isFinished(job.data as Job<unknown> | undefined);
  const data = status.data;

  const submit = async (acknowledge: boolean) => {
    if (!requested) return;
    setConfirming(false);
    setError(null);
    try {
      const response = await post<{ job_id: string }>("/api/v1/cluster/replication", { factor: requested, acknowledge_reduced_protection: acknowledge });
      setJobId(response.job_id);
    } catch (e) {
      setError(e);
    }
  };

  if (status.isError) {
    return (
      <>
        <PageHeader title="Replication manager" />
        <ErrorNotice error={status.error} onRetry={() => status.refetch()} />
      </>
    );
  }
  if (!data) {
    return (
      <>
        <PageHeader title="Replication manager" />
        <RowsSkeleton rows={8} />
      </>
    );
  }
  if (!data.reachable) {
    return (
      <>
        <PageHeader title="Replication manager" />
        <ErrorNotice error={new Error(data.error)} onRetry={() => status.refetch()} />
      </>
    );
  }

  const factor = requested ?? data.effective_replication;
  const lowering = factor < data.effective_replication;
  const changed = factor !== data.effective_replication;

  return (
    <>
      <PageHeader title="Replication manager" description="HDFS keeps block replicas so that data survives a DataNode failure. Replicas are not duplicates: deduplication works above them and never removes one." />

      {data.warnings.length > 0 && (
        <div className="mb-4 space-y-2">
          {data.warnings.map((warning) => (
            <Notice key={warning} tone="warning">
              {warning}
            </Notice>
          ))}
        </div>
      )}

      <Panel className="mb-4">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Stat label="Effective replication" value={`Factor ${data.effective_replication}`} note={data.target_replication ? "Application target" : "Cluster default"} />
          <Stat label="Live DataNodes" value={formatCount(data.live_datanodes)} provenance="measured" note={data.dead_datanodes ? `${data.dead_datanodes} dead` : undefined} />
          <Stat label="Average block replicas" value={data.fsck.average_block_replication?.toFixed(2) ?? "N/A"} provenance="measured" note="fsck" />
          <Stat label="Under-replicated blocks" value={formatCount(data.fsck.under_replicated_blocks)} provenance="measured" note="fsck" />
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Change replication factor" subtitle="Applies to all managed data and to new writes">
          <div className="flex items-center gap-3">
            <Button variant="outline" size="icon" aria-label="Decrease replication factor" disabled={factor <= 1 || running} onClick={() => setRequested(factor - 1)}>
              <Minus />
            </Button>
            <output className="w-10 text-center text-2xl font-semibold" aria-live="polite">
              {factor}
            </output>
            <Button variant="outline" size="icon" aria-label="Increase replication factor" disabled={factor >= data.max_supported_replication || running} onClick={() => setRequested(factor + 1)}>
              <Plus />
            </Button>
            <span className="text-xs text-muted-foreground">Maximum {data.max_supported_replication}, limited by live DataNodes.</span>
          </div>

          <div className="mt-4 rounded-md border p-3">
            <p className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
              Space at factor {factor} <ProvenanceTag kind={changed ? "estimated" : "measured"} />
            </p>
            <p className="text-lg font-semibold tracking-tight">{formatBytes(changed ? data.stored_length_bytes * factor : data.space_consumed_bytes)}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {formatBytes(data.stored_length_bytes)} of data in the managed namespace. Each block survives the loss of {factor - 1} DataNode{factor === 2 ? "" : "s"}.
            </p>
          </div>

          {!!error && (
            <div className="mt-3">
              <ErrorNotice error={error} />
            </div>
          )}
          {running && job.data && (
            <div className="mt-3">
              <p className="mb-1.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="size-3 animate-spin" aria-hidden /> {job.data.message ?? "Queued"}
              </p>
              <ProgressBar value={job.data.progress_total ? job.data.progress_done / job.data.progress_total : 0} label="Replication progress" />
            </div>
          )}

          <Button className="mt-4" size="sm" disabled={!changed || running} onClick={() => (lowering ? setConfirming(true) : submit(false))}>
            Apply factor {factor}
          </Button>
        </Panel>

        <Panel title="Measured state of the managed namespace">
          <KeyValue
            rows={[
              { label: "Cluster default (dfs.replication)", value: data.cluster_default_replication },
              { label: "Data length", value: formatBytes(data.stored_length_bytes) },
              { label: "Space consumed, with replicas", value: formatBytes(data.space_consumed_bytes) },
              { label: "Measured multiplier", value: data.measured_replication_multiplier ? `${data.measured_replication_multiplier.toFixed(2)} ×` : "N/A" },
              { label: "fsck status", value: data.fsck.status ?? "N/A" },
              { label: "Files / blocks checked", value: `${formatCount(data.fsck.total_files)} / ${formatCount(data.fsck.total_blocks)}` },
              { label: "Over-replicated blocks", value: formatCount(data.fsck.over_replicated_blocks) },
              { label: "Missing blocks", value: formatCount(data.fsck.missing_blocks) },
              { label: "Corrupt blocks", value: formatCount(data.fsck.corrupt_blocks) },
            ]}
          />
          <p className="mt-3 text-[11px] text-muted-foreground">Checked {formatDateTime(data.checked_at)}</p>
        </Panel>
      </div>

      <Panel title="Replication changes" className="mt-4" flush>
        {data.operations.length === 0 ? (
          <EmptyState icon={Layers3} title="No replication changes have been made" />
        ) : (
          <div className="overflow-x-auto px-4 pb-3">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">Requested</th>
                  <th className="py-2 pr-3 font-medium">Change</th>
                  <th className="py-2 pr-3 font-medium">Result</th>
                  <th className="py-2 pr-3 text-right font-medium">Files changed</th>
                  <th className="py-2 pr-3 text-right font-medium">Space before</th>
                  <th className="py-2 text-right font-medium">Space after</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {data.operations.map((op) => (
                  <tr key={op.id} className="border-b last:border-0">
                    <td className="py-1.5 pr-3 whitespace-nowrap">{formatDateTime(op.requested_at)}</td>
                    <td className="py-1.5 pr-3 whitespace-nowrap">
                      {op.previous_factor} to {op.requested_factor}
                    </td>
                    <td className="py-1.5 pr-3">
                      <Status tone={OP_TONE[op.status]} className="text-xs">
                        {OP_TEXT[op.status]}
                      </Status>
                    </td>
                    <td className="py-1.5 pr-3 text-right">{formatCount(op.files_changed)}</td>
                    <td className="py-1.5 pr-3 text-right">{formatBytes(op.space_consumed_before)}</td>
                    <td className="py-1.5 text-right">{formatBytes(op.space_consumed_after)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Lower replication to {factor}?</DialogTitle>
            <DialogDescription>
              This reduces fault tolerance: {factor === 1 ? "losing one DataNode could lose data." : `each block will survive the loss of ${factor - 1} DataNode${factor === 2 ? "" : "s"} instead of ${data.effective_replication - 1}.`} It saves space, but it is not deduplication.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={() => submit(true)}>
              Lower to {factor}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

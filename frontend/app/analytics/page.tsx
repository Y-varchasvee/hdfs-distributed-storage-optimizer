"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart3, Download } from "lucide-react";

import { ChartPanel, StorageOverTimeChart } from "@/components/charts";
import { EmptyState, ErrorNotice, PageHeader, Panel, RowsSkeleton, Stat } from "@/components/common";
import { Button } from "@/components/ui/button";
import { API_URL, api } from "@/lib/api";
import { formatBytes, formatCount, formatDateTime, formatMs, formatPercent, formatRatio, MODE_LABEL } from "@/lib/format";
import type { IntegritySummary, OptimizationRecord, Overview, PerformanceOp, Snapshot } from "@/lib/types";

const OPERATION_LABEL: Record<string, string> = {
  hash: "SHA-256 hashing",
  upload: "Upload, end to end",
  chunking: "Chunking and storing",
  restore: "Restore (download)",
  verify: "Integrity verification",
  optimize: "Optimization job",
};

export default function AnalyticsPage() {
  const overview = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/api/v1/analytics/overview") });
  const performance = useQuery({ queryKey: ["performance"], queryFn: () => api<{ operations: PerformanceOp[]; integrity: IntegritySummary }>("/api/v1/analytics/performance") });
  const history = useQuery({ queryKey: ["history"], queryFn: () => api<{ snapshots: Snapshot[]; optimizations: OptimizationRecord[] }>("/api/v1/analytics/history") });

  if (overview.isError) {
    return (
      <>
        <PageHeader title="Analytics" />
        <ErrorNotice error={overview.error} onRetry={() => overview.refetch()} />
      </>
    );
  }
  if (!overview.data) {
    return (
      <>
        <PageHeader title="Analytics" />
        <RowsSkeleton rows={8} />
      </>
    );
  }

  const { derived, measured } = overview.data;
  const operations = performance.data?.operations ?? [];
  const integrity = performance.data?.integrity;
  const restore = operations.filter((o) => o.operation === "restore").reduce((sum, o) => sum + o.samples, 0);
  const throughput = operations
    .filter((o) => o.throughput_mib_s !== null)
    .map((o) => ({ label: `${OPERATION_LABEL[o.operation] ?? o.operation}${o.mode ? `, ${MODE_LABEL[o.mode].toLowerCase()}` : ""}`, value: o.throughput_mib_s as number }))
    .sort((a, b) => b.value - a.value);
  const hashMs = operations.filter((o) => o.operation === "hash").reduce((sum, o) => sum + o.total_ms, 0);
  const uploadMs = operations.filter((o) => o.operation === "upload").reduce((sum, o) => sum + o.total_ms, 0);
  const chunkingMs = operations.filter((o) => o.operation === "chunking").reduce((sum, o) => sum + o.total_ms, 0);

  return (
    <>
      <PageHeader
        title="Analytics and reports"
        description="Volume, deduplication and performance, from measurements recorded by each operation."
        actions={
          <Button size="sm" variant="outline" render={<a href={`${API_URL}/api/v1/analytics/report.csv`} />}>
            <Download /> Download CSV summary
          </Button>
        }
      />

      <Panel className="mb-4">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Logical volume" value={formatBytes(derived.logical_bytes)} provenance="derived" />
          <Stat label="Unique data stored" value={formatBytes(derived.stored_content_bytes)} provenance="derived" />
          <Stat label="Saved bytes" value={formatBytes(derived.bytes_avoided)} provenance="derived" />
          <Stat label="Deduplication rate" value={formatPercent(derived.savings_percent)} provenance="derived" />
          <Stat label="Deduplication ratio" value={formatRatio(derived.dedup_ratio)} provenance="derived" />
          <Stat label="Duplicate files" value={formatCount(derived.duplicate_files)} provenance="derived" />
        </div>
        <div className="mt-4 grid grid-cols-2 gap-4 border-t pt-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="HDFS length" value={measured.available ? formatBytes(measured.length) : "Unavailable"} provenance="measured" />
          <Stat label="HDFS space consumed" value={measured.available ? formatBytes(measured.space_consumed) : "Unavailable"} provenance="measured" />
          <Stat label="HDFS files" value={measured.available ? formatCount(measured.file_count) : "Unavailable"} provenance="measured" />
          <Stat label="Chunks stored" value={formatCount(derived.chunk_count)} provenance="derived" />
          <Stat label="Duplicate chunk refs" value={formatCount(derived.duplicate_chunk_references)} provenance="derived" />
          <Stat label="Manifest metadata" value={formatBytes(derived.manifest_bytes)} provenance="derived" />
        </div>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <ChartPanel
          title="Throughput by operation"
          subtitle="Total bytes divided by total time. Measured on this machine and cluster."
          columns={[
            { key: "label", label: "Operation" },
            { key: "value", label: "MiB/s", align: "right", format: (v: number) => v.toFixed(1) },
          ]}
          rows={throughput}
          empty={<EmptyState icon={BarChart3} title="No operations measured yet" />}
        >
          <ThroughputBars data={throughput} />
        </ChartPanel>
        <ChartPanel
          title="Saved data over time"
          legend={[
            { label: "Logical", color: "var(--chart-label)" },
            { label: "Stored", color: "var(--series-1)" },
          ]}
          columns={[
            { key: "taken_at", label: "Time", format: (v: string) => formatDateTime(v) },
            { key: "logical_bytes", label: "Logical", align: "right", format: (v: number) => formatBytes(v) },
            { key: "stored_bytes", label: "Stored", align: "right", format: (v: number) => formatBytes(v) },
            { key: "saved_bytes", label: "Saved", align: "right", format: (v: number) => formatBytes(v) },
          ]}
          rows={(history.data?.snapshots ?? []) as never}
          empty={<EmptyState title="No snapshots yet" />}
        >
          <StorageOverTimeChart data={history.data?.snapshots ?? []} height={400} />
        </ChartPanel>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Panel title="Measured operations" flush>
          {operations.length === 0 ? (
            <EmptyState title="No operations measured yet" />
          ) : (
            <div className="overflow-x-auto px-4 pb-3">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Operation</th>
                    <th className="py-2 pr-3 font-medium">Mode</th>
                    <th className="py-2 pr-3 text-right font-medium">Samples</th>
                    <th className="py-2 pr-3 text-right font-medium">Bytes</th>
                    <th className="py-2 pr-3 text-right font-medium">Mean</th>
                    <th className="py-2 pr-3 text-right font-medium">Range</th>
                    <th className="py-2 text-right font-medium">MiB/s</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {operations.map((op) => (
                    <tr key={`${op.operation}-${op.mode}`} className="border-b last:border-0">
                      <td className="py-1.5 pr-3 whitespace-nowrap">{OPERATION_LABEL[op.operation] ?? op.operation}</td>
                      <td className="py-1.5 pr-3 whitespace-nowrap">{op.mode ? MODE_LABEL[op.mode] : "N/A"}</td>
                      <td className="py-1.5 pr-3 text-right">{formatCount(op.samples)}</td>
                      <td className="py-1.5 pr-3 text-right">{formatBytes(op.bytes)}</td>
                      <td className="py-1.5 pr-3 text-right">{formatMs(op.mean_ms)}</td>
                      <td className="py-1.5 pr-3 text-right whitespace-nowrap">
                        {formatMs(op.min_ms)} to {formatMs(op.max_ms)}
                      </td>
                      <td className="py-1.5 text-right">{op.throughput_mib_s?.toFixed(1) ?? "N/A"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <div className="space-y-4">
          <Panel title="Integrity and restoration">
            <div className="grid grid-cols-2 gap-4">
              <Stat label="Checks passed" value={integrity ? `${integrity.checks_passed} of ${integrity.checks_total}` : "N/A"} provenance="measured" />
              <Stat label="Checks failed" value={formatCount(integrity?.checks_failed)} provenance="measured" />
              <Stat label="Files never verified" value={formatCount(integrity?.files_never_verified)} />
              <Stat label="Verified restores" value={formatCount(restore)} provenance="measured" note="Downloads that passed SHA-256" />
            </div>
          </Panel>
          <Panel title="Time spent">
            <div className="grid grid-cols-2 gap-4">
              <Stat label="Hashing, all uploads" value={formatMs(hashMs)} provenance="measured" note={uploadMs ? `${((hashMs / uploadMs) * 100).toFixed(1)}% of upload time` : undefined} />
              <Stat label="Chunking and chunk writes" value={formatMs(chunkingMs)} provenance="measured" />
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}

function ThroughputBars({ data }: { data: { label: string; value: number }[] }) {
  // Labels here are long, so they sit above each bar rather than in a narrow axis.
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <ul className="space-y-2">
      {data.map((row) => (
        <li key={row.label}>
          <div className="mb-0.5 flex items-baseline justify-between gap-3 text-xs">
            <span className="truncate text-muted-foreground">{row.label}</span>
            <span className="tabular shrink-0">{row.value.toFixed(1)} MiB/s</span>
          </div>
          <div className="h-2 rounded-r bg-series-1" style={{ width: `${(row.value / max) * 100}%`, minWidth: 2 }} />
        </li>
      ))}
    </ul>
  );
}


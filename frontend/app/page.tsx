"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, FolderTree, Inbox } from "lucide-react";
import Link from "next/link";

import { ColumnChart, ChartPanel, HorizontalBars, ReductionBar, StorageOverTimeChart } from "@/components/charts";
import { EmptyState, ErrorNotice, PageHeader, Panel, ProvenanceTag, RowsSkeleton, Stat, Status, type Provenance } from "@/components/common";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatBytes, formatCount, formatDateTime, formatPercent, formatRatio, formatTime, MODE_LABEL, chunkSizeLabel } from "@/lib/format";
import type { AuditEvent, OptimizationRecord, Overview, Page, Snapshot } from "@/lib/types";

function Ladder({ data }: { data: Overview }) {
  const { derived, measured, estimated } = data;
  const rows: { label: string; hint: string; value: string; kind: Provenance }[] = [
    { label: "Logical data", hint: "What users see: every file at full size", value: formatBytes(derived.logical_bytes), kind: "derived" },
    { label: "Stored content", hint: "Unique data kept, before HDFS replicates it", value: formatBytes(derived.stored_content_bytes), kind: "derived" },
    {
      label: `Replication-adjusted (×${estimated.replication_factor ?? "?"})`,
      hint: "Stored content times the replication factor",
      value: formatBytes(estimated.replication_adjusted_bytes),
      kind: "estimated",
    },
    {
      label: "HDFS space consumed",
      hint: "NameNode content summary, including replicas",
      value: measured.available ? formatBytes(measured.space_consumed) : "Unavailable",
      kind: "measured",
    },
    {
      label: "Metadata in HDFS",
      hint: "Chunk manifests, before replication",
      value: measured.available ? formatBytes(measured.areas.manifests.length) : "Unavailable",
      kind: "measured",
    },
  ];
  return (
    <ul className="divide-y">
      {rows.map((row) => (
        <li key={row.label} className="flex items-center justify-between gap-3 py-2 first:pt-0 last:pb-0">
          <div className="min-w-0">
            <p className="text-[13px]">{row.label}</p>
            <p className="truncate text-[11px] text-muted-foreground">{row.hint}</p>
          </div>
          <div className="shrink-0 text-right">
            <p className="tabular text-[13px] font-medium">{row.value}</p>
            <ProvenanceTag kind={row.kind} />
          </div>
        </li>
      ))}
    </ul>
  );
}

function ClusterCard({ data }: { data: Overview }) {
  const cluster = data.cluster;
  if (!cluster.reachable) {
    return (
      <Panel title="Cluster">
        <Status tone="critical">NameNode unreachable</Status>
        <p className="mt-2 text-xs break-words text-muted-foreground">{cluster.error}</p>
      </Panel>
    );
  }
  const tone = cluster.health === "healthy" ? "good" : cluster.health === "degraded" ? "warning" : "critical";
  return (
    <Panel
      title="Cluster"
      actions={
        <Link href="/cluster" className="text-xs text-muted-foreground hover:text-foreground">
          Details
        </Link>
      }
    >
      <Status tone={tone} className="font-medium">
        {cluster.health === "healthy" ? "Healthy" : cluster.health === "degraded" ? "Degraded" : "Critical"}
      </Status>
      <dl className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-xs">
        <div>
          <dt className="text-muted-foreground">Active DataNodes</dt>
          <dd className="text-[13px] font-medium">
            {cluster.datanodes.live} live{cluster.datanodes.dead ? `, ${cluster.datanodes.dead} dead` : ""}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Replication</dt>
          <dd className="text-[13px] font-medium">Factor {data.estimated.replication_factor ?? "N/A"}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Under-replicated</dt>
          <dd className="text-[13px] font-medium">{formatCount(cluster.namespace.under_replicated_blocks)} blocks</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">Hadoop</dt>
          <dd className="text-[13px] font-medium">{cluster.namenode.software_version}</dd>
        </div>
      </dl>
      {cluster.problems.length > 0 && <p className="mt-2 text-xs text-muted-foreground">{cluster.problems[0]}</p>}
    </Panel>
  );
}

export default function DashboardPage() {
  const overview = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/api/v1/analytics/overview"), refetchInterval: 15_000 });
  const history = useQuery({
    queryKey: ["history"],
    queryFn: () => api<{ snapshots: Snapshot[]; optimizations: OptimizationRecord[] }>("/api/v1/analytics/history"),
    refetchInterval: 15_000,
  });
  const events = useQuery({ queryKey: ["audit", "recent"], queryFn: () => api<Page<AuditEvent>>("/api/v1/audit/events?page_size=7"), refetchInterval: 15_000 });

  if (overview.isError) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <ErrorNotice error={overview.error} onRetry={() => overview.refetch()} />
      </>
    );
  }
  if (!overview.data) {
    return (
      <>
        <PageHeader title="Dashboard" />
        <RowsSkeleton rows={8} />
      </>
    );
  }

  const data = overview.data;
  const { derived, distributions } = data;
  const empty = derived.logical_files === 0;
  const snapshots = history.data?.snapshots ?? [];
  const optimizations = history.data?.optimizations ?? [];

  return (
    <>
      <PageHeader title="Dashboard" description="Live storage state of the managed HDFS namespace. Every value comes from the backend, and states how it is known." />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
        <Panel>
          {empty ? (
            <EmptyState
              icon={FolderTree}
              title="No files are managed yet"
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  <Button size="sm" render={<Link href="/files" />}>
                    Upload files
                  </Button>
                  <Button size="sm" variant="outline" render={<Link href="/lab" />}>
                    Import the dataset
                  </Button>
                </div>
              }
            >
              Savings cannot be calculated until something is stored, so they show as N/A instead of 0%.
            </EmptyState>
          ) : (
            <>
              <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
                <div>
                  <p className="text-xs text-muted-foreground">Storage reduction</p>
                  <p className="mt-1 text-5xl font-semibold tracking-tight">{formatPercent(derived.savings_percent)}</p>
                </div>
                <p className="max-w-md pb-1 text-[13px] text-muted-foreground">
                  {formatBytes(derived.logical_bytes)} of logical data is held in {formatBytes(derived.stored_content_bytes)} of stored content, before replication.
                </p>
              </div>
              <div className="mt-4">
                <ReductionBar logical={derived.logical_bytes} stored={derived.stored_content_bytes} />
              </div>
            </>
          )}
          <div className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4 border-t pt-4 sm:grid-cols-3 lg:grid-cols-6">
            <Stat label="Logical files" value={formatCount(derived.logical_files)} provenance="derived" />
            <Stat label="Unique contents" value={formatCount(derived.unique_files)} provenance="derived" />
            <Stat label="Duplicates detected" value={formatCount(derived.duplicate_files)} provenance="derived" />
            <Stat label="Unique data retained" value={formatBytes(derived.stored_content_bytes)} provenance="derived" />
            <Stat label="Bytes avoided" value={empty ? "N/A" : formatBytes(derived.bytes_avoided)} provenance="derived" />
            <Stat label="Dedup ratio" value={formatRatio(derived.dedup_ratio)} provenance="derived" />
          </div>
        </Panel>
        <ClusterCard data={data} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <ChartPanel
          title="Logical and stored data over time"
          subtitle="Each point is a snapshot taken after an upload, deletion or optimization. The gap is the saving."
          legend={[
            { label: "Logical", color: "var(--chart-label)" },
            { label: "Stored", color: "var(--series-1)" },
          ]}
          columns={[
            { key: "taken_at", label: "Time", format: (v: string) => formatDateTime(v) },
            { key: "reason", label: "After" },
            { key: "logical_bytes", label: "Logical", align: "right", format: (v: number) => formatBytes(v) },
            { key: "stored_bytes", label: "Stored", align: "right", format: (v: number) => formatBytes(v) },
          ]}
          rows={snapshots as never}
          empty={<EmptyState title="No snapshots yet">The first upload records the first point.</EmptyState>}
        >
          <StorageOverTimeChart data={snapshots} />
        </ChartPanel>
        <Panel title="Where the bytes are" subtitle="From logical size down to what HDFS holds">
          <Ladder data={data} />
        </Panel>
      </div>

      <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <ChartPanel
          title="Duplicate distribution"
          subtitle="Distinct contents, by number of logical copies"
          columns={[
            { key: "copies", label: "Copies" },
            { key: "groups", label: "Contents", align: "right" },
          ]}
          rows={distributions.duplicate_distribution as never}
          empty={<EmptyState title="Nothing to show yet" />}
        >
          <ColumnChart data={distributions.duplicate_distribution as never} x="copies" y="groups" seriesLabel="Contents" xFormat={((v: number) => `${v}×`) as never} />
        </ChartPanel>
        <ChartPanel
          title="File types"
          subtitle="Logical bytes per extension"
          columns={[
            { key: "extension", label: "Type" },
            { key: "files", label: "Files", align: "right" },
            { key: "bytes", label: "Size", align: "right", format: (v: number) => formatBytes(v) },
          ]}
          rows={distributions.file_types.slice(0, 6) as never}
          empty={<EmptyState title="Nothing to show yet" />}
        >
          <HorizontalBars data={distributions.file_types.slice(0, 6) as never} category="extension" value="bytes" format={(v) => formatBytes(v)} seriesLabel="Size" />
        </ChartPanel>
        <ChartPanel
          title="Upload trend"
          subtitle="Files uploaded per day (UTC)"
          columns={[
            { key: "day", label: "Day" },
            { key: "files", label: "Files", align: "right" },
            { key: "bytes", label: "Size", align: "right", format: (v: number) => formatBytes(v) },
          ]}
          rows={distributions.upload_trend as never}
          empty={<EmptyState title="Nothing to show yet" />}
        >
          <ColumnChart data={distributions.upload_trend as never} x="day" y="files" seriesLabel="Files" />
        </ChartPanel>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Panel title="Optimization history" subtitle="Verified results from completed jobs" flush>
          {optimizations.length === 0 ? (
            <EmptyState title="No optimization has run">
              <Link href="/optimize" className="underline underline-offset-2">
                Review a dry run
              </Link>{" "}
              to see what could be reclaimed.
            </EmptyState>
          ) : (
            <div className="overflow-x-auto px-4 pb-3">
              <table className="w-full text-[13px]">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Finished</th>
                    <th className="py-2 pr-3 font-medium">Mode</th>
                    <th className="py-2 pr-3 text-right font-medium">Files</th>
                    <th className="py-2 pr-3 text-right font-medium">Stored before</th>
                    <th className="py-2 text-right font-medium">Stored after</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {optimizations.slice(0, 5).map((row) => (
                    <tr key={row.job_id} className="border-b last:border-0">
                      <td className="py-1.5 pr-3 whitespace-nowrap">{formatDateTime(row.created_at)}</td>
                      <td className="py-1.5 pr-3 whitespace-nowrap">
                        {MODE_LABEL[row.mode]}
                        {row.chunk_size ? ` (${chunkSizeLabel(row.chunk_size)})` : ""}
                      </td>
                      <td className="py-1.5 pr-3 text-right">{row.files_processed}</td>
                      <td className="py-1.5 pr-3 text-right">{formatBytes(row.before.derived.stored_content_bytes)}</td>
                      <td className="py-1.5 text-right">{formatBytes(row.after.derived.stored_content_bytes)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <Panel
          title="Recent operations"
          flush
          actions={
            <Link href="/activity" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
              All activity <ArrowRight className="size-3" aria-hidden />
            </Link>
          }
        >
          {events.data?.items.length ? (
            <ul className="divide-y px-4 pb-2">
              {events.data.items.map((event) => (
                <li key={event.id} className="flex items-baseline gap-3 py-1.5 text-xs">
                  <span className="tabular shrink-0 text-muted-foreground">{formatTime(event.occurred_at)}</span>
                  <span className="min-w-0 truncate" title={event.message}>
                    {event.severity !== "info" && <span className="mr-1 font-medium capitalize">{event.severity}:</span>}
                    {event.message}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState icon={Inbox} title="No operations recorded yet" />
          )}
        </Panel>
      </div>
    </>
  );
}

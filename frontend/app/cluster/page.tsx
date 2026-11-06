"use client";

import { useQuery } from "@tanstack/react-query";
import { ExternalLink, RefreshCw, Server, ServerOff } from "lucide-react";

import { EmptyState, ErrorNotice, KeyValue, Notice, PageHeader, Panel, RowsSkeleton, Stat, Status } from "@/components/common";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatBytes, formatCount, formatDateTime } from "@/lib/format";
import { useClusterStatus } from "@/lib/queries";
import type { DataNode } from "@/lib/types";

function CapacityMeter({ used, nonDfs, total }: { used: number; nonDfs: number; total: number }) {
  const usedShare = total ? (used / total) * 100 : 0;
  const otherShare = total ? (nonDfs / total) * 100 : 0;
  return (
    <div>
      <div className="flex h-2 w-full gap-0.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${usedShare.toFixed(2)} percent used by HDFS, ${otherShare.toFixed(1)} percent used by other data`}>
        <div className="h-full rounded-full bg-series-1" style={{ width: `${usedShare}%`, minWidth: used > 0 ? 3 : 0 }} />
        <div className="h-full rounded-full bg-[var(--chart-label)]" style={{ width: `${otherShare}%` }} />
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <li className="flex items-center gap-1.5">
          <span className="inline-block size-2 rounded-sm bg-series-1" aria-hidden /> HDFS: {formatBytes(used)}
        </li>
        <li className="flex items-center gap-1.5">
          <span className="inline-block size-2 rounded-sm bg-[var(--chart-label)]" aria-hidden /> Other data on disk: {formatBytes(nonDfs)}
        </li>
      </ul>
    </div>
  );
}

export default function ClusterPage() {
  const status = useClusterStatus();
  const nodes = useQuery({ queryKey: ["cluster", "nodes"], queryFn: () => api<{ checked_at: string; nodes: DataNode[] }>("/api/v1/cluster/nodes"), refetchInterval: 10_000, retry: false });
  const data = status.data;

  const refresh = () => {
    status.refetch();
    nodes.refetch();
  };

  const actions = (
    <>
      {data && <span className="text-xs text-muted-foreground">Updated {formatDateTime(data.checked_at)}</span>}
      <Button size="sm" variant="outline" onClick={refresh}>
        <RefreshCw className={status.isFetching ? "animate-spin" : ""} /> Refresh
      </Button>
      {data?.namenode_url && (
        <Button size="sm" variant="outline" render={<a href={data.namenode_url} target="_blank" rel="noreferrer" />}>
          NameNode UI <ExternalLink />
        </Button>
      )}
    </>
  );

  if (status.isError) {
    return (
      <>
        <PageHeader title="Cluster monitoring" actions={actions} />
        <ErrorNotice error={status.error} onRetry={refresh} />
      </>
    );
  }
  if (!data) {
    return (
      <>
        <PageHeader title="Cluster monitoring" />
        <RowsSkeleton rows={8} />
      </>
    );
  }
  if (!data.reachable) {
    return (
      <>
        <PageHeader title="Cluster monitoring" actions={actions} />
        <Panel>
          <EmptyState icon={ServerOff} title="The NameNode is not responding">
            {data.error}
          </EmptyState>
        </Panel>
      </>
    );
  }

  const live = nodes.data?.nodes.filter((n) => n.state === "live").length ?? data.datanodes.live;
  const total = nodes.data?.nodes.length ?? live;
  const tone = data.health === "healthy" ? "good" : data.health === "degraded" ? "warning" : "critical";

  return (
    <>
      <PageHeader title="Cluster monitoring" description="Read from the NameNode's JMX interface on each refresh." actions={actions} />

      {data.problems.length > 0 && (
        <div className="mb-4 space-y-2">
          {data.problems.map((problem) => (
            <Notice key={problem} tone="warning">
              {problem}
            </Notice>
          ))}
        </div>
      )}

      <Panel className="mb-4">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
          <Stat label="Health" value={<Status tone={tone} className="text-xl font-semibold capitalize">{data.health}</Status>} provenance="measured" />
          <Stat label="NameNode" value={<span className="capitalize">{data.namenode.state}</span>} provenance="measured" />
          <Stat label="DataNodes" value={`${data.datanodes.live} live`} provenance="measured" note={`${data.datanodes.dead} dead, ${data.datanodes.stale} stale`} />
          <Stat label="HDFS files" value={formatCount(data.namespace.files_total)} provenance="measured" note="Includes directories" />
          <Stat label="Blocks" value={formatCount(data.namespace.blocks_total)} provenance="measured" />
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Panel title="Capacity" subtitle="As reported by DataNodes">
          <div className="mb-4 grid grid-cols-3 gap-4">
            <Stat label="Configured" value={formatBytes(data.capacity.total_bytes)} />
            <Stat label="Used by HDFS" value={formatBytes(data.capacity.used_bytes)} />
            <Stat label="Remaining" value={formatBytes(data.capacity.remaining_bytes)} />
          </div>
          <CapacityMeter used={data.capacity.used_bytes} nonDfs={data.capacity.non_dfs_used_bytes} total={data.capacity.total_bytes} />
          <p className="mt-3 text-xs text-muted-foreground">On a single host, every DataNode reports the same disk, so configured capacity counts that disk once per DataNode.</p>
        </Panel>
        <Panel title="NameNode">
          <KeyValue
            rows={[
              { label: "Address", value: data.namenode.host_and_port },
              { label: "Hadoop version", value: data.namenode.software_version },
              { label: "Cluster ID", value: data.namenode.cluster_id },
              { label: "Filesystem state", value: data.namenode.fs_state },
              { label: "Safe mode", value: data.namenode.safemode ? "On" : "Off" },
              { label: "Connection", value: data.namenode_url },
            ]}
          />
        </Panel>
      </div>

      <Panel title={`DataNodes: ${live} live of ${total}`} className="mt-4" flush>
        {nodes.isError ? (
          <div className="p-4">
            <ErrorNotice error={nodes.error} />
          </div>
        ) : !nodes.data ? (
          <RowsSkeleton rows={3} />
        ) : nodes.data.nodes.length === 0 ? (
          <EmptyState icon={Server} title="No DataNodes have registered" />
        ) : (
          <div className="overflow-x-auto px-4 pb-3">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">Node</th>
                  <th className="py-2 pr-3 font-medium">State</th>
                  <th className="py-2 pr-3 text-right font-medium">Last contact</th>
                  <th className="py-2 pr-3 text-right font-medium">Blocks</th>
                  <th className="py-2 pr-3 text-right font-medium">HDFS used</th>
                  <th className="py-2 pr-3 text-right font-medium">Remaining</th>
                  <th className="py-2 pr-3 font-medium">Admin state</th>
                  <th className="py-2 font-medium">Version</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {nodes.data.nodes.map((node) => (
                  <tr key={node.name} className="border-b last:border-0">
                    <td className="py-1.5 pr-3 font-medium">{node.name}</td>
                    <td className="py-1.5 pr-3">
                      <Status tone={node.state === "live" ? "good" : "critical"} className="text-xs capitalize">
                        {node.state}
                      </Status>
                    </td>
                    <td className="py-1.5 pr-3 text-right">{node.last_contact_seconds ?? "N/A"} s ago</td>
                    <td className="py-1.5 pr-3 text-right">{formatCount(node.blocks)}</td>
                    <td className="py-1.5 pr-3 text-right">{formatBytes(node.used_bytes)}</td>
                    <td className="py-1.5 pr-3 text-right">{formatBytes(node.remaining_bytes)}</td>
                    <td className="py-1.5 pr-3">{node.admin_state ?? "N/A"}</td>
                    <td className="py-1.5">{node.version ?? "N/A"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Block health" className="mt-4">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Under-replicated" value={formatCount(data.namespace.under_replicated_blocks)} />
          <Stat label="Missing" value={formatCount(data.namespace.missing_blocks)} />
          <Stat label="Corrupt" value={formatCount(data.namespace.corrupt_blocks)} />
          <Stat label="Pending replication" value={formatCount(data.namespace.pending_replication_blocks)} />
          <Stat label="Pending deletion" value={formatCount(data.namespace.pending_deletion_blocks)} />
          <Stat label="Excess replicas" value={formatCount(data.namespace.excess_blocks)} />
        </div>
      </Panel>
    </>
  );
}

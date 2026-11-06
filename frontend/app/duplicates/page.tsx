"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, CopyCheck, RefreshCw, Sparkles } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState, ErrorNotice, HashText, Notice, PageHeader, Panel, ProvenanceTag, RowsSkeleton, Stat } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { chunkSizeLabel, formatBytes, formatCount, MODE_LABEL, PROVENANCE_LABEL, shortHash } from "@/lib/format";
import type { DuplicateGroup, DuplicateGroups, SharedChunks } from "@/lib/types";

/**
 * Shows how logical names resolve to stored bytes: converging on one box when deduplicated,
 * one box each when every copy is still stored separately.
 */
function RelationshipDiagram({ group }: { group: DuplicateGroup }) {
  const shown = group.members.slice(0, 6);
  const hidden = group.members.length - shown.length;
  const rowHeight = 30;
  const rows = shown.length + (hidden > 0 ? 1 : 0);
  const height = Math.max(rows * rowHeight + 8, 92);
  const y = (index: number) => 4 + rowHeight * index + rowHeight / 2 - 3;
  const middle = height / 2;
  const raw = group.members.filter((m) => m.storage_mode === "raw").length;
  const deduped = group.members.length - raw;

  const label = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

  return (
    <div className="overflow-x-auto">
      <svg
        viewBox={`0 0 640 ${height}`}
        className="h-auto w-full max-w-[800px] min-w-[520px]"
        role="img"
        aria-label={`${group.copies} logical files share SHA-256 ${shortHash(group.sha256)}. ${raw} stored as separate copies, ${deduped} share one stored form.`}
      >
        {shown.map((member, index) => {
          const isRaw = member.storage_mode === "raw";
          const targetY = isRaw ? y(index) : middle;
          return (
            <g key={member.id}>
              <rect x={0} y={y(index) - 11} width={190} height={22} rx={4} fill="var(--muted)" />
              <text x={8} y={y(index) + 4} fontSize={11} fill="var(--foreground)">
                {label(member.name, 30)}
              </text>
              <path d={`M190 ${y(index)} C 240 ${y(index)}, 240 ${middle}, 290 ${middle}`} fill="none" stroke="var(--chart-axis)" strokeWidth={1.5} />
              <path d={`M430 ${middle} C 470 ${middle}, 470 ${targetY}, 510 ${targetY}`} fill="none" stroke={isRaw ? "var(--series-2)" : "var(--series-1)"} strokeWidth={1.5} opacity={isRaw || index === 0 ? 1 : 0.35} />
              {isRaw && (
                <>
                  <rect x={510} y={y(index) - 11} width={130} height={22} rx={4} fill="none" stroke="var(--series-2)" strokeWidth={1.5} />
                  <text x={520} y={y(index) + 4} fontSize={11} fill="var(--foreground)">
                    Own stored copy
                  </text>
                </>
              )}
            </g>
          );
        })}
        {hidden > 0 && (
          <text x={8} y={y(shown.length) + 4} fontSize={11} fill="var(--chart-label)">
            and {hidden} more
          </text>
        )}
        <rect x={290} y={middle - 22} width={140} height={44} rx={6} fill="var(--card)" stroke="var(--chart-axis)" />
        <text x={360} y={middle - 4} fontSize={10} textAnchor="middle" fill="var(--chart-label)">
          SHA-256
        </text>
        <text x={360} y={middle + 11} fontSize={11} textAnchor="middle" fontFamily="var(--font-plex-mono)" fill="var(--foreground)">
          {shortHash(group.sha256, 16)}
        </text>
        {deduped > 0 && (
          <>
            <rect x={510} y={middle - 15} width={130} height={30} rx={4} fill="var(--series-1)" />
            <text x={575} y={middle + 4} fontSize={11} textAnchor="middle" fill="#ffffff">
              One shared copy
            </text>
          </>
        )}
      </svg>
    </div>
  );
}

function GroupRow({ group, defaultOpen }: { group: DuplicateGroup; defaultOpen: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <li className="border-b last:border-0">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-accent/50">
        {open ? <ChevronDown className="size-4 shrink-0 text-muted-foreground" aria-hidden /> : <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden />}
        <span className="min-w-0 flex-1 truncate text-[13px]" title={group.members[0]?.name}>
          {group.members[0]?.name}
          {group.copies > 1 && <span className="text-muted-foreground"> and {group.copies - 1} more</span>}
        </span>
        <span className="tabular hidden shrink-0 text-xs text-muted-foreground sm:inline">
          {group.copies} × {formatBytes(group.size_bytes)}
        </span>
        <span className="tabular w-28 shrink-0 text-right text-xs">{group.already_deduplicated ? <Badge variant="secondary">Deduplicated</Badge> : `${formatBytes(group.reclaimable_bytes)} reclaimable`}</span>
      </button>
      {open && (
        <div className="space-y-3 px-4 pt-1 pb-4">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <span>Matching hash</span> <HashText hash={group.sha256} length={32} />
          </div>
          <RelationshipDiagram group={group} />
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="px-3 py-1.5 font-medium">Logical file</th>
                  <th className="px-3 py-1.5 font-medium">Folder</th>
                  <th className="px-3 py-1.5 font-medium">Stored as</th>
                  <th className="px-3 py-1.5 font-medium">Origin</th>
                </tr>
              </thead>
              <tbody>
                {group.members.map((member) => (
                  <tr key={member.id} className="border-b last:border-0">
                    <td className="px-3 py-1">{member.name}</td>
                    <td className="px-3 py-1 text-muted-foreground">{member.folder}</td>
                    <td className="px-3 py-1">{MODE_LABEL[member.storage_mode]}</td>
                    <td className="px-3 py-1 text-muted-foreground">{PROVENANCE_LABEL[member.provenance_label] ?? member.provenance_label}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </li>
  );
}

function ChunkMap({ data }: { data: SharedChunks }) {
  return (
    <ul className="space-y-4">
      {data.manifests.map((manifest) => {
        const shared = manifest.chunk_map.filter(Boolean).length;
        return (
          <li key={manifest.id}>
            <div className="mb-1 flex flex-wrap items-baseline justify-between gap-x-3 text-xs">
              <span className="min-w-0 truncate font-medium" title={manifest.logical_files.join(", ")}>
                {manifest.logical_files[0] ?? "No active file"}
                {manifest.logical_files.length > 1 && <span className="font-normal text-muted-foreground"> and {manifest.logical_files.length - 1} more</span>}
              </span>
              <span className="tabular text-muted-foreground">
                {manifest.chunk_count} chunks of {chunkSizeLabel(manifest.chunk_size)}
                {manifest.chunk_map.length > 0 && `, ${((shared / manifest.chunk_map.length) * 100).toFixed(0)}% shared`}
              </span>
            </div>
            <div className="flex flex-wrap gap-px" role="img" aria-label={`${shared} of ${manifest.chunk_map.length} chunks shown are shared with another manifest`}>
              {manifest.chunk_map.map((isShared, index) => (
                <span key={index} className={isShared ? "h-3 w-1.5 rounded-[1px] bg-series-1" : "h-3 w-1.5 rounded-[1px] bg-[var(--chart-axis)]"} />
              ))}
            </div>
            {manifest.chunk_count > data.chunk_map_limit && <p className="mt-1 text-[11px] text-muted-foreground">First {data.chunk_map_limit} chunks shown.</p>}
          </li>
        );
      })}
    </ul>
  );
}

export default function DuplicatesPage() {
  const groups = useQuery({ queryKey: ["dup-groups"], queryFn: () => api<DuplicateGroups>("/api/v1/dedup/groups") });
  const chunks = useQuery({ queryKey: ["shared-chunks"], queryFn: () => api<SharedChunks>("/api/v1/dedup/shared-chunks") });
  const reclaimable = groups.data?.groups.reduce((sum, g) => sum + g.reclaimable_bytes, 0) ?? 0;

  return (
    <>
      <PageHeader
        title="Duplicates"
        description="Identity is the SHA-256 of the content, never the file name."
        actions={
          <>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                groups.refetch();
                chunks.refetch();
              }}
            >
              <RefreshCw className={groups.isFetching ? "animate-spin" : ""} /> Scan again
            </Button>
            <Button size="sm" render={<Link href="/optimize" />}>
              <Sparkles /> Review optimization
            </Button>
          </>
        }
      />

      <Panel className="mb-4">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Stat label="Duplicate groups" value={formatCount(groups.data?.group_count)} provenance="derived" />
          <Stat label="Redundant logical copies" value={formatCount(groups.data?.duplicate_files)} provenance="derived" />
          <Stat label="Redundant logical bytes" value={formatBytes(groups.data?.redundant_logical_bytes)} provenance="derived" />
          <Stat label="Still reclaimable" value={formatBytes(reclaimable)} provenance="estimated" note={reclaimable > 0 ? "until optimized" : undefined} />
        </div>
      </Panel>

      <Tabs defaultValue="exact">
        <TabsList>
          <TabsTrigger value="exact">Exact duplicates</TabsTrigger>
          <TabsTrigger value="chunks">Shared chunks</TabsTrigger>
        </TabsList>

        <TabsContent value="exact" className="mt-3 space-y-3">
          <Notice>
            <strong className="font-medium text-foreground">Exact duplicates</strong> are whole files with identical bytes. These are not HDFS replicas: replicas are block copies HDFS keeps for fault tolerance, and deduplication never removes them.
          </Notice>
          <Panel flush>
            {groups.isError ? (
              <div className="p-4">
                <ErrorNotice error={groups.error} onRetry={() => groups.refetch()} />
              </div>
            ) : !groups.data ? (
              <RowsSkeleton />
            ) : groups.data.groups.length === 0 ? (
              <EmptyState icon={CopyCheck} title="No exact duplicates found">
                Every managed file has distinct content. Upload a file twice, or ingest dataset files with workload copies, to see a group.
              </EmptyState>
            ) : (
              <ul>
                {groups.data.groups.map((group, index) => (
                  <GroupRow key={group.sha256} group={group} defaultOpen={index === 0} />
                ))}
              </ul>
            )}
          </Panel>
        </TabsContent>

        <TabsContent value="chunks" className="mt-3 space-y-3">
          <Notice>
            <strong className="font-medium text-foreground">Shared chunks</strong> are identical fixed-size pieces inside files that may differ overall. These are application-level chunks, each stored as its own HDFS file; they are not HDFS blocks. Only chunk-mode files appear here.
          </Notice>
          <Panel
            title="Chunk map"
            subtitle="Each mark is one chunk, in file order. Blue is also used by another distinct file."
            actions={
              chunks.data && (
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  {formatBytes(chunks.data.bytes_saved_by_sharing)} saved by sharing <ProvenanceTag kind="derived" />
                </span>
              )
            }
          >
            {chunks.isError ? (
              <ErrorNotice error={chunks.error} onRetry={() => chunks.refetch()} />
            ) : !chunks.data ? (
              <RowsSkeleton rows={3} />
            ) : chunks.data.manifests.length === 0 ? (
              <EmptyState title="No chunk-mode files yet">Upload with chunk-level dedup, or run chunk-level optimization.</EmptyState>
            ) : (
              <ChunkMap data={chunks.data} />
            )}
          </Panel>
        </TabsContent>
      </Tabs>
    </>
  );
}

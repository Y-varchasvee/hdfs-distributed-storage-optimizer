"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, ScrollText } from "lucide-react";
import { useState } from "react";

import { Choice, EmptyState, ErrorNotice, PageHeader, Panel, RowsSkeleton, Status } from "@/components/common";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import type { AuditEvent, Page } from "@/lib/types";
import { cn } from "@/lib/utils";

const TYPE_FILTERS = [
  { value: "all", label: "All events" },
  { value: "file.", label: "Files" },
  { value: "dedup.", label: "Duplicate detections" },
  { value: "optimize.", label: "Optimization" },
  { value: "integrity.", label: "Integrity checks" },
  { value: "replication.", label: "Replication" },
  { value: "storage.", label: "Storage maintenance" },
  { value: "dataset.", label: "Datasets" },
  { value: "experiment.", label: "Experiments" },
  { value: "job.", label: "Jobs" },
  { value: "request.", label: "Failed requests" },
  { value: "settings.", label: "Settings" },
];

const TONE = { info: "info", warning: "warning", error: "critical" } as const;

export default function ActivityPage() {
  const [type, setType] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [page, setPage] = useState(1);
  const pageSize = 40;
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (type !== "all") params.set("event_type", type);
  if (severity !== "all") params.set("severity", severity);

  const events = useQuery({
    queryKey: ["audit", params.toString()],
    queryFn: () => api<Page<AuditEvent>>(`/api/v1/audit/events?${params}`),
    placeholderData: keepPreviousData,
    refetchInterval: 10_000,
  });
  const totalPages = events.data ? Math.max(1, Math.ceil(events.data.total / pageSize)) : 1;

  return (
    <>
      <PageHeader title="Activity and audit" description="An append-only record of uploads, duplicate detections, jobs, deletions, restorations, integrity checks, replication changes and failures." />
      <Panel flush>
        <div className="flex flex-wrap items-center gap-2 border-b p-3">
          <Choice
            ariaLabel="Filter by event type"
            value={type}
            onChange={(v) => {
              setType(v);
              setPage(1);
            }}
            options={TYPE_FILTERS}
          />
          <Choice
            ariaLabel="Filter by severity"
            value={severity}
            onChange={(v) => {
              setSeverity(v);
              setPage(1);
            }}
            options={[
              { value: "all", label: "Any severity" },
              { value: "info", label: "Info" },
              { value: "warning", label: "Warnings" },
              { value: "error", label: "Errors" },
            ]}
          />
        </div>
        {events.isError ? (
          <div className="p-4">
            <ErrorNotice error={events.error} onRetry={() => events.refetch()} />
          </div>
        ) : !events.data ? (
          <RowsSkeleton rows={10} />
        ) : events.data.items.length === 0 ? (
          <EmptyState icon={ScrollText} title="No events match">
            Operations appear here as they happen.
          </EmptyState>
        ) : (
          <div className={cn("overflow-x-auto transition-opacity", events.isPlaceholderData && "opacity-60")}>
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="px-3 py-2 font-medium">Time</th>
                  <th className="px-3 py-2 font-medium">Severity</th>
                  <th className="px-3 py-2 font-medium">Event</th>
                  <th className="px-3 py-2 font-medium">Details</th>
                </tr>
              </thead>
              <tbody>
                {events.data.items.map((event) => (
                  <tr key={event.id} className="border-b align-baseline last:border-0">
                    <td className="tabular px-3 py-1.5 text-xs whitespace-nowrap text-muted-foreground">{formatDateTime(event.occurred_at)}</td>
                    <td className="px-3 py-1.5 whitespace-nowrap">
                      <Status tone={TONE[event.severity]} className="text-xs capitalize">
                        {event.severity}
                      </Status>
                    </td>
                    <td className="px-3 py-1.5 font-mono text-xs whitespace-nowrap">{event.event_type}</td>
                    <td className="min-w-80 px-3 py-1.5 text-xs break-words">{event.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {events.data && events.data.total > 0 && (
          <div className="flex items-center justify-between border-t px-3 py-2 text-xs text-muted-foreground">
            <span className="tabular">{events.data.total.toLocaleString("en-US")} events</span>
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
    </>
  );
}

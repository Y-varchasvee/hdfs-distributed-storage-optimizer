"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, FlaskConical, Loader2, PackagePlus, Play } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { Choice, EmptyState, ErrorNotice, HashText, Notice, PageHeader, Panel, ProgressBar, RowsSkeleton, Stat, Status } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { API_URL, api, post } from "@/lib/api";
import { CHUNK_SIZES, formatBytes, formatCount, formatDateTime } from "@/lib/format";
import { isFinished, useJob } from "@/lib/queries";
import type { DatasetList, ExperimentRun, Experiments, Job } from "@/lib/types";

const KIND_TEXT = { original: "Authentic original", transformed: "Transformed test file", workload_copy: "Workload copy" } as const;

function ResultValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">N/A</span>;
  if (typeof value === "boolean") return <>{value ? "Yes" : "No"}</>;
  if (typeof value === "number") return <>{Number.isInteger(value) ? value.toLocaleString("en-US") : value.toFixed(2)}</>;
  if (typeof value === "object") return <span className="font-mono text-[10px] break-all">{JSON.stringify(value)}</span>;
  return <>{String(value)}</>;
}

function RunResult({ run }: { run: ExperimentRun }) {
  const rows = run.result?.rows;
  const columns = useMemo(() => {
    const seen: string[] = [];
    rows?.forEach((row) => Object.keys(row).forEach((key) => !seen.includes(key) && seen.push(key)));
    return seen;
  }, [rows]);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>
          {run.result?.description}
          {run.result?.duration_s !== undefined && ` Ran in ${run.result.duration_s.toFixed(1)} s on ${formatDateTime(run.finished_at)}.`}
        </span>
        <Button size="xs" variant="outline" render={<a href={`${API_URL}/api/v1/experiments/${run.id}/export.csv`} />}>
          <Download /> CSV
        </Button>
      </div>
      <div className="max-h-72 overflow-auto rounded-md border">
        <table className="text-[11px]">
          <thead className="sticky top-0 bg-card text-muted-foreground">
            <tr className="border-b text-left">
              {columns.map((column) => (
                <th key={column} className="px-2 py-1 font-medium whitespace-nowrap">
                  {column.replaceAll("_", " ")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular">
            {rows?.map((row, index) => (
              <tr key={index} className="border-b last:border-0">
                {columns.map((column) => (
                  <td key={column} className="px-2 py-0.5 whitespace-nowrap">
                    <ResultValue value={row[column]} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function LabPage() {
  const client = useQueryClient();
  const datasets = useQuery({ queryKey: ["datasets"], queryFn: () => api<DatasetList>("/api/v1/datasets") });
  const experiments = useQuery({ queryKey: ["experiments"], queryFn: () => api<Experiments>("/api/v1/experiments") });

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [ingestOpen, setIngestOpen] = useState(false);
  const [copies, setCopies] = useState(2);
  const [mode, setMode] = useState<"raw" | "file" | "chunk">("raw");
  const [chunkSize, setChunkSize] = useState(256 * 1024);
  const [activeJob, setActiveJob] = useState<string | null>(null);
  const [activeScenario, setActiveScenario] = useState<string | null>(null);

  const job = useJob<{ errors?: string[] }>(activeJob, (finished) => {
    client.invalidateQueries({ queryKey: ["datasets"] });
    client.invalidateQueries({ queryKey: ["experiments"] });
    client.invalidateQueries({ queryKey: ["files"] });
    client.invalidateQueries({ queryKey: ["overview"] });
    setActiveScenario(null);
    if (finished.status === "succeeded") toast.success(`${finished.kind.replace("_", " ")} finished.`);
    else toast.error(finished.error ?? `Finished with status ${finished.status}.`);
  });
  const running = !!activeJob && !isFinished(job.data as Job<unknown> | undefined);

  const start = async (path: string, body?: unknown) => {
    try {
      const { job_id } = await post<{ job_id: string }>(path, body);
      setActiveJob(job_id);
    } catch (error) {
      setActiveScenario(null);
      toast.error(error instanceof Error ? error.message : "Could not start");
    }
  };

  const items = datasets.data?.items ?? [];
  const originals = items.filter((i) => i.kind === "original");
  const totalBytes = originals.reduce((sum, i) => sum + i.size_bytes, 0);
  const latest = (scenario: string) => experiments.data?.runs.find((run) => run.scenario === scenario);

  return (
    <>
      <PageHeader
        title="Dataset and experiment lab"
        description="Authentic files from Project Gutenberg, with recorded provenance, and reproducible experiments that run on the real cluster."
        actions={
          <Button size="sm" variant="outline" disabled={running} onClick={() => start("/api/v1/datasets/import", {})}>
            <Download /> Download from Project Gutenberg
          </Button>
        }
      />

      {running && job.data && (
        <div className="mb-4 rounded-lg border bg-card px-4 py-3">
          <div className="mb-1.5 flex items-center justify-between gap-3 text-xs text-muted-foreground">
            <Status tone="busy">{job.data.message ?? "Queued"}</Status>
            {job.data.progress_total > 0 && (
              <span className="tabular">
                {job.data.progress_done} of {job.data.progress_total}
              </span>
            )}
          </div>
          <ProgressBar value={job.data.progress_total ? job.data.progress_done / job.data.progress_total : 0} label="Job progress" />
        </div>
      )}

      <Panel className="mb-4">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <Stat label="Authentic original files" value={formatCount(originals.length)} />
          <Stat label="Original data" value={formatBytes(totalBytes)} />
          <Stat label="Transformed test files" value={formatCount(items.filter((i) => i.kind === "transformed").length)} />
          <Stat label="Source" value="Project Gutenberg" note={<a className="underline underline-offset-2" href="https://www.gutenberg.org/" target="_blank" rel="noreferrer">gutenberg.org</a>} />
        </div>
      </Panel>

      <Notice>
        Nothing here is synthesized. <strong className="font-medium text-foreground">Originals</strong> are stored exactly as the publisher served them. <strong className="font-medium text-foreground">Workload copies</strong> are the same bytes under another logical name. <strong className="font-medium text-foreground">Transformed test files</strong> are byte-level edits of one original, documented below. None is presented as a separately published work.
      </Notice>

      <Panel
        title="Dataset files and provenance"
        className="mt-4"
        flush
        actions={
          <Button size="sm" disabled={selected.size === 0 || running} onClick={() => setIngestOpen(true)}>
            <PackagePlus /> Ingest {selected.size > 0 ? selected.size : ""} into HDFS
          </Button>
        }
      >
        {datasets.isError ? (
          <div className="p-4">
            <ErrorNotice error={datasets.error} onRetry={() => datasets.refetch()} />
          </div>
        ) : !datasets.data ? (
          <RowsSkeleton />
        ) : items.length === 0 ? (
          <EmptyState icon={FlaskConical} title="No dataset files yet">
            Use the download button to fetch the catalog from Project Gutenberg. {datasets.data.catalog.length} works are configured.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto px-4 pb-3">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="w-8 py-2 pr-2">
                    <input
                      type="checkbox"
                      aria-label="Select all available files"
                      checked={selected.size > 0 && selected.size === items.filter((i) => i.local_present).length}
                      onChange={(e) => setSelected(e.target.checked ? new Set(items.filter((i) => i.local_present).map((i) => i.id)) : new Set())}
                    />
                  </th>
                  <th className="py-2 pr-3 font-medium">Title</th>
                  <th className="py-2 pr-3 font-medium">Kind</th>
                  <th className="py-2 pr-3 font-medium">Format</th>
                  <th className="py-2 pr-3 text-right font-medium">Size</th>
                  <th className="py-2 pr-3 font-medium">SHA-256</th>
                  <th className="py-2 pr-3 font-medium">Downloaded</th>
                  <th className="py-2 font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-b align-baseline last:border-0">
                    <td className="py-1.5 pr-2">
                      <input
                        type="checkbox"
                        aria-label={`Select ${item.title}`}
                        disabled={!item.local_present}
                        checked={selected.has(item.id)}
                        onChange={(e) => {
                          const next = new Set(selected);
                          if (e.target.checked) next.add(item.id);
                          else next.delete(item.id);
                          setSelected(next);
                        }}
                      />
                    </td>
                    <td className="max-w-80 py-1.5 pr-3">
                      <span className="block truncate" title={item.title}>
                        {item.title}
                      </span>
                      <span className="block truncate text-[11px] text-muted-foreground" title={item.transformation ?? item.author ?? ""}>
                        {item.transformation ?? item.author}
                      </span>
                    </td>
                    <td className="py-1.5 pr-3 whitespace-nowrap">
                      <Badge variant={item.kind === "original" ? "secondary" : "outline"}>{KIND_TEXT[item.kind]}</Badge>
                    </td>
                    <td className="py-1.5 pr-3 uppercase text-xs text-muted-foreground">{item.file_format}</td>
                    <td className="tabular py-1.5 pr-3 text-right whitespace-nowrap">{formatBytes(item.size_bytes)}</td>
                    <td className="py-1.5 pr-3">
                      <HashText hash={item.sha256} />
                    </td>
                    <td className="tabular py-1.5 pr-3 text-xs whitespace-nowrap text-muted-foreground">{item.downloaded_at ? formatDateTime(item.downloaded_at) : "Derived locally"}</td>
                    <td className="py-1.5 whitespace-nowrap">
                      {item.source_url && (
                        <a className="inline-flex items-center gap-1 text-xs underline underline-offset-2" href={item.source_url} target="_blank" rel="noreferrer">
                          #{item.ebook_id} <ExternalLink className="size-3" aria-hidden />
                        </a>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Experiments" subtitle="Each run uses its own HDFS directory and temporary database, so it never touches managed files." className="mt-4" flush>
        {!experiments.data ? (
          <RowsSkeleton />
        ) : (
          <ul className="divide-y border-t">
            {experiments.data.scenarios.map((scenario) => {
              const run = latest(scenario.id);
              const busy = activeScenario === scenario.id && running;
              return (
                <li key={scenario.id} className="px-4 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-medium">{scenario.title}</p>
                      <p className="text-xs text-muted-foreground">{scenario.description}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      {run && !busy && (
                        <Status tone={run.status === "succeeded" ? "good" : run.status === "failed" ? "critical" : "busy"} className="text-xs capitalize">
                          {run.status}
                        </Status>
                      )}
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={running || items.length === 0}
                        onClick={() => {
                          setActiveScenario(scenario.id);
                          start("/api/v1/experiments/run", { scenario: scenario.id });
                        }}
                      >
                        {busy ? <Loader2 className="animate-spin" /> : <Play />} Run
                      </Button>
                    </div>
                  </div>
                  {run?.status === "failed" && <p className="mt-2 text-xs break-words text-muted-foreground">{run.error}</p>}
                  {run?.status === "succeeded" && (
                    <div className="mt-3">
                      <RunResult run={run} />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Panel>

      <Dialog open={ingestOpen} onOpenChange={setIngestOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Ingest {selected.size} dataset file{selected.size === 1 ? "" : "s"}</DialogTitle>
            <DialogDescription>Files go through the normal upload pipeline into the folder /datasets. The bytes of each file are checked against its recorded SHA-256 first.</DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="copies" className="text-xs">
                Exact workload copies per file
              </Label>
              <Input id="copies" type="number" min={0} max={20} value={copies} onChange={(e) => setCopies(Math.max(0, Math.min(20, Number(e.target.value))))} className="h-8 w-24" />
              <p className="text-[11px] text-muted-foreground">Copies are named and labelled as workload copies, so they cannot be mistaken for originals.</p>
            </div>
            <div className="grid gap-1.5">
              <Label className="text-xs">Storage mode</Label>
              <Choice
                ariaLabel="Storage mode for ingestion"
                value={mode}
                onChange={setMode}
                options={[
                  { value: "raw", label: "No dedup (shows what optimization can reclaim)" },
                  { value: "file", label: "Whole-file dedup" },
                  { value: "chunk", label: "Chunk-level dedup" },
                ]}
                className="w-full"
              />
            </div>
            {mode === "chunk" && (
              <div className="grid gap-1.5">
                <Label className="text-xs">Chunk size</Label>
                <Choice ariaLabel="Chunk size for ingestion" value={String(chunkSize)} onChange={(v) => setChunkSize(Number(v))} options={CHUNK_SIZES.map((c) => ({ value: String(c.value), label: c.label }))} className="w-full" />
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIngestOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                setIngestOpen(false);
                start("/api/v1/datasets/ingest", { source_ids: Array.from(selected), copies, mode, chunk_size: mode === "chunk" ? chunkSize : null });
              }}
            >
              Ingest
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

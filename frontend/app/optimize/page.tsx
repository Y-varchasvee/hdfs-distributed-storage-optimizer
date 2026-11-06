"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, Play, RotateCcw, ScanSearch, ShieldCheck } from "lucide-react";
import { useCallback, useState } from "react";
import { toast } from "sonner";

import { BeforeAfter } from "@/components/charts";
import { Choice, EmptyState, ErrorNotice, Notice, PageHeader, Panel, ProgressBar, ProvenanceTag, Stat, Status } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { api, post } from "@/lib/api";
import { CHUNK_SIZES, chunkSizeLabel, formatBytes, formatCount, formatDateTime, formatMs, formatPercent, MODE_LABEL, shortHash } from "@/lib/format";
import { isFinished, useJob } from "@/lib/queries";
import type { AnalysisResult, Job, OptimizeResult } from "@/lib/types";
import { cn } from "@/lib/utils";

const ACTION_TEXT: Record<string, string> = {
  promote_to_object: "Becomes the stored object",
  reference_existing_object: "Points at the stored object; old copy removed",
  chunk: "Split into chunks; new chunks stored",
  reference_existing_manifest: "Points at an existing manifest",
};

function Step({ number, title, state, children }: { number: number; title: string; state: "todo" | "active" | "done"; children?: React.ReactNode }) {
  return (
    <section className="relative grid grid-cols-[28px_minmax(0,1fr)] gap-3">
      <div className="flex flex-col items-center">
        <span
          className={cn(
            "flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-medium",
            state === "active" && "border-transparent bg-primary text-primary-foreground",
            state === "done" && "border-transparent bg-muted",
            state === "todo" && "text-muted-foreground",
          )}
        >
          {state === "done" ? <CheckCircle2 className="size-4 text-good" aria-label="Done" /> : number}
        </span>
        <span className="mt-1 w-px flex-1 bg-border" aria-hidden />
      </div>
      <div className="min-w-0 pb-6">
        <h2 className={cn("text-[13px] leading-6 font-semibold", state === "todo" && "text-muted-foreground")}>{title}</h2>
        {children && <div className="mt-2">{children}</div>}
      </div>
    </section>
  );
}

function JobStatusLine({ job }: { job: Job<unknown> }) {
  const fraction = job.progress_total ? job.progress_done / job.progress_total : 0;
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between gap-3 text-xs text-muted-foreground">
        <Status tone="busy">{job.message ?? "Queued"}</Status>
        <span className="tabular">
          {job.progress_done} of {job.progress_total || "?"}
        </span>
      </div>
      <ProgressBar value={fraction} label="Job progress" />
    </div>
  );
}

function AnalysisPreview({ result }: { result: AnalysisResult }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-4 rounded-md border p-3 lg:grid-cols-4">
        <Stat label="Files to convert" value={formatCount(result.files_eligible)} note={`${result.distinct_contents} distinct`} />
        <Stat label="Stored content now" value={formatBytes(result.current_stored_bytes)} provenance="derived" />
        <Stat label="Expected afterwards" value={formatBytes(result.predicted_stored_bytes)} provenance="estimated" />
        <Stat label="Expected reduction" value={formatBytes(result.predicted_reduction_bytes)} provenance="estimated" note={`${formatPercent(result.predicted_savings_percent)} saving`} />
      </div>
      {result.mode === "chunk" && (
        <p className="tabular text-xs text-muted-foreground">
          Read {formatCount(result.chunks_examined)} chunks of {chunkSizeLabel(result.chunk_size)}: {formatCount(result.chunks_new)} would be new, {formatCount(result.chunks_reused)} would reuse a stored chunk. Each new chunk also becomes an HDFS file, which adds NameNode metadata.
        </p>
      )}
      {result.actions.length > 0 && (
        <div className="max-h-56 overflow-auto rounded-md border">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-card text-muted-foreground">
              <tr className="border-b text-left">
                <th className="px-3 py-1.5 font-medium">File</th>
                <th className="px-3 py-1.5 font-medium">Now</th>
                <th className="px-3 py-1.5 font-medium">SHA-256</th>
                <th className="px-3 py-1.5 font-medium">Planned action</th>
              </tr>
            </thead>
            <tbody>
              {result.actions.map((action) => (
                <tr key={action.id} className="border-b last:border-0">
                  <td className="max-w-56 truncate px-3 py-1" title={action.name}>
                    {action.name}
                  </td>
                  <td className="px-3 py-1 whitespace-nowrap">{MODE_LABEL[action.storage_mode]}</td>
                  <td className="px-3 py-1 font-mono text-muted-foreground">{shortHash(action.sha256, 10)}</td>
                  <td className="px-3 py-1 text-muted-foreground">{ACTION_TEXT[action.action] ?? action.action}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {result.actions_truncated && <p className="text-xs text-muted-foreground">Showing the first 500 files.</p>}
    </div>
  );
}

function VerifiedResult({ job }: { job: Job<OptimizeResult> }) {
  const client = useQueryClient();
  const [verifyJobId, setVerifyJobId] = useState<string | null>(null);
  const verifyJob = useJob<{ files_checked: number; passed: number; failed: string[] }>(verifyJobId);
  const result = job.result;
  if (!result) return null;
  const { before, after } = result;
  const measuredBefore = before.measured.available ? before.measured : null;
  const measuredAfter = after.measured.available ? after.measured : null;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4 rounded-md border p-3 lg:grid-cols-4">
        <Stat label="Files converted" value={formatCount(result.files_processed)} note={result.files_failed ? `${result.files_failed} failed` : "All verified first"} />
        <Stat label="Stored content reclaimed" value={formatBytes(result.bytes_reclaimed)} provenance="derived" />
        <Stat label="Savings now" value={formatPercent(after.derived.savings_percent)} provenance="derived" />
        <Stat label="Duration" value={formatMs(result.duration_ms)} provenance="measured" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div>
          <p className="mb-2 flex items-center gap-2 text-xs font-medium">
            Application view <ProvenanceTag kind="derived" />
          </p>
          <BeforeAfter
            rows={[
              { label: "Stored content", before: before.derived.stored_content_bytes, after: after.derived.stored_content_bytes },
            ]}
          />
        </div>
        {measuredBefore && measuredAfter && (
          <div>
            <p className="mb-2 flex items-center gap-2 text-xs font-medium">
              HDFS view, including replicas <ProvenanceTag kind="measured" />
            </p>
            <BeforeAfter rows={[{ label: "Space consumed", before: measuredBefore.space_consumed, after: measuredAfter.space_consumed }]} />
            <p className="tabular mt-2 text-xs text-muted-foreground">
              Files in namespace: {formatCount(measuredBefore.file_count)} before, {formatCount(measuredAfter.file_count)} after. HDFS frees disk blocks asynchronously after a delete, so DataNode usage catches up shortly.
            </p>
          </div>
        )}
      </div>

      {result.errors.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium">Errors</p>
          <ul className="space-y-1">
            {result.errors.map((error) => (
              <li key={error.file_id} className="rounded-md border border-critical/30 bg-critical/5 px-2.5 py-1.5 text-xs break-words">
                {error.error}
              </li>
            ))}
          </ul>
          <p className="mt-1 text-xs text-muted-foreground">Files with errors were left unchanged.</p>
        </div>
      )}
      {result.orphans_left?.length > 0 && <Notice tone="warning">{result.orphans_left.length} old copies could not be removed. They are harmless and can be quarantined from Settings.</Notice>}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          size="sm"
          variant="outline"
          disabled={!!verifyJobId && !isFinished(verifyJob.data as Job<unknown> | undefined)}
          onClick={async () => {
            const { job_id } = await post<{ job_id: string }>("/api/v1/files/verify-all");
            setVerifyJobId(job_id);
            client.invalidateQueries({ queryKey: ["overview"] });
          }}
        >
          <ShieldCheck /> Verify all restored bytes
        </Button>
        {verifyJob.data && !isFinished(verifyJob.data as Job<unknown>) && <span className="tabular text-xs text-muted-foreground">Checked {verifyJob.data.progress_done} of {verifyJob.data.progress_total}</span>}
        {verifyJob.data?.result && (
          <Status tone={verifyJob.data.result.failed.length ? "critical" : "good"}>
            {verifyJob.data.result.passed} of {verifyJob.data.result.files_checked} files match their SHA-256
          </Status>
        )}
      </div>
    </div>
  );
}

export default function OptimizePage() {
  const client = useQueryClient();
  const [mode, setMode] = useState<"file" | "chunk">("file");
  const [chunkSize, setChunkSize] = useState(256 * 1024);
  const [analysisId, setAnalysisId] = useState<string | null>(null);
  const [optimizeId, setOptimizeId] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const history = useQuery({
    queryKey: ["jobs", "optimize"],
    queryFn: () => api<Job<OptimizeResult>[]>("/api/v1/dedup/jobs?kind=optimize&limit=8"),
  });
  const resumable = history.data?.find((job) => ["interrupted", "failed", "partial"].includes(job.status));

  const refreshAll = useCallback(() => {
    client.invalidateQueries({ queryKey: ["jobs"] });
    client.invalidateQueries({ queryKey: ["overview"] });
    client.invalidateQueries({ queryKey: ["files"] });
    client.invalidateQueries({ queryKey: ["dup-groups"] });
  }, [client]);

  const analysis = useJob<AnalysisResult>(analysisId);
  const optimization = useJob<OptimizeResult>(optimizeId, refreshAll);

  const analysisDone = analysis.data?.status === "succeeded";
  const analysisFailed = analysis.data?.status === "failed";
  const analyzing = !!analysisId && !isFinished(analysis.data as Job<unknown> | undefined);
  const optimizing = !!optimizeId && !isFinished(optimization.data as Job<unknown> | undefined);
  const optimized = !!optimizeId && isFinished(optimization.data as Job<unknown> | undefined);

  const changeMethod = (next: { mode?: "file" | "chunk"; chunkSize?: number }) => {
    if (next.mode) setMode(next.mode);
    if (next.chunkSize) setChunkSize(next.chunkSize);
    // An earlier preview describes a different method, so it no longer applies.
    setAnalysisId(null);
    setOptimizeId(null);
  };

  const startAnalysis = async () => {
    setError(null);
    setOptimizeId(null);
    try {
      const { job_id } = await post<{ job_id: string }>("/api/v1/dedup/analyze", { mode, chunk_size: mode === "chunk" ? chunkSize : null });
      setAnalysisId(job_id);
    } catch (e) {
      setError(e);
    }
  };

  const startOptimization = async () => {
    setConfirming(false);
    setError(null);
    try {
      const { job_id } = await post<{ job_id: string }>("/api/v1/dedup/optimize", { analysis_job_id: analysisId });
      setOptimizeId(job_id);
    } catch (e) {
      setError(e);
    }
  };

  const nothingToDo = analysisDone && analysis.data?.result?.files_eligible === 0;

  return (
    <>
      <PageHeader title="Optimization center" description="Preview first, then convert one file at a time. A file's old copy is removed only after its new form has been read back and its SHA-256 checked." />

      {resumable && !optimizeId && (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card px-4 py-2.5">
          <Status tone="warning">
            A {MODE_LABEL[resumable.mode ?? "file"].toLowerCase()} job from {formatDateTime(resumable.created_at)} ended as {resumable.status}. Finished files are safe.
          </Status>
          <Button
            size="sm"
            variant="outline"
            onClick={async () => {
              try {
                const { job_id } = await post<{ job_id: string }>(`/api/v1/dedup/jobs/${resumable.id}/resume`);
                setOptimizeId(job_id);
              } catch (e) {
                toast.error(e instanceof Error ? e.message : "Could not resume");
              }
            }}
          >
            <RotateCcw /> Resume
          </Button>
        </div>
      )}

      {!!error && (
        <div className="mb-4">
          <ErrorNotice error={error} />
        </div>
      )}

      <Panel>
        <Step number={1} title="Choose a method" state={analysisId ? "done" : "active"}>
          <div className="grid gap-2 sm:grid-cols-2">
            {(
              [
                { value: "file", title: "File-level", text: "Keeps one stored object per distinct file. Fast, and adds no namespace overhead. Finds only whole-file duplicates." },
                { value: "chunk", title: "Chunk-level", text: "Splits content into fixed-size chunks and shares identical ones. Also finds overlap between different files, but creates many small HDFS files." },
              ] as const
            ).map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={mode === option.value}
                onClick={() => changeMethod({ mode: option.value })}
                className={cn("rounded-md border px-3 py-2.5 text-left transition-colors hover:bg-accent/50", mode === option.value && "border-primary ring-1 ring-primary")}
              >
                <span className="text-[13px] font-medium">{option.title}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">{option.text}</span>
              </button>
            ))}
          </div>
          {mode === "chunk" && (
            <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
              Chunk size
              <Choice ariaLabel="Chunk size" value={String(chunkSize)} onChange={(v) => changeMethod({ chunkSize: Number(v) })} options={CHUNK_SIZES.map((c) => ({ value: String(c.value), label: c.label }))} />
            </div>
          )}
          <Button size="sm" className="mt-3" onClick={startAnalysis} disabled={analyzing || optimizing}>
            {analyzing ? <Loader2 className="animate-spin" /> : <ScanSearch />} {analysisId ? "Analyze again" : "Run dry-run analysis"}
          </Button>
        </Step>

        <Step number={2} title="Review the preview" state={analysisDone ? (optimizeId ? "done" : "active") : "todo"}>
          {analyzing && analysis.data && <JobStatusLine job={analysis.data as Job<unknown>} />}
          {analysisFailed && <ErrorNotice error={new Error(analysis.data?.error ?? "The analysis failed.")} />}
          {analysisDone && analysis.data?.result && (
            <>
              <p className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                <ProvenanceTag kind="estimated" /> Nothing has changed yet. These figures are predictions.
              </p>
              {nothingToDo ? (
                <EmptyState icon={CheckCircle2} title="Nothing to convert">
                  No active file would change under this method.
                </EmptyState>
              ) : (
                <>
                  <AnalysisPreview result={analysis.data.result} />
                  {!optimizeId && (
                    <Button size="sm" className="mt-3" onClick={() => setConfirming(true)}>
                      <Play /> Start optimization
                    </Button>
                  )}
                </>
              )}
            </>
          )}
        </Step>

        <Step number={3} title="Convert and verify" state={optimized ? "done" : optimizing ? "active" : "todo"}>
          {optimizing && optimization.data && <JobStatusLine job={optimization.data as Job<unknown>} />}
          {optimized && optimization.data?.status === "failed" && <ErrorNotice error={new Error(optimization.data.error ?? "The job failed.")} />}
          {optimized && optimization.data?.result && (
            <>
              <p className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                <ProvenanceTag kind="measured" /> Results below are observed, not predicted.
              </p>
              <VerifiedResult job={optimization.data} />
            </>
          )}
        </Step>
      </Panel>

      <Panel title="Job history" className="mt-4" flush>
        {history.data?.length ? (
          <div className="overflow-x-auto px-4 pb-3">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-medium">Started</th>
                  <th className="py-2 pr-3 font-medium">Method</th>
                  <th className="py-2 pr-3 font-medium">Outcome</th>
                  <th className="py-2 pr-3 text-right font-medium">Converted</th>
                  <th className="py-2 pr-3 text-right font-medium">Reclaimed</th>
                  <th className="py-2 text-right font-medium">Duration</th>
                </tr>
              </thead>
              <tbody className="tabular">
                {history.data.map((job) => (
                  <tr key={job.id} className="border-b last:border-0">
                    <td className="py-1.5 pr-3 whitespace-nowrap">{formatDateTime(job.created_at)}</td>
                    <td className="py-1.5 pr-3 whitespace-nowrap">
                      {MODE_LABEL[job.mode ?? "file"]}
                      {job.chunk_size ? ` (${chunkSizeLabel(job.chunk_size)})` : ""}
                    </td>
                    <td className="py-1.5 pr-3">
                      <Status tone={job.status === "succeeded" ? "good" : job.status === "running" || job.status === "queued" ? "busy" : job.status === "partial" || job.status === "interrupted" ? "warning" : "critical"} className="text-xs capitalize">
                        {job.status}
                      </Status>
                    </td>
                    <td className="py-1.5 pr-3 text-right">{job.result?.files_processed ?? "N/A"}</td>
                    <td className="py-1.5 pr-3 text-right">{job.result ? formatBytes(job.result.bytes_reclaimed) : "N/A"}</td>
                    <td className="py-1.5 text-right">{job.result ? formatMs(job.result.duration_ms) : "N/A"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title="No optimization jobs have run" />
        )}
      </Panel>

      <Dialog open={confirming} onOpenChange={setConfirming}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Start {mode}-level optimization?</DialogTitle>
            <DialogDescription>
              {analysis.data?.result?.files_eligible} files will be converted. Each is verified by SHA-256 before its old copy is removed, and any file that fails verification stays as it is. HDFS replication is not changed.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
            <Button onClick={startOptimization}>Start optimization</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

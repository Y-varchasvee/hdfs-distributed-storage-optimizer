"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { api } from "./api";
import type { ClusterStatus, Job } from "./types";

export function useClusterStatus() {
  return useQuery({
    queryKey: ["cluster", "status"],
    queryFn: () => api<ClusterStatus>("/api/v1/cluster/status"),
    refetchInterval: 10_000,
  });
}

const FINISHED = new Set(["succeeded", "partial", "failed", "interrupted"]);

export function isFinished(job: Job<unknown> | undefined): boolean {
  return !!job && FINISHED.has(job.status);
}

/** Polls a real background job until it reaches a final state, then calls onFinished once. */
export function useJob<R>(jobId: string | null, onFinished?: (job: Job<R>) => void) {
  const notified = useRef<string | null>(null);
  const query = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api<Job<R>>(`/api/v1/dedup/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (state) => (isFinished(state.state.data as Job<unknown> | undefined) ? false : 700),
  });
  const job = query.data;
  useEffect(() => {
    if (job && isFinished(job as Job<unknown>) && notified.current !== job.id) {
      notified.current = job.id;
      onFinished?.(job);
    }
  }, [job, onFinished]);
  return query;
}

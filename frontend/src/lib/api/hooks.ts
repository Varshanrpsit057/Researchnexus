"use client";

import useSWR from "swr";
import { ApiError } from "./client";
import { jobs, papers } from "./endpoints";
import type { Job, ResearchProfile } from "./types";

/** A paper's stored research profile, or null when it has none yet (a 404
 * is "not analysed", not an error). Every page showing a profile reads it
 * through this one key, so analysing on one updates them all. */
export function useProfile(paperId: string | null) {
  return useSWR<ResearchProfile | null>(paperId ? ["profile", paperId] : null, async () => {
    try {
      return await papers.getProfile(paperId as string);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  });
}

const TERMINAL_STATUSES = new Set<Job["status"]>(["succeeded", "failed", "partial", "cancelled"]);
const POLL_MS = 1500;

/** Polls GET /api/v1/jobs/{id} every 1.5s until the job reaches a terminal
 * status (the only mechanism the API offers for async work -- discovery,
 * gaps, and the ingest job all report progress this way). Discovery in
 * particular can run for a minute or more, long enough that a backgrounded
 * or hidden browser tab throttles the interval timer; `revalidateOnFocus`
 * catches the tab back up the moment the researcher returns to it instead
 * of leaving a finished job showing as still running until the next
 * (possibly throttled) tick -- found live: a real discovery run finished
 * server-side while the tab sat unfocused, and the UI kept showing
 * "Searching external sources..." well after. */
export function useJobPolling(jobId: string | null | undefined) {
  const { data, error, isLoading } = useSWR(
    jobId ? ["job", jobId] : null,
    () => jobs.get(jobId as string),
    {
      refreshInterval: (latest) => (latest && TERMINAL_STATUSES.has(latest.status) ? 0 : POLL_MS),
      // SWR's default 2 s deduping swallowed every other tick, so a job was
      // really polled every 3 s (measured, remediation Phase 8)
      dedupingInterval: POLL_MS / 2,
      revalidateOnFocus: true,
    }
  );

  return {
    job: data,
    isDone: data ? TERMINAL_STATUSES.has(data.status) : false,
    isLoading,
    error,
  };
}

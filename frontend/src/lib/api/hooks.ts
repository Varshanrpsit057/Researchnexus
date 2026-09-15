"use client";

import useSWR from "swr";
import { jobs } from "./endpoints";
import type { Job } from "./types";

const TERMINAL_STATUSES = new Set<Job["status"]>(["succeeded", "failed", "partial"]);

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
      refreshInterval: (latest) => (latest && TERMINAL_STATUSES.has(latest.status) ? 0 : 1500),
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

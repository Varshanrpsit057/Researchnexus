"use client";

import type { ReactNode } from "react";
import { Check, Minus, X } from "@phosphor-icons/react/dist/ssr";
import { CINEMATIC } from "@/lib/cinematic-theme";
import {
  SEARCH_STRATEGIES,
  SOURCE_LABEL,
  SOURCE_ORDER,
  STEP_LABEL,
  STEP_ORDER,
  STRATEGY_LABEL,
  formatSeconds,
  headline,
  sourceSummary,
  stepDetail,
  stepTiming,
  strategyNote,
} from "@/lib/discovery";
import type { DiscoveryProgress, DiscoveryStepEntry, DiscoveryStepState } from "@/lib/api/types";

const C = CINEMATIC;

function StateMark({ state }: { state: DiscoveryStepState | "timed_out" }) {
  if (state === "done") return <Check className="size-3.5" weight="bold" style={{ color: C.mint }} aria-hidden />;
  if (state === "failed") return <X className="size-3.5" weight="bold" style={{ color: C.danger }} aria-hidden />;
  if (state === "timed_out") return <Minus className="size-3.5" weight="bold" style={{ color: C.warning }} aria-hidden />;
  if (state === "skipped") return <Minus className="size-3.5" style={{ color: C.muted2 }} aria-hidden />;
  if (state === "running") {
    return <span className="block size-2 rounded-full motion-safe:animate-pulse" style={{ background: C.mint, boxShadow: `0 0 10px ${C.mint}` }} aria-hidden />;
  }
  return <span className="block size-2 rounded-full" style={{ border: `1px solid ${C.lineStrong}` }} aria-hidden />;
}

const STATE_WORD: Record<DiscoveryStepState, string> = {
  pending: "not started",
  running: "in progress",
  done: "done",
  failed: "failed",
  skipped: "skipped",
};

function Row({ state, label, detail, timing, children }: {
  state: DiscoveryStepState | "timed_out";
  label: string;
  detail: string | null;
  timing: string | null;
  children?: ReactNode;
}) {
  const active = state === "running";
  return (
    <li aria-current={active ? "step" : undefined}>
      <div className="grid grid-cols-[1.25rem_1fr_auto] items-baseline gap-x-3 py-2">
        <span className="flex size-4 translate-y-0.5 items-center justify-center">
          <StateMark state={state} />
        </span>
        <span className="min-w-0 text-sm">
          <span className="font-semibold" style={{ color: state === "pending" ? C.muted2 : C.ink }}>
            {label}
          </span>
          <span className="sr-only"> ({state === "timed_out" ? "stopped at its time limit" : STATE_WORD[state]})</span>
          {detail && (
            <span className="ml-2" style={{ color: state === "failed" ? C.danger : C.muted }}>
              {detail}
            </span>
          )}
        </span>
        <span className="font-mono text-xs tabular-nums" style={{ color: active ? C.mint : C.muted2 }}>
          {timing}
        </span>
      </div>
      {children}
    </li>
  );
}

/** A discovery run as it happens: each step with its real state and time,
 * the searches under way, each source's answers, and the first papers in. */
export function RunProgress({ progress, stage, onCancel, cancelling, cancelError }: {
  progress: DiscoveryProgress | null;
  stage: string | undefined;
  onCancel: () => void;
  cancelling: boolean;
  cancelError: string | null;
}) {
  const elapsed = progress?.elapsed_s ?? 0;
  const searchRunning = progress?.steps.search?.state === "running";
  const ranked = progress?.steps.rank?.state === "done";
  const sources = SOURCE_ORDER.filter((s) => progress?.sources[s]);

  return (
    <section
      className="mx-auto max-w-3xl rounded-2xl px-6 py-6 sm:px-8"
      style={{ background: C.glass, border: `1px solid ${C.line}` }}
      aria-labelledby="run-headline"
      data-testid="discovery-progress"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p id="run-headline" className="text-base font-semibold" role="status" aria-live="polite">
            {headline(progress, stage)}
          </p>
          <p className="mt-1 text-sm" style={{ color: C.muted }}>
            {progress
              ? `Running for ${formatSeconds(elapsed)}${progress.found > 0 ? ` · ${progress.found} distinct papers returned so far` : ""}`
              : "Searching arXiv, OpenAlex, Europe PMC and Semantic Scholar, then ranking against the seed profile."}
          </p>
        </div>
        <button
          type="button"
          onClick={onCancel}
          disabled={cancelling}
          className="shrink-0 rounded-full px-4 py-2 text-sm font-semibold transition-colors hover:bg-white/10 disabled:opacity-60"
          style={{ border: `1px solid ${C.lineStrong}`, color: C.ink }}
        >
          {cancelling ? "Cancelling…" : "Cancel discovery"}
        </button>
      </div>
      {cancelError && (
        <p role="alert" className="mt-2 text-sm" style={{ color: C.danger }}>
          {cancelError}
        </p>
      )}

      {progress && (
        <ol className="mt-5 divide-y border-y" style={{ borderColor: C.line }} aria-label="Steps of the run">
          {STEP_ORDER.map((step) => {
            const entry: DiscoveryStepEntry = progress.steps[step] ?? { state: "pending" };
            return (
              <Row
                key={step}
                state={entry.state}
                label={STEP_LABEL[step]}
                detail={stepDetail(step, entry, progress.found)}
                timing={stepTiming(entry, elapsed)}
              >
                {step === "search" && entry.state !== "pending" && (
                  <ul className="mb-2 ml-8 space-y-1 text-[13px]" aria-label="Searches">
                    {SEARCH_STRATEGIES.map((name) => {
                      const s = progress.strategies[name];
                      if (!s) return null;
                      const note = strategyNote(name, s);
                      return (
                        <li key={name} className="grid grid-cols-[1fr_auto] gap-x-3" style={{ color: C.muted }}>
                          <span>
                            <span style={{ color: C.ink }}>{STRATEGY_LABEL[name]}</span>
                            {" · "}
                            {s.state === "running" ? `${s.found} so far` : `${s.found} found`}
                            {note && <span style={{ color: s.state === "done" ? C.muted2 : C.warning }}>{` — ${note}`}</span>}
                          </span>
                          <span className="font-mono text-xs tabular-nums" style={{ color: C.muted2 }}>
                            {s.state === "running" ? "…" : s.seconds != null ? formatSeconds(s.seconds) : ""}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </Row>
            );
          })}
        </ol>
      )}

      {progress && sources.length > 0 && (
        <div className="mt-5">
          <h2 className="text-xs uppercase tracking-wider" style={{ color: C.muted2 }}>
            Sources
          </h2>
          <dl className="mt-2 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-[13px]" data-testid="discovery-sources">
            {sources.map((s) => (
              <div key={s} className="contents">
                <dt style={{ color: C.ink }}>{SOURCE_LABEL[s] ?? s}</dt>
                <dd style={{ color: progress.sources[s].failed > 0 ? C.warning : C.muted }}>{sourceSummary(progress.sources[s])}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {progress && !ranked && progress.preview.length > 0 && (
        <div className="mt-5">
          <h2 className="text-xs uppercase tracking-wider" style={{ color: C.muted2 }}>
            First to arrive
          </h2>
          <p className="mt-1 text-[12.5px]" style={{ color: C.muted2 }}>
            {searchRunning ? "Not ranked yet: the ranking comes once every source has answered." : "Not ranked yet: ranking follows scoring."}
          </p>
          <ul className="mt-2 space-y-1 text-[13px]" data-testid="discovery-preview">
            {progress.preview.map((p) => (
              <li key={`${p.title}-${p.year}`} className="truncate" style={{ color: C.muted }}>
                {p.title}
                {p.year != null && <span style={{ color: C.muted2 }}>{` · ${p.year}`}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="mt-5 text-[12.5px]" style={{ color: C.muted2 }}>
        You can leave this page: the run keeps going, and coming back here picks it up again.
      </p>
    </section>
  );
}

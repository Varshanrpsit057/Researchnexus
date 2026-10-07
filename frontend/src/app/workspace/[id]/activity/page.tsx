"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { ArrowLeft, CheckCircle, XCircle } from "@phosphor-icons/react/dist/ssr";
import { workspaces } from "@/lib/api/endpoints";
import type { StageName } from "@/lib/api/types";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { STAGE_LABEL } from "@/lib/workspace-overview";
import { formatTokens } from "@/lib/usage";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { Timestamp } from "@/components/ui/Timestamp";
import { C, InlineError, WorkspaceLoadError, focusRing, panel, quietButton } from "@/components/cinematic/ui";

const STAGES = Object.keys(STAGE_LABEL) as StageName[];

function duration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

export default function WorkspaceActivityPage() {
  const { id } = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const [stage, setStage] = useState<StageName | "">("");
  const workspaceQ = useSWR(ready ? ["workspace", id] : null, () => workspaces.get(id));
  const activityQ = useSWR(ready && workspaceQ.data ? ["activity", id, stage] : null, () =>
    workspaces.activity(id, { ...(stage ? { stage } : {}), limit: 200 }),
  );

  if (!ready) return null;
  if (workspaceQ.error) {
    return (
      <PageShell>
        <WorkspaceLoadError error={workspaceQ.error} onRetry={() => workspaceQ.mutate()} />
      </PageShell>
    );
  }

  const runs = activityQ.data?.stage_runs ?? [];
  const failed = runs.filter((r) => !r.ok).length;
  const tokens = runs.reduce((n, r) => n + r.tokens_prompt + r.tokens_completion, 0);

  return (
    <PageShell>
      <header className="border-b pb-7" style={{ borderColor: C.lineStrong }}>
        {workspaceQ.data ? (
          <Link
            href={`/workspace/${id}`}
            className={`inline-flex min-h-11 items-center gap-1.5 rounded-sm text-sm hover:text-white sm:min-h-0 ${focusRing}`}
            style={{ color: C.muted }}
          >
            <ArrowLeft className="size-4" aria-hidden />
            {workspaceQ.data.title}
          </Link>
        ) : (
          <div className="h-5 w-48 rounded motion-safe:animate-pulse" style={{ background: "rgba(255,255,255,.08)" }} />
        )}
        <h1 className="mt-3 text-[clamp(26px,3.6vw,40px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Activity</h1>
        <p className="mt-3 max-w-[70ch] text-[15px] leading-relaxed" style={{ color: C.muted }}>
          Every step that used a language model in this workspace: what it did, whether it worked, how long it took and the tokens your
          provider counted for it.
        </p>
      </header>

      <div className="mt-7 flex flex-wrap items-center justify-between gap-3">
        <label className="inline-flex items-center gap-2 text-[13px]" style={{ color: C.muted }}>
          Show
          <select
            value={stage}
            onChange={(e) => setStage(e.target.value as StageName | "")}
            className={`h-9 rounded-full px-3 text-[13px] ${focusRing}`}
            style={{ background: "rgba(255,255,255,.05)", border: `1px solid ${C.lineStrong}`, color: C.ink }}
          >
            <option value="">Every step</option>
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {STAGE_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
        {activityQ.data && runs.length > 0 && (
          <p className="text-[13px] tabular-nums" style={{ color: C.muted }}>
            {runs.length} step{runs.length === 1 ? "" : "s"} · {formatTokens(tokens)} tokens
            {failed > 0 && <span style={{ color: C.danger }}> · {failed} failed</span>}
          </p>
        )}
      </div>

      <div className="mt-4">
        {activityQ.error ? (
          <div className="rounded-2xl p-5" style={panel}>
            <InlineError message="The activity couldn't be loaded." />
            <button type="button" onClick={() => activityQ.mutate()} className={`mt-3 rounded-full px-4 py-2 text-sm font-semibold ${focusRing}`} style={{ ...quietButton, color: C.ink }}>
              Try again
            </button>
          </div>
        ) : !activityQ.data ? (
          <div role="status" className="h-48 rounded-2xl motion-safe:animate-pulse" style={panel}>
            <span className="sr-only">Loading the activity…</span>
          </div>
        ) : runs.length === 0 ? (
          <div className="rounded-2xl px-6 py-12 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
            <p className="text-base font-semibold">{stage ? `No "${STAGE_LABEL[stage].toLowerCase()}" steps yet` : "Nothing has run here yet"}</p>
            <p className="mx-auto mt-2 max-w-[54ch] text-sm leading-relaxed" style={{ color: C.muted }}>
              Asking a question, comparing papers, finding gaps and proposing directions each add a step here.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-2xl" style={panel}>
            <table className="w-full min-w-[760px] border-collapse text-left text-[13.5px]">
              <caption className="sr-only">Steps that ran in this workspace, newest first</caption>
              <thead>
                <tr className="border-b text-[12.5px]" style={{ borderColor: C.lineStrong, color: C.muted }}>
                  <th scope="col" className="px-5 py-3 font-semibold">
                    Step
                  </th>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    Result
                  </th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold">
                    Took
                  </th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold">
                    Tokens in / out
                  </th>
                  <th scope="col" className="px-5 py-3 font-semibold">
                    When
                  </th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className="border-b align-top last:border-b-0" style={{ borderColor: C.line }}>
                    <td className="px-5 py-3.5">
                      <span className="font-medium" style={{ color: C.ink }}>
                        {STAGE_LABEL[run.stage] ?? run.stage}
                      </span>
                      <span className="mt-0.5 block font-mono text-[12px]" style={{ color: C.muted2 }}>
                        {run.tool}
                      </span>
                    </td>
                    <td className="px-4 py-3.5">
                      {run.ok ? (
                        <span className="inline-flex items-center gap-1.5" style={{ color: C.mint }}>
                          <CheckCircle className="size-4" weight="fill" aria-hidden />
                          Done
                        </span>
                      ) : (
                        <span className="inline-flex items-start gap-1.5" style={{ color: C.danger }}>
                          <XCircle className="mt-0.5 size-4 shrink-0" weight="fill" aria-hidden />
                          <span>
                            Failed
                            {run.error && (
                              <span className="block max-w-[34ch] text-[12.5px]" style={{ color: C.muted }}>
                                {run.error}
                              </span>
                            )}
                          </span>
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3.5 text-right tabular-nums" style={{ color: C.muted }}>
                      {duration(run.latency_ms)}
                    </td>
                    <td className="px-4 py-3.5 text-right tabular-nums" style={{ color: C.muted }}>
                      {run.tokens_prompt + run.tokens_completion > 0 ? `${formatTokens(run.tokens_prompt)} / ${formatTokens(run.tokens_completion)}` : "—"}
                    </td>
                    <td className="px-5 py-3.5" style={{ color: C.muted }}>
                      <Timestamp at={run.ts} style="datetime" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </PageShell>
  );
}

"use client";

import Link from "next/link";
import useSWR from "swr";
import { ArrowRight } from "@phosphor-icons/react/dist/ssr";
import { workspaces } from "@/lib/api/endpoints";
import { parseUtc, relativeTime } from "@/lib/chat";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { C, InlineError, focusRing, panel, primaryButton, quietButton } from "../workspace/[id]/ui";

/** Comparisons belong to a workspace (its papers, its index); this page
 * is the way in from anywhere: pick the workspace whose papers to compare. */
export default function CompareIndexPage() {
  const { ready } = useRequireAuth();
  const { data, error, mutate } = useSWR(ready ? "workspaces" : null, () => workspaces.list());
  // most recently worked on first; titles repeat (every workspace is named after its seed)
  const list = [...(data?.workspaces ?? [])].sort((a, b) => parseUtc(b.updated_at).getTime() - parseUtc(a.updated_at).getTime());

  if (!ready) return null;
  return (
    <PageShell>
      <div className="selection:bg-[rgba(93,240,168,0.28)] selection:text-white">
        <header className="border-b pb-6" style={{ borderColor: C.lineStrong }}>
          <h1 className="text-[clamp(26px,3.6vw,40px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Compare papers</h1>
          <p className="mt-3 max-w-[68ch] text-[15px] leading-relaxed" style={{ color: C.muted }}>
            Papers are compared within a workspace, where their text is indexed. Choose the workspace whose papers you want side by side.
          </p>
        </header>

        {error ? (
          <div className="mt-8 rounded-2xl p-6" style={panel}>
            <InlineError message="Could not load your workspaces." />
            <button type="button" onClick={() => mutate()} className={`mt-4 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
              Try again
            </button>
          </div>
        ) : !data ? (
          <div role="status" className="mt-8 space-y-3">
            <span className="sr-only">Loading your workspaces…</span>
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-20 rounded-2xl motion-safe:animate-pulse" style={panel} />
            ))}
          </div>
        ) : list.length === 0 ? (
          <div className="mt-8 rounded-2xl px-6 py-12 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
            <h2 className="text-lg font-bold">No workspaces yet</h2>
            <p className="mx-auto mt-2 max-w-[56ch] text-sm leading-relaxed" style={{ color: C.muted }}>
              A workspace starts from a seed paper. Upload one, discover the papers around it, and compare them here.
            </p>
            <Link href="/papers" className={`mt-6 inline-flex rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
              Upload a paper
            </Link>
          </div>
        ) : (
          <ul className="mt-8 overflow-hidden rounded-2xl" style={panel}>
            {list.map((ws, i) => {
              const count = ws.papers.length;
              const ready2 = count >= 2;
              // the list carries no counts; say nothing about past comparisons rather than guess
              const compared = ws.counts ? ws.counts.comparisons > 0 : null;
              return (
                <li key={ws.workspace_id} className={i === 0 ? "" : "border-t"} style={{ borderColor: C.line }}>
                  <Link
                    href={ready2 ? `/workspace/${ws.workspace_id}/compare` : `/workspace/${ws.workspace_id}#papers`}
                    className={`group flex items-center gap-4 px-5 py-4 transition-colors hover:bg-white/[0.04] ${focusRing}`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-semibold">{ws.title}</span>
                      <span className="mt-0.5 block text-[13px]" style={{ color: C.muted }}>
                        <span className="tabular-nums">{count}</span> paper{count === 1 ? "" : "s"}
                        {` · updated ${relativeTime(ws.updated_at)}`}
                        {ready2 ? (
                          compared === true ? " · compared before" : compared === false ? " · not compared yet" : ""
                        ) : (
                          <span style={{ color: C.warning }}> · add a second paper to compare</span>
                        )}
                      </span>
                    </span>
                    <span className="hidden shrink-0 rounded-full px-3.5 py-1.5 text-[13px] font-semibold sm:inline-flex" style={ready2 ? primaryButton : quietButton}>
                      {ready2 ? (compared ? "Open comparison" : "Compare") : "Add papers"}
                    </span>
                    <ArrowRight className="size-4 shrink-0 transition-transform duration-200 group-hover:translate-x-0.5 sm:hidden" style={{ color: C.muted }} aria-hidden />
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </PageShell>
  );
}

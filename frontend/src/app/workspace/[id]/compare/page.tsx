"use client";

import { useCallback, useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { ArrowLeft, ChatCircleText, GitBranch, Graph, Plus, Warning, X } from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api/client";
import { workspaces } from "@/lib/api/endpoints";
import type { ComparisonResponse } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import {
  CANONICAL_FIELDS,
  CELL_COPY,
  coverageOf,
  fieldLabel,
  latestComparisonOrNull,
  leftWorkspace,
  normalizeField,
  notYetCompared,
} from "@/lib/compare";
import { truncate } from "@/lib/graph/labels";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { NodeGlyph } from "../graph/GraphPanel";
import { C, InlineError, WorkspaceLoadError, focusRing, panel, primaryButton, quietButton } from "../ui";
import { CellContent, CellEvidence, PaperHeading, StatusGlyph, WorkingTrail, usePaper, type PaperKind } from "./parts";

interface Inspecting {
  paperId: string;
  field: string;
}

export default function ComparePage() {
  const { id } = useParams<{ id: string }>();
  const { ready } = useRequireAuth();
  const { me } = useAuth();
  const { mutate: mutateGlobal } = useSWRConfig();

  const workspaceQ = useSWR(ready ? ["workspace", id] : null, () => workspaces.get(id));
  // shared with the overview's comparison station
  const comparisonQ = useSWR(ready && workspaceQ.data ? ["ws-latest-comparison", id] : null, () => latestComparisonOrNull(id));

  const workspace = workspaceQ.data;
  const comparison = comparisonQ.data ?? null;
  const members = useMemo(() => workspace?.papers.map((p) => p.paper_id) ?? [], [workspace]);

  // what the next run compares: chosen once the data arrives, then the reader's
  const [selected, setSelected] = useState<string[] | null>(null);
  const [fields, setFields] = useState<string[] | null>(null); // null: the papers' own profiles decide
  const [customField, setCustomField] = useState("");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<{ code?: string; message: string } | null>(null);
  const [inspecting, setInspecting] = useState<Inspecting | null>(null);
  const [announcement, setAnnouncement] = useState("");

  if (workspace && comparisonQ.data !== undefined && selected === null) {
    const fromLast = comparison?.paper_ids.filter((p) => members.includes(p)) ?? [];
    setSelected(fromLast.length >= 2 ? fromLast : members.slice(0, 4));
    if (comparison) setFields(comparison.schema);
  }
  const chosen = selected ?? [];

  const kindOf = useCallback(
    (paperId: string): PaperKind =>
      paperId === workspace?.seed_paper_id ? "seed" : members.includes(paperId) ? "member" : "connected",
    [workspace, members],
  );

  const noKey = me != null && !me.has_working_llm_key;
  const shownPapers = comparison ? comparison.paper_ids.filter((p) => chosen.includes(p) || !members.includes(p)) : [];
  const pending = notYetCompared(comparison, chosen);
  const gone = comparison ? leftWorkspace(comparison, members) : [];
  const coverage = comparison ? coverageOf(comparison, shownPapers) : null;
  const fieldsChanged = comparison != null && fields != null && fields.join("|") !== comparison.schema.join("|");

  function toggle(paperId: string) {
    setSelected((prev) => {
      const now = prev ?? [];
      return now.includes(paperId) ? now.filter((p) => p !== paperId) : [...now, paperId];
    });
  }

  function removeFromView(paperId: string) {
    setSelected((prev) => (prev ?? []).filter((p) => p !== paperId));
    if (inspecting?.paperId === paperId) setInspecting(null);
    setAnnouncement("Removed from the comparison.");
  }

  function toggleField(field: string) {
    setFields((prev) => {
      const now = prev ?? [];
      return now.includes(field) ? now.filter((f) => f !== field) : [...now, field];
    });
  }

  function addCustomField() {
    const field = normalizeField(customField);
    if (!field) return;
    setFields((prev) => (prev ?? []).includes(field) ? prev : [...(prev ?? []), field]);
    setCustomField("");
  }

  async function run() {
    if (chosen.length < 2 || running) return;
    setRunning(true);
    setRunError(null);
    setInspecting(null);
    setAnnouncement(`Comparing ${chosen.length} papers.`);
    try {
      // keep the workspace's own paper order, as the backend does
      const ordered = members.filter((p) => chosen.includes(p));
      const result = await workspaces.compare(id, { paper_ids: ordered, schema: fields && fields.length > 0 ? fields : null });
      await mutateGlobal(["ws-latest-comparison", id], result, { revalidate: false });
      void mutateGlobal(["workspace", id]); // the overview counts comparisons
      setFields(result.schema);
      const cov = coverageOf(result, result.paper_ids);
      setAnnouncement(`Comparison ready: ${cov.found} of ${cov.total} values found in the papers' text.`);
    } catch (e) {
      const err = e instanceof ApiError ? e : null;
      setRunError({
        code: err?.code,
        message:
          err?.code === "llm_key_required"
            ? "No working LLM provider key is saved. Add one in Settings to run a comparison."
            : err?.status === 422
              ? "Choose at least two papers from this workspace to compare."
              : err
                ? "The comparison didn't finish. Try again in a moment."
                : "The server couldn't be reached. Check the connection and try again.",
      });
      setAnnouncement("The comparison didn't finish.");
    } finally {
      setRunning(false);
    }
  }

  function onCustomKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      addCustomField();
    }
  }

  if (!ready) return null;
  if (workspaceQ.error) {
    return (
      <PageShell>
        <WorkspaceLoadError error={workspaceQ.error} onRetry={() => workspaceQ.mutate()} />
      </PageShell>
    );
  }

  const inspectedRow = inspecting && comparison?.rows.find((r) => r.paper_id === inspecting.paperId);
  const inspectedCell = inspecting && inspectedRow ? inspectedRow.cells[inspecting.field] : undefined;

  return (
    <PageShell maxWidthClassName="max-w-[1320px]">
      <div className="selection:bg-[rgba(93,240,168,0.28)] selection:text-white">
        <header className="border-b pb-6" style={{ borderColor: C.lineStrong }}>
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1">
            {workspace ? (
              <Link
                href={`/workspace/${id}`}
                className={`inline-flex min-h-11 min-w-0 items-center gap-1.5 rounded-sm text-sm hover:text-white sm:min-h-0 ${focusRing}`}
                style={{ color: C.muted }}
              >
                <ArrowLeft className="size-4 shrink-0" aria-hidden />
                <span className="truncate">{workspace.title}</span>
              </Link>
            ) : (
              <div className="h-5 w-48 rounded motion-safe:animate-pulse" style={{ background: "rgba(255,255,255,.08)" }} />
            )}
            <nav aria-label="Related views" className="flex flex-wrap items-center gap-x-4 text-sm sm:ml-auto" style={{ color: C.muted }}>
              <NavLink href={`/workspace/${id}/trail`} icon={<GitBranch className="size-4" aria-hidden />}>
                Trail
              </NavLink>
              <NavLink href={`/workspace/${id}/graph`} icon={<Graph className="size-4" aria-hidden />}>
                Graph
              </NavLink>
              <NavLink href={`/workspace/${id}/chat`} icon={<ChatCircleText className="size-4" aria-hidden />}>
                Ask
              </NavLink>
            </nav>
          </div>
          <h1 className="mt-3 text-[clamp(26px,3.6vw,40px)] font-extrabold leading-[1.1] tracking-[-0.025em]">Compare papers</h1>
          <p className="mt-3 max-w-[72ch] text-[15px] leading-relaxed" style={{ color: C.muted }}>
            {comparison && coverage ? (
              <>
                <span className="tabular-nums">{shownPapers.length}</span> papers side by side, <span className="tabular-nums">{comparison.schema.length}</span>{" "}
                fields. <span className="tabular-nums">{coverage.found}</span> of <span className="tabular-nums">{coverage.total}</span> values are stated
                in the papers&apos; own text; open one to read the passage it is quoted from.
              </>
            ) : (
              "Put two or more papers side by side. A value appears only when a passage of the paper states it word for word; every gap says why it is empty."
            )}
          </p>
        </header>

        <p className="sr-only" aria-live="polite">
          {announcement}
        </p>

        {!workspace || comparisonQ.data === undefined ? (
          comparisonQ.error ? (
            <div className="mt-8 rounded-2xl p-6" style={panel}>
              <InlineError message="Could not load this workspace's comparison." />
              <button type="button" onClick={() => comparisonQ.mutate()} className={`mt-4 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
                Try again
              </button>
            </div>
          ) : (
            <div role="status" className="mt-8 space-y-3">
              <span className="sr-only">Loading the comparison…</span>
              <div className="h-24 rounded-2xl motion-safe:animate-pulse" style={panel} />
              <div className="h-72 rounded-2xl motion-safe:animate-pulse" style={panel} />
            </div>
          )
        ) : members.length < 2 ? (
          <div className="mt-8 rounded-2xl px-6 py-12 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
            <h2 className="text-lg font-bold">A comparison needs two papers</h2>
            <p className="mx-auto mt-2 max-w-[56ch] text-sm leading-relaxed" style={{ color: C.muted }}>
              This workspace holds only its seed paper. Add related papers to it, then compare them side by side.
            </p>
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              <Link href={`/workspace/${id}#papers`} className={`rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
                Add papers
              </Link>
              <Link href={`/discover/${workspace.seed_paper_id}`} className={`rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={quietButton}>
                Discover related papers
              </Link>
            </div>
          </div>
        ) : (
          <>
            {/* what to compare */}
            <section aria-labelledby="compare-setup" className="mt-7 rounded-2xl p-5" style={panel}>
              <h2 id="compare-setup" className="text-base font-bold">
                What to compare
              </h2>
              <div className="mt-4 grid gap-5 lg:grid-cols-[1fr_1fr]">
                <div>
                  <p className="text-[13px]" style={{ color: C.muted }}>
                    Papers <span className="tabular-nums">· {chosen.length} of {members.length}</span>
                  </p>
                  <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Papers to compare">
                    {members.map((pid) => (
                      <li key={pid}>
                        <PaperChip paperId={pid} kind={kindOf(pid)} on={chosen.includes(pid)} onToggle={() => toggle(pid)} />
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <p className="text-[13px]" style={{ color: C.muted }}>
                    Fields {fields == null && "· chosen from what the papers' profiles cover"}
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="Fields to compare">
                    {[...CANONICAL_FIELDS, ...(fields ?? []).filter((f) => !(CANONICAL_FIELDS as readonly string[]).includes(f))].map((f) => {
                      const on = fields != null && fields.includes(f);
                      const custom = !(CANONICAL_FIELDS as readonly string[]).includes(f);
                      return (
                        <button
                          key={f}
                          type="button"
                          aria-pressed={on}
                          onClick={() => toggleField(f)}
                          className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition-colors sm:min-h-8 ${on ? "" : "hover:bg-white/10"} ${focusRing}`}
                          style={on ? { color: C.mintInk, background: C.mint } : { ...quietButton, color: C.ink }}
                        >
                          {fieldLabel(f)}
                          {custom && on && <X className="size-3" weight="bold" aria-hidden />}
                        </button>
                      );
                    })}
                    <label className="inline-flex min-h-11 items-center gap-1 rounded-full pl-3 sm:min-h-8" style={{ border: `1px dashed ${C.lineStrong}` }}>
                      <span className="sr-only">Add a field of your own</span>
                      <Plus className="size-3.5 shrink-0" style={{ color: C.muted }} aria-hidden />
                      <input
                        value={customField}
                        onChange={(e) => setCustomField(e.target.value)}
                        onKeyDown={onCustomKey}
                        onBlur={addCustomField}
                        maxLength={40}
                        placeholder="Add a field"
                        className="w-28 bg-transparent py-1.5 pr-3 text-[13px] caret-[#5df0a8] outline-none placeholder:text-[#8f9bb8]"
                        style={{ color: C.ink }}
                      />
                    </label>
                  </div>
                  {fields != null && (
                    <button
                      type="button"
                      onClick={() => setFields(null)}
                      className={`mt-2 min-h-11 text-[13px] underline underline-offset-4 hover:text-white sm:min-h-0 ${focusRing}`}
                      style={{ color: C.muted }}
                    >
                      Let the papers&apos; profiles choose the fields
                    </button>
                  )}
                </div>
              </div>

              <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-3 border-t pt-4" style={{ borderColor: C.line }}>
                <button
                  type="button"
                  onClick={run}
                  disabled={chosen.length < 2 || running || noKey}
                  className={`inline-flex min-h-11 items-center rounded-full px-5 text-sm font-semibold transition-[opacity,transform] active:scale-[0.97] disabled:opacity-45 ${focusRing}`}
                  style={primaryButton}
                >
                  {running ? "Comparing…" : comparison ? `Compare ${chosen.length} papers again` : `Compare ${chosen.length} papers`}
                </button>
                <p className="min-w-0 flex-1 text-[13px] leading-snug" style={{ color: noKey ? C.warning : C.muted }}>
                  {noKey ? (
                    <span className="inline-flex items-start gap-1.5">
                      <Warning className="mt-px size-4 shrink-0" weight="bold" aria-hidden />
                      <span>
                        No working LLM provider key is saved, so a comparison can&apos;t run yet.{" "}
                        <Link href="/settings" className={`rounded-sm font-semibold underline underline-offset-4 ${focusRing}`}>
                          Add a key
                        </Link>
                      </span>
                    </span>
                  ) : chosen.length < 2 ? (
                    "Choose at least two papers."
                  ) : pending.length > 0 && comparison ? (
                    `${pending.length} chosen paper${pending.length === 1 ? " isn't" : "s aren't"} in this comparison yet; comparing again includes ${pending.length === 1 ? "it" : "them"}.`
                  ) : fieldsChanged ? (
                    "The fields changed; comparing again fills them in."
                  ) : (
                    "A language model reads each paper; a value is kept only if a passage states it word for word."
                  )}
                </p>
              </div>
              {runError && (
                <div className="mt-3">
                  <InlineError message={runError.message} />
                </div>
              )}
            </section>

            {running && (
              <div role="status" className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl px-5 py-4" style={panel}>
                <WorkingTrail count={chosen.length} />
                <p className="text-[13px]" style={{ color: C.muted }}>
                  Reading {chosen.length} papers and checking every value against its passage. This can take a minute.
                </p>
              </div>
            )}

            {comparison ? (
              <section aria-labelledby="compare-table" className="mt-8">
                <h2 id="compare-table" className="sr-only">
                  The comparison
                </h2>
                {gone.length > 0 && (
                  <p className="mb-3 text-[13px]" style={{ color: C.muted }}>
                    {gone.length} compared paper{gone.length === 1 ? " is" : "s are"} no longer in the workspace and still shown here.
                  </p>
                )}
                {shownPapers.length === 0 ? (
                  <div className="rounded-2xl px-6 py-10 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
                    <p className="text-sm" style={{ color: C.muted }}>
                      Every paper was removed from the view. Choose papers above to show their columns again.
                    </p>
                  </div>
                ) : (
                  <>
                    <ComparisonTable
                      comparison={comparison}
                      papers={shownPapers}
                      members={members}
                      kindOf={kindOf}
                      inspecting={inspecting}
                      onInspect={setInspecting}
                      onRemove={removeFromView}
                    />
                    <ComparisonByField
                      comparison={comparison}
                      papers={shownPapers}
                      kindOf={kindOf}
                      inspecting={inspecting}
                      onInspect={setInspecting}
                    />
                  </>
                )}
                <Legend />
              </section>
            ) : (
              !running && (
                <div className="mt-8 rounded-2xl px-6 py-12 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
                  <h2 className="text-lg font-bold">No comparison yet</h2>
                  <p className="mx-auto mt-2 max-w-[58ch] text-sm leading-relaxed" style={{ color: C.muted }}>
                    Choose the papers and fields above, then compare. The table keeps each value&apos;s passage, and says why a value is missing.
                  </p>
                </div>
              )
            )}
          </>
        )}
      </div>

      {inspecting && inspectedCell && inspectedCell.span && (
        <div className="fixed inset-x-2 bottom-2 z-30 flex max-h-[62dvh] lg:inset-x-auto lg:bottom-6 lg:right-6 lg:top-24 lg:max-h-none lg:w-[400px]">
          <div className="flex min-h-0 w-full flex-col">
            <CellEvidence
              cell={inspectedCell}
              field={inspecting.field}
              paperId={inspecting.paperId}
              kind={kindOf(inspecting.paperId)}
              workspaceId={id}
              onClose={() => setInspecting(null)}
            />
          </div>
        </div>
      )}
    </PageShell>
  );
}

function NavLink({ href, icon, children }: { href: string; icon: ReactNode; children: ReactNode }) {
  return (
    <Link href={href} className={`inline-flex min-h-11 items-center gap-1.5 rounded-sm hover:text-white sm:min-h-0 ${focusRing}`}>
      {icon}
      {children}
    </Link>
  );
}

function PaperChip({ paperId, kind, on, onToggle }: { paperId: string; kind: PaperKind; on: boolean; onToggle: () => void }) {
  const paper = usePaper(paperId);
  const title = paper?.title ?? "Loading…";
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={paper?.year != null ? `${title}, ${paper.year}` : title}
      onClick={onToggle}
      title={title}
      className={`inline-flex min-h-11 max-w-full items-center gap-2 rounded-full px-3 text-[13px] transition-colors sm:min-h-8 ${on ? "" : "hover:bg-white/10"} ${focusRing}`}
      style={on ? { background: "rgba(93,240,168,.14)", border: "1px solid rgba(93,240,168,.45)", color: C.ink } : { ...quietButton, color: C.muted }}
    >
      <NodeGlyph kind={kind} size={11} />
      <span className="truncate">{truncate(title, 40)}</span>
      {paper?.year != null && <span className="shrink-0 tabular-nums" style={{ color: C.muted }}>{paper.year}</span>}
    </button>
  );
}

function abstractOnly(comparison: ComparisonResponse, paperId: string): boolean {
  const row = comparison.rows.find((r) => r.paper_id === paperId);
  return Object.values(row?.cells ?? {}).some((c) => c.grounding === "abstract");
}

/** Wide screens: papers side by side, one column each, fields down the side. */
function ComparisonTable({
  comparison,
  papers,
  members,
  kindOf,
  inspecting,
  onInspect,
  onRemove,
}: {
  comparison: ComparisonResponse;
  papers: string[];
  members: string[];
  kindOf: (id: string) => PaperKind;
  inspecting: Inspecting | null;
  onInspect: (i: Inspecting) => void;
  onRemove: (id: string) => void;
}) {
  return (
    <div className="hidden overflow-x-auto rounded-2xl md:block [scrollbar-color:rgba(150,175,230,.28)_transparent]" style={panel} data-testid="comparison-table">
      <table className="w-full border-collapse text-left">
        <caption className="sr-only">Papers side by side, one column per paper, one row per field</caption>
        <thead>
          <tr>
            <th scope="col" className="sticky left-0 z-10 w-40 min-w-40 px-4 py-3 align-bottom text-[13px] font-medium" style={{ color: C.muted, background: "#0a1024" }}>
              Field
            </th>
            {papers.map((pid) => (
              <th key={pid} scope="col" className="min-w-[230px] border-l px-4 py-3 align-top font-normal" style={{ borderColor: C.line }}>
                <PaperHeading
                  paperId={pid}
                  kind={kindOf(pid)}
                  abstractOnly={abstractOnly(comparison, pid)}
                  inWorkspace={members.includes(pid)}
                  canRemove={papers.length > 1}
                  onRemove={() => onRemove(pid)}
                />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {comparison.schema.map((field) => (
            <tr key={field} className="border-t" style={{ borderColor: C.line }}>
              <th scope="row" className="sticky left-0 z-10 px-4 py-3 align-top text-[13.5px] font-semibold" style={{ background: "#0a1024" }}>
                {fieldLabel(field)}
              </th>
              {papers.map((pid) => {
                const row = comparison.rows.find((r) => r.paper_id === pid);
                return (
                  <td key={pid} className="border-l px-4 py-2.5 align-top" style={{ borderColor: C.line }}>
                    <CellContent
                      cell={row?.cells[field]}
                      field={field}
                      paperId={pid}
                      active={inspecting?.paperId === pid && inspecting.field === field}
                      onOpen={() => onInspect({ paperId: pid, field })}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Narrow screens: one field at a time, every paper's value under it. */
function ComparisonByField({
  comparison,
  papers,
  kindOf,
  inspecting,
  onInspect,
}: {
  comparison: ComparisonResponse;
  papers: string[];
  kindOf: (id: string) => PaperKind;
  inspecting: Inspecting | null;
  onInspect: (i: Inspecting) => void;
}) {
  return (
    <div className="space-y-4 md:hidden" data-testid="comparison-by-field">
      {comparison.schema.map((field) => (
        <section key={field} aria-labelledby={`field-${field}`} className="overflow-hidden rounded-2xl" style={panel}>
          <h3 id={`field-${field}`} className="px-4 pb-1 pt-3 text-[15px] font-bold">
            {fieldLabel(field)}
          </h3>
          <ul>
            {papers.map((pid) => (
              <li key={pid} className="border-t px-4 py-2.5" style={{ borderColor: C.line }}>
                <PaperLine paperId={pid} kind={kindOf(pid)} />
                <CellContent
                  cell={comparison.rows.find((r) => r.paper_id === pid)?.cells[field]}
                  field={field}
                  paperId={pid}
                  active={inspecting?.paperId === pid && inspecting.field === field}
                  onOpen={() => onInspect({ paperId: pid, field })}
                />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function PaperLine({ paperId, kind }: { paperId: string; kind: PaperKind }) {
  const paper = usePaper(paperId);
  return (
    <p className="flex items-center gap-1.5 text-[12.5px]" style={{ color: C.muted }}>
      <NodeGlyph kind={kind} size={10} />
      <span className="truncate">{truncate(paper?.title ?? "", 60)}</span>
    </p>
  );
}

function Legend() {
  return (
    <ul className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-[12.5px]" style={{ color: C.muted }} aria-label="What the empty cells mean">
      <li className="flex items-center gap-1.5">
        <span aria-hidden className="block size-[10px] rounded-full" style={{ border: `1.5px solid ${C.mint}`, background: "rgba(93,240,168,.14)" }} />
        Quoted from the paper: open it for the passage
      </li>
      {(["not_stated", "unsupported", "no_text", "not_extracted"] as const).map((s) => (
        <li key={s} className="flex items-center gap-1.5" title={CELL_COPY[s].meaning}>
          <StatusGlyph status={s} />
          {CELL_COPY[s].label}: {CELL_COPY[s].meaning.charAt(0).toLowerCase() + CELL_COPY[s].meaning.slice(1)}
        </li>
      ))}
    </ul>
  );
}

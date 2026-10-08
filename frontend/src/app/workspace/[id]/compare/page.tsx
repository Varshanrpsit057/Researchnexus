"use client";

import { useCallback, useMemo, useState, type KeyboardEvent, type ReactNode } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import {
  ArrowLeft,
  CaretDown,
  ChatCircleText,
  Check,
  FileArrowDown,
  GitBranch,
  Graph,
  MagnifyingGlass,
  Plus,
  SlidersHorizontal,
  Warning,
  X,
} from "@phosphor-icons/react/dist/ssr";
import { ApiError } from "@/lib/api/client";
import { workspaces } from "@/lib/api/endpoints";
import type { ComparisonCell, ComparisonResponse, ComparisonTable, ComparisonTablePaper } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/auth-context";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import {
  CANONICAL_FIELDS,
  CELL_COPY,
  coverageOf,
  emptyStatusesIn,
  fieldLabel,
  latestComparisonOrNull,
  leftWorkspace,
  normalizeField,
  notYetCompared,
  pickColumns,
} from "@/lib/compare";
import { saveFile } from "@/lib/download";
import { COVERAGE_LABEL } from "@/lib/coverage";
import { shortAuthors } from "@/lib/graph/model";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { Timestamp } from "@/components/ui/Timestamp";
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
  // what to compare: open until there is a comparison, then the table has the room
  const [setupOpen, setSetupOpen] = useState<boolean | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

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
  const setupShown = setupOpen ?? comparison == null;

  // the table the page draws and "Export to Word" writes: one model, from the server
  const tableQ = useSWR(comparison ? ["ws-comparison-table", id, comparison.comparison_id] : null, () =>
    workspaces.comparisonTable(id, comparison!.comparison_id),
  );
  const fullTable = tableQ.data && tableQ.data.comparison_id === comparison?.comparison_id ? tableQ.data : null;
  const table = fullTable ? pickColumns(fullTable, shownPapers) : null;

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
      setSetupOpen(false);
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

  async function exportToWord() {
    if (!comparison || shownPapers.length === 0 || exporting) return;
    setExporting(true);
    setExportError(null);
    try {
      // the columns on screen, in the table's order: the server writes exactly these
      const { blob, filename } = await workspaces.exportComparisonDocx(id, comparison.comparison_id, shownPapers);
      saveFile(blob, filename ?? "Comparison.docx");
      setAnnouncement("The comparison table was saved as a Word document.");
    } catch (e) {
      setExportError(
        e instanceof ApiError
          ? `The Word document couldn't be made: ${e.message}. Try again.`
          : "The server couldn't be reached, so the Word document wasn't made. Check the connection and try again.",
      );
    } finally {
      setExporting(false);
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

  const inspectedCell: ComparisonCell | undefined =
    inspecting && comparison ? comparison.rows.find((r) => r.paper_id === inspecting.paperId)?.cells[inspecting.field] : undefined;

  return (
    <PageShell maxWidthClassName="max-w-[1560px]">
      <div className="selection:bg-[rgba(93,240,168,0.28)] selection:text-white">
        <header className="border-b pb-5" style={{ borderColor: C.line }}>
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
          <div className="mt-3 flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
            <div className="min-w-0 max-w-[82ch]">
              <h1 className="text-[clamp(24px,2.6vw,32px)] font-extrabold leading-[1.1] tracking-[-0.02em]">Compare papers</h1>
              <p className="mt-2 text-[14.5px] leading-relaxed" style={{ color: C.muted }}>
                {comparison && coverage ? (
                  <>
                    <span className="tabular-nums">{shownPapers.length}</span> papers side by side,{" "}
                    <span className="tabular-nums">{comparison.schema.length}</span> fields.{" "}
                    <span className="tabular-nums">{coverage.found}</span> of <span className="tabular-nums">{coverage.total}</span> values are
                    stated in the papers&apos; own text; open one to read the passage it is quoted from.
                  </>
                ) : (
                  "Put two or more papers side by side. A value appears only when a passage of the paper states it word for word; every gap says why it is empty."
                )}
              </p>
            </div>
            {comparison && members.length >= 2 && (
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <button
                  type="button"
                  aria-expanded={setupShown}
                  aria-controls="compare-setup-panel"
                  onClick={() => setSetupOpen(!setupShown)}
                  className={`inline-flex min-h-10 items-center gap-2 rounded-full px-4 text-[13.5px] font-semibold transition-colors hover:bg-white/10 ${focusRing}`}
                  style={{ ...quietButton, color: C.ink }}
                >
                  <SlidersHorizontal className="size-4" aria-hidden />
                  Papers and fields
                  <span className="font-normal tabular-nums" style={{ color: C.muted }}>
                    {chosen.length} · {(fields ?? comparison.schema).length}
                  </span>
                  <CaretDown className={`size-3.5 transition-transform ${setupShown ? "rotate-180" : ""}`} weight="bold" aria-hidden />
                </button>
                <button
                  type="button"
                  onClick={exportToWord}
                  disabled={exporting || shownPapers.length === 0}
                  className={`inline-flex min-h-10 items-center gap-2 rounded-full px-4 text-[13.5px] font-semibold transition-[opacity,transform] active:scale-[0.97] disabled:opacity-45 ${focusRing}`}
                  style={primaryButton}
                >
                  <FileArrowDown className="size-4" weight="bold" aria-hidden />
                  {exporting ? "Exporting…" : "Export to Word"}
                </button>
              </div>
            )}
          </div>
          {exportError && (
            <div className="mt-3">
              <InlineError message={exportError} />
            </div>
          )}
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
            <div role="status" className="mt-6 space-y-3">
              <span className="sr-only">Loading the comparison…</span>
              <div className="h-[60dvh] rounded-xl motion-safe:animate-pulse" style={panel} />
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
            {setupShown && (
              <section id="compare-setup-panel" aria-labelledby="compare-setup" className="mt-5 rounded-2xl p-5" style={panel}>
                <h2 id="compare-setup" className="text-base font-bold">
                  What to compare
                </h2>
                <div className="mt-4 grid grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[1fr_1fr]">
                  <PaperPicker
                    members={members}
                    chosen={chosen}
                    kindOf={kindOf}
                    onToggle={toggle}
                    onSet={(ids) => setSelected(ids)}
                  />
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
                          <Link href="/settings#models" className={`rounded-sm font-semibold underline underline-offset-4 ${focusRing}`}>
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
            )}

            {running && (
              <div role="status" className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl px-5 py-4" style={panel}>
                <WorkingTrail count={chosen.length} />
                <p className="text-[13px]" style={{ color: C.muted }}>
                  Reading {chosen.length} papers and checking every value against its passage. This can take a minute.
                </p>
              </div>
            )}

            {comparison ? (
              <section aria-labelledby="compare-table" className="mt-5">
                <h2 id="compare-table" className="sr-only">
                  The comparison
                </h2>
                <div className="mb-2.5 flex flex-wrap items-baseline gap-x-5 gap-y-1 text-[13px]" style={{ color: C.muted }}>
                  {comparison.created_at && (
                    <p data-testid="compared-at">
                      Compared <Timestamp at={comparison.created_at} />
                    </p>
                  )}
                  {gone.length > 0 && (
                    <p>
                      {gone.length} compared paper{gone.length === 1 ? " is" : "s are"} no longer in the workspace and still shown here.
                    </p>
                  )}
                </div>
                {table && <FullTextSince papers={table.papers.filter((p) => p.read_from === "abstract")} />}
                {shownPapers.length === 0 ? (
                  <div className="rounded-2xl px-6 py-10 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
                    <p className="text-sm" style={{ color: C.muted }}>
                      Every paper was removed from the view. Open &ldquo;Papers and fields&rdquo; to show their columns again.
                    </p>
                  </div>
                ) : table ? (
                  <>
                    <ComparisonGrid
                      table={table}
                      comparison={comparison}
                      inspecting={inspecting}
                      onInspect={setInspecting}
                      onRemove={removeFromView}
                    />
                    <ComparisonByField table={table} comparison={comparison} inspecting={inspecting} onInspect={setInspecting} />
                    <Legend table={table} />
                  </>
                ) : tableQ.error ? (
                  <div className="rounded-2xl p-6" style={panel}>
                    <InlineError message="Could not load the comparison table." />
                    <button type="button" onClick={() => tableQ.mutate()} className={`mt-4 rounded-full px-5 py-2.5 text-sm font-semibold ${focusRing}`} style={primaryButton}>
                      Try again
                    </button>
                  </div>
                ) : (
                  <div role="status" className="h-[50dvh] rounded-xl motion-safe:animate-pulse" style={panel}>
                    <span className="sr-only">Loading the comparison table…</span>
                  </div>
                )}
              </section>
            ) : (
              !running && (
                <div className="mt-6 rounded-2xl px-6 py-12 text-center" style={{ ...panel, border: `1px dashed ${C.lineStrong}` }}>
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

/** The workspace's papers, each named in full with its authors, year and
 * what text it has; a search once the list is long. */
function PaperPicker({
  members,
  chosen,
  kindOf,
  onToggle,
  onSet,
}: {
  members: string[];
  chosen: string[];
  kindOf: (id: string) => PaperKind;
  onToggle: (id: string) => void;
  onSet: (ids: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px]" style={{ color: C.muted }}>
          Papers <span className="tabular-nums">· {chosen.length} of {members.length}</span>
        </p>
        <div className="flex items-center gap-1 text-[12.5px]" style={{ color: C.muted }}>
          <button type="button" onClick={() => onSet(members)} className={`rounded px-1.5 py-0.5 hover:text-white ${focusRing}`}>
            All
          </button>
          <span aria-hidden>·</span>
          <button type="button" onClick={() => onSet([])} className={`rounded px-1.5 py-0.5 hover:text-white ${focusRing}`}>
            None
          </button>
        </div>
      </div>
      {members.length > 6 && (
        <label className="mt-2 flex items-center gap-2 rounded-lg px-3" style={quietButton}>
          <MagnifyingGlass className="size-4 shrink-0" style={{ color: C.muted }} aria-hidden />
          <span className="sr-only">Find a paper</span>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a paper by title, author or year"
            className="min-h-9 min-w-0 flex-1 bg-transparent text-[13px] caret-[#5df0a8] outline-none placeholder:text-[#8f9bb8]"
            style={{ color: C.ink }}
          />
        </label>
      )}
      <ul
        aria-label="Papers to compare"
        className="peer mt-2 max-h-[300px] space-y-0.5 overflow-y-auto overscroll-contain pr-1 [scrollbar-color:rgba(150,175,230,.28)_transparent]"
      >
        {members.map((pid) => (
          <PaperOption key={pid} paperId={pid} kind={kindOf(pid)} on={chosen.includes(pid)} query={q} onToggle={() => onToggle(pid)} />
        ))}
      </ul>
      <p className="mt-2 hidden text-[13px] peer-empty:block" style={{ color: C.muted }}>
        No paper matches &ldquo;{query.trim()}&rdquo;.
      </p>
    </div>
  );
}

function PaperOption({
  paperId,
  kind,
  on,
  query,
  onToggle,
}: {
  paperId: string;
  kind: PaperKind;
  on: boolean;
  query: string;
  onToggle: () => void;
}) {
  const paper = usePaper(paperId);
  const title = paper?.title ?? "Loading…";
  const meta = [
    shortAuthors(paper?.authors ?? []),
    paper?.year != null ? String(paper.year) : null,
    paper?.coverage ? COVERAGE_LABEL[paper.coverage.state] : null,
  ]
    .filter(Boolean)
    .join(" · ");
  if (query && !`${title} ${meta}`.toLowerCase().includes(query)) return null;
  return (
    <li>
      <button
        type="button"
        aria-pressed={on}
        onClick={onToggle}
        className={`flex w-full items-start gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-white/[0.06] ${focusRing}`}
        style={on ? { background: "rgba(93,240,168,.07)" } : undefined}
      >
        <span
          aria-hidden
          className="mt-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded transition-colors"
          style={on ? { background: C.mint } : { border: `1.5px solid ${C.lineStrong}` }}
        >
          {on && <Check className="size-3" weight="bold" style={{ color: C.mintInk }} />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-start gap-1.5 text-[13.5px] font-semibold leading-snug text-pretty" style={{ color: on ? C.ink : C.muted }}>
            <span className="mt-[5px] shrink-0">
              <NodeGlyph kind={kind} size={9} />
            </span>
            {title}
          </span>
          {meta && (
            <span className="mt-0.5 block pl-[15px] text-[12px] leading-snug" style={{ color: C.muted2 }}>
              {meta}
            </span>
          )}
        </span>
      </button>
    </li>
  );
}

/** Papers compared from their abstract whose full text has been found since. */
function FullTextSince({ papers }: { papers: ComparisonTablePaper[] }) {
  if (papers.length === 0) return null;
  return (
    <ul className="mb-2.5 space-y-1 text-[13px]" style={{ color: C.muted }}>
      {papers.map((p) => (
        <FullTextFound key={p.paper_id} paper={p} />
      ))}
    </ul>
  );
}

function FullTextFound({ paper }: { paper: ComparisonTablePaper }) {
  const record = usePaper(paper.paper_id);
  if (record?.coverage?.state !== "full_text") return null;
  return <li>&ldquo;{paper.title}&rdquo; was compared from its abstract; its full text has been found since. Compare again to read it.</li>;
}

const FIELD_COL = 176;
const PAPER_COL_MIN = 264;

/** Wide screens: the papers side by side, numbered and named in full, the
 * fields down a sticky first column, the header pinned while the rows scroll. */
function ComparisonGrid({
  table,
  comparison,
  inspecting,
  onInspect,
  onRemove,
}: {
  table: ComparisonTable;
  comparison: ComparisonResponse;
  inspecting: Inspecting | null;
  onInspect: (i: Inspecting) => void;
  onRemove: (id: string) => void;
}) {
  const evidence = new Map(comparison.rows.map((r) => [r.paper_id, r.cells]));
  return (
    <div
      role="region"
      aria-label="Comparison table"
      tabIndex={0}
      // relative: the containing block for the cells' screen-reader text, which
      // otherwise escaped the scroll box and made the page 800 px too wide
      className={`relative hidden max-h-[calc(100dvh-7.5rem)] overflow-auto overscroll-contain rounded-xl md:block [scrollbar-color:rgba(150,175,230,.28)_transparent] ${focusRing}`}
      style={{ border: `1px solid ${C.lineStrong}`, background: "rgba(7,11,26,.78)" }}
      data-testid="comparison-table"
    >
      <table className="w-full table-fixed border-separate border-spacing-0 text-left" style={{ minWidth: FIELD_COL + table.papers.length * PAPER_COL_MIN }}>
        <caption className="sr-only">Papers side by side, one column per paper, one row per field</caption>
        <colgroup>
          <col style={{ width: FIELD_COL }} />
          {table.papers.map((p) => (
            <col key={p.paper_id} />
          ))}
        </colgroup>
        <thead>
          <tr>
            <th
              scope="col"
              className="sticky left-0 top-0 z-30 border-b border-r px-4 py-3.5 align-bottom text-[12px] font-semibold uppercase tracking-[0.08em]"
              style={{ color: C.muted2, background: "#0c1226", borderColor: C.lineStrong }}
            >
              {table.corner}
            </th>
            {table.papers.map((p, i) => (
              <th
                key={p.paper_id}
                scope="col"
                className="sticky top-0 z-20 border-b px-4 py-3.5 align-top font-normal [&:not(:last-child)]:border-r"
                style={{ background: "#0c1226", borderColor: C.lineStrong }}
                data-paper-id={p.paper_id}
              >
                <PaperHeading paper={p} index={i + 1} canRemove={table.papers.length > 1} onRemove={() => onRemove(p.paper_id)} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, r) => (
            <tr key={row.field} className="group/row">
              <th
                scope="row"
                className={`sticky left-0 z-10 border-r px-4 py-3 align-top text-[13.5px] font-semibold leading-snug ${r > 0 ? "border-t" : ""}`}
                style={{ background: "#0a0f21", borderColor: C.line }}
              >
                {row.label}
              </th>
              {row.cells.map((cell, c) => {
                const paper = table.papers[c];
                const source = evidence.get(cell.paper_id)?.[row.field];
                return (
                  <td
                    key={cell.paper_id}
                    className={`px-4 py-2 align-top transition-colors group-hover/row:bg-white/[0.025] [&:not(:last-child)]:border-r ${r > 0 ? "border-t" : ""}`}
                    style={{ borderColor: C.line }}
                  >
                    <CellContent
                      cell={cell}
                      label={row.label}
                      paperTitle={paper.title}
                      active={inspecting?.paperId === cell.paper_id && inspecting.field === row.field}
                      onOpen={source?.span ? () => onInspect({ paperId: cell.paper_id, field: row.field }) : undefined}
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
  table,
  comparison,
  inspecting,
  onInspect,
}: {
  table: ComparisonTable;
  comparison: ComparisonResponse;
  inspecting: Inspecting | null;
  onInspect: (i: Inspecting) => void;
}) {
  const evidence = new Map(comparison.rows.map((r) => [r.paper_id, r.cells]));
  return (
    <div className="space-y-4 md:hidden" data-testid="comparison-by-field">
      {table.rows.map((row) => (
        <section key={row.field} aria-labelledby={`field-${row.field}`} className="overflow-hidden rounded-2xl" style={panel}>
          <h3 id={`field-${row.field}`} className="px-4 pb-1 pt-3 text-[15px] font-bold">
            {row.label}
          </h3>
          <ul>
            {row.cells.map((cell, c) => {
              const paper = table.papers[c];
              return (
                <li key={cell.paper_id} className="border-t px-4 py-2.5" style={{ borderColor: C.line }}>
                  <p className="flex items-start gap-1.5 text-[12.5px] leading-snug" style={{ color: C.muted }}>
                    <span className="mt-[3px] shrink-0">
                      <NodeGlyph kind={paper.kind} size={10} />
                    </span>
                    {paper.title}
                  </p>
                  <CellContent
                    cell={cell}
                    label={row.label}
                    paperTitle={paper.title}
                    active={inspecting?.paperId === cell.paper_id && inspecting.field === row.field}
                    onOpen={evidence.get(cell.paper_id)?.[row.field]?.span ? () => onInspect({ paperId: cell.paper_id, field: row.field }) : undefined}
                  />
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

/** What the marks mean -- only the ones this table has. */
function Legend({ table }: { table: ComparisonTable }) {
  return (
    <ul className="mt-3 flex flex-wrap gap-x-6 gap-y-1.5 text-[12.5px]" style={{ color: C.muted }} aria-label="What the cells mean">
      <li className="flex items-center gap-1.5">
        <span aria-hidden className="block size-[9px] rounded-full" style={{ border: `1.5px solid ${C.mint}`, background: "rgba(93,240,168,.14)" }} />
        Quoted from the paper: open it for the passage
      </li>
      {emptyStatusesIn(table).map((s) => (
        <li key={s} className="flex items-center gap-1.5">
          <StatusGlyph status={s} />
          <span>
            <span className="font-medium" style={{ color: C.ink }}>
              {CELL_COPY[s].label}
            </span>
            : {CELL_COPY[s].meaning.charAt(0).toLowerCase() + CELL_COPY[s].meaning.slice(1)}
          </span>
        </li>
      ))}
    </ul>
  );
}

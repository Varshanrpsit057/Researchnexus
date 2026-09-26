"use client";

import { forwardRef, useId, useState, type ComponentType, type ReactNode } from "react";
import Link from "next/link";
import { ArrowSquareOut, ChatCircleText, Check, Copy, Crosshair, GitBranch, Signpost, Table } from "@phosphor-icons/react/dist/ssr";
import type { CitationFormat, CitationUse, CitationUseKind, LedgerPaper, SeedReference } from "@/lib/api/types";
import { location } from "@/lib/chat";
import { NOT_AVAILABLE, RESOLVED_COPY, STYLE_LABEL, USE_COPY, USE_KINDS, relationOf, totalUses, useHref, useLinkLabel } from "@/lib/citations";
import { fieldLabel } from "@/lib/compare";
import { RELATIONSHIP_COPY } from "@/lib/trail";
import { NodeGlyph } from "../graph/GraphPanel";
import { usePaper, type PaperKind } from "../compare/parts";
import { C, focusRing, quietButton } from "../ui";

export const USE_ICON: Record<CitationUseKind, ComponentType<{ className?: string; style?: React.CSSProperties; "aria-hidden"?: boolean }>> = {
  answer: ChatCircleText,
  comparison: Table,
  gap: Crosshair,
  direction: Signpost,
};

export function shortAuthors(authors: string[]): string {
  if (authors.length === 0) return "";
  if (authors.length <= 3) return authors.join(", ");
  return `${authors.slice(0, 2).join(", ")} et al.`;
}

/** How often, and where, the workspace cites a paper: one mark per kind it appears in. */
function UseStrip({ paper }: { paper: LedgerPaper }) {
  const total = totalUses(paper);
  if (total === 0) {
    return (
      <span className="text-[12.5px]" style={{ color: C.muted }}>
        Not cited in the workspace yet
      </span>
    );
  }
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]" style={{ color: C.muted }}>
      {USE_KINDS.filter((k) => paper.counts[k] > 0).map((k) => {
        const Icon = USE_ICON[k];
        return (
          <span key={k} className="inline-flex items-center gap-1">
            <Icon className="size-3.5" style={{ color: C.mint }} aria-hidden />
            <span style={{ color: C.ink }}>{USE_COPY[k].label}</span>
            <span className="tabular-nums">{paper.counts[k]}</span>
          </span>
        );
      })}
    </span>
  );
}

export function LedgerRow({ paper, kind, selected, onSelect }: { paper: LedgerPaper; kind: PaperKind; selected: boolean; onSelect: () => void }) {
  const relation = relationOf(paper);
  const meta = [shortAuthors(paper.authors), paper.year != null ? String(paper.year) : null, paper.venue].filter(Boolean).join(" · ");
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={`flex w-full gap-3 rounded-xl px-4 py-3.5 text-left transition-colors ${selected ? "" : "hover:bg-white/[0.04]"} ${focusRing}`}
      style={selected ? { background: "rgba(93,240,168,.07)", boxShadow: "inset 0 0 0 1px rgba(93,240,168,.35)" } : undefined}
    >
      <span className="mt-[5px]">
        <NodeGlyph kind={kind} size={12} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] font-semibold leading-snug [overflow-wrap:anywhere]" style={{ color: C.ink }}>
          {paper.title}
        </span>
        {meta && (
          <span className="mt-0.5 block truncate text-[12.5px]" style={{ color: C.muted }}>
            {meta}
          </span>
        )}
        {(paper.role === "seed" || relation) && (
          <span className="mt-1 block text-[12.5px]" style={{ color: C.mint }}>
            {paper.role === "seed" ? "Seed paper" : relation}
          </span>
        )}
        <span className="mt-2 block">
          <UseStrip paper={paper} />
        </span>
      </span>
    </button>
  );
}

function CopyButton({ text, label, onCopied }: { text: string; label: string; onCopied: (message: string) => void }) {
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setDone(true);
      onCopied(`${label} copied.`);
      setTimeout(() => setDone(false), 1600);
    } catch {
      onCopied("Couldn't copy; select the text instead.");
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={`Copy ${label}`}
      className={`inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-full px-3 text-[13px] font-semibold transition-colors hover:bg-white/10 sm:min-h-8 ${focusRing}`}
      style={quietButton}
    >
      {done ? <Check className="size-3.5" weight="bold" style={{ color: C.mint }} aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      {done ? "Copied" : "Copy"}
    </button>
  );
}

/** One place the workspace cites the paper: its own words, then the passage they rest on. */
function UseItem({ use, workspaceId }: { use: CitationUse; workspaceId: string }) {
  const Icon = USE_ICON[use.kind];
  const where = location({ section: use.section, page: use.page });
  const words = use.kind === "comparison" && use.field ? `${fieldLabel(use.field)}: ${use.text}` : use.text;
  return (
    <li className="relative pl-7">
      <span className="absolute left-0 top-[1px] flex size-[15px] items-center justify-center rounded-full" style={{ background: "#0a0f22", boxShadow: "0 0 0 3px #0a0f22" }}>
        <Icon className="size-[15px]" style={{ color: C.mint }} aria-hidden />
      </span>
      <p className="text-[12.5px]" style={{ color: C.muted }}>
        {USE_COPY[use.kind].where}
        {use.state && use.state !== "candidate" ? ` · ${use.state}` : use.state === "candidate" ? " · to review" : ""}
      </p>
      <p className="mt-1 text-[14.5px] leading-snug [overflow-wrap:anywhere]" style={{ color: C.ink }}>
        {words}
      </p>
      {use.quote && (
        <>
          <p className="mt-2 text-[12.5px]" style={{ color: C.muted }}>
            The passage it rests on{where ? ` · ${where}` : ""}
          </p>
          <blockquote className="mt-1 line-clamp-6 border-l pl-3 text-[14.5px] leading-relaxed [overflow-wrap:anywhere]" style={{ borderColor: "rgba(93,240,168,.5)" }}>
            &ldquo;{use.quote}&rdquo;
          </blockquote>
        </>
      )}
      <Link
        href={useHref(workspaceId, use)}
        className={`mt-1.5 inline-flex min-h-11 items-center gap-1 rounded-sm text-[13px] font-medium underline-offset-4 hover:text-white hover:underline sm:min-h-0 ${focusRing}`}
        style={{ color: C.muted }}
      >
        {useLinkLabel(use)}
      </Link>
    </li>
  );
}

function ConnectionItem({ edgeId, type, otherId, direction, workspaceId, onPick, inLedger }: {
  edgeId: string;
  type: keyof typeof RELATIONSHIP_COPY;
  otherId: string;
  direction: "in" | "out";
  workspaceId: string;
  onPick: (id: string) => void;
  inLedger: boolean;
}) {
  const other = usePaper(otherId);
  const title = other?.title ?? "Loading…";
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-[14px] leading-snug">
      <span style={{ color: C.muted }}>{RELATIONSHIP_COPY[type]?.singular ?? type}</span>
      <span style={{ color: C.muted }}>{direction === "in" ? "from" : "to"}</span>
      {inLedger ? (
        <button type="button" onClick={() => onPick(otherId)} className={`rounded-sm text-left font-semibold hover:underline hover:underline-offset-4 ${focusRing}`}>
          {title}
        </button>
      ) : (
        <Link href={`/papers/${otherId}`} className={`rounded-sm font-semibold hover:underline hover:underline-offset-4 ${focusRing}`}>
          {title}
        </Link>
      )}
      <Link
        href={`/workspace/${workspaceId}/trail?edge=${encodeURIComponent(edgeId)}`}
        className={`ml-auto inline-flex min-h-11 items-center gap-1 rounded-sm text-[13px] hover:text-white sm:min-h-0 ${focusRing}`}
        style={{ color: C.muted }}
      >
        <GitBranch className="size-3.5" aria-hidden />
        In the trail
      </Link>
    </li>
  );
}

function SeedReferences({ refs, ledgerIds, onPick }: { refs: SeedReference[]; ledgerIds: Set<string>; onPick: (id: string) => void }) {
  const matched = refs.filter((r) => r.paper_id).length;
  return (
    <section className="mt-8 border-t pt-6" style={{ borderColor: C.line }} aria-label="The seed paper's references">
      <h3 className="flex flex-wrap items-baseline gap-x-2 text-[15px] font-bold">
        Its references
        <span className="text-[13px] font-normal" style={{ color: C.muted }}>
          <span className="tabular-nums">{refs.length}</span> listed; the trail matched <span className="tabular-nums">{matched}</span> to a paper
        </span>
      </h3>
      <ol className="mt-3 space-y-2">
        {refs.map((r) => (
          <li key={r.order} className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-3 rounded-lg px-3 py-2" style={r.paper_id ? { background: "rgba(93,240,168,.06)" } : undefined}>
            <span className="text-[13.5px] leading-snug [overflow-wrap:anywhere]" style={{ color: r.paper_id ? C.ink : C.muted }}>
              {r.text}
            </span>
            {r.paper_id &&
              (ledgerIds.has(r.paper_id) ? (
                <button
                  type="button"
                  onClick={() => onPick(r.paper_id!)}
                  className={`min-h-11 shrink-0 rounded-sm text-[13px] font-semibold hover:underline hover:underline-offset-4 sm:min-h-0 ${focusRing}`}
                  style={{ color: C.mint }}
                >
                  In this workspace
                </button>
              ) : (
                <Link href={`/papers/${r.paper_id}`} className={`inline-flex min-h-11 shrink-0 items-center rounded-sm text-[13px] font-semibold hover:underline hover:underline-offset-4 sm:min-h-0 ${focusRing}`} style={{ color: C.mint }}>
                  Open the paper
                </Link>
              ))}
          </li>
        ))}
      </ol>
    </section>
  );
}

export const PaperDossier = forwardRef<
  HTMLHeadingElement,
  {
    paper: LedgerPaper;
    kind: PaperKind;
    workspaceId: string;
    style: CitationFormat;
    onStyle: (style: CitationFormat) => void;
    seedReferences: SeedReference[];
    ledgerIds: Set<string>;
    onPick: (paperId: string) => void;
    onAnnounce: (message: string) => void;
    footer: ReactNode;
  }
>(function PaperDossier({ paper, kind, workspaceId, style, onStyle, seedReferences, ledgerIds, onPick, onAnnounce, footer }, headingRef) {
  const headingId = useId();
  const reference = paper.reference.formatted[style];
  const buildable = !!reference && reference !== NOT_AVAILABLE;
  const relation = relationOf(paper);
  const total = totalUses(paper);
  const ids = [
    paper.doi ? { label: `doi:${paper.doi}`, href: `https://doi.org/${paper.doi}` } : null,
    paper.arxiv_id ? { label: `arXiv:${paper.arxiv_id}`, href: `https://arxiv.org/abs/${paper.arxiv_id}` } : null,
    paper.url && !paper.doi && !paper.arxiv_id ? { label: "Publisher page", href: paper.url } : null,
  ].filter((x): x is { label: string; href: string } => x != null);

  return (
    <article aria-labelledby={headingId} className="flex min-h-full flex-col">
      <div className="flex-1 px-5 pb-6 pt-5 sm:px-6">
        <p className="flex flex-wrap items-center gap-x-2 text-[13px]" style={{ color: C.muted }}>
          <NodeGlyph kind={kind} size={11} />
          <span style={{ color: C.ink }}>{paper.role === "seed" ? "Seed paper" : "In this workspace"}</span>
          <span>· {paper.grounding === "full_text" ? "Full text" : "Abstract only"}</span>
          {paper.reference_count != null && <span>· lists {paper.reference_count} references</span>}
        </p>
        <h2
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="mt-2.5 text-[clamp(20px,2.1vw,24px)] font-bold leading-[1.25] tracking-[-0.01em] outline-none [overflow-wrap:anywhere] [text-wrap:balance]"
        >
          {paper.title}
        </h2>
        {paper.authors.length > 0 && <p className="mt-2 text-[14px] leading-relaxed">{paper.authors.join(", ")}</p>}
        <p className="mt-0.5 text-[13.5px]" style={{ color: C.muted }}>
          {[paper.year != null ? String(paper.year) : "Year unknown", paper.venue].filter(Boolean).join(" · ")}
          {relation && (
            <>
              {" "}
              · <span style={{ color: C.mint }}>{relation}</span>
            </>
          )}
        </p>
        {ids.length > 0 && (
          <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
            {ids.map((i) => (
              <a
                key={i.href}
                href={i.href}
                target="_blank"
                rel="noopener noreferrer"
                className={`inline-flex min-h-11 items-center gap-1 rounded-sm font-mono text-[12.5px] hover:text-white sm:min-h-0 ${focusRing}`}
                style={{ color: C.muted }}
              >
                {i.label}
                <ArrowSquareOut className="size-3.5" aria-hidden />
                <span className="sr-only">(opens in a new tab)</span>
              </a>
            ))}
          </p>
        )}

        {/* the reference, in the chosen style */}
        <section aria-label="Reference" className="mt-5 rounded-xl" style={{ border: `1px solid ${C.line}`, background: "rgba(255,255,255,.02)" }}>
          <div className="flex items-center justify-between gap-3 border-b px-2 py-1.5" style={{ borderColor: C.line }}>
            <div role="group" aria-label="Reference style" className="flex gap-0.5">
              {(Object.keys(STYLE_LABEL) as CitationFormat[]).map((s) => (
                <button
                  key={s}
                  type="button"
                  aria-pressed={style === s}
                  onClick={() => onStyle(s)}
                  className={`min-h-11 rounded-full px-2.5 text-[12.5px] font-semibold transition-colors sm:min-h-8 ${style === s ? "" : "hover:bg-white/10"} ${focusRing}`}
                  style={style === s ? { background: "rgba(93,240,168,.14)", color: C.ink } : { color: C.muted }}
                >
                  {STYLE_LABEL[s]}
                </button>
              ))}
            </div>
            {buildable && <CopyButton text={reference!} label={`${STYLE_LABEL[style]} reference`} onCopied={onAnnounce} />}
          </div>
          {buildable ? (
            style === "bibtex" ? (
              <pre className="overflow-x-auto px-4 py-3 font-mono text-[12.5px] leading-relaxed [scrollbar-color:rgba(150,175,230,.28)_transparent]">{reference}</pre>
            ) : (
              <p className="px-4 py-3 text-[14.5px] leading-relaxed [overflow-wrap:anywhere]">{reference}</p>
            )
          ) : (
            <p className="px-4 py-3 text-[14px]" style={{ color: C.muted }}>
              Not available: the paper has no title to cite. A reference is never guessed.
            </p>
          )}
          <p className="border-t px-4 py-2 text-[12.5px]" style={{ borderColor: C.line, color: C.muted }}>
            {RESOLVED_COPY[paper.reference.resolved_from] ?? paper.reference.resolved_from}; formatted by rule, never generated.
          </p>
        </section>

        {/* where the workspace cites it, each with its passage */}
        <section aria-labelledby={`${headingId}-uses`} className="mt-8">
          <h3 id={`${headingId}-uses`} className="flex flex-wrap items-baseline gap-x-2 text-[15px] font-bold">
            Where this workspace cites it
            <span className="text-[13px] font-normal" style={{ color: C.muted }}>
              {total === 0 ? "nowhere yet" : `${total} time${total === 1 ? "" : "s"}, each with the passage it rests on`}
            </span>
          </h3>
          {total === 0 ? (
            <p className="mt-2 text-[14px] leading-relaxed" style={{ color: C.muted }}>
              Nothing in the workspace rests on this paper yet.{" "}
              <Link href={`/workspace/${workspaceId}/chat`} className={`rounded-sm underline underline-offset-4 hover:text-white ${focusRing}`}>
                Ask a question
              </Link>
              ,{" "}
              <Link href={`/workspace/${workspaceId}/compare`} className={`rounded-sm underline underline-offset-4 hover:text-white ${focusRing}`}>
                compare the papers
              </Link>{" "}
              or{" "}
              <Link href={`/workspace/${workspaceId}/gaps`} className={`rounded-sm underline underline-offset-4 hover:text-white ${focusRing}`}>
                look for gaps
              </Link>
              ; every passage used is recorded here.
            </p>
          ) : (
            <ol className="relative mt-4 space-y-5">
              <span aria-hidden className="absolute bottom-3 left-[7px] top-2 w-px" style={{ background: "linear-gradient(to bottom, rgba(93,240,168,.55), rgba(93,240,168,.1))" }} />
              {paper.uses.map((u, i) => (
                <UseItem key={`${u.kind}-${u.artefact_id}-${u.field ?? ""}-${i}`} use={u} workspaceId={workspaceId} />
              ))}
            </ol>
          )}
        </section>

        {paper.connections.length > 0 && (
          <section className="mt-8 border-t pt-6" style={{ borderColor: C.line }} aria-label="In the research trail">
            <h3 className="text-[15px] font-bold">In the research trail</h3>
            <ul className="mt-3 space-y-2">
              {paper.connections.map((c) => (
                <ConnectionItem
                  key={c.edge_id}
                  edgeId={c.edge_id}
                  type={c.type}
                  otherId={c.other_paper_id}
                  direction={c.direction}
                  workspaceId={workspaceId}
                  onPick={onPick}
                  inLedger={ledgerIds.has(c.other_paper_id)}
                />
              ))}
            </ul>
          </section>
        )}

        {paper.role === "seed" && seedReferences.length > 0 && <SeedReferences refs={seedReferences} ledgerIds={ledgerIds} onPick={onPick} />}
      </div>
      <div className="sticky bottom-0 border-t px-5 py-3.5 sm:px-6" style={{ borderColor: C.line, background: "#090d1c" }}>
        {footer}
      </div>
    </article>
  );
});

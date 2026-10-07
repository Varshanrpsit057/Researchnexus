"use client";

import { useEffect, useId, type ReactNode } from "react";
import Link from "next/link";
import useSWR from "swr";
import { ArrowSquareOut, Graph, X } from "@phosphor-icons/react/dist/ssr";
import { papers as papersApi } from "@/lib/api/endpoints";
import type { CellStatus, ComparisonCell, ComparisonTableCell, ComparisonTablePaper } from "@/lib/api/types";
import { CELL_COPY, fieldLabel } from "@/lib/compare";
import { location } from "@/lib/chat";
import { NodeGlyph } from "../graph/GraphPanel";
import { C, focusRing, quietButton } from "../ui";
import chatStyles from "../chat/chat.module.css";

export type PaperKind = "seed" | "member" | "connected";

/** A paper's own record (title, authors, year), from the cache the other workspace pages share. */
export function usePaper(paperId: string) {
  return useSWR(["paper", paperId], () => papersApi.get(paperId)).data;
}

/** A drawn mark per empty state, so a state never rests on colour alone. */
export function StatusGlyph({ status }: { status: Exclude<CellStatus, "found"> }) {
  const common = { width: 12, height: 12, viewBox: "0 0 12 12", "aria-hidden": true, className: "shrink-0" } as const;
  switch (status) {
    case "not_stated":
      return (
        <svg {...common}>
          <line x1="2.5" y1="6" x2="9.5" y2="6" stroke={C.muted} strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "unsupported":
      return (
        <svg {...common}>
          <circle cx="6" cy="6" r="4.6" fill="none" stroke={C.warning} strokeWidth="1.4" strokeDasharray="2 1.6" />
        </svg>
      );
    case "no_text":
      return (
        <svg {...common}>
          <rect x="2" y="1.5" width="8" height="9" rx="1" fill="none" stroke={C.muted} strokeWidth="1.3" />
          <line x1="3" y1="10" x2="9" y2="2" stroke={C.muted} strokeWidth="1.3" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <circle cx="6" cy="6" r="4.6" fill="none" stroke={C.muted} strokeWidth="1.4" />
          <line x1="6" y1="3.6" x2="6" y2="6.6" stroke={C.muted} strokeWidth="1.4" strokeLinecap="round" />
          <circle cx="6" cy="8.4" r=".8" fill={C.muted} />
        </svg>
      );
  }
}

/** One value of the comparison: quoted and inspectable, or an honest reason it is empty.
 * Its text is the table model's -- the same words the Word export writes. */
export function CellContent({
  cell,
  label,
  paperTitle,
  active,
  onOpen,
}: {
  cell: ComparisonTableCell;
  label: string;
  paperTitle: string;
  active: boolean;
  /** absent when there is no passage to open */
  onOpen?: () => void;
}) {
  if (cell.status === "found") {
    const value = (
      <span className="min-w-0 flex-1 whitespace-pre-line text-pretty font-medium" data-cell-text>
        {cell.text}
      </span>
    );
    return (
      <div>
        {onOpen ? (
          <button
            type="button"
            onClick={onOpen}
            aria-pressed={active}
            aria-label={`${label} for ${paperTitle}: ${cell.text}. Show the passage it is quoted from.`}
            className={`group -mx-2 flex w-[calc(100%+16px)] items-start gap-2.5 rounded-lg px-2 py-1.5 text-left text-[14.5px] leading-[1.45] transition-colors hover:bg-white/[0.06] ${focusRing}`}
            style={active ? { background: "rgba(93,240,168,.12)", boxShadow: "inset 0 0 0 1px rgba(93,240,168,.4)" } : undefined}
          >
            {value}
            <span
              aria-hidden
              className="mt-[5px] block size-[9px] shrink-0 rounded-full transition-colors"
              style={{ border: `1.5px solid ${C.mint}`, background: active ? C.mint : "rgba(93,240,168,.14)" }}
            />
          </button>
        ) : (
          <p className="flex py-1.5 text-[14.5px] leading-[1.45]">{value}</p>
        )}
        {cell.note && (
          <p className="mt-0.5 text-[12.5px] leading-snug" style={{ color: C.muted }} data-cell-note>
            {cell.note}
          </p>
        )}
      </div>
    );
  }
  const status = cell.status as Exclude<CellStatus, "found">;
  const copy = CELL_COPY[status] ?? CELL_COPY.unknown;
  return (
    <p className="flex items-center gap-1.5 py-1.5 text-[13px] italic" style={{ color: status === "unsupported" ? C.warning : C.muted2 }} title={copy.meaning}>
      <StatusGlyph status={status} />
      <span data-cell-text>{cell.text}</span>
      <span className="sr-only">. {copy.meaning}</span>
    </p>
  );
}

/** A paper's column heading: which paper (numbered, named in full), where it
 * stands, and -- on hover or focus -- a way to drop it from the view. */
export function PaperHeading({
  paper,
  index,
  onRemove,
  canRemove,
}: {
  paper: ComparisonTablePaper;
  index: number;
  onRemove: () => void;
  canRemove: boolean;
}) {
  return (
    <div className="group/head">
      <div className="flex h-6 items-center justify-between gap-2">
        <span
          className="inline-flex h-5 items-center gap-1 rounded-md px-1.5 font-mono text-[11px] font-semibold tabular-nums"
          style={{ color: C.ink, background: "rgba(150,175,230,.12)" }}
          aria-hidden
        >
          <NodeGlyph kind={paper.kind} size={8} />
          {index}
        </span>
        {canRemove && (
          <button
            type="button"
            onClick={onRemove}
            aria-label={`Remove ${paper.title} from the comparison`}
            title="Remove from this view"
            className={`-mr-1.5 inline-flex size-7 shrink-0 items-center justify-center rounded-full opacity-0 transition-[opacity,background-color] hover:bg-white/10 focus-visible:opacity-100 group-hover/head:opacity-100 ${focusRing}`}
            style={{ color: C.muted }}
          >
            <X className="size-3.5" weight="bold" aria-hidden />
          </button>
        )}
      </div>
      {paper.kind === "seed" && <span className="sr-only">Seed paper: </span>}
      <Link
        href={paper.kind === "seed" ? `/seed/${paper.paper_id}` : `/papers/${paper.paper_id}`}
        className={`mt-1.5 block rounded-sm text-[14px] font-semibold leading-snug text-pretty hover:underline hover:decoration-[rgba(93,240,168,0.5)] hover:underline-offset-4 ${focusRing}`}
        data-testid="paper-title"
      >
        {paper.title}
      </Link>
      <p className="mt-1 text-[12px] leading-snug" style={{ color: C.muted }} data-testid="paper-meta">
        {paper.meta}
      </p>
    </div>
  );
}

/** The passage behind one value, and the ways out to its paper. */
export function CellEvidence({
  cell,
  field,
  paperId,
  kind,
  workspaceId,
  onClose,
}: {
  cell: ComparisonCell;
  field: string;
  paperId: string;
  kind: PaperKind;
  workspaceId: string;
  onClose: () => void;
}) {
  const headingId = useId();
  const paper = usePaper(paperId);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const span = cell.span!;
  return (
    <aside
      aria-labelledby={headingId}
      className="flex max-h-full flex-col overflow-hidden rounded-2xl backdrop-blur-md"
      style={{ background: "rgba(10,15,32,.94)", border: `1px solid ${C.lineStrong}` }}
    >
      <div className="flex items-start gap-3 px-5 pt-4">
        <div className="min-w-0 flex-1">
          <h2 id={headingId} className="text-base font-bold leading-snug">
            {fieldLabel(field)}: {cell.text}
          </h2>
          <p className="mt-1 flex items-start gap-1.5 text-[13px] leading-snug" style={{ color: C.muted }}>
            <span className="mt-[3px]">
              <NodeGlyph kind={kind} size={10} />
            </span>
            {paper?.title ?? ""}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close the passage"
          className={`-mr-2 -mt-1 inline-flex size-11 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-white/10 sm:size-9 ${focusRing}`}
          style={{ color: C.muted }}
        >
          <X className="size-4" weight="bold" aria-hidden />
        </button>
      </div>
      <div className="min-h-0 overflow-y-auto overscroll-contain px-5 pb-5 pt-3 [scrollbar-color:rgba(150,175,230,.28)_transparent]">
        <p className="text-[13px]" style={{ color: C.muted }}>
          Quoted from {location(span) ?? "the paper"}
          {cell.grounding === "abstract" ? ", the only text of this paper in the workspace" : ""}
        </p>
        <blockquote className="mt-2 border-l pl-3 text-[15px] leading-relaxed" style={{ borderColor: "rgba(93,240,168,.5)" }}>
          &ldquo;{span.quote}&rdquo;
        </blockquote>
        {cell.conflicting.length > 0 && (
          <p className="mt-3 text-[13px] leading-relaxed" style={{ color: C.muted }}>
            The same passage also states {cell.conflicting.map((c) => `“${c}”`).join(", ")}; read it before relying on one value.
          </p>
        )}
        <div className="mt-4 flex flex-wrap gap-2">
          <PanelLink href={kind === "seed" ? `/seed/${paperId}` : `/papers/${paperId}`}>
            <ArrowSquareOut className="size-4" aria-hidden />
            Open paper
          </PanelLink>
          <PanelLink href={`/workspace/${workspaceId}/graph?paper=${encodeURIComponent(paperId)}`}>
            <Graph className="size-4" aria-hidden />
            Show in graph
          </PanelLink>
        </div>
      </div>
    </aside>
  );
}

/** Work in progress without a fake percentage: one node per paper, a signal
 * running along them, for as long as the comparison takes. */
export function WorkingTrail({ count }: { count: number }) {
  return (
    <ol className="flex items-center" aria-hidden>
      {Array.from({ length: Math.min(count, 8) }, (_, i) => (
        <li key={i} className="flex items-center">
          {i > 0 && (
            <span className="relative block h-px w-7 overflow-hidden" style={{ background: "rgba(93,240,168,.4)" }}>
              <span className={chatStyles.signal} style={{ animationDelay: `${i * 0.18}s` }} />
            </span>
          )}
          <span className={`block size-2.5 rounded-full ${chatStyles.pulse}`} style={{ border: `1.5px solid ${C.mint}`, background: "#0b1226" }} />
        </li>
      ))}
    </ol>
  );
}

function PanelLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold transition-colors hover:bg-white/10 sm:min-h-9 ${focusRing}`}
      style={quietButton}
    >
      {children}
    </Link>
  );
}

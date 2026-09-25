"use client";

import { useId, type ReactNode } from "react";
import Link from "next/link";
import { ArrowClockwise, ArrowSquareOut, CaretLeft, CaretRight, Graph, X } from "@phosphor-icons/react/dist/ssr";
import type { RagStage } from "@/lib/api/types";
import { STAGES, STAGE_COPY, citationsIn, location, outcomeNotes, sourcesByPaper, type Citation, type Segment } from "@/lib/chat";
import { truncate } from "@/lib/graph/labels";
import { NodeGlyph } from "../graph/GraphPanel";
import { C, focusRing, quietButton } from "../ui";
import styles from "./chat.module.css";

export type PaperKind = "seed" | "member" | "connected";

/** The pipeline's real stages as a short trail of nodes: done ones filled,
 * the current one lit, a pulse running toward it -- the graph's own
 * language for "a signal travelling along a connection". */
export function StageTrail({ stage, seen }: { stage: RagStage | null; seen: RagStage[] }) {
  const current = stage === "rewriting" ? "checking" : stage;
  const reached = STAGES.indexOf(current ?? "searching");
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2" role="status" aria-live="polite">
      <ol className="flex items-center" aria-hidden>
        {STAGES.map((s, i) => {
          const done = i < reached || (seen.includes(s) && i !== reached);
          const active = i === reached;
          return (
            <li key={s} className="flex items-center">
              {i > 0 && (
                <span className="relative block h-px w-6 overflow-hidden sm:w-9" style={{ background: i <= reached ? "rgba(93,240,168,.55)" : C.lineStrong }}>
                  {active && <span className={styles.signal} />}
                </span>
              )}
              <span
                className={`block size-2.5 rounded-full ${active ? styles.pulse : ""}`}
                style={{
                  background: done ? C.mint : active ? "#0b1226" : "transparent",
                  border: `1.5px solid ${done || active ? C.mint : "rgba(207,224,255,.4)"}`,
                  boxShadow: active ? "0 0 0 4px rgba(93,240,168,.12)" : undefined,
                }}
              />
            </li>
          );
        })}
      </ol>
      <span className="text-sm" style={{ color: C.muted }}>
        {stage ? `${STAGE_COPY[stage]}…` : "Starting…"}
      </span>
    </div>
  );
}

/** An inline citation: a small ringed node carrying its number. */
export function CitationMark({
  citation,
  active,
  onOpen,
  onHover,
}: {
  citation: Citation;
  active: boolean;
  onOpen: () => void;
  onHover?: (on: boolean) => void;
}) {
  const first = citation.sources[0];
  const where = first ? [first.paper_title ?? "a workspace paper", location(first)].filter(Boolean).join(", ") : "its source";
  return (
    <button
      type="button"
      onClick={onOpen}
      onPointerEnter={() => onHover?.(true)}
      onPointerLeave={() => onHover?.(false)}
      onFocus={() => onHover?.(true)}
      onBlur={() => onHover?.(false)}
      aria-label={`Source ${citation.marker}: ${where}`}
      aria-pressed={active}
      className={`relative mx-0.5 inline-flex size-[22px] translate-y-[-1px] items-center justify-center rounded-full align-middle text-[11px] font-bold tabular-nums transition-colors before:absolute before:-inset-[11px] before:content-[''] ${focusRing}`}
      style={{
        color: active ? C.mintInk : C.mint,
        background: active ? C.mint : "rgba(93,240,168,.1)",
        border: `1.5px solid ${active ? C.mint : "rgba(93,240,168,.55)"}`,
      }}
    >
      {citation.marker}
    </button>
  );
}

/** An answer's prose with its citations inline; the sentence behind the
 * citation being inspected or pointed at is lit. */
export function AnswerText({
  segments,
  lit,
  caret,
  onOpen,
  onHover,
}: {
  segments: Segment[];
  lit: string | null;
  caret?: boolean;
  onOpen: (c: Citation) => void;
  onHover: (claimId: string | null) => void;
}) {
  return (
    <p className="max-w-[68ch] whitespace-pre-wrap text-[15.5px] leading-[1.75]" style={{ color: C.ink }}>
      {segments.map((seg, i) => {
        if (seg.kind === "cite") {
          return (
            <CitationMark
              key={`c${i}`}
              citation={seg.citation}
              active={lit === seg.citation.claimId}
              onOpen={() => onOpen(seg.citation)}
              onHover={(on) => onHover(on ? seg.citation.claimId : null)}
            />
          );
        }
        const next = segments[i + 1];
        const sentence = next?.kind === "cite" ? next.citation.sentence : "";
        if (sentence && seg.text.endsWith(sentence) && lit === (next as { citation: Citation }).citation.claimId) {
          return (
            <span key={`t${i}`}>
              {seg.text.slice(0, seg.text.length - sentence.length)}
              <mark className="rounded-[3px] px-0.5 text-inherit" style={{ background: "rgba(93,240,168,.16)", boxShadow: "0 1px 0 rgba(93,240,168,.6)" }}>
                {sentence}
              </mark>
            </span>
          );
        }
        return <span key={`t${i}`}>{seg.text}</span>;
      })}
      {caret && <span aria-hidden className={styles.caret} />}
    </p>
  );
}

/** The papers an answer draws on, one chip per paper with its citation numbers. */
export function SourceRow({
  segments,
  kindOf,
  onOpen,
}: {
  segments: Segment[];
  kindOf: (paperId: string) => PaperKind;
  onOpen: (c: Citation) => void;
}) {
  const citations = citationsIn(segments);
  const rows = sourcesByPaper(citations);
  if (rows.length === 0) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-[13px]" style={{ color: C.muted }}>
        Sources
      </span>
      {rows.map((row) => (
        <button
          key={row.paperId}
          type="button"
          onClick={() => onOpen(citations.find((c) => c.marker === row.markers[0])!)}
          className={`inline-flex min-h-11 max-w-full items-center gap-2 rounded-full px-3 text-[13px] transition-colors hover:bg-white/10 sm:min-h-8 ${focusRing}`}
          style={quietButton}
        >
          <NodeGlyph kind={kindOf(row.paperId)} size={11} />
          <span className="truncate">{truncate(row.title ?? "A workspace paper", 44)}</span>
          <span className="shrink-0 tabular-nums" style={{ color: C.muted }}>
            {row.markers.join(", ")}
          </span>
        </button>
      ))}
    </div>
  );
}

export function OutcomeNotes(props: Parameters<typeof outcomeNotes>[0] & { faithfulness?: number | null; onRegenerate?: () => void; busy?: boolean }) {
  const notes = outcomeNotes(props);
  const { faithfulness, onRegenerate, busy } = props;
  if (notes.length === 0 && faithfulness == null && !onRegenerate) return null;
  return (
    <div className="mt-3 space-y-1.5">
      {notes.map((n) => (
        <p key={n} className="max-w-[68ch] text-[13px] leading-relaxed" style={{ color: C.warning }}>
          {n}
        </p>
      ))}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        {faithfulness != null && (
          <span className="text-[12.5px]" style={{ color: C.muted }} title="How much of the answer's wording is found in the passages it cites">
            Faithfulness <span className="font-mono tabular-nums">{faithfulness.toFixed(2)}</span>
          </span>
        )}
        {onRegenerate && (
          <button
            type="button"
            onClick={onRegenerate}
            disabled={busy}
            className={`inline-flex min-h-11 items-center gap-1.5 rounded-sm text-[13px] font-medium hover:text-white disabled:opacity-50 sm:min-h-8 ${focusRing}`}
            style={{ color: C.muted }}
          >
            <ArrowClockwise className="size-4" aria-hidden />
            Regenerate
          </button>
        )}
      </div>
    </div>
  );
}

/** The passages behind one cited sentence, with the ways out to each paper. */
export function EvidencePanel({
  citation,
  total,
  workspaceId,
  kindOf,
  onStep,
  onClose,
}: {
  citation: Citation;
  total: number;
  workspaceId: string;
  kindOf: (paperId: string) => PaperKind;
  onStep: (delta: number) => void;
  onClose: () => void;
}) {
  const headingId = useId();
  return (
    <aside
      aria-labelledby={headingId}
      className="relative flex max-h-full flex-col overflow-hidden rounded-2xl backdrop-blur-md"
      style={{ background: "rgba(10,15,32,.92)", border: `1px solid ${C.lineStrong}` }}
    >
      <div className="flex items-center gap-1 px-4 pt-3">
        <h2 id={headingId} className="mr-auto text-sm font-bold">
          Source <span className="tabular-nums">{citation.marker}</span>
          <span className="font-normal tabular-nums" style={{ color: C.muted }}>
            {" "}
            of {total}
          </span>
        </h2>
        <IconButton label="Previous source" disabled={citation.marker <= 1} onClick={() => onStep(-1)}>
          <CaretLeft className="size-4" weight="bold" aria-hidden />
        </IconButton>
        <IconButton label="Next source" disabled={citation.marker >= total} onClick={() => onStep(1)}>
          <CaretRight className="size-4" weight="bold" aria-hidden />
        </IconButton>
        <IconButton label="Close the source" onClick={onClose}>
          <X className="size-4" weight="bold" aria-hidden />
        </IconButton>
      </div>
      <div className="min-h-0 overflow-y-auto overscroll-contain px-5 pb-5 pt-2 [scrollbar-color:rgba(150,175,230,.28)_transparent]">
        {citation.sentence && (
          <>
            <p className="text-[13px]" style={{ color: C.muted }}>
              The answer says
            </p>
            <p className="mt-1 text-[15px] font-medium leading-relaxed">{citation.sentence}</p>
          </>
        )}
        <p className="mt-4 text-[13px]" style={{ color: C.muted }}>
          {citation.sources.length === 1 ? "It rests on this passage" : `It rests on these ${citation.sources.length} passages`}
        </p>
        <ul className="mt-2 space-y-5">
          {citation.sources.map((s) => {
            const kind = kindOf(s.paper_id);
            return (
              <li key={s.chunk_id}>
                <p className="flex items-start gap-2 text-sm font-semibold leading-snug">
                  <span className="mt-[4px]">
                    <NodeGlyph kind={kind} size={11} />
                  </span>
                  {s.paper_title ?? "A paper in this workspace"}
                </p>
                {location(s) && (
                  <p className="mt-0.5 pl-[19px] text-[12.5px]" style={{ color: C.muted }}>
                    {location(s)}
                  </p>
                )}
                <blockquote className="mt-2 border-l pl-3 text-[14px] leading-relaxed" style={{ borderColor: "rgba(93,240,168,.5)", color: C.ink }}>
                  &ldquo;{s.quote}
                  {s.truncated ? "…" : ""}&rdquo;
                </blockquote>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Link
                    href={kind === "seed" ? `/seed/${s.paper_id}` : `/papers/${s.paper_id}`}
                    className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold transition-colors hover:bg-white/10 sm:min-h-9 ${focusRing}`}
                    style={quietButton}
                  >
                    <ArrowSquareOut className="size-4" aria-hidden />
                    Open paper
                  </Link>
                  <Link
                    href={`/workspace/${workspaceId}/graph?paper=${encodeURIComponent(s.paper_id)}`}
                    className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-semibold transition-colors hover:bg-white/10 sm:min-h-9 ${focusRing}`}
                    style={quietButton}
                  >
                    <Graph className="size-4" aria-hidden />
                    Show in graph
                  </Link>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </aside>
  );
}

function IconButton({ label, disabled, onClick, children }: { label: string; disabled?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex size-11 items-center justify-center rounded-full transition-colors hover:bg-white/10 disabled:opacity-35 disabled:hover:bg-transparent sm:size-9 ${focusRing}`}
      style={{ color: C.muted }}
    >
      {children}
    </button>
  );
}

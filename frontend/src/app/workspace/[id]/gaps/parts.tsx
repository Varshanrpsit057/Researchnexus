"use client";

import { forwardRef, useId, type ReactNode } from "react";
import Link from "next/link";
import { ArrowSquareOut, Graph } from "@phosphor-icons/react/dist/ssr";
import type { Confidence, GapEvidence, GapUserState, ResearchGap } from "@/lib/api/types";
import { location } from "@/lib/chat";
import {
  CONFIDENCE_LABEL,
  CONFIDENCE_MEANING,
  GAP_TYPE_LABEL,
  ROLE_COPY,
  STATE_LABEL,
  confidenceReasons,
  evidenceByPaper,
  passageCount,
  roleOf,
  ruleCopy,
  type PaperEvidence,
} from "@/lib/gaps";
import { truncate } from "@/lib/graph/labels";
import { NodeGlyph } from "../graph/GraphPanel";
import { usePaper, type PaperKind } from "../compare/parts";
import { C, focusRing, quietButton } from "../ui";

const AMBER = C.warning;

/** A band, drawn as three rising bars and always named: never a percentage. */
export function ConfidenceMark({ confidence, compact = false }: { confidence: Confidence; compact?: boolean }) {
  const filled = confidence === "high" ? 3 : confidence === "medium" ? 2 : 1;
  return (
    <span className="inline-flex items-center gap-1.5" title={CONFIDENCE_MEANING[confidence]}>
      <svg width="13" height="11" viewBox="0 0 13 11" aria-hidden className="shrink-0">
        {[0, 1, 2].map((i) => (
          <rect
            key={i}
            x={i * 4.5}
            y={7 - i * 3}
            width="3.2"
            height={4 + i * 3}
            rx="0.8"
            fill={i < filled ? C.mint : "rgba(150,175,230,.22)"}
          />
        ))}
      </svg>
      {compact ? CONFIDENCE_LABEL[confidence].replace(" confidence", "") : CONFIDENCE_LABEL[confidence]}
    </span>
  );
}

/** Accepted / rejected / to review, as a drawn mark and a word. */
export function StateMark({ state }: { state: GapUserState }) {
  const color = state === "accepted" ? C.mint : state === "rejected" ? C.danger : C.muted;
  return (
    <span className="inline-flex items-center gap-1.5" style={{ color }}>
      <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden className="shrink-0">
        {state === "accepted" ? (
          <path d="M2 5.2 4.1 7.3 8 2.8" fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        ) : state === "rejected" ? (
          <path d="M2.5 2.5l5 5M7.5 2.5l-5 5" stroke={color} strokeWidth="1.6" strokeLinecap="round" />
        ) : (
          <circle cx="5" cy="5" r="3.4" fill="none" stroke={color} strokeWidth="1.4" />
        )}
      </svg>
      {STATE_LABEL[state]}
    </span>
  );
}

/** The papers a gap rests on, as linked nodes: amber for a paper with a conflicting claim. */
function PaperCluster({ gap, kindOf }: { gap: ResearchGap; kindOf: (id: string) => PaperKind }) {
  const groups = evidenceByPaper(gap);
  return (
    <span className="flex items-center" aria-hidden>
      {groups.slice(0, 6).map((g, i) => (
        <span key={g.paperId} className="flex items-center">
          {i > 0 && <span className="block h-px w-2.5" style={{ background: "rgba(93,240,168,.45)" }} />}
          {g.conflicting.length > 0 ? <ConflictNode size={10} /> : <NodeGlyph kind={kindOf(g.paperId)} size={10} />}
        </span>
      ))}
    </span>
  );
}

function ConflictNode({ size = 12 }: { size?: number }) {
  const h = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden className="shrink-0">
      <path d={`M${h} 1 L${size - 1} ${h} L${h} ${size - 1} L1 ${h} Z`} fill="#0b1226" stroke={AMBER} strokeWidth="1.5" />
    </svg>
  );
}

export function GapRow({
  gap,
  selected,
  onSelect,
  kindOf,
}: {
  gap: ResearchGap;
  selected: boolean;
  onSelect: () => void;
  kindOf: (id: string) => PaperKind;
}) {
  const papers = new Set(gap.supporting_papers).size;
  const passages = passageCount(gap);
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={`block w-full rounded-xl px-4 py-3.5 text-left transition-colors ${selected ? "" : "hover:bg-white/[0.04]"} ${focusRing}`}
      style={selected ? { background: "rgba(93,240,168,.07)", boxShadow: "inset 0 0 0 1px rgba(93,240,168,.35)" } : undefined}
    >
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]" style={{ color: C.muted }}>
        <span className="font-semibold" style={{ color: C.ink }}>
          {GAP_TYPE_LABEL[gap.gap_type] ?? gap.gap_type}
        </span>
        <ConfidenceMark confidence={gap.confidence} compact />
        {gap.user_state !== "candidate" && <StateMark state={gap.user_state} />}
      </span>
      <span className="mt-1.5 block text-[15px] leading-snug [overflow-wrap:anywhere]" style={{ color: C.ink }}>
        {gap.statement}
      </span>
      <span className="mt-2 flex items-center gap-2.5 text-[12.5px]" style={{ color: C.muted }}>
        <PaperCluster gap={gap} kindOf={kindOf} />
        <span>
          <span className="tabular-nums">{papers}</span> paper{papers === 1 ? "" : "s"} · <span className="tabular-nums">{passages}</span> passage
          {passages === 1 ? "" : "s"}
          {gap.conflicting_evidence.length > 0 && (
            <span style={{ color: AMBER }}>
              {" "}
              · <span className="tabular-nums">{gap.conflicting_evidence.length}</span> conflicting
            </span>
          )}
        </span>
      </span>
    </button>
  );
}

/** The gap itself: its statement, then the trace down to every passage it rests on. */
export const GapDetail = forwardRef<
  HTMLHeadingElement,
  {
    gap: ResearchGap;
    workspaceId: string;
    kindOf: (id: string) => PaperKind;
    generated: string;
    actions: ReactNode;
  }
>(function GapDetail({ gap, workspaceId, kindOf, generated, actions }, headingRef) {
  const headingId = useId();
  const groups = evidenceByPaper(gap);
  const papers = new Set(gap.supporting_papers).size;
  const terms = [...gap.affected_methods, ...gap.affected_datasets];
  return (
    <article aria-labelledby={headingId} className="flex min-h-full flex-col">
      <div className="flex-1 px-5 pb-6 pt-5 sm:px-6">
        <p className="text-[13px] leading-snug" style={{ color: C.muted }}>
          <span className="font-semibold" style={{ color: C.ink }}>
            {GAP_TYPE_LABEL[gap.gap_type] ?? gap.gap_type}
          </span>{" "}
          · {ruleCopy(gap.detection_rule)}
        </p>
        <h2
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="mt-2.5 text-[clamp(20px,2.1vw,24px)] font-bold leading-[1.25] tracking-[-0.01em] outline-none [overflow-wrap:anywhere] [text-wrap:balance]"
        >
          {gap.statement}
        </h2>
        <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px]" style={{ color: C.muted }}>
          <ConfidenceMark confidence={gap.confidence} />
          <StateMark state={gap.user_state} />
          <span>Found {generated}</span>
        </p>

        {/* the trace: statement -> paper -> passage */}
        <section aria-labelledby={`${headingId}-evidence`} className="mt-7">
          <h3 id={`${headingId}-evidence`} className="flex items-baseline gap-2 text-[15px] font-bold">
            The evidence
            <span className="text-[13px] font-normal" style={{ color: C.muted }}>
              <span className="tabular-nums">{papers}</span> paper{papers === 1 ? "" : "s"}, <span className="tabular-nums">{passageCount(gap)}</span> passage
              {passageCount(gap) === 1 ? "" : "s"}, each quoted word for word
            </span>
          </h3>
          <EvidenceTrace groups={groups} workspaceId={workspaceId} kindOf={kindOf} />
        </section>

        <dl className="mt-8 grid gap-5 border-t pt-6 text-[14.5px] leading-relaxed" style={{ borderColor: C.line }}>
          {gap.why_unaddressed && (
            <div>
              <dt className="text-[13px] font-semibold" style={{ color: C.muted }}>
                Why no paper here addresses it
              </dt>
              <dd className="mt-1">{gap.why_unaddressed}</dd>
            </div>
          )}
          {gap.proposed_direction && (
            <div>
              <dt className="text-[13px] font-semibold" style={{ color: C.muted }}>
                A way to test it
              </dt>
              <dd className="mt-1">{gap.proposed_direction}</dd>
            </div>
          )}
          {terms.length > 0 && (
            <div>
              <dt className="text-[13px] font-semibold" style={{ color: C.muted }}>
                What it concerns
              </dt>
              <dd className="mt-1.5 flex flex-wrap gap-1.5">
                {terms.map((t) => (
                  <span key={t} className="rounded-md px-2 py-0.5 text-[13px]" style={{ background: "rgba(255,255,255,.05)", border: `1px solid ${C.line}` }}>
                    {t}
                  </span>
                ))}
              </dd>
            </div>
          )}
          <div>
            <dt className="text-[13px] font-semibold" style={{ color: C.muted }}>
              Why {CONFIDENCE_LABEL[gap.confidence].toLowerCase()}
            </dt>
            <dd className="mt-1.5">
              <ul className="space-y-1">
                {confidenceReasons(gap).map((r) => (
                  <li key={r} className="flex gap-2">
                    <span aria-hidden className="mt-[9px] block size-1 shrink-0 rounded-full" style={{ background: C.muted }} />
                    {r}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-[13px]" style={{ color: C.muted }}>
                {CONFIDENCE_LABEL[gap.confidence]} means: {CONFIDENCE_MEANING[gap.confidence].charAt(0).toLowerCase() + CONFIDENCE_MEANING[gap.confidence].slice(1)}
              </p>
            </dd>
          </div>
        </dl>

        <p className="mt-6 text-[12.5px] leading-relaxed" style={{ color: C.muted }}>
          A rule found this gap from the papers&apos; profiles.{" "}
          {gap.generator_model ? `${gap.generator_model} phrased it from the rule's facts and the passages above` : "It is phrased from the rule's own facts, without a language model"}
          {gap.self_support_passed ? ", and the statement was checked against those passages." : "."}
        </p>
      </div>
      <div className="sticky bottom-0 border-t px-5 py-3.5 sm:px-6" style={{ borderColor: C.line, background: "#090d1c" }}>
        {actions}
      </div>
    </article>
  );
});

/** Paper -> passage, as one rail: each paper a node on it, its passages quoted beneath. */
export function EvidenceTrace({ groups, workspaceId, kindOf }: { groups: PaperEvidence[]; workspaceId: string; kindOf: (id: string) => PaperKind }) {
  return (
    <ol className="relative mt-4 space-y-5">
      <span
        aria-hidden
        className="absolute bottom-3 left-[6px] top-2 w-px"
        style={{ background: "linear-gradient(to bottom, rgba(93,240,168,.6), rgba(93,240,168,.12))" }}
      />
      {groups.map((g) => (
        <PaperTrace
          key={g.paperId}
          paperId={g.paperId}
          kind={kindOf(g.paperId)}
          supporting={g.supporting}
          conflicting={g.conflicting}
          workspaceId={workspaceId}
        />
      ))}
    </ol>
  );
}

function PaperTrace({
  paperId,
  kind,
  supporting,
  conflicting,
  workspaceId,
}: {
  paperId: string;
  kind: PaperKind;
  supporting: GapEvidence[];
  conflicting: GapEvidence[];
  workspaceId: string;
}) {
  const paper = usePaper(paperId);
  const conflict = conflicting.length > 0;
  return (
    <li className="relative pl-7">
      <span className="absolute left-0 top-[3px] rounded-full" style={{ background: "#0a0f22", boxShadow: "0 0 0 3px #0a0f22" }}>
        {conflict ? <ConflictNode size={13} /> : <NodeGlyph kind={kind} size={13} />}
      </span>
      <p className="text-[14px] font-semibold leading-snug [overflow-wrap:anywhere]">
        <Link href={kind === "seed" ? `/seed/${paperId}` : `/papers/${paperId}`} className={`rounded-sm hover:underline hover:underline-offset-4 ${focusRing}`}>
          {paper ? truncate(paper.title, 110) : "Loading…"}
        </Link>
      </p>
      <p className="mt-0.5 text-[12.5px]" style={{ color: C.muted }}>
        {[kind === "seed" ? "Seed paper" : null, paper ? (paper.has_full_text ? "Full text" : "Abstract only") : null, paper?.year != null ? String(paper.year) : null]
          .filter(Boolean)
          .join(" · ")}
      </p>
      <ul className="mt-2.5 space-y-3">
        {[...supporting, ...conflicting].map((e, i) => (
          <Passage key={`${e.span.quote}-${i}`} evidence={e} />
        ))}
      </ul>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-[13px]">
        <TraceLink href={kind === "seed" ? `/seed/${paperId}` : `/papers/${paperId}`}>
          <ArrowSquareOut className="size-3.5" aria-hidden />
          Open paper
        </TraceLink>
        <TraceLink href={`/workspace/${workspaceId}/graph?paper=${encodeURIComponent(paperId)}`}>
          <Graph className="size-3.5" aria-hidden />
          Show in graph
        </TraceLink>
      </div>
    </li>
  );
}

function Passage({ evidence }: { evidence: GapEvidence }) {
  const role = roleOf(evidence);
  const conflict = role === "conflicts_with_gap";
  const where = location(evidence.span);
  return (
    <li>
      <p className="text-[12.5px]" style={{ color: conflict ? AMBER : C.muted }} title={ROLE_COPY[role].meaning}>
        {ROLE_COPY[role].label}
        {where ? ` · ${where}` : ""}
      </p>
      <blockquote
        className="mt-1 border-l pl-3 text-[15px] leading-relaxed [overflow-wrap:anywhere]"
        style={{ borderColor: conflict ? "rgba(232,193,92,.6)" : "rgba(93,240,168,.5)" }}
      >
        &ldquo;{evidence.span.quote}&rdquo;
      </blockquote>
    </li>
  );
}

function TraceLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      className={`inline-flex min-h-11 items-center gap-1.5 rounded-sm font-medium underline-offset-4 hover:text-white hover:underline sm:min-h-0 ${focusRing}`}
      style={{ color: C.muted }}
    >
      {children}
    </Link>
  );
}

export function DecisionButton({
  children,
  onClick,
  primary = false,
  disabled = false,
}: {
  children: ReactNode;
  onClick: () => void;
  primary?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-4 text-sm font-semibold transition-[opacity,transform,background-color] active:scale-[0.97] disabled:opacity-45 sm:min-h-9 ${primary ? "" : "hover:bg-white/10"} ${focusRing}`}
      style={primary ? { color: C.mintInk, background: C.mint } : quietButton}
    >
      {children}
    </button>
  );
}

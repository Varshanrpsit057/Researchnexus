"use client";

import { forwardRef, useId, type ReactNode } from "react";
import Link from "next/link";
import type { DirectionKind, ResearchDirection, ResearchGap } from "@/lib/api/types";
import { CONFIDENCE_LABEL, GAP_TYPE_LABEL, groupEvidence } from "@/lib/gaps";
import { CONFIDENCE_MEANING, KIND_COPY, critiqueAxes, directionReasons, kindOf, type CritiqueAxis } from "@/lib/directions";
import type { PaperKind } from "../compare/parts";
import { ConfidenceMark, EvidenceTrace, StateMark } from "../gaps/parts";
import { C, focusRing } from "../ui";

const AMBER = C.warning;

/** Evidence-backed: a filled node, like a paper the graph already holds.
 * Hypothesis: an open, dashed ring -- something still to test. */
export function KindGlyph({ kind, size = 12 }: { kind: DirectionKind; size?: number }) {
  const h = size / 2;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden className="shrink-0">
      {kind === "evidence_backed_inference" ? (
        <>
          <circle cx={h} cy={h} r={h - 1} fill="none" stroke={C.mint} strokeOpacity={0.5} strokeWidth="1" />
          <circle cx={h} cy={h} r={h - 3.2} fill={C.mint} />
        </>
      ) : (
        <circle cx={h} cy={h} r={h - 1.2} fill="none" stroke={AMBER} strokeWidth="1.5" strokeDasharray="2.2 1.8" />
      )}
    </svg>
  );
}

export function KindMark({ kind, long = false }: { kind: DirectionKind; long?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5" style={{ color: kind === "llm_hypothesis" ? AMBER : C.ink }} title={KIND_COPY[kind].meaning}>
      <KindGlyph kind={kind} />
      {long ? KIND_COPY[kind].long : KIND_COPY[kind].label}
    </span>
  );
}

/** One critique axis: five segments, the ones above its cap drawn as out of reach. */
function CritiqueMeter({ axis }: { axis: CritiqueAxis }) {
  const label = axis.score == null ? `${axis.label}: not scored` : `${axis.label}: ${axis.score} of 5`;
  return (
    <div title={axis.meaning}>
      <div className="flex items-baseline justify-between gap-2 text-[13px]">
        <span style={{ color: C.ink }}>{axis.label}</span>
        <span className="tabular-nums" style={{ color: C.muted }}>
          {axis.score == null ? "–" : `${axis.score}/5`}
        </span>
      </div>
      <div className="mt-1.5 flex gap-1" role="img" aria-label={label}>
        {[1, 2, 3, 4, 5].map((i) => {
          const on = axis.score != null && i <= axis.score;
          const beyond = i > axis.cap;
          return (
            <span
              key={i}
              className="h-1.5 flex-1 rounded-full"
              style={
                on
                  ? { background: C.mint }
                  : beyond
                    ? { background: "transparent", boxShadow: "inset 0 0 0 1px rgba(150,175,230,.22)", backgroundImage: "repeating-linear-gradient(135deg, rgba(150,175,230,.18) 0 2px, transparent 2px 4px)" }
                    : { background: "rgba(150,175,230,.16)" }
              }
            />
          );
        })}
      </div>
    </div>
  );
}

/** The accepted gap a set of directions grows from: the root of their branch. */
export function GapSource({ gapId, gap, workspaceId, count }: { gapId: string; gap: ResearchGap | null; workspaceId: string; count?: number }) {
  const notAccepted = gap != null && gap.user_state !== "accepted";
  return (
    <div className="relative flex gap-3 pl-0.5">
      <span className="mt-[3px] shrink-0 rounded-full" style={{ background: "#0a0f22", boxShadow: "0 0 0 3px #0a0f22" }}>
        <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden>
          <circle cx="6.5" cy="6.5" r="5.5" fill="none" stroke={C.mint} strokeWidth="1.5" />
          <circle cx="6.5" cy="6.5" r="2" fill={C.mint} />
        </svg>
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[12.5px]" style={{ color: C.muted }}>
          {gap ? (
            <>
              From {notAccepted ? "a gap now " + (gap.user_state === "rejected" ? "rejected" : "back under review") : "an accepted gap"} ·{" "}
              {GAP_TYPE_LABEL[gap.gap_type] ?? gap.gap_type}
              {count != null && (
                <>
                  {" "}
                  · <span className="tabular-nums">{count}</span> direction{count === 1 ? "" : "s"}
                </>
              )}
            </>
          ) : (
            "From a gap that is no longer in this workspace"
          )}
        </p>
        {gap && (
          <p className="mt-0.5 text-[14px] font-semibold leading-snug [overflow-wrap:anywhere]" style={{ color: C.ink }}>
            <Link
              href={`/workspace/${workspaceId}/gaps?gap=${encodeURIComponent(gapId)}`}
              className={`rounded-sm hover:underline hover:underline-offset-4 ${focusRing}`}
            >
              {gap.statement}
            </Link>
          </p>
        )}
      </div>
    </div>
  );
}

export function DirectionRow({ direction, selected, onSelect }: { direction: ResearchDirection; selected: boolean; onSelect: () => void }) {
  const kind = kindOf(direction);
  const plan = [direction.suggested_method, direction.possible_dataset ? `on ${direction.possible_dataset}` : null].filter(Boolean).join(" ");
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className={`block w-full rounded-xl px-4 py-3.5 text-left transition-colors ${selected ? "" : "hover:bg-white/[0.04]"} ${focusRing}`}
      style={selected ? { background: "rgba(93,240,168,.07)", boxShadow: "inset 0 0 0 1px rgba(93,240,168,.35)" } : undefined}
    >
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px]" style={{ color: C.muted }}>
        <span className="font-semibold">
          <KindMark kind={kind} />
        </span>
        <ConfidenceMark confidence={direction.confidence} compact />
        {direction.user_state !== "candidate" && <StateMark state={direction.user_state} />}
      </span>
      <span className="mt-1.5 block text-[15px] leading-snug [overflow-wrap:anywhere]" style={{ color: C.ink }}>
        {direction.proposal}
      </span>
      {plan && (
        <span className="mt-1.5 block truncate text-[12.5px]" style={{ color: C.muted }}>
          {plan}
        </span>
      )}
    </button>
  );
}

export const DirectionDetail = forwardRef<
  HTMLHeadingElement,
  {
    direction: ResearchDirection;
    gap: ResearchGap | null;
    workspaceId: string;
    kindOf: (id: string) => PaperKind;
    proposed: ReactNode;
    actions: ReactNode;
  }
>(function DirectionDetail({ direction, gap, workspaceId, kindOf: paperKind, proposed, actions }, headingRef) {
  const headingId = useId();
  const kind = kindOf(direction);
  const groups = groupEvidence(direction.related_papers, direction.supporting_evidence);
  const papers = groups.length;
  const passages = direction.supporting_evidence.length;
  return (
    <article aria-labelledby={headingId} className="flex min-h-full flex-col">
      <div className="flex-1 px-5 pb-6 pt-5 sm:px-6">
        <p className="text-[13px] leading-snug" style={{ color: C.muted }}>
          <span className="font-semibold">
            <KindMark kind={kind} long />
          </span>{" "}
          · {KIND_COPY[kind].meaning}
        </p>
        <h2
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="mt-2.5 text-[clamp(20px,2.1vw,24px)] font-bold leading-[1.25] tracking-[-0.01em] outline-none [overflow-wrap:anywhere] [text-wrap:balance]"
        >
          {direction.proposal}
        </h2>
        <p className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[13px]" style={{ color: C.muted }}>
          <ConfidenceMark confidence={direction.confidence} />
          <StateMark state={direction.user_state} />
          <span>Proposed {proposed}</span>
        </p>

        <p className="mt-5 text-[15px] leading-relaxed">
          <span className="font-semibold" style={{ color: C.muted }}>
            Why:{" "}
          </span>
          {direction.motivation}
        </p>

        {/* the plan, as a researcher would write it down */}
        <section aria-labelledby={`${headingId}-plan`} className="mt-6 overflow-hidden rounded-xl" style={{ border: `1px solid ${C.line}` }}>
          <h3 id={`${headingId}-plan`} className="sr-only">
            The plan
          </h3>
          <dl className="grid grid-cols-[minmax(0,1fr)] sm:grid-cols-3">
            <PlanCell term="Method" value={direction.suggested_method || "Not named"} empty={!direction.suggested_method} />
            <PlanCell term="Data" value={direction.possible_dataset ?? "Not named"} empty={!direction.possible_dataset} bordered />
            <PlanCell term="How to test it" value={direction.evaluation_strategy || "Not specified"} empty={!direction.evaluation_strategy} bordered />
          </dl>
          {direction.risks.length > 0 && (
            <div className="border-t px-4 py-3" style={{ borderColor: C.line, background: "rgba(232,193,92,.04)" }}>
              <p className="text-[12.5px] font-semibold" style={{ color: AMBER }}>
                Risks
              </p>
              <ul className="mt-1 space-y-1 text-[14px] leading-relaxed">
                {direction.risks.map((r) => (
                  <li key={r} className="flex gap-2">
                    <span aria-hidden className="mt-[9px] block size-1 shrink-0 rounded-full" style={{ background: AMBER }} />
                    {r}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        {/* the trace: direction -> its gap -> the papers and passages it inherits */}
        <section aria-labelledby={`${headingId}-source`} className="mt-8">
          <h3 id={`${headingId}-source`} className="flex items-baseline gap-2 text-[15px] font-bold">
            Where it comes from
            <span className="text-[13px] font-normal" style={{ color: C.muted }}>
              <span className="tabular-nums">{papers}</span> paper{papers === 1 ? "" : "s"}, <span className="tabular-nums">{passages}</span> passage
              {passages === 1 ? "" : "s"}, quoted word for word
            </span>
          </h3>
          <div className="mt-4">
            <GapSource gapId={direction.gap_id} gap={gap} workspaceId={workspaceId} />
          </div>
          <div className="ml-[6px] border-l pl-4" style={{ borderColor: "rgba(93,240,168,.25)" }}>
            <EvidenceTrace groups={groups} workspaceId={workspaceId} kindOf={paperKind} />
          </div>
        </section>

        {/* how it was judged */}
        <section aria-labelledby={`${headingId}-critique`} className="mt-8 border-t pt-6" style={{ borderColor: C.line }}>
          <h3 id={`${headingId}-critique`} className="text-[15px] font-bold">
            How a critique rated it
          </h3>
          <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-4">
            {critiqueAxes(direction).map((a) => (
              <CritiqueMeter key={a.key} axis={a} />
            ))}
          </div>
          <p className="mt-3 text-[12.5px] leading-relaxed" style={{ color: C.muted }}>
            Feasibility is never scored above 3: a model can&apos;t judge how practical an idea is, so it stays uncertain.
          </p>
          <p className="mt-5 text-[13px] font-semibold" style={{ color: C.muted }}>
            Why {CONFIDENCE_LABEL[direction.confidence].toLowerCase()}
          </p>
          <ul className="mt-1.5 space-y-1 text-[14.5px] leading-relaxed">
            {directionReasons(direction).map((r) => (
              <li key={r} className="flex gap-2">
                <span aria-hidden className="mt-[9px] block size-1 shrink-0 rounded-full" style={{ background: C.muted }} />
                {r}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[13px]" style={{ color: C.muted }}>
            {CONFIDENCE_LABEL[direction.confidence]} means: {CONFIDENCE_MEANING[direction.confidence].charAt(0).toLowerCase() + CONFIDENCE_MEANING[direction.confidence].slice(1)}
          </p>
        </section>

        <p className="mt-6 text-[12.5px] leading-relaxed" style={{ color: C.muted }}>
          {direction.generator_model
            ? `${direction.generator_model} proposed it from the accepted gap alone; a direction that named anything the gap's evidence doesn't contain would have been dropped.`
            : "It is the gap's own suggested direction, written out by the pipeline without a language model."}
        </p>
      </div>
      <div className="sticky bottom-0 border-t px-5 py-3.5 sm:px-6" style={{ borderColor: C.line, background: "#090d1c" }}>
        {actions}
      </div>
    </article>
  );
});

function PlanCell({ term, value, empty, bordered = false }: { term: string; value: string; empty: boolean; bordered?: boolean }) {
  return (
    <div className={`px-4 py-3 ${bordered ? "border-t sm:border-l sm:border-t-0" : ""}`} style={{ borderColor: C.line }}>
      <dt className="text-[12.5px] font-semibold" style={{ color: C.muted }}>
        {term}
      </dt>
      <dd className="mt-1 text-[14.5px] leading-snug [overflow-wrap:anywhere]" style={{ color: empty ? C.muted : C.ink }}>
        {value}
      </dd>
    </div>
  );
}

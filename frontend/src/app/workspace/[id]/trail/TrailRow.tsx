"use client";

import { useId, useState, type ReactNode } from "react";
import Link from "next/link";
import { motion, useReducedMotion } from "motion/react";
import { ArrowRight, CaretDown, CheckCircle, Circle, XCircle } from "@phosphor-icons/react/dist/ssr";
import type { Confidence, EdgeUserState } from "@/lib/api/types";
import {
  RELATIONSHIP_COPY,
  conclusion,
  confidenceReasons,
  describeEvidence,
  detectionLabel,
  fromWorkspacePapers,
  ruleReasons,
  type TrailEntry,
} from "@/lib/trail";
import { C, InlineError, focusRing, primaryButton, quietButton } from "../ui";

const BAND_LABEL: Record<Confidence, string> = { high: "High confidence", medium: "Medium confidence", low: "Low confidence" };
const BAND_COLOR: Record<Confidence, string> = { high: C.mint, medium: C.ink, low: C.warning };

export interface Seed {
  id: string;
  title: string | null;
  year: number | null;
}

interface TrailRowProps {
  entry: TrailEntry;
  seed: Seed;
  selected: boolean;
  /** Open the evidence chain on arrival (a deep link from the graph). */
  defaultOpen?: boolean;
  onSelect: () => void;
  onDecide: (state: EdgeUserState) => Promise<void>;
}

/** One connection: the target paper, the relationship stated as a
 * conclusion, and -- on expand -- the chain behind it, step by step: the two
 * papers, the verbatim evidence, the rule that fired on measured signals,
 * and the confidence with its reasons. */
export function TrailRow({ entry, seed, selected, defaultOpen = false, onSelect, onDecide }: TrailRowProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chainId = useId();
  const title = entry.target.title ?? entry.target.id;
  const state = entry.edge.user_state;
  const meta = [
    entry.target.authors?.length ? `${entry.target.authors[0]}${entry.target.authors.length > 1 ? " et al." : ""}` : null,
    entry.target.venue,
    entry.target.year != null ? String(entry.target.year) : null,
  ].filter(Boolean);

  async function decide(next: EdgeUserState) {
    setBusy(true);
    setError(null);
    try {
      await onDecide(next);
    } catch {
      setError("That didn't save. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="border-t first:border-t-0" style={{ borderColor: C.line }}>
      <article aria-labelledby={`${chainId}-title`} className="px-4 py-4 sm:px-5">
        <div className="flex gap-3">
          {/* the padded label gives the 16px box a ~44px touch target */}
          <label className="-m-3 flex shrink-0 cursor-pointer items-start p-3 sm:-m-2 sm:p-2">
            <input
              type="checkbox"
              checked={selected}
              onChange={onSelect}
              aria-label={`Select the connection to ${title}`}
              className="mt-1 size-4 accent-[#5df0a8]"
            />
          </label>
          <div className="min-w-0 flex-1">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
              <div className="min-w-0">
                <h3 id={`${chainId}-title`} className="text-[15px] font-semibold leading-snug">
                  <Link
                    href={`/papers/${entry.target.id}`}
                    data-trail-focus={entry.edge.edge_id}
                    className={`rounded-sm hover:underline hover:underline-offset-4 ${focusRing}`}
                    style={{ color: C.ink }}
                  >
                    {title}
                  </Link>
                </h3>
                {meta.length > 0 && (
                  <p className="mt-0.5 text-[13px]" style={{ color: C.muted }}>
                    {meta.join(" · ")}
                  </p>
                )}
                <p className="mt-2 text-sm" style={{ color: C.ink }}>
                  {conclusion(entry.type)}
                </p>
                <p className="mt-1 flex flex-wrap items-center gap-x-2 text-[13px]" style={{ color: C.muted }}>
                  <span style={{ color: BAND_COLOR[entry.edge.confidence] }}>{BAND_LABEL[entry.edge.confidence]}</span>
                  <span aria-hidden>·</span>
                  <span>{detectionLabel(entry.edge.detection_method)}</span>
                  {entry.ranking && (
                    <>
                      <span aria-hidden>·</span>
                      <span className="tabular-nums">
                        ranked #{entry.ranking.final_rank} {fromWorkspacePapers(entry.edge.run_id) ? "of this workspace's papers" : "in discovery"}
                      </span>
                    </>
                  )}
                </p>
              </div>
              <Decision state={state} busy={busy} title={title} onDecide={decide} />
            </div>

            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              aria-controls={chainId}
              className={`mt-3 inline-flex min-h-11 items-center gap-1.5 rounded-full text-sm font-semibold hover:text-white sm:min-h-0 ${focusRing}`}
              style={{ color: C.mint }}
            >
              {open ? "Hide the evidence" : `Show the evidence (${entry.edge.evidence.length})`}
              <CaretDown className={`size-4 transition-transform duration-200 ${open ? "rotate-180" : ""}`} weight="bold" aria-hidden />
            </button>
            {error && (
              <div className="mt-2">
                <InlineError message={error} />
              </div>
            )}
            <div id={chainId}>{open && <Chain entry={entry} seed={seed} />}</div>
          </div>
        </div>
      </article>
    </li>
  );
}

function Decision({
  state,
  busy,
  title,
  onDecide,
}: {
  state: EdgeUserState;
  busy: boolean;
  title: string;
  onDecide: (next: EdgeUserState) => void;
}) {
  if (state === "pending") {
    return (
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => onDecide("accepted")}
          aria-label={`Accept the connection to ${title}`}
          className={`inline-flex min-h-11 items-center rounded-full px-4 text-sm font-semibold disabled:opacity-60 sm:min-h-9 ${focusRing}`}
          style={primaryButton}
        >
          Accept
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => onDecide("rejected")}
          aria-label={`Reject the connection to ${title}`}
          className={`inline-flex min-h-11 items-center rounded-full px-4 text-sm font-semibold transition-colors hover:bg-white/10 disabled:opacity-60 sm:min-h-9 ${focusRing}`}
          style={quietButton}
        >
          Reject
        </button>
      </div>
    );
  }
  const accepted = state === "accepted";
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-2">
      <span className="inline-flex items-center gap-1.5 text-sm font-semibold" style={{ color: accepted ? C.mint : C.muted }}>
        {accepted ? <CheckCircle className="size-4" weight="fill" aria-hidden /> : <XCircle className="size-4" weight="fill" aria-hidden />}
        {accepted ? "Accepted" : "Rejected"}
      </span>
      <button
        type="button"
        disabled={busy}
        onClick={() => onDecide("pending")}
        aria-label={`${accepted ? "Undo accepting" : "Restore"} the connection to ${title}`}
        className={`inline-flex min-h-11 items-center rounded-full px-3.5 text-sm font-medium transition-colors hover:bg-white/10 disabled:opacity-60 sm:min-h-9 ${focusRing}`}
        style={{ color: C.muted }}
      >
        {accepted ? "Undo" : "Restore"}
      </button>
    </div>
  );
}

const STEPS = ["Papers", "Evidence", "Relationship", "Conclusion"] as const;

/** Paper -> evidence -> relationship -> conclusion, as a connected sequence.
 * The one authored motion on the page: the connector draws down as the
 * chain opens (skipped under reduced motion). */
function Chain({ entry, seed }: { entry: TrailEntry; seed: Seed }) {
  const reduce = useReducedMotion();
  const title = entry.target.title ?? entry.target.id;
  const paperTitle = (side: "seed" | "target") => (side === "seed" ? seed.title ?? "the seed paper" : title);
  const state = entry.edge.user_state;

  const body: Record<(typeof STEPS)[number], ReactNode> = {
    Papers: (
      <div className="space-y-1.5 text-sm">
        <p>
          <span style={{ color: C.muted }}>Seed paper · </span>
          <Link href={`/seed/${seed.id}`} className={`rounded-sm font-medium underline decoration-[rgba(93,240,168,0.45)] underline-offset-4 hover:text-white ${focusRing}`}>
            {seed.title ?? "the seed paper"}
          </Link>
        </p>
        <p className="flex items-start gap-1.5">
          <ArrowRight className="mt-[3px] size-3.5 shrink-0" style={{ color: C.mint }} weight="bold" aria-hidden />
          <span>
            <span style={{ color: C.muted }}>Connected paper · </span>
            <Link href={`/papers/${entry.target.id}`} className={`rounded-sm font-medium underline decoration-[rgba(93,240,168,0.45)] underline-offset-4 hover:text-white ${focusRing}`}>
              {title}
            </Link>
          </span>
        </p>
      </div>
    ),
    Evidence: (
      <ul className="space-y-3">
        {entry.edge.evidence.map((ev, i) => {
          const d = describeEvidence(ev);
          return (
            <li key={i}>
              <p className="text-[13px]" style={{ color: C.muted }}>
                <span className="font-semibold" style={{ color: C.ink }}>
                  {d.label}
                </span>
                {d.location && ` · ${d.location}`}
                {!d.titleOnly && <> · {paperTitle(d.side)}</>}
              </p>
              {d.titleOnly ? (
                <p className="mt-1 text-sm" style={{ color: C.muted }}>
                  Only this paper&apos;s title is on record for this link; the relationship rests on the measured signals below.
                </p>
              ) : (
                <blockquote className="mt-1.5 border-l pl-3 text-[15px] leading-relaxed" style={{ borderColor: C.lineStrong, color: C.ink }}>
                  &ldquo;{ev.span.quote}&rdquo;
                </blockquote>
              )}
            </li>
          );
        })}
      </ul>
    ),
    Relationship: (
      <div className="text-sm">
        <p className="font-semibold">{RELATIONSHIP_COPY[entry.type].singular}</p>
        <ul className="mt-1.5 space-y-1" style={{ color: C.ink }}>
          {ruleReasons(entry, seed.year).map((reason) => (
            <li key={reason} className="flex gap-2">
              <span aria-hidden className="mt-2 size-1 shrink-0 rounded-full" style={{ background: C.mint }} />
              {reason}
            </li>
          ))}
        </ul>
        <p className="mt-1.5 text-[13px]" style={{ color: C.muted }}>
          {detectionLabel(entry.edge.detection_method)}.
        </p>
      </div>
    ),
    Conclusion: (
      <div className="text-sm">
        <p className="font-semibold">{conclusion(entry.type)}</p>
        <p className="mt-1.5" style={{ color: BAND_COLOR[entry.edge.confidence] }}>
          {BAND_LABEL[entry.edge.confidence]}
        </p>
        <ul className="mt-1 space-y-0.5 text-[13px]" style={{ color: C.muted }}>
          {confidenceReasons(entry.edge).map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
        <p className="mt-2 text-[13px]" style={{ color: C.muted }}>
          {state === "accepted" ? "You accepted this connection." : state === "rejected" ? "You rejected this connection." : "Waiting for your review."}
        </p>
      </div>
    ),
  };

  return (
    <div className="relative mt-4">
      <motion.span
        aria-hidden
        className="absolute bottom-3 left-[7px] top-3 w-px origin-top"
        style={{ background: `linear-gradient(${C.mint}, ${C.lineStrong})` }}
        initial={{ scaleY: reduce ? 1 : 0 }}
        animate={{ scaleY: 1 }}
        transition={{ duration: reduce ? 0 : 0.45, ease: [0.22, 1, 0.36, 1] }}
      />
      <ol className="relative space-y-5">
        {STEPS.map((step, i) => (
          <motion.li
            key={step}
            className="relative pl-8"
            initial={{ opacity: reduce ? 1 : 0, y: reduce ? 0 : 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: reduce ? 0 : 0.25, delay: reduce ? 0 : 0.06 * i, ease: [0.22, 1, 0.36, 1] }}
          >
            <Circle
              className="absolute left-0 top-0.5 size-[15px]"
              weight={i === STEPS.length - 1 ? "fill" : "bold"}
              style={{ color: C.mint, background: "#0b1020", borderRadius: 999 }}
              aria-hidden
            />
            <h4 className="text-xs font-bold uppercase tracking-[0.08em]" style={{ color: C.muted }}>
              {step}
            </h4>
            <div className="mt-1.5">{body[step]}</div>
          </motion.li>
        ))}
      </ol>
    </div>
  );
}

import type { ReactNode } from "react";
import type { Confidence } from "@/lib/api/types";

type Tone = "neutral" | "accent" | "verified" | "warning" | "danger";

const toneClasses: Record<Tone, string> = {
  neutral: "border-border-strong text-ink-muted",
  accent: "border-accent bg-accent-wash text-accent-strong",
  verified: "border-verified bg-verified-wash text-verified",
  warning: "border-warning bg-warning-wash text-warning",
  danger: "border-danger bg-danger-wash text-danger",
};

/** Specimen-label badge: uppercase mono, letter-spaced, bordered, never a
 * filled pill. Reserved for a genuinely standalone tag (a job status, a
 * single classification in a dense table cell) -- most typed values read
 * better as plain text in a card's own ruled body or tracings line than as
 * a cluster of these, per the brief's "avoid excessive pills/badges." */
export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-xs border px-1.5 py-0.5
        font-mono text-[0.6875rem] font-medium uppercase tracking-wider ${toneClasses[tone]}`}
    >
      {children}
    </span>
  );
}

const confidenceInk: Record<Confidence, string> = {
  high: "text-accent-strong",
  medium: "text-ink-muted",
  low: "text-ink-subtle",
};

/** A confidence reading is a stamp, not a tag: plain glyph plus label, no
 * border or fill, the way a cataloger's pencil mark sits directly on the
 * card rather than in its own little box. */
export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  return (
    <span className={`inline-flex items-center gap-1 font-mono text-xs font-medium ${confidenceInk[confidence]}`}>
      <span aria-hidden>{confidence === "high" ? "●" : confidence === "medium" ? "◐" : "○"}</span>
      {confidence} confidence
    </span>
  );
}

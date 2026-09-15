import type { HTMLAttributes } from "react";
import Link from "next/link";

/** The system's one card anatomy: a header line, a ruled body, and
 * (optionally) a tracings footer -- the same shape a paper, an edge, or a
 * gap all share. Sharp corners throughout: an index card has corners, not
 * curves; separation comes from a hairline border, never a shadow. */
export function Card({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`border border-border bg-surface-raised ${className}`} {...props} />;
}

export function CardHeader({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`flex flex-col gap-1 border-b border-border px-4 py-3 ${className}`} {...props} />;
}

export function CardBody({ className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={`px-4 py-3 ${className}`} {...props} />;
}

/** The tracings footer: every card that carries real cross-references
 * (a paper's own external identifiers, an edge's supporting references, a
 * gap's supporting papers, a direction's source gap and related papers)
 * ends in this ruled line, present even when empty -- a drawer's cards say
 * "no tracings filed" rather than simply omitting the line, so absence of
 * evidence is never silent. Pass `entries`; an empty array renders the
 * honest empty line instead of nothing. An `href` starting with "/" is an
 * in-app route (client-side `Link`); anything else is treated as an
 * external cross-reference and opens in a new tab. */
export function CardTracings({
  entries,
  className = "",
  ...props
}: { entries: { label: string; href?: string }[] } & Omit<HTMLAttributes<HTMLDivElement>, "children">) {
  return (
    <div
      className={`rule-t flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 font-mono text-[0.6875rem] text-ink-subtle ${className}`}
      {...props}
    >
      {entries.length === 0 ? (
        <span>no tracings filed</span>
      ) : (
        entries.map((e, i) => {
          if (!e.href) return <span key={i}>→ {e.label}</span>;
          if (e.href.startsWith("/")) {
            return (
              <Link key={i} href={e.href} className="hover:text-ink-muted hover:underline">
                → {e.label}
              </Link>
            );
          }
          return (
            <a key={i} href={e.href} target="_blank" rel="noreferrer" className="hover:text-ink-muted hover:underline">
              → {e.label}
            </a>
          );
        })
      )}
    </div>
  );
}

"use client";

import { useId, useState, type ReactNode } from "react";
import { CaretDown, Quotes, WarningCircle } from "@phosphor-icons/react/dist/ssr";
import type { ResearchProfile } from "@/lib/api/types";
import { CINEMATIC as C } from "@/lib/cinematic-theme";
import {
  METRIC_STATE_TEXT,
  approachGroups,
  briefOf,
  contextGroups,
  fieldOf,
  groundingNote,
  hasUnmatched,
  itemsOf,
  metricRows,
  type Group,
  type ProfileItem,
} from "@/lib/profile";

/**
 * One paper's research profile, read top to bottom (remediation Phase 6):
 * what it does in brief, the problem, the approach, the results with the
 * values the paper reports, its limits -- then the context. Every item opens
 * the passage it was read from; only an item that couldn't be matched to the
 * paper is marked, so the page isn't a column of "verified".
 */

const focusRing = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5df0a8]";

function Evidence({ item, id }: { item: ProfileItem; id: string }) {
  return (
    <blockquote id={id} className="mt-1.5 rounded-lg px-3 py-2 text-[13px] leading-relaxed" style={{ background: "rgba(0,0,0,.28)", color: C.muted }}>
      <Quotes className="mr-1 inline size-3.5 -translate-y-px" style={{ color: C.muted2 }} aria-hidden />
      <span className="italic">{item.quote}</span>
      {item.page != null && <span className="ml-2 whitespace-nowrap not-italic text-[12px]" style={{ color: C.muted2 }}>p.&nbsp;{item.page}</span>}
    </blockquote>
  );
}

function Unmatched() {
  return (
    <span className="ml-1.5 inline-flex items-center gap-1 whitespace-nowrap text-[12px]" style={{ color: C.warning }}>
      <WarningCircle className="size-3.5" weight="bold" aria-hidden />
      not found in the text
    </span>
  );
}

/** A sentence, with its passage one click away. */
function Statement({ item }: { item: ProfileItem }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <>
      <span>{item.text}</span>
      {item.quote ? (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-controls={id}
          className={`ml-1.5 inline-flex translate-y-[2px] items-center rounded-sm align-baseline transition-colors hover:text-white ${focusRing}`}
          style={{ color: open ? C.mint : C.muted2 }}
        >
          <Quotes className="size-3.5" weight={open ? "fill" : "regular"} aria-hidden />
          <span className="sr-only">{open ? "Hide" : "Show"} the passage for: {item.text}</span>
        </button>
      ) : null}
      {item.status === "unverified" && <Unmatched />}
      {open && item.quote && <Evidence item={item} id={id} />}
    </>
  );
}

function Statements({ items }: { items: ProfileItem[] }) {
  if (items.length === 1) {
    return (
      <p className="text-[14.5px] leading-relaxed" style={{ color: C.ink }}>
        <Statement item={items[0]} />
      </p>
    );
  }
  return (
    <ul className="space-y-2 text-[14.5px] leading-relaxed" style={{ color: C.ink }}>
      {items.map((i) => (
        <li key={i.key} className="flex gap-2.5">
          <span aria-hidden className="mt-[0.7em] size-1 shrink-0 rounded-full" style={{ background: C.muted2 }} />
          <div className="min-w-0">
            <Statement item={i} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Short names in a row; each opens its passage beneath the row. A list
 * with a descriptive entry (older extractions wrote sentences) goes one per line. */
function Names({ items }: { items: ProfileItem[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const id = useId();
  const shown = items.find((i) => i.key === open) ?? null;
  const stacked = items.some((i) => i.text.split(/\s+/).length > 6);
  return (
    <div>
      <ul className={`text-[14.5px] ${stacked ? "space-y-1.5" : "flex flex-wrap gap-x-1 gap-y-1.5"}`} style={{ color: C.ink }}>
        {items.map((i, n) => (
          <li key={i.key} className={stacked ? "leading-snug" : "inline-flex items-baseline"}>
            {i.quote ? (
              <button
                type="button"
                onClick={() => setOpen((o) => (o === i.key ? null : i.key))}
                aria-expanded={open === i.key}
                aria-controls={id}
                className={`rounded-sm text-left underline decoration-dotted underline-offset-4 transition-colors hover:text-white ${focusRing}`}
                style={{ textDecorationColor: open === i.key ? C.mint : "rgba(154,166,196,.45)" }}
              >
                {i.text}
              </button>
            ) : (
              <span>{i.text}</span>
            )}
            {i.status === "unverified" && <Unmatched />}
            {!stacked && n < items.length - 1 && <span aria-hidden style={{ color: C.muted2 }}>&nbsp;·</span>}
          </li>
        ))}
      </ul>
      {shown?.quote && <Evidence item={shown} id={id} />}
    </div>
  );
}

function Rows({ groups }: { groups: Group[] }) {
  return (
    <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-[132px_minmax(0,1fr)]">
      {groups.map((g) => (
        <div key={g.label} className="contents">
          <dt className="pt-0.5 text-[13px] font-medium" style={{ color: C.muted }}>
            {g.label}
          </dt>
          <dd className="min-w-0">
            <Names items={g.items} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t pt-5" style={{ borderColor: C.line }}>
      <h3 className="mb-3 text-[15px] font-semibold tracking-[-0.005em]" style={{ color: C.ink }}>
        {title}
      </h3>
      <div className="space-y-4">{children}</div>
    </section>
  );
}

function Labelled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 text-[13px] font-medium" style={{ color: C.muted }}>
        {label}
      </p>
      {children}
    </div>
  );
}

function MetricTable({ profile }: { profile: ResearchProfile }) {
  const rows = metricRows(profile);
  const [open, setOpen] = useState<string | null>(null);
  if (rows.length === 0) return null;
  return (
    <table className="w-full border-collapse text-[14.5px]" data-testid="profile-metrics">
      <caption className="sr-only">Evaluation metrics and the values the paper reports</caption>
      <thead>
        <tr className="text-left text-[12.5px]" style={{ color: C.muted }}>
          <th scope="col" className="pb-1.5 pr-4 font-medium">
            Metric
          </th>
          <th scope="col" className="pb-1.5 pr-4 font-medium">
            Reported value
          </th>
          <th scope="col" className="w-8 pb-1.5 font-medium">
            <span className="sr-only">Evidence</span>
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <MetricRowView key={r.key} row={r} open={open === r.key} onToggle={() => setOpen((o) => (o === r.key ? null : r.key))} />
        ))}
      </tbody>
    </table>
  );
}

function MetricRowView({ row, open, onToggle }: { row: ReturnType<typeof metricRows>[number]; open: boolean; onToggle: () => void }) {
  const id = useId();
  return (
    <>
      <tr className="border-t align-top" style={{ borderColor: C.line }}>
        <th scope="row" className="py-2 pr-4 text-left font-normal" style={{ color: C.ink }}>
          {row.text}
          {row.status === "unverified" && <Unmatched />}
        </th>
        <td className="py-2 pr-4">
          {row.value ? (
            <span className="font-semibold tabular-nums" style={{ color: C.ink }}>
              {row.value}
            </span>
          ) : (
            <span className="text-[13px]" style={{ color: row.state === "unconfirmed" ? C.warning : C.muted2 }}>
              {METRIC_STATE_TEXT[row.state as "not_reported" | "unconfirmed"]}
            </span>
          )}
        </td>
        <td className="py-2 text-right">
          {row.quote && (
            <button
              type="button"
              onClick={onToggle}
              aria-expanded={open}
              aria-controls={id}
              className={`inline-flex rounded-sm transition-colors hover:text-white ${focusRing}`}
              style={{ color: open ? C.mint : C.muted2 }}
            >
              <Quotes className="size-4" weight={open ? "fill" : "regular"} aria-hidden />
              <span className="sr-only">
                {open ? "Hide" : "Show"} the passage for {row.text}
              </span>
            </button>
          )}
        </td>
      </tr>
      {open && row.quote && (
        <tr>
          <td colSpan={3} className="pb-2">
            <Evidence item={row} id={id} />
          </td>
        </tr>
      )}
    </>
  );
}

export function ResearchProfileView({ profile, notice }: { profile: ResearchProfile; notice?: ReactNode }) {
  const brief = briefOf(profile);
  const problem = fieldOf(profile.research_problem, "problem");
  const questions = itemsOf(profile.research_questions, "question");
  const objectives = itemsOf(profile.objectives, "objective");
  const approach = approachGroups(profile);
  const findings = itemsOf(profile.findings, "finding");
  const limitations = itemsOf(profile.limitations, "limitation");
  const futureWork = itemsOf(profile.future_work, "future");
  const context = contextGroups(profile);
  const hasMetrics = profile.evaluation_metrics.items.some((m) => m.value.trim());

  return (
    <div className="space-y-5" data-testid="research-profile">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-[12.5px]" style={{ color: C.muted }}>
        <span>{groundingNote(profile)}</span>
        <span>{profile.extraction_confidence} confidence</span>
      </div>
      {notice}

      {/* in brief */}
      <div data-testid="profile-brief">
        {brief.abstractFound ? (
          <>
            <p className="max-w-[72ch] text-[15.5px] leading-relaxed" style={{ color: C.ink }}>
              {brief.summary}
            </p>
            {brief.fullAbstract && (
              <details className="group mt-2">
                <summary
                  className={`inline-flex cursor-pointer list-none items-center gap-1 rounded-sm text-[13px] font-medium transition-colors hover:text-white ${focusRing}`}
                  style={{ color: C.mint }}
                >
                  <span className="group-open:hidden">Read the full abstract</span>
                  <span className="hidden group-open:inline">Hide the full abstract</span>
                  <CaretDown className="size-3.5 transition-transform group-open:rotate-180" aria-hidden />
                </summary>
                <p className="mt-2 max-w-[72ch] text-[14px] leading-relaxed" style={{ color: C.muted }}>
                  {brief.fullAbstract}
                </p>
              </details>
            )}
          </>
        ) : (
          <p className="text-[14px]" style={{ color: C.muted }}>
            No abstract was found in this paper&apos;s text, so there is no summary. The profile below was read from its body.
          </p>
        )}
        {profile.keywords.length > 0 && (
          <p className="mt-3 text-[13px]" style={{ color: C.muted2 }}>
            {profile.keywords.join(" · ")}
          </p>
        )}
      </div>

      {(problem || questions.length > 0 || objectives.length > 0) && (
        <Section title="Problem">
          {problem && <Statements items={[problem]} />}
          {objectives.length > 0 && (
            <Labelled label="Aims">
              <Statements items={objectives} />
            </Labelled>
          )}
          {questions.length > 0 && (
            <Labelled label="Questions">
              <Statements items={questions} />
            </Labelled>
          )}
        </Section>
      )}

      {approach.length > 0 && (
        <Section title="Approach">
          <Rows groups={approach} />
        </Section>
      )}

      {(hasMetrics || findings.length > 0) && (
        <Section title="Results">
          <MetricTable profile={profile} />
          {findings.length > 0 && (
            <Labelled label="Findings">
              <Statements items={findings} />
            </Labelled>
          )}
        </Section>
      )}

      {(limitations.length > 0 || futureWork.length > 0) && (
        <Section title="Limits and next steps">
          {limitations.length > 0 && (
            <Labelled label="Limitations">
              <Statements items={limitations} />
            </Labelled>
          )}
          {futureWork.length > 0 && (
            <Labelled label="Future work">
              <Statements items={futureWork} />
            </Labelled>
          )}
        </Section>
      )}

      <details className="group border-t pt-4" style={{ borderColor: C.line }}>
        <summary
          className={`inline-flex cursor-pointer list-none items-center gap-1 rounded-sm text-[13px] font-medium transition-colors hover:text-white ${focusRing}`}
          style={{ color: C.muted }}
        >
          More about this paper
          <CaretDown className="size-3.5 transition-transform group-open:rotate-180" aria-hidden />
        </summary>
        <div className="mt-3 space-y-4">
          {context.length > 0 && <Rows groups={context} />}
          <p className="text-[12.5px] leading-relaxed" style={{ color: C.muted2 }}>
            Each item opens the passage it was read from.
            {hasUnmatched(profile) && " Items marked “not found in the text” couldn’t be matched to the paper, so read them with care."}{" "}
            A metric shows a value only when its passage states one. Extracted by {profile.extraction_model ?? "an unrecorded model"}.
          </p>
        </div>
      </details>
    </div>
  );
}

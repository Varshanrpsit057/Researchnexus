import Link from "next/link";
import { FlaskIcon, Key } from "@phosphor-icons/react/dist/ssr";
import { ConfidenceBadge } from "@/components/ui/Badge";
import { Card, CardBody, CardTracings } from "@/components/ui/Card";
import { LeaderRow } from "@/components/ui/ConfidenceBasis";

const MECHANISM = [
  {
    label: "Signal",
    title: "Every score is real",
    body: "Rankings show the actual per-signal values behind them: semantic similarity, method overlap, citation-graph position, and recency. Never a single invented percentage.",
  },
  {
    label: "Tracing",
    title: "Every relationship is typed",
    body: "Related papers are classified as similar, foundational, competing, method-extending, dataset-related, contradictory, or recent, each with the rule that fired and the evidence span behind it.",
  },
  {
    label: "Source",
    title: "Every claim has a source",
    body: "Chat answers, gaps, and directions are built only from evidence spans pulled from your own papers. If nothing supports a claim, it is not shown.",
  },
];

const STEPS = [
  { n: "01", label: "Upload a seed paper", detail: "A PDF you already have, or one you just wrote." },
  { n: "02", label: "Review its profile", detail: "Problem, methods, datasets, and findings, extracted with provenance." },
  { n: "03", label: "Discover related work", detail: "Several search strategies run in parallel and get fused into one ranking." },
  { n: "04", label: "Walk the typed trail", detail: "Accept or reject each classified relationship to the seed." },
  { n: "05", label: "Build a workspace", detail: "The papers you keep become one persistent, tenant-isolated collection." },
  { n: "06", label: "Chat, compare, find gaps", detail: "Every answer grounded in your own papers, or flagged unsupported." },
];

export default function LandingPage() {
  return (
    <div>
      <header className="border-b border-border-strong">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center justify-between px-4 sm:px-6">
          <span className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-ink">
            <FlaskIcon className="size-4.5 text-accent" weight="duotone" aria-hidden />
            ResearchNexus
          </span>
          <Link
            href="/login"
            className="rounded-sm border border-border-strong px-3 py-1.5 text-sm font-medium text-ink transition-colors hover:border-ink-subtle focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
          >
            Sign in
          </Link>
        </div>
      </header>

      <main id="main" tabIndex={-1}>
        <section className="mx-auto grid max-w-[1400px] items-center gap-16 px-4 py-16 sm:px-6 sm:py-24 lg:grid-cols-[0.95fr_1.05fr] lg:py-32">
          <div className="max-w-lg">
            <h1 className="text-4xl font-semibold leading-[1.08] tracking-tightest text-ink sm:text-5xl">
              From one seed paper to a defensible research gap
            </h1>
            <p className="mt-6 max-w-md text-base leading-relaxed text-ink-muted">
              ResearchNexus takes a single paper through profile extraction, multi-strategy discovery, transparent
              ranking, and typed relationship analysis, then into evidence-grounded chat, comparison, and
              gap-finding. Every score, relationship, and claim traces back to real text you can check.
            </p>
            <div className="mt-9 flex flex-wrap items-center gap-6">
              <Link
                href="/login"
                className="inline-flex h-11 items-center justify-center rounded-sm bg-accent px-6 text-sm font-medium text-accent-foreground transition-colors hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
              >
                Sign in
              </Link>
              <a href="#mechanism" className="text-sm font-medium text-ink-muted underline decoration-border-strong underline-offset-4 hover:text-ink hover:decoration-ink-subtle">
                See how it works
              </a>
            </div>
          </div>

          {/* The hero's one memorable moment: a fanned hand of index cards,
              not a floating dashboard mockup -- the front card is real,
              accessible content; the two behind it are decorative stock. */}
          <div className="relative mx-auto h-[280px] w-full max-w-md lg:mx-0 lg:justify-self-end">
            <Card
              aria-hidden
              className="absolute inset-x-6 top-6 h-48 rotate-[-4deg] bg-surface-sunken opacity-70"
            />
            <Card
              aria-hidden
              className="absolute inset-x-3 top-3 h-48 rotate-[3deg] bg-surface-raised opacity-90"
            />
            <Card className="absolute inset-x-0 top-0">
              <CardBody className="space-y-2">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-sm font-medium text-ink">Query Rewriting in Retrieval-Augmented LLMs</p>
                    <p className="mt-0.5 text-xs text-ink-muted">Ma, Gong, He, Zhao, Duan · 2023</p>
                  </div>
                  <ConfidenceBadge confidence="high" />
                </div>
                <ul className="list-inside list-disc space-y-0.5 text-xs text-ink-muted">
                  <li>linked to the seed in the citation graph (1.00)</li>
                  <li>recent relative to the seed (0.47)</li>
                </ul>
                <div className="grid grid-cols-3 gap-x-3 border-t border-border pt-2 font-mono text-[0.6875rem] text-ink-subtle">
                  <LeaderRow label="citation" value="1.00" />
                  <LeaderRow label="recency" value="0.47" />
                  <LeaderRow label="dataset" value="0.00" />
                </div>
              </CardBody>
              <CardTracings entries={[{ label: "citation" }, { label: "cites seed" }]} />
            </Card>
          </div>
        </section>

        {/* Committed color moment: the one saturated field on the page,
            carrying the product's core mechanism as three ruled entries,
            not three same-size icon cards. */}
        <section id="mechanism" className="bg-[#1a1c19] text-[#f5f6f3]">
          <div className="mx-auto max-w-[1400px] px-4 py-20 sm:px-6">
            <h2 className="max-w-2xl text-2xl font-semibold tracking-tightest sm:text-3xl">
              Free-text literature review has no auditable trail. This does.
            </h2>
            <dl className="mt-12 divide-y divide-white/15 border-t border-white/15">
              {MECHANISM.map((m) => (
                <div key={m.title} className="grid grid-cols-[4.5rem_1fr] gap-3 py-6 sm:grid-cols-[7rem_1fr] sm:gap-8">
                  <dt className="font-mono text-[0.6875rem] uppercase tracking-wider text-[#6fc7bd]">{m.label}</dt>
                  <dd>
                    <p className="text-base font-semibold">{m.title}</p>
                    <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-white/70">{m.body}</p>
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </section>

        {/* The session's steps threaded on one rod, like cards punched
            through a catalog drawer's rail, rather than a numbered grid. */}
        <section className="border-b border-border-strong">
          <div className="mx-auto max-w-[1400px] px-4 py-20 sm:px-6">
            <h2 className="text-2xl font-semibold tracking-tightest text-ink sm:text-3xl">How a session runs</h2>
            <ol className="relative mt-12 max-w-2xl border-l border-border-strong pl-8">
              {STEPS.map((step) => (
                <li key={step.n} className="relative pb-10 last:pb-0">
                  <span
                    aria-hidden
                    className="absolute -left-[calc(2rem+3.5px)] top-1 size-[7px] rounded-full border-2 border-accent bg-surface"
                  />
                  <span className="font-mono text-xs text-ink-subtle">{step.n}</span>
                  <p className="mt-0.5 text-base font-medium text-ink">{step.label}</p>
                  <p className="mt-1 text-sm text-ink-muted">{step.detail}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section className="border-b border-border-strong bg-surface-raised">
          <div className="mx-auto max-w-[1400px] px-4 py-16 sm:px-6">
            <div className="flex flex-col gap-6 sm:flex-row sm:items-start">
              <Key className="size-6 shrink-0 text-accent" weight="duotone" aria-hidden />
              <div className="max-w-2xl">
                <h2 className="text-xl font-semibold tracking-tightest text-ink">Bring your own model</h2>
                <p className="mt-3 text-sm leading-relaxed text-ink-muted">
                  ResearchNexus does not host or resell LLM access. Connect an OpenAI, Groq, DeepSeek, OpenRouter,
                  Together, or Gemini key and it is used only for your own requests, never stored in plaintext
                  and never re-sent to your browser after saving. Deterministic steps, like citation formatting,
                  never need one at all.
                </p>
              </div>
            </div>
          </div>
        </section>

        <section>
          <div className="mx-auto flex max-w-[1400px] flex-col items-start gap-6 px-4 py-20 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <div>
              <h2 className="text-xl font-semibold tracking-tightest text-ink">Start from a paper you already have</h2>
              <p className="mt-2 text-sm text-ink-muted">Any email signs in on this development build.</p>
            </div>
            <Link
              href="/login"
              className="inline-flex h-11 shrink-0 items-center justify-center rounded-sm bg-accent px-6 text-sm font-medium text-accent-foreground transition-colors hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--focus-ring)]"
            >
              Sign in
            </Link>
          </div>
        </section>
      </main>
    </div>
  );
}

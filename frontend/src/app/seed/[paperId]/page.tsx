"use client";

import { useState, type ReactNode } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import {
  ArrowSquareOut,
  Compass,
  FileText,
  Quotes,
  Sparkle,
  Table as TableIcon,
  WarningCircle,
} from "@phosphor-icons/react/dist/ssr";
import { papers } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { CINEMATIC } from "@/lib/cinematic-theme";
import { Reveal } from "@/components/effects/Reveal";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import type { ProfileField as ProfileFieldT, ProfileList as ProfileListT, ProvenanceStatus, SourceSpan } from "@/lib/api/types";

const C = CINEMATIC;

function GlassCard({ title, icon, children }: { title?: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-2xl" style={{ background: C.glass, border: `1px solid ${C.line}` }}>
      {title && (
        <div className="flex items-center gap-2 border-b px-5 py-3.5" style={{ borderColor: C.line }}>
          {icon}
          <h2 className="text-sm font-semibold">{title}</h2>
        </div>
      )}
      <div className="p-5">{children}</div>
    </div>
  );
}

function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded-2xl ${className}`} style={{ background: C.glass, border: `1px solid ${C.line}` }} />;
}

function CenteredState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <Reveal>
      <div className="mx-auto max-w-md rounded-2xl px-6 py-14 text-center" style={{ background: C.glass, border: `1px dashed ${C.lineStrong}` }}>
        <p className="text-base font-semibold">{title}</p>
        {description && (
          <p className="mt-2 text-sm" style={{ color: C.muted }}>
            {description}
          </p>
        )}
        {action}
      </div>
    </Reveal>
  );
}

export default function SeedPaperPage() {
  const { paperId } = useParams<{ paperId: string }>();
  const { ready } = useRequireAuth();

  const {
    data: paper,
    error: paperError,
    isLoading: paperLoading,
    mutate: refetchPaper,
  } = useSWR(ready ? ["paper", paperId] : null, () => papers.get(paperId));

  const {
    data: profile,
    isLoading: profileLoading,
    mutate: mutateProfile,
  } = useSWR(paper?.has_full_text ? ["profile", paperId] : null, async () => {
    try {
      return await papers.getProfile(paperId);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return null;
      throw err;
    }
  });

  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [analyzeWarnings, setAnalyzeWarnings] = useState<string[]>([]);

  async function handleAnalyze() {
    setAnalyzing(true);
    setAnalyzeError(null);
    setAnalyzeWarnings([]);
    try {
      const res = await papers.analyze(paperId);
      await mutateProfile(res.profile, { revalidate: false });
      setAnalyzeWarnings(res.warnings);
    } catch (err) {
      if (err instanceof ApiError && err.code === "llm_key_required") {
        setAnalyzeError("No working LLM provider key is saved yet. Add one in Settings, then analyze again.");
      } else {
        setAnalyzeError(err instanceof ApiError ? err.message : "Analysis failed. Try again.");
      }
    } finally {
      setAnalyzing(false);
    }
  }

  if (!ready) return null;

  if (paperLoading) {
    return (
      <PageShell>
        <div className="space-y-4">
          <SkeletonBlock className="h-24 w-full" />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.5fr_1fr]">
            <SkeletonBlock className="h-80 w-full" />
            <SkeletonBlock className="h-64 w-full" />
          </div>
        </div>
      </PageShell>
    );
  }

  if (paperError) {
    const notFound = paperError instanceof ApiError && paperError.status === 404;
    return (
      <PageShell>
        <CenteredState
          title={notFound ? "Paper not found" : "Could not load this paper"}
          description={
            notFound
              ? `No paper with id ${paperId}.`
              : paperError instanceof ApiError
                ? paperError.message
                : undefined
          }
          action={
            <div className="mt-5 flex justify-center gap-3">
              {!notFound && (
                <button
                  type="button"
                  onClick={() => refetchPaper()}
                  className="rounded-full px-5 py-2.5 text-sm font-semibold"
                  style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
                >
                  Try again
                </button>
              )}
              <Link
                href="/papers"
                className="rounded-full px-5 py-2.5 text-sm font-semibold"
                style={{ background: "rgba(255,255,255,.05)", border: `1px solid ${C.lineStrong}` }}
              >
                Back to papers
              </Link>
            </div>
          }
        />
      </PageShell>
    );
  }

  if (!paper) return null;

  const externalRefs = [
    paper.doi ? { label: `doi:${paper.doi}`, href: `https://doi.org/${paper.doi}` } : null,
    paper.arxiv_id ? { label: `arXiv:${paper.arxiv_id}`, href: `https://arxiv.org/abs/${paper.arxiv_id}` } : null,
  ].filter((e): e is { label: string; href: string } => e !== null);

  return (
    <PageShell>
      <Reveal>
        <div className="border-b pb-6" style={{ borderColor: C.lineStrong }}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h1 className="max-w-3xl text-[clamp(22px,3vw,32px)] font-extrabold leading-[1.15] tracking-[-0.02em]">
              {paper.title}
            </h1>
            {paper.parse_confidence && (
              <span className="inline-flex shrink-0 items-center gap-1.5 font-mono text-xs" style={{ color: C.mint }}>
                <span aria-hidden>{paper.parse_confidence === "high" ? "●" : paper.parse_confidence === "medium" ? "◐" : "○"}</span>
                {paper.parse_confidence} confidence
              </span>
            )}
          </div>
          <p className="mt-2 text-sm" style={{ color: C.muted }}>
            {paper.authors.length > 0 ? paper.authors.join(", ") : "Authors unknown"}
            {paper.venue && ` · ${paper.venue}`}
            {paper.year != null && ` · ${paper.year}`}
          </p>
          <p className="mt-1 font-mono text-xs" style={{ color: C.muted2 }}>
            {paper.id}
          </p>
          {paper.warnings.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {paper.warnings.map((w) => (
                <li key={w} className="flex items-center gap-1.5 text-xs" style={{ color: C.warning }}>
                  <WarningCircle className="size-3.5 shrink-0" weight="bold" aria-hidden />
                  {w}
                </li>
              ))}
            </ul>
          )}
        </div>
      </Reveal>

      <div className="mt-8 grid grid-cols-1 gap-6 lg:grid-cols-[1.5fr_1fr] lg:items-start">
        <div className="space-y-6">
          {externalRefs.length > 0 && (
            <Reveal delay={0.05}>
              <div className="flex flex-wrap gap-2">
                {externalRefs.map((r) => (
                  <a
                    key={r.label}
                    href={r.href}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 font-mono text-xs transition-colors hover:text-white"
                    style={{ background: C.glass, border: `1px solid ${C.line}`, color: C.muted }}
                  >
                    {r.label}
                    <ArrowSquareOut className="size-3" aria-hidden />
                  </a>
                ))}
              </div>
            </Reveal>
          )}

          <Reveal delay={0.1}>
            <GlassCard title="Research profile" icon={<Sparkle className="size-4" style={{ color: C.mint }} aria-hidden />}>
              {!paper.has_full_text ? (
                <p className="text-sm" style={{ color: C.muted }}>
                  Still extracting text from this paper — analysis will be available once parsing finishes.
                </p>
              ) : profileLoading ? (
                <div className="space-y-2">
                  <div className="h-4 w-full animate-pulse rounded" style={{ background: C.line }} />
                  <div className="h-4 w-2/3 animate-pulse rounded" style={{ background: C.line }} />
                </div>
              ) : profile ? (
                <div className="space-y-5">
                  {analyzeWarnings.length > 0 && (
                    <ul className="space-y-0.5">
                      {analyzeWarnings.map((w) => (
                        <li key={w} className="text-xs" style={{ color: C.warning }}>
                          {w}
                        </li>
                      ))}
                    </ul>
                  )}
                  {profile.abstract && (
                    <p className="text-sm leading-relaxed" style={{ color: C.muted }}>
                      {profile.abstract}
                    </p>
                  )}
                  {profile.keywords.length > 0 && (
                    <p className="text-xs" style={{ color: C.muted2 }}>
                      {profile.keywords.join(" · ")}
                    </p>
                  )}
                  <div className="grid gap-5 sm:grid-cols-2">
                    <FieldRow label="Domain" field={profile.domain} />
                    <FieldRow label="Research problem" field={profile.research_problem} />
                  </div>
                  <ListFieldRows label="Methods" list={profile.methods} />
                  <ListFieldRows label="Datasets" list={profile.datasets} />
                  <ListFieldRows label="Findings" list={profile.findings} />
                  <ListFieldRows label="Limitations" list={profile.limitations} />
                  <p className="border-t pt-3 text-xs" style={{ borderColor: C.line, color: C.muted2 }}>
                    Extracted with {profile.extraction_model ?? "an unspecified model"} · {profile.extraction_confidence} confidence
                  </p>
                </div>
              ) : (
                <div className="flex flex-col items-start gap-3">
                  <p className="text-sm" style={{ color: C.muted }}>
                    Extract the research problem, methods, datasets, and findings from this paper&apos;s full text.
                  </p>
                  <button
                    type="button"
                    onClick={handleAnalyze}
                    disabled={analyzing}
                    className="inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold disabled:opacity-60"
                    style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
                  >
                    <Sparkle className="size-4" aria-hidden />
                    {analyzing ? "Running analysis…" : "Run analysis"}
                  </button>
                  {analyzeError && <InlineError message={analyzeError} />}
                </div>
              )}
            </GlassCard>
          </Reveal>

          <Reveal delay={0.15}>
            <GlassCard title="Document status" icon={<FileText className="size-4" style={{ color: C.mint }} aria-hidden />}>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-sm sm:grid-cols-4">
                <StatusStat label="Full text" value={paper.has_full_text ? "extracted" : "pending"} />
                <StatusStat label="Pages" value={paper.page_count != null ? String(paper.page_count) : "—"} />
                <StatusStat label="Sections" value={String(paper.sections.length)} />
                <StatusStat label="Tables" value={String(paper.tables.length)} />
              </dl>
            </GlassCard>
          </Reveal>

          {(paper.sections.length > 0 || paper.tables.length > 0) && (
            <Reveal delay={0.2}>
              <GlassCard title="Document structure" icon={<TableIcon className="size-4" style={{ color: C.mint }} aria-hidden />}>
                <div className="grid gap-6 sm:grid-cols-2">
                  {paper.sections.length > 0 && (
                    <div>
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wider" style={{ color: C.muted2 }}>
                        Sections
                      </p>
                      <ul className="space-y-1.5 text-sm" style={{ color: C.muted }}>
                        {[...paper.sections]
                          .sort((a, b) => a.order - b.order)
                          .map((s) => (
                            <li key={`${s.order}-${s.title}`} className="flex items-center justify-between gap-3">
                              <span className="min-w-0 truncate">{s.title}</span>
                              <span className="shrink-0 font-mono text-xs" style={{ color: C.muted2 }}>
                                p.{s.page_span[0]}–{s.page_span[1]}
                              </span>
                            </li>
                          ))}
                      </ul>
                    </div>
                  )}
                  {paper.tables.length > 0 && (
                    <div>
                      <p className="mb-2 text-xs font-semibold uppercase tracking-wider" style={{ color: C.muted2 }}>
                        Tables
                      </p>
                      <ul className="space-y-1.5 text-sm" style={{ color: C.muted }}>
                        {paper.tables.map((t, i) => (
                          <li key={i} className="flex items-center justify-between gap-3">
                            <span className="min-w-0 truncate">{t.caption ?? "Untitled table"}</span>
                            <span className="shrink-0 font-mono text-xs" style={{ color: C.muted2 }}>
                              p.{t.page}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </GlassCard>
            </Reveal>
          )}
        </div>

        <div className="lg:sticky lg:top-6">
          <Reveal delay={0.1}>
            <GlassCard title="Discover related papers" icon={<Compass className="size-4" style={{ color: C.mint }} aria-hidden />}>
              <div className="flex flex-col items-start gap-3">
                <p className="text-sm" style={{ color: C.muted }}>
                  Search arXiv, OpenAlex, Semantic Scholar, and Crossref for related work, then rank it against this
                  paper&apos;s profile.
                </p>
                {profile ? (
                  <Link
                    href={`/discover/${paperId}`}
                    className="inline-flex w-full items-center justify-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold"
                    style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
                  >
                    <Compass className="size-4" aria-hidden />
                    Start discovery
                  </Link>
                ) : (
                  <>
                    <span
                      aria-disabled
                      className="inline-flex w-full items-center justify-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold opacity-60"
                      style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
                    >
                      <Compass className="size-4" aria-hidden />
                      Start discovery
                    </span>
                    <p className="text-xs" style={{ color: C.muted2 }}>
                      Run analysis first.
                    </p>
                  </>
                )}
              </div>
            </GlassCard>
          </Reveal>
        </div>
      </div>
    </PageShell>
  );
}

const provenanceLabel: Record<ProvenanceStatus, string> = {
  verified: "verified",
  unverified: "unverified",
  user_edited: "edited",
};

function EvidenceDisclosure({ span }: { span: SourceSpan }) {
  if (!span.quote) return null;
  return (
    <details className="mt-1">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs" style={{ color: C.muted2 }}>
        <Quotes className="size-3" aria-hidden />
        Evidence
      </summary>
      <blockquote className="mt-1 rounded-lg px-2.5 py-1.5 text-xs italic" style={{ background: "rgba(0,0,0,.3)", color: C.muted }}>
        &ldquo;{span.quote}&rdquo;
        {span.page != null && (
          <span className="ml-1.5 not-italic" style={{ color: C.muted2 }}>
            p.{span.page}
          </span>
        )}
      </blockquote>
    </details>
  );
}

function FieldRow({ label, field }: { label: string; field: ProfileFieldT }) {
  return (
    <div>
      <p className="text-xs font-medium" style={{ color: C.muted2 }}>
        {label}
      </p>
      {!field.value ? (
        <p className="mt-1 text-sm" style={{ color: C.muted2 }}>
          Not extracted
        </p>
      ) : (
        <div className="mt-1">
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm">{field.value}</p>
            <span className="shrink-0 text-xs" style={{ color: C.muted2 }}>
              {provenanceLabel[field.status]}
            </span>
          </div>
          {field.source_span && <EvidenceDisclosure span={field.source_span} />}
        </div>
      )}
    </div>
  );
}

function ListFieldRows({ label, list }: { label: string; list: ProfileListT }) {
  if (list.items.length === 0) return null;
  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wider" style={{ color: C.muted2 }}>
        {label}
      </p>
      <ul className="space-y-2.5">
        {list.items.map((item, i) => (
          <li key={i}>
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm" style={{ color: C.muted }}>
                {item.value}
              </p>
              <span className="shrink-0 text-xs" style={{ color: C.muted2 }}>
                {provenanceLabel[item.status]}
              </span>
            </div>
            {item.source_span && <EvidenceDisclosure span={item.source_span} />}
          </li>
        ))}
      </ul>
    </div>
  );
}

function StatusStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs" style={{ color: C.muted2 }}>
        {label}
      </dt>
      <dd className="mt-0.5 font-mono text-sm capitalize">{value}</dd>
    </div>
  );
}

function InlineError({ message }: { message: string }) {
  return (
    <p role="alert" className="flex items-center gap-1.5 text-sm" style={{ color: C.danger }}>
      <WarningCircle className="size-4 shrink-0" weight="bold" aria-hidden />
      {message}
    </p>
  );
}

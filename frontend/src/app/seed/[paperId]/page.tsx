"use client";

import { useRef, useState, type ReactNode } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import useSWR from "swr";
import { ArrowSquareOut, Compass, FileText, Sparkle, Table as TableIcon, WarningCircle } from "@phosphor-icons/react/dist/ssr";
import { papers, workspaces as workspacesApi } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import { useProfile } from "@/lib/api/hooks";
import { useRequireAuth } from "@/lib/auth/use-require-auth";
import { CINEMATIC } from "@/lib/cinematic-theme";
import { Reveal } from "@/components/effects/Reveal";
import { CinematicPageShell as PageShell } from "@/components/layout/CinematicPageShell";
import { ProfilePanel } from "@/components/profile/ProfilePanel";
import { COVERAGE_LABEL } from "@/lib/coverage";
import { RankingCriteriaControls } from "@/components/discovery/RankingCriteriaControls";
import { CinematicDialog, type CinematicDialogHandle } from "@/components/ui/CinematicDialog";
import { InlineError, focusRing, quietButton } from "@/components/cinematic/ui";
import { DEFAULT_CRITERIA, criteriaError, criteriaName, sameCriteria, useSavedCriteria, writeCriteria } from "@/lib/ranking";
import type { RankingCriteria } from "@/lib/api/types";

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

  // a paper found by discovery has a profile (read from its abstract) without full text
  const { data: profile, isLoading: profileLoading, mutate: mutateProfile } = useProfile(paper ? paperId : null);

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
  // the reader's workspaces that already hold it, so a second one isn't started by mistake
  const holding = paper.workspaces ?? [];

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
            {paper.publisher && paper.publisher !== paper.venue && ` · ${paper.publisher}`}
            {paper.year != null && ` · ${paper.year}`}
          </p>
          <p className="mt-1 font-mono text-xs" style={{ color: C.muted2 }}>
            {paper.id}
          </p>
          {holding.length > 0 && (
            <p className="mt-3 flex flex-wrap items-center gap-1.5 text-[13px]" data-testid="paper-workspaces">
              <span style={{ color: C.muted }}>In your workspace{holding.length === 1 ? "" : "s"}</span>
              {holding.map((w) => (
                <Link
                  key={w.workspace_id}
                  href={`/workspace/${w.workspace_id}`}
                  className={`rounded-full px-2.5 py-0.5 transition-colors hover:text-white ${focusRing}`}
                  style={{ border: `1px solid ${C.lineStrong}`, color: C.ink }}
                >
                  {w.title}
                </Link>
              ))}
            </p>
          )}
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
              <ProfilePanel paper={paper} profile={profile} loading={profileLoading} mutate={mutateProfile} />
            </GlassCard>
          </Reveal>

          <Reveal delay={0.15}>
            <GlassCard title="Document status" icon={<FileText className="size-4" style={{ color: C.mint }} aria-hidden />}>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2.5 text-sm sm:grid-cols-4">
                <StatusStat
                  label="Text"
                  value={paper.coverage ? COVERAGE_LABEL[paper.coverage.state] : paper.has_full_text ? "Full text" : "Pending"}
                />
                <StatusStat label="Pages" value={paper.page_count != null ? String(paper.page_count) : "—"} />
                <StatusStat label="Sections" value={String(paper.sections.length)} />
                <StatusStat label="Tables" value={String(paper.tables.length)} />
              </dl>
            </GlassCard>
          </Reveal>

          {(paper.sections.length > 0 || paper.tables.length > 0) && (
            <Reveal delay={0.2}>
              <GlassCard title="Document structure" icon={<TableIcon className="size-4" style={{ color: C.mint }} aria-hidden />}>
                <div className="grid grid-cols-[minmax(0,1fr)] gap-6 sm:grid-cols-2">
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
                  Search OpenAlex, Crossref, Semantic Scholar, arXiv, DBLP, CORE and Europe PMC for related work, then rank it against this
                  paper&apos;s profile.
                </p>
                {profile ? (
                  <>
                    <DiscoveryStart paperId={paperId} />
                    <StartWorkspace paperId={paperId} paperTitle={paper.title} />
                  </>
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

/** Start discovery, ranked by the criteria saved in this browser -- which
 * can be set here first (remediation Phase 9). Criteria nobody could rank
 * by (all off) are never saved, and discovery can't start with them. */
function DiscoveryStart({ paperId }: { paperId: string }) {
  const saved = useSavedCriteria();
  const [draft, setDraft] = useState<RankingCriteria | null>(null);
  const criteria = draft ?? saved;
  const invalid = criteriaError(criteria) !== null;

  function change(next: RankingCriteria) {
    setDraft(next);
    if (criteriaError(next) === null) writeCriteria(next);
  }

  return (
    <div className="flex w-full flex-col gap-3">
      {invalid ? (
        <span
          aria-disabled
          className="inline-flex w-full items-center justify-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold opacity-60"
          style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
        >
          <Compass className="size-4" aria-hidden />
          Start discovery
        </span>
      ) : (
        <Link
          href={`/discover/${paperId}`}
          className="inline-flex w-full items-center justify-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold"
          style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
        >
          <Compass className="size-4" aria-hidden />
          Start discovery
        </Link>
      )}
      <details className="group w-full rounded-xl px-3 py-2" style={{ border: `1px solid ${C.line}` }}>
        <summary className="cursor-pointer text-sm" style={{ color: C.muted }}>
          Ranking criteria: {criteriaName(criteria)}
        </summary>
        <div className="mt-3">
          <p className="mb-3 text-[12.5px]" style={{ color: C.muted2 }}>
            How much each criterion counts when the papers found are ranked. Kept in this browser for every run.
          </p>
          <RankingCriteriaControls value={criteria} onChange={change} idPrefix="seed-criteria" />
          {!sameCriteria(criteria, DEFAULT_CRITERIA) && (
            <button
              type="button"
              onClick={() => change(DEFAULT_CRITERIA)}
              className="mt-3 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors hover:bg-white/10"
              style={{ border: `1px solid ${C.lineStrong}`, color: C.ink }}
            >
              Back to the default weights
            </button>
          )}
        </div>
      </details>
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

/** A workspace with just this paper as its seed -- no discovery first: a
 * reader with their own papers adds them there (the old paper page had this;
 * it is how a workspace of one's own papers starts). */
function StartWorkspace({ paperId, paperTitle }: { paperId: string; paperTitle: string }) {
  const router = useRouter();
  const dialog = useRef<CinematicDialogHandle>(null);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const ws = await workspacesApi.create({ title: title.trim() || `${paperTitle} workspace`, seed_paper_id: paperId });
      dialog.current?.close();
      router.push(`/workspace/${ws.workspace_id}`);
    } catch (err) {
      setError(err instanceof ApiError ? `${err.message}.` : "The workspace couldn't be created: the server couldn't be reached.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => dialog.current?.show()}
        className={`rounded-sm text-left text-[13px] underline decoration-[rgba(150,175,230,.35)] underline-offset-4 transition-colors hover:text-white ${focusRing}`}
        style={{ color: C.muted }}
      >
        Skip discovery, start a workspace with just this paper
      </button>
      <CinematicDialog ref={dialog} title="Create a workspace" onClose={() => setError(null)}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
          className="space-y-4"
        >
          <label className="block text-left">
            <span className="text-[13px] font-semibold" style={{ color: C.muted }}>
              Title
            </span>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder={`${paperTitle} workspace`}
              maxLength={200}
              className={`mt-1 h-10 w-full rounded-xl px-3 text-[14px] ${focusRing}`}
              style={{ background: "rgba(255,255,255,.04)", border: `1px solid ${C.lineStrong}`, color: C.ink }}
            />
          </label>
          <p className="text-[13px] leading-relaxed" style={{ color: C.muted }}>
            Only this paper is added, as the seed. Add your own papers there, or discover related ones later, and connect them on its research
            trail.
          </p>
          {error && <InlineError message={error} />}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => dialog.current?.close()}
              className={`rounded-full px-4 py-2 text-sm font-semibold hover:bg-white/10 ${focusRing}`}
              style={{ ...quietButton, color: C.ink }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={busy}
              className={`rounded-full px-4 py-2 text-sm font-semibold disabled:opacity-60 ${focusRing}`}
              style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
            >
              {busy ? "Creating…" : "Create workspace"}
            </button>
          </div>
        </form>
      </CinematicDialog>
    </>
  );
}

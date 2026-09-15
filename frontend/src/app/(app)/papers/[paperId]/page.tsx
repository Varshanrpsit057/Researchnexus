"use client";

import { Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import useSWR from "swr";
import {
  ArrowSquareOut,
  CaretUp,
  Compass,
  Quotes,
  Sparkle,
} from "@phosphor-icons/react/dist/ssr";
import { papers, workspaces } from "@/lib/api/endpoints";
import { useJobPolling } from "@/lib/api/hooks";
import { ApiError } from "@/lib/api/client";
import type {
  CitationRelationship,
  ProfileField as ProfileFieldT,
  ProfileList as ProfileListT,
  ProvenanceStatus,
  RelatedResult,
  ResearchProfile,
  SourceSpan,
} from "@/lib/api/types";
import { Button } from "@/components/ui/Button";
import { Badge, ConfidenceBadge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader, CardTracings } from "@/components/ui/Card";
import { LeaderRow } from "@/components/ui/ConfidenceBasis";
import { EmptyState, ErrorState, InlineError, Skeleton } from "@/components/ui/States";
import { Dialog, type DialogHandle } from "@/components/ui/Dialog";
import { TextInput } from "@/components/ui/Field";

export default function PaperDetailPage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <PaperDetail />
    </Suspense>
  );
}

function PageSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-16 w-2/3" />
      <div className="lg:grid lg:grid-cols-[1.5fr_1fr] lg:gap-8">
        <Skeleton className="h-96 w-full" />
        <Skeleton className="mt-6 h-64 w-full lg:mt-0" />
      </div>
    </div>
  );
}

function PaperDetail() {
  const { paperId } = useParams<{ paperId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const runId = searchParams.get("run");

  const {
    data: paper,
    error: paperError,
    isLoading: paperLoading,
    mutate: refetchPaper,
  } = useSWR(["paper", paperId], () => papers.get(paperId));

  // A paper that already has an extracted profile shows it on arrival --
  // `analyze` always re-runs (and re-bills) LLM extraction, so it must
  // never be the only way to see a profile that already exists. A 404
  // here just means "not analyzed yet", not a real error, so the fetcher
  // absorbs it into a plain `null` rather than surfacing an error state.
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

  // The job id lives in the URL (like the final run_id) so a refresh
  // mid-discovery resumes polling instead of silently losing an
  // in-progress run -- found live: without this, a refresh 20s into a
  // ~30s discovery job stranded the user with no way back to that result
  // short of starting over.
  const [discoverJobId, setDiscoverJobId] = useState<string | null>(() => (runId ? null : searchParams.get("job")));
  const [discoverError, setDiscoverError] = useState<string | null>(null);
  const discoverPolling = useJobPolling(discoverJobId);
  const [mobileSheetOpen, setMobileSheetOpen] = useState(false);

  async function handleDiscover() {
    setDiscoverError(null);
    try {
      const res = await papers.discoverRelated(paperId);
      setDiscoverJobId(res.job.job_id);
      const next = new URLSearchParams(searchParams);
      next.set("job", res.job.job_id);
      router.replace(`/papers/${paperId}?${next.toString()}`);
    } catch (err) {
      if (err instanceof ApiError && err.code === "conflict") {
        setDiscoverError("This paper needs a research profile first — run analysis above.");
      } else {
        setDiscoverError(err instanceof ApiError ? err.message : "Could not start discovery.");
      }
    }
  }

  useEffect(() => {
    if (!discoverPolling.isDone || !discoverPolling.job) return;
    const { status, result_ref } = discoverPolling.job;
    if ((status === "succeeded" || status === "partial") && result_ref) {
      // Once `run` is in the URL the `!runId` branch below (the only place
      // `discoverJobId` is read) stops rendering, so there is nothing left
      // to reset -- SWR's own polling interval already goes to 0 once the
      // job is terminal.
      const next = new URLSearchParams(searchParams);
      next.delete("job");
      next.set("run", result_ref);
      router.replace(`/papers/${paperId}?${next.toString()}`);
    }
  }, [discoverPolling.isDone, discoverPolling.job, paperId, router, searchParams]);

  const {
    data: related,
    error: relatedError,
    isLoading: relatedLoading,
  } = useSWR(runId ? ["related", paperId, runId] : null, () => papers.related(paperId, runId as string));

  const [selected, setSelected] = useState<Set<string>>(new Set());
  function toggleSelected(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const dialogRef = useRef<DialogHandle>(null);
  const [workspaceTitle, setWorkspaceTitle] = useState("");
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  async function handleCreateWorkspace(): Promise<void> {
    // A discovery run is not required: a researcher who wants to start
    // curating, chatting, or comparing before discovery has run (or after
    // it comes back empty, or fails -- all real, not-rare situations, not
    // edge cases) must still be able to reach a workspace with just the
    // seed paper. `import_run_id`/`from_run_id` are only meaningful when a
    // run actually exists.
    setCreatingWorkspace(true);
    setCreateError(null);
    try {
      const ws = await workspaces.create({
        title: workspaceTitle.trim() || `${paper?.title ?? "Untitled"} workspace`,
        seed_paper_id: paperId,
        import_run_id: runId ?? undefined,
      });
      if (selected.size > 0 && runId) {
        await workspaces.addPapers(ws.workspace_id, { paper_ids: Array.from(selected), from_run_id: runId });
      }
      dialogRef.current?.close();
      router.push(`/workspaces/${ws.workspace_id}`);
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : "Could not create workspace.");
    } finally {
      setCreatingWorkspace(false);
    }
  }

  if (paperLoading) return <PageSkeleton />;
  if (paperError) {
    return paperError instanceof ApiError && paperError.status === 404 ? (
      <EmptyState title="Paper not found" description={`No paper with id ${paperId}.`} />
    ) : (
      <ErrorState description={paperError instanceof ApiError ? paperError.message : undefined} onRetry={() => refetchPaper()} />
    );
  }
  if (!paper) return null;

  const externalRefs = [
    paper.doi ? { label: `doi:${paper.doi}`, href: `https://doi.org/${paper.doi}` } : null,
    paper.arxiv_id ? { label: `arXiv:${paper.arxiv_id}`, href: `https://arxiv.org/abs/${paper.arxiv_id}` } : null,
  ].filter((e): e is { label: string; href: string } => e !== null);

  return (
    <div className="space-y-6 pb-16 max-lg:pb-20">
      {/* The drawer's outer label: no card chrome, this line IS the page's
          identity, not content inside a container. */}
      <header className="space-y-2 border-b border-border-strong pb-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 className="text-2xl font-semibold tracking-tightest text-ink">{paper.title}</h1>
          {paper.parse_confidence && <ConfidenceBadge confidence={paper.parse_confidence} />}
        </div>
        <p className="text-sm text-ink-muted">
          {paper.authors.length > 0 ? paper.authors.join(", ") : "Authors unknown"}
          {paper.venue && ` · ${paper.venue}`}
          {paper.year != null && ` · ${paper.year}`}
        </p>
        <p className="font-mono text-xs text-ink-subtle">{paper.id}</p>
        {paper.warnings.length > 0 && (
          <ul className="space-y-0.5">
            {paper.warnings.map((w) => (
              <li key={w} className="text-xs text-warning">
                {w}
              </li>
            ))}
          </ul>
        )}
      </header>

      <div className="lg:grid lg:grid-cols-[1.5fr_1fr] lg:items-start lg:gap-8">
        {/* Left: the paper's own card -- its tracings footer holds the
            external identifiers it is also filed under, the way a catalog
            card's cross-reference numbers point to other indexes. */}
        <Card>
          <CardHeader>
            <h2 className="text-sm font-semibold text-ink">Research profile</h2>
          </CardHeader>
          <CardBody>
            {!paper.has_full_text ? (
              <p className="text-sm text-ink-muted">Still extracting text from this paper — analysis will be available once parsing finishes.</p>
            ) : profileLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-2/3" />
              </div>
            ) : profile ? (
              <div className="space-y-4">
                {analyzeWarnings.length > 0 && (
                  <ul className="space-y-0.5">
                    {analyzeWarnings.map((w) => (
                      <li key={w} className="text-xs text-warning">
                        {w}
                      </li>
                    ))}
                  </ul>
                )}
                <ProfileDetail profile={profile} />
              </div>
            ) : (
              <div className="flex flex-col items-start gap-3">
                <p className="text-sm text-ink-muted">
                  Extract the research problem, methods, datasets, and findings from this paper&apos;s full text.
                </p>
                <Button onClick={handleAnalyze} loading={analyzing}>
                  <Sparkle className="size-4" aria-hidden />
                  Run analysis
                </Button>
                {analyzeError && <InlineError message={analyzeError} />}
              </div>
            )}
          </CardBody>
          <CardTracings
            entries={externalRefs.map((r) => ({
              label: r.label,
              href: r.href,
            }))}
          />
        </Card>

        {/* Right: the action rail. Desktop: a sticky column. Mobile: a
            bottom sheet, collapsed to a peek bar by default so it never
            covers the profile the researcher came to read. */}
        <div
          className={`mt-6 space-y-4 lg:sticky lg:top-6 lg:mt-0
            max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:z-20 max-lg:mt-0 max-lg:border-t max-lg:border-border-strong max-lg:bg-surface-raised max-lg:shadow-[0_-6px_20px_rgb(var(--shadow-color)/0.16)]
            ${mobileSheetOpen ? "max-lg:max-h-[75vh] max-lg:overflow-y-auto" : "max-lg:max-h-12 max-lg:overflow-hidden"}`}
        >
          <button
            type="button"
            onClick={() => setMobileSheetOpen((o) => !o)}
            aria-expanded={mobileSheetOpen}
            className="flex w-full items-center justify-between px-4 py-3 text-sm font-semibold text-ink lg:hidden"
          >
            Discover related papers
            <CaretUp className={`size-4 shrink-0 transition-transform duration-150 ${mobileSheetOpen ? "" : "rotate-180"}`} aria-hidden />
          </button>
          <Card className="max-lg:border-none">
            <CardHeader className="max-lg:hidden">
              <h2 className="text-sm font-semibold text-ink">Discover related papers</h2>
            </CardHeader>
            <CardBody className="space-y-4 max-lg:px-4 max-lg:pt-0 max-lg:pb-4">
              {!runId && (
                <div className="flex flex-col items-start gap-3">
                  <p className="text-sm text-ink-muted">
                    Search arXiv, OpenAlex, Semantic Scholar, and Crossref for related work, then rank it against this paper&apos;s profile.
                  </p>
                  <Button className="w-full" onClick={handleDiscover} disabled={!profile} loading={discoverJobId != null && !discoverPolling.isDone}>
                    <Compass className="size-4" aria-hidden />
                    Discover related papers
                  </Button>
                  {!profile && <p className="text-xs text-ink-subtle">Run analysis first.</p>}
                  {discoverError && <InlineError message={discoverError} />}
                  {discoverJobId && !discoverPolling.isDone && (
                    <p className="text-sm text-ink-muted" role="status" aria-live="polite">
                      {discoverStageLabel(discoverPolling.job?.progress.stage)}
                    </p>
                  )}
                  {discoverPolling.job?.status === "failed" && (
                    <div className="space-y-1">
                      <InlineError message="Discovery failed. Try again, or try a different seed paper." />
                      {discoverPolling.job.error && (
                        <details>
                          <summary className="cursor-pointer list-none text-xs text-ink-subtle hover:text-ink-muted">Technical details</summary>
                          <p className="rule-t mt-1 bg-surface-sunken px-2.5 py-1.5 font-mono text-[0.6875rem] text-ink-subtle">
                            {discoverPolling.job.error}
                          </p>
                        </details>
                      )}
                    </div>
                  )}
                  {profile && (
                    <button
                      type="button"
                      onClick={() => dialogRef.current?.show()}
                      className="text-xs text-ink-subtle underline decoration-border-strong underline-offset-2 hover:text-ink-muted hover:decoration-ink-subtle"
                    >
                      Skip discovery, start a workspace with just this paper
                    </button>
                  )}
                </div>
              )}

              {runId && relatedLoading && (
                <div className="space-y-2">
                  <Skeleton className="h-20 w-full" />
                  <Skeleton className="h-20 w-full" />
                </div>
              )}
              {runId && relatedError && (
                <ErrorState
                  title="Could not load related papers"
                  description={relatedError instanceof ApiError ? relatedError.message : undefined}
                />
              )}
              {runId && related && (
                <div className="space-y-4">
                  <div className="rule-t space-y-1.5 pt-3 text-xs text-ink-subtle">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span>
                        {related.run.counts.after_filter} candidates from {related.run.strategies_succeeded.join(", ") || "no"} strategies
                      </span>
                      {related.run.strategies_failed.length > 0 && (
                        <Badge tone="warning">{related.run.strategies_failed.join(", ")} failed</Badge>
                      )}
                    </div>
                    <details>
                      <summary className="cursor-pointer list-none hover:text-ink-muted">How this search ran</summary>
                      <div className="mt-1.5 space-y-0.5 bg-surface-sunken px-2.5 py-1.5 font-mono text-[0.6875rem]">
                        <LeaderRow label="found" value={String(related.run.counts.raw)} />
                        <LeaderRow label="after dedupe" value={String(related.run.counts.after_dedupe)} />
                        <LeaderRow label="after filter" value={String(related.run.counts.after_filter)} />
                        <LeaderRow
                          label="extra citation hop"
                          value={related.run.extra_citation_hop_used ? "used" : "not used"}
                        />
                      </div>
                    </details>
                  </div>

                  {related.results.length === 0 ? (
                    <EmptyState title="No related papers found" description="Try again later, or broaden the seed paper's profile." />
                  ) : (
                    <>
                      <Button size="sm" variant="secondary" className="w-full" onClick={handleDiscover} loading={discoverJobId != null && !discoverPolling.isDone}>
                        Run again
                      </Button>
                      <ul className="space-y-3">
                        {related.results.map((r) => (
                          <RelatedResultCard
                            key={r.paper.id}
                            result={r}
                            selected={selected.has(r.paper.id)}
                            onToggle={() => toggleSelected(r.paper.id)}
                          />
                        ))}
                      </ul>
                      <div className="rule-t flex items-center justify-between pt-3">
                        <p className="text-xs text-ink-subtle">{selected.size} selected</p>
                        <Button size="sm" onClick={() => dialogRef.current?.show()}>
                          Create workspace{selected.size > 0 ? ` with ${selected.size} paper${selected.size === 1 ? "" : "s"}` : ""}
                        </Button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      </div>

      <Dialog ref={dialogRef} title="Create a workspace" onClose={() => setCreateError(null)}>
        <div className="space-y-4">
          <TextInput
            label="Title"
            placeholder={`${paper.title} workspace`}
            value={workspaceTitle}
            onChange={(e) => setWorkspaceTitle(e.target.value)}
          />
          <p className="text-xs text-ink-muted">
            {selected.size > 0
              ? `${paper.title} plus ${selected.size} selected paper${selected.size === 1 ? "" : "s"} will be added, and their relationship to the seed will be filed as accepted on the trail.`
              : `Only ${paper.title} will be added as the seed. You can add more papers from the trail later.`}
          </p>
          {createError && <InlineError message={createError} />}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" size="sm" onClick={() => dialogRef.current?.close()}>
              Cancel
            </Button>
            <Button size="sm" onClick={handleCreateWorkspace} loading={creatingWorkspace}>
              Create workspace
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}

function discoverStageLabel(stage: string | undefined): string {
  switch (stage) {
    case "discovery":
      return "Searching external sources…";
    case "ranking":
      return "Ranking candidates against the seed profile…";
    case "trail":
      return "Classifying relationships…";
    case "done":
      return "Done.";
    default:
      return "Starting…";
  }
}

// --- research profile ------------------------------------------------

const provenanceLabel: Record<ProvenanceStatus, string> = {
  verified: "verified",
  unverified: "unverified",
  user_edited: "edited",
};

function EvidenceDisclosure({ span }: { span: SourceSpan }) {
  if (!span.quote) return null;
  return (
    <details className="mt-1">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-xs text-ink-subtle hover:text-ink-muted">
        <Quotes className="size-3" aria-hidden />
        Evidence
      </summary>
      <blockquote className="rule-t mt-1 bg-surface-sunken px-2.5 py-1.5 text-xs italic text-ink-muted">
        &ldquo;{span.quote}&rdquo;
        {span.page != null && <span className="ml-1.5 not-italic text-ink-subtle">p.{span.page}</span>}
      </blockquote>
    </details>
  );
}

function FieldValue({ field }: { field: ProfileFieldT }) {
  if (!field.value) return <p className="text-sm text-ink-subtle">Not extracted</p>;
  return (
    <div>
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-ink">{field.value}</p>
        <span className="shrink-0 text-xs text-ink-subtle">{provenanceLabel[field.status]}</span>
      </div>
      {field.source_span && <EvidenceDisclosure span={field.source_span} />}
    </div>
  );
}

function ListFieldValue({ list }: { list: ProfileListT }) {
  if (list.items.length === 0) return <p className="text-sm text-ink-subtle">None extracted</p>;
  return (
    <ul className="space-y-2">
      {list.items.map((item, i) => (
        <li key={i}>
          <FieldValue field={item} />
        </li>
      ))}
    </ul>
  );
}

function ProfileGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-3">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-subtle">{title}</h3>
      {children}
    </div>
  );
}

function LabeledField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-medium text-ink-muted">{label}</p>
      {children}
    </div>
  );
}

function ProfileDetail({ profile }: { profile: ResearchProfile }) {
  return (
    <div className="space-y-6">
      {profile.abstract && <p className="text-sm leading-relaxed text-ink-muted">{profile.abstract}</p>}
      {profile.keywords.length > 0 && (
        <p className="text-xs text-ink-subtle">{profile.keywords.join(" · ")}</p>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <ProfileGroup title="Problem & domain">
          <LabeledField label="Domain">
            <FieldValue field={profile.domain} />
          </LabeledField>
          {profile.subdomains.items.length > 0 && (
            <LabeledField label="Subdomains">
              <ListFieldValue list={profile.subdomains} />
            </LabeledField>
          )}
          <LabeledField label="Research problem">
            <FieldValue field={profile.research_problem} />
          </LabeledField>
          <LabeledField label="Research questions">
            <ListFieldValue list={profile.research_questions} />
          </LabeledField>
          <LabeledField label="Objectives">
            <ListFieldValue list={profile.objectives} />
          </LabeledField>
        </ProfileGroup>

        <ProfileGroup title="Method & data">
          <LabeledField label="Methods">
            <ListFieldValue list={profile.methods} />
          </LabeledField>
          {profile.algorithms.items.length > 0 && (
            <LabeledField label="Algorithms">
              <ListFieldValue list={profile.algorithms} />
            </LabeledField>
          )}
          <LabeledField label="Models">
            <ListFieldValue list={profile.models} />
          </LabeledField>
          <LabeledField label="Datasets">
            <ListFieldValue list={profile.datasets} />
          </LabeledField>
          <LabeledField label="Evaluation metrics">
            <ListFieldValue list={profile.evaluation_metrics} />
          </LabeledField>
        </ProfileGroup>

        <ProfileGroup title="Findings & limitations">
          <LabeledField label="Findings">
            <ListFieldValue list={profile.findings} />
          </LabeledField>
          <LabeledField label="Limitations">
            <ListFieldValue list={profile.limitations} />
          </LabeledField>
          <LabeledField label="Future work">
            <ListFieldValue list={profile.future_work} />
          </LabeledField>
        </ProfileGroup>

        <ProfileGroup title="Entities">
          <LabeledField label="Important entities">
            <ListFieldValue list={profile.important_entities} />
          </LabeledField>
          <LabeledField label="Cited methods">
            <ListFieldValue list={profile.cited_methods} />
          </LabeledField>
        </ProfileGroup>
      </div>

      <p className="rule-t pt-3 text-xs text-ink-subtle">
        Extracted with {profile.extraction_model ?? "an unspecified model"} · {profile.extraction_confidence} confidence
      </p>
    </div>
  );
}

// --- related results ----------------------------------------------------

const citationRelationshipLabel: Record<CitationRelationship, string> = {
  cited_by_seed: "cited by seed",
  cites_seed: "cites seed",
  co_cited: "co-cited",
  none: "",
};

const signalLabels: Record<string, string> = {
  semantic_doc: "semantic",
  semantic_chunk: "chunk sim",
  problem_sim: "problem",
  method_sim: "method",
  dataset_overlap: "dataset",
  citation: "citation",
  recency: "recency",
};

function RelatedResultCard({
  result,
  selected,
  onToggle,
}: {
  result: RelatedResult;
  selected: boolean;
  onToggle: () => void;
}) {
  const signalEntries = result.signals
    ? Object.entries(result.signals).filter((entry): entry is [string, number] => entry[1] != null)
    : [];
  const methods = [
    ...result.discovery_methods.map((m) => m.replace(/_/g, " ")),
    ...(result.citation_relationship !== "none" ? [citationRelationshipLabel[result.citation_relationship]] : []),
  ];

  return (
    <li>
      <Card>
        <CardBody className="flex gap-3">
          <input
            type="checkbox"
            checked={selected}
            onChange={onToggle}
            aria-label={`Select ${result.paper.title}`}
            className="mt-1 size-4 shrink-0 accent-[var(--color-accent)]"
          />
          <div className="min-w-0 flex-1 space-y-1.5">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <p className="min-w-0 text-sm font-medium text-ink">{result.paper.title}</p>
              <span className="flex shrink-0 items-center gap-1.5">
                {result.final_rank != null && <span className="font-mono text-xs text-ink-subtle">#{result.final_rank}</span>}
                {result.band ? <ConfidenceBadge confidence={result.band} /> : <span className="text-xs text-ink-subtle">rank pending</span>}
              </span>
            </div>
            <p className="text-xs text-ink-muted">
              {result.paper.authors.length > 0 ? result.paper.authors.join(", ") : "Authors unknown"}
              {result.paper.venue && ` · ${result.paper.venue}`}
              {result.paper.year != null && ` · ${result.paper.year}`}
            </p>

            {/* `explanation.prose` is the system's own best available
                account of the rank -- an LLM-polished sentence when a key
                is on hand, the same deterministic reasons joined into one
                sentence otherwise (see explain.py). It is never a fragment
                of a list the reader has to piece together themselves. */}
            {result.explanation?.prose && <p className="text-xs text-ink-muted">{result.explanation.prose}</p>}

            {/* Per-signal scores lead, visible by default -- the evidence
                behind the rank, not a click away. The itemized reasons
                behind that one-sentence summary stay behind the disclosure
                below. */}
            {signalEntries.length > 0 && (
              <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 border-y border-border py-1.5 font-mono text-[0.6875rem] text-ink-subtle">
                {signalEntries.map(([name, value]) => (
                  <LeaderRow key={name} label={signalLabels[name] ?? name} value={value.toFixed(2)} />
                ))}
              </div>
            )}

            {result.explanation && result.explanation.bullet_reasons.length > 0 && (
              <details>
                <summary className="cursor-pointer list-none text-xs text-ink-subtle hover:text-ink-muted">Why this rank</summary>
                <ul className="rule-t mt-1.5 list-inside list-disc space-y-0.5 bg-surface-sunken px-2.5 py-1.5 text-xs text-ink-muted">
                  {result.explanation.bullet_reasons.map((reason, i) => (
                    <li key={i}>{reason}</li>
                  ))}
                </ul>
              </details>
            )}

            {(result.paper.doi || result.paper.url) && (
              <a
                href={result.paper.doi ? `https://doi.org/${result.paper.doi}` : result.paper.url!}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-xs text-accent-strong hover:underline"
              >
                View source <ArrowSquareOut className="size-3" aria-hidden />
              </a>
            )}
          </div>
        </CardBody>
        {methods.length > 0 && <CardTracings entries={methods.map((m) => ({ label: m }))} />}
      </Card>
    </li>
  );
}

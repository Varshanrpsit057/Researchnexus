"use client";

import { useState } from "react";
import Link from "next/link";
import type { KeyedMutator } from "swr";
import { Sparkle, WarningCircle } from "@phosphor-icons/react/dist/ssr";
import { papers } from "@/lib/api/endpoints";
import { ApiError } from "@/lib/api/client";
import type { Paper, ResearchProfile } from "@/lib/api/types";
import { CINEMATIC as C } from "@/lib/cinematic-theme";
import { CoverageNote } from "./CoverageNote";
import { ResearchProfileView } from "./ResearchProfileView";

/** What an analysis warning means, in words (unknown codes pass through). */
const WARNING_TEXT: Record<string, string> = {
  no_abstract_section_detected: "No abstract section was found in this PDF, so the profile has no summary.",
  profile_extraction_failed: "The model's reply couldn't be read, so only the paper's details were saved. Run the analysis again.",
};

/** Which analysis a paper can have: from its full text, from its abstract
 * (a paper found by discovery), or none yet (a PDF still being read). */
export function analysisSource(paper: Pick<Paper, "has_full_text" | "source" | "has_abstract">): "full_text" | "abstract" | "pending" | "none" {
  if (paper.has_full_text) return "full_text";
  if (paper.has_abstract || paper.source === "discovery") return "abstract";
  return paper.source === "upload" || paper.source === undefined ? "pending" : "none";
}

interface PanelProps {
  paper: Paper;
  profile: ResearchProfile | null | undefined;
  loading: boolean;
  mutate: KeyedMutator<ResearchProfile | null>;
}

/**
 * A paper's research profile, or the way to get one. Shared by the seed
 * analysis page and the paper page, so a profile reads the same everywhere.
 * What text the paper is read from comes first: the profile rests on it.
 */
export function ProfilePanel(props: PanelProps) {
  return (
    <div className="space-y-5">
      <CoverageNote paper={props.paper} />
      <ProfileBody {...props} />
    </div>
  );
}

function ProfileBody({ paper, profile, loading, mutate }: PanelProps) {
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<{ text: string; settings?: boolean } | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const source = analysisSource(paper);

  async function analyze() {
    setAnalyzing(true);
    setError(null);
    setWarnings([]);
    try {
      const res = await papers.analyze(paper.id);
      await mutate(res.profile, { revalidate: false });
      setWarnings(res.warnings);
    } catch (err) {
      if (err instanceof ApiError && err.code === "llm_key_required") {
        setError({ text: "No working language model key is saved yet. Add one in Settings, then run the analysis again.", settings: true });
      } else {
        setError({ text: err instanceof ApiError ? err.message : "The analysis failed. Try again." });
      }
    } finally {
      setAnalyzing(false);
    }
  }

  if (loading) {
    return (
      <div role="status" className="space-y-2">
        <span className="sr-only">Loading the research profile…</span>
        <div className="h-4 w-full rounded motion-safe:animate-pulse" style={{ background: C.line }} />
        <div className="h-4 w-2/3 rounded motion-safe:animate-pulse" style={{ background: C.line }} />
      </div>
    );
  }

  const notices = warnings.length > 0 && (
    <ul className="space-y-1" role="status">
      {warnings.map((w) => (
        <li key={w} className="flex items-start gap-1.5 text-[13px]" style={{ color: C.warning }}>
          <WarningCircle className="mt-0.5 size-3.5 shrink-0" weight="bold" aria-hidden />
          {WARNING_TEXT[w] ?? w}
        </li>
      ))}
    </ul>
  );

  // its full text was found after the profile was read from its abstract
  const stale = profile && profile.grounding === "abstract" && paper.has_full_text && (
    <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-2 text-[13.5px]" style={{ color: C.ink }} data-testid="profile-stale">
      <span>This profile was read from the abstract; the full text is now available.</span>
      <button
        type="button"
        onClick={analyze}
        disabled={analyzing}
        className="inline-flex min-h-9 items-center gap-1.5 rounded-full px-4 text-[13px] font-semibold disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5df0a8]"
        style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
      >
        <Sparkle className="size-3.5" aria-hidden />
        {analyzing ? "Reading the full text…" : "Read the full text"}
      </button>
      {error && (
        <span role="alert" className="w-full" style={{ color: C.danger }}>
          {error.text}
        </span>
      )}
    </div>
  );

  if (profile) {
    const notice = stale || notices ? (
      <>
        {stale}
        {notices}
      </>
    ) : undefined;
    return <ResearchProfileView profile={profile} notice={notice} />;
  }

  if (source === "pending" || source === "none") {
    return (
      <p className="text-[14px]" style={{ color: C.muted }}>
        {source === "pending"
          ? "Still extracting text from this paper — the analysis will be available once reading finishes."
          : "This paper has no text to analyse yet."}
      </p>
    );
  }

  return (
    <div className="flex flex-col items-start gap-3">
      <p className="max-w-[62ch] text-[14px] leading-relaxed" style={{ color: C.muted }}>
        {source === "full_text"
          ? "Extract the research problem, methods, datasets, results and limitations from this paper’s full text."
          : "This paper was found by a search, so only its abstract is available. Its profile will be read from the abstract, and marked as such."}
      </p>
      <button
        type="button"
        onClick={analyze}
        disabled={analyzing}
        className="inline-flex items-center gap-2 rounded-full px-5 py-2.5 text-sm font-semibold transition-opacity disabled:opacity-60 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#5df0a8]"
        style={{ color: C.mintInk, background: `linear-gradient(180deg, ${C.mint}, ${C.mint2})` }}
      >
        <Sparkle className="size-4" aria-hidden />
        {analyzing ? "Running analysis…" : source === "full_text" ? "Run analysis" : "Analyse the abstract"}
      </button>
      {error && (
        <p role="alert" className="flex items-start gap-1.5 text-[14px]" style={{ color: C.danger }}>
          <WarningCircle className="mt-0.5 size-4 shrink-0" weight="bold" aria-hidden />
          <span>
            {error.text}
            {error.settings && (
              <>
                {" "}
                <Link href="/settings#models" className="underline underline-offset-4 hover:text-white">
                  Open Settings
                </Link>
              </>
            )}
          </span>
        </p>
      )}
    </div>
  );
}

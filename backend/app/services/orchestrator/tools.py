"""Typed tool registry + fixed workflow DAG (Architecture §4: `ResearchOrchestrator`
runs a **fixed workflow DAG**... **No runtime agent creation. No recursion.**).

`FIXED_STAGE_ORDER` and `STAGE_PREREQUISITE` are plain module-level
constants, not data the orchestrator can mutate at runtime -- the "no
runtime node creation" guarantee is structural, not merely a convention.

Each stage's actual call signature is too heterogeneous to unify behind one
generic `Callable` without fake abstraction (compare `run_ingestion`'s
`(db, paper_id, pdf_bytes, filename, settings)` to `answer_question`'s
`(db, *, workspace, request, session, settings, ...)`), so `TOOL_REGISTRY`
holds only typed *metadata* -- the name every `stage_runs` row uses, and
the input/output type names for the activity log and documentation.
`ResearchOrchestrator` (orchestrator.py) holds the one method per stage
that actually calls the already-existing Phase 1-13 pipeline function.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.orchestrator import StageName

FIXED_STAGE_ORDER: tuple[StageName, ...] = (
    StageName.INGEST,
    StageName.PROFILE,
    StageName.DISCOVERY,
    StageName.RANKING,
    StageName.TRAIL,
    StageName.WORKSPACE,
    StageName.RAG,
    StageName.COMPARISON,
    StageName.GAPS,
    StageName.DIRECTIONS,
    StageName.CITATIONS,
)

STAGE_PREREQUISITE: dict[StageName, StageName | None] = {
    StageName.INGEST: None,
    StageName.PROFILE: StageName.INGEST,
    StageName.DISCOVERY: StageName.PROFILE,
    StageName.RANKING: StageName.DISCOVERY,
    StageName.TRAIL: StageName.RANKING,
    StageName.WORKSPACE: StageName.TRAIL,
    StageName.RAG: StageName.WORKSPACE,
    StageName.COMPARISON: StageName.WORKSPACE,
    StageName.GAPS: StageName.WORKSPACE,
    StageName.DIRECTIONS: StageName.GAPS,
    StageName.CITATIONS: StageName.WORKSPACE,
}


@dataclass(frozen=True)
class StageTool:
    name: StageName
    description: str
    input_type: str
    output_type: str
    tool: str


TOOL_REGISTRY: dict[StageName, StageTool] = {
    StageName.INGEST: StageTool(
        StageName.INGEST, "Validate, parse, chunk and persist an uploaded PDF (S1-S3).",
        "pdf_bytes", "IngestResult", "run_ingestion",
    ),
    StageName.PROFILE: StageTool(
        StageName.PROFILE, "Extract the seed paper's ResearchProfile (S4).",
        "PaperORM", "AnalyzeResult", "run_profile_extraction",
    ),
    StageName.DISCOVERY: StageTool(
        StageName.DISCOVERY, "Search-plan generation + multi-strategy discovery (S5+S6, one combined entry point).",
        "SearchPlan(implicit)", "DiscoveryResult", "run_discovery",
    ),
    StageName.RANKING: StageTool(
        StageName.RANKING, "Score and band the discovered candidates (S9-S10).",
        "SearchRun", "RankResult", "rank_search_run",
    ),
    StageName.TRAIL: StageTool(
        StageName.TRAIL, "Type the seed-to-candidate relationships (S11).",
        "RankedPaper[]", "TrailBuildResult", "build_trail",
    ),
    StageName.WORKSPACE: StageTool(
        StageName.WORKSPACE, "Create the workspace and import the discovery run's trail (S12-S13).",
        "WorkspaceCreateRequest", "ResearchWorkspace", "create_workspace",
    ),
    StageName.RAG: StageTool(
        StageName.RAG, "Multi-paper retrieval-augmented question answering.",
        "RagRequest", "RagAnswer", "answer_question",
    ),
    StageName.COMPARISON: StageTool(
        StageName.COMPARISON, "Build the cross-paper comparison table.",
        "ComparisonSchema", "ComparisonResult", "build_comparison",
    ),
    StageName.GAPS: StageTool(
        StageName.GAPS, "Detect evidence-grounded research gaps.",
        "GapBuildOptions", "GapBuildResult", "build_gaps",
    ),
    StageName.DIRECTIONS: StageTool(
        StageName.DIRECTIONS, "Generate research directions from accepted gaps.",
        "gap_ids", "DirectionBuildResult", "build_directions",
    ),
    StageName.CITATIONS: StageTool(
        StageName.CITATIONS, "Resolve and format citations for workspace papers.",
        "paper_ids", "CitationsBuildResult", "build_citations",
    ),
}

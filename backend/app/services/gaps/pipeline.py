"""Gap workflow orchestration (Architecture §3 / §4 `GapAnalyzer`; Data
Model §8 "Pipeline (enforced in code order)"; Roadmap Phase 11).

Fixed order, every step a hard gate:

    matrix  ->  deterministic rule candidates (+ trail CONTRADICTION edges)
      ->  evidence assembly (>= 2 real papers or DROP)
      ->  constrained LLM articulation (introduces an unsupported claim -> DROP)
      ->  Self-RAG self-support check (fails -> DROP)
      ->  deterministic confidence band  ->  persist as `user_state="candidate"`

The LLM never sees a paper before a rule has fired, and no `ResearchGap`
is ever built from fewer than two evidence spans. `gap_id` is derived from
(workspace, type, papers, rule, key) so a rerun upserts the same rows; a
`rejected` gap is preserved and never re-proposed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.domain.gap import GapType, ResearchGap
from app.domain.workspace import Grounding, ResearchWorkspace
from app.llm.session import LlmSession
from app.services.gaps.articulate_llm import articulate
from app.services.gaps.candidates import GapCandidate, contradiction_candidates, generate_candidates
from app.services.gaps.confidence import assign_confidence, self_support_check
from app.services.gaps.evidence import assemble
from app.services.gaps.matrix import PaperMeta, build_matrix


@dataclass
class GapBuildOptions:
    gap_types: set[GapType] | None = None
    min_supporting_papers: int = 2


@dataclass
class GapBuildResult:
    workspace_id: str
    candidate_count: int = 0
    gap_count: int = 0
    dropped_insufficient_evidence: int = 0
    dropped_unsupported_articulation: int = 0
    dropped_self_support: int = 0
    skipped_rejected: int = 0
    by_type: dict[str, int] = field(default_factory=dict)


def _candidate_key(cand: GapCandidate) -> str:
    f = cand.facts
    return "|".join(
        str(x)
        for x in (
            f.get("value", ""),
            f.get("method", ""),
            f.get("dataset", ""),
            f.get("topic", ""),
            f.get("edge_id", ""),
            f.get("facet", ""),
        )
    )


def _gap_id(workspace_id: str, cand: GapCandidate) -> str:
    papers = ",".join(sorted(set(cand.supporting_papers)))
    raw = f"{workspace_id}|{cand.gap_type.value}|{cand.detection_rule}|{papers}|{_candidate_key(cand)}"
    return f"gap_{hashlib.sha256(raw.encode()).hexdigest()[:20]}"


def _paper_metas(db: Session, workspace: ResearchWorkspace) -> list[PaperMeta]:
    metas: list[PaperMeta] = []
    for wp in workspace.papers:
        paper = repo.get_paper(db, wp.paper_id)
        metas.append(
            PaperMeta(
                paper_id=wp.paper_id,
                title=paper.title if paper else wp.paper_id,
                year=paper.year if paper else None,
                abstract_only=wp.grounding is Grounding.ABSTRACT,
            )
        )
    return metas


async def build_gaps(
    db: Session,
    *,
    workspace: ResearchWorkspace,
    options: GapBuildOptions,
    session: LlmSession | None,
    settings: Settings,
) -> GapBuildResult:
    profiles = {
        wp.paper_id: p
        for wp in workspace.papers
        if (p := repo.get_profile(db, wp.paper_id)) is not None
    }
    metas = _paper_metas(db, workspace)
    matrix = build_matrix(profiles, metas)

    candidates = generate_candidates(matrix, gap_types=options.gap_types)
    trail_edges = repo.get_workspace_trail_edges(db, workspace.workspace_id)
    contradiction = contradiction_candidates(trail_edges)
    if options.gap_types is not None:
        contradiction = [c for c in contradiction if c.gap_type in options.gap_types]
    candidates += contradiction

    rejected = repo.get_rejected_gap_ids(db, workspace.workspace_id)
    result = GapBuildResult(workspace_id=workspace.workspace_id, candidate_count=len(candidates))
    gaps: list[ResearchGap] = []

    for cand in candidates:
        assembled = assemble(cand, min_papers=options.min_supporting_papers)
        if assembled is None:
            result.dropped_insufficient_evidence += 1
            continue

        gap_id = _gap_id(workspace.workspace_id, assembled)
        if gap_id in rejected:
            result.skipped_rejected += 1
            continue

        art = await articulate(session, assembled)
        if art is None:
            result.dropped_unsupported_articulation += 1
            continue

        quotes = [e.span.quote for e in assembled.supporting_evidence] + [
            e.span.quote for e in assembled.conflicting_evidence
        ]
        self_support = await self_support_check(session, art.statement, quotes)
        if not self_support:
            result.dropped_self_support += 1
            continue

        confidence, basis = assign_confidence(
            assembled, self_support_passed=self_support, evidence_coverage=assembled.evidence_coverage
        )
        gaps.append(
            ResearchGap(
                gap_id=gap_id,
                workspace_id=workspace.workspace_id,
                statement=art.statement,
                gap_type=assembled.gap_type,
                supporting_papers=assembled.supporting_papers,
                supporting_evidence=list(assembled.supporting_evidence),
                conflicting_evidence=list(assembled.conflicting_evidence),
                why_unaddressed=art.why_unaddressed,
                affected_methods=list(assembled.affected_methods),
                affected_datasets=list(assembled.affected_datasets),
                evidence_coverage=assembled.evidence_coverage,
                confidence=confidence,
                confidence_basis=basis,
                proposed_direction=art.proposed_direction,
                detection_rule=assembled.detection_rule,
                self_support_passed=self_support,
                generator_model=art.generator_model,
            )
        )
        result.by_type[assembled.gap_type.value] = result.by_type.get(assembled.gap_type.value, 0) + 1

    repo.save_gaps(db, workspace.workspace_id, gaps, owner_id=workspace.owner_id)
    result.gap_count = len(gaps)
    return result


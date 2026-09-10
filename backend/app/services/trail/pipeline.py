"""Stage S11 orchestration: rules -> LLM confirm -> contradiction NLI ->
deterministic confidence -> persist (Roadmap Phase 7).

Order is fixed and every step is optional-degrading: with no LLM session the
trail is the deterministic rule output alone (edges at capped confidence,
`detection_method=rule`); `POTENTIALLY_CONTRADICTORY` is never produced
without a session and a span verified in BOTH papers. A candidate for
which no rule fires gets NO edge -- "prefer UNKNOWN over unsupported
relationships".

Deterministic: `edge_id` is derived from (run_id, target, type), so a
re-run upserts the same rows; a user-`rejected` edge is preserved and its
(target, type) key is never re-proposed.

Run-scoped for the pre-workspace MVP; the async `GET /papers/{id}/related`
`trail_edges` payload + accept/reject routes are deferred (like the P5/P6
endpoints). The seed's `ResearchProfile` supplies the key-claims and
dataset spans -- discovery + ranking supply everything else.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.domain.profile import SourceSpan
from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge
from app.llm.session import LlmSession
from app.services.trail.confidence import assign_confidence
from app.services.trail.confirm_llm import confirm_rule_results
from app.services.trail.contradiction import verify_contradiction
from app.services.trail.rules import (
    CandidateView,
    RuleResult,
    TrailContext,
    TrailThresholds,
    apply_rules,
)
from app.services.trail.verify_span import find_span


class RunNotFound(Exception):
    pass


class SeedNotReady(Exception):
    """The run's seed paper or its ResearchProfile is missing (analyze first)."""


class RankingRequired(Exception):
    """The run has no ranked_papers yet (rank first)."""


@dataclass
class TrailOptions:
    session: LlmSession | None = None
    top_k: int | None = None
    thresholds: TrailThresholds = field(default_factory=TrailThresholds)


@dataclass
class TrailBuildResult:
    run_id: str
    edge_count: int
    typed_targets: int
    unknown_targets: int
    contradiction_edges: int
    warnings: list[str] = field(default_factory=list)


def _edge_id(run_id: str, target_paper_id: str, rtype: RelationshipType) -> str:
    digest = hashlib.sha256(f"{run_id}|{target_paper_id}|{rtype.value}".encode()).hexdigest()
    return f"edge_{digest[:20]}"


def _build_context(seed_paper, profile, max_claims: int) -> TrailContext:  # noqa: ANN001 - PaperORM
    findings = [
        (item.value, item.source_span)
        for item in (*profile.findings.items, *profile.limitations.items)
        if item.value.strip()
    ][:max_claims]
    return TrailContext(
        seed_paper_id=seed_paper.id,
        seed_year=seed_paper.year,
        seed_title=seed_paper.title,
        seed_abstract=seed_paper.abstract or profile.abstract,
        seed_datasets=[(i.value, i.source_span) for i in profile.datasets.items if i.value.strip()],
        seed_methods=[i.value for i in profile.methods.items if i.value.strip()],
        seed_findings=findings,
    )


async def build_trail(
    db: Session,
    *,
    run_id: str,
    settings: Settings,
    options: TrailOptions,
) -> TrailBuildResult:
    run = repo.get_search_run(db, run_id)
    if run is None:
        raise RunNotFound(run_id)
    seed = repo.get_paper(db, run.seed_paper_id)
    profile = repo.get_profile(db, run.seed_paper_id)
    if seed is None or profile is None:
        raise SeedNotReady(run.seed_paper_id)
    ranked = repo.get_ranked_papers(db, run_id)
    if not ranked:
        raise RankingRequired(run_id)

    candidates = {c.candidate_id: c for c in repo.get_search_candidates(db, run_id)}
    paper_ids = repo.get_search_candidate_paper_ids(db, run_id)
    rejected = repo.get_rejected_trail_keys(db, run_id)
    ctx = _build_context(seed, profile, settings.trail_max_seed_claims)
    session = options.session
    top_k = options.top_k if options.top_k is not None else settings.trail_top_k

    edges: list[TrailEdge] = []
    typed_targets: set[str] = set()
    unknown_targets = 0
    contradiction_edges = 0

    for rp in ranked[:top_k]:
        cand = candidates.get(rp.candidate_id)
        if cand is None:
            continue
        view = CandidateView(
            candidate_id=rp.candidate_id,
            paper_id=paper_ids[rp.candidate_id],
            title=cand.title,
            abstract=cand.abstract,
            year=cand.year,
            citation_relationship=cand.citation_relationship,
            citation_hops=cand.citation_hops,
            signals=rp.signals,
        )
        rule_results = apply_rules(ctx, view, thresholds=options.thresholds)
        if not rule_results:
            unknown_targets += 1
            continue

        non_contradiction = [r for r in rule_results if not r.is_contradiction_candidate]
        confirmations = await confirm_rule_results(session, ctx, view, non_contradiction)

        for rr in non_contradiction:
            if (view.paper_id, rr.relationship_type.value) in rejected:
                continue
            edge = _build_edge(run_id, run, view, rr, confirmations.get(rr.relationship_type), session)
            edges.append(edge)
            typed_targets.add(view.paper_id)

        for rr in rule_results:
            if not rr.is_contradiction_candidate:
                continue
            if session is None or (view.paper_id, RelationshipType.POTENTIALLY_CONTRADICTORY.value) in rejected:
                continue
            c_edge = await _build_contradiction_edge(run_id, run, view, rr, ctx, session)
            if c_edge is not None:
                edges.append(c_edge)
                typed_targets.add(view.paper_id)
                contradiction_edges += 1

    repo.save_trail_edges(db, run_id, edges)
    return TrailBuildResult(
        run_id=run_id,
        edge_count=len(edges),
        typed_targets=len(typed_targets),
        unknown_targets=unknown_targets,
        contradiction_edges=contradiction_edges,
    )


def _build_edge(run_id: str, run, view: CandidateView, rr: RuleResult, conf, session: LlmSession | None) -> TrailEdge:  # noqa: ANN001
    evidence = list(rr.evidence)
    llm_confirmed = bool(conf and conf.confirmed)
    if llm_confirmed and conf and conf.target_span:
        span = find_span(conf.target_span, view.abstract or "", paper_id=view.paper_id) or SourceSpan(
            paper_id=view.paper_id, quote=conf.target_span[:400]
        )
        evidence.append(Evidence(span=span, role="target_claim"))

    confidence, basis = assign_confidence(
        rr,
        llm_confirmed=llm_confirmed,
        llm_certainty=(conf.certainty if conf else "none"),
        evidence_count=len(evidence),
        session_present=session is not None,
    )
    return TrailEdge(
        edge_id=_edge_id(run_id, view.paper_id, rr.relationship_type),
        run_id=run_id,
        workspace_id=None,
        source_paper_id=run.seed_paper_id,
        target_paper_id=view.paper_id,
        relationship_type=rr.relationship_type,
        detection_method=DetectionMethod.RULE_LLM_CONFIRMED if llm_confirmed else DetectionMethod.RULE,
        rule_fired=rr.rule_fired,
        llm_confirmed=llm_confirmed,
        evidence=evidence,
        supporting_references=[view.paper_id],
        confidence=confidence,
        confidence_basis=basis,
    )


async def _build_contradiction_edge(
    run_id: str, run, view: CandidateView, rr: RuleResult, ctx: TrailContext, session: LlmSession  # noqa: ANN001
) -> TrailEdge | None:
    for claim_text, claim_span in ctx.seed_findings:
        pair = await verify_contradiction(session, claim_text, claim_span, view)
        if pair is None:
            continue
        confidence, basis = assign_confidence(
            rr, llm_confirmed=True, llm_certainty="high", evidence_count=2, session_present=True
        )
        return TrailEdge(
            edge_id=_edge_id(run_id, view.paper_id, RelationshipType.POTENTIALLY_CONTRADICTORY),
            run_id=run_id,
            workspace_id=None,
            source_paper_id=run.seed_paper_id,
            target_paper_id=view.paper_id,
            relationship_type=RelationshipType.POTENTIALLY_CONTRADICTORY,
            detection_method=DetectionMethod.CONTRADICTION_NLI,
            rule_fired=rr.rule_fired,
            llm_confirmed=True,
            evidence=list(pair),
            supporting_references=[view.paper_id],
            confidence=confidence,
            confidence_basis=basis,
        )
    return None

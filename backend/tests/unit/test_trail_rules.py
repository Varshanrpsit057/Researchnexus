from __future__ import annotations

from app.domain.candidate import CitationRelationship
from app.domain.profile import Confidence, SourceSpan
from app.domain.ranking import SignalScores
from app.domain.trail import RelationshipType
from app.services.trail.rules import (
    CandidateView,
    RuleResult,
    TrailContext,
    TrailThresholds,
    apply_rules,
)

_T = TrailThresholds()


def _ctx(**kw: object) -> TrailContext:
    base: dict[str, object] = {
        "seed_paper_id": "pap_seed",
        "seed_year": 2020,
        "seed_title": "Retrieval-Augmented Generation",
        "seed_abstract": "We combine parametric and non-parametric memory for knowledge-intensive tasks.",
        "seed_datasets": [("Natural Questions", SourceSpan(paper_id="pap_seed", quote="Natural Questions"))],
        "seed_methods": ["dense retrieval", "seq2seq"],
        "seed_findings": [("RAG reduces hallucination", SourceSpan(paper_id="pap_seed", quote="RAG reduces hallucination"))],
    }
    base.update(kw)
    return TrailContext(**base)  # type: ignore[arg-type]


def _cand(**kw: object) -> CandidateView:
    base: dict[str, object] = {
        "candidate_id": "cand_1",
        "paper_id": "pap_x",
        "title": "Some Candidate Paper",
        "abstract": "An abstract mentioning some approach and results.",
        "year": 2021,
        "citation_relationship": CitationRelationship.NONE,
        "citation_hops": None,
        "signals": SignalScores(),
    }
    base.update(kw)
    return CandidateView(**base)  # type: ignore[arg-type]


def _types(results: list[RuleResult]) -> set[RelationshipType]:
    return {r.relationship_type for r in results}


# --- FOUNDATIONAL --------------------------------------------------------------


def test_foundational_fires_when_seed_cites_an_older_paper() -> None:
    cand = _cand(year=2016, citation_relationship=CitationRelationship.CITED_BY_SEED, citation_hops=1)
    results = apply_rules(_ctx(), cand, thresholds=_T)
    assert RelationshipType.FOUNDATIONAL in _types(results)
    edge = next(r for r in results if r.relationship_type is RelationshipType.FOUNDATIONAL)
    assert edge.evidence  # a citation span is attached
    assert edge.rule_confidence == Confidence.HIGH  # cited + >=2yr gap


def test_foundational_does_not_fire_for_a_newer_cited_paper() -> None:
    cand = _cand(year=2023, citation_relationship=CitationRelationship.CITED_BY_SEED)
    assert RelationshipType.FOUNDATIONAL not in _types(apply_rules(_ctx(), cand, thresholds=_T))


def test_foundational_needs_a_year_on_both_papers() -> None:
    cand = _cand(year=None, citation_relationship=CitationRelationship.CITED_BY_SEED)
    assert RelationshipType.FOUNDATIONAL not in _types(apply_rules(_ctx(), cand, thresholds=_T))


# --- RECENT ------------------------------------------------------------------


def test_recent_fires_for_a_newer_related_paper() -> None:
    cand = _cand(year=2024, signals=SignalScores(problem_sim=0.7))
    assert RelationshipType.RECENT in _types(apply_rules(_ctx(), cand, thresholds=_T))


def test_recent_does_not_fire_without_a_similarity_signal() -> None:
    cand = _cand(year=2024, signals=SignalScores())
    assert RelationshipType.RECENT not in _types(apply_rules(_ctx(), cand, thresholds=_T))


def test_recent_does_not_fire_for_an_older_paper() -> None:
    cand = _cand(year=2018, signals=SignalScores(problem_sim=0.9))
    assert RelationshipType.RECENT not in _types(apply_rules(_ctx(), cand, thresholds=_T))


# --- DATASET_RELATED --------------------------------------------------------


def test_dataset_related_fires_on_a_shared_dataset_named_in_the_abstract() -> None:
    cand = _cand(abstract="We evaluate on Natural Questions and report EM.", signals=SignalScores())
    results = apply_rules(_ctx(), cand, thresholds=_T)
    assert RelationshipType.DATASET_RELATED in _types(results)
    edge = next(r for r in results if r.relationship_type is RelationshipType.DATASET_RELATED)
    roles = {e.role for e in edge.evidence}
    assert "shared_dataset" in roles  # verbatim dataset span from the candidate
    assert any(e.span.paper_id == "pap_seed" for e in edge.evidence)  # and a seed-side span


def test_dataset_related_fires_on_a_high_overlap_signal_alone() -> None:
    cand = _cand(abstract="no dataset name here", signals=SignalScores(dataset_overlap=0.75))
    assert RelationshipType.DATASET_RELATED in _types(apply_rules(_ctx(), cand, thresholds=_T))


def test_dataset_related_does_not_fire_with_no_shared_dataset() -> None:
    cand = _cand(abstract="We use CIFAR-10.", signals=SignalScores(dataset_overlap=0.1))
    assert RelationshipType.DATASET_RELATED not in _types(apply_rules(_ctx(), cand, thresholds=_T))


# --- METHOD_EXTENSION -----------------------------------------------------


def test_method_extension_fires_when_a_newer_paper_cites_the_seed_and_shares_methods() -> None:
    cand = _cand(
        year=2022,
        citation_relationship=CitationRelationship.CITES_SEED,
        citation_hops=1,
        signals=SignalScores(method_sim=0.7),
    )
    assert RelationshipType.METHOD_EXTENSION in _types(apply_rules(_ctx(), cand, thresholds=_T))


def test_method_extension_does_not_fire_without_the_citation_to_the_seed() -> None:
    cand = _cand(citation_relationship=CitationRelationship.NONE, signals=SignalScores(method_sim=0.9))
    assert RelationshipType.METHOD_EXTENSION not in _types(apply_rules(_ctx(), cand, thresholds=_T))


def test_method_extension_does_not_fire_with_low_method_similarity() -> None:
    cand = _cand(citation_relationship=CitationRelationship.CITES_SEED, signals=SignalScores(method_sim=0.2))
    assert RelationshipType.METHOD_EXTENSION not in _types(apply_rules(_ctx(), cand, thresholds=_T))


# --- COMPETING ----------------------------------------------------------------


def test_competing_fires_on_same_problem_different_method() -> None:
    cand = _cand(signals=SignalScores(problem_sim=0.8, method_sim=0.2))
    assert RelationshipType.COMPETING in _types(apply_rules(_ctx(), cand, thresholds=_T))


def test_competing_does_not_fire_when_methods_are_also_similar() -> None:
    cand = _cand(signals=SignalScores(problem_sim=0.8, method_sim=0.8))
    assert RelationshipType.COMPETING not in _types(apply_rules(_ctx(), cand, thresholds=_T))


def test_competing_does_not_fire_when_the_papers_cite_each_other() -> None:
    cand = _cand(
        citation_relationship=CitationRelationship.CITES_SEED, signals=SignalScores(problem_sim=0.8, method_sim=0.1)
    )
    assert RelationshipType.COMPETING not in _types(apply_rules(_ctx(), cand, thresholds=_T))


# --- SIMILAR ----------------------------------------------------------------


def test_similar_is_the_fallback_for_a_strong_generic_match() -> None:
    # no year -> RECENT cannot fire; nothing else applies -> SIMILAR
    cand = _cand(year=None, signals=SignalScores(semantic_doc=0.8))
    assert _types(apply_rules(_ctx(), cand, thresholds=_T)) == {RelationshipType.SIMILAR}


def test_similar_is_suppressed_when_a_specific_type_fires() -> None:
    cand = _cand(year=2024, signals=SignalScores(semantic_doc=0.9, problem_sim=0.8))
    types = _types(apply_rules(_ctx(), cand, thresholds=_T))
    assert RelationshipType.RECENT in types
    assert RelationshipType.SIMILAR not in types  # RECENT subsumes it


def test_similar_coexists_with_dataset_related() -> None:
    cand = _cand(year=None, abstract="Evaluated on Natural Questions.", signals=SignalScores(semantic_doc=0.85))
    types = _types(apply_rules(_ctx(), cand, thresholds=_T))
    assert {RelationshipType.SIMILAR, RelationshipType.DATASET_RELATED} <= types


def test_no_rule_fires_for_an_unrelated_paper() -> None:
    cand = _cand(abstract="A paper about protein folding.", year=2019, signals=SignalScores(semantic_doc=0.1))
    assert apply_rules(_ctx(), cand, thresholds=_T) == []


# --- POTENTIALLY_CONTRADICTORY (rule only proposes a candidate) ---------------


def test_contradiction_is_only_proposed_as_a_candidate_never_a_confirmed_edge() -> None:
    cand = _cand(
        abstract="We find that retrieval does not reduce hallucination in long-form generation.",
        signals=SignalScores(problem_sim=0.75),
    )
    results = apply_rules(_ctx(), cand, thresholds=_T)
    contradiction = [r for r in results if r.relationship_type is RelationshipType.POTENTIALLY_CONTRADICTORY]
    assert len(contradiction) == 1
    assert contradiction[0].is_contradiction_candidate is True


def test_contradiction_not_proposed_without_seed_findings_or_topical_overlap() -> None:
    cand = _cand(abstract="Unrelated content.", signals=SignalScores(problem_sim=0.1))
    results = apply_rules(_ctx(seed_findings=[]), cand, thresholds=_T)
    assert RelationshipType.POTENTIALLY_CONTRADICTORY not in _types(results)


def test_repeated_calls_are_deterministic() -> None:
    cand = _cand(year=2016, citation_relationship=CitationRelationship.CITED_BY_SEED, signals=SignalScores(semantic_doc=0.8))
    a = apply_rules(_ctx(), cand, thresholds=_T)
    b = apply_rules(_ctx(), cand, thresholds=_T)
    assert [r.relationship_type for r in a] == [r.relationship_type for r in b]
    assert [r.rule_fired for r in a] == [r.rule_fired for r in b]

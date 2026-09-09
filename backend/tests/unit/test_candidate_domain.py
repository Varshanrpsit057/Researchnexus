from __future__ import annotations

from app.domain.candidate import (
    CandidateSource,
    CitationRelationship,
    DiscoveryStrategy,
    NormalizedCandidate,
    PaperCandidate,
    RawExternalRecord,
    RawSignalScores,
    SearchRun,
)


def test_raw_external_record_minimal() -> None:
    rec = RawExternalRecord(source=CandidateSource.ARXIV, title="A Paper")
    assert rec.authors == []
    assert rec.is_preprint is False
    assert rec.raw == {}


def test_normalized_candidate_defaults() -> None:
    cand = NormalizedCandidate(title="A Paper", title_hash="abc")
    assert cand.external_ids == {}
    assert cand.sources == []
    assert cand.field_provenance == []
    assert cand.possible_duplicate is False


def test_paper_candidate_matches_data_model_shape() -> None:
    cand = PaperCandidate(candidate_id="cand_1", run_id="run_1", title="A Paper")
    assert cand.discovery_methods == []
    assert cand.citation_relationship == CitationRelationship.NONE
    assert cand.filter_kept is True
    assert isinstance(cand.raw_signals, RawSignalScores)


def test_search_run_defaults() -> None:
    run = SearchRun(run_id="run_1", seed_paper_id="pap_1")
    assert run.strategies_requested == []
    assert run.candidate_count_raw == 0
    assert run.finished_at is None


def test_enums_have_data_model_values() -> None:
    assert DiscoveryStrategy.RESEARCH_QUESTION.value == "research_question"
    assert CitationRelationship.CITES_SEED.value == "cites_seed"
    assert CandidateSource.SEMANTIC_SCHOLAR.value == "semantic_scholar"

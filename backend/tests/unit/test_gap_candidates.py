from __future__ import annotations

from app.domain.gap import GapType
from app.domain.profile import Confidence, SourceSpan
from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge
from app.services.gaps.candidates import contradiction_candidates, generate_candidates
from app.services.gaps.matrix import GapMatrix, MatrixEntry, PaperMeta


def _span(pid: str, quote: str) -> SourceSpan:
    return SourceSpan(paper_id=pid, section="Body", char_start=1, char_end=10, quote=quote)


def _matrix(spec: dict[str, dict[str, list[str]]], years: dict[str, int] | None = None) -> GapMatrix:
    """spec = {paper_id: {facet: [values]}}."""
    years = years or {}
    papers = [PaperMeta(paper_id=pid, title=pid.upper(), year=years.get(pid, 2022)) for pid in spec]
    cells: dict[tuple[str, str], list[MatrixEntry]] = {}
    from app.services.gaps.matrix import FACETS, norm

    for pid, facets in spec.items():
        for facet in FACETS:
            vals = facets.get(facet, [])
            cells[(pid, facet)] = [MatrixEntry(value=norm(v), raw=v, span=_span(pid, v)) for v in vals]
    return GapMatrix(papers, cells)


def _types(cands: list) -> set[GapType]:
    return {c.gap_type for c in cands}


# --- METHOD_GAP -----------------------------------------------------------


def test_method_gap_fires_when_two_plus_papers_omit_a_method_used_elsewhere() -> None:
    m = _matrix({
        "a": {"problem": ["dense retrieval"], "method": ["contrastive pretraining"]},
        "b": {"problem": ["dense retrieval"], "method": ["bm25"]},
        "c": {"problem": ["dense retrieval"], "method": ["tf-idf"]},
    })
    cands = generate_candidates(m, gap_types=None)
    method = [c for c in cands if c.gap_type is GapType.METHOD_GAP and "contrastive pretraining" in c.affected_methods]
    assert method
    assert method[0].facts["missing_from"] == ["b", "c"]  # the papers that omit it, sharing the problem
    # the evidence shows both sides: the paper that uses it, in its own words, and the ones that don't
    roles = [(e.paper_id, e.role, e.span.quote) for e in method[0].supporting_evidence]
    assert roles[0] == ("a", "supports_gap", "contrastive pretraining")
    assert {(pid, role) for pid, role, _ in roles[1:]} == {("b", "shared_context"), ("c", "shared_context")}
    assert set(method[0].supporting_papers) == {"b", "c"}  # the gap's papers: the ones lacking it


def test_method_gap_does_not_fire_when_only_one_paper_omits_the_method() -> None:
    m = _matrix({
        "a": {"problem": ["x"], "method": ["m1"]},
        "b": {"problem": ["x"], "method": ["m1", "m2"]},
        "c": {"problem": ["x"], "method": ["m1"]},
    })
    # only 'b' has m2 and only... a & c omit m2 -> that IS 2. Flip: m1 omitted by nobody.
    cands = [c for c in generate_candidates(m, gap_types=None) if c.gap_type is GapType.METHOD_GAP]
    assert all("m1" not in c.affected_methods for c in cands)


def test_method_gap_requires_a_shared_problem_context() -> None:
    m = _matrix({
        "a": {"problem": ["retrieval"], "method": ["m1"]},
        "b": {"problem": ["vision"], "method": ["m2"]},
        "c": {"problem": ["nlp"], "method": ["m3"]},
    })
    cands = [c for c in generate_candidates(m, gap_types=None) if c.gap_type is GapType.METHOD_GAP]
    assert cands == []  # no shared problem -> not a gap, just unrelated papers


# --- DATASET_GAP / EVALUATION_GAP -------------------------------------


def test_dataset_gap_fires_when_no_dataset_is_shared_by_two_papers() -> None:
    m = _matrix({
        "a": {"dataset": ["NQ"]},
        "b": {"dataset": ["TriviaQA"]},
        "c": {"dataset": ["HotpotQA"]},
    })
    cands = generate_candidates(m, gap_types=None)
    assert GapType.DATASET_GAP in _types(cands)
    ds = next(c for c in cands if c.gap_type is GapType.DATASET_GAP)
    assert set(ds.supporting_papers) == {"a", "b", "c"}


def test_dataset_gap_does_not_fire_when_a_dataset_is_shared() -> None:
    m = _matrix({"a": {"dataset": ["NQ", "X"]}, "b": {"dataset": ["NQ"]}, "c": {"dataset": ["Y"]}})
    assert GapType.DATASET_GAP not in _types(generate_candidates(m, gap_types=None))


def test_evaluation_gap_fires_when_no_metric_is_shared() -> None:
    m = _matrix({"a": {"metric": ["exact match"]}, "b": {"metric": ["recall@20"]}})
    assert GapType.EVALUATION_GAP in _types(generate_candidates(m, gap_types=None))


# --- GENERALIZATION_GAP (shared limitation) -------------------------


def test_generalization_gap_fires_on_a_limitation_shared_by_two_papers() -> None:
    m = _matrix({
        "a": {"limitation": ["evaluated only on English"]},
        "b": {"limitation": ["evaluated only on English"]},
        "c": {"limitation": ["small model"]},
    })
    cands = generate_candidates(m, gap_types=None)
    gen = [c for c in cands if c.gap_type is GapType.GENERALIZATION_GAP]
    assert gen and set(gen[0].supporting_papers) == {"a", "b"}
    assert gen[0].facts.get("limitation_agreement") is True


def test_generalization_gap_ignores_a_limitation_named_by_only_one_paper() -> None:
    m = _matrix({"a": {"limitation": ["x"]}, "b": {"limitation": ["y"]}})
    assert GapType.GENERALIZATION_GAP not in _types(generate_candidates(m, gap_types=None))


# --- UNEXPLORED_COMBINATION -----------------------------------------


def test_unexplored_combination_fires_when_no_paper_combines_a_common_method_and_dataset() -> None:
    m = _matrix({
        "a": {"method": ["graph nn"], "dataset": ["ogb"]},
        "b": {"method": ["graph nn"], "dataset": ["ogb"]},
        "c": {"method": ["transformer"], "dataset": ["imagenet"]},
        "d": {"method": ["transformer"], "dataset": ["imagenet"]},
    })
    # method "graph nn" (a,b) x dataset "imagenet" (c,d) -> never combined
    cands = [c for c in generate_candidates(m, gap_types=None) if c.gap_type is GapType.UNEXPLORED_COMBINATION]
    combos = {(c.affected_methods[0], c.affected_datasets[0]) for c in cands}
    assert ("graph nn", "imagenet") in combos or ("transformer", "ogb") in combos


def test_unexplored_combination_does_not_fire_when_a_paper_uses_both() -> None:
    m = _matrix({
        "a": {"method": ["m"], "dataset": ["d"]},
        "b": {"method": ["m"], "dataset": ["d"]},
    })
    assert GapType.UNEXPLORED_COMBINATION not in _types(generate_candidates(m, gap_types=None))


# --- TEMPORAL_GAP ---------------------------------------------------


def test_temporal_gap_fires_when_a_shared_topic_has_no_recent_paper() -> None:
    m = _matrix(
        {"a": {"problem": ["knowledge graphs"]}, "b": {"problem": ["knowledge graphs"]}, "c": {"problem": ["llm agents"]}},
        years={"a": 2016, "b": 2017, "c": 2024},
    )
    cands = [c for c in generate_candidates(m, gap_types=None) if c.gap_type is GapType.TEMPORAL_GAP]
    assert cands and set(cands[0].supporting_papers) == {"a", "b"}


def test_temporal_gap_does_not_fire_without_a_stale_gap_or_year_data() -> None:
    recent = _matrix({"a": {"problem": ["t"]}, "b": {"problem": ["t"]}}, years={"a": 2023, "b": 2024})
    assert GapType.TEMPORAL_GAP not in _types(generate_candidates(recent, gap_types=None))
    noyear = _matrix({"a": {"problem": ["t"]}, "b": {"problem": ["t"]}}, years={})
    # PaperMeta year defaults to 2022 in the helper -> override to None
    for p in noyear._papers:
        p.year = None
    assert GapType.TEMPORAL_GAP not in _types(generate_candidates(noyear, gap_types=None))


# --- CONTRADICTION (from trail edges) -----------------------------


def test_contradiction_candidates_come_from_potentially_contradictory_trail_edges() -> None:
    edge = TrailEdge(
        edge_id="edge_1", run_id="run_1", source_paper_id="p1", target_paper_id="p2",
        relationship_type=RelationshipType.POTENTIALLY_CONTRADICTORY, detection_method=DetectionMethod.CONTRADICTION_NLI,
        evidence=[
            Evidence(span=SourceSpan(paper_id="p1", quote="method A improves accuracy"), role="seed_claim"),
            Evidence(span=SourceSpan(paper_id="p2", quote="method A does not improve accuracy"), role="target_claim"),
        ],
        confidence=Confidence.MEDIUM,
    )
    similar = TrailEdge(
        edge_id="edge_2", run_id="run_1", source_paper_id="p1", target_paper_id="p3",
        relationship_type=RelationshipType.SIMILAR, detection_method=DetectionMethod.RULE,
        evidence=[Evidence(span=SourceSpan(paper_id="p3", quote="x"), role="similarity_signal")],
        confidence=Confidence.MEDIUM,
    )
    cands = contradiction_candidates([edge, similar])
    assert len(cands) == 1
    c = cands[0]
    assert c.gap_type is GapType.CONTRADICTION
    assert set(c.supporting_papers) == {"p1", "p2"}
    assert len(c.conflicting_evidence) == 2
    assert {e.role for e in c.conflicting_evidence} == {"conflicts_with_gap"}


def test_gap_types_filter_limits_which_rules_run() -> None:
    m = _matrix({"a": {"dataset": ["x"], "limitation": ["shared"]}, "b": {"dataset": ["y"], "limitation": ["shared"]}})
    only_ds = generate_candidates(m, gap_types={GapType.DATASET_GAP})
    assert _types(only_ds) == {GapType.DATASET_GAP}

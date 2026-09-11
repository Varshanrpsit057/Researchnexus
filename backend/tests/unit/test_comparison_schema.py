from __future__ import annotations

from app.domain.profile import ProfileField, ProfileList, ResearchProfile
from app.services.synthesis.compare import DEFAULT_COLUMNS, build_schema


def _profile(pid: str, **lists: list[str]) -> ResearchProfile:
    kw: dict = {
        "profile_id": f"prof_{pid}",
        "paper_id": pid,
        "title": pid,
        "abstract": "abstract",
        "domain": ProfileField(value="x"),
        "research_problem": ProfileField(value=lists.get("problem", ["p"])[0] if lists.get("problem") else ""),
    }
    for facet, dest in (("methods", "methods"), ("datasets", "datasets"), ("metrics", "evaluation_metrics"), ("findings", "findings"), ("limitations", "limitations")):
        vals = lists.get(facet, [])
        if vals:
            kw[dest] = ProfileList(items=[ProfileField(value=v) for v in vals])
    return ResearchProfile(**kw)


def test_default_schema_is_the_union_of_populated_profile_facets() -> None:
    a = _profile("a", methods=["dense retrieval"], datasets=["NQ"])
    b = _profile("b", methods=["bm25"], findings=["+3 EM"])
    sch = build_schema([a, b], explicit=None)
    assert sch.generated_by == "deterministic_union"
    # method + dataset + result present; metric + limitation + problem absent
    assert sch.columns == ["method", "dataset", "result"]


def test_schema_falls_back_to_default_columns_when_no_profile_data() -> None:
    sch = build_schema([], explicit=None)
    assert sch.columns == DEFAULT_COLUMNS
    sch2 = build_schema([_profile("a")], explicit=None)  # profile with no populated lists
    assert sch2.columns == DEFAULT_COLUMNS


def test_explicit_schema_is_normalised_and_marked_deterministic() -> None:
    sch = build_schema([], explicit=[" Method ", "method", "Dataset", "", "  ", "RESULT"])
    assert sch.columns == ["method", "dataset", "result"]
    assert sch.generated_by == "deterministic_union"


def test_schema_generation_is_deterministic() -> None:
    a = _profile("a", methods=["m"], metrics=["f1"], datasets=["d"])
    b = _profile("b", problem=["prob"], limitations=["small n"])
    first = build_schema([a, b], explicit=None).columns
    second = build_schema([b, a], explicit=None).columns
    assert first == second == ["problem", "method", "dataset", "metric", "limitation"]

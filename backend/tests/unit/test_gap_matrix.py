from __future__ import annotations

from app.domain.profile import ProfileField, ProfileList, ResearchProfile, SourceSpan
from app.services.gaps.matrix import PaperMeta, build_matrix


def _profile(pid: str, **facets: list[str]) -> ResearchProfile:
    kw: dict = {
        "profile_id": f"prof_{pid}", "paper_id": pid, "title": pid, "abstract": "ab",
        "domain": ProfileField(value="IR"),
        "research_problem": ProfileField(
            value=facets.get("problem", ["retrieval"])[0] if facets.get("problem") else "retrieval",
            source_span=SourceSpan(paper_id=pid, section="Intro", char_start=1, char_end=9, quote="retrieval"),
        ),
    }
    for facet, attr in (("methods", "methods"), ("datasets", "datasets"), ("metrics", "evaluation_metrics"), ("limitations", "limitations")):
        vals = facets.get(facet, [])
        if vals:
            kw[attr] = ProfileList(items=[
                ProfileField(value=v, source_span=SourceSpan(paper_id=pid, section="Body", char_start=10, char_end=20, quote=v))
                for v in vals
            ])
    return ResearchProfile(**kw)


def _meta(pid: str, year: int | None = 2022) -> PaperMeta:
    return PaperMeta(paper_id=pid, title=pid.upper(), year=year)


def test_matrix_rows_are_papers_and_pulls_profile_facets_with_spans() -> None:
    a = _profile("a", methods=["Dense Retrieval", "BM25"], datasets=["NQ"])
    b = _profile("b", methods=["bm25"], limitations=["small scale"])
    m = build_matrix({"a": a, "b": b}, [_meta("a"), _meta("b")])

    assert m.paper_ids() == ["a", "b"]
    assert m.values("a", "method") == {"dense retrieval", "bm25"}  # normalised
    entries = m.entries("a", "method")
    assert all(e.span is not None and e.span.paper_id == "a" for e in entries)
    assert m.values("b", "limitation") == {"small scale"}


def test_papers_with_and_without_a_value_use_normalised_matching() -> None:
    a = _profile("a", methods=["BM25"])
    b = _profile("b", methods=["bm25 "])
    c = _profile("c", methods=["dense retrieval"])
    m = build_matrix({"a": a, "b": b, "c": c}, [_meta("a"), _meta("b"), _meta("c")])

    assert set(m.papers_with("method", "bm25")) == {"a", "b"}
    assert set(m.papers_without("method", "bm25")) == {"c"}


def test_value_counts_and_newest_year() -> None:
    a = _profile("a", datasets=["NQ", "TriviaQA"])
    b = _profile("b", datasets=["NQ"])
    m = build_matrix({"a": a, "b": b}, [_meta("a", 2019), _meta("b", 2023)])
    counts = m.value_counts("dataset")
    assert set(counts["nq"]) == {"a", "b"}
    assert counts["triviaqa"] == ["a"]
    assert m.newest_year() == 2023


def test_paper_without_a_profile_is_still_a_row_with_empty_cells() -> None:
    a = _profile("a", methods=["x"])
    m = build_matrix({"a": a}, [_meta("a"), _meta("ghost")])
    assert "ghost" in m.paper_ids()
    assert m.values("ghost", "method") == set()

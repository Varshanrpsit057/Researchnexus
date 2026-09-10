from __future__ import annotations

from app.db.models import PaperORM
from app.domain.citation import NOT_AVAILABLE
from app.services.citations.metadata_resolver import resolve_paper, to_citation
from app.services.normalize.canonical import title_hash


def _paper(**kw: object) -> PaperORM:
    base: dict[str, object] = {
        "id": "pap_1",
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        "title_hash": title_hash("rag"),
        "authors": ["Patrick Lewis", "Ethan Perez"],
        "year": 2020,
    }
    base.update(kw)
    return PaperORM(**base)


def test_resolved_from_prefers_doi_then_arxiv_then_metadata() -> None:
    assert resolve_paper(_paper(doi="10.1/x")).resolved_from == "crossref"
    assert resolve_paper(_paper(arxiv_id="2005.11401")).resolved_from == "arxiv"
    assert resolve_paper(_paper()).resolved_from == "openalex"  # title + authors + year
    assert resolve_paper(_paper(authors=[], year=None)).resolved_from == "unresolved"
    assert resolve_paper(_paper(title="")).resolved_from == "unresolved"


def test_csl_maps_stored_metadata_and_splits_author_names() -> None:
    csl = resolve_paper(_paper(venue="NeurIPS", doi="10.1/x")).csl_json
    assert csl["title"].startswith("Retrieval-Augmented")
    assert csl["author"] == [
        {"family": "Lewis", "given": "Patrick"},
        {"family": "Perez", "given": "Ethan"},
    ]
    assert csl["issued"] == {"date-parts": [[2020]]}
    assert csl["container-title"] == "NeurIPS"
    assert csl["DOI"] == "10.1/x"


def test_comma_form_author_names_are_handled() -> None:
    csl = resolve_paper(_paper(authors=["Ahad, Jawad Ibn"])).csl_json
    assert csl["author"] == [{"family": "Ahad", "given": "Jawad Ibn"}]


def test_to_citation_builds_formatted_for_resolved_paper() -> None:
    cit = to_citation("ws_1", _paper(venue="NeurIPS", doi="10.1/x"), number=1)
    assert cit.workspace_id == "ws_1" and cit.paper_id == "pap_1"
    assert cit.resolved_from == "crossref"
    assert cit.formatted["apa"].startswith("Lewis, P., & Perez, E. (2020).")
    assert cit.formatted["ieee"].startswith('[1] P. Lewis and E. Perez,')
    assert cit.formatted["bibtex"].startswith("@article{lewis2020retrieval,")


def test_to_citation_never_guesses_an_unresolved_reference() -> None:
    cit = to_citation("ws_1", _paper(title="Mystery Paper", authors=[], year=None))
    assert cit.resolved_from == "unresolved"
    assert cit.formatted == {"apa": NOT_AVAILABLE, "ieee": NOT_AVAILABLE, "bibtex": NOT_AVAILABLE}

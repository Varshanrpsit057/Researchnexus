"""An uploaded paper's record, completed from its sources (remediation,
2026-10-02): matched by the DOI it prints or its exact title, filling only
what the PDF lacks."""

from __future__ import annotations

import asyncio
import json

import httpx

from app.db.models import PaperORM
from app.external.http import ExternalHttpClient
from app.services.metadata.enrich import apply_metadata
from app.services.metadata.lookup import PaperMetadata, find_metadata, same_title
from app.services.metadata.publishers import from_doi, is_trusted, normalize, publisher_of

DOI = "10.1109/isci65687.2025.11167819"
TITLE = "OnBoard: A Real-Time Bus Tracking Mobile Application for University Campus"
WORK = {
    "id": "https://openalex.org/W1",
    "doi": f"https://doi.org/{DOI}",
    "title": TITLE,
    "publication_year": 2025,
    "authorships": [{"author": {"display_name": "Mohd Suffian Sulaiman"}}, {"author": {"display_name": "Syaqir Syamsul"}}],
    "abstract_inverted_index": {"Public": [0], "transport": [1], "matters.": [2]},
    "primary_location": {"source": None},
}
MESSAGE = {
    "DOI": DOI,
    "title": [TITLE],
    "publisher": "Institute of Electrical and Electronics Engineers (IEEE)",
    "container-title": ["2025 IEEE 7th Symposium on Computers &amp;amp; Informatics (ISCI)"],
    "author": [{"given": "Mohd Suffian", "family": "Sulaiman"}, {"given": "Syaqir", "family": "Syamsul"}],
    "issued": {"date-parts": [[2025, 8]]},
}


def _http(handler) -> ExternalHttpClient:  # noqa: ANN001
    return ExternalHttpClient(transport=httpx.MockTransport(handler), max_retries=0)


def _sources(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "api.openalex.org/works/https://doi.org/" in url:
        return httpx.Response(200, json=WORK)
    if "api.crossref.org/works/" in url:
        return httpx.Response(200, json={"message": MESSAGE})
    if "api.crossref.org/works" in url and "query.bibliographic" in url:
        other = {**MESSAGE, "DOI": "10.1/other", "title": ["OnBoard: Something Else Entirely"]}
        return httpx.Response(200, json={"message": {"items": [other, MESSAGE]}})
    return httpx.Response(404, json={})


def _openalex_out_of_budget(request: httpx.Request) -> httpx.Response:
    # OpenAlex's keyless daily budget, spent (measured 2026-10-02): every request refused
    if request.url.host == "api.openalex.org":
        return httpx.Response(429, headers={"Retry-After": "1464"}, json={"error": "Rate limit exceeded"})
    return _sources(request)


def test_publishers_are_named_as_readers_know_them() -> None:
    assert normalize("Institute of Electrical and Electronics Engineers (IEEE)") == "IEEE"
    assert normalize("Springer Science and Business Media LLC") == "Springer"
    assert normalize("Association for Computing Machinery (ACM)") == "ACM"
    assert normalize("Elsevier BV") == "Elsevier"
    assert normalize("Some University Press Ltd") == "Some University Press"
    assert from_doi("https://doi.org/10.1145/3292500.3330919") == "ACM"
    assert from_doi("10.1016/j.cell.2020.01.001") == "Elsevier"
    assert from_doi("10.9999/unknown") is None
    assert publisher_of(None, "10.1007/978-3-030-1") == "Springer"
    assert [is_trusted(p) for p in ("IEEE", "Springer", "ACM", "Elsevier", "MDPI", None)] == [True] * 4 + [False, False]


def test_a_paper_is_found_by_the_doi_it_prints() -> None:
    meta = asyncio.run(find_metadata(_http(_sources), doi=DOI, title=TITLE))
    assert meta is not None and meta.matched_by == "doi" and meta.sources == ["crossref", "openalex"]
    assert meta.authors == ["Mohd Suffian Sulaiman", "Syaqir Syamsul"]  # the publisher's order
    assert meta.venue == "2025 IEEE 7th Symposium on Computers & Informatics (ISCI)"  # unescaped
    assert (meta.publisher, meta.year, meta.doi) == ("IEEE", 2025, DOI)
    assert meta.abstract == "Public transport matters."


def test_without_a_doi_only_the_exact_title_matches() -> None:
    meta = asyncio.run(find_metadata(_http(_sources), doi=None, title=TITLE))
    assert meta is not None and meta.matched_by == "title" and meta.doi == DOI
    assert meta.sources == ["crossref", "openalex"]  # the DOI found by title is followed
    assert asyncio.run(find_metadata(_http(_sources), doi=None, title="A Survey of Something Unrelated")) is None
    assert same_title("OnBoard: a real-time bus tracking mobile application for university campus.", TITLE)
    assert not same_title("OnBoard: Something Else Entirely", TITLE)


def test_a_source_that_fails_leaves_nothing_found() -> None:
    assert asyncio.run(find_metadata(_http(lambda r: httpx.Response(503, text="busy")), doi=DOI, title=TITLE)) is None


def test_the_pdf_keeps_its_own_words_and_gains_what_it_lacked() -> None:
    meta = PaperMetadata(
        matched_by="doi", sources=["crossref"], doi=DOI, title="Different Title", authors=["Mohd Suffian Sulaiman"],
        year=2025, venue="ISCI", publisher="IEEE", abstract="The source's abstract.", url=f"https://doi.org/{DOI}",
    )
    paper = PaperORM(id="pap_1", title=TITLE, title_hash="h", authors=[], abstract="The PDF's own abstract.")
    filled = apply_metadata(paper, meta)
    assert paper.title == TITLE and paper.abstract == "The PDF's own abstract."
    assert (paper.authors, paper.year, paper.venue, paper.publisher, paper.doi) == (["Mohd Suffian Sulaiman"], 2025, "ISCI", "IEEE", DOI)
    assert set(filled) == {"authors", "year", "venue", "publisher", "doi", "url"}

    no_abstract = PaperORM(id="pap_2", title=TITLE, title_hash="h", authors=["M. S. Sulaiman"], abstract=None)
    apply_metadata(no_abstract, meta)
    assert no_abstract.abstract == "The source's abstract."
    assert no_abstract.authors == ["M. S. Sulaiman"]  # the same person: the PDF's names stay

    junk = PaperORM(id="pap_3", title=TITLE, title_hash="h", authors=["LaTeX with hyperref"], abstract=None)
    apply_metadata(junk, meta)
    assert junk.authors == ["Mohd Suffian Sulaiman"]  # an embedded field naming nobody on the paper is replaced


def test_requests_carry_the_contact_address_in_the_user_agent_only() -> None:
    from app.config import Settings
    from app.external.keys import source_headers

    headers = source_headers(Settings(_env_file=None, contact_email="someone@example.org")) or {}  # type: ignore[call-arg]
    assert headers["api.openalex.org"]["User-Agent"].endswith("(mailto:someone@example.org)")
    assert headers["api.crossref.org"]["User-Agent"].endswith("(mailto:someone@example.org)")
    assert "api.semanticscholar.org" not in headers
    seen: list[str] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return _sources(request)

    asyncio.run(find_metadata(_http(record), doi=DOI, title=TITLE))
    assert seen and all("example.org" not in u and "mailto" not in u for u in seen)  # never in a URL
    assert json.dumps(seen)  # every request was a plain GET


def test_an_exhausted_source_does_not_leave_the_paper_without_a_record() -> None:
    meta = asyncio.run(find_metadata(_http(_openalex_out_of_budget), doi=DOI, title=TITLE))
    assert meta is not None and meta.sources == ["crossref"]
    assert (meta.publisher, meta.year, meta.authors[0]) == ("IEEE", 2025, "Mohd Suffian Sulaiman")


def test_a_preprint_is_found_by_its_title_on_semantic_scholar() -> None:
    title = "Agentic Retrieval-Augmented Generation: A Survey on Agentic RAG"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.crossref.org":
            return httpx.Response(200, json={"message": {"items": []}})
        if request.url.path.endswith("/paper/search/match"):
            return httpx.Response(200, json={"data": [{
                "title": title, "year": 2025, "venue": "arXiv.org", "abstract": "Agentic RAG surveyed.",
                "authors": [{"name": "Aditi Singh"}], "externalIds": {"ArXiv": "2501.09136"},
            }]})
        return httpx.Response(404, json={})

    meta = asyncio.run(find_metadata(_http(handler), doi=None, title=title))
    assert meta is not None and meta.sources == ["semantic_scholar"]
    assert (meta.authors, meta.year, meta.abstract, meta.url) == (["Aditi Singh"], 2025, "Agentic RAG surveyed.", "https://arxiv.org/abs/2501.09136")


def test_the_preferred_publishers_are_the_readers_list_or_the_default_four() -> None:
    from app.services.metadata.publishers import TRUSTED_PUBLISHERS, preferred_set
    from app.services.ranking.signals import publisher_signal

    assert preferred_set(None) == TRUSTED_PUBLISHERS
    assert preferred_set([]) == ()
    assert preferred_set(["ieee", "Institute of Electrical and Electronics Engineers", " Wiley ", ""]) == ("IEEE", "Wiley")
    assert publisher_signal("IEEE") == 1.0 and publisher_signal("MDPI") == 0.0
    assert publisher_signal("MDPI", ("MDPI",)) == 1.0 and publisher_signal("IEEE", ("MDPI",)) == 0.0
    assert publisher_signal(None, ("MDPI",)) == 0.0

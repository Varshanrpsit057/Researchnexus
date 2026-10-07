"""Full-text retrieval (remediation Phase 7): legitimate sources only, the
paper's text attached and read everywhere, nothing downloaded twice, and a
paper that can't be read keeps its abstract and says why."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.db.models import PaperORM, WorkspacePaperORM
from app.domain.workspace import (
    AddedBy,
    Grounding,
    ResearchWorkspace,
    WorkspacePaper,
    WorkspacePaperRole,
)
from app.external.http import ExternalHttpClient
from app.services.fulltext.retrieve import coverage_of, retrieve_full_text
from app.services.ingest.abstract_chunks import abstract_chunk_id, ensure_abstract_chunks
from app.services.normalize.canonical import title_hash

ARTICLE_XML = """<article><front><article-meta><abstract><p>We map a brain.</p></abstract></article-meta></front>
<body><sec><title>Introduction</title><p>Brains are wired in circuits of many neurons.</p></sec>
<sec><title>Results</title><p>We found 3016 neurons in the larva.</p></sec></body></article>"""


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path)  # type: ignore[call-arg]


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _paper(db: Session, pid: str = "pap_found", **kw: object) -> PaperORM:
    fields: dict = {"id": pid, "title": "A found paper", "title_hash": title_hash(pid), "source": "discovery", "has_full_text": False}
    return repo.save_paper(db, PaperORM(**(fields | kw)))


def _http(routes: dict[str, httpx.Response | object], seen: list[str] | None = None) -> ExternalHttpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if seen is not None:
            seen.append(url)
        for prefix, resp in routes.items():
            if url.startswith(prefix):
                return resp(request) if callable(resp) else resp  # type: ignore[return-value]
        return httpx.Response(404)

    return ExternalHttpClient(transport=httpx.MockTransport(handler), sleep=_no_sleep)


async def _no_sleep(_s: float) -> None:
    return None


def _work(*locations: dict, pmcid: str | None = None) -> httpx.Response:
    return httpx.Response(200, json={"id": "https://openalex.org/W1", "ids": {"pmcid": pmcid} if pmcid else {}, "locations": list(locations)})


def test_an_arxiv_paper_is_read_from_its_pdf_and_every_workspace_reads_it(
    db: Session, settings: Settings, normal_paper_pdf_bytes: bytes
) -> None:
    _paper(db, arxiv_id="2005.11401", abstract="Retrieval helps generation.")
    ensure_abstract_chunks(db, ["pap_found"])
    repo.create_user(db, user_id="u1", email="u@example.com")
    _paper(db, "pap_seed", source="upload", has_full_text=True)
    repo.create_workspace(
        db,
        ResearchWorkspace(
            workspace_id="ws1", owner_id="u1", title="W", seed_paper_id="pap_seed", seed_profile_id="prof",
            papers=[
                WorkspacePaper(workspace_id="ws1", paper_id="pap_seed", added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED),
                WorkspacePaper(workspace_id="ws1", paper_id="pap_found", added_by=AddedBy.TRAIL, role=WorkspacePaperRole.RELATED, grounding=Grounding.ABSTRACT),
            ],
        ),
    )
    http = _http({"https://arxiv.org/pdf/2005.11401": httpx.Response(200, content=normal_paper_pdf_bytes)})

    outcome = asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http))

    assert (outcome.status, outcome.source) == ("retrieved", "arxiv") and outcome.chunks > 0
    paper = repo.get_paper(db, "pap_found")
    assert paper is not None and paper.has_full_text and paper.sections and Path(paper.pdf_path or "").exists()
    assert paper.title == "A found paper"  # the discovery record's metadata stays
    chunk_ids = [c.chunk_id for c in repo.get_chunks_for_paper(db, "pap_found")]
    assert abstract_chunk_id("pap_found") in chunk_ids and len(chunk_ids) > 1  # the abstract past answers cite stays
    member = db.get(WorkspacePaperORM, ("ws1", "pap_found"))
    assert member is not None and member.grounding == "full_text"
    assert coverage_of(paper)["state"] == "full_text" and coverage_of(paper)["source"] == "arxiv"


def test_a_retrieved_paper_is_never_downloaded_again(db: Session, settings: Settings, normal_paper_pdf_bytes: bytes) -> None:
    _paper(db, arxiv_id="2005.11401")
    seen: list[str] = []
    http = _http({"https://arxiv.org/pdf/": httpx.Response(200, content=normal_paper_pdf_bytes)}, seen)
    asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http))
    again = asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http, force=True))
    assert again.status == "already" and len(seen) == 1


def test_an_open_access_copy_is_found_through_openalex_and_a_closed_one_is_ignored(
    db: Session, settings: Settings, normal_paper_pdf_bytes: bytes
) -> None:
    _paper(db, doi="10.3390/app13053120")
    seen: list[str] = []
    http = _http(
        {
            "https://api.openalex.org/works/https://doi.org/10.3390/app13053120": _work(
                {"is_oa": False, "pdf_url": "https://link.springer.com/content/pdf/closed.pdf"},
                {"is_oa": True, "pdf_url": "https://www.mdpi.com/2076-3417/13/5/3120/pdf"},
            ),
            "https://www.mdpi.com/": httpx.Response(200, content=normal_paper_pdf_bytes),
        },
        seen,
    )
    outcome = asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http))
    assert (outcome.status, outcome.source) == ("retrieved", "openalex")
    assert not any("closed.pdf" in u for u in seen)


def test_pubmed_central_is_read_from_europe_pmcs_full_text_xml(db: Session, settings: Settings) -> None:
    _paper(db, doi="10.1101/2022.11.28.518219")
    http = _http(
        {
            "https://api.openalex.org/works/": _work(pmcid="https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7614541"),
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC7614541/fullTextXML": httpx.Response(200, text=ARTICLE_XML),
        }
    )
    outcome = asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http))
    assert (outcome.status, outcome.source) == ("retrieved", "europepmc")
    chunks = repo.get_chunks_for_paper(db, "pap_found")
    assert any("3016 neurons" in c.text for c in chunks)
    assert all(c.page is None for c in chunks)  # XML has no pages, and none is invented


def test_an_open_copy_on_a_small_journals_site_is_retrieved(
    db: Session, settings: Settings, normal_paper_pdf_bytes: bytes
) -> None:
    # the reader's decision (2026-10-02): any public host an API names as an open copy
    _paper(db, doi="10.56536/jicet.v5i1.193", abstract="An abstract.")
    http = _http(
        {
            "https://api.openalex.org/works/": _work({"is_oa": True, "pdf_url": "https://jicet.org/index.php/j/article/download/193/1"}),
            "https://jicet.org/": httpx.Response(200, content=normal_paper_pdf_bytes),
        }
    )
    outcome = asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http))
    assert outcome.status == "retrieved"
    paper = repo.get_paper(db, "pap_found")
    assert paper is not None and coverage_of(paper)["state"] == "full_text"


def test_a_doi_that_resolves_to_a_publishers_sign_in_page_is_a_failure_with_its_reason(db: Session, settings: Settings) -> None:
    # a paywalled article: the DOI leads to the publisher's page, not a PDF -- said, never disguised
    _paper(db, doi="10.22214/ijraset.2024.1", abstract="An abstract.")
    http = _http(
        {
            "https://api.openalex.org/works/": _work({"is_oa": True, "pdf_url": "https://doi.org/10.22214/ijraset.2024.1"}),
            "https://doi.org/": httpx.Response(302, headers={"location": "https://www.ijraset.com/fileserve.php?FID=1"}),
            "https://www.ijraset.com/": httpx.Response(200, text="<html>Sign in</html>", headers={"content-type": "text/html"}),
        }
    )
    outcome = asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http))
    assert (outcome.status, outcome.reason) == ("failed", "not_a_pdf")
    paper = repo.get_paper(db, "pap_found")
    assert paper is not None and not paper.has_full_text and coverage_of(paper)["has_abstract"] is True


def test_a_copy_that_cant_be_read_is_a_failure_with_its_reason_and_the_abstract_stays(db: Session, settings: Settings) -> None:
    _paper(db, arxiv_id="2101.00001", abstract="Still readable.")
    http = _http({"https://arxiv.org/pdf/": httpx.Response(200, text="<html>Not available</html>")})
    outcome = asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http))
    assert (outcome.status, outcome.reason) == ("failed", "not_a_pdf")
    paper = repo.get_paper(db, "pap_found")
    assert paper is not None and not paper.has_full_text
    cov = coverage_of(paper)
    assert (cov["state"], cov["reason"], cov["has_abstract"], cov["retrievable"]) == ("retrieval_failed", "not_a_pdf", True, True)


def test_when_one_copy_cant_be_read_the_next_is_tried(
    db: Session, settings: Settings, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.fulltext.retrieve as retrieve

    _paper(db, arxiv_id="2101.00001", doi="10.3390/app13053120")
    http = _http(
        {
            "https://arxiv.org/pdf/": httpx.Response(200, content=b"%PDF-1.4 a file the parser chokes on"),
            "https://api.openalex.org/works/": _work({"is_oa": True, "pdf_url": "https://www.mdpi.com/2076-3417/13/5/3120/pdf"}),
            "https://www.mdpi.com/": httpx.Response(200, content=normal_paper_pdf_bytes),
        }
    )
    real = retrieve.parse_pdf

    def choke_on_the_first(paper_id: str, data: bytes, filename: str, s: Settings, **kw: object) -> object:
        if b"chokes" in data:
            raise RuntimeError("an unexpected parser failure")
        return real(paper_id, data, filename, s)

    monkeypatch.setattr(retrieve, "parse_pdf", choke_on_the_first)
    outcome = asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http))
    assert (outcome.status, outcome.source) == ("retrieved", "openalex")


def test_a_negative_answer_is_believed_for_a_while_unless_asked_again(db: Session, settings: Settings) -> None:
    _paper(db, doi="10.1/none")
    seen: list[str] = []
    http = _http({"https://api.openalex.org/works/": _work(), "https://api.semanticscholar.org/": httpx.Response(404)}, seen)
    assert asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http)).reason == "no_open_access_copy"
    asked = len(seen)
    assert asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http)).status == "cached"
    assert len(seen) == asked  # not asked again within the week
    asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http, force=True))
    assert len(seen) > asked
    paper = repo.get_paper(db, "pap_found")
    assert paper is not None
    paper.fulltext_checked_at = datetime.now(timezone.utc) - timedelta(days=8)
    db.commit()
    before = len(seen)
    asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http))
    assert len(seen) > before  # a week on, an automatic run looks again


def test_a_source_that_cant_be_asked_is_a_failure_not_an_answer(db: Session, settings: Settings) -> None:
    _paper(db, doi="10.1/x")
    http = _http({"https://api.openalex.org/": httpx.Response(503), "https://api.semanticscholar.org/": httpx.Response(503)})
    outcome = asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http))
    assert (outcome.status, outcome.reason) == ("failed", "lookup_failed")


def test_a_paper_with_no_identifier_and_no_abstract_has_no_text(db: Session, settings: Settings) -> None:
    _paper(db)
    outcome = asyncio.run(retrieve_full_text(db, "pap_found", settings, http=_http({})))
    assert (outcome.status, outcome.reason) == ("unavailable", "no_identifier")
    paper = repo.get_paper(db, "pap_found")
    assert paper is not None and coverage_of(paper)["state"] == "no_text"


def test_a_paper_is_read_whole_without_its_abstract_twice() -> None:
    from app.domain.chunk import ChunkKind, PaperChunk
    from app.services.ingest.abstract_chunks import for_reading

    def chunk(cid: str, kind: ChunkKind) -> PaperChunk:
        return PaperChunk(chunk_id=cid, paper_id="p", char_start=0, char_end=1, kind=kind, text="t", token_count=1)

    search = chunk(abstract_chunk_id("p"), ChunkKind.ABSTRACT)
    pdf_abstract, body = chunk("chk_p_1", ChunkKind.ABSTRACT), chunk("chk_p_2", ChunkKind.BODY)
    assert for_reading("p", [search, pdf_abstract, body]) == [pdf_abstract, body]
    # a PDF without an abstract section: the one from search is the paper's abstract
    assert for_reading("p", [search, body]) == [search, body]


def test_unpaywall_finds_the_open_copy_openalex_doesnt_know(
    db: Session, tmp_path: Path, normal_paper_pdf_bytes: bytes
) -> None:
    # remediation, 2026-10-02: Unpaywall tracks where articles are legally free (it needs a contact email)
    settings = Settings(_env_file=None, data_dir=tmp_path, contact_email="reader@example.org")  # type: ignore[call-arg]
    _paper(db, doi="10.1109/access.2023.1", abstract="An abstract.")
    seen: list[str] = []
    http = _http(
        {
            "https://api.openalex.org/works/": _work(),  # no open location known
            "https://api.unpaywall.org/v2/10.1109/access.2023.1": httpx.Response(
                200, json={"best_oa_location": {"url_for_pdf": "https://repository.example.edu/bitstream/1/paper.pdf"}, "oa_locations": []}
            ),
            "https://repository.example.edu/": httpx.Response(200, content=normal_paper_pdf_bytes),
        },
        seen,
    )
    outcome = asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http))
    assert (outcome.status, outcome.source) == ("retrieved", "unpaywall")
    unpaywall = next(u for u in seen if "unpaywall" in u)
    assert "email=reader%40example.org" in unpaywall  # its API requires the address; nothing else gets it
    assert all("example.org" not in u for u in seen if "unpaywall" not in u)


def test_without_a_contact_email_unpaywall_is_not_asked(db: Session, settings: Settings) -> None:
    _paper(db, doi="10.1109/access.2023.2", abstract="An abstract.")
    seen: list[str] = []
    asyncio.run(retrieve_full_text(db, "pap_found", settings, http=_http({"https://api.openalex.org/works/": _work()}, seen)))
    assert not any("unpaywall" in u for u in seen)


def test_core_finds_a_repository_copy_by_the_papers_exact_title(
    db: Session, settings: Settings, normal_paper_pdf_bytes: bytes
) -> None:
    _paper(db, title="Smart Campus Transit Tracking", abstract="An abstract.")  # no DOI or arXiv id
    http = _http(
        {
            "https://api.core.ac.uk/v3/search/works/": httpx.Response(200, json={"results": [
                {"id": 1, "title": "A Different Paper", "downloadUrl": "https://core.ac.uk/download/1.pdf"},
                {"id": 2, "title": "Smart Campus Transit Tracking", "downloadUrl": "https://core.ac.uk/download/2.pdf"},
            ]}),
            "https://core.ac.uk/download/2.pdf": httpx.Response(200, content=normal_paper_pdf_bytes),
        }
    )
    outcome = asyncio.run(retrieve_full_text(db, "pap_found", settings, http=http))
    assert (outcome.status, outcome.source) == ("retrieved", "core")
    paper = repo.get_paper(db, "pap_found")
    assert paper is not None and paper.fulltext_url == "https://core.ac.uk/download/2.pdf"

"""`GET /workspaces/{id}/citations` -- the workspace's citation ledger: every
paper with its reference, its relation to the seed, and every place the
workspace cites it, each with the passage it rests on."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_session_factory
from app.domain.candidate import (
    CitationRelationship,
    DiscoveryStrategy,
    NormalizedCandidate,
    SearchRun,
)
from app.domain.chat import ChatMessage, ChatRole, ChatSession
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.citation import Claim
from app.domain.comparison import Comparison, ComparisonCell, ComparisonRow, ComparisonSchema
from app.domain.direction import ResearchDirection
from app.domain.gap import GapEvidence, GapType, ResearchGap
from app.domain.profile import Confidence, ProfileField, ResearchProfile, SourceSpan
from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge
from app.main import create_app
from app.services.normalize.canonical import title_hash
from tests.auth_helpers import sign_in

SEED_REFERENCES: list[dict[str, Any]] = [
    {"order": 0, "raw_text": "[1] K. Guu et al. REALM: Retrieval-augmented language model pre-training. ICML."},
    {"order": 1, "raw_text": "[2] A reference the trail never resolved. Conf."},
]
PASSAGE = "REALM augments language model pre-training with a latent knowledge retriever."


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-jwt-secret",
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _token(c: TestClient, email: str = "r@example.com") -> str:
    return sign_in(c, email)


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def _seed_papers_and_run() -> str:
    """The seed (full text, with a bibliography), the paper its first reference
    resolves to, and the discovery run whose trail matched them. Returns that paper's id."""
    from app.db.models import PaperORM

    db = get_session_factory()()
    try:
        repo.save_paper(
            db,
            PaperORM(
                id="pap_seed", title="Retrieval-Augmented Generation", title_hash=title_hash("seed"), has_full_text=True,
                authors=["Patrick Lewis", "Ethan Perez"], year=2020, venue="NeurIPS", doi="10.5555/rag", references=SEED_REFERENCES,
            ),
        )
        repo.upsert_profile(
            db,
            ResearchProfile(
                profile_id="prof_seed", paper_id="pap_seed", title="Retrieval-Augmented Generation", abstract="ab",
                domain=ProfileField(value="RAG"), research_problem=ProfileField(value="grounding"),
            ),
        )
        realm = repo.upsert_discovered_paper(db, NormalizedCandidate(title="REALM", title_hash=title_hash("REALM"), year=2020, authors=["Kelvin Guu"]))
        repo.save_chunks(
            db,
            [PaperChunk(chunk_id="chk_realm_0", paper_id=realm, section="Abstract", char_start=0, char_end=len(PASSAGE), text=PASSAGE, token_count=11, kind=ChunkKind.ABSTRACT)],
        )
        repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id="pap_seed"))
        repo.add_search_candidate(
            db, candidate_id="cand_1", run_id="run_1", paper_id=realm, discovery_methods=[DiscoveryStrategy.CITATION],
            possible_duplicate_of=None, provenance={}, citation_relationship=CitationRelationship.CITED_BY_SEED, citation_hops=1,
        )
        repo.save_trail_edges(
            db, "run_1",
            [
                TrailEdge(
                    edge_id="edge_1", run_id="run_1", source_paper_id="pap_seed", target_paper_id=realm,
                    relationship_type=RelationshipType.FOUNDATIONAL, detection_method=DetectionMethod.RULE,
                    evidence=[Evidence(span=SourceSpan(paper_id="pap_seed", section="References", quote=SEED_REFERENCES[0]["raw_text"]), role="seed_reference")],
                    confidence=Confidence.MEDIUM,
                )
            ],
        )
        return realm
    finally:
        db.close()


def _cite_it(wid: str, owner: str, realm: str) -> None:
    """The workspace cites the paper four ways: a chat answer, a comparison
    cell, a gap and its direction -- plus a claim whose message is gone."""
    db = get_session_factory()()
    try:
        repo.create_chat_session(db, ChatSession(session_id="cs_1", workspace_id=wid, owner_id=owner, title="Q"))
        repo.add_chat_message(db, ChatMessage(message_id="msg_1", session_id="cs_1", role=ChatRole.ASSISTANT, content="REALM retrieves while it pre-trains."))
        repo.save_claims(
            db,
            [
                Claim(claim_id="clm_msg_1_0", workspace_id=wid, artefact_kind="answer", artefact_id="msg_1",
                      sentence="REALM retrieves while it pre-trains.", supporting_chunk_ids=["chk_realm_0"], supporting_paper_ids=[realm], is_supported=True),
                Claim(claim_id="clm_msg_gone_0", workspace_id=wid, artefact_kind="answer", artefact_id="msg_gone",
                      sentence="An answer that was deleted.", supporting_chunk_ids=["chk_realm_0"], supporting_paper_ids=[realm], is_supported=True),
            ],
        )
        span = SourceSpan(paper_id=realm, section="Abstract", char_start=0, char_end=40, quote="a latent knowledge retriever")
        old = datetime.now(timezone.utc) - timedelta(days=1)
        for cid, value, at in (("cmp_old", "an older reading", old), ("cmp_new", "latent knowledge retrieval", datetime.now(timezone.utc))):
            repo.save_comparison(
                db,
                Comparison(
                    comparison_id=cid, workspace_id=wid, column_schema=ComparisonSchema(columns=["method"]), paper_ids=["pap_seed", realm],
                    rows=[ComparisonRow(paper_id=realm, cells={"method": ComparisonCell(column="method", text=value, span=span, grounding="abstract")})],
                    created_at=at,
                ),
                owner_id=owner,
            )
        gap = ResearchGap(
            gap_id="gap_1", workspace_id=wid, statement="No paper here pairs retrieval with pre-training evaluation.",
            gap_type=GapType.METHOD_GAP, supporting_papers=["pap_seed", realm],
            supporting_evidence=[GapEvidence(paper_id=realm, span=span, role="shared_context")],
            confidence=Confidence.MEDIUM, self_support_passed=True, user_state="accepted",
        )
        repo.save_gaps(db, wid, [gap], owner_id=owner)
        repo.save_directions(
            db, wid,
            [
                ResearchDirection(
                    direction_id="dir_1", workspace_id=wid, gap_id="gap_1", proposal="Evaluate retrieval during pre-training.",
                    motivation="m", supporting_evidence=list(gap.supporting_evidence), related_papers=["pap_seed", realm],
                    kind="evidence_backed_inference",
                )
            ],
            owner_id=owner,
        )
    finally:
        db.close()


def _workspace(c: TestClient, token: str) -> tuple[str, str, str]:
    realm = _seed_papers_and_run()
    ws = c.post("/api/v1/workspaces", json={"title": "RAG", "seed_paper_id": "pap_seed", "import_run_id": "run_1"}, headers=_h(token))
    assert ws.status_code == 201, ws.text
    wid = ws.json()["workspace_id"]
    assert c.post(f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": [realm]}, headers=_h(token)).status_code in (200, 201)
    return wid, ws.json()["owner_id"], realm


def test_the_ledger_needs_auth_and_the_owner(tmp_path: Path) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, _, _ = _workspace(c, token)
    assert c.get(f"/api/v1/workspaces/{wid}/citations").status_code == 401
    assert c.get(f"/api/v1/workspaces/{wid}/citations", headers=_h(_token(c, "other@example.com"))).status_code == 404


def test_every_paper_with_its_reference_its_seed_relation_and_where_the_workspace_cites_it(tmp_path: Path) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, owner, realm = _workspace(c, token)
    _cite_it(wid, owner, realm)

    r = c.get(f"/api/v1/workspaces/{wid}/citations", headers=_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["paper_id"] for p in body["papers"]] == ["pap_seed", realm]
    seed, cited = body["papers"]

    # the seed: its own reference, its bibliography's size, no relation to itself
    assert seed["role"] == "seed" and seed["grounding"] == "full_text"
    assert seed["reference"]["resolved_from"] == "crossref"
    assert seed["reference"]["formatted"]["apa"].startswith("Lewis, P., & Perez, E. (2020). Retrieval-Augmented Generation.")
    assert seed["reference"]["formatted"]["ieee"].startswith("[1] ")
    assert seed["reference_count"] == 2
    assert seed["seed_relation"] is None
    assert seed["uses"] == [] or all(u["kind"] != "answer" for u in seed["uses"])

    # the paper the seed cites: what discovery and the trail know about it
    assert cited["role"] == "member" and cited["grounding"] == "abstract"
    assert cited["title"] == "REALM" and cited["year"] == 2020 and cited["authors"] == ["Kelvin Guu"]
    assert cited["seed_relation"] == "cited_by_seed"
    assert cited["reference_count"] is None
    assert cited["reference"]["formatted"]["ieee"].startswith("[2] ")
    assert [(e["type"], e["other_paper_id"], e["direction"]) for e in cited["connections"]] == [("FOUNDATIONAL", "pap_seed", "in")]

    # every place the workspace cites it, each with its own passage -- and only live ones
    assert cited["counts"] == {"answer": 1, "comparison": 1, "gap": 1, "direction": 1}
    by_kind = {u["kind"]: u for u in cited["uses"]}
    answer = by_kind["answer"]
    assert answer["text"] == "REALM retrieves while it pre-trains."
    assert answer["quote"] == PASSAGE and answer["section"] == "Abstract"
    # verbatim, uncut, with the sentence it rests on marked (remediation Phase 13)
    assert (answer["cut_before"], answer["cut_after"], answer["highlight"]) == (False, False, [0, len(PASSAGE)])
    assert answer["session_id"] == "cs_1" and answer["artefact_id"] == "msg_1"
    comparison = by_kind["comparison"]
    assert (comparison["field"], comparison["text"], comparison["quote"]) == ("method", "latent knowledge retrieval", "a latent knowledge retriever")
    assert comparison["artefact_id"] == "cmp_new"  # only the comparison on screen, not an older one
    assert (by_kind["gap"]["artefact_id"], by_kind["gap"]["state"]) == ("gap_1", "accepted")
    assert by_kind["direction"]["text"] == "Evaluate retrieval during pre-training."
    assert all(u["created_at"].endswith(("Z", "+00:00")) for u in cited["uses"])

    # the seed's own bibliography, matched to the papers the trail resolved
    assert body["seed_references"] == [
        {"order": 0, "text": SEED_REFERENCES[0]["raw_text"], "paper_id": realm, "in_workspace": True},
        {"order": 1, "text": SEED_REFERENCES[1]["raw_text"], "paper_id": None, "in_workspace": False},
    ]


def test_a_workspace_nothing_cites_yet_still_lists_its_papers(tmp_path: Path) -> None:
    c = _client(tmp_path)
    token = _token(c)
    wid, _, realm = _workspace(c, token)
    body = c.get(f"/api/v1/workspaces/{wid}/citations", headers=_h(token)).json()
    assert [p["paper_id"] for p in body["papers"]] == ["pap_seed", realm]
    assert all(p["uses"] == [] and sum(p["counts"].values()) == 0 for p in body["papers"])

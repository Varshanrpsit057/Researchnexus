from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_session_factory
from app.domain.candidate import NormalizedCandidate
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.profile import ProfileField, ResearchProfile
from app.domain.user import LlmCapabilities, LlmProvider, LlmTestResult
from app.main import create_app
from app.services.normalize.canonical import title_hash
from tests.auth_helpers import sign_in


def _make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-jwt-secret",
        key_vault_secret=Fernet.generate_key().decode(),
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _token(client: TestClient, email: str = "r@example.com") -> str:
    return sign_in(client, email)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_workspace(client: TestClient, token: str) -> str:
    factory = get_session_factory()
    db = factory()
    try:
        from app.db.models import PaperORM

        repo.save_paper(db, PaperORM(id="pap_seed", title="Dense Retrieval", title_hash=title_hash("seed"), has_full_text=True, authors=["Patrick Lewis"], year=2020, doi="10.1/seed"))
        repo.upsert_profile(
            db,
            ResearchProfile(
                profile_id="prof_seed", paper_id="pap_seed", title="Dense Retrieval",
                abstract="A study of dense retrieval.", domain=ProfileField(value="IR"),
                research_problem=ProfileField(value="retrieval quality"),
            ),
        )
        repo.save_chunks(db, [PaperChunk(chunk_id="chk_seed_0", paper_id="pap_seed", section="Results", page=3, char_start=0, char_end=54, kind=ChunkKind.BODY, text="Dense retrieval improves recall on question answering.", token_count=7)])
        p2 = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Reranking", title_hash=title_hash("Reranking"), authors=["Ethan Perez"], year=2021))
        repo.save_chunks(db, [PaperChunk(chunk_id="chk_p2_0", paper_id=p2, section="Method", page=2, char_start=0, char_end=52, kind=ChunkKind.BODY, text="Cross encoder reranking raises precision of passages.", token_count=7)])
    finally:
        db.close()

    ws = client.post("/api/v1/workspaces", json={"title": "RAG", "seed_paper_id": "pap_seed"}, headers=_h(token))
    assert ws.status_code == 201, ws.text
    wid = ws.json()["workspace_id"]
    add = client.post(f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": [p2]}, headers=_h(token))
    assert add.status_code == 201, add.text
    return wid


def _mock_llm(monkeypatch: pytest.MonkeyPatch, router) -> None:
    import app.llm.session as session_module

    def fake_get_llm_client(provider: object):  # noqa: ANN202
        from app.llm.providers.openai_compat import OpenAiCompatClient

        return OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(router)))

    monkeypatch.setattr(session_module, "get_llm_client", fake_get_llm_client)


def _save_key(client: TestClient, token: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.routers.settings_keys as sk

    async def _fake_probe(provider: object, api_key: str, *, transport: object = None) -> LlmTestResult:
        return LlmTestResult(success=True, latency_ms=1, capabilities=LlmCapabilities(json_mode=True, context_tokens=8192, streaming=True))

    monkeypatch.setattr(sk, "probe", _fake_probe)
    r = client.put("/api/v1/settings/llm-keys", json={"provider": "groq", "api_key": "sk-x"}, headers=_h(token))
    assert r.status_code == 200


def _rag_router(*, generate: dict | str, verify: dict, filt: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "copy VERBATIM" in body:
            payload: object = filt if filt is not None else {
                "chunks": [
                    {"chunk_id": "chk_seed_0", "relevant_text": "Dense retrieval improves recall on question answering."},
                    {"chunk_id": "chk_p2_0", "relevant_text": "Cross encoder reranking raises precision of passages."},
                ]
            }
        elif "ONLY the numbered CONTEXT" in body:
            payload = generate
        elif "fully supports the statement" in body:
            payload = verify
        else:
            payload = {}
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 30, "completion_tokens": 12}})

    return handler


def test_chat_requires_key_and_tenant(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    wid = _seed_workspace(client, token)
    assert client.post(f"/api/v1/workspaces/{wid}/chat", json={"message": "hi"}, headers=_h(token)).status_code == 409
    other = _token(client, "intruder@example.com")
    assert client.post(f"/api/v1/workspaces/{wid}/chat", json={"message": "hi"}, headers=_h(other)).status_code == 404


def test_chat_non_stream_returns_grounded_answer_with_claims(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    wid = _seed_workspace(client, token)
    _save_key(client, token, monkeypatch)
    _mock_llm(
        monkeypatch,
        _rag_router(
            generate={"sentences": [
                {"text": "Dense retrieval improves recall.", "chunk_ids": ["chk_seed_0"]},
                {"text": "Reranking raises precision of passages.", "chunk_ids": ["chk_p2_0"]},
            ]},
            verify={"results": [{"index": 0, "supported": True}, {"index": 1, "supported": True}]},
        ),
    )
    r = client.post(f"/api/v1/workspaces/{wid}/chat", json={"message": "How is retrieval quality improved?"}, headers=_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answerable"] is True
    assert body["text"]
    assert len(body["claims"]) == 2
    for c in body["claims"]:
        assert c["supporting_chunk_ids"] and c["supporting_paper_ids"]
        assert c["supporting_chunk_ids"][0] in {"chk_seed_0", "chk_p2_0"}
    assert body["faithfulness"] is not None

    # persisted + retrievable
    sid = body["session_id"]
    hist = client.get(f"/api/v1/workspaces/{wid}/chat/sessions/{sid}", headers=_h(token)).json()
    assert [m["role"] for m in hist["messages"]] == ["user", "assistant"]
    assert len(hist["messages"][1]["claims"]) == 2


def test_chat_sse_emits_token_citation_usage_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    wid = _seed_workspace(client, token)
    _save_key(client, token, monkeypatch)
    _mock_llm(
        monkeypatch,
        _rag_router(
            generate={"sentences": [{"text": "Dense retrieval improves recall.", "chunk_ids": ["chk_seed_0"]}]},
            verify={"results": [{"index": 0, "supported": True}]},
        ),
    )
    r = client.post(
        f"/api/v1/workspaces/{wid}/chat",
        json={"message": "How is retrieval quality improved?"},
        headers={**_h(token), "Accept": "text/event-stream"},
    )
    assert r.status_code == 200
    stream = r.text
    assert "event: token" in stream
    assert "event: citation" in stream
    assert "event: usage" in stream
    assert "event: done" in stream
    cite_line = next(ln for ln in stream.splitlines() if ln.startswith("data: ") and "chunk_id" in ln)
    cite = json.loads(cite_line[len("data: "):])
    assert cite["chunk_id"] == "chk_seed_0" and cite["section"] == "Results"


def test_chat_not_answerable_when_evidence_is_thin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    wid = _seed_workspace(client, token)
    _save_key(client, token, monkeypatch)
    _mock_llm(
        monkeypatch,
        _rag_router(
            generate={"sentences": []},
            verify={"results": []},
            filt={"chunks": [{"chunk_id": "chk_seed_0", "relevant_text": "Dense retrieval improves recall on question answering."}]},
        ),
    )
    r = client.post(f"/api/v1/workspaces/{wid}/chat", json={"message": "What learning rate did pretraining use?"}, headers=_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["answerable"] is False
    assert body["suggestion"] and body["claims"] == []


def test_summary_returns_supported_claims(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    wid = _seed_workspace(client, token)
    _save_key(client, token, monkeypatch)
    _mock_llm(
        monkeypatch,
        _rag_router(
            generate={"sentences": [{"text": "Dense retrieval improves recall.", "chunk_ids": ["chk_seed_0"]}]},
            verify={"results": [{"index": 0, "supported": True}]},
        ),
    )
    r = client.post(f"/api/v1/workspaces/{wid}/summary", json={"scope": "all", "length": "short"}, headers=_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "recall" in body["text"]
    assert len(body["claims"]) == 1 and body["claims"][0]["artefact_kind"] == "summary"
    assert client.post(f"/api/v1/workspaces/{wid}/summary", json={}, headers=_h(_token(client, "nokey@example.com"))).status_code == 404


def test_keypoints_returns_spans(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    wid = _seed_workspace(client, token)
    _save_key(client, token, monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {"points": [{"facet": "result", "text": "Dense retrieval improves recall on question answering.", "chunk_id": "chk_seed_0"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 5, "completion_tokens": 5}})

    _mock_llm(monkeypatch, handler)
    r = client.post(f"/api/v1/workspaces/{wid}/keypoints", json={"paper_ids": ["pap_seed"]}, headers=_h(token))
    assert r.status_code == 200, r.text
    papers = r.json()["papers"]
    seed = next(p for p in papers if p["paper_id"] == "pap_seed")
    assert seed["points"][0]["facet"] == "result"
    assert seed["points"][0]["span"]["paper_id"] == "pap_seed" and seed["points"][0]["span"]["page"] == 3


def test_citations_are_deterministic_and_need_no_key(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    wid = _seed_workspace(client, token)

    r = client.post(f"/api/v1/workspaces/{wid}/citations", json={"paper_ids": "all", "formats": ["apa", "bibtex"]}, headers=_h(token))
    assert r.status_code == 200, r.text
    body = r.json()
    by_paper = {c["paper_id"]: c for c in body["citations"]}
    assert by_paper["pap_seed"]["resolved_from"] == "crossref"
    assert by_paper["pap_seed"]["formatted"]["apa"].startswith("Lewis, P. (2020).")
    assert "ieee" not in by_paper["pap_seed"]["formatted"]  # only requested formats

    # deterministic across calls
    r2 = client.post(f"/api/v1/workspaces/{wid}/citations", json={"paper_ids": "all", "formats": ["apa", "bibtex"]}, headers=_h(token))
    assert r2.json() == body

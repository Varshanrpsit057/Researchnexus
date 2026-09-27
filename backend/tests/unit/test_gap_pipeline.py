from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.db.models import PaperORM
from app.domain.gap import GapType, GapUserState
from app.domain.profile import Confidence, ProfileField, ProfileList, ResearchProfile, SourceSpan
from app.domain.user import LlmProvider
from app.domain.workspace import AddedBy, ResearchWorkspace, WorkspacePaper, WorkspacePaperRole
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.gaps.pipeline import GapBuildOptions, build_gaps
from app.services.normalize.canonical import title_hash


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(conn: object, _rec: object) -> None:
        cur = conn.cursor()  # type: ignore[attr-defined]
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, database_url="sqlite://")  # type: ignore[call-arg]


def _paper(db: Session, pid: str, *, year: int, **facets: list[str]) -> None:
    db.add(PaperORM(id=pid, title=pid.upper(), title_hash=title_hash(pid), year=year))
    db.commit()
    kw: dict = {
        "profile_id": f"prof_{pid}", "paper_id": pid, "title": pid.upper(), "abstract": "ab",
        "domain": ProfileField(value="IR"),
        "research_problem": ProfileField(
            value=facets.get("problem", ["retrieval"])[0],
            source_span=SourceSpan(paper_id=pid, section="Intro", char_start=1, char_end=9, quote=facets.get("problem", ["retrieval"])[0]),
        ),
    }
    for key, attr in (("methods", "methods"), ("datasets", "datasets"), ("limitations", "limitations")):
        vals = facets.get(key, [])
        if vals:
            kw[attr] = ProfileList(items=[
                ProfileField(value=v, source_span=SourceSpan(paper_id=pid, section="Body", char_start=10, char_end=20, quote=v))
                for v in vals
            ])
    repo.upsert_profile(db, ResearchProfile(**kw))


@pytest.fixture()
def workspace(db: Session) -> ResearchWorkspace:
    repo.create_user(db, user_id="usr_1", email="u@e.com")
    _paper(db, "p1", year=2022, problem=["dense retrieval"], methods=["bm25"], limitations=["English only"])
    _paper(db, "p2", year=2022, problem=["dense retrieval"], methods=["tf-idf"], limitations=["English only"])
    _paper(db, "p3", year=2022, problem=["dense retrieval"], methods=["contrastive pretraining"])
    ws = ResearchWorkspace(
        workspace_id="ws_1", owner_id="usr_1", title="W", seed_paper_id="p1", seed_profile_id="prof_p1",
        papers=[
            WorkspacePaper(workspace_id="ws_1", paper_id="p1", added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED),
            WorkspacePaper(workspace_id="ws_1", paper_id="p2", added_by=AddedBy.TRAIL),
            WorkspacePaper(workspace_id="ws_1", paper_id="p3", added_by=AddedBy.TRAIL),
        ],
    )
    repo.create_workspace(db, ws)
    return ws


def _session(*, articulate_ok: bool = True, self_support: bool = True, profile_ok: bool = True) -> LlmSession:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        if "scientific paper analysis assistant" in body:
            if not profile_ok:
                return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}})
            # quotes copied from the abstract the pipeline sent
            payload: object = {
                "domain": {"value": "IR", "quote": None},
                "research_problem": {"value": "dense retrieval", "quote": "dense retrieval"},
                "limitations": {"items": [{"value": "English only", "quote": "English only"}]},
            }
        elif "phrase a research gap" in body:
            if not articulate_ok:
                payload = {"statement": "The papers ignore quantum annealing.", "why_unaddressed": "quantum annealing untried", "proposed_direction": "use quantum annealing"}
            elif "limitation" in body and "English only" in body:
                payload = {
                    "statement": "Two papers report the same English only limitation and none of them resolves it.",
                    "why_unaddressed": "The English only limitation is stated but not addressed.",
                    "proposed_direction": "Extend the setting beyond English only.",
                }
            elif "contrastive pretraining" in body:
                payload = {
                    "statement": "No workspace paper applies contrastive pretraining to dense retrieval.",
                    "why_unaddressed": "The papers study dense retrieval but none adopt contrastive pretraining.",
                    "proposed_direction": "Apply contrastive pretraining to the shared setting.",
                }
            else:
                # phrase strictly from the facts/evidence terms the pipeline sent
                payload = {"statement": "The workspace papers share no common value on this facet.", "why_unaddressed": "Each paper differs on it.", "proposed_direction": "Adopt a shared choice."}
        elif "fully supports the statement" in body:
            payload = {"results": [{"index": 0, "supported": self_support}]}
        else:
            payload = {}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}], "usage": {"prompt_tokens": 5, "completion_tokens": 3}})

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x", model="groq/x", provider=LlmProvider.GROQ,
    )


def _run(db, ws, settings, session, **kw):
    return asyncio.run(build_gaps(db, workspace=ws, options=GapBuildOptions(**kw), session=session, settings=settings))


def test_pipeline_surfaces_evidence_grounded_gaps(db, workspace, settings) -> None:
    res = _run(db, workspace, settings, _session())
    assert res.gap_count >= 1
    gaps = repo.get_gaps(db, "ws_1")
    assert all(len(g.supporting_papers) >= 2 for g in gaps)
    assert all(g.supporting_evidence and all(e.span.quote for e in g.supporting_evidence) for g in gaps)
    assert all(g.self_support_passed for g in gaps)
    assert all(g.user_state == GapUserState.CANDIDATE.value for g in gaps)
    assert all(g.confidence in {Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW} for g in gaps)
    # a shared "English only" limitation across p1+p2 -> GENERALIZATION_GAP
    assert GapType.GENERALIZATION_GAP in {g.gap_type for g in gaps}


def test_articulation_that_invents_a_claim_is_replaced_by_the_rules_own_words(db, workspace, settings) -> None:
    res = _run(db, workspace, settings, _session(articulate_ok=False))
    # the rule's gaps survive; the invented wording never reaches them
    assert res.gap_count >= 1 and res.rephrased >= 1
    gaps = repo.get_gaps(db, "ws_1")
    assert gaps and all("quantum" not in f"{g.statement} {g.why_unaddressed} {g.proposed_direction}".lower() for g in gaps)
    assert all(g.generator_model is None for g in gaps)


def test_self_support_failure_drops_the_candidate(db, workspace, settings) -> None:
    res = _run(db, workspace, settings, _session(self_support=False))
    assert res.gap_count == 0
    assert res.dropped_self_support >= 1


def test_no_session_yields_no_gaps_because_self_support_cannot_pass(db, workspace, settings) -> None:
    res = _run(db, workspace, settings, None)
    assert res.gap_count == 0
    assert res.dropped_self_support >= 1


def test_rerun_is_deterministic(db, workspace, settings) -> None:
    a = _run(db, workspace, settings, _session())
    first = [g.model_dump(exclude={"generated_at"}) for g in repo.get_gaps(db, "ws_1")]
    b = _run(db, workspace, settings, _session())
    second = [g.model_dump(exclude={"generated_at"}) for g in repo.get_gaps(db, "ws_1")]
    assert a.gap_count == b.gap_count
    assert first == second


def test_rejected_gap_is_not_reproposed_on_rerun(db, workspace, settings) -> None:
    _run(db, workspace, settings, _session())
    gaps = repo.get_gaps(db, "ws_1")
    victim = gaps[0]
    repo.set_gap_user_state(db, victim.gap_id, workspace_id="ws_1", owner_id="usr_1", state=GapUserState.REJECTED)

    res = _run(db, workspace, settings, _session())
    assert res.skipped_rejected >= 1
    surviving = repo.get_gaps(db, "ws_1")
    assert victim.gap_id in {g.gap_id for g in surviving}
    assert next(g for g in surviving if g.gap_id == victim.gap_id).user_state == "rejected"


def test_gap_types_filter_limits_the_pipeline(db, workspace, settings) -> None:
    _run(db, workspace, settings, _session(), gap_types={GapType.GENERALIZATION_GAP})
    assert {g.gap_type for g in repo.get_gaps(db, "ws_1")} <= {GapType.GENERALIZATION_GAP}


def _abstract_only_member(db: Session, ws: ResearchWorkspace, pid: str, abstract: str | None) -> ResearchWorkspace:
    """A discovered paper: no text of its own beyond the abstract, and no profile."""
    db.add(PaperORM(id=pid, title=pid.upper(), title_hash=title_hash(pid), year=2022, abstract=abstract, has_full_text=False))
    db.commit()
    member = WorkspacePaper(workspace_id=ws.workspace_id, paper_id=pid, added_by=AddedBy.TRAIL)
    repo.add_workspace_paper(db, member, "usr_1")
    got = repo.get_workspace(db, ws.workspace_id, "usr_1")
    assert got is not None
    return got


def test_a_paper_without_a_profile_is_profiled_from_its_abstract_and_joins_the_gaps(db, workspace, settings) -> None:
    ws = _abstract_only_member(db, workspace, "p4", "We study dense retrieval for English only corpora.")

    res = _run(db, ws, settings, _session())

    assert (res.profiled, res.unprofiled) == (1, 0)
    profile = repo.get_profile(db, "p4")
    assert profile is not None and profile.grounding == "abstract"
    shared = next(g for g in repo.get_gaps(db, "ws_1") if g.gap_type is GapType.GENERALIZATION_GAP)
    assert set(shared.supporting_papers) == {"p1", "p2", "p4"}
    from_abstract = next(e for e in shared.supporting_evidence if e.paper_id == "p4")
    assert from_abstract.span.section == "Abstract" and from_abstract.span.quote == "English only"
    # two of three papers are backed by full text; the abstract-only one is not
    assert shared.evidence_coverage == pytest.approx(2 / 3, abs=1e-5)


def test_without_a_model_an_unprofiled_paper_is_counted_not_guessed(db, workspace, settings) -> None:
    ws = _abstract_only_member(db, workspace, "p4", "We study dense retrieval for English only corpora.")

    res = _run(db, ws, settings, None)

    assert (res.profiled, res.unprofiled) == (0, 1)
    assert repo.get_profile(db, "p4") is None


def test_a_paper_that_cannot_be_profiled_is_counted_and_nothing_is_stored(db, workspace, settings) -> None:
    ws = _abstract_only_member(db, workspace, "p4", "We study dense retrieval for English only corpora.")
    ws = _abstract_only_member(db, ws, "p5", None)  # no abstract, no text

    res = _run(db, ws, settings, _session(profile_ok=False))

    # p5 has nothing to read; p4's reading failed this time and is tried again next run
    assert (res.profiled, res.unprofiled, res.profile_failed) == (0, 1, 1)
    assert repo.get_profile(db, "p4") is None and repo.get_profile(db, "p5") is None
    assert res.gap_count >= 1  # the profiled papers' gaps still come through


# --- remediation Phase 3: a run that finishes, says why, and keeps decisions ---


def _members(db: Session, ws: ResearchWorkspace, n: int) -> ResearchWorkspace:
    for i in range(n):
        ws = _abstract_only_member(db, ws, f"a{i}", f"We study dense retrieval for English only corpora, variant {i}.")
    return ws


def test_papers_are_read_several_at_a_time_and_each_step_is_reported(db, workspace, settings) -> None:
    ws = _members(db, workspace, 5)
    inner = _session()
    in_flight = {"now": 0, "most": 0}

    class Slow:
        async def chat(self, **kw):  # noqa: ANN003, ANN201
            in_flight["now"] += 1
            in_flight["most"] = max(in_flight["most"], in_flight["now"])
            try:
                await asyncio.sleep(0.02)
                return await inner.client.chat(**kw)
            finally:
                in_flight["now"] -= 1

    session = LlmSession(client=Slow(), api_key="k", model="m", provider=LlmProvider.GROQ)  # type: ignore[arg-type]
    steps: list[dict[str, str]] = []
    res = asyncio.run(
        build_gaps(db, workspace=ws, options=GapBuildOptions(), session=session,
                   settings=settings.model_copy(update={"gap_llm_concurrency": 3}), on_progress=steps.append)
    )

    assert res.profiled == 5
    assert 1 < in_flight["most"] <= 3  # concurrent, and bounded
    stages = [s["stage"] for s in steps]
    assert stages[0] == "profiling" and stages.index("detecting") < stages.index("checking") < stages.index("saving")
    reading = [s for s in steps if s["stage"] == "profiling"]
    assert reading[-1] == {"stage": "profiling", "done": "5", "total": "5"}
    checking = [s for s in steps if s["stage"] == "checking"]
    assert checking[-1]["done"] == checking[-1]["total"]


def test_a_paper_that_is_too_slow_is_counted_and_the_run_goes_on(db, workspace, settings) -> None:
    ws = _members(db, workspace, 2)
    inner = _session()

    class OneSlow:
        async def chat(self, **kw):  # noqa: ANN003, ANN201
            if "variant 0" in kw["messages"][-1].content:
                await asyncio.sleep(5)
            return await inner.client.chat(**kw)

    session = LlmSession(client=OneSlow(), api_key="k", model="m", provider=LlmProvider.GROQ)  # type: ignore[arg-type]
    res = _run(db, ws, settings.model_copy(update={"gap_profile_timeout_s": 0.3}), session)
    assert (res.profiled, res.profile_failed) == (1, 1)
    assert repo.get_profile(db, "a0") is None and repo.get_profile(db, "a1") is not None
    assert res.gap_count >= 1


def _failing(status: int, message: str = "nope") -> LlmSession:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": message}})

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x", model="m", provider=LlmProvider.GROQ,
    )


def test_a_rejected_key_stops_the_run_with_that_reason_and_saves_nothing(db, workspace, settings) -> None:
    from app.llm.client import LlmErrorKind, LlmProviderError

    ws = _members(db, workspace, 2)
    with pytest.raises(LlmProviderError) as info:
        _run(db, ws, settings, _failing(401, "Authentication Fails"))
    assert info.value.kind is LlmErrorKind.AUTH
    assert repo.get_gaps(db, "ws_1") == []


def test_a_provider_that_fails_every_call_is_the_result_not_no_gaps(db, workspace, settings) -> None:
    from app.llm.client import LlmErrorKind, LlmProviderError

    with pytest.raises(LlmProviderError) as info:
        _run(db, workspace, settings, _failing(503, "Server overloaded"))
    assert info.value.kind is LlmErrorKind.UNAVAILABLE


def test_one_candidate_whose_check_fails_is_counted_and_the_others_are_kept(db, workspace, settings) -> None:
    inner = _session()

    class FlakyOnce:
        async def chat(self, **kw):  # noqa: ANN003, ANN201
            from app.llm.client import LlmProviderError

            if "contrastive pretraining" in kw["messages"][-1].content and "phrase a research gap" in kw["messages"][0].content:
                raise LlmProviderError("groq answered 503", provider="groq")
            return await inner.client.chat(**kw)

    session = LlmSession(client=FlakyOnce(), api_key="k", model="m", provider=LlmProvider.GROQ)  # type: ignore[arg-type]
    res = _run(db, workspace, settings, session)
    assert res.unchecked >= 1 and res.gap_count >= 1


def test_decisions_hold_when_a_later_run_finds_the_gap_with_more_papers(db, workspace, settings) -> None:
    """A gap's id changes when one more paper supports it (later runs profile
    more papers): the decision is recognised by what the gap says."""
    _run(db, workspace, settings, _session())
    by_type = {g.gap_type: g for g in repo.get_gaps(db, "ws_1")}
    shared = by_type[GapType.GENERALIZATION_GAP]
    method = by_type[GapType.METHOD_GAP]
    repo.set_gap_user_state(db, shared.gap_id, workspace_id="ws_1", owner_id="usr_1", state=GapUserState.ACCEPTED)
    repo.set_gap_user_state(db, method.gap_id, workspace_id="ws_1", owner_id="usr_1", state=GapUserState.REJECTED)

    # a new paper shares the problem and the limitation: both gaps now have one more paper
    ws = _members(db, workspace, 1)
    calls: list[str] = []
    inner = _session()

    class Recording:
        async def chat(self, **kw):  # noqa: ANN003, ANN201
            calls.append(kw["messages"][-1].content)
            return await inner.client.chat(**kw)

    session = LlmSession(client=Recording(), api_key="k", model="m", provider=LlmProvider.GROQ)  # type: ignore[arg-type]
    res = _run(db, ws, settings, session)

    assert res.kept_accepted >= 1 and res.skipped_rejected >= 1
    gaps = repo.get_gaps(db, "ws_1")
    limitation = [g for g in gaps if g.gap_type is GapType.GENERALIZATION_GAP]
    assert [(g.gap_id, g.user_state) for g in limitation] == [(shared.gap_id, "accepted")]  # no duplicate
    assert [g.user_state for g in gaps if g.affected_methods == method.affected_methods] == ["rejected"]
    # decided gaps cost no model call: nothing phrased or checked the English-only limitation again
    assert not any("English only" in c and "FACTS" in c for c in calls)


def test_the_strongest_rules_are_checked_first_when_a_run_is_capped(db, workspace, settings) -> None:
    res = _run(db, workspace, settings.model_copy(update={"gap_max_candidates_per_run": 1}), _session())
    assert res.not_checked >= 1
    assert [g.detection_rule for g in repo.get_gaps(db, "ws_1")] == ["shared_limitation"]


def test_the_checker_reads_the_rules_own_facts_for_a_gap_that_is_an_absence(db, workspace, settings) -> None:
    """A quote can't show that papers *don't* use a method; the rule's
    comparison of the profiles can."""
    inner = _session()
    checked: list[str] = []

    class Verifier:
        async def chat(self, **kw):  # noqa: ANN003, ANN201
            body = kw["messages"][-1].content
            if "fully supports the statement" in kw["messages"][0].content:
                checked.append(body)
            return await inner.client.chat(**kw)

    session = LlmSession(client=Verifier(), api_key="k", model="m", provider=LlmProvider.GROQ)  # type: ignore[arg-type]
    _run(db, workspace, settings, session)
    method_check = next(c for c in checked if "contrastive pretraining" in c)
    assert "is not listed as a method of any of these papers" in method_check
    assert '"P1"' in method_check and '"P2"' in method_check  # named by title

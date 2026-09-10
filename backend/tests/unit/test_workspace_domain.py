from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.profile import Confidence
from app.domain.ranking import RankedPaper, RankingExplanation, SignalScores
from app.domain.workspace import (
    AddedBy,
    Grounding,
    ResearchWorkspace,
    WorkspacePaper,
    WorkspacePaperRole,
)


def _ws(**kw: object) -> ResearchWorkspace:
    base: dict[str, object] = {
        "workspace_id": "ws_1",
        "owner_id": "usr_1",
        "title": "RAG survey",
        "seed_paper_id": "pap_seed",
        "seed_profile_id": "prof_seed",
    }
    base.update(kw)
    return ResearchWorkspace(**base)  # type: ignore[arg-type]


def _wp(**kw: object) -> WorkspacePaper:
    base: dict[str, object] = {
        "workspace_id": "ws_1",
        "paper_id": "pap_x",
        "added_by": AddedBy.MANUAL,
    }
    base.update(kw)
    return WorkspacePaper(**base)  # type: ignore[arg-type]


def test_enum_values_match_the_data_model_vocabulary() -> None:
    assert {r.value for r in WorkspacePaperRole} == {"seed", "related"}
    assert {a.value for a in AddedBy} == {"trail", "manual"}
    assert {g.value for g in Grounding} == {"full_text", "abstract"}


def test_workspace_paper_defaults() -> None:
    wp = _wp()
    assert wp.role is WorkspacePaperRole.RELATED
    assert wp.grounding is Grounding.ABSTRACT
    assert wp.pinned is False
    assert wp.tags == []
    assert wp.note is None
    assert wp.order == 0
    assert wp.ranking_snapshot is None
    assert wp.added_at is not None


def test_workspace_defaults() -> None:
    ws = _ws()
    assert ws.papers == []
    assert ws.token_budget_usd == 5.0
    assert ws.tokens_used.prompt == 0 and ws.tokens_used.completion == 0
    assert ws.cost_used_usd == 0.0
    assert ws.combined_index_path is None
    assert ws.source_run_id is None


def test_title_must_not_be_blank() -> None:
    with pytest.raises(ValidationError):
        _ws(title="   ")


def test_tags_are_stripped_deduped_and_order_preserved() -> None:
    wp = _wp(tags=[" rag ", "rag", "retrieval", "", "  ", "retrieval", "eval"])
    assert wp.tags == ["rag", "retrieval", "eval"]


def test_paper_lookup_and_related_papers_helpers() -> None:
    seed = _wp(paper_id="pap_seed", role=WorkspacePaperRole.SEED, added_by=AddedBy.MANUAL)
    a = _wp(paper_id="pap_a")
    b = _wp(paper_id="pap_b", pinned=True)
    ws = _ws(papers=[seed, a, b])
    assert ws.paper("pap_a") is a
    assert ws.paper("pap_missing") is None
    assert [p.paper_id for p in ws.related_papers] == ["pap_a", "pap_b"]


def test_ranking_snapshot_round_trips_a_ranked_paper() -> None:
    snap = RankedPaper(
        candidate_id="cand_1",
        signals=SignalScores(semantic_doc=0.8),
        weights_version="w0-initial",
        fused_score=0.8,
        rerank_score=None,
        final_rank=1,
        band=Confidence.HIGH,
        explanation=RankingExplanation(bullet_reasons=["b"], prose="p", signals_used=["semantic_doc"]),
    )
    wp = _wp(ranking_snapshot=snap)
    dumped = wp.model_dump(mode="json")
    restored = WorkspacePaper.model_validate(dumped)
    assert restored.ranking_snapshot is not None
    assert restored.ranking_snapshot.final_rank == 1
    assert restored.ranking_snapshot.band is Confidence.HIGH

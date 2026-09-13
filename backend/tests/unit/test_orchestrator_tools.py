from __future__ import annotations

from app.domain.orchestrator import StageName
from app.services.orchestrator.tools import (
    FIXED_STAGE_ORDER,
    STAGE_PREREQUISITE,
    TOOL_REGISTRY,
)


def test_fixed_stage_order_matches_the_documented_pipeline() -> None:
    assert FIXED_STAGE_ORDER == (
        StageName.INGEST, StageName.PROFILE, StageName.DISCOVERY, StageName.RANKING,
        StageName.TRAIL, StageName.WORKSPACE, StageName.RAG, StageName.COMPARISON,
        StageName.GAPS, StageName.DIRECTIONS, StageName.CITATIONS,
    )


def test_fixed_stage_order_is_a_tuple_not_a_mutable_list() -> None:
    # "the plan is a fixed DAG (no runtime node creation)" -- a tuple can't
    # grow at runtime the way a list could.
    assert isinstance(FIXED_STAGE_ORDER, tuple)


def test_every_stage_appears_exactly_once_in_the_fixed_order() -> None:
    assert len(FIXED_STAGE_ORDER) == len(set(FIXED_STAGE_ORDER)) == len(StageName)


def test_tool_registry_has_an_entry_for_every_stage() -> None:
    assert set(TOOL_REGISTRY) == set(StageName)


def test_tool_registry_entries_are_typed() -> None:
    for stage, tool in TOOL_REGISTRY.items():
        assert tool.name is stage
        assert tool.input_type
        assert tool.output_type
        assert tool.description


def test_every_stage_except_ingest_has_a_prerequisite() -> None:
    assert STAGE_PREREQUISITE[StageName.INGEST] is None
    for stage in StageName:
        if stage is StageName.INGEST:
            continue
        assert STAGE_PREREQUISITE[stage] is not None


def test_prerequisites_only_reference_earlier_stages_in_fixed_order() -> None:
    position = {s: i for i, s in enumerate(FIXED_STAGE_ORDER)}
    for stage, prereq in STAGE_PREREQUISITE.items():
        if prereq is None:
            continue
        assert position[prereq] < position[stage]

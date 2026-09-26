"""Direction workflow orchestration (Architecture §4 `DirectionGenerator`;
Roadmap Phase 12).

Directions are generated **only** from gaps whose `user_state` is
`"accepted"` -- never from a `candidate` or `rejected` gap, and (defensively
-- Phase 11 never persists one) never from a gap whose
`self_support_passed` is `False`. Fixed order per requested `gap_id`:

    load gap (must be accepted + self-supported, else SKIP)
      -> LLM generate (grounded, or DROP)
      -> LLM critique
      -> deterministic confidence band
      -> persist as user_state="candidate"

`direction_id` is derived from `(workspace, gap, suggested_method,
proposal)` so a rerun with the same LLM output upserts the same rows; a
`rejected` direction is preserved (`repo.save_directions`), matching the
Phase 7 / Phase 11 rerun-determinism pattern.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.domain.direction import ResearchDirection
from app.domain.gap import GapUserState
from app.domain.workspace import ResearchWorkspace
from app.llm.session import LlmSession
from app.services.directions.confidence import assign_confidence
from app.services.directions.critique import critique_direction
from app.services.directions.generate import generate_directions
from app.services.gaps.matrix import norm


@dataclass
class DirectionBuildResult:
    workspace_id: str
    requested: int = 0
    direction_count: int = 0
    skipped_not_accepted: int = 0
    skipped_not_found: int = 0
    dropped_unsupported: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _direction_id(workspace_id: str, gap_id: str, suggested_method: str, proposal: str) -> str:
    raw = f"{workspace_id}|{gap_id}|{norm(suggested_method)}|{norm(proposal)[:80]}"
    return f"dir_{hashlib.sha256(raw.encode()).hexdigest()[:20]}"


async def build_directions(
    db: Session,
    *,
    workspace: ResearchWorkspace,
    gap_ids: list[str],
    session: LlmSession | None,
    settings: Settings,
) -> DirectionBuildResult:
    result = DirectionBuildResult(workspace_id=workspace.workspace_id, requested=len(gap_ids))
    directions: list[ResearchDirection] = []
    regenerated: list[str] = []  # the gaps whose candidate directions this run replaces

    for gap_id in gap_ids:
        gap = repo.get_gap(db, gap_id, workspace_id=workspace.workspace_id)
        if gap is None:
            result.skipped_not_found += 1
            continue
        if gap.user_state != GapUserState.ACCEPTED.value or not gap.self_support_passed:
            result.skipped_not_accepted += 1
            continue
        regenerated.append(gap_id)

        gen = await generate_directions(session, gap, max_directions=settings.direction_max_per_gap)
        result.dropped_unsupported += gen.dropped_unsupported
        result.prompt_tokens += gen.prompt_tokens
        result.completion_tokens += gen.completion_tokens

        for draft in gen.drafts:
            critique, pt, ct = await critique_direction(session, draft)
            result.prompt_tokens += pt
            result.completion_tokens += ct
            confidence, basis = assign_confidence(draft.kind, critique, gap)
            directions.append(
                ResearchDirection(
                    direction_id=_direction_id(workspace.workspace_id, gap_id, draft.suggested_method, draft.proposal),
                    workspace_id=workspace.workspace_id,
                    gap_id=gap_id,
                    proposal=draft.proposal,
                    motivation=draft.motivation,
                    supporting_evidence=list(gap.supporting_evidence),
                    related_papers=list(gap.supporting_papers),
                    suggested_method=draft.suggested_method,
                    possible_dataset=draft.possible_dataset,
                    evaluation_strategy=draft.evaluation_strategy,
                    risks=list(draft.risks),
                    kind=draft.kind,
                    critique=critique,
                    confidence=confidence,
                    confidence_basis=basis,
                    flags=["low_critique"] if basis.get("low_critique") else [],
                    generator_model=draft.generator_model,
                )
            )

    repo.save_directions(db, workspace.workspace_id, directions, owner_id=workspace.owner_id, gap_ids=regenerated)
    result.direction_count = len(directions)
    return result

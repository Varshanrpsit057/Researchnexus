"""Self-support check + deterministic confidence band (Architecture §1.1
"Gap: self-support check ... uses rag/verify.py" and "Gap: confidence band
... Deterministic ... bands only, never invented %"; Roadmap Phase 11).

`self_support_check` reuses the Phase 9 `IsSupported?` verifier over
(statement, evidence quotes). A candidate whose statement is not entailed
by its own evidence is dropped by the pipeline (`self_support_passed=false
-> dropped`). No session -> unsupported (safe default).

`assign_confidence` returns a `Confidence` **enum** (never a number) and
the `confidence_basis` dict it was derived from. Calibrated probabilities
are Phase 16.
"""

from __future__ import annotations

from app.domain.gap import GapType
from app.domain.profile import Confidence
from app.llm.session import LlmSession
from app.services.gaps.candidates import GapCandidate
from app.services.rag.generate import DraftSentence
from app.services.rag.verify import verify_sentences

_STRONG_TYPES = {GapType.CONTRADICTION}


async def self_support_check(
    session: LlmSession | None, statement: str, quotes: list[str]
) -> bool:
    if session is None or not quotes or not statement.strip():
        return False
    draft = [DraftSentence(text=statement, chunk_ids=[f"ev{i}" for i in range(len(quotes))])]
    chunk_text = {f"ev{i}": q for i, q in enumerate(quotes)}
    verified, _pt, _ct = await verify_sentences(session, draft, chunk_text)
    return bool(verified) and verified[0].is_supported


def assign_confidence(
    candidate: GapCandidate, *, self_support_passed: bool, evidence_coverage: float
) -> tuple[Confidence, dict]:
    n = len(set(candidate.supporting_papers))
    limitation_agreement = bool(candidate.facts.get("limitation_agreement"))
    recency = "stale" if candidate.gap_type is GapType.TEMPORAL_GAP else "unknown"
    basis: dict = {
        "n_supporting": n,
        "limitation_agreement": limitation_agreement,
        "recency": recency,
        "self_support": self_support_passed,
        "evidence_coverage": round(evidence_coverage, 3),
        "detection_rule": candidate.detection_rule,
    }
    if not self_support_passed:
        return Confidence.LOW, basis

    strong = limitation_agreement or candidate.gap_type in _STRONG_TYPES
    if n >= 3 and evidence_coverage >= 0.66 and (strong or n >= 4):
        return Confidence.HIGH, basis
    if n >= 2 and evidence_coverage >= 0.33:
        return Confidence.MEDIUM, basis
    return Confidence.LOW, basis

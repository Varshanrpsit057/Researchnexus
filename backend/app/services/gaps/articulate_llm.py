"""Constrained gap articulation (Architecture §1.1 "Gap: constrained
articulation ... LLM (structured) ... may only phrase statement +
why-unaddressed + direction; no new claims"; Roadmap Phase 11).

The LLM is handed the deterministic `facts` a rule produced plus the
verbatim evidence quotes, and asked to phrase three short strings. On the
way out `is_grounded` runs a deterministic check: any *long technical
term* (>= 8 chars, not generic research vocabulary) in `statement` /
`why_unaddressed` must already appear in the facts or an evidence quote.
An adversarial LLM that names an invented method / dataset / technique
("quantum annealing", "reinforcement learning") is caught here and the
candidate is dropped; a short acronym that slips past is still caught by
the downstream Self-RAG self-support check (`confidence.self_support_check`).

No session -> a deterministic template built straight from the facts
(`generator_model=None`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel

from app.llm.session import LlmSession
from app.services.gaps.candidates import GapCandidate
from app.services.gaps.matrix import norm
from app.services.rag._llm import chat_json

_LONG_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9-]{7,}")

# long words the articulation is always free to use -- meta-vocabulary and
# ordinary long English words, never "the invented method".
_ALLOWED_LONG = {
    "workspace", "workspaces", "research", "approach", "approaches", "benchmark", "benchmarks",
    "baseline", "baselines", "evaluation", "evaluations", "experiment", "experiments", "comparison",
    "comparisons", "limitation", "limitations", "generalize", "generalise", "generalization",
    "generalisation", "separately", "controlled", "together", "directly", "reconcile", "reconciled",
    "addressed", "addresses", "unaddressed", "resolves", "resolved", "reported", "reports", "observed",
    "described", "following", "previous", "several", "various", "different", "difference", "differences",
    "therefore", "however", "additional", "remaining", "particular", "specific", "existing", "proposed",
    "combined", "combining", "combination", "combinations", "revisited", "revisit", "problem", "problems",
    "setting", "settings", "context", "consistent", "consistently", "conflicting", "conflict",
    "identical", "overlap", "overlapping", "coverage", "recently",
}


class _Articulation(BaseModel):
    statement: str = ""
    why_unaddressed: str = ""
    proposed_direction: str = ""


@dataclass
class Articulation:
    statement: str
    why_unaddressed: str
    proposed_direction: str
    generator_model: str | None


_SYSTEM = (
    "You phrase a research gap that a deterministic rule already found. You are "
    "given FACTS and verbatim EVIDENCE quotes. Return JSON: "
    '{"statement":"<one sentence>","why_unaddressed":"<one sentence>",'
    '"proposed_direction":"<one short sentence>"}. Use ONLY terms that appear '
    "in the FACTS or the EVIDENCE. Do not name any method, dataset, metric or "
    "result that is not in them. Do not add numbers."
)


def _flatten(obj: object) -> list[object]:
    if isinstance(obj, dict):
        return [x for v in obj.values() for x in _flatten(v)]
    if isinstance(obj, (list, tuple, set)):
        return [x for v in obj for x in _flatten(v)]
    return [obj]


def _allowed_text(candidate: GapCandidate) -> str:
    parts: list[str] = list(candidate.affected_methods) + list(candidate.affected_datasets)
    parts += [str(v) for v in _flatten(candidate.facts)]
    parts += [e.span.quote for e in candidate.supporting_evidence]
    parts += [e.span.quote for e in candidate.conflicting_evidence]
    return norm(" ".join(parts))


def _unsupported_terms(text: str, allowed: str) -> set[str]:
    out: set[str] = set()
    for tok in _LONG_TOKEN.findall(text):
        low = tok.lower()
        if low in _ALLOWED_LONG:
            continue
        if low not in allowed:
            out.add(low)
    return out


def is_grounded(statement: str, why_unaddressed: str, candidate: GapCandidate) -> bool:
    allowed = _allowed_text(candidate)
    return not _unsupported_terms(f"{statement} {why_unaddressed}", allowed)


def _template(candidate: GapCandidate) -> Articulation:
    f = candidate.facts
    gt = candidate.gap_type.value
    n_sup = len(candidate.supporting_papers)
    if candidate.affected_methods and f.get("facet") == "method":
        value = candidate.affected_methods[0]
        statement = f"No workspace paper applies {value} to the research problem shared by {n_sup} of the papers."
        why = f"The {n_sup} papers addressing that shared problem do not adopt {value}."
        direction = f"Evaluate {value} on the shared problem setting."
    elif candidate.affected_methods and candidate.affected_datasets:
        statement = f"No workspace paper combines {candidate.affected_methods[0]} with {candidate.affected_datasets[0]}."
        why = f"{candidate.affected_methods[0]} and {candidate.affected_datasets[0]} are each used by separate papers, never together."
        direction = f"Apply {candidate.affected_methods[0]} on {candidate.affected_datasets[0]}."
    elif f.get("facet") in {"dataset", "metric"}:
        statement = f"The {n_sup} papers share no common {f['facet']}, so their results are not directly comparable."
        why = f"Each of the {n_sup} papers reports a different {f['facet']}."
        direction = f"Adopt a shared {f['facet']} across these papers."
    elif f.get("facet") == "limitation":
        statement = f"{n_sup} papers report the same limitation and none of the workspace papers resolves it."
        why = f"The limitation is stated by {n_sup} papers but addressed by none."
        direction = "Design an approach that removes this shared limitation."
    elif candidate.gap_type.value == "TEMPORAL_GAP":
        statement = f"A topic studied by {n_sup} papers has not been revisited in {f.get('gap_years', 'several')} years."
        why = "No recent workspace paper returns to this topic."
        direction = "Revisit the topic with current methods."
    else:
        statement = f"Two workspace papers make conflicting claims that no paper resolves ({gt})."
        why = "The conflicting claims are stated but not reconciled by any paper."
        direction = "Run a controlled comparison to resolve the conflict."
    return Articulation(statement=statement, why_unaddressed=why, proposed_direction=direction, generator_model=None)


async def articulate(session: LlmSession | None, candidate: GapCandidate) -> Articulation | None:
    if session is None:
        return _template(candidate)

    user = (
        f"FACTS: {candidate.facts}\n\nEVIDENCE:\n"
        + "\n".join(f"- ({e.paper_id}) {e.span.quote}" for e in candidate.supporting_evidence)
        + "".join(f"\n- CONFLICT ({e.paper_id}) {e.span.quote}" for e in candidate.conflicting_evidence)
    )
    parsed, _pt, _ct = await chat_json(session, _SYSTEM, user, _Articulation)
    if parsed is None:
        return _template(candidate)
    assert isinstance(parsed, _Articulation)
    statement = parsed.statement.strip()
    why = parsed.why_unaddressed.strip()
    if not statement:
        return _template(candidate)
    if not is_grounded(statement, why, candidate):
        return None  # LLM introduced an unsupported claim -> drop the candidate
    return Articulation(
        statement=statement,
        why_unaddressed=why or "The evidence states this but no paper addresses it.",
        proposed_direction=parsed.proposed_direction.strip() or "Investigate this gap directly.",
        generator_model=session.model,
    )

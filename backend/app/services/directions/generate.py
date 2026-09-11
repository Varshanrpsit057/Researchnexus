"""Constrained direction generation (Architecture §4 `DirectionGenerator`:
"LLM generate -> LLM critique"; Roadmap Phase 12).

Directions are only ever generated from an **accepted** `ResearchGap`
(enforced by the caller, `services/directions/pipeline.py`) and inherit its
evidence spans verbatim. The LLM proposes `proposal` / `motivation` /
`suggested_method` / `possible_dataset` / `evaluation_strategy` / `risks`;
a deterministic grounding check on `proposal` + `motivation` rejects any
long technical term that is neither in the gap's own grounding vocabulary
nor this draft's own `suggested_method` / `possible_dataset` -- the LLM may
propose *one* new method/dataset (that is the point of a direction) but may
not smuggle in an extra unsupported technical claim.

`kind` is deterministic: `evidence_backed_inference` when the proposed
method/dataset is already named by the gap itself (its `affected_methods`/
`affected_datasets`, statement, or evidence quotes); `llm_hypothesis` when
it is genuinely new.

No session, or a malformed/failed LLM call, -> exactly one deterministic
direction built from the gap's own `proposed_direction` / `why_unaddressed`
(Phase 11 produced them for this purpose) -- always grounded, always
`evidence_backed_inference`. A syntactically valid but *ungrounded* LLM
draft is dropped outright, not replaced by the template -- that would mask
the failure as a success.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.domain.gap import ResearchGap
from app.llm.session import LlmSession
from app.services.gaps.matrix import norm
from app.services.rag._llm import chat_json

_LONG_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9-]{7,}")

# Same meta-vocabulary as services/gaps/articulate_llm.py, plus words a
# forward-looking research suggestion legitimately needs.
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
    "identical", "overlap", "overlapping", "coverage", "recently", "suggest", "suggests", "suggested",
    "explore", "explores", "exploring", "applying", "applies", "applied", "extend", "extending",
    "investigate", "investigating", "measure", "measuring", "measured", "outcome", "outcomes",
    "protocol", "protocols", "strategy", "strategies", "hypothesis", "hypotheses", "possible", "feasible",
}


class _DraftItem(BaseModel):
    proposal: str = ""
    motivation: str = ""
    suggested_method: str = ""
    possible_dataset: str | None = None
    evaluation_strategy: str = ""
    risks: list[str] = Field(default_factory=list)


class _Drafts(BaseModel):
    directions: list[_DraftItem] = Field(default_factory=list)


@dataclass
class DirectionDraft:
    proposal: str
    motivation: str
    suggested_method: str
    possible_dataset: str | None
    evaluation_strategy: str
    risks: list[str]
    kind: str
    generator_model: str | None


@dataclass
class GenerateResult:
    drafts: list[DirectionDraft] = field(default_factory=list)
    dropped_unsupported: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


_SYSTEM_TEMPLATE = (
    "A research gap was found in a workspace of papers. Propose up to {n} concrete "
    "next-step research directions that would help fill it. For each, give: proposal "
    "(one sentence), motivation (one sentence citing why, from the GAP only), "
    "suggested_method (a short name), possible_dataset (short name or null), "
    "evaluation_strategy (one sentence), risks (1-2 short strings). Return JSON: "
    '{{"directions":[{{"proposal":"...","motivation":"...","suggested_method":"...",'
    '"possible_dataset":"..."|null,"evaluation_strategy":"...","risks":["..."]}}]}}. '
    "The motivation may ONLY restate facts from the GAP -- it must not assert anything "
    "about the papers beyond what the GAP already states."
)


def _gap_grounding_text(gap: ResearchGap) -> str:
    parts = list(gap.affected_methods) + list(gap.affected_datasets)
    parts += [gap.statement, gap.why_unaddressed, gap.proposed_direction]
    parts += [e.span.quote for e in gap.supporting_evidence]
    parts += [e.span.quote for e in gap.conflicting_evidence]
    return norm(" ".join(parts))


def _unsupported_terms(text: str, allowed: str) -> set[str]:
    out: set[str] = set()
    for tok in _LONG_TOKEN.findall(text):
        low = tok.lower()
        if low in _ALLOWED_LONG or low in allowed:
            continue
        out.add(low)
    return out


def _classify_kind(suggested_method: str, possible_dataset: str | None, gap_text: str) -> str:
    terms = [norm(suggested_method)]
    if possible_dataset:
        terms.append(norm(possible_dataset))
    terms = [t for t in terms if t]
    if terms and all(t in gap_text for t in terms):
        return "evidence_backed_inference"
    return "llm_hypothesis"


def _template(gap: ResearchGap) -> DirectionDraft:
    method = gap.affected_methods[0] if gap.affected_methods else ""
    dataset = gap.affected_datasets[0] if gap.affected_datasets else None
    n = len(gap.supporting_papers)
    return DirectionDraft(
        proposal=gap.proposed_direction or f"Address the gap: {gap.statement}",
        motivation=gap.why_unaddressed or gap.statement,
        suggested_method=method,
        possible_dataset=dataset,
        evaluation_strategy=f"Evaluate on the setting shared by the {n} supporting papers.",
        risks=["Feasibility has not yet been assessed."],
        kind="evidence_backed_inference",
        generator_model=None,
    )


async def generate_directions(
    session: LlmSession | None, gap: ResearchGap, *, max_directions: int
) -> GenerateResult:
    if session is None:
        return GenerateResult(drafts=[_template(gap)])

    gap_text = _gap_grounding_text(gap)
    user = (
        f"GAP: {gap.statement}\nWHY_UNADDRESSED: {gap.why_unaddressed}\n"
        f"AFFECTED_METHODS: {gap.affected_methods}\nAFFECTED_DATASETS: {gap.affected_datasets}\n\n"
        "EVIDENCE:\n" + "\n".join(f"- ({e.paper_id}) {e.span.quote}" for e in gap.supporting_evidence)
    )
    parsed, pt, ct = await chat_json(session, _SYSTEM_TEMPLATE.format(n=max_directions), user, _Drafts)
    result = GenerateResult(prompt_tokens=pt, completion_tokens=ct)
    if parsed is None:
        result.drafts = [_template(gap)]
        return result
    assert isinstance(parsed, _Drafts)

    for item in parsed.directions[:max_directions]:
        proposal = item.proposal.strip()
        motivation = item.motivation.strip()
        if not proposal or not motivation:
            continue
        kind = _classify_kind(item.suggested_method, item.possible_dataset, gap_text)
        allowed = gap_text
        if item.suggested_method:
            allowed = norm(f"{allowed} {item.suggested_method}")
        if item.possible_dataset:
            allowed = norm(f"{allowed} {item.possible_dataset}")
        if _unsupported_terms(f"{proposal} {motivation}", allowed):
            result.dropped_unsupported += 1
            continue
        result.drafts.append(
            DirectionDraft(
                proposal=proposal,
                motivation=motivation,
                suggested_method=item.suggested_method.strip(),
                possible_dataset=(item.possible_dataset or "").strip() or None,
                evaluation_strategy=item.evaluation_strategy.strip() or "Not yet specified.",
                risks=[r.strip() for r in item.risks if r.strip()] or ["Feasibility has not yet been assessed."],
                kind=kind,
                generator_model=session.model,
            )
        )
    return result

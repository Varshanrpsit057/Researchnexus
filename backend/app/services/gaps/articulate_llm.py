"""Constrained gap articulation (Architecture §1.1 "Gap: constrained
articulation ... LLM (structured) ... may only phrase statement +
why-unaddressed + direction; no new claims"; Roadmap Phase 11).

The LLM is handed the deterministic `facts` a rule produced plus the
verbatim evidence quotes, and asked to phrase three short strings. On the
way out `is_grounded` runs a deterministic check: any *long term* (>= 8
chars) in `statement` / `why_unaddressed` must already appear in the facts
or an evidence quote -- a technical-looking one (CamelCase, a digit, a
hyphen) verbatim, a plain word by its stem -- unless it is ordinary English
used to phrase a gap ("adopting", "describe", "addressing"). An adversarial
LLM that names an invented method / dataset / technique ("quantum
annealing", "reinforcement learning") is caught here; a short acronym that
slips past is still caught by the downstream Self-RAG self-support check
(`confidence.self_support_check`).

What happens then: the model's wording is discarded, never the gap. The
rule found the gap and its evidence deterministically; the deterministic
template phrases exactly that (`fallback="ungrounded"`). Measured on a real
workspace, the old "drop the candidate" policy -- with plain words like
"adopting" counted as invented terms -- discarded every candidate.

No session, or no usable reply -> the same template (`generator_model=None`).
With `strict=True` a provider failure is raised instead of hidden, so a
run can say the key was rejected rather than "no gaps".
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
# an inner capital (ResNet, ArcFace), a digit (YOLOv7), a hyphen (t-SNE):
# the shape of a named method, dataset or metric
_TECHNICAL = re.compile(r"^.+[A-Z]|\d|-")
_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ied", "ies", "ed", "es", "s", "ly")

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
    # flagged on a real run: words about the gap itself, not new claims
    "evidence", "outcome", "outcomes", "comparable", "comparability", "measurement", "measurements",
    "reproducibility", "consistency", "distinct", "distinctly", "independent", "independently",
    "numerous", "respective", "isolated", "unrelated", "diverse", "varying", "inconsistent",
    "considerable", "substantial", "relatively", "notably", "especially",
}

# ordinary English a gap is phrased with -- the words a real run flagged as
# "invented", and their kin; matched by stem, so "adopting" covers "adopted"
_PLAIN_WORDS = {
    "absence", "although", "addressing", "adopting", "adoption", "analysing", "analyzing", "analysis",
    "applying", "application", "assessing", "assessment", "available", "building", "capability",
    "checking", "commonly", "compared", "comparing", "complete", "considering", "currently",
    "demonstrate", "describe", "describing", "designed", "determine", "developing", "development",
    "discussing", "effective", "effectiveness", "enabling", "evaluate", "evaluating", "examining",
    "experience", "explicitly", "exploring", "extending", "extension", "focusing", "furthermore",
    "handling", "implement", "implementation", "improve", "improving", "improvement", "including",
    "incorporate", "incorporating", "indicate", "individual", "integrate", "integrating", "integration",
    "investigate", "investigating", "investigation", "involving", "measuring", "mentioned", "missing",
    "moreover", "multiple", "necessary", "otherwise", "performance", "performing", "possible",
    "potential", "potentially", "practical", "presence", "presenting", "primarily", "provide",
    "providing", "published", "question", "regarding", "relevant", "relying", "reporting", "requiring",
    "respectively", "scenario", "significant", "similarly", "specifically", "standard", "strategy",
    "studying", "suggest", "systematic", "systematically", "targeted", "technique", "throughout",
    "typically", "understanding", "unexplored", "untested", "validate", "validation", "variation",
    "whereas", "whether", "without", "combines", "examines", "explores", "lacking", "remains",
    "sharing", "instead", "between", "further", "whereby", "neither", "specific", "underexplored",
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
    # why the rule's template phrased it: "no_reply" or "ungrounded"; None when the model did
    fallback: str | None = None


_SYSTEM = (
    "You phrase a research gap that a deterministic rule already found. You are "
    "given FACTS and verbatim EVIDENCE quotes. Return JSON: "
    '{"statement":"<one sentence, at most 30 words>","why_unaddressed":"<one sentence>",'
    '"proposed_direction":"<one short sentence>"}. Name at most two examples; '
    "the evidence lists the rest. The statement must say what "
    "the papers do NOT do or do not share, as the FACTS establish -- a gap, not "
    "a description of what one paper does. Use ONLY terms that appear "
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


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 5:
            word = word[: -len(suffix)]
            break
    # "experience" and "experiences", "describe" and "described", share one stem
    return word[:-1] if word.endswith("e") and len(word) > 5 else word


_PLAIN_STEMS = {_stem(w) for w in _PLAIN_WORDS}


def _unsupported_terms(text: str, allowed: str) -> set[str]:
    out: set[str] = set()
    for tok in _LONG_TOKEN.findall(text):
        low = tok.lower()
        if low in _ALLOWED_LONG or low in allowed:
            continue
        if _TECHNICAL.search(tok):
            out.add(low)  # a named thing must appear as it is written
            continue
        stem = _stem(low)
        if stem in allowed or stem in _PLAIN_STEMS:
            continue
        out.add(low)
    return out


def is_grounded(statement: str, why_unaddressed: str, candidate: GapCandidate) -> bool:
    allowed = _allowed_text(candidate)
    return not _unsupported_terms(f"{statement} {why_unaddressed}", allowed)


def _template(candidate: GapCandidate, fallback: str | None = None) -> Articulation:
    art = _template_text(candidate)
    art.fallback = fallback
    return art


def _clean(value: object) -> str:
    return str(value).strip().rstrip(".;:, ")


def _template_text(candidate: GapCandidate) -> Articulation:
    f = candidate.facts
    gt = candidate.gap_type.value
    n_sup = len(candidate.supporting_papers)
    if candidate.affected_methods and f.get("facet") == "method":
        # the method IS used in the workspace (`used_by`); the gap is the papers sharing its problem
        value = _clean(candidate.affected_methods[0])
        n_used = len(f.get("used_by") or []) or 1
        users = "the paper" if n_used == 1 else f"the {n_used} papers"
        others = "another workspace paper does" if n_used == 1 else f"{n_used} other workspace papers do"
        statement = f"None of the {n_sup} papers that share a research problem with {users} using {value} applies it."
        why = f"The {n_sup} papers addressing that shared problem do not adopt {value}, although {others}."
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


async def articulate(session: LlmSession | None, candidate: GapCandidate, *, strict: bool = False) -> Articulation:
    if session is None:
        return _template(candidate)

    user = (
        f"FACTS: {candidate.facts}\n\nEVIDENCE:\n"
        + "\n".join(f"- ({e.paper_id}) {e.span.quote}" for e in candidate.supporting_evidence)
        + "".join(f"\n- CONFLICT ({e.paper_id}) {e.span.quote}" for e in candidate.conflicting_evidence)
    )
    parsed, _pt, _ct = await chat_json(session, _SYSTEM, user, _Articulation, raise_provider_errors=strict, temperature=0.0)
    if parsed is None:
        return _template(candidate, "no_reply")
    assert isinstance(parsed, _Articulation)
    statement = parsed.statement.strip()
    why = parsed.why_unaddressed.strip()
    if not statement:
        return _template(candidate, "no_reply")
    if not is_grounded(statement, why, candidate):
        return _template(candidate, "ungrounded")  # the wording goes, the rule's gap stays
    return Articulation(
        statement=statement,
        why_unaddressed=why or "The evidence states this but no paper addresses it.",
        proposed_direction=parsed.proposed_direction.strip() or "Investigate this gap directly.",
        generator_model=session.model,
    )
